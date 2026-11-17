# Agent Session History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the left panel's two text tabs with Files / Changes / History icon tabs, and add a project-scoped History list of past and live agent sessions (search, day groups, live states, redacted in-place preview, Resume, and "Continue in another agent…").

**Architecture:** A new `web/agent_sessions.py` reads Claude and Codex transcript files (head and tail only, cached by path, mtime and size) for the window's project, on Windows and, in the background, over WSL shares. A GET-only router exposes the list and a preview. Resume reuses `POST /api/generic-agent/terminal` with a new `resume_id`. A new `web/static/agent-history.js` renders the list from pure, node-tested functions; live state comes from the terminal module's existing output timestamps.

**Tech Stack:** Python 3 / FastAPI / pytest (`tests/conftest.py` redirects HOME and puts `web/` on `sys.path`); vanilla JS (UMD modules, node `assert` tests run directly with `node`); CSS variables only.

**Spec:** `docs/superpowers/specs/2026-11-15-agent-session-history-design.md`

## Global Constraints

- The product is called **AI Gator**. Never write "POC" in code, docs or messages.
- All LLM calls go through `llm.gateway`. This feature makes no LLM call; titles come from the agent's own summary or the first real user message.
- Commits carry no `Co-Authored-By` line (project rule; it overrides any tool default).
- The only fake credential in tests, fixtures and docs is `aigator-fake-api-key`.
- Every new POST/PUT/PATCH/DELETE route uses `dependencies=[Depends(verify_csrf)]`. This plan adds only GET routes and one new field on an existing POST route. `tests/test_csrf_route_inventory.py` must stay green and `tests/csrf_route_baseline.txt` must not be edited.
- Email, Teams and Slack messages are draft-only; nothing here sends any.
- Styles use only the app's CSS variables (`--surface`, `--bg`, `--border`, `--border2`, `--accent`, `--warn`, `--text`, `--text-dim`, `--text-sub`), never hard-coded colours, and work in both `:root` (dark) and `[data-theme='light']`.
- Gator keeps no copy of any conversation. Previews and list titles pass through the handoff redactor (`agent_handoff.Redactor`).
- Nothing is pushed or merged without the user's say-so. Work happens in this worktree on a branch stacked on `feat/agent-handoff`.
- Every dynamic string from a transcript (titles, branches, previews) is written with `textContent`, never `innerHTML`.
- Server timestamps are epoch **seconds**; terminal timestamps (`_lastOutputAt`, `_viewedAt`, `created_at` JS side) are **milliseconds**.

---

## File Structure

| File                                      | Action | Responsibility                                                                                                |
| ----------------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------- |
| `web/agent_sessions.py`                   | Create | Parse Claude/Codex transcripts, scan a project (Windows + WSL), cache, find, join live, public shape, preview |
| `web/routes/agent_session_routes.py`      | Create | `GET /api/agent-sessions` and `GET /api/agent-sessions/{agent}/{id}/preview`                                  |
| `web/generic_agent.py`                    | Modify | `_wsl_command` gains resume args; add `build_resume_command`, `pin_resume`                                    |
| `web/routes/generic_agent_routes.py`      | Modify | `resume_id` on the launch route; stored-session handoff prepare                                               |
| `web/agent_handoff.py`                    | Modify | `prepare_handoff_from_transcript`, shared `_save_prepared`                                                    |
| `web/app.py`                              | Modify | Include the new router                                                                                        |
| `web/static/agent-history.js`             | Create | Pure grouping/time/live-state functions and the DOM controller                                                |
| `web/static/agent-handoff.js`             | Modify | `openDialog` accepts a stored session and a project                                                           |
| `web/static/tp-generic-agent-terminal.js` | Modify | `resume_id` in launch bodies; `_viewedAt` tracking                                                            |
| `web/static/tp-code-agent.js`             | Modify | Three icon tabs, History pane, `_caSetLeftView`                                                               |
| `web/static/index.html`                   | Modify | Load `agent-history.js` after `agent-handoff.js`                                                              |
| `web/static/style.css`                    | Modify | Icon tabs, amber dot, `.ah-*` list styles                                                                     |
| `tests/test_agent_sessions.py`            | Create | Parser, scan, WSL mapping, join, preview tests                                                                |
| `tests/test_agent_session_routes.py`      | Create | List, preview, resume, stored handoff route tests                                                             |
| `tests/agent_history.test.js`             | Create | Node tests for the pure functions                                                                             |
| `tests/test_agent_history_frontend.py`    | Create | Source-string wiring checks                                                                                   |

---

### Task 1: Stacked branch and spec addendum

**Files:**

- Modify: `docs/superpowers/specs/2026-11-15-agent-session-history-design.md`

**Interfaces:**

- Consumes: nothing.
- Produces: branch `feat/agent-history` (off `feat/agent-handoff`) that every later task commits to.

- [ ] **Step 1: Confirm a clean tree and cut the branch**

Run (from `C:\Users\maykulka\POCs\aigator-agent-handoff`):

```bash
git status --short
git branch --show-current
git switch -c feat/agent-history
```

Expected: `git status --short` prints nothing, the current branch is `feat/agent-handoff`, and the switch reports `Switched to a new branch 'feat/agent-history'`.

- [ ] **Step 2: Correct the join window in the spec**

In the spec, replace the sentence

```
Codex and other agents without a pinned id join by start time: the rollout created within 5 seconds before the terminal's `created_at`, only when exactly one matches.
```

with

```
Codex and other agents without a pinned id join by start time: the rollout whose start falls from 5 seconds before to 120 seconds after the terminal's `created_at`, only when exactly one unclaimed Windows rollout matches. Codex writes its first line when the first prompt is sent, so a rollout can start well after the terminal opens.
```

- [ ] **Step 3: Add the implementation notes section**

Insert before `## Session record (Workboard compatibility)`:

```markdown
## Implementation notes

- Hidden Claude sessions: `isSidechain`, and any whose first `entrypoint` starts with `sdk` (headless runs that are not user conversations).
- The head read is 256 KB, because a session can open with a very large hook line before the first user message. The tail read is 256 KB.
- A live row is "working" while its terminal printed within the last 3 seconds. After that it is "needs you" until the user views the tab, then "done".
- List titles are redacted as well as previews, because a pasted secret can be the first user message.
- Codex Desktop often opens with a generic prompt, so its titles can read the same ("Review this change…"). The branch and time on the second line tell them apart.
```

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-11-15-agent-session-history-design.md
git commit -m "docs: record session history join window and filter details"
```

---

### Task 2: Transcript parsers

**Files:**

- Create: `web/agent_sessions.py`
- Test: `tests/test_agent_sessions.py`

**Interfaces:**

- Consumes: `agent_handoff._CODEX_CONTEXT_PREFIXES` (tuple of strings that mark Codex injected context).
- Produces, all in `agent_sessions`:
  - Constants `HEAD_BYTES`, `TAIL_BYTES`, `TITLE_MAX`, `SESSION_ID_RE`.
  - `real_user_text(text: str) -> str` returns `""` for boilerplate.
  - `parse_claude(path: Path, st: os.stat_result) -> dict | None`.
  - `parse_codex(path: Path, st: os.stat_result) -> dict | None`.
  - `codex_meta(path: Path) -> dict | None` returns the first line's `session_meta` payload.
  - A parsed record is `{"id", "agent", "title", "branch", "started_at", "last_active_at", "state": "done", "path", "cwd"}`. `branch` is `""` when unknown, times are epoch seconds. `source` is added later by the scanner.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_sessions.py`:

````python
import json

import pytest

import agent_sessions as ags


def jl(path, objs, trailing=""):
    with open(path, "w", encoding="utf-8") as fh:
        for o in objs:
            fh.write(json.dumps(o) + "\n")
        fh.write(trailing)
    return path


def claude_user(text, ts="2026-11-15T10:00:00.000Z", **extra):
    return {"type": "user", "timestamp": ts, "cwd": "C:\\work\\app",
            "gitBranch": "feat/x", "message": {"role": "user", "content": text}, **extra}


def claude_assistant(text, ts="2026-11-15T10:01:00.000Z"):
    return {"type": "assistant", "timestamp": ts,
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def parse_c(tmp_path, objs, name="abc-123.jsonl", trailing=""):
    p = jl(tmp_path / name, objs, trailing)
    return ags.parse_claude(p, p.stat())


def test_claude_title_prefers_custom_then_ai_then_first_message(tmp_path):
    base = [claude_user("first question here"), claude_assistant("ok")]
    assert parse_c(tmp_path, base)["title"] == "first question here"
    ai = base + [{"type": "ai-title", "aiTitle": "AI summary"}]
    assert parse_c(tmp_path, ai)["title"] == "AI summary"
    custom = ai + [{"type": "custom-title", "customTitle": "My name"}]
    assert parse_c(tmp_path, custom)["title"] == "My name"


def test_claude_record_fields(tmp_path):
    rec = parse_c(tmp_path, [claude_user("hello"), claude_assistant("hi")])
    assert rec["id"] == "abc-123"
    assert rec["agent"] == "claude"
    assert rec["branch"] == "feat/x"
    assert rec["cwd"] == "C:\\work\\app"
    assert rec["state"] == "done"
    assert rec["started_at"] == pytest.approx(1794736800.0, abs=1)
    assert rec["last_active_at"] > 0
    assert rec["path"].endswith("abc-123.jsonl")


def test_claude_boilerplate_is_not_a_title(tmp_path):
    objs = [
        claude_user("<command-name>/clear</command-name>"),
        claude_user("Caveat: The messages below were generated by the user"),
        claude_user("<system-reminder>ctx</system-reminder>\n\nWhy is the build slow?"),
    ]
    assert parse_c(tmp_path, objs)["title"] == "Why is the build slow?"


def test_claude_only_boilerplate_is_hidden(tmp_path):
    assert parse_c(tmp_path, [claude_user("<command-name>/clear</command-name>")]) is None


def test_claude_hides_sdk_sidechain_and_cwdless(tmp_path):
    assert parse_c(tmp_path, [claude_user("hi", entrypoint="sdk-cli")]) is None
    assert parse_c(tmp_path, [claude_user("hi", isSidechain=True)]) is None
    nocwd = {"type": "user", "message": {"role": "user", "content": "hi"}}
    assert parse_c(tmp_path, [nocwd]) is None


def test_claude_ignores_half_written_last_line(tmp_path):
    rec = parse_c(tmp_path, [claude_user("hello")], trailing='{"type": "assist')
    assert rec["title"] == "hello"


def test_claude_finds_first_message_after_huge_hook_line(tmp_path):
    big = {"type": "attachment", "cwd": "C:\\work\\app", "blob": "x" * (100 * 1024)}
    rec = parse_c(tmp_path, [big, claude_user("real question")])
    assert rec["title"] == "real question"


def test_claude_reads_tail_of_a_large_file(tmp_path):
    filler = [claude_assistant("y" * 1000) for _ in range(700)]
    objs = [claude_user("start here")] + filler + [
        {"type": "ai-title", "aiTitle": "Late title"},
        {"type": "user", "cwd": "C:\\work\\app", "gitBranch": "feat/late",
         "message": {"role": "user", "content": "end"}},
    ]
    rec = parse_c(tmp_path, objs)
    assert rec["title"] == "Late title"
    assert rec["branch"] == "feat/late"


def test_title_is_collapsed_and_truncated(tmp_path):
    rec = parse_c(tmp_path, [claude_user("a\n\n  b   " + "z" * 300)])
    assert "\n" not in rec["title"]
    assert len(rec["title"]) <= ags.TITLE_MAX
    assert rec["title"].endswith("\u2026")


def test_claude_rejects_unsafe_id(tmp_path):
    assert parse_c(tmp_path, [claude_user("hi")], name="bad id;rm.jsonl") is None


def codex_meta_line(**payload):
    base = {"id": "019a-aaaa", "timestamp": "2026-11-15T10:00:00.000Z", "cwd": "C:\\work\\app",
            "source": "cli", "git": {"branch": "main"}}
    base.update(payload)
    return {"type": "session_meta", "payload": base}


def codex_msg(role, text, ctype="input_text"):
    return {"type": "response_item",
            "payload": {"type": "message", "role": role, "content": [{"type": ctype, "text": text}]}}


def parse_x(tmp_path, objs, name="rollout-2026-11-15T10-00-00-019a-aaaa.jsonl"):
    p = jl(tmp_path / name, objs)
    return ags.parse_codex(p, p.stat())


def test_codex_record_and_context_skip(tmp_path):
    rec = parse_x(tmp_path, [
        codex_meta_line(),
        codex_msg("user", "<environment_context>cwd</environment_context>"),
        codex_msg("user", "# AGENTS.md instructions for C:\\work\\app"),
        codex_msg("user", "Fix the flaky login test"),
        codex_msg("assistant", "On it", "output_text"),
    ])
    assert rec["id"] == "019a-aaaa"
    assert rec["agent"] == "codex"
    assert rec["title"] == "Fix the flaky login test"
    assert rec["branch"] == "main"
    assert rec["cwd"] == "C:\\work\\app"
    assert rec["started_at"] == pytest.approx(1794736800.0, abs=1)


def test_codex_hides_subagent_noid_and_empty(tmp_path):
    sub = codex_meta_line(source={"subagent": {"thread_spawn": {}}})
    assert parse_x(tmp_path, [sub, codex_msg("user", "hi")]) is None
    assert parse_x(tmp_path, [codex_meta_line(id=""), codex_msg("user", "hi")]) is None
    assert parse_x(tmp_path, [codex_meta_line()]) is None
    assert parse_x(tmp_path, [{"type": "event_msg"}]) is None


def test_codex_meta_reads_only_the_first_line(tmp_path):
    p = jl(tmp_path / "rollout-x.jsonl", [codex_meta_line(), codex_msg("user", "hi")])
    assert ags.codex_meta(p)["cwd"] == "C:\\work\\app"
    p2 = jl(tmp_path / "rollout-y.jsonl", [{"type": "event_msg"}])
    assert ags.codex_meta(p2) is None

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_agent_sessions.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'agent_sessions'`.

- [ ] **Step 3: Write the parsers**

Create `web/agent_sessions.py`:

```python
"""Project-scoped agent session history, read from the agents' own transcript files.

Nothing is stored: each call reads the head and tail of transcript files that
Claude Code and Codex already keep, and caches the parsed result by
(path, mtime, size).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

import agent_handoff as ah

HEAD_BYTES = 256 * 1024
TAIL_BYTES = 256 * 1024
TITLE_MAX = 120
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")

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
    if not SESSION_ID_RE.match(session_id):
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
    if not isinstance(session_id, str) or not SESSION_ID_RE.match(session_id) or not isinstance(cwd, str):
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
````

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_agent_sessions.py -v`
Expected: all tests PASS. If `test_claude_finds_first_message_after_huge_hook_line` fails, the head read is too small: confirm `HEAD_BYTES` is `256 * 1024`.

- [ ] **Step 5: Commit**

```bash
git add web/agent_sessions.py tests/test_agent_sessions.py
git commit -m "feat: parse Claude and Codex transcripts into session records"
```

---

### Task 3: Scan, find, join, public shape and preview

**Files:**

- Modify: `web/agent_sessions.py`
- Test: `tests/test_agent_sessions.py`

**Interfaces:**

- Consumes: `parse_claude`, `parse_codex`, `codex_meta`, `_claude_message`, `_codex_message`, `_read_tail`, `HEAD_BYTES`, `ah.Redactor`, `ah._configured_api_keys` (returns `list[str]`; `Redactor` is callable and replaces keys with `[REDACTED]`).
- Produces, in `agent_sessions`:
  - Constants `MAX_SESSIONS = 200`, `MAX_FILES = 300`, `MAX_CODEX_SCAN = 2000`, `PREVIEW_EXCHANGES = 6`, `PREVIEW_CHARS = 600`, `AGENTS = ("claude", "codex")`.
  - `SourceHome(source: str, home: Path, cwd: str)` frozen dataclass. `source` is `"windows"` or `"wsl:<distro>"`; `cwd` is the project's folder as that home's agents recorded it.
  - `windows_homes(repo_path: str) -> list[SourceHome]`.
  - `scan_project(repo_path: str, *, homes=None, agents=AGENTS) -> list[dict]`: records newest first, each with `source` added, capped at `MAX_SESSIONS`.
  - `find_session(repo_path: str, agent: str, session_id: str, *, homes=None) -> dict | None`.
  - `join_live(records: list[dict], live: list[dict]) -> list[dict]`. Each `live` item is `{"agent", "pty_session_id", "session_id" (pinned id or None), "created_at" (epoch seconds)}`. Returns copies; a joined record gains `pty_session_id`.
  - `public(rec: dict) -> dict`: only `id, agent, title, branch, started_at, last_active_at, state, source` and, when joined, `pty_session_id`.
  - `preview(rec: dict) -> list[dict]`: up to 6 `{"role", "text"}`, redacted before the 600-character cut. Raises `OSError` if the file is gone.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_sessions.py` (and add `import os` at the top of the file):

```python
PROJECT = "C:\\work\\app"


@pytest.fixture(autouse=True)
def _clear_cache():
    ags._CACHE.clear()
    yield


def home_for(tmp_path):
    return ags.SourceHome("windows", tmp_path, PROJECT)


def put_claude(home, sid, objs, slug="C--work-app", mtime=None):
    d = home / ".claude" / "projects" / slug
    d.mkdir(parents=True, exist_ok=True)
    p = jl(d / f"{sid}.jsonl", objs)
    if mtime:
        os.utime(p, (mtime, mtime))
    return p


def put_codex(home, sid, objs, mtime=None):
    d = home / ".codex" / "sessions" / "2026" / "11" / "15"
    d.mkdir(parents=True, exist_ok=True)
    p = jl(d / f"rollout-2026-11-15T10-00-00-{sid}.jsonl", objs)
    if mtime:
        os.utime(p, (mtime, mtime))
    return p


def test_same_dir_ignores_case_slashes_and_long_prefix():
    assert ags._same_dir("C:\\Work\\App", "c:/work/app/")
    assert ags._same_dir("\\\\?\\C:\\work\\app", "C:\\work\\app")
    assert ags._same_dir("//Server/Share/p", "\\\\server\\share\\P")
    assert not ags._same_dir("/home/me/App", "/home/me/app")
    assert not ags._same_dir("C:\\work\\app", "C:\\work\\app2")


def test_scan_finds_this_projects_sessions_newest_first(tmp_path):
    put_claude(tmp_path, "c-old", [claude_user("old one")], mtime=1_700_000_000)
    put_codex(tmp_path, "x-new", [codex_meta_line(id="x-new"), codex_msg("user", "new one")], mtime=1_800_000_000)
    put_claude(tmp_path, "c-other", [claude_user("elsewhere")], slug="C--other-app")
    put_codex(tmp_path, "x-other", [codex_meta_line(id="x-other", cwd="C:\\other"), codex_msg("user", "nope")])
    recs = ags.scan_project(PROJECT, homes=[home_for(tmp_path)])
    assert [r["id"] for r in recs] == ["x-new", "c-old"]
    assert {r["source"] for r in recs} == {"windows"}


def test_scan_matches_slug_case_insensitively_but_rejects_slug_collisions(tmp_path):
    put_claude(tmp_path, "same", [claude_user("mine")], slug="c--WORK-app")
    collide = {**claude_user("not mine"), "cwd": "C:\\work-app"}
    put_claude(tmp_path, "collide", [collide])
    recs = ags.scan_project(PROJECT, homes=[home_for(tmp_path)])
    assert [r["id"] for r in recs] == ["same"]


def test_scan_respects_agent_filter_and_cap(tmp_path, monkeypatch):
    put_claude(tmp_path, "c1", [claude_user("one")], mtime=1_700_000_001)
    put_claude(tmp_path, "c2", [claude_user("two")], mtime=1_700_000_002)
    put_codex(tmp_path, "x1", [codex_meta_line(id="x1"), codex_msg("user", "three")], mtime=1_700_000_003)
    assert [r["id"] for r in ags.scan_project(PROJECT, homes=[home_for(tmp_path)], agents=("claude",))] == ["c2", "c1"]
    monkeypatch.setattr(ags, "MAX_SESSIONS", 2)
    assert [r["id"] for r in ags.scan_project(PROJECT, homes=[home_for(tmp_path)])] == ["x1", "c2"]


def test_scan_missing_agent_directories_give_an_empty_list(tmp_path):
    assert ags.scan_project(PROJECT, homes=[home_for(tmp_path)]) == []


def test_scan_parses_each_unchanged_file_once(tmp_path, monkeypatch):
    p = put_claude(tmp_path, "c1", [claude_user("one")])
    calls = []
    real = ags.parse_claude
    monkeypatch.setattr(ags, "parse_claude", lambda path, st: calls.append(1) or real(path, st))
    ags.scan_project(PROJECT, homes=[home_for(tmp_path)])
    ags.scan_project(PROJECT, homes=[home_for(tmp_path)])
    assert len(calls) == 1
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(claude_assistant("more")) + "\n")
    ags.scan_project(PROJECT, homes=[home_for(tmp_path)])
    assert len(calls) == 2


def test_find_session_returns_the_record_or_none(tmp_path):
    put_claude(tmp_path, "c1", [claude_user("one")])
    h = [home_for(tmp_path)]
    assert ags.find_session(PROJECT, "claude", "c1", homes=h)["title"] == "one"
    assert ags.find_session(PROJECT, "claude", "nope", homes=h) is None
    assert ags.find_session(PROJECT, "codex", "c1", homes=h) is None


def mk(agent, sid, started, source="windows"):
    return {"id": sid, "agent": agent, "title": "t", "branch": "", "started_at": started,
            "last_active_at": started, "state": "done", "source": source, "path": "p", "cwd": "c"}


def test_join_by_pinned_id():
    live = [{"agent": "claude", "pty_session_id": "p1", "session_id": "s2", "created_at": 150}]
    out = ags.join_live([mk("claude", "s1", 100), mk("claude", "s2", 200)], live)
    assert [r.get("pty_session_id") for r in out] == [None, "p1"]


def test_join_by_start_time_needs_exactly_one_unclaimed_windows_candidate():
    live = [{"agent": "codex", "pty_session_id": "p1", "session_id": None, "created_at": 1000}]
    one = [mk("codex", "a", 1030), mk("codex", "b", 5000)]
    assert ags.join_live(one, live)[0]["pty_session_id"] == "p1"
    assert "pty_session_id" not in one[0]
    two = [mk("codex", "a", 1030), mk("codex", "b", 1040)]
    assert all("pty_session_id" not in r for r in ags.join_live(two, live))
    assert "pty_session_id" not in ags.join_live([mk("codex", "a", 1030, "wsl:Ubuntu")], live)[0]
    assert "pty_session_id" not in ags.join_live([mk("codex", "a", 994)], live)[0]
    assert ags.join_live([mk("codex", "a", 995)], live)[0]["pty_session_id"] == "p1"
    assert ags.join_live([mk("codex", "a", 1120)], live)[0]["pty_session_id"] == "p1"
    assert "pty_session_id" not in ags.join_live([mk("codex", "a", 1121)], live)[0]


def test_join_skips_a_rollout_wanted_by_two_terminals():
    live = [
        {"agent": "codex", "pty_session_id": "p1", "session_id": None, "created_at": 1000},
        {"agent": "codex", "pty_session_id": "p2", "session_id": None, "created_at": 1010},
    ]
    assert all("pty_session_id" not in r for r in ags.join_live([mk("codex", "a", 1030)], live))


def test_public_strips_internal_fields():
    rec = {**mk("claude", "s1", 100), "pty_session_id": "p1"}
    pub = ags.public(rec)
    assert set(pub) == {"id", "agent", "title", "branch", "started_at", "last_active_at",
                        "state", "source", "pty_session_id"}
    assert "path" not in pub and "cwd" not in pub
    assert "pty_session_id" not in ags.public(mk("claude", "s1", 100))


def test_preview_merges_turns_redacts_and_caps(tmp_path, monkeypatch):
    monkeypatch.setattr(ags.ah, "_configured_api_keys", lambda: ["aigator-fake-api-key"])
    objs = []
    for i in range(5):
        objs += [claude_user(f"question {i}"), claude_assistant(f"answer {i}")]
    objs.append(claude_assistant("key is aigator-fake-api-key " + "z" * 700))
    p = jl(tmp_path / "s.jsonl", objs)
    msgs = ags.preview({"agent": "claude", "path": str(p)})
    assert len(msgs) == ags.PREVIEW_EXCHANGES
    assert msgs[0] == {"role": "user", "text": "question 2"}
    assert msgs[-1]["role"] == "assistant"
    assert "aigator-fake-api-key" not in msgs[-1]["text"]
    assert "[REDACTED]" in msgs[-1]["text"]
    assert len(msgs[-1]["text"]) <= ags.PREVIEW_CHARS


def test_preview_of_a_deleted_file_raises(tmp_path):
    with pytest.raises(OSError):
        ags.preview({"agent": "claude", "path": str(tmp_path / "gone.jsonl")})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_agent_sessions.py -v`
Expected: the Task 2 tests PASS; the new tests FAIL with `AttributeError: module 'agent_sessions' has no attribute '_same_dir'` (or `SourceHome`, `scan_project`, and so on).

- [ ] **Step 3: Write the scanner**

In `web/agent_sessions.py`, change the import block to add `threading` and `dataclass`:

```python
import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
```

Add the new constants below `SESSION_ID_RE`:

```python
MAX_SESSIONS = 200
MAX_FILES = 300
MAX_CODEX_SCAN = 2000
PREVIEW_EXCHANGES = 6
PREVIEW_CHARS = 600
AGENTS = ("claude", "codex")
```

Append to the end of the file:

```python
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
    if re.match(r"^[A-Za-z]:", s) or s.startswith("//"):
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
                    files.append((e.stat(), Path(e.path)))
    except OSError:
        pass
    files.sort(key=lambda f: f[0].st_mtime, reverse=True)
    out = []
    for st, p in files[:MAX_FILES]:
        rec = _cached("claude", p, st, parse_claude)
        if rec and _same_dir(rec["cwd"], sh.cwd):
            out.append(dict(rec, source=sh.source))
    return out


def _scan_codex(sh: SourceHome) -> list[dict]:
    files = []
    for dirpath, _dirs, names in os.walk(sh.home / ".codex" / "sessions"):
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
        if not meta or not _same_dir(str(meta.get("cwd") or ""), sh.cwd):
            continue
        rec = _cached("codex", p, st, parse_codex)
        if rec:
            out.append(dict(rec, source=sh.source))
        if len(out) >= MAX_FILES:
            break
    return out


_SCANNERS = {"claude": _scan_claude, "codex": _scan_codex}


def windows_homes(repo_path: str) -> list[SourceHome]:
    return [SourceHome("windows", Path.home(), repo_path)]


def scan_project(repo_path: str, *, homes=None, agents=AGENTS) -> list[dict]:
    homes = windows_homes(repo_path) if homes is None else homes
    out: list[dict] = []
    for sh in homes:
        for agent in agents:
            out.extend(_SCANNERS[agent](sh))
    out.sort(key=lambda r: r["last_active_at"], reverse=True)
    return out[:MAX_SESSIONS]


def find_session(repo_path: str, agent: str, session_id: str, *, homes=None) -> dict | None:
    for rec in scan_project(repo_path, homes=homes, agents=(agent,)):
        if rec["id"] == session_id:
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


_PUBLIC_KEYS = ("id", "agent", "title", "branch", "started_at", "last_active_at", "state", "source", "pty_session_id")


def public(rec: dict) -> dict:
    return {k: rec[k] for k in _PUBLIC_KEYS if k in rec}


def preview(rec: dict) -> list[dict]:
    path = Path(rec["path"])
    extract = _claude_message if rec["agent"] == "claude" else _codex_message
    merged: list[dict] = []
    for o in _read_tail(path, path.stat().st_size):
        m = extract(o)
        if not m:
            continue
        if merged and merged[-1]["role"] == m[0]:
            merged[-1]["text"] += " " + m[1]
        else:
            merged.append({"role": m[0], "text": m[1]})
    red = ah.Redactor(ah._configured_api_keys())
    return [{"role": m["role"], "text": red(m["text"])[:PREVIEW_CHARS]} for m in merged[-PREVIEW_EXCHANGES:]]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_agent_sessions.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add web/agent_sessions.py tests/test_agent_sessions.py
git commit -m "feat: scan a project's agent sessions with caching, live join and preview"
```

---

### Task 4: WSL sessions

**Files:**

- Modify: `web/agent_sessions.py`
- Test: `tests/test_agent_sessions.py`

**Interfaces:**

- Consumes: `generic_agent.wsl_agents() -> (distro | None, {agent: executable})` (the default distro and the agents installed in it), `generic_agent._stale_while_revalidate(key: str, refresh: Callable[[], None])` (runs `refresh` on a daemon thread, at most one per key), `SourceHome`, `scan_project`, `find_session` from Task 3.
- Produces, in `agent_sessions`:
  - `WSL_TTL_SECONDS = 30`.
  - `wsl_cwd(repo_path: str, distro: str) -> str | None`: the project's folder as a WSL process sees it (`C:\work\app` becomes `/mnt/c/work/app`; a `\\wsl.localhost\<distro>\…` path becomes its Linux path; anything else is `None`).
  - `wsl_homes(repo_path: str) -> tuple[list[SourceHome], tuple[str, ...]]`: one `SourceHome("wsl:<distro>", <UNC home>, <wsl cwd>)` per user under `\\wsl.localhost\<distro>\home`, plus the agents installed in that distro.
  - `wsl_sessions(repo_path: str) -> tuple[list[dict], bool]`: cached WSL records and `pending` (no result yet). Never blocks on WSL; a refresh runs in the background at most every 30 seconds.
  - `cached_wsl_records(repo_path: str) -> list[dict]`: what `wsl_sessions` last stored, never refreshing.
  - `find_session` now also searches the cached WSL records.

- [ ] **Step 1: Write the failing tests**

In `tests/test_agent_sessions.py`, extend the autouse fixture so it also clears the WSL cache:

```python
@pytest.fixture(autouse=True)
def _clear_cache():
    ags._CACHE.clear()
    ags._WSL.clear()
    yield
```

Append:

```python
def test_wsl_cwd_maps_windows_and_unc_paths():
    assert ags.wsl_cwd("C:\\work\\app", "Ubuntu") == "/mnt/c/work/app"
    assert ags.wsl_cwd("d:/Data/", "Ubuntu") == "/mnt/d/Data"
    assert ags.wsl_cwd("C:\\", "Ubuntu") == "/mnt/c"
    assert ags.wsl_cwd("\\\\?\\C:\\work\\app", "Ubuntu") == "/mnt/c/work/app"
    assert ags.wsl_cwd("\\\\wsl.localhost\\Ubuntu\\home\\me\\proj", "ubuntu") == "/home/me/proj"
    assert ags.wsl_cwd("\\\\wsl$\\Ubuntu\\home\\me", "Ubuntu") == "/home/me"
    assert ags.wsl_cwd("\\\\wsl.localhost\\Debian\\home\\me", "Ubuntu") is None
    assert ags.wsl_cwd("\\\\server\\share\\p", "Ubuntu") is None


def test_mnt_paths_compare_case_insensitively():
    assert ags._same_dir("/mnt/c/Work/App", "/mnt/c/work/app")
    assert not ags._same_dir("/home/me/App", "/home/me/app")


def test_wsl_homes_lists_user_homes_and_installed_agents(monkeypatch, tmp_path):
    monkeypatch.setattr(ags.generic_agent, "wsl_agents", lambda: ("Ubuntu", {"claude": "claude"}))
    monkeypatch.setattr(ags, "_wsl_user_homes", lambda distro: [tmp_path])
    homes, agents = ags.wsl_homes("C:\\work\\app")
    assert agents == ("claude",)
    assert homes == [ags.SourceHome("wsl:Ubuntu", tmp_path, "/mnt/c/work/app")]


def test_wsl_homes_is_empty_without_wsl_or_agents(monkeypatch, tmp_path):
    monkeypatch.setattr(ags, "_wsl_user_homes", lambda distro: [tmp_path])
    monkeypatch.setattr(ags.generic_agent, "wsl_agents", lambda: (None, {}))
    assert ags.wsl_homes("C:\\work\\app") == ([], ())
    monkeypatch.setattr(ags.generic_agent, "wsl_agents", lambda: ("Ubuntu", {}))
    assert ags.wsl_homes("C:\\work\\app") == ([], ())
    monkeypatch.setattr(ags.generic_agent, "wsl_agents", lambda: ("Ubuntu", {"claude": "claude"}))
    assert ags.wsl_homes("E:\\elsewhere")[0][0].cwd == "/mnt/e/elsewhere"
    assert ags.wsl_homes("\\\\server\\share\\p") == ([], ())


def test_scan_reads_wsl_sessions_recorded_with_mnt_paths(tmp_path):
    sh = ags.SourceHome("wsl:Ubuntu", tmp_path, "/mnt/c/work/app")
    rec = {**claude_user("from wsl"), "cwd": "/mnt/c/work/app"}
    put_claude(tmp_path, "w1", [rec], slug="-mnt-c-work-app")
    out = ags.scan_project(PROJECT, homes=[sh], agents=("claude",))
    assert [(r["id"], r["source"]) for r in out] == [("w1", "wsl:Ubuntu")]


def test_codex_scan_skips_compressed_rollouts(tmp_path):
    p = put_codex(tmp_path, "x1", [codex_meta_line(id="x1"), codex_msg("user", "hi")])
    p.rename(str(p) + ".zst")
    assert ags.scan_project(PROJECT, homes=[home_for(tmp_path)], agents=("codex",)) == []


def test_wsl_sessions_never_blocks_and_serves_the_cached_result(monkeypatch, tmp_path):
    sh = ags.SourceHome("wsl:Ubuntu", tmp_path, "/mnt/c/work/app")
    rec = {**claude_user("from wsl"), "cwd": "/mnt/c/work/app"}
    put_claude(tmp_path, "w1", [rec], slug="-mnt-c-work-app")
    monkeypatch.setattr(ags, "wsl_homes", lambda repo: ([sh], ("claude",)))
    monkeypatch.setattr(ags.generic_agent, "_stale_while_revalidate", lambda key, refresh: refresh())
    first, pending = ags.wsl_sessions(PROJECT)
    assert (first, pending) == ([], True)
    second, pending = ags.wsl_sessions(PROJECT)
    assert [r["id"] for r in second] == ["w1"]
    assert pending is False
    assert [r["id"] for r in ags.cached_wsl_records(PROJECT)] == ["w1"]


def test_wsl_sessions_without_wsl_settles_to_empty(monkeypatch):
    monkeypatch.setattr(ags, "wsl_homes", lambda repo: ([], ()))
    monkeypatch.setattr(ags.generic_agent, "_stale_while_revalidate", lambda key, refresh: refresh())
    ags.wsl_sessions(PROJECT)
    assert ags.wsl_sessions(PROJECT) == ([], False)


def test_find_session_also_searches_cached_wsl_records(tmp_path):
    ags._WSL[PROJECT] = (0.0, [{**mk("claude", "w1", 100, "wsl:Ubuntu"), "cwd": "/mnt/c/work/app"}])
    found = ags.find_session(PROJECT, "claude", "w1", homes=[home_for(tmp_path)])
    assert found["source"] == "wsl:Ubuntu"
    assert ags.find_session(PROJECT, "codex", "w1", homes=[home_for(tmp_path)]) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_agent_sessions.py -v`
Expected: the new tests FAIL (`AttributeError: ... no attribute 'wsl_cwd'` / `'_WSL'` / `'generic_agent'`); earlier tests PASS.

- [ ] **Step 3: Write the WSL support**

In `web/agent_sessions.py`:

1. Add imports at the top (`time` joins the stdlib block, `generic_agent` the local one):

```python
import time
```

```python
import agent_handoff as ah
import generic_agent
```

2. Add the constant below `AGENTS`:

```python
WSL_TTL_SECONDS = 30
```

3. Replace `_norm_dir` so WSL's case-insensitive `/mnt/<drive>` paths compare equal:

```python
def _norm_dir(path: str) -> str:
    s = (path or "").replace("\\", "/")
    if s.startswith("//?/"):
        s = s[4:]
    s = s.rstrip("/") or "/"
    if re.match(r"^[A-Za-z]:", s) or s.startswith("//") or s.startswith("/mnt/"):
        s = s.lower()
    return s
```

4. Replace `find_session` with a version that also checks the cached WSL records:

```python
def find_session(repo_path: str, agent: str, session_id: str, *, homes=None) -> dict | None:
    for rec in [*scan_project(repo_path, homes=homes, agents=(agent,)), *cached_wsl_records(repo_path)]:
        if rec["agent"] == agent and rec["id"] == session_id:
            return rec
    return None
```

5. Append the WSL section to the end of the file:

```python
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
    cwd = wsl_cwd(repo_path, distro) if distro else None
    if not distro or not agents or not cwd:
        return [], ()
    return [SourceHome(f"wsl:{distro}", home, cwd) for home in _wsl_user_homes(distro)], agents


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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_agent_sessions.py -v`
Expected: all tests PASS (including the Task 2 and Task 3 tests).

- [ ] **Step 5: Commit**

```bash
git add web/agent_sessions.py tests/test_agent_sessions.py
git commit -m "feat: read WSL agent sessions in the background"
```

---

### Task 5: Resume commands in `generic_agent`

**Files:**

- Modify: `web/generic_agent.py` (`_wsl_command` at ~370, add after `build_command` at ~410 and after `pin_session` at ~457)
- Test: `tests/test_agent_resume_command.py`

**Interfaces:**

- Consumes: `find_agent_binary(agent)`, `wsl_agents() -> (distro | None, {agent: executable})`, `SUPPORTED_AGENTS`, `_pinned_sessions`.
- Produces, in `generic_agent`:
  - `_wsl_command(agent: str, repo_path: str, resume_args: tuple[str, ...] = ())` (existing function, new optional parameter appended after the agent's own args).
  - `build_resume_command(agent: str, repo_path: str, session_id: str, source: str = "windows", extra_args: tuple[str, ...] = ()) -> list[str] | None`. `None` means "cannot resume here" (unsupported agent, binary missing, or the WSL distro or agent does not match `source`). For `source == "windows"` it returns `[binary, *base_args, *extra_args, *verb, session_id]`; for `source == "wsl:<distro>"` it returns the `wsl.exe` command from `_wsl_command`, and `repo_path` must already be the Linux path.
  - `pin_resume(agent: str, command: list[str], pty_session_id: str, session_id: str) -> list[str]`: records the resumed Claude session id under the terminal (so `pinned_session_id` finds it) and returns `command` unchanged.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_resume_command.py`:

```python
import generic_agent as ga


def test_windows_resume_commands(monkeypatch):
    monkeypatch.setattr(ga, "find_agent_binary", lambda a: f"C:\\bin\\{a}.exe")
    assert ga.build_resume_command("claude", "C:\\w", "abc-1") == ["C:\\bin\\claude.exe", "--resume", "abc-1"]
    assert ga.build_resume_command("codex", "C:\\w", "019a", extra_args=("-c", "x=1")) == [
        "C:\\bin\\codex.exe", "-c", "x=1", "resume", "019a",
    ]
    assert ga.build_resume_command("crush", "C:\\w", "x") is None
    assert ga.build_resume_command("claude", "C:\\w", "abc-1", source="elsewhere") is None


def test_windows_resume_needs_the_binary(monkeypatch):
    monkeypatch.setattr(ga, "find_agent_binary", lambda a: None)
    assert ga.build_resume_command("claude", "C:\\w", "abc-1") is None


def test_wsl_resume_uses_the_sessions_own_distro_and_agent(monkeypatch):
    monkeypatch.setattr(ga, "wsl_agents", lambda: ("Ubuntu", {"claude": "claude"}))
    cmd = ga.build_resume_command("claude", "/mnt/c/work/app", "abc-1", source="wsl:Ubuntu")
    assert cmd == [
        "wsl.exe", "-d", "Ubuntu", "--cd", "/mnt/c/work/app", "--", "bash", "-lc", "exec claude --resume abc-1",
    ]
    assert ga.build_resume_command("claude", "/mnt/c/w", "abc-1", source="wsl:Debian") is None
    assert ga.build_resume_command("codex", "/mnt/c/w", "x", source="wsl:Ubuntu") is None


def test_wsl_resume_quotes_the_id(monkeypatch):
    monkeypatch.setattr(ga, "wsl_agents", lambda: ("Ubuntu", {"codex": "codex"}))
    cmd = ga.build_resume_command("codex", "/mnt/c/w", "a b", source="wsl:Ubuntu")
    assert cmd[-1] == "exec codex resume 'a b'"


def test_pin_resume_records_the_claude_session_id(monkeypatch):
    monkeypatch.setattr(ga, "_pinned_sessions", {})
    cmd = ["C:\\bin\\claude.exe", "--resume", "abc-1"]
    assert ga.pin_resume("claude", cmd, "pty1", "abc-1") == cmd
    assert ga.pinned_session_id("pty1") == "abc-1"


def test_pin_resume_ignores_wsl_and_other_agents(monkeypatch):
    monkeypatch.setattr(ga, "_pinned_sessions", {})
    ga.pin_resume("claude", ["wsl.exe", "-d", "Ubuntu"], "pty2", "abc-1")
    ga.pin_resume("codex", ["C:\\bin\\codex.exe", "resume", "x"], "pty3", "x")
    assert ga.pinned_session_id("pty2") is None
    assert ga.pinned_session_id("pty3") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_agent_resume_command.py -v`
Expected: FAIL with `AttributeError: module 'generic_agent' has no attribute 'build_resume_command'`.

- [ ] **Step 3: Implement**

In `web/generic_agent.py`, replace `_wsl_command` with:

```python
def _wsl_command(agent: str, repo_path: str, resume_args: tuple[str, ...] = ()) -> list[str] | None:
    distro, found = wsl_agents()
    name = found.get(agent)
    if not distro or not name:
        return None
    argv = [name, *SUPPORTED_AGENTS[agent][1:], *resume_args]
    cmd = ["wsl.exe", "-d", distro]
    if repo_path:
        cmd += ["--cd", repo_path]
    return [*cmd, "--", "bash", "-lc", "exec " + shlex.join(argv)]
```

Add directly after `build_command`:

```python
_RESUME_VERBS = {"claude": ("--resume",), "codex": ("resume",)}


def build_resume_command(
    agent: str,
    repo_path: str,
    session_id: str,
    source: str = "windows",
    extra_args: tuple[str, ...] = (),
) -> list[str] | None:
    """argv that reopens a stored session in the agent's own resume mode, in the
    place the session lives. A WSL session resumes inside its distro with the
    Linux path, never a UNC path."""
    verb = _RESUME_VERBS.get(agent)
    if not verb:
        return None
    if source == "windows":
        resolved = find_agent_binary(agent)
        if not resolved:
            return None
        return [resolved, *SUPPORTED_AGENTS[agent][1:], *extra_args, *verb, session_id]
    distro, _found = wsl_agents()
    if not distro or source != f"wsl:{distro}":
        return None
    return _wsl_command(agent, repo_path, (*verb, session_id))
```

Add directly after `pin_session`:

```python
def pin_resume(agent: str, command: list[str], pty_session_id: str, session_id: str) -> list[str]:
    if agent == "claude" and command and Path(command[0]).stem.lower() != "wsl":
        _pinned_sessions[pty_session_id] = session_id
    return command
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_agent_resume_command.py tests/test_agent_handoff_routes.py -v`
Expected: PASS (the existing handoff route tests confirm `_wsl_command`'s old callers still work).

- [ ] **Step 5: Commit**

```bash
git add web/generic_agent.py tests/test_agent_resume_command.py
git commit -m "feat: build resume commands for stored Claude and Codex sessions"
```

---

### Task 6: List and preview routes

**Files:**

- Create: `web/routes/agent_session_routes.py`
- Modify: `web/app.py:95` (import) and `web/app.py:954` (include)
- Test: `tests/test_agent_session_routes.py`

**Interfaces:**

- Consumes: `agent_sessions.scan_project / wsl_sessions / find_session / join_live / public / preview / AGENTS / SESSION_ID_RE / MAX_SESSIONS`, `generic_agent.is_installed`, `generic_agent.pinned_session_id`, `agent_handoff._session_started_at` (epoch seconds or `None`), `agent_handoff.Redactor`, `agent_handoff._configured_api_keys`, `skills.code_agent.projects.get_project(name) -> {"name", "repo_path", ...} | None`.
- Produces:
  - `GET /api/agent-sessions?project_name=<name>&pty=<agent>:<pty_session_id>` (the `pty` parameter repeats, one per open terminal) returning `{"sessions": [public record, ...], "wsl_pending": bool}`. Unknown project is 404.
  - `GET /api/agent-sessions/{agent}/{session_id}/preview?project_name=<name>` returning `{"messages": [{"role", "text"}, ...]}`. A bad agent or id is 400; an unknown project, an unknown session, or a file that has since been deleted is 404.
  - Module-level `router` (an `APIRouter`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_session_routes.py`:

```python
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import agent_handoff as ah
import agent_sessions as ags
import generic_agent
from routes import agent_session_routes as asr

FAKE = "aigator-fake-api-key"


def client():
    app = FastAPI()
    app.include_router(asr.router)
    return TestClient(app)


def rec(agent, sid, title, last, source="windows"):
    return {"id": sid, "agent": agent, "title": title, "branch": "main", "started_at": last - 60,
            "last_active_at": last, "state": "done", "source": source,
            "path": f"C:\\secret\\{sid}.jsonl", "cwd": "C:\\work\\app"}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setattr(
        asr.code_projects, "get_project",
        lambda name: {"name": name, "repo_path": "C:\\work\\app"} if name == "demo" else None,
    )
    monkeypatch.setattr(generic_agent, "is_installed", lambda a: a in ("claude", "codex"))
    monkeypatch.setattr(generic_agent, "pinned_session_id", lambda pty: "c1" if pty == "p1" else None)
    monkeypatch.setattr(ags, "wsl_sessions", lambda repo: ([], False))
    monkeypatch.setattr(ags, "cached_wsl_records", lambda repo: [])
    monkeypatch.setattr(ah, "_configured_api_keys", lambda: [FAKE])
    monkeypatch.setattr(ah, "_session_started_at", lambda sid: None)


@pytest.fixture
def scanned(monkeypatch):
    seen = {}
    records = [
        rec("claude", "c1", "Older claude", 100),
        rec("codex", "x1", f"Use key {FAKE} here", 300),
    ]

    def fake(repo, *, homes=None, agents=ags.AGENTS):
        seen["repo"], seen["agents"] = repo, agents
        return [r for r in records if r["agent"] in agents]

    monkeypatch.setattr(ags, "scan_project", fake)
    return seen


def test_list_returns_public_records_newest_first_and_redacts_titles(scanned):
    r = client().get("/api/agent-sessions", params={"project_name": "demo"})
    assert r.status_code == 200
    data = r.json()
    assert [s["id"] for s in data["sessions"]] == ["x1", "c1"]
    assert data["wsl_pending"] is False
    assert all("path" not in s and "cwd" not in s for s in data["sessions"])
    assert FAKE not in data["sessions"][0]["title"] and "[REDACTED]" in data["sessions"][0]["title"]
    assert scanned["repo"] == "C:\\work\\app"


def test_list_unknown_project_is_404(scanned):
    assert client().get("/api/agent-sessions", params={"project_name": "nope"}).status_code == 404


def test_list_scans_only_installed_agents(scanned, monkeypatch):
    monkeypatch.setattr(generic_agent, "is_installed", lambda a: a == "claude")
    data = client().get("/api/agent-sessions", params={"project_name": "demo"}).json()
    assert scanned["agents"] == ("claude",)
    assert [s["id"] for s in data["sessions"]] == ["c1"]


def test_list_merges_wsl_records_and_reports_pending(scanned, monkeypatch):
    wsl = rec("claude", "w1", "From WSL", 200, source="wsl:Ubuntu")
    monkeypatch.setattr(ags, "wsl_sessions", lambda repo: ([wsl], True))
    data = client().get("/api/agent-sessions", params={"project_name": "demo"}).json()
    assert [s["id"] for s in data["sessions"]] == ["x1", "w1", "c1"]
    assert data["wsl_pending"] is True


def test_list_joins_live_terminals_by_pinned_id(scanned):
    r = client().get("/api/agent-sessions", params={"project_name": "demo", "pty": ["claude:p1", "junk", "claude:"]})
    assert r.status_code == 200
    joined = {s["id"]: s.get("pty_session_id") for s in r.json()["sessions"]}
    assert joined == {"x1": None, "c1": "p1"}


def test_list_joins_codex_by_start_time(scanned, monkeypatch):
    monkeypatch.setattr(ah, "_session_started_at", lambda sid: 200.0 if sid == "p9" else None)
    r = client().get("/api/agent-sessions", params={"project_name": "demo", "pty": "codex:p9"})
    assert {s["id"]: s.get("pty_session_id") for s in r.json()["sessions"]}["x1"] == "p9"


def write_transcript(path: Path):
    lines = [
        {"type": "user", "cwd": "C:\\work\\app", "message": {"role": "user", "content": "hello"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": f"key {FAKE}"}]}},
    ]
    path.write_text("\n".join(json.dumps(o) for o in lines) + "\n", encoding="utf-8")


def test_preview_returns_redacted_messages(tmp_path, monkeypatch):
    p = tmp_path / "c1.jsonl"
    write_transcript(p)
    monkeypatch.setattr(ags, "find_session", lambda repo, agent, sid, **kw: {"agent": "claude", "path": str(p)})
    r = client().get("/api/agent-sessions/claude/c1/preview", params={"project_name": "demo"})
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert FAKE not in json.dumps(msgs) and "[REDACTED]" in msgs[1]["text"]


def test_preview_rejects_bad_agent_and_id():
    assert client().get("/api/agent-sessions/pi/c1/preview", params={"project_name": "demo"}).status_code == 400
    assert client().get("/api/agent-sessions/claude/bad%20id/preview", params={"project_name": "demo"}).status_code == 400


def test_preview_unknown_project_session_or_deleted_file_is_404(tmp_path, monkeypatch):
    assert client().get("/api/agent-sessions/claude/c1/preview", params={"project_name": "nope"}).status_code == 404
    monkeypatch.setattr(ags, "find_session", lambda repo, agent, sid, **kw: None)
    assert client().get("/api/agent-sessions/claude/c1/preview", params={"project_name": "demo"}).status_code == 404
    gone = {"agent": "claude", "path": str(tmp_path / "gone.jsonl")}
    monkeypatch.setattr(ags, "find_session", lambda repo, agent, sid, **kw: gone)
    assert client().get("/api/agent-sessions/claude/c1/preview", params={"project_name": "demo"}).status_code == 404


def test_app_includes_the_router():
    src = (Path(__file__).parent.parent / "web" / "app.py").read_text(encoding="utf-8")
    assert "from routes.agent_session_routes import router as agent_session_router" in src
    assert "app.include_router(agent_session_router)" in src
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_agent_session_routes.py -v`
Expected: collection error, `ImportError: cannot import name 'agent_session_routes' from 'routes'`.

- [ ] **Step 3: Write the routes**

Create `web/routes/agent_session_routes.py`:

```python
"""Agent session history: this project's past and live agent sessions.

GET only. Resume goes through POST /api/generic-agent/terminal (resume_id), which
already requires CSRF, so nothing here mutates state.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query

import agent_handoff
import agent_sessions
import generic_agent
from skills.code_agent import projects as code_projects

router = APIRouter()


def _repo_path(project_name: str) -> str:
    repo_path = (code_projects.get_project(project_name) or {}).get("repo_path")
    if not repo_path:
        raise HTTPException(status_code=404, detail="Unknown project.")
    return repo_path


def _live_terminals(pty: list[str]) -> list[dict]:
    live = []
    for item in pty:
        agent, _, pty_id = item.partition(":")
        if agent not in agent_sessions.AGENTS or not pty_id:
            continue
        session_id = generic_agent.pinned_session_id(pty_id)
        created_at = agent_handoff._session_started_at(pty_id)
        if session_id is None and created_at is None:
            continue
        live.append({"agent": agent, "pty_session_id": pty_id, "session_id": session_id, "created_at": created_at})
    return live


def _list_sessions(repo_path: str, pty: list[str]) -> dict:
    agents = tuple(a for a in agent_sessions.AGENTS if generic_agent.is_installed(a))
    records = agent_sessions.scan_project(repo_path, agents=agents)
    wsl, pending = agent_sessions.wsl_sessions(repo_path)
    records = sorted([*records, *wsl], key=lambda r: r["last_active_at"], reverse=True)
    records = records[: agent_sessions.MAX_SESSIONS]
    red = agent_handoff.Redactor(agent_handoff._configured_api_keys())
    records = [dict(r, title=red(r["title"])) for r in records]
    joined = agent_sessions.join_live(records, _live_terminals(pty))
    return {"sessions": [agent_sessions.public(r) for r in joined], "wsl_pending": pending}


@router.get("/api/agent-sessions")
async def list_agent_sessions(project_name: str, pty: list[str] = Query(default=[])):
    repo_path = _repo_path(project_name)
    return await asyncio.to_thread(_list_sessions, repo_path, pty)


@router.get("/api/agent-sessions/{agent}/{session_id}/preview")
async def preview_agent_session(agent: str, session_id: str, project_name: str):
    if agent not in agent_sessions.AGENTS or not agent_sessions.SESSION_ID_RE.match(session_id):
        raise HTTPException(status_code=400, detail="Unknown agent or session id.")
    repo_path = _repo_path(project_name)

    def load():
        rec = agent_sessions.find_session(repo_path, agent, session_id)
        if rec is None:
            return None
        try:
            return agent_sessions.preview(rec)
        except OSError:
            return None

    messages = await asyncio.to_thread(load)
    if messages is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"messages": messages}
```

In `web/app.py`, after line 95 (`from routes.generic_agent_routes import router as generic_agent_router`) add:

```python
from routes.agent_session_routes import router as agent_session_router
```

After line 954 (`app.include_router(generic_agent_router)`) add:

```python
app.include_router(agent_session_router)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_agent_session_routes.py tests/test_csrf_route_inventory.py -v`
Expected: all PASS. The CSRF inventory stays green because both new routes are GET.

- [ ] **Step 5: Commit**

```bash
git add web/routes/agent_session_routes.py web/app.py tests/test_agent_session_routes.py
git commit -m "feat: add agent session list and preview routes"
```

---

### Task 7: Launch route accepts `resume_id`

**Files:**

- Modify: `web/routes/generic_agent_routes.py` (request model at 26, handoff validation at 122-129, final `else` branch at 176-193, pin at 196-197)
- Test: `tests/test_agent_resume_launch.py`

**Interfaces:**

- Consumes: `agent_sessions.find_session(repo_path, agent, session_id) -> record | None` (record keys `id`, `source`, `cwd`), `agent_sessions.SESSION_ID_RE`, `generic_agent.build_resume_command(agent, repo_path, session_id, source, extra_args)`, `generic_agent.pin_resume(agent, command, pty_session_id, session_id)`.
- Produces: `POST /api/generic-agent/terminal` accepts `resume_id: str | None`. With it the route always spawns a new process running the agent's own resume command. Errors: 400 (bad id, agent is not claude or codex, or `handoff_id` also sent), 404 (no such session in this project), 409 (the session exists but cannot be resumed here, for example the agent binary or its WSL distro is gone).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_resume_launch.py`:

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import agent_sessions as ags
import generic_agent
from routes import generic_agent_routes
from security import verify_csrf

BODY = {"agent": "claude", "project_id": "demo", "repo_path": "C:\\work\\app", "resume_id": "abc-1"}


def client():
    app = FastAPI()
    app.include_router(generic_agent_routes.router)
    app.dependency_overrides[verify_csrf] = lambda: None
    return TestClient(app)


@pytest.fixture
def env(monkeypatch):
    calls = {"spawn": [], "resume": []}

    import routes.terminal as terminal

    monkeypatch.setattr(terminal, "create_pty_session", lambda sid, **kw: calls["spawn"].append({"sid": sid, **kw}))
    monkeypatch.setattr(generic_agent, "wsl_agents", lambda: (None, {}))
    monkeypatch.setattr(generic_agent, "effective_binding", lambda agent: (("-c", "x=1"), {"K": "v"}))
    monkeypatch.setattr(generic_agent, "_pinned_sessions", {})
    monkeypatch.setattr(generic_agent, "_active_sessions", {})
    monkeypatch.setattr(
        ags, "find_session",
        lambda repo, agent, sid, **kw: {"id": sid, "agent": agent, "source": "windows", "cwd": repo} if sid == "abc-1" else None,
    )

    def fake_resume(agent, repo_path, session_id, source="windows", extra_args=()):
        calls["resume"].append({"agent": agent, "repo_path": repo_path, "id": session_id, "source": source, "extra": extra_args})
        return [f"C:\\bin\\{agent}.exe", "--resume", session_id]

    monkeypatch.setattr(generic_agent, "build_resume_command", fake_resume)
    return calls


def test_resume_spawns_the_resume_command_and_pins_the_session(env):
    r = client().post("/api/generic-agent/terminal", json=BODY)
    assert r.status_code == 200 and r.json()["created"] is True
    assert env["resume"] == [
        {"agent": "claude", "repo_path": "C:\\work\\app", "id": "abc-1", "source": "windows", "extra": ("-c", "x=1")}
    ]
    spawn = env["spawn"][-1]
    assert spawn["command"] == ["C:\\bin\\claude.exe", "--resume", "abc-1"]
    assert spawn["cwd"] == "C:\\work\\app"
    assert spawn["env"] == {"K": "v"}
    assert generic_agent.pinned_session_id(r.json()["pty_session_id"]) == "abc-1"


def test_resume_always_spawns_even_when_a_live_session_exists(env, monkeypatch):
    import routes.terminal as terminal
    from types import SimpleNamespace

    monkeypatch.setattr(generic_agent, "_active_sessions", {("demo", "claude"): "existing"})
    monkeypatch.setattr(terminal, "get_pty_session", lambda sid: SimpleNamespace(done=False))
    r = client().post("/api/generic-agent/terminal", json=BODY)
    assert r.json()["created"] is True and r.json()["pty_session_id"] != "existing"
    assert len(env["spawn"]) == 1


def test_resume_of_a_wsl_session_runs_in_its_distro_with_the_linux_path(env, monkeypatch):
    wsl = {"id": "abc-1", "agent": "claude", "source": "wsl:Ubuntu", "cwd": "/mnt/c/work/app"}
    monkeypatch.setattr(ags, "find_session", lambda repo, agent, sid, **kw: wsl)
    client().post("/api/generic-agent/terminal", json=BODY)
    assert env["resume"][-1]["repo_path"] == "/mnt/c/work/app"
    assert env["resume"][-1]["source"] == "wsl:Ubuntu"
    assert env["spawn"][-1]["cwd"] == "C:\\work\\app"


def test_resume_rejects_bad_requests(env):
    c = client()
    assert c.post("/api/generic-agent/terminal", json={**BODY, "agent": "crush"}).status_code == 400
    assert c.post("/api/generic-agent/terminal", json={**BODY, "resume_id": "bad id"}).status_code == 400
    assert c.post("/api/generic-agent/terminal", json={**BODY, "handoff_id": "f" * 32}).status_code == 400
    assert c.post("/api/generic-agent/terminal", json={**BODY, "resume_id": "missing"}).status_code == 404
    assert env["spawn"] == []


def test_resume_that_cannot_run_here_is_409(env, monkeypatch):
    monkeypatch.setattr(generic_agent, "build_resume_command", lambda *a, **kw: None)
    r = client().post("/api/generic-agent/terminal", json=BODY)
    assert r.status_code == 409
    assert env["spawn"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_agent_resume_launch.py -v`
Expected: FAIL. Without a `resume_id` field the route ignores it, so the first test sees `env["resume"] == []`.

- [ ] **Step 3: Implement**

In `web/routes/generic_agent_routes.py`:

1. Add the import below `import generic_agent`:

```python
import agent_sessions
```

2. Add the field to `GenericAgentTerminalRequest`, below `handoff_id`:

```python
    resume_id: str | None = None  # reopen a stored session in its own agent; always a new process
```

3. Replace the region from `handoff = None` through `force_new = req.force_new or handoff is not None` with the block below. The resume checks run first so a request carrying both ids gets its 400 before the handoff is loaded:

```python
    resume = None
    if req.resume_id:
        if req.handoff_id:
            raise HTTPException(status_code=400, detail="A session cannot be resumed and handed off at once.")
        if req.agent not in ("claude", "codex"):
            raise HTTPException(status_code=400, detail=f"{req.agent!r} cannot resume a session.")
        if not agent_sessions.SESSION_ID_RE.match(req.resume_id):
            raise HTTPException(status_code=400, detail="Invalid session id.")
        resume = await asyncio.to_thread(agent_sessions.find_session, req.repo_path, req.agent, req.resume_id)
        if resume is None:
            raise HTTPException(status_code=404, detail="Session not found in this project.")

    handoff = None
    if req.handoff_id:
        if req.agent == generic_agent.TERMINAL_AGENT:
            raise HTTPException(status_code=400, detail=f"{req.agent!r} cannot continue a handoff.")
        handoff = await asyncio.to_thread(agent_handoff.load_handoff, req.handoff_id)
        if handoff is None:
            raise HTTPException(status_code=404, detail="Handoff expired or not found.")
    force_new = req.force_new or handoff is not None or resume is not None
```

4. In the final `else:` branch, replace the `command = generic_agent.build_command(...)` line and the `if not command:` check with:

```python
        binding = generic_agent.effective_binding(req.agent)
        extra = binding[0] if binding else ()
        if resume is not None:
            command = generic_agent.build_resume_command(
                req.agent,
                resume["cwd"] if resume["source"] != "windows" else req.repo_path,
                resume["id"],
                resume["source"],
                extra,
            )
            if not command:
                raise HTTPException(
                    status_code=409,
                    detail=f"This session cannot be resumed here: '{req.agent}' is not available where it was recorded.",
                )
        else:
            command = generic_agent.build_command(req.agent, req.repo_path, extra)
        if not command:
```

Keep the existing body of that `if not command:` block (the install hint and the 500) unchanged, and remove the old `binding = ...` line that this replaces. `env = generic_agent.with_wsl_env(command, binding[1] if binding else None)` stays as is.

5. Replace the pin lines:

```python
    if command:
        command = generic_agent.pin_session(req.agent, command, pty_session_id)
```

with:

```python
    if command:
        if resume is not None:
            command = generic_agent.pin_resume(req.agent, command, pty_session_id, resume["id"])
        else:
            command = generic_agent.pin_session(req.agent, command, pty_session_id)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_agent_resume_launch.py tests/test_agent_handoff_routes.py tests/test_csrf_route_inventory.py -v`
Expected: all PASS (the existing launch and handoff tests prove the non-resume path is unchanged).

- [ ] **Step 5: Commit**

```bash
git add web/routes/generic_agent_routes.py tests/test_agent_resume_launch.py
git commit -m "feat: resume a stored agent session from the terminal launch route"
```

---

### Task 8: Hand off from a stored session

**Files:**

- Modify: `web/agent_handoff.py` (`prepare_handoff` tail at 524-533; new function after it)
- Modify: `web/routes/generic_agent_routes.py` (`HandoffPrepareRequest` at 36, `prepare_agent_handoff` at 68)
- Test: `tests/test_agent_handoff_stored.py`

**Interfaces:**

- Consumes: `render_transcript(agent, path, red) -> (text, last_user, last_assistant)`, `save_handoff(...)`, `log_event(...)`, `NothingToHandOff`, `agent_sessions.find_session`, `agent_sessions.SESSION_ID_RE`.
- Produces:
  - `agent_handoff._save_prepared(*, agent, project_id, cwd, kind, text, last_user, last_assistant, red) -> dict`: saves the snapshot and logs the `prepared` event.
  - `agent_handoff.prepare_handoff_from_transcript(agent: str, project_id: str, cwd: str, transcript: Path) -> dict`, raising `NothingToHandOff` when the transcript is unreadable or empty.
  - `POST /api/generic-agent/handoff/prepare` body: `pty_session_id` is now optional and `session_id: str | None` is new. Exactly one must be given (else 400). `session_id` only works for claude and codex (400), must match `SESSION_ID_RE` (400), and must exist in the project (404). The response shape is unchanged.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_handoff_stored.py`:

```python
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import agent_handoff as ah
import agent_sessions as ags
import generic_agent
from routes import generic_agent_routes
from security import verify_csrf

FAKE = "aigator-fake-api-key"
STORED = {"agent": "claude", "project_id": "demo", "repo_path": "C:\\work\\app", "session_id": "abc-1"}


def client():
    app = FastAPI()
    app.include_router(generic_agent_routes.router)
    app.dependency_overrides[verify_csrf] = lambda: None
    return TestClient(app)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(ah, "HANDOFF_DIR", tmp_path / "h")
    monkeypatch.setattr(ah, "_configured_api_keys", lambda: [FAKE])
    monkeypatch.setattr(generic_agent, "wsl_agents", lambda: (None, {}))
    monkeypatch.setattr(generic_agent, "is_installed", lambda a: True)
    transcript = tmp_path / "abc-1.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        ags, "find_session",
        lambda repo, agent, sid, **kw: {"id": sid, "agent": agent, "path": str(transcript)} if sid == "abc-1" else None,
    )
    monkeypatch.setattr(
        ah, "render_transcript",
        lambda agent, path, red=None: (f"user: hi\nassistant: key {FAKE}", "hi", "done"),
    )
    return transcript


def test_prepare_from_transcript_saves_a_redacted_snapshot(env):
    record = ah.prepare_handoff_from_transcript("claude", "demo", "C:\\work\\app", env)
    assert record["source_kind"] == "transcript" and record["source_agent"] == "claude"
    snap = (ah.HANDOFF_DIR / f"{record['handoff_id']}.txt").read_text(encoding="utf-8")
    assert FAKE not in snap and "[REDACTED]" in snap
    assert record["redactions"] >= 1


def test_prepare_from_transcript_with_nothing_to_render_raises(env, monkeypatch):
    monkeypatch.setattr(ah, "render_transcript", lambda agent, path, red=None: ("  ", "", ""))
    with pytest.raises(ah.NothingToHandOff):
        ah.prepare_handoff_from_transcript("claude", "demo", "C:\\work\\app", env)


def test_prepare_from_transcript_unreadable_raises_nothing_to_hand_off(env, monkeypatch):
    def boom(agent, path, red=None):
        raise OSError("gone")

    monkeypatch.setattr(ah, "render_transcript", boom)
    with pytest.raises(ah.NothingToHandOff):
        ah.prepare_handoff_from_transcript("claude", "demo", "C:\\work\\app", env)


def test_route_prepares_from_a_stored_session(env):
    r = client().post("/api/generic-agent/handoff/prepare", json=STORED)
    assert r.status_code == 200
    data = r.json()
    assert data["source_kind"] == "transcript" and len(data["handoff_id"]) == 32
    assert isinstance(data["targets"], list)


def test_route_needs_exactly_one_source(env):
    c = client()
    both = {**STORED, "pty_session_id": "p1"}
    neither = {k: v for k, v in STORED.items() if k != "session_id"}
    assert c.post("/api/generic-agent/handoff/prepare", json=both).status_code == 400
    assert c.post("/api/generic-agent/handoff/prepare", json=neither).status_code == 400


def test_route_rejects_bad_stored_requests(env):
    c = client()
    assert c.post("/api/generic-agent/handoff/prepare", json={**STORED, "agent": "crush"}).status_code == 400
    assert c.post("/api/generic-agent/handoff/prepare", json={**STORED, "session_id": "bad id"}).status_code == 400
    assert c.post("/api/generic-agent/handoff/prepare", json={**STORED, "session_id": "missing"}).status_code == 404


def test_route_empty_stored_session_is_422(env, monkeypatch):
    monkeypatch.setattr(ah, "render_transcript", lambda agent, path, red=None: ("", "", ""))
    assert client().post("/api/generic-agent/handoff/prepare", json=STORED).status_code == 422


def test_existing_live_prepare_still_requires_a_pty_id(env, monkeypatch):
    monkeypatch.setattr(ah, "find_transcript", lambda agent, cwd, home=None, **kw: None)
    monkeypatch.setattr(ah, "_session_started_at", lambda sid: None)
    monkeypatch.setattr(ah, "capture_pane", lambda sid, red=None: "pane")
    live = {"agent": "claude", "project_id": "demo", "repo_path": "C:\\work\\app", "pty_session_id": "p1"}
    assert client().post("/api/generic-agent/handoff/prepare", json=live).status_code == 200
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_agent_handoff_stored.py -v`
Expected: FAIL with `AttributeError: module 'agent_handoff' has no attribute 'prepare_handoff_from_transcript'` and 422s from the route (`pty_session_id` is still required).

- [ ] **Step 3: Implement**

In `web/agent_handoff.py`, replace the tail of `prepare_handoff` (from `record = save_handoff(` to `return record`) with:

```python
    return _save_prepared(
        agent=agent, project_id=project_id, cwd=cwd, kind=kind, text=text,
        last_user=last_user, last_assistant=last_assistant, red=red,
    )


def _save_prepared(
    *, agent: str, project_id: str, cwd: str, kind: str, text: str,
    last_user: str, last_assistant: str, red: Redactor,
) -> dict:
    record = save_handoff(
        source_agent=agent, project_id=project_id, cwd=cwd, source_kind=kind, text=text,
        last_user=last_user, last_assistant=last_assistant, api_key=red.keys,
        prior_redactions=red.count,
    )
    log_event(
        "prepared", project_id=project_id, source=agent, source_kind=kind,
        snapshot_bytes=record["snapshot_bytes"], redactions=record["redactions"],
    )
    return record


def prepare_handoff_from_transcript(agent: str, project_id: str, cwd: str, transcript: Path) -> dict:
    """Hand off a stored session: its transcript is the only source, there is no pane to fall back on."""
    red = Redactor(_configured_api_keys())
    try:
        text, last_user, last_assistant = render_transcript(agent, transcript, red)
    except Exception as exc:
        _log.warning("agent_handoff transcript unreadable (%s)", type(exc).__name__)
        raise NothingToHandOff()
    if not text.strip():
        raise NothingToHandOff()
    return _save_prepared(
        agent=agent, project_id=project_id, cwd=cwd, kind="transcript", text=text,
        last_user=last_user, last_assistant=last_assistant, red=red,
    )
```

In `web/routes/generic_agent_routes.py`, replace `HandoffPrepareRequest` with:

```python
class HandoffPrepareRequest(BaseModel):
    agent: str
    project_id: str
    repo_path: str
    pty_session_id: str | None = None  # a live terminal...
    session_id: str | None = None  # ...or a stored session from the history panel
```

and replace the body of `prepare_agent_handoff` up to the `except` with:

```python
@router.post("/api/generic-agent/handoff/prepare", dependencies=[Depends(verify_csrf)])
async def prepare_agent_handoff(req: HandoffPrepareRequest):
    if not generic_agent.is_supported(req.agent):
        raise HTTPException(status_code=400, detail=f"Unknown agent: {req.agent!r}")
    if bool(req.pty_session_id) == bool(req.session_id):
        raise HTTPException(status_code=400, detail="Give either pty_session_id or session_id.")
    try:
        if req.session_id:
            if req.agent not in ("claude", "codex"):
                raise HTTPException(status_code=400, detail=f"{req.agent!r} has no stored sessions.")
            if not agent_sessions.SESSION_ID_RE.match(req.session_id):
                raise HTTPException(status_code=400, detail="Invalid session id.")
            stored = await asyncio.to_thread(
                agent_sessions.find_session, req.repo_path, req.agent, req.session_id
            )
            if stored is None:
                raise HTTPException(status_code=404, detail="Session not found in this project.")
            record = await asyncio.to_thread(
                agent_handoff.prepare_handoff_from_transcript,
                req.agent, req.project_id, req.repo_path, Path(stored["path"]),
            )
        else:
            record = await asyncio.to_thread(
                agent_handoff.prepare_handoff,
                req.agent, req.project_id, req.repo_path, req.pty_session_id,
            )
    except agent_handoff.NothingToHandOff:
        raise HTTPException(status_code=422, detail="Nothing to hand off from this session.")
```

Leave the `return {...}` block after it unchanged. Add `from pathlib import Path` to the stdlib imports at the top of the file (`import asyncio` is already there).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_agent_handoff_stored.py tests/test_agent_handoff_routes.py tests/test_agent_handoff.py tests/test_csrf_route_inventory.py -v`
Expected: all PASS. If `tests/test_agent_handoff.py` does not exist in this repo, drop it from the command.

- [ ] **Step 5: Commit**

```bash
git add web/agent_handoff.py web/routes/generic_agent_routes.py tests/test_agent_handoff_stored.py
git commit -m "feat: hand off from a stored session's transcript"
```

---

### Task 9: `agent-history.js` pure functions

**Files:**

- Create: `web/static/agent-history.js`
- Test: `tests/agent_history.test.js`

**Interfaces:**

- Consumes: server session records from `GET /api/agent-sessions` (`id, agent, title, branch, started_at, last_active_at, state, source`, optional `pty_session_id`; times are epoch **seconds**) and live terminal objects from the terminal module (`ptySessionId, agent, _lastOutputAt, _viewedAt`; times are **milliseconds**).
- Produces, on `module.exports` in node and `window.agentHistory` in the browser:
  - `WORKING_MS = 3000`.
  - `dayGroup(ts: seconds, nowMs) -> 'today' | 'yesterday' | 'earlier'` (local calendar days).
  - `relTime(ts: seconds, nowMs) -> string` ("just now", "5 min ago", "3 h ago", "2 d ago", else a short date).
  - `liveState(term, nowMs) -> 'working' | 'needs_you' | 'done'`: working if the last output was under 3000 ms ago; needs_you if output has gone quiet and arrived after the user last looked at the terminal; else done.
  - `buildRows(sessions, terminals, nowMs, agentLabel?) -> Row[]` where `Row = {key, id, agent, title, branch, source, lastActive (seconds), state, group, ptySessionId | null}`. A server record joined to a live terminal takes that terminal's `liveState`; an open terminal that no record claims (and is not the bare `terminal` agent) becomes a synthesized row titled `New <Agent> session` with `id: null`.
  - `shortAge(ts: seconds, nowMs) -> string` ("<1m", "4m", "3h", "2d").
  - `metaLine(row, nowMs, agentLabel?) -> string`: the row's second line, `Agent · branch · time`; the branch is dropped when empty, `WSL` is added for a WSL source, and the time reads `waiting 4m` for a needs-you row, `2m` for a working row, otherwise `3 h ago` style.
  - `rowActions(row) -> string[]`: `['go']` for a row with a live terminal, else `['resume', 'handoff']`.
  - `filterGroups(rows, query) -> [{key, title, rows}]` in the order Needs you, Working, Today, Yesterday, Earlier; empty groups dropped; every whitespace-separated word of `query` must appear in the row's title, branch or agent (case-insensitive); rows newest first.
  - `needsYou(terminals, nowMs) -> boolean`.

- [ ] **Step 1: Write the failing test**

Create `tests/agent_history.test.js`:

```js
const assert = require('assert');
const h = require('../web/static/agent-history.js');

const NOW = new Date(2026, 10, 15, 12, 0, 0).getTime();
const at = (m, d, hh, mm) => new Date(2026, m, d, hh, mm).getTime() / 1000;

// day groups use local calendar days
{
  assert.strictEqual(h.dayGroup(at(10, 15, 0, 30), NOW), 'today');
  assert.strictEqual(h.dayGroup(at(10, 14, 23, 0), NOW), 'yesterday');
  assert.strictEqual(h.dayGroup(at(10, 14, 0, 0), NOW), 'yesterday');
  assert.strictEqual(h.dayGroup(at(10, 13, 23, 59), NOW), 'earlier');
  assert.strictEqual(
    h.dayGroup(at(10, 15, 13, 0), NOW),
    'today',
    'a clock-skewed future time is today',
  );
}

// relative time
{
  const ago = (sec) => NOW / 1000 - sec;
  assert.strictEqual(h.relTime(ago(5), NOW), 'just now');
  assert.strictEqual(h.relTime(ago(50), NOW), '1 min ago');
  assert.strictEqual(h.relTime(ago(5 * 60), NOW), '5 min ago');
  assert.strictEqual(h.relTime(ago(3 * 3600), NOW), '3 h ago');
  assert.strictEqual(h.relTime(ago(2 * 86400), NOW), '2 d ago');
  const old = h.relTime(ago(30 * 86400), NOW);
  assert(old.length > 0 && !old.includes('ago'), 'older than a week is a date');
  assert.strictEqual(h.relTime(ago(-60), NOW), 'just now');
}

// live state: working, needs you, done
{
  assert.strictEqual(h.WORKING_MS, 3000);
  assert.strictEqual(h.liveState({}, NOW), 'done', 'no output yet');
  assert.strictEqual(h.liveState({ _lastOutputAt: NOW - 1000, _viewedAt: 0 }, NOW), 'working');
  assert.strictEqual(h.liveState({ _lastOutputAt: NOW - 1000, _viewedAt: NOW }, NOW), 'working');
  assert.strictEqual(
    h.liveState({ _lastOutputAt: NOW - 5000, _viewedAt: NOW - 9000 }, NOW),
    'needs_you',
  );
  assert.strictEqual(h.liveState({ _lastOutputAt: NOW - 5000 }, NOW), 'needs_you', 'never viewed');
  assert.strictEqual(
    h.liveState({ _lastOutputAt: NOW - 5000, _viewedAt: NOW - 4000 }, NOW),
    'done',
  );
  assert.strictEqual(
    h.liveState({ _lastOutputAt: NOW - 5000, _viewedAt: NOW - 5000 }, NOW),
    'done',
  );
}

// needsYou looks only at live terminals
{
  const quiet = { _lastOutputAt: NOW - 5000, _viewedAt: 0 };
  const busy = { _lastOutputAt: NOW - 500, _viewedAt: 0 };
  assert.strictEqual(h.needsYou([busy, quiet], NOW), true);
  assert.strictEqual(h.needsYou([busy], NOW), false);
  assert.strictEqual(h.needsYou([], NOW), false);
  assert.strictEqual(h.needsYou(undefined, NOW), false);
}

const rec = (id, agent, title, last, extra) =>
  Object.assign(
    {
      id,
      agent,
      title,
      branch: 'main',
      started_at: last - 60,
      last_active_at: last,
      state: 'done',
      source: 'windows',
    },
    extra || {},
  );
const term = (pty, agent, out, viewed) => ({
  ptySessionId: pty,
  agent,
  _lastOutputAt: out,
  _viewedAt: viewed,
});

// rows: stored, joined live, and unclaimed live terminals
{
  const sessions = [
    rec('s1', 'claude', 'Fix the login bug', at(10, 15, 9, 0)),
    rec('s2', 'codex', 'Add dark mode', at(10, 14, 16, 0)),
    rec('s3', 'claude', 'Refactor parser', at(10, 1, 9, 0), { pty_session_id: 'p3' }),
    rec('s4', 'claude', 'Joined but its terminal closed', at(10, 15, 8, 0), {
      pty_session_id: 'gone',
    }),
  ];
  const terminals = [
    term('p3', 'claude', NOW - 9000, NOW - 20000),
    term('p9', 'codex', NOW - 1000, 0),
    term('p10', 'terminal', NOW - 1000, 0),
  ];
  const rows = h.buildRows(sessions, terminals, NOW, (a) => a.toUpperCase());
  const by = Object.fromEntries(rows.map((r) => [r.key, r]));

  assert.strictEqual(by['claude:s1'].group, 'today');
  assert.strictEqual(by['claude:s1'].ptySessionId, null);
  assert.strictEqual(by['codex:s2'].group, 'yesterday');
  assert.strictEqual(by['claude:s3'].state, 'needs_you');
  assert.strictEqual(by['claude:s3'].group, 'needs_you');
  assert.strictEqual(by['claude:s3'].ptySessionId, 'p3');
  assert.strictEqual(by['claude:s4'].state, 'done', 'a stale join falls back to a stored row');
  assert.strictEqual(by['claude:s4'].ptySessionId, null);

  const synth = by['live:p9'];
  assert.strictEqual(synth.title, 'New CODEX session');
  assert.strictEqual(synth.id, null);
  assert.strictEqual(synth.state, 'working');
  assert.strictEqual(synth.group, 'working');
  assert.strictEqual(synth.ptySessionId, 'p9');
  assert(!by['live:p10'], 'a bare terminal is not an agent session');
  assert.strictEqual(rows.length, 5);
}

// a live terminal's newer output lifts the row's last-active time
{
  const rows = h.buildRows(
    [rec('s1', 'claude', 'T', at(10, 15, 9, 0), { pty_session_id: 'p1' })],
    [term('p1', 'claude', NOW - 1000, 0)],
    NOW,
  );
  assert.strictEqual(rows[0].lastActive, (NOW - 1000) / 1000);
}

// meta line
{
  const lab = (a) => a[0].toUpperCase() + a.slice(1);
  const ago = (sec) => NOW / 1000 - sec;
  const row = (o) =>
    Object.assign({ agent: 'claude', branch: 'main', source: 'windows', state: 'done' }, o);
  assert.strictEqual(h.shortAge(ago(10), NOW), '<1m');
  assert.strictEqual(h.shortAge(ago(240), NOW), '4m');
  assert.strictEqual(h.shortAge(ago(3 * 3600), NOW), '3h');
  assert.strictEqual(h.shortAge(ago(2 * 86400), NOW), '2d');
  assert.strictEqual(
    h.metaLine(row({ lastActive: ago(3 * 3600) }), NOW, lab),
    'Claude · main · 3 h ago',
  );
  assert.strictEqual(
    h.metaLine(row({ state: 'needs_you', lastActive: ago(240) }), NOW, lab),
    'Claude · main · waiting 4m',
  );
  assert.strictEqual(
    h.metaLine(row({ state: 'working', lastActive: ago(120) }), NOW, lab),
    'Claude · main · 2m',
  );
  assert.strictEqual(
    h.metaLine(row({ branch: '', lastActive: ago(10) }), NOW, lab),
    'Claude · just now',
  );
  assert.strictEqual(
    h.metaLine(row({ source: 'wsl:Ubuntu', lastActive: ago(10) }), NOW, lab),
    'Claude · main · WSL · just now',
  );
}

// actions
{
  assert.deepStrictEqual(h.rowActions({ ptySessionId: 'p1' }), ['go']);
  assert.deepStrictEqual(h.rowActions({ ptySessionId: null }), ['resume', 'handoff']);
}

// filtering and grouping
{
  const sessions = [
    rec('a', 'claude', 'Fix login bug', at(10, 15, 9, 0), { branch: 'fix/login' }),
    rec('b', 'codex', 'Add dark mode', at(10, 15, 10, 0), { branch: 'feat/theme' }),
    rec('c', 'claude', 'Old spike', at(10, 1, 10, 0), { branch: 'spike' }),
    rec('d', 'claude', 'Yesterday task', at(10, 14, 10, 0)),
  ];
  const rows = h.buildRows(sessions, [term('p1', 'claude', NOW - 9000, 0)], NOW);
  const all = h.filterGroups(rows, '');
  assert.deepStrictEqual(
    all.map((g) => g.key),
    ['needs_you', 'today', 'yesterday', 'earlier'],
  );
  assert.deepStrictEqual(
    all.find((g) => g.key === 'today').rows.map((r) => r.id),
    ['b', 'a'],
  );
  assert.deepStrictEqual(
    all.find((g) => g.key === 'needs_you').rows.map((r) => r.id),
    [null],
  );

  const login = h.filterGroups(rows, 'LOGIN');
  assert.deepStrictEqual(
    login.map((g) => g.key),
    ['today'],
  );
  assert.deepStrictEqual(
    h
      .filterGroups(rows, 'fix/login')
      .flatMap((g) => g.rows)
      .map((r) => r.id),
    ['a'],
  );
  assert.deepStrictEqual(
    h
      .filterGroups(rows, 'codex theme')
      .flatMap((g) => g.rows)
      .map((r) => r.id),
    ['b'],
  );
  assert.deepStrictEqual(h.filterGroups(rows, 'login codex'), [], 'every word must match');
  assert.deepStrictEqual(
    h.filterGroups(rows, '   ').length,
    all.length,
    'blank query shows everything',
  );
}

console.log('agent_history: ok');
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node tests/agent_history.test.js`
Expected: FAIL with `Cannot find module '../web/static/agent-history.js'`.

- [ ] **Step 3: Write the module**

Create `web/static/agent-history.js`:

```js
// Agent session history: pure helpers (grouping, live state, search) and, in the
// browser, the History panel. The helpers are exported for node tests.
(function (root) {
  'use strict';

  const WORKING_MS = 3000;
  const GROUPS = [
    { key: 'needs_you', title: 'Needs you' },
    { key: 'working', title: 'Working' },
    { key: 'today', title: 'Today' },
    { key: 'yesterday', title: 'Yesterday' },
    { key: 'earlier', title: 'Earlier' },
  ];

  // ts is epoch seconds (server clock); nowMs is epoch milliseconds.
  function dayGroup(ts, nowMs) {
    const now = new Date(nowMs);
    const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const startYesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1).getTime();
    const t = ts * 1000;
    if (t >= startToday) return 'today';
    if (t >= startYesterday) return 'yesterday';
    return 'earlier';
  }

  function relTime(ts, nowMs) {
    const sec = Math.max(0, Math.floor(nowMs / 1000 - ts));
    if (sec < 45) return 'just now';
    const min = Math.floor(sec / 60);
    if (min < 60) return Math.max(1, min) + ' min ago';
    const hr = Math.floor(min / 60);
    if (hr < 24) return hr + ' h ago';
    const day = Math.floor(hr / 24);
    if (day < 7) return day + ' d ago';
    return new Date(ts * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }

  // term._lastOutputAt and term._viewedAt are epoch milliseconds.
  function liveState(term, nowMs) {
    const out = term._lastOutputAt || 0;
    if (out && nowMs - out < WORKING_MS) return 'working';
    if (out && out > (term._viewedAt || 0)) return 'needs_you';
    return 'done';
  }

  function needsYou(terminals, nowMs) {
    return (terminals || []).some((t) => liveState(t, nowMs) === 'needs_you');
  }

  function groupOf(state, lastActive, nowMs) {
    return state === 'needs_you' || state === 'working' ? state : dayGroup(lastActive, nowMs);
  }

  function buildRows(sessions, terminals, nowMs, agentLabel) {
    const label = agentLabel || ((a) => a);
    const live = new Map();
    (terminals || []).forEach((t) => {
      if (t.ptySessionId) live.set(t.ptySessionId, t);
    });
    const claimed = new Set();
    const rows = (sessions || []).map((s) => {
      const term = s.pty_session_id ? live.get(s.pty_session_id) : null;
      if (term) claimed.add(term.ptySessionId);
      const state = term ? liveState(term, nowMs) : 'done';
      const lastActive =
        term && term._lastOutputAt
          ? Math.max(s.last_active_at, term._lastOutputAt / 1000)
          : s.last_active_at;
      return {
        key: s.agent + ':' + s.id,
        id: s.id,
        agent: s.agent,
        title: s.title,
        branch: s.branch || '',
        source: s.source,
        lastActive,
        state,
        group: groupOf(state, lastActive, nowMs),
        ptySessionId: term ? term.ptySessionId : null,
      };
    });
    live.forEach((term, pty) => {
      if (claimed.has(pty) || term.agent === 'terminal') return;
      const state = liveState(term, nowMs);
      const lastActive = (term._lastOutputAt || nowMs) / 1000;
      rows.push({
        key: 'live:' + pty,
        id: null,
        agent: term.agent,
        title: 'New ' + label(term.agent) + ' session',
        branch: '',
        source: 'windows',
        lastActive,
        state,
        group: groupOf(state, lastActive, nowMs),
        ptySessionId: pty,
      });
    });
    return rows;
  }

  function shortAge(ts, nowMs) {
    const sec = Math.max(0, Math.floor(nowMs / 1000 - ts));
    if (sec < 60) return '<1m';
    if (sec < 3600) return Math.floor(sec / 60) + 'm';
    if (sec < 86400) return Math.floor(sec / 3600) + 'h';
    return Math.floor(sec / 86400) + 'd';
  }

  function metaLine(row, nowMs, agentLabel) {
    const label = agentLabel || ((a) => a);
    let when;
    if (row.state === 'needs_you') when = 'waiting ' + shortAge(row.lastActive, nowMs);
    else if (row.state === 'working') when = shortAge(row.lastActive, nowMs);
    else when = relTime(row.lastActive, nowMs);
    const parts = [label(row.agent)];
    if (row.branch) parts.push(row.branch);
    if (row.source && row.source !== 'windows') parts.push('WSL');
    parts.push(when);
    return parts.join(' · ');
  }

  function rowActions(row) {
    return row.ptySessionId ? ['go'] : ['resume', 'handoff'];
  }

  function filterGroups(rows, query) {
    const words = String(query || '')
      .toLowerCase()
      .split(/\s+/)
      .filter(Boolean);
    const hit = (r) => {
      const hay = (r.title + ' ' + r.branch + ' ' + r.agent).toLowerCase();
      return words.every((w) => hay.includes(w));
    };
    return GROUPS.map((g) => ({
      key: g.key,
      title: g.title,
      rows: rows
        .filter((r) => r.group === g.key && hit(r))
        .sort((a, b) => b.lastActive - a.lastActive),
    })).filter((g) => g.rows.length);
  }

  const api = {
    WORKING_MS,
    dayGroup,
    relTime,
    liveState,
    needsYou,
    buildRows,
    shortAge,
    metaLine,
    rowActions,
    filterGroups,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.agentHistory = api;
})(typeof window !== 'undefined' ? window : globalThis);
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `node tests/agent_history.test.js`
Expected: prints `agent_history: ok`.

- [ ] **Step 5: Commit**

```bash
git add web/static/agent-history.js tests/agent_history.test.js
git commit -m "feat: add agent history grouping, live-state and search helpers"
```

---

### Task 10: Terminal module and handoff dialog hooks

**Files:**

- Modify: `web/static/tp-generic-agent-terminal.js` (`_genAgentActivateSession` ~494, both spawn bodies in `_genAgentStart` ~884-905, output handler ~1355)
- Modify: `web/static/agent-handoff.js` (`renderDialog` 229-320, `openDialog` 410-446)
- Test: `tests/test_agent_history_frontend.py`, `tests/agent_handoff_ui.test.js`

**Interfaces:**

- Consumes: `_genAgentEnsureTermsContainer(tabId)` (returns the tab's terminal state, creating it when the tab has none), `_genAgentStart(tabId, agent, projectId, repoPath, opts)`, `window.agentHistory.isViewing(sess)` (defined in Task 11; every call here is guarded by `window.agentHistory &&`).
- Produces:
  - `_genAgentStart` opts gain `resumeId` and the spawn request carries `resume_id`.
  - Every terminal session object gets `_viewedAt` (ms): set when the session is activated and while its output arrives in the terminal the user is looking at.
  - `agentHandoff.openDialog({tabId, sess, stored?, project?})`: with `stored = {agent, id}` and `project = {id, repoPath}` it prepares a handoff from that stored session (`session_id` in the request body instead of `pty_session_id`) and works on a tab that has no terminal yet. `sess` is then just `{agent}`. Without `stored` behaviour is unchanged.
  - `agentHandoff.prepareBody(opts, project) -> object`: the JSON body for `/api/generic-agent/handoff/prepare` (pure, node-tested).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_history_frontend.py`:

```python
"""Source-string wiring checks for the agent history UI (the DOM paths need a real browser)."""

from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
TERM = (STATIC / "tp-generic-agent-terminal.js").read_text(encoding="utf-8")
HANDOFF = (STATIC / "agent-handoff.js").read_text(encoding="utf-8")


def test_spawn_requests_carry_the_resume_id():
    assert TERM.count("resume_id: opts.resumeId") == 2  # _ocFetch and fetch branches


def test_activating_a_session_marks_it_viewed():
    assert "if (sess) sess._viewedAt = Date.now();" in TERM


def test_output_in_the_viewed_terminal_counts_as_seen():
    assert "if (window.agentHistory && agentHistory.isViewing(sess)) sess._viewedAt = sess._lastOutputAt;" in TERM


def test_handoff_dialog_takes_a_stored_session():
    assert "opts.stored" in HANDOFF
    assert "keepStateAgent: !!state.agent" in HANDOFF
    assert "_genAgentEnsureTermsContainer(opts.tabId)" in HANDOFF
```

Append to `tests/agent_handoff_ui.test.js`, above its final line (or at the end if it has none):

```js
// prepare body: a live terminal sends pty_session_id, a stored session sends session_id
{
  const state = { projectId: 'demo', repoPath: 'C:\\work\\app' };
  assert.deepStrictEqual(h.prepareBody({ sess: { agent: 'claude', ptySessionId: 'p1' } }, state), {
    agent: 'claude',
    project_id: 'demo',
    repo_path: 'C:\\work\\app',
    pty_session_id: 'p1',
  });
  assert.deepStrictEqual(
    h.prepareBody({ sess: { agent: 'codex' }, stored: { agent: 'codex', id: 'abc-1' } }, state),
    { agent: 'codex', project_id: 'demo', repo_path: 'C:\\work\\app', session_id: 'abc-1' },
  );
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_agent_history_frontend.py -v` and `node tests/agent_handoff_ui.test.js`
Expected: the four Python tests FAIL (strings absent) and the node test throws `h.prepareBody is not a function`.

- [ ] **Step 3: Implement the terminal module hooks**

In `web/static/tp-generic-agent-terminal.js`:

1. In `_genAgentActivateSession`, directly after `const sess = state.sessions[ptyId];` add:

```js
if (sess) sess._viewedAt = Date.now();
```

2. In both spawn bodies of `_genAgentStart` (the `_ocFetch` one and the `fetch` one), add a line after each `handoff_id: opts.handoffId,`:

```js
              resume_id: opts.resumeId,
```

Match the indentation of the surrounding keys in each branch (14 spaces in both).

3. In the output handler, directly after `sess._lastOutputAt = Date.now();` add:

```js
if (window.agentHistory && agentHistory.isViewing(sess)) sess._viewedAt = sess._lastOutputAt;
```

- [ ] **Step 4: Implement the handoff dialog changes**

In `web/static/agent-handoff.js`:

1. Add the pure body builder above `// ── Browser-only below ──`:

```js
function prepareBody(opts, project) {
  const body = {
    agent: opts.sess.agent,
    project_id: project.projectId,
    repo_path: project.repoPath,
  };
  if (opts.stored) body.session_id = opts.stored.id;
  else body.pty_session_id = opts.sess.ptySessionId;
  return body;
}
```

and add `prepareBody,` to the `api` object (after `errorDetail,`).

2. Change the `renderDialog` signature to `function renderDialog(prep, sess, state, tabId, project) {` and, inside `begin()`, replace the `_genAgentStart(...)` call with:

```js
_genAgentStart(tabId, target, project.projectId, project.repoPath, {
  forceNew: true,
  handoffId: prep.handoff_id,
  keepStateAgent: !!state.agent,
});
```

3. Replace `openDialog` with:

```js
async function openDialog(opts) {
  if (dialogBusy || document.querySelector('.agent-handoff-overlay')) return;
  const stored = opts.stored || null;
  const state = stored
    ? _genAgentEnsureTermsContainer(opts.tabId)
    : _genAgentTerminals[_caSessionKey(opts.tabId)];
  if (!state || !opts.sess) return;
  if (stored ? !opts.project : !opts.sess.ptySessionId) return;
  const project = stored
    ? { projectId: opts.project.id, repoPath: opts.project.repoPath }
    : { projectId: state.projectId, repoPath: state.repoPath };
  dialogBusy = true;
  try {
    const doFetch = typeof _ocFetch === 'function' ? _ocFetch : fetch;
    let prep;
    try {
      const headers = await _caHeadersAsync();
      const resp = await doFetch('/api/generic-agent/handoff/prepare', {
        method: 'POST',
        headers,
        body: JSON.stringify(prepareBody(opts, project)),
      });
      const body = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        showToast(errorDetail(body, 'Could not prepare the handoff.'), 'warn');
        return;
      }
      prep = body;
      // A malformed 200 (missing fields) throws here, so it gets the same toast.
      renderDialog(prep, opts.sess, state, opts.tabId, project);
    } catch (_) {
      document.querySelectorAll('.agent-handoff-overlay').forEach((el) => el.remove());
      showToast('Could not prepare the handoff.', 'warn');
      return;
    }
  } finally {
    dialogBusy = false;
  }
}
```

- [ ] **Step 5: Run the tests to verify they pass, then commit**

Run: `python -m pytest tests/test_agent_history_frontend.py tests/test_agent_handoff_frontend.py -v`, `node tests/agent_handoff_ui.test.js`, `node tests/agent_limit_detect.test.js`
Expected: all PASS (the existing handoff frontend tests prove the live path is intact).

```bash
git add web/static/tp-generic-agent-terminal.js web/static/agent-handoff.js tests/test_agent_history_frontend.py tests/agent_handoff_ui.test.js
git commit -m "feat: carry resume ids and viewed-state through the terminal and handoff dialog"
```

---

### Task 11: The three icon tabs and the History panel

**Files:**

- Modify: `web/static/tp-code-agent.js` (`_caLeftView` line 7, `_initCodeAgentPane` ~109, `_caSourceControlPanel` 166-191, `_caSetLeftView` and `_caLeftViewRefresh` 193-213)
- Modify: `web/static/agent-history.js` (append the panel controller)
- Modify: `web/static/index.html` (script tag after `agent-handoff.js`, ~line 2025)
- Modify: `web/static/style.css` (`.ca-sc-viewtab` at ~21418, new `.ah-*` block after `.ca-scm-view` at ~21445)
- Test: `tests/test_agent_history_frontend.py`

**Interfaces:**

- Consumes (all already global in the browser):
  - From Task 9: `buildRows, filterGroups, metaLine, rowActions, needsYou`.
  - From Task 10: `agentHandoff.openDialog({tabId, sess, stored, project})`, the `resume_id` option of `_genAgentStart`.
  - Existing: `_activeTabId`, `_caProjects` (`[{name, repo_path}]`), `_caActiveProject` (a project name), `_caSessionKey(tabId)`, `_genAgentTerminals[key]` (`{projectId, order, sessions, agent}`), `_genAgentLabel(agent)`, `_genAgentTabIcon(agent)`, `_genAgentStart(tabId, agent, projectId, repoPath, opts)`, `_genAgentStartInFlight(tabId)`, `_genAgentActivateSession(tabId, ptyId)`, `_caCloseFileDiff('ca-file-diff-view')`, `_ocFetch`.
  - Server: `GET /api/agent-sessions?project_name=<name>&pty=<agent>:<ptySessionId>...` returning `{sessions, wsl_pending}`; `GET /api/agent-sessions/{agent}/{id}/preview?project_name=<name>` returning `{messages: [{role, text}]}`.
- Produces on `window.agentHistory`: `show()` (called when the History tab opens), `refresh()`, `updateDot()`, `isViewing(sess) -> boolean`, `liveSessions() -> term[]`, plus every Task 9 function.
- DOM ids: `ca-viewtab-explorer`, `ca-viewtab-scm`, `ca-viewtab-history`, `ca-hist-view`, `ca-hist-search`, `ca-hist-list`. `_caSetLeftView('scm' | 'explorer' | 'history')` is already in the `GATOR_ACTIONS` allow-list in `app.js`; no change there.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_history_frontend.py` (add `import re` at the top and these constants under the existing ones):

```python
CODE = (STATIC / "tp-code-agent.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "style.css").read_text(encoding="utf-8")
HISTORY = (STATIC / "agent-history.js").read_text(encoding="utf-8")


def test_left_panel_has_three_icon_tabs():
    for name in ("explorer", "scm", "history"):
        assert f'id="ca-viewtab-{name}"' in CODE
        assert f"gatorActionAttrs('_caSetLeftView', ['{name}'])" in CODE
    for label in ("Files", "Changes", "History"):
        assert f'aria-label="{label}"' in CODE
        assert f'title="{label}"' in CODE
    assert ">Source Control</button>" not in CODE
    assert ">Explorer</button>" not in CODE


def test_history_pane_markup_is_in_the_left_panel():
    for el in ('id="ca-hist-view"', 'id="ca-hist-search"', 'id="ca-hist-list"'):
        assert el in CODE


def test_switching_views_covers_history_and_survives_a_pane_rebuild():
    assert "agentHistory.show()" in CODE
    assert "agentHistory.refresh()" in CODE
    assert "if (_caLeftView !== 'scm') _caSetLeftView(_caLeftView);" in CODE


def test_history_script_loads_after_handoff_and_before_the_terminal_module():
    h, a, t = (INDEX.index(n) for n in ("agent-handoff.js", "agent-history.js", "tp-generic-agent-terminal.js"))
    assert h < a < t


def test_history_styles_use_theme_variables_only():
    block = CSS.split("/* agent session history: start */")[1].split("/* agent session history: end */")[0]
    assert ".ah-row" in block and ".ca-hist-view" in block
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", block)


def test_history_panel_never_builds_markup_from_session_text():
    ctl = HISTORY.split("Browser panel")[1]
    assert "innerHTML" not in ctl
    assert "insertAdjacentHTML" not in ctl
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_agent_history_frontend.py -v`
Expected: the six new tests FAIL (strings and markers absent; `split("Browser panel")[1]` raises `IndexError`).

- [ ] **Step 3: Rebuild the tab strip and add the pane in `tp-code-agent.js`**

1. Line 7: change the comment so it reads `// 'scm' | 'explorer' | 'history' — which view the left pane shows`.

2. Above `function _caSourceControlPanel()` add the three icons (stroke icons that take `currentColor`):

```js
const _CA_TAB_ICON_FILES =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>';
const _CA_TAB_ICON_CHANGES =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="8" r="2.5"/><path d="M6 8.5v7"/><path d="M18 10.5c0 4-5 4-9 5"/></svg>';
const _CA_TAB_ICON_HISTORY =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/></svg>';
```

3. In `_caSourceControlPanel`, replace the `<div class="ca-sc-viewtabs">…</div>` block (the two text buttons) with:

```js
      <div class="ca-sc-viewtabs">
        <button class="ca-sc-viewtab" id="ca-viewtab-explorer" title="Files" aria-label="Files"${gatorActionAttrs('_caSetLeftView', ['explorer'])}>${_CA_TAB_ICON_FILES}</button>
        <button class="ca-sc-viewtab active" id="ca-viewtab-scm" title="Changes" aria-label="Changes"${gatorActionAttrs('_caSetLeftView', ['scm'])}>${_CA_TAB_ICON_CHANGES}</button>
        <button class="ca-sc-viewtab" id="ca-viewtab-history" title="History" aria-label="History"${gatorActionAttrs('_caSetLeftView', ['history'])}>${_CA_TAB_ICON_HISTORY}</button>
      </div>
```

and add the history pane right after the `ca-fe-view` div (before the closing `</div>` of `ca-sc-panel`):

```js
<div id="ca-hist-view" class="ca-hist-view" style="display:none">
  <div class="ah-search">
    <input
      id="ca-hist-search"
      type="search"
      placeholder="Search this project's sessions"
      aria-label="Search this project's sessions"
      autocomplete="off"
    />
  </div>
  <div id="ca-hist-list" class="ah-list" role="list"></div>
</div>
```

4. Replace `_caSetLeftView` and `_caLeftViewRefresh` (and update the section comment to `Source Control / Explorer / History`):

```js
function _caSetLeftView(view) {
  const panes = { scm: 'ca-scm-view', explorer: 'ca-fe-view', history: 'ca-hist-view' };
  if (!panes[view]) view = 'scm';
  if (!Object.values(panes).every((id) => document.getElementById(id))) return;
  _caLeftView = view;
  Object.entries(panes).forEach(([name, id]) => {
    document.getElementById(id).style.display = name === view ? '' : 'none';
    document.getElementById('ca-viewtab-' + name)?.classList.toggle('active', name === view);
  });
  if (view === 'explorer') _caLoadFileTree('', document.getElementById('ca-fe-root'), 0);
  if (view === 'history' && window.agentHistory) agentHistory.show();
}

function _caLeftViewRefresh() {
  if (_caLeftView === 'explorer') {
    _caLoadFileTree('', document.getElementById('ca-fe-root'), 0);
  } else if (_caLeftView === 'history') {
    if (window.agentHistory) agentHistory.refresh();
  } else {
    _caRefreshSourceControl(true);
  }
}
```

5. In `_initCodeAgentPane`, directly after `leftCol.innerHTML = _caSourceControlPanel();` add (the rebuilt panel always starts on Changes, so put the remembered view back):

```js
if (_caLeftView !== 'scm') _caSetLeftView(_caLeftView);
```

- [ ] **Step 4: Load the script**

In `web/static/index.html`, directly after the `agent-handoff.js` `document.write` (line ~2025) and before the `tp-generic-agent-terminal.js` one (line ~2027), add the same three-part form used by its neighbours:

```js
document.write('<scr' + 'ipt src="/static/agent-history.js' + _cacb + '"><\/scr' + 'ipt>');
```

- [ ] **Step 5: Add the panel controller to `agent-history.js`**

Delete everything from the line `  const api = {` to the end of the file and append the following (the pure helpers above it are unchanged). Functions that touch `document` are only called from the browser; the interval starts only when `document` exists, so the node test still loads the module.

```js
  // ── Browser panel ────────────────────────────────────────────────────────
  const FETCH_MS = 15000;
  const TICK_MS = 2000;
  const WSL_POLL_MS = 2000;
  const WSL_POLL_MAX = 5;

  const ui = {
    sessions: [],
    project: null,
    wslPending: false,
    wslPolls: 0,
    wslTimer: null,
    error: false,
    loaded: false,
    busy: false,
    fetchedAt: 0,
    query: '',
    openKey: null,
    previews: {},
    notice: {},
    sig: '',
  };

  function agentName(agent) {
    return typeof _genAgentLabel === 'function' ? _genAgentLabel(agent) : agent;
  }

  function context() {
    const tabId = typeof _activeTabId !== 'undefined' ? _activeTabId : null;
    const project =
      typeof _caProjects !== 'undefined' && typeof _caActiveProject !== 'undefined'
        ? _caProjects.find((p) => p.name === _caActiveProject) || null
        : null;
    return { tabId, project };
  }

  function terminalState(tabId) {
    if (tabId === null || typeof _genAgentTerminals === 'undefined') return null;
    return _genAgentTerminals[_caSessionKey(tabId)] || null;
  }

  function liveSessions() {
    const { tabId, project } = context();
    const st = terminalState(tabId);
    if (!st || !project || st.projectId !== project.name) return [];
    return st.order.map((id) => st.sessions[id]).filter(Boolean);
  }

  function panelVisible() {
    const pane = document.getElementById('ca-hist-view');
    return !!pane && pane.offsetParent !== null;
  }

  function isViewing(sess) {
    return !!sess.container && sess.container.offsetParent !== null && !document.hidden;
  }

  function updateDot() {
    const btn = document.getElementById('ca-viewtab-history');
    if (!btn) return;
    const attention = needsYou(liveSessions(), Date.now());
    btn.classList.toggle('has-attention', attention);
    const text = attention ? 'History (a session needs you)' : 'History';
    btn.title = text;
    btn.setAttribute('aria-label', text);
  }

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function fetcher() {
    return typeof _ocFetch === 'function' ? _ocFetch : fetch;
  }

  async function load() {
    const { project } = context();
    if (!project) {
      ui.project = null;
      ui.sessions = [];
      ui.loaded = true;
      render();
      return;
    }
    if (ui.busy) return;
    if (ui.project !== project.name) {
      ui.project = project.name;
      ui.sessions = [];
      ui.loaded = false;
      ui.openKey = null;
      ui.previews = {};
      ui.notice = {};
      ui.wslPolls = 0;
    }
    ui.busy = true;
    ui.fetchedAt = Date.now();
    const params = new URLSearchParams({ project_name: project.name });
    liveSessions().forEach((t) => {
      if (t.ptySessionId && t.agent !== 'terminal') params.append('pty', t.agent + ':' + t.ptySessionId);
    });
    try {
      const resp = await fetcher()('/api/agent-sessions?' + params.toString());
      if (!resp.ok) throw new Error('status ' + resp.status);
      const data = await resp.json();
      const now = context().project;
      if (!now || now.name !== project.name) return;
      ui.sessions = data.sessions || [];
      ui.wslPending = !!data.wsl_pending;
      ui.error = false;
    } catch (_) {
      ui.error = true;
    } finally {
      ui.busy = false;
    }
    ui.loaded = true;
    render();
    scheduleWslPoll();
  }

  function scheduleWslPoll() {
    if (ui.wslTimer || !ui.wslPending || ui.wslPolls >= WSL_POLL_MAX) return;
    ui.wslPolls += 1;
    ui.wslTimer = setTimeout(() => {
      ui.wslTimer = null;
      if (panelVisible()) load();
    }, WSL_POLL_MS);
  }

  function closeFileView() {
    if (document.getElementById('ca-file-diff-view') && typeof _caCloseFileDiff === 'function') {
      _caCloseFileDiff('ca-file-diff-view');
    }
  }

  function goToTerminal(row) {
    const { tabId } = context();
    if (tabId === null || typeof _genAgentActivateSession !== 'function') return;
    closeFileView();
    _genAgentActivateSession(tabId, row.ptySessionId);
  }

  async function resume(row) {
    const { tabId, project } = context();
    if (!project || typeof _genAgentStart !== 'function') return;
    if (typeof _genAgentStartInFlight === 'function' && _genAgentStartInFlight(tabId)) return;
    const before = terminalState(tabId);
    const count = before ? before.order.length : 0;
    closeFileView();
    await _genAgentStart(tabId, row.agent, project.name, project.repo_path, {
      forceNew: true,
      resumeId: row.id,
      keepStateAgent: !!(before && before.agent),
    });
    const after = terminalState(tabId);
    if (after && after.order.length > count) {
      delete ui.notice[row.key];
      load();
      return;
    }
    ui.notice[row.key] = 'Could not resume this session. It may have been deleted.';
    render();
    load();
  }

  function handoff(row) {
    const { tabId, project } = context();
    if (!project || !window.agentHandoff) return;
    window.agentHandoff.openDialog({
      tabId,
      sess: { agent: row.agent },
      stored: { agent: row.agent, id: row.id },
      project: { id: project.name, repoPath: project.repo_path },
    });
  }

  async function loadPreview(row) {
    const { project } = context();
    if (!project) return;
    const prev = ui.previews[row.key];
    if (!prev || prev.status !== 'ok') {
      ui.previews[row.key] = { status: 'loading' };
      render();
    }
    let result;
    try {
      const url =
        '/api/agent-sessions/' +
        encodeURIComponent(row.agent) +
        '/' +
        encodeURIComponent(row.id) +
        '/preview?project_name=' +
        encodeURIComponent(project.name);
      const resp = await fetcher()(url);
      if (resp.status === 404) {
        result = { status: 'error', message: 'This session is no longer on disk.' };
        load();
      } else if (!resp.ok) {
        result = { status: 'error', message: 'Could not load the preview.' };
      } else {
        const data = await resp.json();
        result = { status: 'ok', messages: data.messages || [] };
      }
    } catch (_) {
      result = { status: 'error', message: 'Could not load the preview.' };
    }
    ui.previews[row.key] = result;
    render();
  }

  function toggleOpen(row) {
    if (ui.openKey === row.key) {
      ui.openKey = null;
      render();
      return;
    }
    ui.openKey = row.key;
    delete ui.notice[row.key];
    render();
    if (row.id) loadPreview(row);
  }

  function actionButton(row, action) {
    const spec = {
      go: ['Go to terminal', true, goToTerminal],
      resume: ['Resume', true, resume],
      handoff: ['Continue in another agent…', false, handoff],
    }[action];
    const btn = el('button', 'ah-btn' + (spec[1] ? ' ah-btn-primary' : ''), spec[0]);
    btn.type = 'button';
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      spec[2](row);
    });
    return btn;
  }

  function buildDetail(row) {
    const box = el('div', 'ah-detail');
    if (row.id) {
      const pv = ui.previews[row.key];
      const body = el('div', 'ah-preview');
      if (!pv || pv.status === 'loading') {
        body.appendChild(el('div', 'ah-note', 'Loading preview…'));
      } else if (pv.status === 'error') {
        body.appendChild(el('div', 'ah-note', pv.message));
      } else if (!pv.messages.length) {
        body.appendChild(el('div', 'ah-note', 'Nothing to preview yet.'));
      } else {
        pv.messages.forEach((m) => {
          const user = m.role === 'user';
          const msg = el('div', 'ah-msg ' + (user ? 'ah-msg-user' : 'ah-msg-assistant'));
          msg.appendChild(el('span', 'ah-role', user ? 'You' : 'Agent'));
          msg.appendChild(el('span', 'ah-text', m.text));
          body.appendChild(msg);
        });
      }
      box.appendChild(body);
    }
    if (ui.notice[row.key]) box.appendChild(el('div', 'ah-note ah-note-warn', ui.notice[row.key]));
    const bar = el('div', 'ah-actions');
    rowActions(row).forEach((a) => bar.appendChild(actionButton(row, a)));
    box.appendChild(bar);
    return box;
  }

  function buildRow(row, now) {
    const open = ui.openKey === row.key;
    const item = el('div', 'ah-item' + (open ? ' open' : ''));
    item.setAttribute('role', 'listitem');
    const head = el('div', 'ah-row ah-state-' + row.state);
    head.tabIndex = 0;
    head.setAttribute('role', 'button');
    head.setAttribute('aria-expanded', open ? 'true' : 'false');
    head.title = row.title;
    const lead = el('span', 'ah-lead');
    if (row.state === 'needs_you' || row.state === 'working') {
      const dot = el('span', 'ah-dot ah-dot-' + row.state);
      dot.setAttribute('role', 'img');
      dot.setAttribute('aria-label', row.state === 'needs_you' ? 'Needs you' : 'Working');
      lead.appendChild(dot);
    } else if (typeof _genAgentTabIcon === 'function') {
      lead.appendChild(_genAgentTabIcon(row.agent));
    }
    const main = el('span', 'ah-main');
    main.appendChild(el('span', 'ah-title', row.title));
    main.appendChild(el('span', 'ah-meta', metaLine(row, now, agentName)));
    head.appendChild(lead);
    head.appendChild(main);
    head.addEventListener('click', () => toggleOpen(row));
    head.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        toggleOpen(row);
      }
    });
    item.appendChild(head);
    if (open) item.appendChild(buildDetail(row));
    return item;
  }

  function emptyText(rows, groups) {
    const { project } = context();
    if (!project) return 'Open a project to see its sessions.';
    if (!ui.loaded) return 'Loading sessions…';
    if (groups.length) return '';
    if (ui.query.trim()) return 'No sessions match “' + ui.query.trim() + '”.';
    if (ui.error && !rows.length) return '';
    return 'No agent sessions in this project yet.';
  }

  function render() {
    const list = document.getElementById('ca-hist-list');
    if (!list) return;
    const now = Date.now();
    const rows = buildRows(ui.sessions, liveSessions(), now, agentName);
    const groups = filterGroups(rows, ui.query);
    const sig = JSON.stringify([
      ui.error,
      ui.loaded,
      ui.wslPending && ui.wslPolls < WSL_POLL_MAX,
      ui.query,
      ui.openKey,
      ui.openKey && ui.previews[ui.openKey],
      ui.openKey && ui.notice[ui.openKey],
      context().project && context().project.name,
      groups.map((g) => [
        g.key,
        g.rows.map((r) => [r.key, r.state, r.title, r.ptySessionId, metaLine(r, now, agentName)]),
      ]),
    ]);
    if (sig === ui.sig && list.childNodes.length) return;
    ui.sig = sig;
    const top = list.scrollTop;
    list.textContent = '';
    groups.forEach((g) => {
      const section = el('div', 'ah-group ah-group-' + g.key);
      section.appendChild(el('div', 'ah-group-label', g.title));
      g.rows.forEach((r) => section.appendChild(buildRow(r, now)));
      list.appendChild(section);
    });
    const message = emptyText(rows, groups);
    if (message) list.appendChild(el('div', 'ah-empty', message));
    if (ui.error) {
      const box = el('div', 'ah-empty', 'Could not load sessions. ');
      const retry = el('button', 'ah-btn', 'Retry');
      retry.type = 'button';
      retry.addEventListener('click', () => refresh());
      box.appendChild(retry);
      list.appendChild(box);
    }
    if (ui.wslPending && ui.wslPolls < WSL_POLL_MAX) list.appendChild(el('div', 'ah-foot', 'Checking WSL…'));
    list.scrollTop = top;
  }

  function bindSearch() {
    const input = document.getElementById('ca-hist-search');
    if (!input || input.dataset.bound) return;
    input.dataset.bound = '1';
    input.value = ui.query;
    input.addEventListener('input', () => {
      ui.query = input.value;
      render();
    });
  }

  function show() {
    bindSearch();
    ui.wslPolls = 0;
    render();
    load();
  }

  function refresh() {
    ui.wslPolls = 0;
    load();
  }

  function tick() {
    updateDot();
    if (!panelVisible()) return;
    const { project } = context();
    if (!project || ui.project !== project.name || Date.now() - ui.fetchedAt > FETCH_MS) load();
    else render();
  }

  if (typeof document !== 'undefined') setInterval(tick, TICK_MS);

  const api = {
    WORKING_MS,
    dayGroup,
    relTime,
    liveState,
    needsYou,
    buildRows,
    shortAge,
    metaLine,
    rowActions,
    filterGroups,
    show,
    refresh,
    updateDot,
    isViewing,
    liveSessions,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.agentHistory = api;
})(typeof window !== 'undefined' ? window : globalThis);
```

The marker the Task 11 test splits on is the comment `// ── Browser panel ──…`; keep the words `Browser panel` in it exactly.

Note: the pure-helper `api` block from Task 9 is removed by the deletion above, so the file has one `api` object and one export.

- [ ] **Step 6: Restyle the tabs and add the History styles**

In `web/static/style.css`:

1. Replace the `.ca-sc-viewtab { … }` rule (the text-tab version, ~21418-21437) with the icon-button version, leave `:hover` and `.active` as they are, and add the focus and attention rules after `.ca-sc-viewtab.active`:

```css
.ca-sc-viewtab {
  flex: 1;
  position: relative;
  background: none;
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 4px;
  color: var(--text-sub, #4a6a8a);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  transition:
    color 0.15s,
    border-color 0.15s;
}
.ca-sc-viewtab svg {
  width: 16px;
  height: 16px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.ca-sc-viewtab:focus-visible {
  outline: 1px solid var(--accent, #4ade80);
  outline-offset: -3px;
}
.ca-sc-viewtab.has-attention::after {
  content: '';
  position: absolute;
  top: 8px;
  left: calc(50% + 6px);
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--warn);
  box-shadow: 0 0 0 2px var(--surface);
}
```

2. After the `.ca-scm-view { … }` rule add the History block. It uses theme variables only and so reads correctly in both themes with no `[data-theme='light']` overrides:

```css
/* agent session history: start */
.ca-hist-view {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}
.ah-search {
  padding: 8px 10px;
  flex-shrink: 0;
}
.ah-search input {
  width: 100%;
  box-sizing: border-box;
  padding: 6px 8px;
  font: inherit;
  font-size: 12px;
  color: var(--text);
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 6px;
  outline: none;
}
.ah-search input::placeholder {
  color: var(--text-sub);
}
.ah-search input:focus {
  border-color: var(--accent);
}
.ah-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-bottom: 8px;
  scrollbar-width: thin;
  scrollbar-color: var(--border2) transparent;
}
.ah-list::-webkit-scrollbar {
  width: 3px;
}
.ah-list::-webkit-scrollbar-track {
  background: transparent;
}
.ah-list::-webkit-scrollbar-thumb {
  background: var(--border2);
  border-radius: 2px;
}
.ah-group-label {
  padding: 10px 12px 4px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-sub);
}
.ah-group-needs_you .ah-group-label {
  color: var(--warn);
}
.ah-group-working .ah-group-label {
  color: var(--accent);
}
.ah-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 12px;
  cursor: pointer;
  border-left: 2px solid transparent;
}
.ah-row:hover,
.ah-item.open .ah-row {
  background: var(--bg-hover);
}
.ah-row:focus-visible {
  outline: 1px solid var(--accent);
  outline-offset: -1px;
}
.ah-state-needs_you {
  border-left-color: var(--warn);
}
.ah-lead {
  flex: 0 0 16px;
  height: 16px;
  margin-top: 1px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-dim);
}
.ah-lead .gtp-tab-icon {
  width: 14px;
  height: 14px;
  display: inline-flex;
}
.ah-lead .gtp-tab-icon svg,
.ah-lead .gtp-tab-icon img {
  width: 100%;
  height: 100%;
}
.ah-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.ah-dot-needs_you {
  background: var(--warn);
}
.ah-dot-working {
  background: var(--accent);
  animation: ah-pulse 1.6s ease-in-out infinite;
}
@keyframes ah-pulse {
  50% {
    opacity: 0.35;
  }
}
@media (prefers-reduced-motion: reduce) {
  .ah-dot-working {
    animation: none;
  }
}
.ah-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.ah-title,
.ah-meta {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ah-title {
  font-size: 12px;
  color: var(--text);
}
.ah-meta {
  font-size: 11px;
  color: var(--text-sub);
}
.ah-detail {
  padding: 2px 12px 10px 38px;
  background: var(--bg-hover);
}
.ah-preview {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 220px;
  overflow-y: auto;
  margin-bottom: 8px;
  scrollbar-width: thin;
  scrollbar-color: var(--border2) transparent;
}
.ah-msg {
  display: flex;
  flex-direction: column;
  gap: 1px;
  font-size: 11px;
  line-height: 1.4;
  color: var(--text-dim);
}
.ah-role {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-sub);
}
.ah-msg-assistant .ah-role {
  color: var(--accent);
}
.ah-text {
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
  white-space: pre-wrap;
  word-break: break-word;
}
.ah-note {
  padding: 2px 0 8px;
  font-size: 11px;
  color: var(--text-sub);
}
.ah-note-warn {
  color: var(--warn);
}
.ah-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.ah-btn {
  font: inherit;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
}
.ah-btn:hover {
  border-color: var(--accent);
}
.ah-btn:focus-visible {
  outline: 1px solid var(--accent);
  outline-offset: 1px;
}
.ah-btn-primary {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--surface);
}
.ah-empty,
.ah-foot {
  padding: 16px 14px;
  font-size: 12px;
  text-align: center;
  color: var(--text-sub);
}
.ah-foot {
  padding: 8px 14px;
  font-size: 11px;
}
/* agent session history: end */
```

- [ ] **Step 7: Run the tests, then format**

Run: `python -m pytest tests/test_agent_history_frontend.py tests/test_agent_handoff_frontend.py -v`, `node tests/agent_history.test.js`, `node tests/agent_handoff_ui.test.js`
Expected: all PASS.

Run: `npx prettier --write web/static/agent-history.js tests/agent_history.test.js` (prettier only reformats; the node test must still print `agent_history: ok`).

- [ ] **Step 8: Commit**

```bash
git add web/static/agent-history.js web/static/tp-code-agent.js web/static/index.html web/static/style.css tests/test_agent_history_frontend.py tests/agent_history.test.js
git commit -m "feat: add the History tab with search, day groups, live status and in-place preview"
```

---

### Task 12: Format, full test run, and browser verification

**Files:**

- Modify (only if a check below fails): the files from Tasks 2-11.

**Interfaces:**

- Consumes: everything from Tasks 2-11. Produces nothing new.

- [ ] **Step 1: Format check**

Run:

```bash
npx prettier --check web/static/agent-history.js web/static/agent-handoff.js web/static/tp-generic-agent-terminal.js web/static/tp-code-agent.js web/static/style.css tests/agent_history.test.js tests/agent_handoff_ui.test.js
```

Expected: `All matched files use Prettier code style!`. If not, run the same command with `--write`, re-run the node tests in Step 2, and include the reformatted files in the commit in Step 5.

- [ ] **Step 2: Full automated run**

```bash
python -m pytest -q
node tests/agent_history.test.js
node tests/agent_handoff_ui.test.js
```

Expected: pytest all PASS (this includes `tests/test_csrf_route_inventory.py`; the history routes are all GET, so `tests/csrf_route_baseline.txt` must be untouched: `git diff --stat tests/csrf_route_baseline.txt` prints nothing); both node scripts print their `ok` line.

- [ ] **Step 3: Start the dev server and open the app**

Restart uvicorn on :8003 (Python changed, so a restart is required; static changes need Ctrl+R). Open the app, open a project that has past Claude or Codex sessions, and use the code-agent view.

- [ ] **Step 4: Check each behaviour in both themes (toggle in Settings; repeat every row)**

| Check                      | Expected                                                                                                                                                                              |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Left panel header          | Three icon tabs, in order Files, Changes, History. Hovering each shows its name. Changes is selected on a fresh load.                                                                 |
| Files and Changes          | Behave exactly as the old Explorer and Source Control tabs did.                                                                                                                       |
| History opens              | Past sessions for this project appear under Today / Yesterday / Earlier, newest first, each with agent icon, title, and `Agent · branch · time`.                                      |
| Search                     | Typing filters by title, agent name and branch; clearing restores the list; a query with no hits shows `No sessions match “…”.`                                                       |
| Preview                    | Clicking a row expands it in place with the first messages (labelled You / Agent); clicking again collapses it. Only one row is open at a time.                                       |
| Redaction                  | A session that contained a token or key shows it masked in the preview.                                                                                                               |
| Resume                     | `Resume` on a stored Claude and a stored Codex session opens a new terminal tab that continues that conversation (the agent's earlier messages are visible).                          |
| Resume failure             | Resume a session whose file was deleted after the list loaded: the row shows `Could not resume this session. It may have been deleted.` and the list refreshes.                       |
| Continue in another agent… | Opens the handoff dialog for that stored session, with the agent picker; confirming starts the other agent with the handoff.                                                          |
| Live rows                  | Start a new agent terminal. Within ~15 s it appears under Working or Today (joined to its stored record, not duplicated). While it prints, its dot pulses.                            |
| Needs you                  | Leave a live agent idle with its tab hidden (view Changes or another terminal). The History icon gets an amber dot and the row sits under Needs you. Viewing that terminal clears it. |
| Go to terminal             | `Go to terminal` on a live row switches to that terminal, including while a file diff is open (the diff closes).                                                                      |
| Resume double click        | Double-clicking Resume starts one terminal, not two.                                                                                                                                  |
| WSL                        | With WSL and an agent installed, `Checking WSL…` shows briefly, then WSL sessions appear with `WSL` in their meta line. Without WSL nothing is shown and nothing errors.              |
| Project switch             | Switching projects replaces the list; an open preview from the old project is gone.                                                                                                   |
| Panel rebuild              | Switching to History, then to another project and back, keeps History selected.                                                                                                       |
| Keyboard                   | Tab reaches each row and button; Enter and Space expand a row; focus rings are visible.                                                                                               |
| Legibility                 | In light theme the amber dot, the primary button label and the dim meta text are all readable.                                                                                        |
| Reduced motion             | With the OS reduced-motion setting on, the working dot does not pulse.                                                                                                                |

Take a dark and a light screenshot of the open History tab (with one row expanded) for the PR description.

- [ ] **Step 5: Resolve the three open questions**

1. Resume a Claude session, then check `~/.claude/projects/<slug>/`. If Claude reused the original id, `pin_resume` is correct as written. If it wrote a new `<new-id>.jsonl`, change `pin_resume` (Task 5) to pin the new id once it appears and add a test for that, then re-run Step 2.
2. Resume a Codex session and confirm its terminal joins its stored record (no extra unjoined `New Codex session` row after ~15 s). If it does not, widen the join in `join_live` (Task 3) and add a test.
3. Titles for Codex Desktop sessions are often generic (the first message is a system preamble). That is accepted for this release; do not add a fix.

Commit any fixes made in this task:

```bash
git status
git add <only the files you changed>
git commit -m "fix: address issues found while verifying agent session history"
```

- [ ] **Step 6: Clean up**

Stop the brainstorming visual companion if it is still running: `scripts/stop-server.sh .superpowers/brainstorm/1469-1794763652` (from the superpowers brainstorming skill directory), and confirm `git status` shows a clean tree. Do not push or open a PR until asked; the PR for `feat/agent-history` is stacked on `feat/agent-handoff` (#117).
