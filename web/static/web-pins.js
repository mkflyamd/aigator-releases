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

  function icon(px) {
    const n = px || 16;
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${n}" height="${n}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="vertical-align:middle;flex-shrink:0"><circle cx="12" cy="12" r="7"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/></svg>`;
  }

  const api = { STALE_MS, errorMessage, ageLabel, isStale, icon };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document === 'undefined') return;

  const captured = new Map(); // pin id -> captured_at seconds (null while loading)

  function activeContext() {
    return typeof _activeTabId !== 'undefined' && _activeTabId ? _activeTabId : null;
  }

  function toast(message) {
    if (typeof _showConnectivityToast === 'function') _showConnectivityToast(message, 'warning');
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
        fillComposer(s.text);
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
    const pin = await res.json();
    captured.set(pin.id, pin.captured_at);
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
    if (iconEl) {
      const img = document.createElement('img');
      img.className = 'wp-thumb';
      img.alt = '';
      img.src = `/api/web-pins/${encodeURIComponent(pin.id)}/image?t=${Date.now()}`;
      img.addEventListener('error', () => img.remove());
      iconEl.classList.add('has-thumb');
      iconEl.appendChild(img);
    }
    const open = card.querySelector('.pin-card-open');
    if (open) open.style.display = 'none';
    const metaEl = card.querySelector('.pin-card-meta');
    fetch(`/api/web-pins/${encodeURIComponent(pin.id)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        if (!j || !metaEl) return;
        captured.set(pin.id, j.captured_at);
        const app = (pin.meta && pin.meta.app_name) || 'Web view';
        metaEl.textContent = `${app} · ${ageLabel(j.captured_at)}`;
        metaEl.classList.toggle('is-stale', isStale(j.captured_at));
      })
      .catch(() => {});
  }

  root.WebPins = Object.assign(api, { onCaptured, decorateCard, tickChips });

  const shell = root.gatorShell;
  if (shell && shell.isShell && shell.onWebPinCaptured && shell.onWebPinEvent) {
    shell.onWebPinCaptured(onCaptured);
    shell.onWebPinEvent(onEvent);
  }
  setInterval(tickChips, 60000);
})(typeof window !== 'undefined' ? window : globalThis);
