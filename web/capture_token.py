"""Auto-capture a Microsoft Graph Bearer token via Chrome DevTools Protocol.

Opens a temporary Edge window to outlook.office.com and waits for SSO authentication,
intercepts graph.microsoft.com network requests, and returns the token with the best
scope coverage (prefers tokens containing Chat.Read / ChatMessage.Send).
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
import tempfile
import time
import urllib.request
from pathlib import Path

from proc_utils import no_window_kwargs


_EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
_CDP_PORT = 9224
_CAPTURE_URL = "https://outlook.office.com"


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
    header = bytearray([0x81])  # FIN + text
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

def capture_token(timeout: int = 60, status_cb=None) -> str | None:
    """Open Edge → Teams, collect all graph.microsoft.com Bearer tokens and return the best one.

    Navigates to the Teams chat list after page load to trigger Chat.Read-scoped tokens.
    Picks the token that has the most chat-related scopes (Chat.Read, Chat.Create, etc.).

    Args:
        timeout: seconds to wait for the token.
        status_cb: optional callable(str) for progress messages.
    Returns:
        Full 'Bearer ey…' string, or None on failure.
    """
    def _log(msg: str) -> None:
        if status_cb:
            status_cb(msg)

    edge = _find_edge()

    # Reuse a persistent profile for SSO cookie caching (skips re-auth on subsequent captures)
    persistent_dir = Path.home() / ".config" / "aigator" / "edge_capture_profile"
    persistent_dir.mkdir(parents=True, exist_ok=True)
    tmpdir = str(persistent_dir)
    _is_persistent = True
    _log("Opening Outlook in Edge…")

    proc = subprocess.Popen(
        [
            edge,
            f"--remote-debugging-port={_CDP_PORT}",
            f"--user-data-dir={tmpdir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-popup-blocking",
            # NOTE: extensions intentionally kept ON — SSO extensions may be needed for silent login
            # Run off-screen so the window is invisible to the user
            "--window-position=-32000,-32000",
            "--window-size=1,1",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **no_window_kwargs(),
    )

    def _kill() -> None:
        # Force-kill the entire Edge process tree (terminate() alone is not enough on Windows)
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                **no_window_kwargs(),
            )
        except Exception:
            proc.kill()
        # Don't delete persistent profile — keeps SSO cookies for faster re-capture

    try:
        # Wait for CDP HTTP endpoint
        _log("Waiting for browser to start…")
        for _ in range(60):
            try:
                urllib.request.urlopen(
                    f"http://localhost:{_CDP_PORT}/json/version", timeout=1
                )
                break
            except Exception:
                time.sleep(0.25)
        else:
            _log("Browser did not start in time.")
            return None

        # Get a debuggable tab (wait a bit longer — SSO pages can take time)
        tabs = []
        for _ in range(30):
            try:
                all_tabs = json.loads(
                    urllib.request.urlopen(
                        f"http://localhost:{_CDP_PORT}/json/list"
                    ).read()
                )
                # Prefer a page-type tab (not extension background pages)
                tabs = [t for t in all_tabs if t.get("type") == "page"]
                if not tabs:
                    tabs = all_tabs
                if tabs:
                    break
            except Exception:
                pass
            time.sleep(0.25)

        if not tabs:
            _log("No debuggable tab found.")
            return None

        ws_url = tabs[0]["webSocketDebuggerUrl"]
        ws_path = "/" + ws_url.split("/", 3)[3]

        _log("Connected — navigating to Outlook…")
        sock = _ws_connect("localhost", _CDP_PORT, ws_path)
        sock.settimeout(2.0)

        # Enable Network events then navigate to Teams
        _ws_send(sock, json.dumps({"id": 1, "method": "Network.enable", "params": {}}))
        _ws_send(sock, json.dumps({"id": 2, "method": "Page.navigate",
                                   "params": {"url": _CAPTURE_URL}}))

        _log("Waiting for Outlook sign-in and chat token…")

        # Preferred scopes — the token with all of these is ideal
        _WANT = {"Chat.Read", "Chat.ReadWrite", "Chat.Create", "ChatMessage.Send"}

        def _decode_scopes(raw_token: str) -> set[str]:
            """Decode JWT and return the scp claim as a set of scope strings."""
            try:
                payload = raw_token.split(".")[1]
                payload += "=" * (4 - len(payload) % 4)
                claims = json.loads(base64.b64decode(payload))
                return set(claims.get("scp", "").split())
            except Exception:
                return set()

        def _score(scopes: set[str]) -> int:
            """Higher = better. Prefer tokens that contain chat scopes."""
            chat_hits = len(scopes & _WANT)
            return chat_hits * 1000 + len(scopes)

        # Collect all unique tokens until deadline; pick the best-scoring one
        candidates: dict[str, set[str]] = {}  # raw_token → scopes
        deadline = time.time() + timeout
        # After page load, navigate explicitly to the chat list to trigger Chat.Read tokens
        _nav_triggered = False

        while time.time() < deadline:
            msg = _ws_recv(sock)
            if not msg:
                # Once we have at least one token with chat scope, stop early
                if any(scopes & {"Chat.Read", "Chat.ReadWrite"} for scopes in candidates.values()):
                    break
                continue
            try:
                evt = json.loads(msg)
                method = evt.get("method", "")

                # No secondary navigation needed for Outlook — it fires multiple Graph requests
                # covering Chat.Read, Mail, Calendar scopes on initial load
                if not _nav_triggered and method == "Page.loadEventFired":
                    _nav_triggered = True

                if method == "Network.requestWillBeSent":
                    req = evt["params"]["request"]
                    url = req.get("url", "")
                    headers = req.get("headers", {})
                    auth = headers.get("Authorization") or headers.get("authorization", "")
                    if "graph.microsoft.com" in url and auth.startswith("Bearer "):
                        raw = auth[7:] if auth.startswith("Bearer ") else auth
                        if raw not in candidates:
                            scopes = _decode_scopes(raw)
                            candidates[raw] = scopes
                            chat_scopes = scopes & _WANT
                            if chat_scopes:
                                _log(f"Chat token found ({', '.join(sorted(chat_scopes))})!")
                                # Got what we need — exit immediately
                                break
                            else:
                                _log(f"Token collected ({len(scopes)} scopes, no chat scope yet…)")
            except Exception:
                pass

        sock.close()

        if not candidates:
            _log("Timed out — no graph.microsoft.com request seen.")
            return None

        # Pick the token with the highest score (chat scopes first, then most scopes)
        best_raw = max(candidates, key=lambda t: _score(candidates[t]))
        best_scopes = candidates[best_raw]
        chat_hits = best_scopes & _WANT
        if chat_hits:
            _log(f"Using best token with: {', '.join(sorted(chat_hits))}")
        else:
            _log(f"Warning: no chat-scoped token found. Using token with {len(best_scopes)} scopes.")
            _log("To send to new contacts, sign in to teams.microsoft.com, open a chat, then re-capture.")
        return "Bearer " + best_raw

    finally:
        _kill()


if __name__ == "__main__":
    result = capture_token(status_cb=lambda m: print(m, file=sys.stderr))
    if result:
        print(result)
    else:
        sys.exit(1)
