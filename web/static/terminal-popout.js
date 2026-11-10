// Standalone view of one coding-agent terminal session, opened in its own
// window by the shell's "Pop out" button. It attaches to the same PTY session
// as the main window over /api/terminal/agent, so both show the same agent.
(function () {
  const params = new URLSearchParams(location.search);
  const sessionId = params.get('session_id') || '';
  const label = params.get('label') || 'Terminal';
  document.title = label + ' - AI Gator';

  const statusEl = document.getElementById('status');

  // Same light/dark choice as the in-app terminals (Settings > terminal theme).
  const DARK = { background: '#0b0d12', foreground: '#d4d4d4', cursor: '#d4d4d4' };
  const LIGHT = { background: '#ffffff', foreground: '#0f172a', cursor: '#0f172a' };
  function xtermTheme(setting) {
    if (setting === 'light') return LIGHT;
    if (setting === 'auto') {
      return document.documentElement.getAttribute('data-theme') === 'light' ? LIGHT : DARK;
    }
    return DARK;
  }
  function applyTheme(theme) {
    term.options.theme = theme;
    document.body.style.background = theme.background;
  }

  const term = new Terminal({
    fontFamily: 'Consolas, "Courier New", monospace',
    fontSize: 13,
    cursorBlink: true,
    theme: DARK,
    scrollback: 5000,
    convertEol: false,
  });
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open(document.getElementById('term'));

  let ws = null;
  let seq = 0;
  let attempt = 0;
  let ended = false;

  function send(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  }

  function refit() {
    try {
      fit.fit();
    } catch {
      return;
    }
    send({ type: 'resize', cols: term.cols, rows: term.rows });
  }

  function connect() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(
      proto +
        '//' +
        location.host +
        '/api/terminal/agent?session_id=' +
        encodeURIComponent(sessionId) +
        '&seq=' +
        seq,
    );
    ws.onopen = () => {
      statusEl.textContent = '';
      refit();
      term.focus();
    };
    ws.onmessage = (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type === 'output') {
        if (typeof msg.seq === 'number') seq = msg.seq;
        attempt = 0;
        term.write(msg.data);
      } else if (msg.type === 'exit') {
        ended = true;
        term.write('\r\n\x1b[33m[' + (msg.data || 'Session ended') + ']\x1b[0m\r\n');
        statusEl.textContent = 'Session ended';
      }
    };
    ws.onclose = () => {
      if (ended) return;
      attempt += 1;
      statusEl.textContent = 'Reconnecting...';
      setTimeout(connect, Math.min(1000 * attempt, 5000));
    };
  }

  fetch('/api/config')
    .then((r) => (r.ok ? r.json() : {}))
    .then((cfg) => applyTheme(xtermTheme(cfg.terminal_theme)))
    .catch(() => {});

  term.onData((data) => send({ type: 'input', data }));
  window.addEventListener('resize', refit);
  if (!sessionId) {
    statusEl.textContent = 'No session to show';
  } else {
    connect();
  }
})();
