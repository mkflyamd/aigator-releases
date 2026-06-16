"""Ephemeral localhost HTTP server to receive an OAuth redirect."""
from __future__ import annotations

import http.server
import logging
import socketserver
import threading
import urllib.parse
from typing import Callable

_log = logging.getLogger(__name__)
_TIMEOUT_SECONDS = 300  # 5 min max wait for user to complete consent

# Registry of active callback listeners so a new flow can evict prior ones.
# Without this, stale listeners hold their ports and answer redirects meant
# for the current flow — keyed to the wrong `state`, the poll never resolves.
_ACTIVE: dict[int, tuple[socketserver.TCPServer, threading.Event]] = {}
_ACTIVE_LOCK = threading.Lock()


def stop_all() -> None:
    """Shut down every callback listener still running. Call before a new flow."""
    with _ACTIVE_LOCK:
        items = list(_ACTIVE.items())
        _ACTIVE.clear()
    for port, (srv, done) in items:
        done.set()
        try:
            srv.server_close()
        except Exception as e:
            _log.warning("[oauth] error closing listener on %s: %s", port, e)
        _log.info("[oauth] evicted stale callback listener on 127.0.0.1:%s", port)


def _try_bind(handler_cls, port: int) -> socketserver.TCPServer | None:
    try:
        # Do NOT set allow_reuse_address — on Windows it would let two
        # listeners coexist on the same port and silently mis-route redirects
        # to whichever one answers first, breaking the in-flight OAuth flow.
        srv = socketserver.TCPServer(("127.0.0.1", port), handler_cls)
        srv.timeout = 1
        return srv
    except OSError as e:
        _log.info("[oauth] could not bind 127.0.0.1:%s — %s", port, e)
        return None


def _js_string_literal(s: str) -> str:
    """Safely embed a string in a JS string literal. Escapes quotes, backslashes,
    and `<` (to defeat any `</script>` injection if the source ever leaks data)."""
    return (
        s.replace("\\", "\\\\")
         .replace("'", "\\'")
         .replace("<", "\\x3c")
         .replace("\n", "\\n")
         .replace("\r", "")
    )


def start_callback_listener(
    on_params: Callable[[dict], tuple[bool, str]],
    port_candidates: list[int] | None = None,
    path: str = "/callback",
    app_origin: str = "",
) -> tuple[int, threading.Event]:
    """Bind a localhost server on the first available candidate port.

    Returns (bound_port, done_event). Raises RuntimeError if no candidate
    port can be bound.
    """
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            _log.info("[oauth-callback] GET %s", self.path)
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != path:
                self.send_response(404)
                self.end_headers()
                return
            params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
            try:
                ok, msg = on_params(params)
            except Exception as e:
                _log.exception("[oauth-callback] on_params raised")
                ok, msg = False, f"Server error: {e}"
            _log.info("[oauth-callback] handled ok=%s state=%r", ok, params.get("state", ""))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            event_type = "oauth-ok" if ok else "oauth-fail"
            # Restrict postMessage target origin. Falling back to '*' would let
            # any window that obtained a reference to our opener intercept the
            # OAuth success/failure signal. If we know the app origin, use it;
            # otherwise omit the postMessage entirely — the frontend polls the
            # backend for status anyway, so postMessage is best-effort.
            if app_origin:
                origin_lit = _js_string_literal(app_origin)
                post_js = (
                    f"window.opener && window.opener.postMessage("
                    f"{{type:'{event_type}'}},'{origin_lit}');"
                )
            else:
                post_js = ""  # polling will pick up the result
            html = (
                "<html><body style='font-family:system-ui;padding:2em;text-align:center'>"
                "<script>"
                f"{post_js}"
                "setTimeout(function(){window.close()},1500);"
                "</script>"
                f"<h2>{'Connected!' if ok else 'Sign-in failed'}</h2>"
                f"<p>{msg}</p><p>You can close this window.</p>"
                "</body></html>"
            )
            self.wfile.write(html.encode())
            done.set()

        def log_message(self, fmt, *args):
            pass

    # Synchronously bind the server here so the caller knows immediately
    # whether the port is available. The serve loop runs in a thread.
    srv = None
    bound_port = None
    for p in port_candidates or [0]:
        srv = _try_bind(Handler, p)
        if srv is not None:
            bound_port = srv.server_address[1]
            break
    if srv is None:
        raise RuntimeError(
            "Could not bind any localhost callback port — close other apps using "
            "ports in the range and retry."
        )
    _log.info("[oauth] callback server listening on 127.0.0.1:%s", bound_port)
    with _ACTIVE_LOCK:
        _ACTIVE[bound_port] = (srv, done)

    def serve():
        try:
            with srv:
                deadline = threading.Event()
                t = threading.Timer(_TIMEOUT_SECONDS, deadline.set)
                t.daemon = True
                t.start()
                try:
                    while not done.is_set() and not deadline.is_set():
                        srv.handle_request()
                finally:
                    t.cancel()
                    if not done.is_set():
                        done.set()
        finally:
            with _ACTIVE_LOCK:
                if _ACTIVE.get(bound_port, (None,))[0] is srv:
                    _ACTIVE.pop(bound_port, None)
        _log.info("[oauth] callback server on 127.0.0.1:%s closed", bound_port)

    th = threading.Thread(target=serve, daemon=True)
    th.start()
    return bound_port, done
