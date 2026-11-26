"""Project-scoped agent session history, read from the agents' own transcript files.

Claude Code and Codex transcripts are indexed once per agent store in
agent_session_index (one row per file, re-parsed only when its mtime or size
changes); a project is then a cwd filter over the indexed rows. Crush and
OpenCode keep sessions in SQLite databases and are read from those directly.
"""
from __future__ import annotations

import json
import logging
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
import agent_session_index as index
import agent_session_stores
import generic_agent

_log = logging.getLogger(__name__)

HEAD_BYTES = 256 * 1024
TAIL_BYTES = 256 * 1024
TITLE_MAX = 120
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
MAX_SESSIONS = 200
PREVIEW_EXCHANGES = 6
PREVIEW_CHARS = 600
AGENTS = ("claude", "codex", *agent_session_stores.SCANNERS)
SYNC_SECONDS = 30
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


def _codex_imports(home: Path) -> dict:
    """Codex Desktop copies other agents' transcripts (Claude's, here) into new Codex
    threads and records each in this ledger: thread id -> import time."""
    path = home / ".codex" / "external_agent_session_imports.json"
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


_SCANNERS = {agent: _store_scanner(agent) for agent in agent_session_stores.SCANNERS}


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


@dataclass(frozen=True)
class Unit:
    """One place transcripts are kept: an agent's folder under one home. Every
    worktree of a project that shares the home shares the unit, so it is walked once."""

    kind: str
    source: str
    home: Path
    root: Path

    @property
    def key(self) -> str:
        return f"{self.source}|{self.kind}|{self.root}"


def _home_units(source: str, home: Path) -> list[Unit]:
    return [
        Unit("claude", source, home, home / ".claude" / "projects"),
        Unit("codex", source, home, home / ".codex" / "sessions"),
    ]


def _units(homes: list[SourceHome]) -> list[Unit]:
    units: list[Unit] = []
    for sh in homes:
        units.append(Unit("claude", sh.source, sh.home, sh.home / ".claude" / "projects"))
        units += [Unit("codex", sh.source, sh.home, root) for i, root in enumerate(_codex_roots(sh)) if i == 0 or root.is_dir()]
    return list(dict.fromkeys(units))


def _slug(cwd: str) -> str:
    """The name Claude Code gives a folder's directory under .claude/projects."""
    if cwd.startswith("\\\\?\\"):
        cwd = cwd[4:]
    return re.sub(r"[^A-Za-z0-9]", "-", cwd).lower()


def _entries(path: str) -> list[os.DirEntry]:
    return list(os.scandir(path))


def _walk(unit: Unit, slugs: frozenset[str] | None = None) -> tuple[dict[str, os.stat_result], set[str]] | None:
    """({path: stat} of the unit's transcript files, folders that could not be read), or
    None when the unit cannot be read at all. A Windows store that does not exist is
    empty; a WSL one that cannot be reached is not known to be. With slugs, only those
    Claude project folders are listed."""
    try:
        top = _entries(str(unit.root))
    except FileNotFoundError:
        return ({}, set()) if unit.source == "windows" else None
    except OSError:
        return None
    claude = unit.kind == "claude"
    files: dict[str, os.stat_result] = {}
    unread: set[str] = set()
    stack = [(top, 0)]
    while stack:
        entries, depth = stack.pop()
        for e in entries:
            try:
                if e.name.endswith(".jsonl") and (depth > 0 if claude else e.name.startswith("rollout-")):
                    if e.is_file():
                        files[e.path] = e.stat()
                elif e.is_dir() and not (claude and (depth > 0 or (slugs is not None and e.name.lower() not in slugs))):
                    try:
                        stack.append((_entries(e.path), depth + 1))
                    except FileNotFoundError:
                        pass
                    except OSError:
                        unread.add(e.path)
            except OSError:
                continue  # vanished between scandir and stat
    return files, unread


def _covered(path: str, unread: set[str], slugs: frozenset[str] | None, claude: bool) -> bool:
    """Whether a walk looked at the folder this file is in, so its absence means it is gone."""
    d = os.path.dirname(path)
    if claude and slugs is not None and os.path.basename(d).lower() not in slugs:
        return False
    while True:
        if d in unread:
            return False
        parent = os.path.dirname(d)
        if parent == d:
            return True
        d = parent


def _transcript_messages(agent: str, path: str, size: int) -> list[tuple[str, str]]:
    extract = _claude_message if agent == "claude" else _codex_message
    return [m for m in map(extract, _read_tail(Path(path), size)) if m]


def _merge(messages: list[tuple[str, str]]) -> list[dict]:
    merged: list[dict] = []
    for role, text in messages:
        if not text:
            continue
        if merged and merged[-1]["role"] == role:
            merged[-1]["text"] += " " + text
        else:
            merged.append({"role": role, "text": text})
    return merged[-PREVIEW_EXCHANGES:]


def _redacted(merged: list[dict], red) -> list[dict]:
    return [{"role": m["role"], "text": red(m["text"])[:PREVIEW_CHARS]} for m in merged]


def _index_row(unit: Unit, path: str, st, red) -> dict | None:
    """The row for one transcript, or None when it cannot be read right now (it is
    tried again on the next refresh). A file that is not a user session still gets a
    row, with no agent, so it is not parsed again until it changes."""
    parse = parse_claude if unit.kind == "claude" else parse_codex
    try:
        rec = parse(Path(path), st)
        merged = _merge(_transcript_messages(unit.kind, path, st.st_size)) if rec else []
    except (OSError, ValueError):
        return None
    row = {
        "path": path, "unit": unit.key, "home": str(unit.home), "source": unit.source,
        "mtime_ns": st.st_mtime_ns, "size": st.st_size,
        "agent": "", "session_id": "", "cwd": "", "cwd_key": "", "title": "", "branch": "",
        "started_at": 0.0, "last_active_at": 0.0, "preview": "[]",
    }
    if rec:
        row.update(
            agent=rec["agent"], session_id=rec["id"], cwd=rec["cwd"], cwd_key=_norm_dir(rec["cwd"]),
            title=rec["title"], branch=rec["branch"], started_at=rec["started_at"],
            last_active_at=rec["last_active_at"], preview=json.dumps(_redacted(merged, red)),
        )
    return row


_SYNC_BATCH = 100
_SYNCED: dict[str, float] = {}
_COLD_LOCK = threading.Lock()


def _stale(key: str) -> bool:
    at = _SYNCED.get(key)
    return at is None or time.monotonic() - at > SYNC_SECONDS


def _wsl_key(repo_path: str) -> str:
    return f"wsl-project|{repo_path}"


_UNIT_LOCKS: dict[str, threading.Lock] = {}


def _sync_unit(unit: Unit, red, slugs: frozenset[str] | None = None) -> bool:
    """Bring one unit's rows up to date: parse only new or changed files and drop the
    rows of files that are gone. A unit that cannot be read, or that another refresh is
    already reading, is left as it is. Returns False when it was left because of that
    other refresh."""
    lock = _UNIT_LOCKS.setdefault(unit.key, threading.Lock())
    if not lock.acquire(blocking=False):
        return False
    try:
        walked = _walk(unit, slugs)
        if walked is None:
            return True
        files, unread = walked
        try:
            known = index.known(unit.key)
            claude = unit.kind == "claude"
            gone = [p for p in known if p not in files and _covered(p, unread, slugs, claude)]
            batch: list[dict] = []
            for path, st in sorted(files.items(), key=lambda f: f[1].st_mtime_ns, reverse=True):
                if known.get(path) == (st.st_mtime_ns, st.st_size):
                    continue
                row = _index_row(unit, path, st, red)
                if row:
                    batch.append(row)
                if len(batch) >= _SYNC_BATCH:
                    index.apply(batch, [])
                    batch = []
            if batch or gone:
                index.apply(batch, gone)
        except sqlite3.Error as exc:
            _log.warning("History index could not be updated: %s", exc)
            _SYNCED.clear()  # the index may have been rebuilt from scratch; check every unit again
            return True
        _SYNCED[unit.key] = time.monotonic()
        return True
    finally:
        lock.release()


def _sync_wsl(repo_path: str, red) -> None:
    """Read this project's folders of the WSL stores. The distro was running a moment
    ago; each Claude store is listed only for the project's own folders so the read is
    short and does not scan every project in the distro."""
    try:
        homes, agents = wsl_homes(repo_path)
    except WslStopped:
        homes, agents = [], ()
    slugs = frozenset(_slug(sh.cwd) for sh in homes)
    done = True
    for unit in _units(homes):
        if unit.kind in agents:
            done = _sync_unit(unit, red, slugs) and done
    if done:
        _SYNCED[_wsl_key(repo_path)] = time.monotonic()


def refresh_index(repo_path: str, *, homes=None, only_stale: bool = False, include_wsl: bool = True) -> None:
    """Re-read the transcript stores behind a project into the index. WSL stores are
    read only while the distro is running, and only for the agents found in it; a WSL
    Claude store is listed for the project's own folders only."""
    own = homes is None
    red = ah.Redactor(ah._configured_api_keys())
    for unit in _units(windows_homes(repo_path) if own else homes):
        if not only_stale or _stale(unit.key):
            _sync_unit(unit, red)
    if own and include_wsl and _wsl_context(repo_path) and (not only_stale or _stale(_wsl_key(repo_path))):
        _sync_wsl(repo_path, red)


def _built_units() -> set[str]:
    try:
        return index.populated()
    except sqlite3.Error:
        return set()


def ensure_fresh(repo_path: str) -> None:
    """Called by each History request, so nothing runs while the panel is closed. The
    first ever build blocks, because there is nothing to show yet; after that a stale
    index is refreshed on a background thread and the request is served from the index."""
    units = _units(windows_homes(repo_path))
    wsl = _wsl_context(repo_path) is not None

    def needs_refresh() -> bool:
        return any(_stale(u.key) for u in units) or (wsl and _stale(_wsl_key(repo_path)))

    if not needs_refresh():
        return
    if any(u.key not in _SYNCED for u in units):
        with _COLD_LOCK:
            built = _built_units()
            if not any(u.key in _SYNCED or u.key in built for u in units):
                refresh_index(repo_path, only_stale=True, include_wsl=False)
    if needs_refresh():
        generic_agent._stale_while_revalidate(
            f"history-index:{repo_path}", lambda: refresh_index(repo_path, only_stale=True)
        )


def touch(path, units: list[Unit] | None = None) -> None:
    """Re-index one Windows-side transcript now instead of waiting for the next refresh."""
    p = Path(path)
    for unit in units or _home_units("windows", Path.home()):
        if unit.source != "windows" or unit.root not in p.parents or not p.name.endswith(".jsonl"):
            continue
        try:
            st = p.stat()
        except OSError:
            index.apply([], [str(p)])
            return
        row = _index_row(unit, str(p), st, ah.Redactor(ah._configured_api_keys()))
        if row:
            index.apply([row], [])
        return


def _indexed(homes: list[SourceHome], agent: str, *, session_id: str | None = None, with_preview: bool = False) -> list[dict]:
    """The indexed sessions of one agent that belong to these project folders."""
    out: list[dict] = []
    for source in dict.fromkeys(sh.source for sh in homes):
        group = [sh for sh in homes if sh.source == source]
        here = {_norm_dir(sh.cwd): sh for sh in group}
        linux = {}
        if source == "windows" and agent == "codex":
            linux = {_norm_dir(c): sh for sh in group if (c := wsl_cwd(sh.cwd, ""))}
        try:
            rows = index.rows(source, agent, [*here, *linux], session_id=session_id, with_preview=with_preview)
        except sqlite3.Error as exc:
            _log.warning("History index could not be read: %s", exc)
            _SYNCED.clear()
            continue
        ledgers: dict[str, dict] = {}
        for r in rows:
            sh = here.get(r["cwd_key"]) or linux.get(r["cwd_key"])
            if sh is None:
                continue
            rec_source = _codex_source(sh, r["cwd"]) if agent == "codex" else source
            if not rec_source:
                continue
            if agent == "codex" and source == "windows":
                ledger = ledgers.setdefault(r["home"], _codex_imports(Path(r["home"])))
                if r["session_id"] in ledger:
                    path = Path(r["path"])
                    try:
                        if _is_import_copy(path, path.stat(), r["session_id"], ledger):
                            continue
                    except OSError:
                        continue
            rec = {
                "id": r["session_id"], "agent": agent, "title": r["title"], "branch": r["branch"],
                "started_at": r["started_at"], "last_active_at": r["last_active_at"], "state": "done",
                "path": r["path"], "cwd": r["cwd"], "source": rec_source,
                "indexed_source": r["source"], "mtime_ns": r["mtime_ns"], "size": r["size"],
            }
            if with_preview:
                rec["preview"] = json.loads(r["preview"])
            out.append(rec)
    return out


_INDEX_KEYS = ("indexed_source", "mtime_ns", "size")


def _without_index_keys(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if k not in _INDEX_KEYS}


def scan_project(repo_path: str, *, homes=None, agents=AGENTS) -> list[dict]:
    """The project's sessions, newest first, read from the index (see ensure_fresh)."""
    homes = windows_homes(repo_path) if homes is None else homes
    out: list[dict] = []
    for agent in agents:
        if agent in _SCANNERS:
            for sh in homes:
                out.extend(_SCANNERS[agent](sh))
        else:
            out.extend(_indexed(homes, agent))
    out.sort(key=lambda r: r["last_active_at"], reverse=True)
    return [_without_index_keys(r) for r in out[:MAX_SESSIONS]]


def _lookup(agent: str, session_id: str, homes: list[SourceHome]) -> list[dict]:
    if agent in _SCANNERS:
        return [r for sh in homes for r in _SCANNERS[agent](sh) if r["id"] == session_id]
    return _indexed(homes, agent, session_id=session_id, with_preview=True)


def _changed_on_disk(rec: dict) -> bool:
    """Whether a Windows-side transcript has been written to since it was indexed.
    WSL files are not looked at: that would start the distro."""
    if rec["indexed_source"] != "windows":
        return False
    try:
        st = os.stat(rec["path"])
    except OSError:
        return True
    return (st.st_mtime_ns, st.st_size) != (rec["mtime_ns"], rec["size"])


def find_session(repo_path: str, agent: str, session_id: str, *, homes=None) -> dict | None:
    """One session of this project, current as of now: a transcript changed since the
    last refresh is re-indexed first, so callers that run while nobody is viewing
    History do not see an old last_active_at."""
    homes = windows_homes(repo_path) if homes is None else homes
    found = _lookup(agent, session_id, [*homes, *_wsl_query_homes(repo_path)])
    if found and agent not in _SCANNERS and _changed_on_disk(found[0]):
        touch(found[0]["path"], _units(homes))
        found = _lookup(agent, session_id, [*homes, *_wsl_query_homes(repo_path)])
    if not found and agent not in _SCANNERS:
        refresh_index(repo_path, homes=homes)  # the session is newer than the last refresh
        found = _lookup(agent, session_id, homes)
    return _without_index_keys(found[0]) if found else None


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


_PUBLIC_KEYS = ("id", "agent", "title", "branch", "started_at", "last_active_at", "state", "source", "pty_session_id")


def public(rec: dict) -> dict:
    return {k: rec[k] for k in _PUBLIC_KEYS if k in rec}


def _store_messages(rec: dict) -> list[tuple[str, str]]:
    read = agent_session_stores.PREVIEWERS[rec["agent"]]
    try:
        pairs = read(Path(rec["path"]), rec["id"], PREVIEW_EXCHANGES * 4)
    except sqlite3.Error as exc:
        raise OSError(str(exc)) from exc
    return [(role, real_user_text(text) if role == "user" else " ".join(text.split())) for role, text in pairs]


def preview(rec: dict) -> list[dict]:
    """The last few exchanges: from the index for transcript agents, from the agent's
    own database for the SQLite ones."""
    merged = _merge(_store_messages(rec)) if rec["agent"] in agent_session_stores.PREVIEWERS else rec["preview"]
    return _redacted(merged, ah.Redactor(ah._configured_api_keys()))


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


class WslStopped(Exception):
    """The distro is not running; reading its files over \\\\wsl.localhost would start it."""


def _wsl_context(repo_path: str) -> tuple[str, list[str], tuple[str, ...]] | None:
    """(distro, the project's folders as the distro sees them, its agents), or None when
    the project has no WSL side. Reads saved state only; it never starts the distro."""
    distro, found = generic_agent.wsl_agents()
    agents = tuple(a for a in AGENTS if a in found)
    if not distro or not agents:
        return None
    cwds = [c for c in (wsl_cwd(d, distro) for d in project_dirs(repo_path)) if c]
    return (distro, cwds, agents) if cwds else None


def _wsl_query_homes(repo_path: str) -> list[SourceHome]:
    """The project's WSL folders, to filter indexed rows by. Their home is not needed to query."""
    context = _wsl_context(repo_path)
    if context is None:
        return []
    return [SourceHome(f"wsl:{context[0]}", Path("/"), cwd) for cwd in context[1]]


def wsl_homes(repo_path: str) -> tuple[list[SourceHome], tuple[str, ...]]:
    context = _wsl_context(repo_path)
    if context is None:
        return [], ()
    distro, cwds, agents = context
    if not generic_agent.wsl_distro_running(distro):
        raise WslStopped
    homes = _wsl_user_homes(distro)
    return [SourceHome(f"wsl:{distro}", home, cwd) for cwd in cwds for home in homes], agents


def wsl_sessions(repo_path: str) -> tuple[list[dict], bool]:
    """(indexed WSL sessions, pending). Never touches WSL: the index is refreshed on a
    background thread and only while the distro is running, so a stopped distro stays
    stopped and its last-seen sessions are still listed. Pending is true until the
    first refresh of this run has finished."""
    context = _wsl_context(repo_path)
    if context is None:
        return [], False
    return scan_project(repo_path, homes=_wsl_query_homes(repo_path), agents=context[2]), _wsl_key(repo_path) not in _SYNCED
