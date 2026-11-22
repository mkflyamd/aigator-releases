// Renderer side of web pane pins: turns a shell capture into a pin, a chip in the composer,
// a lift animation and starter questions. Pure helpers are exported for Node tests.
(function (root) {
  'use strict';

  const STALE_MS = 30 * 60 * 1000;
  const COACHED_KEY = 'aigator.webpin.coached';
  const ERRORS = {
    pane_unavailable: "That app isn't ready yet. Give it a second to load, then try again.",
    pane_not_visible: 'Open the app first, then pin.',
    page_mismatch: 'The app is on a different page than when this was pinned.',
    timeout: 'The page took too long to answer. Try again.',
    empty_target: 'That spot has nothing to capture. Pick a larger area.',
  };

  function errorMessage(code) {
    return ERRORS[code] || ERRORS.pane_unavailable;
  }

  function ageLabel(capturedAtSec, nowMs) {
    const now = nowMs === undefined ? Date.now() : nowMs;
    const s = Math.max(0, Math.floor(now / 1000 - capturedAtSec));
    if (s < 60) return 'just now';
    const m = Math.floor(s / 60);
    if (m < 60) return `${m} min ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h} h ago`;
    return `${Math.floor(h / 24)} d ago`;
  }

  function isStale(capturedAtSec, nowMs) {
    const now = nowMs === undefined ? Date.now() : nowMs;
    return now - capturedAtSec * 1000 >= STALE_MS;
  }

  function matchNote(match) {
    if (match === 'rect') return 'Refreshed. The element moved, so this capture is approximate.';
    if (match === 'view-fallback')
      return 'Could not find the pinned element, so Gator captured the whole view.';
    return '';
  }

  // The five codes the shell emits; the snapshot route accepts all of them. Anything outside
  // this set is posted as pane_unavailable so the waiting agent tool is still released.
  const POSTABLE_FAILURES = new Set([
    'pane_not_visible',
    'page_mismatch',
    'pane_unavailable',
    'timeout',
    'empty_target',
  ]);

  function createRecapturer({ fetchFn, shell, sleep }) {
    const base = (pinId) => `/api/web-pins/${encodeURIComponent(pinId)}`;

    async function post(pinId, body) {
      try {
        const r = await fetchFn(`${base(pinId)}/snapshot`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (!r || !r.ok) return { ok: false, status: r ? r.status : undefined, json: null };
        let json = null;
        try {
          json = await r.json();
        } catch {
          json = null;
        }
        return { ok: true, status: r.status, json: json && typeof json === 'object' ? json : {} };
      } catch {
        return { ok: false, status: undefined, json: null };
      }
    }

    async function recapture(pinId, opts) {
      const requestId = opts && opts.requestId;
      const user = !!(opts && opts.user);
      let detail = null;
      try {
        const r = await fetchFn(base(pinId));
        detail = r && r.ok ? await r.json() : null;
      } catch {
        detail = null;
      }
      const meta = (detail && detail.meta) || {};
      const fail = async (code) => {
        if (requestId) {
          await post(pinId, {
            request_id: requestId,
            status: POSTABLE_FAILURES.has(code) ? code : 'pane_unavailable',
          });
        }
        const out = { status: code };
        if (meta.app_id) out.appId = meta.app_id;
        if (meta.url) out.url = meta.url;
        return out;
      };
      if (!meta.app_id || !shell || !shell.webPinRecapture) return fail('pane_unavailable');
      const locator = meta.locator || null;
      const url = meta.url || '';
      const capture = async () => {
        try {
          const res = await shell.webPinRecapture(meta.app_id, locator, url);
          return res && typeof res === 'object' && res.status
            ? res
            : { status: 'pane_unavailable' };
        } catch {
          return { status: 'pane_unavailable' };
        }
      };
      let res = await capture();
      if (user && res.status === 'pane_not_visible' && shell.showCustomApp) {
        try {
          await shell.showCustomApp(meta.app_id);
          await sleep(700);
        } catch {
          // fall through to the retry; it reports pane_not_visible again if the pane never showed
        }
        res = await capture();
      }
      if (res.status !== 'ok') return fail(res.status);
      const out = await post(pinId, {
        request_id: requestId,
        status: 'ok',
        image_b64: res.image_b64,
        text: res.text,
        match: res.match,
      });
      if (!out.ok) {
        // The route validates image/text (400/413) before it claims the request, so a rejected
        // success post leaves the agent waiting. 409 means the request is already answered.
        // A post that never reached the server (status undefined) cannot be followed up.
        if (requestId && out.status !== undefined && out.status !== 409) {
          await post(pinId, { request_id: requestId, status: 'pane_unavailable' });
        }
        return { status: 'pane_unavailable' };
      }
      if (typeof out.json.captured_at !== 'number') return { status: 'pane_unavailable' };
      return {
        status: 'ok',
        changed: out.json.changed,
        captured_at: out.json.captured_at,
        match: out.json.match,
      };
    }

    return { recapture };
  }

  const api = { STALE_MS, errorMessage, ageLabel, isStale, matchNote, createRecapturer };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document === 'undefined') return;

  const captured = new Map(); // pin id -> captured_at seconds (null while loading)
  const changedPins = new Set();
  const recapturer = createRecapturer({
    fetchFn: (...args) => root.fetch(...args),
    shell: root.gatorShell,
    sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  });

  function ownsContext(contextId) {
    return (
      typeof _tabs !== 'undefined' && Array.isArray(_tabs) && _tabs.some((t) => t.id === contextId)
    );
  }

  function afterRefresh(pinId, r) {
    captured.set(pinId, r.captured_at);
    if (r.changed) changedPins.add(pinId);
    tickChips();
    if (typeof _refreshPinOrb === 'function') _refreshPinOrb(true);
  }

  // Agent-initiated refresh. Only the tab that owns the conversation answers; the recapturer
  // always posts a result (success or failure) so the waiting agent tool is released.
  function onRecaptureRequest(msg) {
    if (!msg || !msg.request_id || !msg.pin_id || !ownsContext(msg.context_id)) return;
    // A client without the desktop shell cannot capture: stay silent so a shell client can win the claim.
    if (!root.gatorShell || !root.gatorShell.webPinRecapture) return;
    recapturer
      .recapture(msg.pin_id, { requestId: msg.request_id, user: false })
      .then((r) => {
        if (r && r.status === 'ok') afterRefresh(msg.pin_id, r);
      })
      .catch(() => {});
  }

  function offerGoTo(metaEl, appId, url) {
    if (!metaEl) return;
    metaEl.textContent = 'Different page · ';
    const link = document.createElement('button');
    link.type = 'button';
    link.className = 'wp-goto';
    link.textContent = "Go to pin's page";
    link.addEventListener('click', async () => {
      link.disabled = true;
      const shell = root.gatorShell;
      let ok = false;
      try {
        ok = shell && shell.webPinGoTo ? await shell.webPinGoTo(appId, url) : false;
      } catch {
        ok = false;
      }
      if (!ok) link.disabled = false;
      toast(
        ok ? 'Back on the pinned page. Refresh again.' : "Couldn't open that page.",
        ok ? 'info' : 'warning',
      );
    });
    metaEl.appendChild(link);
  }

  function activeContext() {
    return typeof _activeTabId !== 'undefined' && _activeTabId ? _activeTabId : null;
  }

  function tabTitle(id) {
    const tab =
      typeof _tabs !== 'undefined' && Array.isArray(_tabs) ? _tabs.find((t) => t.id === id) : null;
    return tab && tab.title ? tab.title : 'another tab';
  }

  function toast(message, type) {
    if (typeof _showConnectivityToast === 'function')
      _showConnectivityToast(message, type || 'warning');
  }

  function fly(imageB64) {
    if (root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const input = document.getElementById('chat-input');
    if (!input) return;
    const to = input.getBoundingClientRect();
    const w = Math.min(320, root.innerWidth * 0.4);
    const left = root.innerWidth * 0.5 - w / 2;
    const top = root.innerHeight * 0.3;
    const img = document.createElement('img');
    img.className = 'wp-fly';
    img.alt = '';
    img.src = 'data:image/png;base64,' + imageB64;
    img.style.cssText = `left:${left}px;top:${top}px;width:${w}px;`;
    document.body.appendChild(img);
    requestAnimationFrame(() => {
      img.style.transform = `translate(${to.left + 24 - left}px, ${to.top - top}px) scale(0.12)`;
      img.style.opacity = '0';
    });
    setTimeout(() => img.remove(), 700);
  }

  function clearSuggestions() {
    const old = document.getElementById('wp-suggest');
    if (old) old.remove();
  }

  function fillComposer(text) {
    const input = document.getElementById('chat-input');
    if (!input) return;
    input.focus();
    const range = document.createRange();
    range.selectNodeContents(input);
    range.collapse(false);
    const sel = root.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    document.execCommand('insertText', false, text + ' ');
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }

  async function showSuggestions(pinId, contextId) {
    clearSuggestions();
    let list = [];
    try {
      const r = await fetch(`/api/web-pins/${encodeURIComponent(pinId)}/suggestions`);
      list = r.ok ? (await r.json()).suggestions || [] : [];
    } catch {
      list = [];
    }
    if (!list.length || activeContext() !== contextId) return;
    const input = document.getElementById('chat-input');
    const host = input && input.parentElement;
    if (!host) return;
    const row = document.createElement('div');
    row.id = 'wp-suggest';
    row.className = 'wp-suggest';
    let coached = true;
    try {
      coached = root.localStorage.getItem(COACHED_KEY) === '1';
      if (!coached) root.localStorage.setItem(COACHED_KEY, '1');
    } catch {
      coached = true;
    }
    if (!coached) {
      const hint = document.createElement('div');
      hint.className = 'wp-suggest-hint';
      hint.textContent = 'Pinned. Gator can see it now. Ask anything, or start with one of these.';
      row.appendChild(hint);
    }
    list.forEach((s) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'wp-suggest-chip' + (s.kind === 'action' ? ' is-action' : '');
      b.textContent = s.text;
      b.addEventListener('click', () => {
        clearSuggestions();
        if (activeContext() === contextId) fillComposer(s.text);
      });
      row.appendChild(b);
    });
    const x = document.createElement('button');
    x.type = 'button';
    x.className = 'wp-suggest-x';
    x.setAttribute('aria-label', 'Dismiss suggestions');
    x.textContent = '×';
    x.addEventListener('click', clearSuggestions);
    row.appendChild(x);
    clearSuggestions();
    host.insertAdjacentElement('beforebegin', row);
  }

  async function onCaptured(p) {
    const contextId = activeContext();
    if (!contextId) {
      toast('Open a chat tab, then pin again.');
      return;
    }
    let res = null;
    try {
      res = await fetch('/api/web-pins', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          context_id: contextId,
          app_id: p.appId,
          image_b64: p.image_b64,
          text: p.text,
          locator: p.locator,
          url: p.url,
          title: p.title,
          aria_label: p.aria_label,
        }),
      });
    } catch {
      res = null;
    }
    if (!res || !res.ok) {
      toast(
        res && res.status === 413
          ? 'That view is too large to pin. Pick a smaller area.'
          : 'Could not pin that. Try again.',
      );
      return;
    }
    let pin = null;
    try {
      pin = await res.json();
    } catch {
      pin = null;
    }
    if (!pin || !pin.id) {
      toast('Could not pin that. Try again.');
      return;
    }
    captured.set(pin.id, pin.captured_at);
    if (activeContext() !== contextId) {
      // The user switched tabs while the capture was saving: the pin belongs to the original tab.
      toast(`Pinned to ${tabTitle(contextId)}. Switch back to use it.`);
      if (typeof _refreshPinOrb === 'function') _refreshPinOrb(true);
      return;
    }
    fly(p.image_b64);
    if (typeof root.insertPinChipAtCaret === 'function') {
      root.insertPinChipAtCaret({ source: 'webpin', id: pin.id, label: pin.label });
    }
    if (typeof _refreshPinOrb === 'function') _refreshPinOrb(true);
    tickChips();
    showSuggestions(pin.id, contextId);
  }

  function onEvent(ev) {
    if (ev && ev.type === 'error') toast(errorMessage(ev.code));
  }

  function tickChips() {
    document.querySelectorAll('.pin-ref-chip[data-pin-source="webpin"]').forEach((chip) => {
      const id = chip.dataset.pinId;
      const label = chip.dataset.wpLabel || chip.title.replace(/^webpin: /, '');
      chip.dataset.wpLabel = label;
      if (!captured.has(id)) {
        captured.set(id, null);
        fetch(`/api/web-pins/${encodeURIComponent(id)}`)
          .then((r) => (r.ok ? r.json() : null))
          .then((j) => {
            if (j) {
              captured.set(id, j.captured_at);
              tickChips();
            } else {
              captured.delete(id);
            }
          })
          .catch(() => captured.delete(id));
        return;
      }
      const at = captured.get(id);
      if (at == null) return;
      chip.classList.toggle('is-stale', isStale(at));
      chip.title = `Web view: ${label} · captured ${ageLabel(at)}`;
    });
  }

  function decorateCard(card, pin) {
    const iconEl = card.querySelector('.pin-card-icon');
    let thumb = null;
    if (iconEl) {
      thumb = document.createElement('img');
      thumb.className = 'wp-thumb';
      thumb.alt = '';
      thumb.src = `/api/web-pins/${encodeURIComponent(pin.id)}/image?t=${Date.now()}`;
      thumb.addEventListener('error', () => thumb.remove());
      iconEl.classList.add('has-thumb');
      iconEl.appendChild(thumb);
    }
    const open = card.querySelector('.pin-card-open');
    if (open) open.style.display = 'none';
    const metaEl = card.querySelector('.pin-card-meta');
    const appName = (pin.meta && pin.meta.app_name) || 'Web view';
    const paintMeta = (at) => {
      if (!metaEl) return;
      metaEl.textContent = `${appName} · ${ageLabel(at)}`;
      metaEl.classList.toggle('is-stale', isStale(at));
    };
    if (changedPins.has(pin.id)) card.classList.add('has-change');
    const ask = card.querySelector('.pin-card-ask');
    if (ask) {
      ask.addEventListener('click', () => {
        changedPins.delete(pin.id);
        card.classList.remove('has-change');
      });
    }
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'pin-card-btn pin-card-refresh';
    btn.title = 'Refresh this pin';
    btn.setAttribute('aria-label', 'Refresh this pin');
    btn.textContent = '↻';
    if (ask && ask.parentElement) ask.parentElement.insertBefore(btn, ask);
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      btn.classList.add('is-spinning');
      let r;
      try {
        r = await recapturer.recapture(pin.id, { user: true });
      } catch {
        r = { status: 'pane_unavailable' };
      }
      btn.disabled = false;
      btn.classList.remove('is-spinning');
      if (r.status === 'ok') {
        afterRefresh(pin.id, r);
        paintMeta(r.captured_at);
        card.classList.toggle('has-change', !!r.changed);
        if (thumb) thumb.src = `/api/web-pins/${encodeURIComponent(pin.id)}/image?t=${Date.now()}`;
        const note = matchNote(r.match);
        if (note) toast(note, 'info');
        else if (!r.changed) toast('No change since the last capture.', 'info');
      } else if (r.status === 'page_mismatch' && r.url) {
        offerGoTo(metaEl, r.appId, r.url);
      } else {
        toast(errorMessage(r.status));
      }
    });
    fetch(`/api/web-pins/${encodeURIComponent(pin.id)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        if (!j) return;
        captured.set(pin.id, j.captured_at);
        paintMeta(j.captured_at);
      })
      .catch(() => {});
  }

  root.WebPins = Object.assign(api, { onCaptured, decorateCard, tickChips, onRecaptureRequest });

  const shell = root.gatorShell;
  if (shell && shell.isShell && shell.onWebPinCaptured && shell.onWebPinEvent) {
    shell.onWebPinCaptured(onCaptured);
    shell.onWebPinEvent(onEvent);
  }
  setInterval(tickChips, 60000);
})(typeof window !== 'undefined' ? window : globalThis);
