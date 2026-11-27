"""Project-scoped agent session history, read from the agents' own transcript files.

Nothing is stored: each call reads the head and tail of transcript files that
Claude Code and Codex already keep, and caches the parsed result by
(path, mtime, size).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import agent_handoff as ah
import agent_session_stores
import generic_agent

HEAD_BYTES = 256 * 1024
TAIL_BYTES = 256 * 1024
TITLE_MAX = 120
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
MAX_SESSIONS = 200
MAX_FILES = 300
MAX_CODEX_SCAN = 2000
PREVIEW_EXCHANGES = 6
PREVIEW_CHARS = 600
AGENTS = ("claude", "codex", *agent_session_stores.SCANNERS)
WSL_TTL_SECONDS = 30
WORKTREE_TTL_SECONDS = 30

_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
_SKIP_PREFIXES = (
    "<command-name>",
    "<command-message>",
    "<command-args>",
    "<local-command",
    "Caveat:",
    "[Request interrupted",
    "<user-prompt-submit-hook>",
    "<ide_",
    "<task-notification",
)


def real_user_text(text: str) -> str:
    """The user's own words on one line, or "" for injected boilerplate."""
    t = _REMINDER.sub("", text or "").strip()
    if not t or t.startswith(_SKIP_PREFIXES):
        return ""
    return " ".join(t.split())


def _clip(text: str) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= TITLE_MAX else t[: TITLE_MAX - 1].rstrip() + "…"


def _epoch(iso) -> float | None:
    if not isinstance(iso, str) or not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _json_lines(raw: bytes, drop_first: bool, drop_last: bool) -> list[dict]:
    lines = raw.decode("utf-8", "replace").split("\n")
    if drop_first:
        lines = lines[1:]
    if drop_last:
        lines = lines[:-1]
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _read_head(path: Path) -> list[dict]:
    with open(path, "rb") as fh:
        raw = fh.read(HEAD_BYTES + 1)
    return _json_lines(raw[:HEAD_BYTES], False, len(raw) > HEAD_BYTES)


def _read_tail(path: Path, size: int) -> list[dict]:
    start = max(0, size - TAIL_BYTES)
    with open(path, "rb") as fh:
        fh.seek(start)
        raw = fh.read()
    return _json_lines(raw, start > 0, False)


def _last_value(objs: list[dict], typ: str, field: str) -> str:
    for o in reversed(objs):
        v = o.get(field)
        if o.get("type") == typ and isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _claude_message(o: dict):
    """(role, one-line text) for a real user or assistant turn, else None."""
    if o.get("type") not in ("user", "assistant") or o.get("isMeta"):
        return None
    msg = o.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        parts = [content]
    elif isinstance(content, list):
        parts = [
            b["text"]
            for b in content
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
        ]
    else:
        return None
    text = "\n".join(parts)
    text = real_user_text(text) if o["type"] == "user" else " ".join(text.split())
    return (o["type"], text) if text else None


def _codex_message(o: dict):
    if o.get("type") != "response_item":
        return None
    p = o.get("payload")
    if not isinstance(p, dict) or p.get("type") != "message" or p.get("role") not in ("user", "assistant"):
        return None
    content = p.get("content")
    parts = [
        b["text"]
        for b in (content if isinstance(content, list) else [])
        if isinstance(b, dict) and isinstance(b.get("text"), str)
    ]
    text = "\n".join(parts)
    if p["role"] == "user":
        if text.lstrip().startswith(ah._CODEX_CONTEXT_PREFIXES):
            return None
        text = real_user_text(text)
    else:
        text = " ".join(text.split())
    return (p["role"], text) if text else None


def parse_claude(path: Path, st) -> dict | None:
    """A session record for one Claude transcript, or None when it is not a user session."""
    session_id = path.stem
    if not SESSION_ID_RE.fullmatch(session_id):
        return None
    head = _read_head(path)
    tail = _read_tail(path, st.st_size) if st.st_size > HEAD_BYTES else head
    meta = next((o for o in head if isinstance(o.get("cwd"), str)), None)
    if meta is None or meta.get("isSidechain"):
        return None
    entrypoint = next((str(o["entrypoint"]) for o in head if o.get("entrypoint")), "")
    if entrypoint.startswith("sdk"):
        return None
    first = ""
    for o in head:
        m = _claude_message(o)
        if m and m[0] == "user":
            first = m[1]
            break
    both = head + tail
    title = _last_value(both, "custom-title", "customTitle") or _last_value(both, "ai-title", "aiTitle") or first
    if not title:
        return None
    branch = next((o["gitBranch"] for o in reversed(both) if isinstance(o.get("gitBranch"), str) and o["gitBranch"]), "")
    started = next((t for t in (_epoch(o.get("timestamp")) for o in head) if t), None)
    return {
        "id": session_id,
        "agent": "claude",
        "title": _clip(title),
        "branch": branch,
        "started_at": started or st.st_mtime,
        "last_active_at": st.st_mtime,
        "state": "done",
        "path": str(path),
        "cwd": meta["cwd"],
    }


def codex_meta(path: Path) -> dict | None:
    """The first line's session_meta payload, read without loading the file."""
    try:
        with open(path, "rb") as fh:
            obj = json.loads(fh.readline(HEAD_BYTES))
    except (OSError, ValueError):
        return None
    if not isinstance(obj, dict) or obj.get("type") != "session_meta":
        return None
    payload = obj.get("payload")
    return payload if isinstance(payload, dict) else None


def parse_codex(path: Path, st) -> dict | None:
    """A session record for one Codex rollout, or None when it is not a user session."""
    meta = codex_meta(path)
    if meta is None:
        return None
    session_id = meta.get("id")
    cwd = meta.get("cwd")
    if not isinstance(session_id, str) or not SESSION_ID_RE.fullmatch(session_id) or not isinstance(cwd, str):
        return None
    source = meta.get("source")
    if isinstance(source, dict) and "subagent" in source:
        return None
    first = ""
    for o in _read_head(path):
        m = _codex_message(o)
        if m and m[0] == "user":
            first = m[1]
            break
    if not first:
        return None
    git = meta.get("git") if isinstance(meta.get("git"), dict) else {}
    branch = git.get("branch") if isinstance(git.get("branch"), str) else ""
    return {
        "id": session_id,
        "agent": "codex",
        "title": _clip(first),
        "branch": branch,
        "started_at": _epoch(meta.get("timestamp")) or st.st_mtime,
        "last_active_at": st.st_mtime,
        "state": "done",
        "path": str(path),
        "cwd": cwd,
    }


@dataclass(frozen=True)
class SourceHome:
    source: str
    home: Path
    cwd: str


def _norm_dir(path: str) -> str:
    s = (path or "").replace("\\", "/")
    if s.startswith("//?/"):
        s = s[4:]
    s = s.rstrip("/") or "/"
    if re.match(r"^[A-Za-z]:", s) or s.startswith("//") or s.startswith("/mnt/"):
        s = s.lower()
    return s


def _same_dir(a: str, b: str) -> bool:
    return _norm_dir(a) == _norm_dir(b)


def _slug(cwd: str) -> str:
    if cwd.startswith("\\\\?\\"):
        cwd = cwd[4:]
    return re.sub(r"[^A-Za-z0-9]", "-", cwd).lower()


_MISS = object()
_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 4000


def _cached(kind: str, path: Path, st, parse):
    """Parse once per (kind, path, mtime, size). A file that cannot be read is skipped, not cached."""
    key = (kind, str(path), st.st_mtime_ns, st.st_size)
    with _CACHE_LOCK:
        hit = _CACHE.get(key, _MISS)
    if hit is not _MISS:
        return hit
    try:
        value = parse(path, st)
    except (OSError, ValueError):
        return None
    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.clear()
        _CACHE[key] = value
    return value


def _scan_claude(sh: SourceHome) -> list[dict]:
    slug = _slug(sh.cwd)
    files = []
    try:
        for d in os.scandir(sh.home / ".claude" / "projects"):
            if not d.is_dir() or d.name.lower() != slug:
                continue
            for e in os.scandir(d.path):
                if e.name.endswith(".jsonl") and e.is_file():
                    try:
                        files.append((e.stat(), Path(e.path)))
                    except OSError:
                        continue  # vanished between scandir and stat
    except OSError:
        pass
    files.sort(key=lambda f: f[0].st_mtime, reverse=True)
    out = []
    for st, p in files[:MAX_FILES]:
        rec = _cached("claude", p, st, parse_claude)
        if rec and _same_dir(rec["cwd"], sh.cwd):
            out.append(dict(rec, source=sh.source))
    return out


def _codex_roots(sh: SourceHome) -> list[Path]:
    """Codex keeps rollouts under ~/.codex, but a Codex run from WSL on a Windows
    project can keep them in the project's own .codex folder instead."""
    roots = [sh.home / ".codex" / "sessions"]
    if sh.source == "windows":
        roots.append(Path(sh.cwd) / ".codex" / "sessions")
    return roots


def _codex_source(sh: SourceHome, cwd: str) -> str | None:
    if _same_dir(cwd, sh.cwd):
        return sh.source
    linux_cwd = wsl_cwd(sh.cwd, "") if sh.source == "windows" else None
    if linux_cwd and _same_dir(cwd, linux_cwd):
        distro = generic_agent.wsl_agents()[0]
        return f"wsl:{distro}" if distro else None
    return None


_IMPORT_SETTLE_SECONDS = 120


def _import_time(value) -> float:
    """Seconds since the epoch; Codex may write milliseconds. Anything else is 0 (unknown)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return value / 1000 if value > 1e11 else float(value)


def _parse_codex_imports(path: Path, _st) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    records = data.get("records") if isinstance(data, dict) else None
    return {
        r["imported_thread_id"]: _import_time(r.get("imported_at"))
        for r in records or ()
        if isinstance(r, dict) and isinstance(r.get("imported_thread_id"), str)
    }


def _codex_imports(sh: SourceHome) -> dict:
    """Codex Desktop copies other agents' transcripts (Claude's, here) into new Codex
    threads and records each in this ledger: thread id -> import time."""
    path = sh.home / ".codex" / "external_agent_session_imports.json"
    try:
        st = path.stat()
    except OSError:
        return {}
    return _cached("codex-imports", path, st, _parse_codex_imports) or {}


def _continued_in_codex(path: Path, st, imported_at: float) -> bool:
    """True when the user took an imported thread on in Codex, making it Codex work.
    Reads the whole rollout line by line: the first post-import user turn can sit far
    from the tail once the thread has grown."""
    cutoff = imported_at + _IMPORT_SETTLE_SECONDS
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            m = _codex_message(o) if isinstance(o, dict) else None
            if m and m[0] == "user" and (_epoch(o.get("timestamp")) or 0) > cutoff:
                return True
    return False


def _is_import_copy(p: Path, st, thread_id, imports: dict) -> bool:
    """An untouched copy of another agent's session: the original already has its own
    History row, so the copy would only repeat it."""
    if thread_id not in imports:
        return False
    imported_at = imports[thread_id]
    continued = _cached(
        f"codex-continued:{imported_at}", p, st, lambda path, s: _continued_in_codex(path, s, imported_at)
    )
    return continued is False  # an unreadable rollout stays listed rather than vanishing


def _scan_codex(sh: SourceHome) -> list[dict]:
    imports = _codex_imports(sh)
    files = []
    for root in _codex_roots(sh):
        for dirpath, _dirs, names in os.walk(root):
            for name in names:
                if name.startswith("rollout-") and name.endswith(".jsonl"):
                    p = os.path.join(dirpath, name)
                    try:
                        files.append((os.stat(p), Path(p)))
                    except OSError:
                        continue
    files.sort(key=lambda f: f[0].st_mtime, reverse=True)
    out = []
    for st, p in files[:MAX_CODEX_SCAN]:
        meta = _cached("codex-meta", p, st, lambda path, _st: codex_meta(path))
        source = _codex_source(sh, str(meta.get("cwd") or "")) if meta else None
        if not source or _is_import_copy(p, st, meta.get("id"), imports):
            continue
        rec = _cached("codex", p, st, parse_codex)
        if rec:
            out.append(dict(rec, source=source))
        if len(out) >= MAX_FILES:
            break
    return out


def _store_scanner(agent: str):
    scan = agent_session_stores.SCANNERS[agent]

    def run(sh: SourceHome) -> list[dict]:
        if sh.source != "windows":
            return []
        return [
            dict(rec, agent=agent, source=sh.source, title=_clip(real_user_text(rec["title"])) or "Untitled session")
            for rec in scan(sh.home, sh.cwd, _same_dir)
        ]

    return run


_SCANNERS = {
    "claude": _scan_claude,
    "codex": _scan_codex,
    **{agent: _store_scanner(agent) for agent in agent_session_stores.SCANNERS},
}


_WORKTREES: dict[str, tuple[float, list[str]]] = {}


def project_dirs(repo_path: str) -> list[str]:
    """The project folder plus its git worktrees, when repo_path is the repo's main
    folder: sessions run in a worktree belong to the project they branch from."""
    hit = _WORKTREES.get(repo_path)
    if hit and time.monotonic() - hit[0] < WORKTREE_TTL_SECONDS:
        return list(hit[1])
    dirs = [repo_path]
    try:
        proc = subprocess.run(
            ["git", "-C", repo_path, "worktree", "list", "--porcelain"],
            capture_output=True, text=True, timeout=5, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        listed = [line[len("worktree "):].strip() for line in proc.stdout.splitlines() if line.startswith("worktree ")]
        if listed and _same_dir(listed[0], repo_path):
            dirs += [os.path.normpath(p) for p in listed[1:]]
    except (OSError, subprocess.SubprocessError):
        pass
    _WORKTREES[repo_path] = (time.monotonic(), dirs)
    return list(dirs)


def windows_homes(repo_path: str) -> list[SourceHome]:
    return [SourceHome("windows", Path.home(), d) for d in project_dirs(repo_path)]


def scan_project(repo_path: str, *, homes=None, agents=AGENTS) -> list[dict]:
    homes = windows_homes(repo_path) if homes is None else homes
    out: list[dict] = []
    for sh in homes:
        for agent in agents:
            out.extend(_SCANNERS[agent](sh))
    out.sort(key=lambda r: r["last_active_at"], reverse=True)
    return out[:MAX_SESSIONS]


def find_session(repo_path: str, agent: str, session_id: str, *, homes=None) -> dict | None:
    for rec in [*scan_project(repo_path, homes=homes, agents=(agent,)), *cached_wsl_records(repo_path)]:
        if rec["agent"] == agent and rec["id"] == session_id:
            return rec
    return None


_JOIN_BEFORE = 5
_JOIN_AFTER = 120


def join_live(records: list[dict], live: list[dict]) -> list[dict]:
    """Attach each live terminal to its stored session: by pinned id, else by start time."""
    out = [dict(r) for r in records]
    timed = []
    for lv in live:
        if lv.get("session_id"):
            for r in out:
                if r["agent"] == lv["agent"] and r["id"] == lv["session_id"]:
                    r["pty_session_id"] = lv["pty_session_id"]
        else:
            timed.append(lv)
    candidates = []
    for lv in timed:
        lo, hi = lv["created_at"] - _JOIN_BEFORE, lv["created_at"] + _JOIN_AFTER
        candidates.append([
            i for i, r in enumerate(out)
            if r["agent"] == lv["agent"] and r["source"] == "windows"
            and "pty_session_id" not in r and lo <= r["started_at"] <= hi
        ])
    for lv, cands in zip(timed, candidates):
        if len(cands) != 1:
            continue
        if sum(cands[0] in other for other in candidates) == 1:
            out[cands[0]]["pty_session_id"] = lv["pty_session_id"]
    return out


_PUBLIC_KEYS = (
    "id", "agent", "title", "branch", "started_at", "last_active_at", "state", "source",
    "pty_session_id", "live_elsewhere", "live_elsewhere_in",
)


def public(rec: dict) -> dict:
    return {k: rec[k] for k in _PUBLIC_KEYS if k in rec}


def _transcript_messages(rec: dict) -> list[tuple[str, str]]:
    path = Path(rec["path"])
    extract = _claude_message if rec["agent"] == "claude" else _codex_message
    return [m for m in map(extract, _read_tail(path, path.stat().st_size)) if m]


def _store_messages(rec: dict) -> list[tuple[str, str]]:
    read = agent_session_stores.PREVIEWERS[rec["agent"]]
    try:
        pairs = read(Path(rec["path"]), rec["id"], PREVIEW_EXCHANGES * 4)
    except sqlite3.Error as exc:
        raise OSError(str(exc)) from exc
    return [(role, real_user_text(text) if role == "user" else " ".join(text.split())) for role, text in pairs]


def preview(rec: dict) -> list[dict]:
    messages = _store_messages(rec) if rec["agent"] in agent_session_stores.PREVIEWERS else _transcript_messages(rec)
    merged: list[dict] = []
    for role, text in messages:
        if not text:
            continue
        if merged and merged[-1]["role"] == role:
            merged[-1]["text"] += " " + text
        else:
            merged.append({"role": role, "text": text})
    red = ah.Redactor(ah._configured_api_keys())
    return [{"role": m["role"], "text": red(m["text"])[:PREVIEW_CHARS]} for m in merged[-PREVIEW_EXCHANGES:]]


_WSL: dict[str, tuple[float, list[dict]]] = {}


def wsl_cwd(repo_path: str, distro: str) -> str | None:
    p = (repo_path or "").replace("\\", "/")
    if p.startswith("//?/"):
        p = p[4:]
    unc = re.match(r"^//(?:wsl\.localhost|wsl\$)/([^/]+)(/.*)?$", p, re.I)
    if unc:
        return (unc.group(2) or "/") if unc.group(1).lower() == distro.lower() else None
    drive = re.match(r"^([A-Za-z]):(/.*)?$", p)
    if drive:
        return f"/mnt/{drive.group(1).lower()}{drive.group(2) or ''}".rstrip("/")
    return None


def _wsl_user_homes(distro: str) -> list[Path]:
    try:
        return [Path(d.path) for d in os.scandir(rf"\\wsl.localhost\{distro}\home") if d.is_dir()]
    except OSError:
        return []


def wsl_homes(repo_path: str) -> tuple[list[SourceHome], tuple[str, ...]]:
    distro, found = generic_agent.wsl_agents()
    agents = tuple(a for a in AGENTS if a in found)
    if not distro or not agents:
        return [], ()
    cwds = [c for c in (wsl_cwd(d, distro) for d in project_dirs(repo_path)) if c]
    if not cwds:
        return [], ()
    homes = _wsl_user_homes(distro)
    return [SourceHome(f"wsl:{distro}", home, cwd) for cwd in cwds for home in homes], agents


def _refresh_wsl(repo_path: str) -> None:
    homes, agents = wsl_homes(repo_path)
    records = scan_project(repo_path, homes=homes, agents=agents) if homes else []
    _WSL[repo_path] = (time.monotonic(), records)


def wsl_sessions(repo_path: str) -> tuple[list[dict], bool]:
    """(cached WSL records, pending). Never waits on WSL: a stale or missing entry
    is refreshed on a background thread and the next call sees the result."""
    hit = _WSL.get(repo_path)
    if hit is None or time.monotonic() - hit[0] > WSL_TTL_SECONDS:
        generic_agent._stale_while_revalidate(f"wsl-sessions:{repo_path}", lambda: _refresh_wsl(repo_path))
    return (list(hit[1]) if hit else []), hit is None


def cached_wsl_records(repo_path: str) -> list[dict]:
    hit = _WSL.get(repo_path)
    return list(hit[1]) if hit else []
