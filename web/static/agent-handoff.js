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

  function bracketedPaste(text) {
    const clean = String(text).split(ESC).join('').replace(/\r\n?/g, '\n');
    return PASTE_START + clean + PASTE_END;
  }

  function isInputReady(s, now) {
    if (!s.outputChars || !s.lastOutputAt) return false;
    if (now - s.lastOutputAt < READY_QUIET_MS) return false;
    if (s.paintedRows < 2) return false;
    if (s.agent === 'opencode-bare' && !s.frameReady) return false;
    return true;
  }

  function visibleTargets(targets, sourceAgent, excludeSource) {
    return targets.filter((t) => !(excludeSource && t.agent === sourceAgent));
  }

  function errorDetail(body, fallback) {
    return body && typeof body.detail === 'string' && body.detail ? body.detail : fallback;
  }

  function targetWarning(target) {
    return target.gateway_routed
      ? ''
      : 'Runs on its own configuration, outside the AI Gator gateway.';
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

  // ── Browser-only below ──────────────────────────────────────────────────
  function agentLabel(agent) {
    return typeof _genAgentLabel === 'function' ? _genAgentLabel(agent) : agent;
  }

  function sessionProbe(sess, now) {
    return isInputReady(
      {
        agent: sess.agent,
        outputChars: sess._outputChars,
        lastOutputAt: sess._lastOutputAt,
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

  function renderDialog(prep, sess, state, tabId, excludeSource) {
    dialogSeq += 1;
    const radioName = 'agent-handoff-target-' + dialogSeq;
    const overlay = h('div', 'agent-handoff-overlay');
    const box = h('div', 'agent-handoff-dialog');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    box.setAttribute('aria-label', 'Continue in another agent');
    box.appendChild(h('h3', null, 'Continue in…'));

    const kb = Math.max(1, Math.round(prep.snapshot_bytes / 1024));
    let meta =
      agentLabel(sess.agent) +
      ' session · ' +
      kb +
      ' KB · ' +
      (prep.source_kind === 'transcript' ? 'transcript' : 'terminal capture');
    if (prep.redactions) meta += ' · ' + prep.redactions + ' credential(s) redacted';
    box.appendChild(h('div', 'agent-handoff-meta', meta));
    if (prep.last_user_message) {
      box.appendChild(h('div', 'agent-handoff-label', 'Last message in the prior session'));
      box.appendChild(h('pre', 'agent-handoff-last', prep.last_user_message.slice(0, 300)));
    }

    const excludeLabel = h('label', 'agent-handoff-exclude');
    const excludeBox = document.createElement('input');
    excludeBox.type = 'checkbox';
    excludeBox.checked = !!excludeSource;
    excludeLabel.appendChild(excludeBox);
    excludeLabel.appendChild(document.createTextNode(' Hide ' + agentLabel(sess.agent)));
    box.appendChild(excludeLabel);

    const list = h('div', 'agent-handoff-targets');
    box.appendChild(list);
    const actions = h('div', 'agent-handoff-actions');
    const cancel = h('button', 'agent-handoff-btn', 'Cancel');
    cancel.type = 'button';
    const go = h('button', 'agent-handoff-btn agent-handoff-btn-primary', 'Continue');
    go.type = 'button';
    actions.appendChild(cancel);
    actions.appendChild(go);
    box.appendChild(actions);

    let selected = null;
    function renderTargets() {
      list.textContent = '';
      const shown = visibleTargets(prep.targets, sess.agent, excludeBox.checked);
      if (!shown.some((t) => t.agent === selected)) selected = shown.length ? shown[0].agent : null;
      shown.forEach((t) => {
        const row = h('label', 'agent-handoff-target');
        const radio = document.createElement('input');
        radio.type = 'radio';
        radio.name = radioName;
        radio.value = t.agent;
        radio.checked = t.agent === selected;
        radio.addEventListener('change', () => (selected = t.agent));
        row.appendChild(radio);
        row.appendChild(document.createTextNode(' ' + t.label));
        const warning = targetWarning(t);
        if (warning) row.appendChild(h('div', 'agent-handoff-warning', warning));
        list.appendChild(row);
      });
      go.disabled = !selected;
    }
    excludeBox.addEventListener('change', renderTargets);
    renderTargets();

    const close = () => {
      overlay.remove();
      document.removeEventListener('keydown', onKey);
    };
    const onKey = (e) => {
      if (e.key === 'Escape') close();
    };
    document.addEventListener('keydown', onKey);
    cancel.addEventListener('click', close);
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) close();
    });
    go.addEventListener('click', () => {
      const target = selected;
      close();
      if (!target) return;
      _genAgentStart(tabId, target, state.projectId, state.repoPath, {
        forceNew: true,
        handoffId: prep.handoff_id,
        keepStateAgent: true,
      });
    });

    overlay.appendChild(box);
    document.body.appendChild(overlay);
    go.focus();
  }

  async function openDialog(opts) {
    if (dialogBusy || document.querySelector('.agent-handoff-overlay')) return;
    const state = _genAgentTerminals[_caSessionKey(opts.tabId)];
    if (!state || !opts.sess || !opts.sess.ptySessionId) return;
    dialogBusy = true;
    try {
      const doFetch = typeof _ocFetch === 'function' ? _ocFetch : fetch;
      let prep;
      try {
        const headers = await _caHeadersAsync();
        const resp = await doFetch('/api/generic-agent/handoff/prepare', {
          method: 'POST',
          headers,
          body: JSON.stringify({
            agent: opts.sess.agent,
            project_id: state.projectId,
            repo_path: state.repoPath,
            pty_session_id: opts.sess.ptySessionId,
          }),
        });
        const body = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          showToast(errorDetail(body, 'Could not prepare the handoff.'), 'warn');
          return;
        }
        prep = body;
      } catch (_) {
        showToast('Could not prepare the handoff.', 'warn');
        return;
      }
      renderDialog(prep, opts.sess, state, opts.tabId, !!opts.excludeSource);
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
          onClick: () => openDialog({ tabId: sess.tabId, sess, excludeSource: true }),
        },
      ],
    );
    offerToasts.set(sess, toast);
  }

  const api = {
    bracketedPaste,
    isInputReady,
    visibleTargets,
    targetWarning,
    errorDetail,
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
