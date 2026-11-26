// Continue-in-another-agent UI: dialog, drafting into the new terminal, toasts,
// and the usage-limit offer. Pure helpers are exported for node tests; the DOM
// parts only run in the browser.
(function (root) {
  'use strict';

  const ESC = String.fromCharCode(27);
  const PASTE_START = ESC + '[200~';
  const PASTE_END = ESC + '[201~';
  const READY_QUIET_MS = 800;
  const READY_TIMEOUT_MS = 20000;
  const WS_OPEN = 1;

  // Everything a terminal could act on is dropped: ESC (so the text cannot end
  // the paste early), the other C0 controls except newline and tab, DEL, and the
  // C1 range (U+009B is a one-character CSI). A drafted prompt is never submitted.
  const CONTROL_CHARS = new RegExp('[\\u0000-\\u0008\\u000b-\\u001f\\u007f-\\u009f]', 'g');

  function bracketedPaste(text) {
    const clean = String(text).replace(/\r\n?/g, '\n').replace(CONTROL_CHARS, '');
    return PASTE_START + clean + PASTE_END;
  }

  const BRACKETED_ON = ESC + '[?2004h';
  const BRACKETED_OFF = ESC + '[?2004l';
  const BRACKETED_TAIL_CHARS = 8;

  // Tracks whether the program in the terminal has turned bracketed paste on.
  // `prev` is { enabled, tail } from the last chunk; the tail lets a sequence
  // split across two chunks be recognised.
  function trackBracketedPaste(prev, chunk) {
    const before = prev || { enabled: false, tail: '' };
    const text = before.tail + String(chunk);
    const on = text.lastIndexOf(BRACKETED_ON);
    const off = text.lastIndexOf(BRACKETED_OFF);
    return {
      enabled: on === -1 && off === -1 ? !!before.enabled : on > off,
      tail: text.slice(-BRACKETED_TAIL_CHARS),
    };
  }

  // Without bracketed paste the target would read the prompt's newlines as Enter
  // and submit it, so a target that has not enabled it is never ready.
  function isInputReady(s, now) {
    if (!s.bracketedPaste) return false;
    if (!s.outputChars || !s.lastOutputAt) return false;
    if (now - s.lastOutputAt < READY_QUIET_MS) return false;
    if (s.paintedRows < 2) return false;
    if (s.agent === 'opencode-bare' && !s.frameReady) return false;
    return true;
  }

  const SEARCH_THRESHOLD = 6;

  // Sections in display order. The agent being left stays selectable (a fresh
  // context in the same agent is legitimate) but sorts after the others.
  function groupTargets(targets, sourceAgent, query) {
    const q = String(query || '')
      .trim()
      .toLowerCase();
    const matches = targets.filter(
      (t) => !q || t.label.toLowerCase().includes(q) || t.agent.toLowerCase().includes(q),
    );
    const ordered = matches
      .filter((t) => t.agent !== sourceAgent)
      .concat(matches.filter((t) => t.agent === sourceAgent));
    const installed = ordered.filter((t) => t.installed !== false);
    return [
      {
        key: 'routed',
        title: 'Through AI Gator',
        items: installed.filter((t) => t.gateway_routed),
      },
      { key: 'own', title: 'Own configuration', items: installed.filter((t) => !t.gateway_routed) },
      {
        key: 'missing',
        title: 'Not installed',
        items: ordered.filter((t) => t.installed === false),
      },
    ].filter((sec) => sec.items.length);
  }

  const PREVIEW_CHARS = 300;

  // The last message as a single line for the dialog; the CSS ellipsis does the
  // visual truncation, this only collapses newlines and bounds the DOM text.
  function oneLine(text) {
    return String(text || '')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, PREVIEW_CHARS);
  }

  function defaultTarget(targets, sourceAgent) {
    const usable = targets.filter((t) => t.installed !== false);
    const first = groupTargets(usable, sourceAgent, '')
      .flatMap((sec) => sec.items)
      .find((t) => t.agent !== sourceAgent);
    return first || usable[0] || null;
  }

  function errorDetail(body, fallback) {
    return body && typeof body.detail === 'string' && body.detail ? body.detail : fallback;
  }

  function targetWarning(target) {
    return target.gateway_routed
      ? ''
      : 'Runs on its own configuration, outside the AI Gator gateway. ' +
          'The carried-over session goes to that agent’s own provider, ' +
          'without AI Gator’s controls.';
  }

  const REDACTION_NOTE =
    'Secrets are redacted on a best-effort basis. Other sensitive text may remain.';

  // Where Tab goes next inside the dialog, or null when the browser's own
  // order stays within it. Focus that is outside the dialog comes back in.
  function trapTarget(focusables, active, shift) {
    if (!focusables.length) return null;
    const i = focusables.indexOf(active);
    const last = focusables.length - 1;
    if (i === -1) return shift ? focusables[last] : focusables[0];
    if (shift && i === 0) return focusables[last];
    if (!shift && i === last) return focusables[0];
    return null;
  }

  async function waitForReady(sess, probe, opts) {
    const o = opts || {};
    const now = o.now || Date.now;
    const sleep = o.sleep || ((ms) => new Promise((r) => setTimeout(r, ms)));
    const timeoutMs = o.timeoutMs || READY_TIMEOUT_MS;
    const start = now();
    for (;;) {
      if (probe(sess, now())) return true;
      if (now() - start >= timeoutMs) return false;
      await sleep(100);
    }
  }

  async function draftPrompt(sess, prompt, probe, opts) {
    if (!(await waitForReady(sess, probe, opts))) return 'unconfirmed';
    if (!sess.ws || sess.ws.readyState !== WS_OPEN) return 'failed';
    sess.ws.send(JSON.stringify({ type: 'input', data: bracketedPaste(prompt) }));
    return 'delivered';
  }

  function prepareBody(opts, project) {
    const body = {
      agent: opts.sess.agent,
      project_id: project.projectId,
      repo_path: project.repoPath,
    };
    if (opts.stored) body.session_id = opts.stored.id;
    else body.pty_session_id = opts.sess.ptySessionId;
    return body;
  }

  // ── Browser-only below ──────────────────────────────────────────────────
  function agentLabel(agent) {
    return typeof _genAgentLabel === 'function' ? _genAgentLabel(agent) : agent;
  }

  function sessionProbe(sess, now) {
    return isInputReady(
      {
        agent: sess.agent,
        bracketedPaste: !!sess._bracketedPaste,
        outputChars: sess._outputChars,
        lastOutputAt: sess._lastRawOutputAt,
        paintedRows: _genAgentPaintedRowCount(sess),
        frameReady: _genAgentOpenCodeFrameIsReady(sess),
      },
      now,
    );
  }

  function h(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text != null) el.textContent = text;
    return el;
  }

  function toastStack() {
    let stack = document.getElementById('agent-handoff-toasts');
    if (!stack) {
      stack = h('div', 'agent-handoff-toasts');
      stack.id = 'agent-handoff-toasts';
      document.body.appendChild(stack);
    }
    return stack;
  }

  function removeToast(el) {
    const stack = el.parentNode;
    el.remove();
    if (stack && !stack.children.length) stack.remove();
  }

  function showToast(message, tone, actions) {
    const el = h('div', 'agent-handoff-toast agent-handoff-toast-' + tone);
    el.setAttribute('role', 'status');
    el.appendChild(h('span', 'agent-handoff-toast-msg', message));
    (actions || []).forEach((a) => {
      const b = h('button', 'agent-handoff-toast-btn', a.label);
      b.type = 'button';
      b.addEventListener('click', () => {
        removeToast(el);
        if (a.onClick) a.onClick();
      });
      el.appendChild(b);
    });
    const close = h('button', 'agent-handoff-toast-close', '✕');
    close.type = 'button';
    close.title = 'Dismiss';
    close.addEventListener('click', () => removeToast(el));
    el.appendChild(close);
    toastStack().appendChild(el);
    if (tone === 'success') setTimeout(() => removeToast(el), 8000);
    return el;
  }

  function copyPrompt(prompt) {
    navigator.clipboard
      .writeText(prompt)
      .then(() => showToast('Handoff prompt copied.', 'success'))
      .catch(() => showToast('Could not copy the handoff prompt.', 'warn'));
  }

  async function deliver(sess, prompt) {
    const label = agentLabel(sess.agent);
    const copyAction = [{ label: 'Copy prompt', onClick: () => copyPrompt(prompt) }];
    let outcome;
    try {
      outcome = await draftPrompt(sess, prompt, sessionProbe);
    } catch (_) {
      outcome = 'failed';
    }
    if (outcome === 'delivered') {
      showToast('Handoff drafted in ' + label + '. Review it and press Enter to send.', 'success');
    } else if (outcome === 'failed') {
      showToast(
        label + ' terminal connection is closed, so the handoff prompt was not pasted.',
        'warn',
        copyAction,
      );
    } else {
      showToast(
        'Could not confirm ' + label + ' was ready, so the handoff prompt was not pasted.',
        'warn',
        copyAction,
      );
    }
    return outcome;
  }

  let dialogSeq = 0;
  let dialogBusy = false;

  // Whether the terminal module is still starting an agent for this tab.
  function startInFlight(tabId) {
    return typeof _genAgentStartInFlight === 'function' && !!_genAgentStartInFlight(tabId);
  }

  function renderDialog(prep, sess, state, tabId, project) {
    dialogSeq += 1;
    const listId = 'agent-handoff-list-' + dialogSeq;
    const overlay = h('div', 'agent-handoff-overlay');
    const box = h('div', 'agent-handoff-dialog');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    const opener = document.activeElement;
    const heading = h('h3', null, 'Hand off to another agent');
    heading.id = 'agent-handoff-title-' + dialogSeq;
    box.setAttribute('aria-labelledby', heading.id);
    box.appendChild(heading);

    // What travels: secondary context, kept compact so the choice below leads.
    const kb = Math.max(1, Math.round(prep.snapshot_bytes / 1024));
    const carry = h('div', 'agent-handoff-carry');
    carry.appendChild(h('div', 'agent-handoff-label', 'Carrying over'));
    const from = h('div', 'agent-handoff-from');
    if (typeof _genAgentTabIcon === 'function') from.appendChild(_genAgentTabIcon(sess.agent));
    let meta =
      agentLabel(sess.agent) +
      ' · ' +
      (prep.source_kind === 'transcript' ? 'transcript' : 'terminal capture') +
      ' · ' +
      kb +
      ' KB';
    if (prep.redactions) meta += ' · ' + prep.redactions + ' secret(s) redacted';
    from.appendChild(h('span', 'agent-handoff-meta', meta));
    carry.appendChild(from);
    carry.appendChild(h('div', 'agent-handoff-redaction-note', REDACTION_NOTE));
    const lastLine = oneLine(prep.last_user_message);
    if (lastLine) {
      const last = h('div', 'agent-handoff-last');
      last.appendChild(h('span', 'agent-handoff-last-key', 'Last message'));
      last.appendChild(h('span', 'agent-handoff-last-text', lastLine));
      last.title = String(prep.last_user_message).trim().slice(0, 600);
      carry.appendChild(last);
    }
    box.appendChild(carry);
    box.appendChild(h('div', 'agent-handoff-label agent-handoff-section', 'Continue in'));

    const search = document.createElement('input');
    search.type = 'search';
    search.className = 'agent-handoff-search';
    search.placeholder = 'Search agents…';
    search.setAttribute('role', 'combobox');
    search.setAttribute('aria-label', 'Search agents');
    search.setAttribute('aria-controls', listId);
    search.setAttribute('aria-expanded', 'true');
    search.autocomplete = 'off';
    search.spellcheck = false;
    const searchable = prep.targets.length > SEARCH_THRESHOLD;
    if (searchable) box.appendChild(search);

    const list = h('div', 'agent-handoff-targets');
    list.id = listId;
    list.setAttribute('role', 'listbox');
    list.setAttribute('aria-label', 'Agents');
    box.appendChild(list);
    const note = h('div', 'agent-handoff-note');
    note.setAttribute('aria-live', 'polite');
    box.appendChild(note);
    const actions = h('div', 'agent-handoff-actions');
    const cancel = h('button', 'agent-handoff-btn', 'Cancel');
    cancel.type = 'button';
    const go = h('button', 'agent-handoff-btn agent-handoff-btn-primary', 'Continue');
    go.type = 'button';
    actions.appendChild(cancel);
    actions.appendChild(go);
    box.appendChild(actions);

    const initial = defaultTarget(prep.targets, sess.agent);
    let selected = initial ? initial.agent : null;
    let visible = [];

    function close() {
      overlay.remove();
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('focusin', onFocusIn);
      if (opener && opener.isConnected && typeof opener.focus === 'function') opener.focus();
    }

    function begin() {
      const target = selected;
      if (!target) return;
      // _genAgentStart silently returns while another start is in flight, so
      // check first and keep the dialog open rather than closing it on a no-op.
      if (startInFlight(tabId)) {
        showToast('Another agent is still starting. Try again in a moment.', 'warn');
        return;
      }
      close();
      _genAgentStart(tabId, target, project.projectId, _genAgentFolder(state), {
        forceNew: true,
        handoffId: prep.handoff_id,
        keepStateAgent: !!state.agent,
      });
    }

    function select(agent) {
      selected = agent;
      list.querySelectorAll('.agent-handoff-option').forEach((el) => {
        const on = el.dataset.agent === agent;
        el.classList.toggle('is-selected', on);
        el.setAttribute('aria-selected', on ? 'true' : 'false');
        if (on) {
          search.setAttribute('aria-activedescendant', el.id);
          el.scrollIntoView({ block: 'nearest' });
        }
      });
      const t = prep.targets.find((x) => x.agent === agent);
      note.textContent = t ? targetWarning(t) : '';
      go.disabled = !t;
    }

    function renderTargets() {
      list.textContent = '';
      const sections = groupTargets(prep.targets, sess.agent, search.value);
      visible = sections.flatMap((sec) => sec.items).filter((t) => t.installed !== false);
      sections.forEach((sec) => {
        const group = h('div', 'agent-handoff-group');
        group.setAttribute('role', 'group');
        group.setAttribute('aria-label', sec.title);
        group.appendChild(h('div', 'agent-handoff-group-title', sec.title));
        sec.items.forEach((t) => {
          const missing = t.installed === false;
          const row = h('div', 'agent-handoff-option');
          row.id = listId + '-' + t.agent;
          row.dataset.agent = t.agent;
          row.setAttribute('role', 'option');
          row.setAttribute('aria-disabled', missing ? 'true' : 'false');
          row.classList.toggle('is-missing', missing);
          if (typeof _genAgentTabIcon === 'function') row.appendChild(_genAgentTabIcon(t.agent));
          row.appendChild(h('span', 'agent-handoff-option-name', t.label));
          if (!missing) {
            row.addEventListener('click', () => {
              select(t.agent);
              if (searchable) search.focus();
            });
            row.addEventListener('dblclick', () => {
              select(t.agent);
              begin();
            });
          }
          group.appendChild(row);
        });
        list.appendChild(group);
      });
      if (!sections.length) list.appendChild(h('div', 'agent-handoff-empty', 'No agents match.'));
      if (!visible.some((t) => t.agent === selected))
        selected = visible.length ? visible[0].agent : null;
      select(selected);
    }

    function move(delta) {
      if (!visible.length) return;
      const i = visible.findIndex((t) => t.agent === selected);
      const next = Math.max(0, Math.min(visible.length - 1, i + delta));
      select(visible[next].agent);
    }

    function focusables() {
      return [searchable && search, cancel, go].filter((el) => el && !el.disabled);
    }

    const onFocusIn = (e) => {
      if (box.contains(e.target)) return;
      const first = focusables()[0];
      if (first) first.focus();
    };

    const onKey = (e) => {
      if (e.key === 'Escape') {
        close();
      } else if (e.key === 'Tab') {
        const next = trapTarget(focusables(), document.activeElement, e.shiftKey);
        if (next) {
          e.preventDefault();
          next.focus();
        }
      } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        move(e.key === 'ArrowDown' ? 1 : -1);
      } else if (e.key === 'Enter' && e.target !== cancel && e.target !== go) {
        e.preventDefault();
        begin();
      }
    };

    search.addEventListener('input', renderTargets);
    renderTargets();
    document.addEventListener('keydown', onKey);
    document.addEventListener('focusin', onFocusIn);
    cancel.addEventListener('click', close);
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) close();
    });
    go.addEventListener('click', begin);

    overlay.appendChild(box);
    document.body.appendChild(overlay);
    if (searchable) search.focus();
    else go.focus();
  }

  async function openDialog(opts) {
    if (dialogBusy || document.querySelector('.agent-handoff-overlay')) return;
    const stored = opts.stored || null;
    const state = stored
      ? _genAgentEnsureTermsContainer(opts.tabId)
      : _genAgentTerminals[_caSessionKey(opts.tabId)];
    if (!state || !opts.sess) return;
    if (stored ? !opts.project : !opts.sess.ptySessionId) return;
    const project = stored
      ? { projectId: opts.project.id, repoPath: opts.project.repoPath }
      : { projectId: state.projectId, repoPath: state.repoPath };
    dialogBusy = true;
    try {
      const doFetch = typeof _ocFetch === 'function' ? _ocFetch : fetch;
      let prep;
      try {
        const headers = await _caHeadersAsync();
        const resp = await doFetch('/api/generic-agent/handoff/prepare', {
          method: 'POST',
          headers,
          body: JSON.stringify(prepareBody(opts, project)),
        });
        const body = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          showToast(errorDetail(body, 'Could not prepare the handoff.'), 'warn');
          return;
        }
        prep = body;
        // A malformed 200 (missing fields) throws here, so it gets the same toast.
        renderDialog(prep, opts.sess, state, opts.tabId, project);
      } catch (_) {
        document.querySelectorAll('.agent-handoff-overlay').forEach((el) => el.remove());
        showToast('Could not prepare the handoff.', 'warn');
        return;
      }
    } finally {
      dialogBusy = false;
    }
  }

  const offerToasts = new WeakMap();

  function offerOnLimit(sess) {
    const existing = offerToasts.get(sess);
    if (existing && existing.isConnected) return;
    const toast = showToast(
      agentLabel(sess.agent) + ' looks out of usage. Continue in another agent?',
      'offer',
      [
        {
          label: 'Continue in…',
          onClick: () => openDialog({ tabId: sess.tabId, sess }),
        },
      ],
    );
    offerToasts.set(sess, toast);
  }

  const api = {
    bracketedPaste,
    trackBracketedPaste,
    startInFlight,
    isInputReady,
    groupTargets,
    oneLine,
    defaultTarget,
    targetWarning,
    trapTarget,
    REDACTION_NOTE,
    errorDetail,
    prepareBody,
    waitForReady,
    draftPrompt,
    showToast,
    openDialog,
    deliver,
    offerOnLimit,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.agentHandoff = api;
})(typeof window !== 'undefined' ? window : globalThis);
