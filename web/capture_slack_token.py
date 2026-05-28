"""Auto-capture Slack xoxc- token and xoxd- cookie via Chrome DevTools Protocol.

Opens a temporary Edge window to app.slack.com, waits for Slack to load and
authenticate, then extracts the xoxc- token from the WebSocket URL and the
xoxd- cookie from browser storage.

No external dependencies — pure Python stdlib.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


_EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
_CDP_PORT = 9225  # Different port from Teams capture to avoid conflicts
_CAPTURE_URL = "https://app.slack.com"


def _find_edge() -> str:
    for c in _EDGE_CANDIDATES:
        if Path(c).exists():
            return c
    return "msedge"


# ── Minimal stdlib WebSocket client ──────────────────────────────────────────

def _ws_send(sock: socket.socket, message: str) -> None:
    data = message.encode()
    mask = os.urandom(4)
    n = len(data)
    header = bytearray([0x81])
    if n < 126:
        header.append(0x80 | n)
    elif n < 65536:
        header.append(0x80 | 126)
        header.extend(n.to_bytes(2, "big"))
    else:
        header.append(0x80 | 127)
        header.extend(n.to_bytes(8, "big"))
    header.extend(mask)
    payload = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    sock.sendall(bytes(header) + payload)


def _ws_recv(sock: socket.socket) -> str | None:
    try:
        hdr = b""
        while len(hdr) < 2:
            chunk = sock.recv(2 - len(hdr))
            if not chunk:
                return None
            hdr += chunk
        masked = bool(hdr[1] & 0x80)
        length = hdr[1] & 0x7F
        if length == 126:
            ext = b""
            while len(ext) < 2:
                ext += sock.recv(2 - len(ext))
            length = int.from_bytes(ext, "big")
        elif length == 127:
            ext = b""
            while len(ext) < 8:
                ext += sock.recv(8 - len(ext))
            length = int.from_bytes(ext, "big")
        mask_bytes = b""
        if masked:
            while len(mask_bytes) < 4:
                mask_bytes += sock.recv(4 - len(mask_bytes))
        body = b""
        while len(body) < length:
            body += sock.recv(min(4096, length - len(body)))
        if masked:
            body = bytes(b ^ mask_bytes[i % 4] for i, b in enumerate(body))
        return body.decode("utf-8", errors="replace")
    except Exception:
        return None


def _ws_connect(host: str, port: int, path: str) -> socket.socket:
    sock = socket.create_connection((host, port), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    handshake = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(handshake.encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += sock.recv(4096)
    return sock


# ── Main capture function ─────────────────────────────────────────────────────

_JS_GET_TOKEN = """
(function() {
    try {
        // Determine the active team_id from the current URL or TS boot data.
        // app.slack.com/client/TXXXXXXX/... — team ID is the first path segment after /client/
        var activeTeamId = '';
        var pathMatch = location.pathname.match(/\\/client\\/([A-Z0-9]+)/);
        if (pathMatch) activeTeamId = pathMatch[1];
        if (!activeTeamId && window.TS && window.TS.boot_data && window.TS.boot_data.team_id)
            activeTeamId = window.TS.boot_data.team_id;

        // Method 1: window.TS global — only use if it matches the active team
        if (window.TS && window.TS.model && window.TS.model.token &&
                window.TS.model.token.startsWith('xoxc-')) {
            var tsTeam = (window.TS.model.team && window.TS.model.team.id) || activeTeamId;
            if (!activeTeamId || tsTeam === activeTeamId)
                return JSON.stringify({token: window.TS.model.token, team_id: tsTeam});
        }

        // Method 2: scan localStorage, match by team_id when possible
        var fallback = null;
        for (var i = 0; i < localStorage.length; i++) {
            try {
                var v = JSON.parse(localStorage.getItem(localStorage.key(i)));
                if (!v) continue;
                var tok = (typeof v.token === 'string' && v.token.startsWith('xoxc-')) ? v.token : null;
                if (!tok && v.tokens)
                    for (var t of Object.values(v.tokens))
                        if (typeof t === 'string' && t.startsWith('xoxc-')) { tok = t; break; }
                if (!tok) continue;
                var tid = v.team_id || '';
                if (activeTeamId && tid === activeTeamId)
                    return JSON.stringify({token: tok, team_id: tid});
                if (!fallback) fallback = {token: tok, team_id: tid};
            } catch(e) {}
        }
        if (fallback) return JSON.stringify(fallback);
    } catch(e) {}
    return '';
})()
"""


def capture_slack_token(timeout: int = 90, status_cb=None) -> tuple[str, str] | None:
    """Open Edge → app.slack.com, capture xoxc- token and xoxd- cookie.

    Strategy (in order):
      1. After page load fires, read xoxc- token from window.TS / localStorage
         via Runtime.evaluate — works even if WebSocket was already open.
      2. Also listen for Network.webSocketCreated events as a backup.
      3. Fetch cookies via Network.getAllCookies and filter for name='d'.

    Returns:
        (xoxc_token, xoxd_cookie) tuple, or None on failure.
    """
    def _log(msg: str) -> None:
        if status_cb:
            status_cb(msg)

    edge = _find_edge()
    profile_dir = Path.home() / ".config" / "slack" / "edge_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    _log("Opening Slack in Edge…")

    proc = subprocess.Popen(
        [
            edge,
            f"--remote-debugging-port={_CDP_PORT}",
            f"--user-data-dir={str(profile_dir)}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-popup-blocking",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    def _kill() -> None:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            proc.kill()
        # Profile directory kept — preserves Slack session for future captures

    try:
        # Wait for CDP HTTP endpoint
        _log("Waiting for browser to start…")
        for _ in range(40):
            try:
                urllib.request.urlopen(f"http://localhost:{_CDP_PORT}/json/version", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            _log("Browser did not start in time.")
            return None

        # Get a debuggable page tab
        tabs = []
        for _ in range(20):
            try:
                all_tabs = json.loads(
                    urllib.request.urlopen(f"http://localhost:{_CDP_PORT}/json/list").read()
                )
                tabs = [t for t in all_tabs if t.get("type") == "page"] or all_tabs
                if tabs:
                    break
            except Exception:
                pass
            time.sleep(0.5)

        if not tabs:
            _log("No debuggable tab found.")
            return None

        ws_url = tabs[0]["webSocketDebuggerUrl"]
        ws_path = "/" + ws_url.split("/", 3)[3]

        sock = _ws_connect("localhost", _CDP_PORT, ws_path)
        sock.settimeout(2.0)

        # Enable domains — wait for each ack before navigating so no events are missed
        for cmd_id, method in [(1, "Network.enable"), (2, "Runtime.enable"), (3, "Page.enable")]:
            _ws_send(sock, json.dumps({"id": cmd_id, "method": method, "params": {}}))
        # Drain acks (up to 2s) then navigate — ensures Network events are live
        deadline_ack = time.time() + 2
        while time.time() < deadline_ack:
            _ws_recv(sock)

        _log("Navigating to Slack — sign in if prompted, then switch to your workspace…")
        _ws_send(sock, json.dumps({"id": 4, "method": "Page.navigate",
                                   "params": {"url": _CAPTURE_URL}}))

        xoxc_token: str | None = None
        xoxd_cookie: str | None = None
        eval_sent = False
        cookies_sent = False
        deadline = time.time() + timeout
        _cmd_id = 20
        _eval_id: int | None = None
        _cookies_id: int | None = None

        def _send_eval() -> None:
            nonlocal _cmd_id, _eval_id, eval_sent
            if eval_sent:
                return
            eval_sent = True
            _cmd_id += 1
            _eval_id = _cmd_id
            _ws_send(sock, json.dumps({
                "id": _eval_id,
                "method": "Runtime.evaluate",
                "params": {"expression": _JS_GET_TOKEN, "returnByValue": True},
            }))

        def _send_cookies() -> None:
            nonlocal _cmd_id, _cookies_id, cookies_sent
            if cookies_sent:
                return
            cookies_sent = True
            _cmd_id += 1
            _cookies_id = _cmd_id
            _ws_send(sock, json.dumps({
                "id": _cookies_id,
                "method": "Network.getAllCookies",
                "params": {},
            }))

        while time.time() < deadline:
            if xoxc_token and xoxd_cookie:
                break

            msg = _ws_recv(sock)
            if not msg:
                continue
            try:
                evt = json.loads(msg)
            except Exception:
                continue

            method = evt.get("method", "")
            evt_id = evt.get("id")

            # Page fully loaded → try reading token from JS context
            if method in ("Page.loadEventFired", "Page.frameStoppedLoading"):
                _log("Page loaded — reading token from Slack…")
                _send_eval()

            # Also trigger on URL navigation to a Slack workspace
            if method == "Page.frameNavigated":
                nav_url = evt.get("params", {}).get("frame", {}).get("url", "")
                if "slack.com" in nav_url and nav_url != _CAPTURE_URL:
                    _log(f"Navigated to workspace — reading token…")
                    # Give the page a moment to initialise JS
                    time.sleep(2)
                    eval_sent = False   # allow re-send for new page
                    _send_eval()

            # Runtime.evaluate response — JS returns JSON {token, team_id}
            if evt_id is not None and evt_id == _eval_id and "result" in evt:
                val = (evt["result"].get("result") or {}).get("value", "")
                if val:
                    try:
                        parsed = json.loads(val)
                        tok = parsed.get("token", "") if isinstance(parsed, dict) else ""
                        tid = parsed.get("team_id", "") if isinstance(parsed, dict) else ""
                    except Exception:
                        tok = val if val.startswith("xoxc-") else ""
                        tid = ""
                    if tok and tok.startswith("xoxc-"):
                        xoxc_token = tok
                        team_hint = f" (workspace {tid})" if tid else ""
                        _log(f"Token read from localStorage: {xoxc_token[:20]}…{team_hint}")
                        _send_cookies()
                        continue
                # Page not ready yet — retry in 3s
                _log("Token not found yet — retrying in 3s…")
                time.sleep(3)
                eval_sent = False
                _send_eval()

            # Network.getAllCookies response
            if evt_id is not None and evt_id == _cookies_id and "result" in evt:
                for c in evt["result"].get("cookies", []):
                    if c.get("name") == "d" and "slack.com" in c.get("domain", ""):
                        val = c.get("value", "")
                        if val.startswith("xoxd-"):
                            xoxd_cookie = val
                            _log(f"Cookie captured: {xoxd_cookie[:20]}…")
                            break

            # Backup: WebSocket URL contains token
            if method == "Network.webSocketCreated" and not xoxc_token:
                url = evt["params"].get("url", "")
                if "slack.com" in url and "token=xoxc-" in url:
                    parsed = urllib.parse.urlparse(url)
                    token_val = urllib.parse.parse_qs(parsed.query).get("token", [None])[0]
                    if token_val and token_val.startswith("xoxc-"):
                        xoxc_token = token_val
                        _log(f"Token from WebSocket URL: {xoxc_token[:20]}…")
                        _send_cookies()

        sock.close()

        if not xoxc_token:
            _log("Timed out — could not find Slack token. Make sure you navigated to your workspace.")
            return None
        if not xoxd_cookie:
            _log("Token found but xoxd cookie missing — returning token only.")
            return xoxc_token, ""

        _log("Captured successfully!")
        return xoxc_token, xoxd_cookie

    finally:
        _kill()


if __name__ == "__main__":
    result = capture_slack_token(status_cb=lambda m: print(m, file=sys.stderr))
    if result:
        token, cookie = result
        print(f"TOKEN: {token}")
        print(f"COOKIE: {cookie[:30]}…")
    else:
        sys.exit(1)
