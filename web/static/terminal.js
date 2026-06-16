// Integrated terminal — xterm.js + WebSocket PTY bridge, with tabs.
// API: window.GatorTerminal.toggle() / .open() / .close() / .setLayout('horizontal' | 'vertical') / .newSession() / .toggleFullscreen()

(function () {
  const LS_LAYOUT_KEY = 'gator.terminal.layout';
  const LS_SIZE_H_KEY = 'gator.terminal.height';
  const LS_SIZE_V_KEY = 'gator.terminal.width';

  const STATE = {
    panel: null,
    body: null,            // wraps tabs+terminals
    tabsEl: null,
    termsEl: null,         // container that holds each session's xterm div
    sessions: [],          // {id, title, term, fitAddon, ws, el, tabEl}
    activeId: null,
    nextId: 1,
    opened: false,
    layout: null,
    fullscreen: false,
    layoutBtn: null,
    fullscreenBtn: null,
  };

  function _loadLayout() {
    return localStorage.getItem(LS_LAYOUT_KEY) === 'vertical' ? 'vertical' : 'horizontal';
  }

  function _el(tag, opts = {}) {
    const el = document.createElement(tag);
    if (opts.id) el.id = opts.id;
    if (opts.className) el.className = opts.className;
    if (opts.text) el.textContent = opts.text;
    if (opts.title) el.title = opts.title;
    if (opts.type) el.type = opts.type;
    return el;
  }

  function _ensurePanel() {
    if (STATE.panel) return STATE.panel;

    const panel = _el('div', { id: 'gator-terminal-panel', className: 'gator-terminal-panel hidden' });

    const resizeHandle = _el('div', { className: 'gtp-resize-handle', id: 'gtp-resize-handle', title: 'Drag to resize' });

    // Single combined row: scrollable tabs + new-tab on the left, fixed action cluster on the right
    const tabs = _el('div', { className: 'gtp-tabs' });
    const tabsScroll = _el('div', { className: 'gtp-tabs-scroll' });
    const newTabBtn = _el('button', { type: 'button', className: 'gtp-tab-new', title: 'New terminal', text: '+' });

    const actions = _el('div', { className: 'gtp-actions' });
    const layoutBtn = _el('button', { type: 'button', className: 'gtp-btn gtp-btn-icon', id: 'gtp-layout', title: 'Switch layout' });
    layoutBtn.appendChild(_el('span', { className: 'material-symbols-outlined' }));
    const fullscreenBtn = _el('button', { type: 'button', className: 'gtp-btn gtp-btn-icon', id: 'gtp-fullscreen', title: 'Toggle fullscreen' });
    fullscreenBtn.appendChild(_el('span', { className: 'material-symbols-outlined' }));
    const closeBtn = _el('button', { type: 'button', className: 'gtp-btn', id: 'gtp-close', title: 'Close', text: '✕' });
    actions.appendChild(layoutBtn);
    actions.appendChild(fullscreenBtn);
    actions.appendChild(closeBtn);

    // Terminals container — holds one xterm div per session, only active is visible
    const terms = _el('div', { className: 'gtp-terms' });

    panel.appendChild(resizeHandle);
    panel.appendChild(tabs);
    panel.appendChild(terms);
    document.body.appendChild(panel);

    STATE.panel = panel;
    STATE.tabsEl = tabsScroll;
    STATE.tabsRow = tabs;
    STATE.termsEl = terms;
    STATE.layoutBtn = layoutBtn;
    STATE.fullscreenBtn = fullscreenBtn;

    closeBtn.addEventListener('click', close);
    layoutBtn.addEventListener('click', () => {
      if (STATE.fullscreen) return;
      setLayout(STATE.layout === 'horizontal' ? 'vertical' : 'horizontal');
    });
    fullscreenBtn.addEventListener('click', toggleFullscreen);
    newTabBtn.addEventListener('click', () => newSession());
    tabsScroll.appendChild(newTabBtn);
    tabs.appendChild(tabsScroll);
    tabs.appendChild(actions);
    STATE.newTabBtn = newTabBtn;
    STATE.actionsEl = actions;
    _wireResize(resizeHandle);

    return panel;
  }

  function _updateVerticalFlag() {
    // body flag so CSS can hide the chat's .main-resize (terminal owns the resize in vertical mode)
    const on = STATE.opened && STATE.layout === 'vertical' && !STATE.fullscreen
      && STATE.panel && !STATE.panel.classList.contains('hidden');
    document.body.classList.toggle('gator-terminal-vertical', !!on);
  }

  function _updatePush() {
    // Push the chat layout up by the terminal height ONLY when horizontal, opened, not fullscreen.
    const shouldPush = STATE.opened
      && STATE.layout === 'horizontal'
      && !STATE.fullscreen
      && STATE.panel
      && !STATE.panel.classList.contains('hidden');
    if (shouldPush) {
      const h = STATE.panel.getBoundingClientRect().height || 280;
      document.documentElement.style.setProperty('--gator-terminal-h', h + 'px');
      document.body.classList.add('gator-terminal-pushing');
    } else {
      document.body.classList.remove('gator-terminal-pushing');
      document.documentElement.style.removeProperty('--gator-terminal-h');
    }
  }

  function _reparent(layout) {
    if (!STATE.panel) return;
    const layoutEl = document.querySelector('.layout');
    if (layout === 'vertical' && !STATE.fullscreen && layoutEl) {
      const dock = layoutEl.querySelector('.dock');
      const anchor = dock ? dock.nextSibling : layoutEl.firstChild;
      if (STATE.panel.parentNode !== layoutEl || STATE.panel.previousSibling !== dock) {
        layoutEl.insertBefore(STATE.panel, anchor);
      }
    } else {
      if (STATE.panel.parentNode !== document.body) {
        document.body.appendChild(STATE.panel);
      }
    }
  }

  function _applyLayout(layout) {
    STATE.layout = layout;
    if (!STATE.panel) return;
    STATE.panel.classList.remove('horizontal', 'vertical');
    STATE.panel.classList.add(layout);
    _reparent(layout);

    if (!STATE.fullscreen) {
      if (layout === 'horizontal') {
        const h = parseInt(localStorage.getItem(LS_SIZE_H_KEY), 10);
        STATE.panel.style.height = Number.isFinite(h) ? h + 'px' : '';
        STATE.panel.style.width = '';
      } else {
        const w = parseInt(localStorage.getItem(LS_SIZE_V_KEY), 10);
        STATE.panel.style.width = Number.isFinite(w) ? w + 'px' : '';
        STATE.panel.style.height = '';
      }
    }
    if (STATE.layoutBtn) {
      STATE.layoutBtn.title = layout === 'horizontal' ? 'Switch to left (vertical)' : 'Switch to bottom (horizontal)';
      const iconEl = STATE.layoutBtn.querySelector('.material-symbols-outlined');
      if (iconEl) iconEl.textContent = layout === 'horizontal' ? 'side_navigation' : 'bottom_navigation';
    }
    localStorage.setItem(LS_LAYOUT_KEY, layout);
    _updatePush();
    _updateVerticalFlag();
    setTimeout(_fitActive, 30);
  }

  function _applyFullscreen(on) {
    STATE.fullscreen = on;
    if (!STATE.panel) return;
    STATE.panel.classList.toggle('fullscreen', on);
    if (on) {
      if (STATE.panel.parentNode !== document.body) document.body.appendChild(STATE.panel);
      STATE.panel.style.height = '';
      STATE.panel.style.width = '';
    } else {
      _applyLayout(STATE.layout);
    }
    if (STATE.fullscreenBtn) {
      STATE.fullscreenBtn.title = on ? 'Exit fullscreen' : 'Fullscreen';
      const iconEl = STATE.fullscreenBtn.querySelector('.material-symbols-outlined');
      if (iconEl) iconEl.textContent = on ? 'fullscreen_exit' : 'fullscreen';
    }
    if (STATE.layoutBtn) {
      STATE.layoutBtn.disabled = on;
      STATE.layoutBtn.style.opacity = on ? '0.4' : '';
      STATE.layoutBtn.style.cursor = on ? 'not-allowed' : '';
    }
    _updatePush();
    _updateVerticalFlag();
    setTimeout(_fitActive, 30);
  }

  function toggleFullscreen() {
    _applyFullscreen(!STATE.fullscreen);
  }

  function _wireResize(handle) {
    let startMouse = 0, startSize = 0, axis = 'y';
    const onMove = (e) => {
      if (axis === 'y') {
        const dy = startMouse - e.clientY;
        const newH = Math.max(120, Math.min(window.innerHeight - 100, startSize + dy));
        STATE.panel.style.height = newH + 'px';
      } else {
        const dx = e.clientX - startMouse;
        const newW = Math.max(240, Math.min(window.innerWidth - 200, startSize + dx));
        STATE.panel.style.width = newW + 'px';
      }
      _fitActive();
      _updatePush();
    _updateVerticalFlag();
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.body.style.userSelect = '';
      handle.classList.remove('dragging');
      if (axis === 'y') {
        localStorage.setItem(LS_SIZE_H_KEY, parseInt(STATE.panel.style.height, 10) || 280);
      } else {
        localStorage.setItem(LS_SIZE_V_KEY, parseInt(STATE.panel.style.width, 10) || 420);
      }
    };
    handle.addEventListener('mousedown', (e) => {
      const rect = STATE.panel.getBoundingClientRect();
      if (STATE.layout === 'horizontal') {
        axis = 'y'; startMouse = e.clientY; startSize = rect.height;
      } else {
        axis = 'x'; startMouse = e.clientX; startSize = rect.width;
      }
      document.body.style.userSelect = 'none';
      handle.classList.add('dragging');
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
      e.preventDefault();
    });
  }

  // ── Sessions ────────────────────────────────────────────────

  function _getSession(id) {
    return STATE.sessions.find((s) => s.id === id) || null;
  }

  function _renderTabs() {
    if (!STATE.tabsEl) return;
    // Wipe everything except the + button (which we'll re-append last)
    STATE.tabsEl.innerHTML = '';
    STATE.sessions.forEach((s) => {
      const tab = _el('div', { className: 'gtp-tab' + (s.id === STATE.activeId ? ' active' : '') });
      tab.dataset.sid = String(s.id);
      const label = _el('span', { className: 'gtp-tab-label', text: s.title });
      const x = _el('button', { type: 'button', className: 'gtp-tab-close', title: 'Close', text: '✕' });
      tab.appendChild(label);
      tab.appendChild(x);
      tab.addEventListener('click', (e) => {
        if (e.target === x) return;
        if (label.isContentEditable) return;
        _activate(s.id);
      });
      x.addEventListener('click', (e) => {
        e.stopPropagation();
        closeSession(s.id);
      });
      tab.addEventListener('dblclick', (e) => {
        if (e.target === x) return;
        e.preventDefault();
        e.stopPropagation();
        _beginRename(s, label);
      });
      s.tabEl = tab;
      STATE.tabsEl.appendChild(tab);
    });
    if (STATE.newTabBtn) STATE.tabsEl.appendChild(STATE.newTabBtn);
  }

  function _updateActiveTab() {
    STATE.sessions.forEach((s) => {
      if (s.tabEl) s.tabEl.classList.toggle('active', s.id === STATE.activeId);
    });
  }

  function _beginRename(sess, labelEl) {
    STATE.editing = true;
    labelEl.contentEditable = 'true';
    labelEl.spellcheck = false;
    labelEl.classList.add('editing');
    labelEl.focus();
    // Select all text
    const range = document.createRange();
    range.selectNodeContents(labelEl);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);

    const finish = (commit) => {
      labelEl.removeEventListener('keydown', onKey);
      labelEl.removeEventListener('blur', onBlur);
      labelEl.contentEditable = 'false';
      labelEl.classList.remove('editing');
      const next = labelEl.textContent.trim();
      if (commit && next) {
        sess.title = next;
      }
      labelEl.textContent = sess.title;
      window.getSelection().removeAllRanges();
      STATE.editing = false;
    };
    const onKey = (e) => {
      if (e.key === 'Enter') { e.preventDefault(); finish(true); }
      else if (e.key === 'Escape') { e.preventDefault(); finish(false); }
    };
    const onBlur = () => finish(true);
    labelEl.addEventListener('keydown', onKey);
    labelEl.addEventListener('blur', onBlur);
  }

  function _activate(id) {
    const sess = _getSession(id);
    if (!sess) return;
    STATE.activeId = id;
    STATE.sessions.forEach((s) => {
      s.el.style.display = (s.id === id) ? '' : 'none';
    });
    _updateActiveTab();
    setTimeout(() => {
      _fit(sess);
      // Don't steal focus from an in-progress rename
      if (!STATE.editing && sess.term) sess.term.focus();
    }, 20);
  }

  function _fit(sess) {
    if (!sess || !sess.fitAddon || !sess.term) return;
    try {
      sess.fitAddon.fit();
      if (sess.ws && sess.ws.readyState === WebSocket.OPEN) {
        sess.ws.send(JSON.stringify({ type: 'resize', cols: sess.term.cols, rows: sess.term.rows }));
      }
    } catch (e) { /* not visible yet */ }
  }

  function _fitActive() {
    _fit(_getSession(STATE.activeId));
  }

  function _spawnTerm(sess) {
    /* global Terminal, FitAddon */
    sess.term = new Terminal({
      fontFamily: 'Consolas, "Courier New", monospace',
      fontSize: 13,
      cursorBlink: true,
      theme: { background: '#0b0d12', foreground: '#d4d4d4', cursor: '#d4d4d4' },
      scrollback: 5000,
      convertEol: true,
    });
    sess.fitAddon = new FitAddon.FitAddon();
    sess.term.loadAddon(sess.fitAddon);
    sess.term.open(sess.el);

    // Own all paste through a single capture-phase listener on the container.
    // This fires before xterm's textarea listener so there's no double-paste.
    // Covers: Ctrl+V (browser fires paste event), right-click paste, etc.
    sess.el.addEventListener('paste', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const txt = (e.clipboardData || window.clipboardData).getData('text');
      if (txt && sess.term) sess.term.paste(txt);
    }, true);

    sess.term.attachCustomKeyEventHandler((e) => {
      if (e.type !== 'keydown') return true;
      if (e.ctrlKey && !e.shiftKey && !e.altKey && !e.metaKey
          && (e.key === 'c' || e.key === 'C')) {
        if (sess.term.hasSelection()) {
          const sel = sess.term.getSelection();
          if (sel) navigator.clipboard.writeText(sel).catch(() => {});
          sess.term.clearSelection();
        } else {
          _sendCtrlC(sess);
        }
        return false;
      }
      // Ctrl+V: return false so xterm doesn't double-handle keydown;
      // the browser will fire a paste event which our capture listener owns.
      if (e.ctrlKey && !e.shiftKey && !e.altKey && !e.metaKey
          && (e.key === 'v' || e.key === 'V')) {
        return false;
      }
      // Ctrl+Shift+V: browser won't fire a paste event for this combo,
      // so read the clipboard explicitly.
      if (e.ctrlKey && e.shiftKey && !e.altKey && !e.metaKey
          && (e.key === 'v' || e.key === 'V')) {
        navigator.clipboard.readText().then((txt) => {
          if (txt && sess.term) sess.term.paste(txt);
        }).catch(() => {});
        return false;
      }
      return true;
    });
    sess.term.onData((data) => {
      if (sess.ws && sess.ws.readyState === WebSocket.OPEN) {
        sess.ws.send(JSON.stringify({ type: 'input', data }));
      }
    });
  }

  function _connect(sess, retryDelay) {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = proto + '//' + location.host + '/api/terminal/ws';
    const delay = retryDelay || 0;

    sess.ws = new WebSocket(url);
    sess.ws.onopen = () => {
      sess._retryDelay = 0;
      _fit(sess);
      if (sess.id === STATE.activeId) sess.term && sess.term.focus();
    };
    sess.ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.type === 'output') {
        sess.term && sess.term.write(msg.data);
      } else if (msg.type === 'exit') {
        sess.term && sess.term.write('\r\n\x1b[33m[shell exited]\x1b[0m\r\n');
      }
    };
    sess.ws.onerror = () => { /* onclose handles retry */ };
    sess.ws.onclose = () => {
      if (!sess.term) return; // session was manually closed
      if (sess._closing) return; // user explicitly closed this session
      const next = Math.min((sess._retryDelay || 1000) * 2, 30000);
      sess._retryDelay = next;
      if (delay === 0) {
        // First disconnect — tell the user
        sess.term.write('\r\n\x1b[33m[disconnected — reconnecting in ' + Math.round(next / 1000) + 's…]\x1b[0m\r\n');
      }
      setTimeout(() => {
        if (!sess.term || sess._closing) return;
        _connect(sess, next);
      }, next);
    };
  }

  function newSession() {
    _ensurePanel();
    const id = STATE.nextId++;
    const el = _el('div', { className: 'gtp-term' });
    el.style.width = '100%';
    el.style.height = '100%';
    STATE.termsEl.appendChild(el);
    const sess = { id, title: 'shell ' + id, term: null, fitAddon: null, ws: null, el, tabEl: null };
    STATE.sessions.push(sess);
    _spawnTerm(sess);
    _connect(sess);
    _renderTabs();
    _activate(id);
    // Scroll the freshly added tab into view so the user can see (and rename) it
    if (sess.tabEl && sess.tabEl.scrollIntoView) {
      sess.tabEl.scrollIntoView({ behavior: 'smooth', inline: 'end', block: 'nearest' });
    }
    return id;
  }

  function closeSession(id) {
    const idx = STATE.sessions.findIndex((s) => s.id === id);
    if (idx < 0) return;
    const sess = STATE.sessions[idx];
    sess._closing = true; // prevent reconnect loop
    try { sess.ws && sess.ws.close(); } catch {}
    try { sess.term && sess.term.dispose(); } catch {}
    if (sess.el && sess.el.parentNode) sess.el.parentNode.removeChild(sess.el);
    STATE.sessions.splice(idx, 1);
    if (STATE.sessions.length === 0) {
      STATE.activeId = null;
      STATE.nextId = 1;
      close();
      return;
    }
    _renderTabs();
    if (STATE.activeId === id) {
      const next = STATE.sessions[Math.min(idx, STATE.sessions.length - 1)];
      _activate(next.id);
    }
  }

  // ── Public ──────────────────────────────────────────────────

  function _conflictingPaneOpen() {
    const isVisible = (el) => el
      && !el.classList.contains('hidden')
      && !el.classList.contains('is-closing')
      && el.offsetWidth > 0
      && getComputedStyle(el).display !== 'none';
    return isVisible(document.getElementById('third-pane'))
        || isVisible(document.getElementById('browser-pane'));
  }

  function _closeConflictingPanes() {
    // Explicit user request for vertical — close any pane occupying the .layout row.
    // Reuse the panes' own close buttons so their internal state stays consistent.
    const tpClose = document.getElementById('tp-detail-close');
    if (tpClose) tpClose.click();
    const bpClose = document.getElementById('bp-close-btn');
    if (bpClose) bpClose.click();
  }

  function setLayout(layout) {
    if (layout !== 'horizontal' && layout !== 'vertical') return;
    _ensurePanel();
    // User explicitly chose vertical — make room by closing any conflicting pane.
    if (layout === 'vertical' && !STATE.fullscreen && _conflictingPaneOpen()) {
      _closeConflictingPanes();
    }
    _applyLayout(layout);
  }

  function open() {
    _ensurePanel();
    _applyLayout(STATE.layout || _loadLayout());
    if (STATE.fullscreenBtn) {
      const iconEl = STATE.fullscreenBtn.querySelector('.material-symbols-outlined');
      if (iconEl && !iconEl.textContent) iconEl.textContent = STATE.fullscreen ? 'fullscreen_exit' : 'fullscreen';
    }
    STATE.panel.classList.remove('hidden');
    if (STATE.sessions.length === 0) newSession();
    STATE.opened = true;
    _updatePush();
    _updateVerticalFlag();
    setTimeout(_fitActive, 50);
    window.addEventListener('resize', _fitActive);
    if (!STATE._watching) {
      STATE._watching = true;
      _watchPanesForConflicts();
    }
  }

  function close() {
    if (STATE.panel) STATE.panel.classList.add('hidden');
    STATE.opened = false;
    _updatePush();
    _updateVerticalFlag();
  }

  function toggle() {
    if (STATE.opened) close();
    else open();
  }

  // Auto-flip vertical → horizontal when another left-rail pane opens, so they don't fight for width.
  // Non-destructive: shell sessions are preserved; user can flip back to vertical when the other pane closes.
  function _watchPanesForConflicts() {
    const check = () => {
      if (!STATE.opened || STATE.layout !== 'vertical' || STATE.fullscreen) return;
      if (_conflictingPaneOpen()) setLayout('horizontal');
    };
    const obs = new MutationObserver(check);
    ['third-pane', 'browser-pane'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) obs.observe(el, { attributes: true, attributeFilter: ['class', 'style'] });
    });
    // Initial check in case a pane is already open when terminal first opens
    check();
  }

  function _sendCtrlC(sess) {
    if (sess && sess.ws && sess.ws.readyState === WebSocket.OPEN) {
      sess.ws.send(JSON.stringify({ type: 'input', data: '\x03' }));
    }
  }

  // Ctrl+J to toggle; Ctrl+C forwarded to active terminal when panel is open
  // and focus is outside the xterm (e.g. user clicked into the chat input).
  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && !e.shiftKey && !e.altKey && !e.metaKey) {
      if (e.key === 'j' || e.key === 'J') {
        e.preventDefault();
        toggle();
        return;
      }
      if ((e.key === 'c' || e.key === 'C') && STATE.opened) {
        // Only intercept if focus is NOT inside the xterm textarea
        // (xterm's own handler covers that case).
        const active = document.activeElement;
        const inXterm = active && active.closest && active.closest('.xterm');
        if (!inXterm) {
          e.preventDefault();
          _sendCtrlC(_getSession(STATE.activeId));
        }
      }
    }
  });

  window.GatorTerminal = { open, close, toggle, setLayout, toggleFullscreen, newSession, closeSession };
})();
