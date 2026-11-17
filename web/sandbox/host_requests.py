"""Server-side store of "run on my machine" requests.

The model can only create a pending request (run_on_host). A command runs only
when the user clicks Run on the card, which calls the CSRF-guarded route in
routes/host_shell_routes.py. Every request is single use: it runs once, for the
tab that asked, and expires 10 minutes after it was created. In-memory
(single-process desktop backend): a restart forgets pending requests, which only
means asking again.
"""
from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass

from proc_utils import kill_process_tree

REQUEST_TTL_SECONDS = 600
RESULT_TTL_SECONDS = 1800
OUTPUT_LIMIT = 20_000

_SECRET_NAME = re.compile(
    r"TOKEN|SECRET|PASSW|CREDENTIAL|KEY|COOKIE|(?:^|_)PAT(?:$|_)|_AUTH$|^DATABASE_URL$"
    r"|^PYTHON(?:HOME|PATH)$|^(?:AIGATOR|GATEWAY|LLM_GATEWAY|JIRA|CONFLUENCE)",
    re.IGNORECASE,
)

# Control (except tab, newline, return), ANSI escape, bidi override and zero-width characters: invisible or
# misleading on a card, so a command that holds one is refused instead of shown.
_HIDDEN_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u2028\u2029\u200b-\u200f\u202a-\u202e\u2060\u2066-\u2069\ufeff]")

_RISKS = (
    ("Pushes commits to a remote", re.compile(r"\bgit\b[^\n;|&]*?\bpush\b", re.IGNORECASE)),
    ("Can discard local changes", re.compile(r"\bgit\b[^\n;|&]*?(?:\bclean\b|\breset\b[^\n;|&]*--hard|\bcheckout\b[^\n;|&]*\s-f\b)", re.IGNORECASE)),
    ("Publishes a package", re.compile(r"\b(?:(?:npm|pnpm|yarn)\s+publish|twine\s+upload|cargo\s+publish)\b", re.IGNORECASE)),
    ("Changes GitHub", re.compile(
        r"\bgh\s+(?:(?:pr|issue|release|repo|gist|workflow)\s+(?:create|merge|close|delete|edit|comment|upload|run|rename|archive)"
        r"|api\b[^\n;|&]*(?:-X|--method)\s*(?:POST|PUT|PATCH|DELETE))\b", re.IGNORECASE)),
    ("Runs downloaded code", re.compile(r"\|\s*(?:sh|bash|zsh|iex|Invoke-Expression)\b", re.IGNORECASE)),
)


class HostRequestError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code


@dataclass
class HostRequest:
    id: str
    context_id: str
    command: str
    cwd: str
    shell: str
    reason: str
    timeout: int
    risks: tuple[str, ...]
    created_at: float
    status: str = "pending"  # pending | running | done | denied
    result: dict | None = None
    finished_at: float = 0.0
    proc: object | None = None
    stopped: bool = False


_LOCK = threading.Lock()
_REQUESTS: dict[str, HostRequest] = {}


def risk_flags(command: str) -> tuple[str, ...]:
    return tuple(label for label, pattern in _RISKS if pattern.search(command))


def host_env(environ) -> dict[str, str]:
    """The user's own environment (PATH, proxy, certificates, login) minus secrets and settings the app holds."""
    return {k: v for k, v in environ.items() if not _SECRET_NAME.search(k)}


def has_hidden_characters(text: str) -> bool:
    return bool(_HIDDEN_CHARS.search(text))


def strip_hidden_characters(text: str) -> str:
    return _HIDDEN_CHARS.sub(" ", text)


def _purge(now: float) -> None:
    for rid in [r.id for r in _REQUESTS.values()
                if now - (r.finished_at or r.created_at) > (RESULT_TTL_SECONDS if r.finished_at else 2 * REQUEST_TTL_SECONDS)]:
        del _REQUESTS[rid]


def create(context_id: str, command: str, cwd: str, shell: str, reason: str, timeout: int,
           now: float | None = None) -> HostRequest:
    now = time.time() if now is None else now
    req = HostRequest(
        id=uuid.uuid4().hex, context_id=context_id or "", command=command, cwd=cwd, shell=shell,
        reason=reason, timeout=timeout, risks=risk_flags(command), created_at=now,
    )
    with _LOCK:
        _purge(now)
        _REQUESTS[req.id] = req
    return req


def _owned(request_id: str, context_id: str) -> HostRequest:
    req = _REQUESTS.get(request_id)
    if req is None:
        raise HostRequestError(404, "This command request was not found or has expired. Ask AI Gator to propose it again.")
    if req.context_id != (context_id or ""):
        raise HostRequestError(409, "This command request belongs to a different tab.")
    return req


def claim(request_id: str, context_id: str, now: float | None = None) -> HostRequest:
    """pending -> running. Raises unless the request is pending, unexpired and this tab's."""
    now = time.time() if now is None else now
    with _LOCK:
        req = _owned(request_id, context_id)
        if req.status != "pending":
            raise HostRequestError(409, f"This command request was already {req.status}.")
        if now - req.created_at > REQUEST_TTL_SECONDS:
            raise HostRequestError(410, "This command request expired (requests last 10 minutes). Ask AI Gator to propose it again.")
        req.status = "running"
        return req


def finish(request_id: str, result: dict, now: float | None = None) -> None:
    with _LOCK:
        req = _REQUESTS.get(request_id)
        if req is not None:
            req.status, req.result, req.finished_at = "done", result, time.time() if now is None else now
            req.proc = None


def attach(request_id: str, proc) -> None:
    """Remember the running process so Stop and app quit can kill it; kill it now if Stop already came."""
    with _LOCK:
        req = _REQUESTS.get(request_id)
        if req is None:
            return
        req.proc = proc
        kill_now = req.stopped
    if kill_now:
        kill_process_tree(proc)


def stop(request_id: str, context_id: str) -> HostRequest:
    """Kill the whole process tree of a running request. Raises unless it is running and this tab's."""
    with _LOCK:
        req = _owned(request_id, context_id)
        if req.status != "running":
            raise HostRequestError(409, f"This command request is {req.status}, not running.")
        req.stopped = True
        proc = req.proc
    if proc is not None:
        kill_process_tree(proc)
    return req


def stop_all() -> None:
    """App quit: kill every command still running."""
    with _LOCK:
        running = [r for r in _REQUESTS.values() if r.status == "running"]
        for req in running:
            req.stopped = True
        procs = [r.proc for r in running if r.proc is not None]
    for proc in procs:
        kill_process_tree(proc)


def deny(request_id: str, context_id: str, now: float | None = None) -> HostRequest:
    now = time.time() if now is None else now
    with _LOCK:
        req = _owned(request_id, context_id)
        if req.status != "pending":
            raise HostRequestError(409, f"This command request was already {req.status}.")
        req.status, req.finished_at = "denied", now
        return req


def lookup(request_id: str, context_id: str, now: float | None = None) -> tuple[str, HostRequest | None]:
    """(status, request) for the tab that asked: pending | running | done | denied | expired | none."""
    now = time.time() if now is None else now
    with _LOCK:
        req = _REQUESTS.get(request_id)
        if req is None or req.context_id != (context_id or ""):
            return "none", None
        if req.status == "pending" and now - req.created_at > REQUEST_TTL_SECONDS:
            return "expired", req
        return req.status, req


def _reset() -> None:
    with _LOCK:
        _REQUESTS.clear()
