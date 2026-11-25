"""probe_local_url: a read-only GET to a loopback address a run printed.

Any command can print any URL, so the printed-URL list is not trusted on its own. The gate is here:
loopback only (resolved once and pinned), http only, GET only, no redirects, no credentials, no
Gator backend or container-control ports, short timeout, capped body.
"""
from __future__ import annotations

import http.client
import ipaddress
import os
import socket
import time
from urllib.parse import urlsplit

MAX_PROBES_PER_RUN = 10
BODY_CAP_BYTES = 16 * 1024
TIMEOUT_SECONDS = 5
_LOOPBACK_NAMES = ("127.0.0.1", "localhost", "::1")
_CONTROL_PORTS = frozenset({2375, 2376})


class ProbeRefused(Exception):
    """The probe was not made. The message says why, in words the model can act on."""


def backend_ports() -> set[int]:
    """Ports this backend is listening on, read from the live process at call time."""
    ports: set[int] = set()
    try:
        import psutil

        me = psutil.Process()
        getter = getattr(me, "net_connections", None) or me.connections
        ports |= {c.laddr.port for c in getter(kind="tcp") if c.status == psutil.CONN_LISTEN and c.laddr}
    except Exception:
        pass
    configured = os.environ.get("AIGATOR_PORT", "")
    if configured.isdigit():
        ports.add(int(configured))
    return ports


def _origin(url: str) -> tuple[str, int] | None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    host = "127.0.0.1" if parts.hostname == "localhost" else parts.hostname
    try:
        return host, parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return None


def check(url: str, urls_seen: list[str], blocked_ports: set[int]) -> tuple[str, int, str]:
    """Validate the URL. Returns (host, port, path) or raises ProbeRefused."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise ProbeRefused("That is not a valid URL.") from None
    if parts.scheme != "http":
        raise ProbeRefused("Only http URLs can be probed.")
    if parts.username is not None or parts.password is not None:
        raise ProbeRefused("URLs with a user name or password cannot be probed.")
    if (parts.hostname or "") not in _LOOPBACK_NAMES:
        raise ProbeRefused("Only 127.0.0.1, localhost and [::1] can be probed.")
    port = port or 80
    if port in blocked_ports or port in _CONTROL_PORTS:
        raise ProbeRefused("That port belongs to AI Gator or to container control and cannot be probed.")
    wanted = _origin(url)
    if not any(_origin(seen) == wanted for seen in urls_seen):
        raise ProbeRefused("That address was not printed by this run. Only addresses a run printed can be probed.")
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return parts.hostname, port, path


def _pin(host: str, port: int) -> list[str]:
    """Resolve once; every address must be loopback. Returns the addresses to try, in order."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = [info[4][0] for info in infos]
    if not addresses or not all(ipaddress.ip_address(a).is_loopback for a in addresses):
        raise ProbeRefused("That name does not resolve to a loopback address.")
    return list(dict.fromkeys(addresses))


def probe(url: str, urls_seen: list[str], blocked_ports: set[int] | None = None) -> dict:
    """One GET. Returns the response as facts; the body is untrusted text."""
    host, port, path = check(url, urls_seen, backend_ports() if blocked_ports is None else blocked_ports)
    started = time.monotonic()
    failure = "ConnectionRefusedError"
    for address in _pin(host, port):
        conn = http.client.HTTPConnection(address, port, timeout=TIMEOUT_SECONDS)
        try:
            conn.request("GET", path, headers={"Host": f"{host}:{port}", "Accept": "*/*", "Connection": "close"})
            response = conn.getresponse()
            body = response.read(BODY_CAP_BYTES + 1)
            headers = {k.lower(): v for k, v in response.getheaders()}
            break
        except (OSError, http.client.HTTPException) as exc:
            failure = type(exc).__name__
        finally:
            conn.close()
    else:
        return {"url": url, "reached": False, "error": failure,
                "elapsed_ms": int((time.monotonic() - started) * 1000)}
    result = {
        "url": url, "reached": True, "status": response.status,
        "content_type": headers.get("content-type", ""),
        "body": body[:BODY_CAP_BYTES].decode("utf-8", "replace"), "body_truncated": len(body) > BODY_CAP_BYTES,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }
    if 300 <= response.status < 400:
        result["redirect_to"] = headers.get("location", "")
    return result
