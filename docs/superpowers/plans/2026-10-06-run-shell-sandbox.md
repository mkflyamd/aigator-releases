# run_shell Sandbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `run_shell` runs inside the same OS sandbox as `run_python`; widening access needs a human decision on an approval card, one approval covers a task, and approvals can be saved and managed in Settings.

**Architecture:** `run_shell` builds a `SandboxRequest` and calls the existing `launch_sandboxed`. A gate in `shell_runner/tools.py` decides whether the command needs a card: single-use approvals (`approvals`), per-tab task grants (`task_grants`, new), then saved permissions (`saved_permissions`, new, kept in `secure_store`). The approval routes gain a `scope`, and the chat route ends task grants when a genuinely new user message arrives.

**Tech Stack:** Python 3 (FastAPI, pydantic, pytest), vanilla JS (`web/static/app.js`, node-run `tests/sandbox_ui.test.js`), Windows AppContainer / macOS Seatbelt / Linux bubblewrap launchers already in `web/sandbox/`.

Spec: `docs/superpowers/specs/2026-10-06-run-shell-sandbox-design.md`. Read it before Task 1.

## Global Constraints

- Project name is "AI Gator", never "POC".
- The only fake credential in tests, fixtures, examples and docs is `aigator-fake-api-key`.
- Commit messages carry NO `Co-Authored-By` line. Stage files by name; never `git add -A`; never add the untracked `pip/` folder.
- Human-in-the-loop: nothing here may auto-send email, Teams or Slack. (Not touched by this plan; do not weaken it.)
- All LLM calls stay behind `llm.gateway` (not touched by this plan).
- Same launcher, same deny list (`sandbox/paths.py`), same admin policy file, same card as `run_python`. No second mechanism.
- Approval buttons: **Allow for this task** and **Always allow this**, plus **Deny**.
- A task approval ends when the user sends the next message in that tab (the automatic follow-up after a card click does NOT count: chat request flag `sandbox_followup`), or after `TASK_TTL_SECONDS = 600` seconds, whichever is first.
- Saved permissions are created only by the CSRF-guarded approve route and removed only through the CSRF-guarded Settings routes. The model can never create, change or remove them.
- Saved permissions live in `secure_store` under the name `sandbox/saved-permissions`, JSON `{"version": 1, "entries": [...]}`. Any read error, bad shape or unknown version means an empty list (fail closed).
- Never saveable (per task only): a command whose programs include any of `python python3 py node deno bun ruby perl php bash sh zsh pwsh powershell cmd wsl npx`, a command containing `$(`, a backtick, `<(`, `>(`, `<<`, `eval`, `source`, `-c`/`-Command`/`-e` style code arguments, or anything the parser cannot read.
- Admin policy gains `saved_permissions: allow|deny` (default `allow`). `deny` hides "Always allow", ignores saved entries and keeps task approvals.
- Telemetry `approval` values gain `task_approved`, `saved`, `saved_created`. Telemetry and logs carry metadata only: never paths, hosts or commands.
- The delete blocklist (`_find_delete_command`) still runs first, before everything else.
- Fail closed: if the sandbox cannot start, the command does not run unsandboxed. `background=True` is refused when the sandbox is enforced.
- On Windows with the sandbox enforced, the only shell is `cmd.exe`; WSL is never used when enforced. `dir` and `git` cannot run in the AppContainer cmd (Windows limit of v1); the error hint says so.
- Never put the cwd in `SandboxRequest.write_paths`: the launcher always grants the cwd read/write.
- Plain DOM text only (`textContent`); no `innerHTML` for any command, path, host or saved-permission text.
- Default to no comments; one short line max where a comment is needed.

## File Structure

New:

- `web/sandbox/command_programs.py` — `programs_in(command)`; parses a shell command into program names or `None`.
- `web/sandbox/task_grants.py` — per-tab, in-memory, 10-minute task grants.
- `web/sandbox/saved_permissions.py` — saved permissions on `secure_store`.
- `tests/code_sandbox/test_command_programs.py`, `test_task_grants.py`, `test_saved_permissions.py`, `test_sandbox_routes_scope.py`
- `tests/shell_runner/conftest.py`, `tests/shell_runner/test_run_shell_sandbox.py`, `tests/shell_runner/test_run_shell_sandbox_real.py`

Modified:

- `web/sandbox/paths.py` (`paths_covered`), `web/sandbox/policy.py`, `web/sandbox/approvals.py`
- `web/routes/sandbox_routes.py`, `web/routes/chat.py`
- `web/skills/shell_runner/tools.py`
- `web/static/app.js`, `web/static/index.html`, `tests/sandbox_ui.test.js`
- `docs/BUILD_INSTRUCTIONS.md`, `docs/security/threatmodel-remediation.md`, the spec

Run tests from the repo root: `python -m pytest <path> -q`. pytest config already has `pythonpath = web .` and the `real_sandbox` marker.

---

### Task 1: Command program parser

**Files:**

- Create: `web/sandbox/command_programs.py`
- Test: `tests/code_sandbox/test_command_programs.py`

**Interfaces:**

- Produces: `programs_in(command: str) -> set[str] | None`. `None` means "cannot be saved with network": empty, unreadable, interpreter, wrapper, substitution or code-argument command. Otherwise the lowercase program names (no `.exe/.cmd/.bat`) of every statement.

- [ ] **Step 1: Write the failing test**

```python
import pytest

from sandbox.command_programs import programs_in


@pytest.mark.parametrize("command, expected", [
    ("git status", {"git"}),
    ("git pull && npm install", {"git", "npm"}),
    ("curl https://example.com | tee out.txt", {"curl", "tee"}),
    ("echo hi; echo there", {"echo"}),
    ("GIT.EXE status", {"git"}),
    ("npm.cmd install", {"npm"}),
    ("git log 2>&1", {"git"}),
    ("git status\nnpm test", {"git", "npm"}),
    ("echo 'it is'", {"echo"}),
])
def test_plain_programs(command, expected):
    assert programs_in(command) == expected


@pytest.mark.parametrize("command", [
    "",
    "   ",
    "python script.py",
    "python3 -m http.server",
    "py -3 x.py",
    "node app.js",
    "npx create-thing",
    "bash -c 'curl x'",
    "sh run.sh",
    "powershell -Command Get-Date",
    "cmd /c dir",
    "wsl ls",
    "git status && python x.py",
    "echo $(whoami)",
    "echo `whoami`",
    "diff <(ls) <(ls)",
    "cat <<EOF",
    "eval ls",
    "source env.sh",
    ". ./env.sh",
    "env FOO=1 git status",
    "xargs rm",
    "sudo ls",
    "time git status",
    "find . -exec ls {} +",
    "FOO=bar git status",
    "./run.sh",
    "C:\\tools\\x.exe",
    "/usr/bin/git status",
    "(git status)",
    "{ git status; }",
    "echo 'unbalanced",
    "echo \"a;b\"",
    "git status -c core.pager=x",
    "if true; then git status; fi",
    "for f in a b; do git add $f; done",
    "!git",
])
def test_unsaveable_commands_return_none(command):
    assert programs_in(command) is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/code_sandbox/test_command_programs.py -q`
Expected: FAIL (`ModuleNotFoundError: sandbox.command_programs`).

- [ ] **Step 3: Implement**

```python
"""Program names in a shell command, for "Always allow this" with network.

Returns None for anything that is not a plain sequence of ordinary programs
(interpreters, wrappers, substitutions, code arguments, unreadable quoting).
None means the permission can be granted for this task only, never saved.
Over-inclusive splitting is deliberate: a false None is safe, a false set is not.
"""
from __future__ import annotations

import re
import shlex

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")
_SPLIT = re.compile(r";|&&|\|\||\||&|\n|\r")
_FD_DUP = re.compile(r"\d*>&\d*|&>")
_FORBIDDEN = ("$(", "`", "<(", ">(", "<<")
_INTERPRETERS = frozenset(
    "python python3 py node deno bun ruby perl php bash sh zsh pwsh powershell cmd wsl npx".split()
)
_KEYWORDS = frozenset(
    "eval source . exec env xargs sudo nohup nice time timeout command builtin watch start call find "
    "if then else elif fi for while until do done case esac function select !".split()
)
_CODE_FLAGS = frozenset("-c -e -command -encodedcommand -ec --eval -exec -execdir -ok".split())
_SUFFIXES = (".exe", ".cmd", ".bat")


def programs_in(command: str) -> set[str] | None:
    if not command or not command.strip():
        return None
    if any(marker in command for marker in _FORBIDDEN):
        return None
    try:
        shlex.split(command)
    except ValueError:
        return None
    programs: set[str] = set()
    for statement in _SPLIT.split(_FD_DUP.sub(" ", command)):
        tokens = statement.split()
        if not tokens:
            continue
        first = tokens[0]
        if not _NAME.fullmatch(first):
            return None
        name = first.lower()
        for suffix in _SUFFIXES:
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        if name in _INTERPRETERS or name in _KEYWORDS:
            return None
        if any(token.lower() in _CODE_FLAGS for token in tokens):
            return None
        programs.add(name)
    return programs or None
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python -m pytest tests/code_sandbox/test_command_programs.py -q`
Expected: all pass. If a case fails, fix the implementation (not the case) unless the case contradicts the Global Constraints.

- [ ] **Step 5: Commit**

```bash
git add web/sandbox/command_programs.py tests/code_sandbox/test_command_programs.py
git commit -m "feat: command program parser decides which shell commands can be saved with network"
```

---

### Task 2: Task grants and path coverage

**Files:**

- Modify: `web/sandbox/paths.py` (append `paths_covered`; `Path` and `is_within` already exist there)
- Create: `web/sandbox/task_grants.py`
- Test: `tests/code_sandbox/test_task_grants.py`

**Interfaces:**

- Consumes: `sandbox.paths.is_within(child: Path, parent: Path) -> bool` (True for equal or nested, case-insensitive).
- Produces:
  - `paths.paths_covered(read, write, granted_read, granted_write) -> bool` (all arguments are iterables of `str | Path`): every requested write lies inside a granted write folder; every requested read lies inside a granted read or write folder.
  - `task_grants.TASK_TTL_SECONDS = 600`
  - `task_grants.add(context_id, read, write, hosts, now=None) -> None`
  - `task_grants.covers(context_id, read, write, hosts, now=None) -> bool`
  - `task_grants.end_for_tab(context_id) -> None`
  - `task_grants._reset() -> None`
  - The tab key is `context_id or ""`; callers use `req.context_id or "default"` consistently, so a missing tab id is `"default"` on both the add and the end side.

- [ ] **Step 1: Write the failing test**

```python
import pytest

from sandbox import task_grants
from sandbox.paths import paths_covered


@pytest.fixture(autouse=True)
def _fresh():
    task_grants._reset()
    yield
    task_grants._reset()


def test_paths_covered_rules(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    sub = a / "sub"
    for d in (a, b, sub):
        d.mkdir()
    assert paths_covered([], [sub], [], [a])
    assert paths_covered([sub], [], [], [a])
    assert paths_covered([sub], [], [a], [])
    assert not paths_covered([], [sub], [a], [])
    assert not paths_covered([b], [], [], [a])
    assert paths_covered([], [], [], [])
    assert not paths_covered([a], [], [sub], [])


def test_grant_covers_subset_only(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    task_grants.add("t1", [], [str(a)], ["h.example:443"], now=100.0)
    assert task_grants.covers("t1", [], [str(a)], [], now=101.0)
    assert task_grants.covers("t1", [str(a)], [], ["h.example:443"], now=101.0)
    assert not task_grants.covers("t1", [], [str(a)], ["other.example:443"], now=101.0)
    assert not task_grants.covers("t2", [], [str(a)], [], now=101.0)


def test_union_of_grants(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    task_grants.add("t1", [str(a)], [], [], now=100.0)
    task_grants.add("t1", [], [str(b)], [], now=101.0)
    assert task_grants.covers("t1", [str(a), str(b)], [str(b)], [], now=102.0)


def test_expires_after_ttl(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    task_grants.add("t1", [], [str(a)], [], now=100.0)
    assert task_grants.covers("t1", [], [str(a)], [], now=100.0 + task_grants.TASK_TTL_SECONDS)
    assert not task_grants.covers("t1", [], [str(a)], [], now=100.0 + task_grants.TASK_TTL_SECONDS + 1)


def test_end_for_tab_only_that_tab(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    task_grants.add("t1", [], [str(a)], [], now=100.0)
    task_grants.add("t2", [], [str(a)], [], now=100.0)
    task_grants.end_for_tab("t1")
    assert not task_grants.covers("t1", [], [str(a)], [], now=101.0)
    assert task_grants.covers("t2", [], [str(a)], [], now=101.0)


def test_empty_request_is_covered_even_with_no_grants():
    assert task_grants.covers("t1", [], [], [], now=1.0)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/code_sandbox/test_task_grants.py -q`
Expected: FAIL (import error).

- [ ] **Step 3: Implement**

Append to `web/sandbox/paths.py`:

```python
def paths_covered(read, write, granted_read, granted_write) -> bool:
    gw = [Path(p) for p in granted_write]
    gr = gw + [Path(p) for p in granted_read]
    return (all(any(is_within(Path(p), g) for g in gw) for p in write)
            and all(any(is_within(Path(p), g) for g in gr) for p in read))
```

Create `web/sandbox/task_grants.py`:

```python
"""Per-tab approvals that last for one task.

Created only by the CSRF-guarded approve route in routes/sandbox_routes.py.
Ended when the user sends the next message in the tab (routes/chat.py) or after
TASK_TTL_SECONDS. In-memory: a restart forgets them, which only means asking again.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .paths import paths_covered

TASK_TTL_SECONDS = 600


@dataclass(frozen=True)
class _Grant:
    context_id: str
    read: tuple[str, ...]
    write: tuple[str, ...]
    hosts: tuple[str, ...]
    expires: float


_LOCK = threading.Lock()
_GRANTS: list[_Grant] = []


def _purge(now: float) -> None:
    _GRANTS[:] = [g for g in _GRANTS if g.expires >= now]


def add(context_id: str, read, write, hosts, now: float | None = None) -> None:
    now = time.time() if now is None else now
    grant = _Grant(context_id or "", tuple(str(p) for p in read), tuple(str(p) for p in write),
                   tuple(h.lower() for h in hosts), now + TASK_TTL_SECONDS)
    with _LOCK:
        _purge(now)
        _GRANTS.append(grant)


def covers(context_id: str, read, write, hosts, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    with _LOCK:
        _purge(now)
        live = [g for g in _GRANTS if g.context_id == (context_id or "")]
    granted_read = [p for g in live for p in g.read]
    granted_write = [p for g in live for p in g.write]
    granted_hosts = {h for g in live for h in g.hosts}
    return paths_covered(read, write, granted_read, granted_write) and {h.lower() for h in hosts} <= granted_hosts


def end_for_tab(context_id: str) -> None:
    with _LOCK:
        _GRANTS[:] = [g for g in _GRANTS if g.context_id != (context_id or "")]


def _reset() -> None:
    with _LOCK:
        _GRANTS.clear()
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python -m pytest tests/code_sandbox/test_task_grants.py tests/code_sandbox/test_paths.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add web/sandbox/paths.py web/sandbox/task_grants.py tests/code_sandbox/test_task_grants.py
git commit -m "feat: per-tab task grants and a path coverage check for run_shell approvals"
```

---

### Task 3: Saved permissions and the policy field

**Files:**

- Create: `web/sandbox/saved_permissions.py`
- Modify: `web/sandbox/policy.py` (the `Policy` dataclass, `_ALLOWED`)
- Test: `tests/code_sandbox/test_saved_permissions.py`, extend `tests/code_sandbox/test_policy.py`

**Interfaces:**

- Consumes: `paths.paths_covered`; `secure_store.get_json(name)`, `secure_store.set_json(name, data)` (imported lazily inside functions: the `sandbox` package must stay importable without the web modules).
- Produces (`saved_permissions`):
  - `list_entries() -> list[dict]` — each entry `{"id": str, "read_paths": [str], "write_paths": [str], "network": bool, "programs": [str], "created": float}`
  - `add(read, write, network: bool, programs) -> dict` (dedupes an identical entry; may raise on a store failure)
  - `covers(read, write, hosts, programs) -> bool` — `programs` is a set/tuple of names or `None`
  - `remove(entry_id: str) -> bool`, `remove_all() -> None`
  - `describe(entry: dict) -> str`
- Produces (`policy`): `Policy.saved_permissions: str = "allow"` (`allow|deny`), accepted by `parse_policy`, included in `as_dict()`. `FAIL_CLOSED_POLICY` also sets `saved_permissions="deny"`.

- [ ] **Step 1: Write the failing tests**

`tests/code_sandbox/test_saved_permissions.py` (the autouse `_isolated_secure_store` fixture in `tests/conftest.py` already gives a fake store):

```python
import pytest

import secure_store
from sandbox import saved_permissions as sp


def test_empty_by_default():
    assert sp.list_entries() == []
    assert not sp.covers([], ["/x"], [], None)


def test_add_and_cover_paths(tmp_path):
    proj = tmp_path / "proj"
    (proj / "sub").mkdir(parents=True)
    sp.add([], [str(proj)], False, [])
    assert sp.covers([], [str(proj / "sub")], [], None)
    assert sp.covers([str(proj)], [], [], None)
    assert not sp.covers([], [str(tmp_path)], [], None)


def test_paths_covered_by_union_of_entries(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    sp.add([], [str(a)], False, [])
    sp.add([str(b)], [], False, [])
    assert sp.covers([str(b)], [str(a)], [], None)


def test_network_needs_one_entry_with_all_programs(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    sp.add([], [str(proj)], True, ["git", "npm"])
    assert sp.covers([], [str(proj)], ["github.com:443"], {"git"})
    assert sp.covers([], [str(proj)], ["github.com:443"], {"git", "npm"})
    assert not sp.covers([], [str(proj)], ["github.com:443"], {"git", "curl"})
    assert not sp.covers([], [str(proj)], ["github.com:443"], None)


def test_network_not_granted_by_a_folder_only_entry(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    sp.add([], [str(proj)], False, [])
    assert not sp.covers([], [str(proj)], ["github.com:443"], {"git"})


def test_add_dedupes(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    sp.add([], [str(proj)], False, [])
    sp.add([], [str(proj)], False, [])
    assert len(sp.list_entries()) == 1


def test_remove_and_remove_all(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    first = sp.add([], [str(a)], False, [])
    sp.add([], [str(b)], False, [])
    assert sp.remove(first["id"]) is True
    assert sp.remove("nope") is False
    assert len(sp.list_entries()) == 1
    sp.remove_all()
    assert sp.list_entries() == []


@pytest.mark.parametrize("bad", ["x", [], {"version": 2, "entries": []}, {"version": 1, "entries": "x"},
                                 {"version": 1, "entries": [{"id": 1}]}])
def test_bad_stored_data_means_no_permissions(bad):
    secure_store.set_json("sandbox/saved-permissions", bad)
    assert sp.list_entries() == []
    assert not sp.covers([], ["/x"], [], None)


def test_store_exception_means_no_permissions(monkeypatch):
    def boom(name):
        raise RuntimeError("store down")
    monkeypatch.setattr(secure_store, "get_json", boom)
    assert sp.list_entries() == []


def test_describe_plain_words(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    e = sp.add([str(proj)], [str(proj)], True, ["npm", "git"])
    text = sp.describe(e)
    assert "Write to" in text and "Read from" in text
    assert "Use the network with: git, npm" in text
```

Add to `tests/code_sandbox/test_policy.py` (match that file's existing style for writing a policy file / calling `parse_policy`):

```python
def test_saved_permissions_field():
    from sandbox.policy import parse_policy, DEFAULT_POLICY, FAIL_CLOSED_POLICY
    assert DEFAULT_POLICY.saved_permissions == "allow"
    assert parse_policy('{"saved_permissions": "deny"}').saved_permissions == "deny"
    assert FAIL_CLOSED_POLICY.saved_permissions == "deny"
    assert DEFAULT_POLICY.as_dict()["saved_permissions"] == "allow"
    with pytest.raises(ValueError):
        parse_policy('{"saved_permissions": "maybe"}')
```

(Add `import pytest` there if the file lacks it.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/code_sandbox/test_saved_permissions.py tests/code_sandbox/test_policy.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

`web/sandbox/policy.py`: add the field after `require_sandbox`, add it to `FAIL_CLOSED_POLICY` and `_ALLOWED`:

```python
    require_sandbox: bool = False
    saved_permissions: str = "allow"   # allow | deny
```

```python
FAIL_CLOSED_POLICY = Policy(code_runner="enabled", network="deny", filesystem="strict", require_sandbox=True,
                            saved_permissions="deny")
_ALLOWED = {
    "code_runner": {"enabled", "disabled"},
    "network": {"ask", "deny"},
    "filesystem": {"ask", "strict"},
    "saved_permissions": {"allow", "deny"},
}
```

(`parse_policy` already loops over `_ALLOWED`, so no other change is needed.)

`web/sandbox/saved_permissions.py`:

```python
"""Permissions the user saved with "Always allow this".

Kept in the encrypted credential store, not in a file: the file tools can write
anywhere, so a plain file would let a tricked model grant itself access. An
unreadable, malformed or unknown-version blob means no saved permissions.
Created only by the CSRF-guarded approve route; removed only by the Settings routes.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid

from .paths import paths_covered

_NAME = "sandbox/saved-permissions"
_VERSION = 1
_LOCK = threading.Lock()
_log = logging.getLogger(__name__)


def _valid(entry) -> bool:
    return (isinstance(entry, dict) and isinstance(entry.get("id"), str)
            and isinstance(entry.get("network"), bool) and isinstance(entry.get("created"), (int, float))
            and all(isinstance(entry.get(k), list) and all(isinstance(v, str) for v in entry[k])
                    for k in ("read_paths", "write_paths", "programs")))


def list_entries() -> list[dict]:
    import secure_store
    try:
        data = secure_store.get_json(_NAME)
    except Exception as exc:
        _log.warning("saved permissions unreadable (%s); treating as none", type(exc).__name__)
        return []
    if not isinstance(data, dict) or data.get("version") != _VERSION or not isinstance(data.get("entries"), list):
        return []
    return [e for e in data["entries"] if _valid(e)]


def _save(entries: list[dict]) -> None:
    import secure_store
    secure_store.set_json(_NAME, {"version": _VERSION, "entries": entries})


def add(read, write, network: bool, programs) -> dict:
    entry = {
        "id": uuid.uuid4().hex,
        "read_paths": sorted({str(p) for p in read}),
        "write_paths": sorted({str(p) for p in write}),
        "network": bool(network),
        "programs": sorted({str(p) for p in programs}) if network else [],
        "created": time.time(),
    }
    with _LOCK:
        entries = list_entries()
        for existing in entries:
            if all(existing[k] == entry[k] for k in ("read_paths", "write_paths", "network", "programs")):
                return existing
        _save(entries + [entry])
    return entry


def covers(read, write, hosts, programs) -> bool:
    entries = list_entries()
    if not entries:
        return False
    granted_read = [p for e in entries for p in e["read_paths"]]
    granted_write = [p for e in entries for p in e["write_paths"]]
    if not paths_covered(read, write, granted_read, granted_write):
        return False
    if not hosts:
        return True
    if programs is None:
        return False
    wanted = set(programs)
    return any(e["network"] and wanted <= set(e["programs"]) for e in entries)


def remove(entry_id: str) -> bool:
    with _LOCK:
        entries = list_entries()
        kept = [e for e in entries if e["id"] != entry_id]
        if len(kept) == len(entries):
            return False
        _save(kept)
    return True


def remove_all() -> None:
    with _LOCK:
        _save([])


def describe(entry: dict) -> str:
    parts = []
    if entry["write_paths"]:
        parts.append("Write to " + ", ".join(entry["write_paths"]))
    if entry["read_paths"]:
        parts.append("Read from " + ", ".join(entry["read_paths"]))
    if entry["network"]:
        parts.append("Use the network with: " + ", ".join(sorted(entry["programs"])))
    return "; ".join(parts) or "No access"
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/code_sandbox -q -m "not real_sandbox"`
Expected: all pass (existing sandbox tests unchanged).

- [ ] **Step 5: Commit**

```bash
git add web/sandbox/saved_permissions.py web/sandbox/policy.py tests/code_sandbox/test_saved_permissions.py tests/code_sandbox/test_policy.py
git commit -m "feat: saved permissions in the encrypted store and a saved_permissions admin policy field"
```

---

### Task 4: Approval scope and the sandbox routes

**Files:**

- Modify: `web/sandbox/approvals.py`, `web/routes/sandbox_routes.py`
- Test: `tests/code_sandbox/test_approvals.py` (extend), `tests/code_sandbox/test_sandbox_routes_scope.py` (new)

**Interfaces:**

- Consumes: `task_grants.add`, `saved_permissions.add/list_entries/remove/remove_all/describe`, `policy.load_policy().saved_permissions`.
- Produces:
  - `ApprovalRequest` gains, after `status`: `tool: str = "run_python"`, `command: str = ""`, `programs: tuple[str, ...] | None = None`, `saveable: bool = False`, `scope: str = "once"`.
  - `approvals.create(context_id, read_paths, write_paths, network_hosts, now=None, *, tool="run_python", command="", programs=None, saveable=False)`.
  - `approvals.decide(request_id, context_id, approve, now=None, scope="once", allow_saved=True)`: for `tool == "run_shell"` on approve, `scope` in `{"once","task","always"}` (anything else becomes `"once"`); `"always"` becomes `"task"` when the request is not `saveable` or `allow_saved` is False. For `run_python` the scope is always `"once"`. The lookup key is unchanged (the command is not in the key).
  - Routes: the approve/deny body is `{"context_id": str, "scope": "once"|"task"|"always"}` (default `"once"`); the response is `{"ok": True, "request_id", "status", "scope", "saved": bool}`.
  - `GET /api/sandbox/saved-permissions` → `{"entries": [{"id", "description", "created"}]}`; `DELETE /api/sandbox/saved-permissions/{entry_id}` → `{"ok": True}` (404 when unknown); `DELETE /api/sandbox/saved-permissions` → `{"ok": True}`. All three carry `Depends(verify_csrf)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/code_sandbox/test_approvals.py`:

```python
def test_run_python_request_defaults_and_scope_is_once():
    req = approvals.create("t", R, W, H, now=100.0)
    assert (req.tool, req.command, req.programs, req.saveable, req.scope) == ("run_python", "", None, False, "once")
    got = approvals.decide(req.id, "t", True, now=101.0, scope="always")
    assert got.scope == "once"


def test_shell_scope_task_and_always():
    req = approvals.create("t", R, [], [], now=100.0, tool="run_shell", command="git pull",
                           programs=("git",), saveable=True)
    got = approvals.decide(req.id, "t", True, now=101.0, scope="always")
    assert got.scope == "always"
    assert approvals.lookup("t", R, [], [], now=102.0)[1].scope == "always"


def test_shell_always_falls_back_to_task_when_not_saveable_or_not_allowed():
    a = approvals.create("t", R, [], [], now=100.0, tool="run_shell", command="python x.py", saveable=False)
    assert approvals.decide(a.id, "t", True, now=101.0, scope="always").scope == "task"
    approvals._reset()
    b = approvals.create("t", R, [], [], now=100.0, tool="run_shell", command="git pull",
                         programs=("git",), saveable=True)
    assert approvals.decide(b.id, "t", True, now=101.0, scope="always", allow_saved=False).scope == "task"


def test_shell_unknown_scope_is_once_and_deny_keeps_once():
    a = approvals.create("t", R, [], [], now=100.0, tool="run_shell", command="ls")
    assert approvals.decide(a.id, "t", True, now=101.0, scope="forever").scope == "once"
    approvals._reset()
    b = approvals.create("t", R, [], [], now=100.0, tool="run_shell", command="ls")
    got = approvals.decide(b.id, "t", False, now=101.0, scope="task")
    assert (got.status, got.scope) == ("denied", "once")
```

`tests/code_sandbox/test_sandbox_routes_scope.py` (look at how existing route tests in the repo build a `TestClient` and satisfy `verify_csrf`; reuse that. `grep -rn "verify_csrf\|csrf" tests | head` shows the pattern. If the repo overrides the dependency with `app.dependency_overrides[verify_csrf] = lambda: None`, do that):

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import secure_store
from routes import sandbox_routes
from sandbox import approvals, saved_permissions, task_grants
from security import verify_csrf


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(sandbox_routes.router)
    app.dependency_overrides[verify_csrf] = lambda: None
    approvals._reset()
    task_grants._reset()
    yield TestClient(app)
    approvals._reset()
    task_grants._reset()


def _shell_request(tmp_path, saveable=True, hosts=()):
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    return proj, approvals.create("tab", [], [str(proj)], list(hosts), tool="run_shell", command="git pull",
                                  programs=("git",), saveable=saveable)


def test_approve_task_adds_task_grant(client, tmp_path):
    proj, req = _shell_request(tmp_path)
    r = client.post(f"/api/sandbox/requests/{req.id}/approve", json={"context_id": "tab", "scope": "task"})
    assert r.status_code == 200 and r.json()["scope"] == "task" and r.json()["saved"] is False
    assert task_grants.covers("tab", [], [str(proj)], [])


def test_approve_always_saves_and_adds_no_task_grant(client, tmp_path):
    proj, req = _shell_request(tmp_path)
    r = client.post(f"/api/sandbox/requests/{req.id}/approve", json={"context_id": "tab", "scope": "always"})
    assert r.json()["scope"] == "always" and r.json()["saved"] is True
    assert saved_permissions.covers([], [str(proj)], [], None)
    assert not task_grants.covers("tab", [], [str(proj)], [])


def test_always_on_unsaveable_request_becomes_task(client, tmp_path):
    proj, req = _shell_request(tmp_path, saveable=False)
    r = client.post(f"/api/sandbox/requests/{req.id}/approve", json={"context_id": "tab", "scope": "always"})
    assert r.json()["scope"] == "task" and r.json()["saved"] is False
    assert saved_permissions.list_entries() == []
    assert task_grants.covers("tab", [], [str(proj)], [])


def test_policy_deny_blocks_saving(client, tmp_path, monkeypatch):
    from sandbox.policy import Policy
    monkeypatch.setattr(sandbox_routes, "load_policy", lambda: Policy(saved_permissions="deny"))
    proj, req = _shell_request(tmp_path)
    r = client.post(f"/api/sandbox/requests/{req.id}/approve", json={"context_id": "tab", "scope": "always"})
    assert r.json()["scope"] == "task" and saved_permissions.list_entries() == []


def test_save_failure_falls_back_to_task(client, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("store down")
    monkeypatch.setattr(saved_permissions, "add", boom)
    proj, req = _shell_request(tmp_path)
    r = client.post(f"/api/sandbox/requests/{req.id}/approve", json={"context_id": "tab", "scope": "always"})
    assert r.status_code == 200 and r.json()["scope"] == "task" and r.json()["saved"] is False
    assert task_grants.covers("tab", [], [str(proj)], [])


def test_run_python_approval_unchanged(client):
    req = approvals.create("tab", [], ["/x"], [])
    r = client.post(f"/api/sandbox/requests/{req.id}/approve", json={"context_id": "tab", "scope": "always"})
    assert r.json()["scope"] == "once" and r.json()["saved"] is False
    assert saved_permissions.list_entries() == []


def test_deny_creates_nothing(client, tmp_path):
    proj, req = _shell_request(tmp_path)
    r = client.post(f"/api/sandbox/requests/{req.id}/deny", json={"context_id": "tab", "scope": "task"})
    assert r.json()["status"] == "denied"
    assert not task_grants.covers("tab", [], [str(proj)], [])


def test_list_and_remove_saved_permissions(client, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    first = saved_permissions.add([], [str(a)], False, [])
    saved_permissions.add([], [str(b)], False, [])
    body = client.get("/api/sandbox/saved-permissions").json()
    assert len(body["entries"]) == 2 and set(body["entries"][0]) == {"id", "description", "created"}
    assert client.delete(f"/api/sandbox/saved-permissions/{first['id']}").json() == {"ok": True}
    assert client.delete("/api/sandbox/saved-permissions/nope").status_code == 404
    assert len(client.get("/api/sandbox/saved-permissions").json()["entries"]) == 1
    assert client.delete("/api/sandbox/saved-permissions").json() == {"ok": True}
    assert client.get("/api/sandbox/saved-permissions").json()["entries"] == []


def test_new_routes_require_csrf():
    app = FastAPI()
    app.include_router(sandbox_routes.router)
    c = TestClient(app)
    assert c.get("/api/sandbox/saved-permissions").status_code in (401, 403)
    assert c.delete("/api/sandbox/saved-permissions").status_code in (401, 403)
    assert c.delete("/api/sandbox/saved-permissions/x").status_code in (401, 403)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/code_sandbox/test_approvals.py tests/code_sandbox/test_sandbox_routes_scope.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

`web/sandbox/approvals.py`: extend the dataclass, `create` and `decide`:

```python
    status: str = "pending"  # pending | approved | denied
    tool: str = "run_python"
    command: str = ""
    programs: tuple[str, ...] | None = None
    saveable: bool = False
    scope: str = "once"      # once | task | always (run_shell only; set by decide)
```

```python
def create(context_id: str, read_paths, write_paths, network_hosts, now: float | None = None, *,
           tool: str = "run_python", command: str = "", programs=None, saveable: bool = False) -> ApprovalRequest:
    now = time.time() if now is None else now
    req = ApprovalRequest(
        id=uuid.uuid4().hex, context_id=context_id or "",
        read_paths=tuple(str(p) for p in read_paths), write_paths=tuple(str(p) for p in write_paths),
        network_hosts=tuple(network_hosts), created_at=now,
        tool=tool, command=command, programs=None if programs is None else tuple(programs), saveable=saveable,
    )
    with _LOCK:
        _purge(now)
        _REQUESTS[req.id] = req
    return req
```

```python
def decide(request_id: str, context_id: str, approve: bool, now: float | None = None,
           scope: str = "once", allow_saved: bool = True) -> ApprovalRequest:
    # ... existing lookups and checks unchanged ...
        req.status = "approved" if approve else "denied"
        req.scope = "once"
        if approve and req.tool == "run_shell" and scope in ("task", "always"):
            req.scope = "task" if scope == "always" and not (req.saveable and allow_saved) else scope
        return req
```

`web/routes/sandbox_routes.py`:

```python
from typing import Literal

from sandbox import approvals, saved_permissions, task_grants


class SandboxDecisionRequest(BaseModel):
    context_id: str = ""
    scope: Literal["once", "task", "always"] = "once"


def _decide(request_id: str, body: SandboxDecisionRequest, approve: bool) -> dict:
    allow_saved = load_policy().saved_permissions != "deny"
    try:
        req = approvals.decide(request_id, body.context_id, approve, scope=body.scope, allow_saved=allow_saved)
    except approvals.ApprovalError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    saved = False
    if approve and req.tool == "run_shell":
        if req.scope == "always":
            try:
                saved_permissions.add(req.read_paths, req.write_paths, bool(req.network_hosts), req.programs or ())
                saved = True
            except Exception as exc:
                _log.warning("saving a permission failed (%s); using a task approval", type(exc).__name__)
                req.scope = "task"
        if req.scope == "task":
            task_grants.add(req.context_id, req.read_paths, req.write_paths, req.network_hosts)
    # Metadata only: never log the paths, hosts or command.
    _log.info("sandbox approval decision=%s scope=%s saved=%s", req.status, req.scope, saved)
    return {"ok": True, "request_id": req.id, "status": req.status, "scope": req.scope, "saved": saved}
```

Add the three saved-permission routes:

```python
@router.get("/api/sandbox/saved-permissions", dependencies=[Depends(verify_csrf)])
def list_saved_permissions():
    return {"entries": [{"id": e["id"], "description": saved_permissions.describe(e), "created": e["created"]}
                        for e in saved_permissions.list_entries()]}


@router.delete("/api/sandbox/saved-permissions/{entry_id}", dependencies=[Depends(verify_csrf)])
def remove_saved_permission(entry_id: str):
    if not saved_permissions.remove(entry_id):
        raise HTTPException(status_code=404, detail="That saved permission was not found.")
    return {"ok": True}


@router.delete("/api/sandbox/saved-permissions", dependencies=[Depends(verify_csrf)])
def remove_all_saved_permissions():
    saved_permissions.remove_all()
    return {"ok": True}
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/code_sandbox -q -m "not real_sandbox"`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add web/sandbox/approvals.py web/routes/sandbox_routes.py tests/code_sandbox/test_approvals.py tests/code_sandbox/test_sandbox_routes_scope.py
git commit -m "feat: approval scope (task or always allow) and saved-permission routes behind CSRF"
```

### Task 5: Sandbox `run_shell`

**Files:**

- Modify: `web/skills/shell_runner/tools.py` (imports at the top; `_tool_run_shell` at ~560-717; `TOOL_DEFS` at ~720)
- Create: `tests/shell_runner/conftest.py`, `tests/shell_runner/test_run_shell_sandbox.py`, `tests/shell_runner/test_run_shell_sandbox_real.py`

**Interfaces:**

- Consumes (all already exist): `skills.code_runner.tools` helpers `_check_requested_access(extra_read, extra_write, hosts, policy)` (returns an error dict, or `(read, write, hosts)` of normalized `Path` lists and host strings), `_sandbox_mode(cfg, policy)` -> `("enforced"|"off"|"unavailable", reason)`, `_unavailable_message(reason)`, `_runtime_paths(None, npm_root)`, `_runtime_path_refused(path)`, `_PERMISSION_PATTERNS`, and the messages `_DISABLED_MSG`, `_DENIED_MSG`, `_EXPIRED_MSG`, `_RUN_ERROR_MSG`, `_FS_REFUSED_MSG`. From `sandbox`: `SandboxRequest(argv, cwd, env, runtime_paths, read_paths, write_paths, network, timeout)`, `launch_sandboxed(req) -> SandboxResult(returncode, stdout, stderr, timed_out)` (blocking), `SandboxUnavailable`, `SandboxRunError`, `build_env(parent, run_dir, node_path)`, `telemetry_record(run_id, skill_id, level, network, extra_read, extra_write, approval)`. From Tasks 1-4: `programs_in`, `task_grants.covers`, `saved_permissions.covers`, `approvals.create(..., tool, command, programs, saveable)`, `approvals.lookup`.
- Produces:
  - `_tool_run_shell(command, shell="", cwd="", timeout=60, background=False, extra_read_paths=None, extra_write_paths=None, network_hosts=None, _context_id="")`. The app injects `_context_id` (the tab id) into handlers whose signature has it, exactly as for `run_python`.
  - `_run_unsandboxed(command, shell, cwd, timeout, background)`: the existing body from the "Windows auto-correct" comment onward, moved unchanged. Used only when `_sandbox_mode` returns `"off"`.
  - `_npm_global_root() -> str | None` (cached once per process).
  - Sandboxed result shape: `stdout`, `stderr`, `exit_code`, `shell_used`, `runtime_ms`, `sandbox` (`"enforced"`), `_sandbox_telemetry`, optional `output_files`, and `error` on a nonzero exit or a timeout. Approval-card result: `approval_required`, `request_id`, `read_paths`, `write_paths`, `network_hosts`, `message`, `_sandbox_approval` (card dict: `request_id, read_paths, write_paths, network_hosts, context_id, tool="run_shell", command` (first 2000 chars), `saveable`, `programs`), `_sandbox_telemetry`.

**Behavior (spec sections "Behavior", "Shell choice", "Background commands", "Unchanged behavior"):**

1. The delete check (`_find_delete_command`) stays the first thing in `_tool_run_shell`.
2. Then, in order: policy `code_runner == "disabled"` -> error; `cr._check_requested_access` -> error; `cr._sandbox_mode(load_config(), policy)`: `"unavailable"` -> error with `cr._unavailable_message`; `"off"` -> `_run_unsandboxed(...)`; `"enforced"` -> `_run_sandboxed(...)`.
3. Enforced: `background=True` is refused with an error (the command never runs, never unsandboxed).
4. Shell: Windows -> `[COMSPEC or %SystemRoot%\System32\cmd.exe, "/c"]`, `shell_used="cmd"`; a request for `bash` or `powershell` is an error saying that with the sandbox on, Windows commands run in cmd.exe. POSIX -> `_DETECTED_ARGV` / `_DETECTED_SHELL` (a request for `bash` uses `shutil.which("bash")`; `powershell`/`cmd` are errors). WSL is never used when enforced. The Windows `python3`->`python` replacement and `_route_frozen_python` still apply.
5. Working folder: no `cwd` -> `WORK_DIR` (scratch). A `cwd` inside `WORK_DIR` -> used, no grant. Any other `cwd`: refused when policy `filesystem == "strict"` (`cr._FS_REFUSED_MSG`); otherwise it must pass `normalize_grant_paths([cwd])` (deny list) and be a directory, and it is added to the required WRITE paths (so it needs approval). A non-scratch cwd is passed as `SandboxRequest.cwd` only, never in `SandboxRequest.write_paths` (the launcher always grants the cwd).
6. Gate (only when the required read/write/hosts are not all empty), tab key `tab = _context_id or "default"`: (a) `approvals.lookup` -> approved: decision `{"once": "approved", "task": "task_approved", "always": "saved_created"}[req.scope]`; denied -> `cr._DENIED_MSG` error; expired -> `cr._EXPIRED_MSG` error (each with `_sandbox_telemetry`); (b) `task_grants.covers(tab, ...)` -> `"task_approved"`; (c) unless policy `saved_permissions == "deny"`, `saved_permissions.covers(read, write, hosts, programs_in(command))` -> `"saved"`; (d) otherwise reuse the pending request or `approvals.create(tab, ..., tool="run_shell", command=command, programs=<sorted tuple or None>, saveable=<policy.saved_permissions != "deny" and (not hosts or programs is not None)>)` and return the card result with decision `"requested"`.
7. Runtime paths: `cr._runtime_paths(None, npm_root)`; if any is refused by `cr._runtime_path_refused`, return an error and run nothing. On POSIX only, also add the resolved parent folders of `git` and `npm` (skip any refused), then drop nested duplicates. Nothing extra on Windows.
8. Environment: for a scratch cwd, `env_dir = run cwd`. For a project cwd, `env_dir = WORK_DIR / f".run-{run_id}"` (created, appended to `SandboxRequest.write_paths`, removed with `shutil.rmtree(..., ignore_errors=True)` in a `finally`). `env=sandbox.build_env(os.environ, env_dir, npm_root)`.
9. Failures: `SandboxUnavailable` -> `cr._unavailable_message(str(exc))`; `SandboxRunError` -> `cr._RUN_ERROR_MSG`; `OSError` -> "could not start ... nothing was run" message. Never fall back to running unsandboxed.
10. Output: snapshot/diff `watched_output_dirs(run_cwd)` for `output_files` as today. A nonzero exit sets `error` = `Command exited with code N: <last 3 lines of stderr or stdout>`; a timeout sets `error` = `Command timed out after {timeout}s.`. When stderr matches `cr._PERMISSION_PATTERNS` or contains `Unable to read current working directory`, append the hint below to stderr (not to `error`).

- [ ] **Step 1: Write the legacy-test conftest and the failing sandbox tests**

`tests/shell_runner/conftest.py` (keeps the existing unsandboxed shell tests unsandboxed; the new test files re-patch to enforced):

```python
import pytest


@pytest.fixture(autouse=True)
def _legacy_shell_is_unsandboxed(monkeypatch):
    from skills.code_runner import tools as cr

    monkeypatch.setattr(cr, "_sandbox_mode", lambda cfg, policy: ("off", None))
```

`tests/shell_runner/test_run_shell_sandbox.py`:

```python
import types
from pathlib import Path

import pytest

import config
import sandbox
from sandbox import approvals, saved_permissions, task_grants
from sandbox.policy import Policy
from skills.code_runner import tools as cr
from skills.shell_runner import tools as sh


class FakeLauncher:
    def __init__(self):
        self.requests = []
        self.result = sandbox.SandboxResult(0, "out\n", "", False)
        self.raises = None

    def __call__(self, request):
        self.requests.append(request)
        if self.raises:
            raise self.raises
        return self.result


@pytest.fixture
def env(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(config, "WORK_DIR", work)
    monkeypatch.setattr(cr, "_sandbox_mode", lambda cfg, policy: ("enforced", None))
    monkeypatch.setattr(sh, "_npm_global_root", lambda: None)
    monkeypatch.setattr(sh, "load_policy", lambda: Policy())
    fake = FakeLauncher()
    monkeypatch.setattr(sandbox, "launch_sandboxed", fake)
    approvals._reset()
    task_grants._reset()
    yield types.SimpleNamespace(work=work.resolve(), fake=fake, tmp=tmp_path, mp=monkeypatch)
    approvals._reset()
    task_grants._reset()


def _project(env):
    p = env.tmp / "proj"
    p.mkdir(exist_ok=True)
    return p.resolve()


def _run(command="echo hi", **kw):
    kw.setdefault("_context_id", "tab")
    return sh._tool_run_shell(command, **kw)


def test_scratch_cwd_runs_with_no_card(env):
    r = _run()
    assert r["exit_code"] == 0 and r["stdout"] == "out\n" and "approval_required" not in r
    req = env.fake.requests[0]
    assert req.cwd == env.work and req.network is False and req.read_paths == []
    assert req.argv[-1] == "echo hi"
    assert r["sandbox"] == "enforced" and "_sandbox_telemetry" in r


def test_project_cwd_needs_a_card_then_task_grant_covers(env):
    proj = _project(env)
    r = _run(cwd=str(proj))
    assert r["approval_required"] is True and env.fake.requests == []
    card = r["_sandbox_approval"]
    assert card["tool"] == "run_shell" and card["write_paths"] == [str(proj)]
    assert card["command"] == "echo hi" and card["saveable"] is True and card["context_id"] == "tab"
    approvals.decide(card["request_id"], "tab", True, scope="task")
    task_grants.add("tab", card["read_paths"], card["write_paths"], card["network_hosts"])
    first = _run(cwd=str(proj))
    assert "approval_required" not in first and "task_approved" in str(first["_sandbox_telemetry"])
    second = _run("echo again", cwd=str(proj))
    assert "approval_required" not in second
    req = env.fake.requests[-1]
    assert req.cwd == proj and proj not in req.write_paths
    env_dir = Path(req.env["TEMP"])
    assert env_dir.parent == env.work and env_dir.name.startswith(".run-") and env_dir in req.write_paths
    assert not env_dir.exists()


def test_task_grant_does_not_cross_tabs(env):
    proj = _project(env)
    task_grants.add("tab", [], [str(proj)], [])
    assert "approval_required" in _run(cwd=str(proj), _context_id="other")


def test_saved_permission_covers_unless_policy_denies(env):
    proj = _project(env)
    saved_permissions.add([], [str(proj)], False, [])
    r = _run(cwd=str(proj))
    assert "approval_required" not in r and "saved" in str(r["_sandbox_telemetry"])
    env.mp.setattr(sh, "load_policy", lambda: Policy(saved_permissions="deny"))
    assert _run(cwd=str(proj))["approval_required"] is True


def test_saveable_follows_command_programs(env):
    git = _run("git pull", network_hosts=["github.com:443"])
    card = git["_sandbox_approval"]
    assert card["saveable"] is True and card["programs"] == ["git"] and card["network_hosts"] == ["github.com:443"]
    py = _run("python x.py", network_hosts=["github.com:443"])
    assert py["_sandbox_approval"]["saveable"] is False


def test_network_approval_runs_with_network(env):
    r = _run("git pull", network_hosts=["github.com:443"])
    approvals.decide(r["request_id"], "tab", True)
    assert "approval_required" not in _run("git pull", network_hosts=["github.com:443"])
    assert env.fake.requests[0].network is True


def test_denied_request_never_runs(env):
    r = _run("git pull", network_hosts=["github.com:443"])
    approvals.decide(r["request_id"], "tab", False)
    out = _run("git pull", network_hosts=["github.com:443"])
    assert out["error"] == cr._DENIED_MSG and env.fake.requests == []


def test_unsafe_or_missing_cwd_is_refused(env):
    assert "error" in _run(cwd=str(Path.home()))
    assert "error" in _run(cwd=str(env.tmp / "missing"))
    assert env.fake.requests == []


def test_strict_filesystem_policy_refuses_project_cwd(env):
    env.mp.setattr(sh, "load_policy", lambda: Policy(filesystem="strict"))
    assert _run(cwd=str(_project(env)))["error"] == cr._FS_REFUSED_MSG


def test_policy_disabled_and_network_deny(env):
    env.mp.setattr(sh, "load_policy", lambda: Policy(code_runner="disabled"))
    assert _run()["error"] == cr._DISABLED_MSG
    env.mp.setattr(sh, "load_policy", lambda: Policy(network="deny"))
    assert "error" in _run(network_hosts=["a.example:443"]) and env.fake.requests == []


def test_background_refused_when_enforced(env):
    env.mp.setattr(sh, "_spawn_background", lambda *a, **k: pytest.fail("must not spawn"))
    assert "error" in _run(background=True) and env.fake.requests == []


def test_delete_still_blocked_first(env):
    assert "Delete operations are blocked" in _run("rm -rf x")["error"] and env.fake.requests == []


def test_unavailable_never_runs(env):
    env.mp.setattr(cr, "_sandbox_mode", lambda cfg, policy: ("unavailable", "no sandbox here"))
    assert "error" in _run() and env.fake.requests == []


def test_launcher_failures_never_fall_back(env):
    env.mp.setattr(sh.subprocess, "run", lambda *a, **k: pytest.fail("unsandboxed run"))
    env.fake.raises = sandbox.SandboxRunError("boom")
    assert _run()["error"] == cr._RUN_ERROR_MSG
    env.fake.raises = sandbox.SandboxUnavailable("gone")
    assert "error" in _run()
    env.fake.raises = OSError("ledger")
    assert "nothing was run" in _run()["error"]


def test_result_shaping_and_hint(env):
    env.fake.result = sandbox.SandboxResult(1, "", "cat: x: Permission denied\n", False)
    r = _run("cat x")
    assert r["exit_code"] == 1 and r["error"].startswith("Command exited with code 1:")
    assert "[sandbox]" in r["stderr"]
    env.fake.result = sandbox.SandboxResult(-1, "", "", True)
    assert _run("sleep 9", timeout=1)["error"] == "Command timed out after 1s."


def test_git_cwd_error_gets_hint(env):
    env.fake.result = sandbox.SandboxResult(128, "", "fatal: Unable to read current working directory: x\n", False)
    assert "[sandbox]" in _run("git status")["stderr"]


def test_sandbox_shell_choice():
    assert sh._sandbox_shell("", is_windows=True)[1] == "cmd"
    assert sh._sandbox_shell("cmd", is_windows=True)[0][-1] == "/c"
    for bad in ("bash", "powershell"):
        assert isinstance(sh._sandbox_shell(bad, is_windows=True), str)
    for bad in ("powershell", "cmd"):
        assert isinstance(sh._sandbox_shell(bad, is_windows=False), str)
    argv, name = sh._sandbox_shell("", is_windows=False)
    assert name == sh._DETECTED_SHELL and argv == sh._DETECTED_ARGV
```

Adjust mechanics only, never intent: if `Path.home()` or a temp folder is classified by the deny list differently on this machine, place the project folder where the deny list allows it and keep every assertion; if `sandbox.SandboxResult` is keyword-only, use keywords.

`tests/shell_runner/test_run_shell_sandbox_real.py` (real OS sandbox; mirror how `tests/code_sandbox/test_launcher_windows.py` and `test_launcher_linux.py` mark and skip real runs):

```python
import sys

import pytest

import config
import sandbox
from sandbox.policy import Policy
from skills.code_runner import tools as cr
from skills.shell_runner import tools as sh

pytestmark = pytest.mark.real_sandbox


@pytest.fixture
def real(tmp_path, monkeypatch):
    if sandbox.sandbox_level() != "enforced":
        pytest.skip("OS sandbox is not available here")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(config, "WORK_DIR", work)
    monkeypatch.setattr(cr, "_sandbox_mode", lambda cfg, policy: ("enforced", None))
    monkeypatch.setattr(sh, "load_policy", lambda: Policy())
    return work


def test_write_in_working_folder_and_read_back(real):
    cmd = "echo hello> out.txt & type out.txt" if sys.platform == "win32" else "echo hello > out.txt && cat out.txt"
    r = sh._tool_run_shell(cmd, _context_id="tab")
    assert r["exit_code"] == 0 and "hello" in r["stdout"], r
    assert (real / "out.txt").exists()


def test_read_outside_granted_folders_is_denied(real, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-aigator", encoding="utf-8")
    cmd = f'type "{secret}"' if sys.platform == "win32" else f"cat '{secret}'"
    r = sh._tool_run_shell(cmd, _context_id="tab")
    assert "TOP-SECRET-aigator" not in r["stdout"] and r["exit_code"] != 0, r
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/shell_runner/test_run_shell_sandbox.py -q`
Expected: FAIL (`_sandbox_shell`, `_npm_global_root` and the sandbox path do not exist).

- [ ] **Step 3: Implement**

At the top of `web/skills/shell_runner/tools.py`, add whichever of these are not already imported (`functools`, `os`, `re`, `shutil`, `subprocess`, `time` are likely present; check):

```python
import functools
from pathlib import Path
from uuid import uuid4

import sandbox
from sandbox import approvals as sandbox_approvals
from sandbox import saved_permissions, task_grants
from sandbox.command_programs import programs_in
from sandbox.paths import PathNotGrantable, is_within, normalize_grant_paths
from sandbox.policy import load_policy
```

Keep the signature, docstring and delete check in the new `_tool_run_shell`; move everything from the `# Windows auto-correct:` comment to the end of the old function into `def _run_unsandboxed(command, shell, cwd, timeout, background) -> dict:` unchanged. Add above `_tool_run_shell`:

```python
_BACKGROUND_REFUSED_MSG = (
    "Background commands are not available while the command sandbox is on. Run the command in the "
    "foreground with a timeout, or ask the user to start it themselves."
)
_SHELL_APPROVAL_MSG = (
    "The user must approve this access first; an approval card is now shown in the chat. Tell the user "
    "briefly what access you asked for and why, then stop and wait. When the user says they approved, "
    "call run_shell again with exactly the same command, cwd, extra_read_paths, extra_write_paths and "
    "network_hosts. If they deny, do not retry."
)
_SHELL_HINT = (
    "[sandbox] This command can only use its working folder and has no network. If it really needs more, "
    "re-call run_shell with cwd, extra_read_paths, extra_write_paths or network_hosts; the user will be "
    "asked to approve. git push, gh and ssh need credentials the sandbox does not have: ask the user to "
    "run them, or use the GitHub tools."
)
_WINDOWS_SHELL_HINT = (
    "On Windows the sandboxed shell is cmd.exe: dir and git cannot run in it; use the file tools to list "
    "files and ask the user to run git."
)


def _shell_error(message: str, shell_used: str = "", **extra) -> dict:
    return {"error": message, "stdout": "", "stderr": "", "exit_code": -1,
            "shell_used": shell_used, "runtime_ms": 0, **extra}


@functools.lru_cache(maxsize=1)
def _npm_global_root() -> str | None:
    root = None
    try:
        root = subprocess.run("npm root -g", capture_output=True, text=True, timeout=5, shell=True,
                              **no_window_kwargs()).stdout.strip()
        if not root or not Path(root).is_dir():
            root = None
    except Exception:
        root = None
    if not root:
        fallback = Path.home() / "AppData" / "Roaming" / "npm" / "node_modules"
        if fallback.is_dir():
            root = str(fallback)
    return root


def _sandbox_shell(shell: str, is_windows: bool | None = None):
    """(argv_prefix, shell_used), or an error string. WSL is never used: it reaches the whole profile."""
    windows = os.name == "nt" if is_windows is None else is_windows
    if windows:
        if shell in ("bash", "powershell"):
            return ("With the sandbox on, commands run in cmd.exe on Windows (bash, WSL and PowerShell "
                    "cannot be sandboxed). Omit shell or use cmd, and write the command for cmd.exe.")
        comspec = os.environ.get("COMSPEC") or os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cmd.exe")
        return [comspec, "/c"], "cmd"
    if shell in ("powershell", "cmd"):
        return f"{shell} is not available with the sandbox on; commands run in {_DETECTED_SHELL}."
    if shell == "bash" and _DETECTED_SHELL != "bash":
        bash = shutil.which("bash")
        return ([bash, "-c"], "bash") if bash else "Bash is not available on this system."
    return list(_DETECTED_ARGV), _DETECTED_SHELL


def _drop_nested(paths) -> list:
    kept: list = []
    for path in sorted({Path(p) for p in paths}, key=lambda p: len(str(p))):
        if not any(is_within(path, k) for k in kept):
            kept.append(path)
    return kept


def _locate_cwd(cwd: str, policy, cr):
    """(run_cwd, project_to_grant_or_None, scratch), or an error string."""
    from config import WORK_DIR

    try:
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        scratch = WORK_DIR.resolve()
    except OSError:
        return "The AI Gator working folder is not available; nothing was run."
    if not cwd:
        return scratch, None, scratch
    try:
        resolved = Path(cwd).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return "The working folder is not valid. Do not retry with this value."
    if is_within(resolved, scratch):
        if not resolved.is_dir():
            return "The working folder must be an existing folder. Do not retry with this value."
        return resolved, None, scratch
    if policy.filesystem == "strict":
        return cr._FS_REFUSED_MSG
    try:
        (project,) = normalize_grant_paths([cwd])
    except (PathNotGrantable, ValueError) as exc:
        return f"{exc} Do not retry with this value."
    if not project.is_dir():
        return "The working folder must be an existing folder. Do not retry with this value."
    return project, project, scratch


def _shell_gate(cr, command, read_paths, write_paths, hosts, context_id, policy):
    """An approval decision string (None when no access was needed), or a result dict to return as is."""
    if not (read_paths or write_paths or hosts):
        return None
    tab = context_id or "default"
    read_s, write_s = [str(p) for p in read_paths], [str(p) for p in write_paths]

    def telemetry(decision: str) -> dict:
        return sandbox.telemetry_record("", "run_shell", "enforced", bool(hosts),
                                        len(read_paths), len(write_paths), decision)

    status, req = sandbox_approvals.lookup(tab, read_s, write_s, hosts)
    if status == "approved":
        return {"once": "approved", "task": "task_approved", "always": "saved_created"}[req.scope]
    if status == "denied":
        return _shell_error(cr._DENIED_MSG, _sandbox_telemetry=telemetry("denied"))
    if status == "expired":
        return _shell_error(cr._EXPIRED_MSG, _sandbox_telemetry=telemetry("expired"))
    if task_grants.covers(tab, read_s, write_s, hosts):
        return "task_approved"
    programs = programs_in(command)
    if policy.saved_permissions != "deny" and saved_permissions.covers(read_s, write_s, hosts, programs):
        return "saved"
    if req is None:
        req = sandbox_approvals.create(
            tab, read_s, write_s, hosts, tool="run_shell", command=command,
            programs=None if programs is None else tuple(sorted(programs)),
            saveable=policy.saved_permissions != "deny" and (not hosts or programs is not None),
        )
    card = {
        "request_id": req.id, "read_paths": list(req.read_paths), "write_paths": list(req.write_paths),
        "network_hosts": list(req.network_hosts), "context_id": req.context_id, "tool": "run_shell",
        "command": req.command[:2000], "saveable": bool(req.saveable),
        "programs": list(req.programs or ()),
    }
    return {
        "approval_required": True, "request_id": req.id, "read_paths": card["read_paths"],
        "write_paths": card["write_paths"], "network_hosts": card["network_hosts"],
        "message": _SHELL_APPROVAL_MSG, "_sandbox_approval": card,
        "_sandbox_telemetry": telemetry("requested"),
    }


def _with_shell_hint(cr, stderr: str) -> str:
    if stderr and (cr._PERMISSION_PATTERNS.search(stderr) or "Unable to read current working directory" in stderr):
        hint = _SHELL_HINT + (" " + _WINDOWS_SHELL_HINT if os.name == "nt" else "")
        return stderr.rstrip("\n") + "\n" + hint + "\n"
    return stderr


def _run_sandboxed(cr, command, shell, cwd, timeout, background, requested, policy, context_id) -> dict:
    if background:
        return _shell_error(_BACKGROUND_REFUSED_MSG)
    picked = _sandbox_shell(shell)
    if isinstance(picked, str):
        return _shell_error(picked, shell)
    argv_prefix, shell_used = picked
    if os.name == "nt":
        command = re.sub(r"\bpython3\b", "python", command)
    command = _route_frozen_python(command, shell_used)

    read_paths, write_paths, hosts = requested
    located = _locate_cwd(cwd, policy, cr)
    if isinstance(located, str):
        return _shell_error(located, shell_used)
    run_cwd, project, scratch = located
    if project is not None and project not in write_paths:
        write_paths = [*write_paths, project]

    gate = _shell_gate(cr, command, read_paths, write_paths, hosts, context_id, policy)
    if isinstance(gate, dict):
        return gate
    approval = gate

    npm_root = _npm_global_root()
    runtime_paths = cr._runtime_paths(None, npm_root)
    if any(cr._runtime_path_refused(p) for p in runtime_paths):
        return _shell_error("The command sandbox refused to start because a runtime folder is not allowed. "
                            "Nothing was run. Tell the user; do not retry automatically.", shell_used)
    if os.name != "nt":
        for name in ("git", "npm"):
            found = shutil.which(name)
            if found and not cr._runtime_path_refused(Path(found).resolve().parent):
                runtime_paths.append(Path(found).resolve().parent)
        runtime_paths = _drop_nested(runtime_paths)

    run_id = uuid4().hex[:12]
    in_scratch = is_within(run_cwd, scratch)
    env_dir = run_cwd if in_scratch else scratch / f".run-{run_id}"
    sandbox_write = [p for p in write_paths if os.path.normcase(str(p)) != os.path.normcase(str(run_cwd))]
    try:
        if not in_scratch:
            env_dir.mkdir(parents=True, exist_ok=True)
            sandbox_write.append(env_dir)
    except OSError:
        return _shell_error("The command sandbox could not prepare its temporary folder; nothing was run.",
                            shell_used)

    telemetry = sandbox.telemetry_record(run_id, "run_shell", "enforced", bool(hosts),
                                         len(read_paths), len(write_paths), approval)
    tags = {"sandbox": "enforced", "_sandbox_telemetry": telemetry}
    watch_dirs = watched_output_dirs(str(run_cwd))
    before = snapshot_outputs(watch_dirs)
    request = sandbox.SandboxRequest(
        argv=argv_prefix + [command], cwd=run_cwd, env=sandbox.build_env(os.environ, env_dir, npm_root),
        runtime_paths=runtime_paths, read_paths=list(read_paths), write_paths=sandbox_write,
        network=bool(hosts), timeout=timeout,
    )
    start = time.monotonic()
    try:
        res = sandbox.launch_sandboxed(request)
    except sandbox.SandboxUnavailable as exc:
        return _shell_error(cr._unavailable_message(str(exc)), shell_used, **tags)
    except sandbox.SandboxRunError:
        return _shell_error(cr._RUN_ERROR_MSG, shell_used, **tags)
    except OSError as exc:
        return _shell_error(f"The command sandbox could not start ({type(exc).__name__}) and nothing was run. "
                            "Tell the user; do not retry automatically.", shell_used, **tags)
    finally:
        if not in_scratch:
            shutil.rmtree(env_dir, ignore_errors=True)

    result = {
        "stdout": res.stdout or "", "stderr": _with_shell_hint(cr, res.stderr or ""),
        "exit_code": res.returncode, "shell_used": shell_used,
        "runtime_ms": int((time.monotonic() - start) * 1000), **tags,
    }
    new_files = diff_outputs(before, watch_dirs)
    if new_files:
        result["output_files"] = new_files
    if res.timed_out:
        result["error"] = f"Command timed out after {timeout}s."
    elif res.returncode != 0:
        tail = (res.stderr or res.stdout or "").strip().splitlines()
        reason = " ".join(tail[-3:]) if tail else ""
        result["error"] = (f"Command exited with code {res.returncode}: {reason}" if reason
                           else f"Command exited with code {res.returncode}")
    return result
```

Match `snapshot_outputs`/`diff_outputs`/`watched_output_dirs` argument order to how the existing (moved) body calls them; the code above must behave identically to it. New `_tool_run_shell`:

```python
def _tool_run_shell(
    command: str,
    shell: str = "",
    cwd: str = "",
    timeout: int = 60,
    background: bool = False,
    extra_read_paths=None,
    extra_write_paths=None,
    network_hosts=None,
    _context_id: str = "",
) -> dict:
    """Run a shell command inside the OS sandbox (same launcher and policy as run_python).

    The command may use its working folder only; a project cwd, extra paths or network need the user's
    approval card. _context_id is the server-injected tab id (never supplied by the model).
    """
    _del_token, _del_pos = _find_delete_command(command)
    if _del_token is not None:
        return {
            "error": (
                f"Delete operations are blocked: matched command '{_del_token}' "
                f"at position {_del_pos}. Ask the user to run this command manually."
            ),
            "stdout": "", "stderr": "", "exit_code": -1, "shell_used": _DETECTED_SHELL, "runtime_ms": 0,
        }
    from config import load_config
    from skills.code_runner import tools as cr

    policy = load_policy()
    if policy.code_runner == "disabled":
        return _shell_error(cr._DISABLED_MSG, _DETECTED_SHELL)
    requested = cr._check_requested_access(extra_read_paths, extra_write_paths, network_hosts, policy)
    if isinstance(requested, dict):
        return _shell_error(requested["error"], _DETECTED_SHELL)
    mode, reason = cr._sandbox_mode(load_config(), policy)
    if mode == "unavailable":
        return _shell_error(cr._unavailable_message(reason), _DETECTED_SHELL)
    if mode == "off":
        return _run_unsandboxed(command, shell, cwd, timeout, background)
    return _run_sandboxed(cr, command, shell, cwd, timeout, background, requested, policy, _context_id)
```

`TOOL_DEFS` for `run_shell`: change the description's first sentence to "Run a shell command inside the OS sandbox (bash/sh on macOS and Linux; cmd.exe on Windows, where dir and git do not work in the sandbox)." and add after the delete-blocked sentence: "By default the command can use only its working folder (omit cwd for scratch work) and has no network. To work in a project folder (cwd), read or write other folders, or reach the network, pass cwd, extra_read_paths, extra_write_paths or network_hosts: the call returns approval_required and the user approves in the chat; call again with exactly the same values only after the user says they approved. background=true is not available with the sandbox on." Add three array properties after `background` with the same shape and wording as `run_python`'s `extra_read_paths`, `extra_write_paths`, `network_hosts`, replacing "outside OUTPUT_DIR" with "outside the working folder" and "the code" with "the command".

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/shell_runner tests/code_sandbox -q -m "not real_sandbox"`
Expected: all pass, including the existing shell tests (the conftest keeps them unsandboxed). Then run `grep -rln "_tool_run_shell\|run_shell" tests`; if another test directory now fails only because the sandbox is enforced on this machine, add the same autouse `_sandbox_mode` "off" patch to that directory's `conftest.py`.

- [ ] **Step 5: Real run (this machine)**

Run: `python -m pytest tests/shell_runner/test_run_shell_sandbox_real.py -q -s -m real_sandbox`
Expected: 2 passed on Windows (the first run can take about 30 s while runtime-folder ACEs are set), or skipped if the OS sandbox is unavailable. If a real run fails, report the output; do not weaken the assertions.

- [ ] **Step 6: Commit**

```bash
git add web/skills/shell_runner/tools.py tests/shell_runner
git commit -m "feat: run_shell runs in the OS sandbox with task and saved approvals; WSL and background are refused when enforced"
```

---

### Task 6: End task approvals on a new user message

**Files:**

- Modify: `web/routes/chat.py` (`ChatRequest` at ~108; start of `chat()` at ~904)
- Modify: `web/static/app.js` (`_sendSandboxFollowUp` ~8907; submit handler ~11272; `_postBody` ~12003)
- Modify: `tests/sandbox_ui.test.js`
- Create: `tests/code_sandbox/test_chat_task_grants.py`

**Interfaces:**

- Consumes: `task_grants.end_for_tab(tab: str) -> None` (Task 2).
- Produces: `ChatRequest.sandbox_followup: bool = False`; `_end_task_grants_for_new_message(req) -> None` in `routes/chat.py`; JS module variable `_sandboxFollowUpSending` (true only while `_sendSandboxFollowUp` calls `form.requestSubmit()`); the chat POST body carries `sandbox_followup: true` only for that automatic message.

Why a flag and not "any message": after Approve or Deny the UI sends an automatic chat message so the model re-calls the tool. That message is part of the same task, so it must not end the grant. A real user message must end it. The flag is set by browser code, but the browser cannot approve anything the server did not already record behind CSRF; at worst a caller keeps a grant the user already gave, for at most 10 minutes.

- [ ] **Step 1: Write the failing tests**

`tests/code_sandbox/test_chat_task_grants.py` (mirror the import style of an existing test that imports from `routes.chat`, for example `grep -rl "from routes.chat import" tests | head -3`):

```python
import inspect

from routes import chat as chat_routes
from routes.chat import ChatRequest
from sandbox import task_grants


def test_flag_defaults_to_false():
    assert ChatRequest(message="hi").sandbox_followup is False
    assert ChatRequest(message="hi", sandbox_followup=True).sandbox_followup is True


def test_new_user_message_ends_the_tabs_grants_only():
    task_grants._reset()
    task_grants.add("tab-a", [], ["/proj"], [])
    task_grants.add("tab-b", [], ["/proj"], [])
    chat_routes._end_task_grants_for_new_message(ChatRequest(message="next", context_id="tab-a"))
    assert not task_grants.covers("tab-a", [], ["/proj"], [])
    assert task_grants.covers("tab-b", [], ["/proj"], [])
    task_grants._reset()


def test_automatic_followup_keeps_the_grants():
    task_grants._reset()
    task_grants.add("tab-a", [], ["/proj"], [])
    chat_routes._end_task_grants_for_new_message(
        ChatRequest(message="I approved ...", context_id="tab-a", sandbox_followup=True))
    assert task_grants.covers("tab-a", [], ["/proj"], [])
    task_grants._reset()


def test_empty_context_id_means_default_tab():
    task_grants._reset()
    task_grants.add("default", [], ["/proj"], [])
    chat_routes._end_task_grants_for_new_message(ChatRequest(message="x", context_id=""))
    assert not task_grants.covers("default", [], ["/proj"], [])
    task_grants._reset()


def test_chat_ends_grants_before_any_early_return():
    src = inspect.getsource(chat_routes.chat)
    call = src.index("_end_task_grants_for_new_message(req)")
    assert call < src.index("return "), "must run before the first return in chat()"
```

In `tests/sandbox_ui.test.js`, make three edits:

1. In `makeEnv`, add `_sandboxFollowUpSending: false,` to `ctx`, and make `requestSubmit` record the flag: replace `form.sentImages = [];` with `form.sentImages = [];\n  form.flags = [];` and, as the first line inside `form.requestSubmit`, add `form.flags.push(ctx._sandboxFollowUpSending);`.
2. After the "Approve: CSRF POST ..." block's `assert.match(env.form.sent[0], /approved sandbox access request req1/);` add:

```js
assert.deepStrictEqual(env.form.flags, [true], 'automatic follow-up is marked');
assert.strictEqual(env.ctx._sandboxFollowUpSending, false, 'flag is reset after the submit');
```

3. After the line `assert(source.includes('  _initSandboxSettings();'));` add:

```js
assert(/let _sandboxFollowUpSending = false;/.test(source));
assert(
  /e\.preventDefault\(\);\s*const _isSandboxFollowUp = _sandboxFollowUpSending;/.test(source),
  'submit handler captures the flag synchronously, right after preventDefault',
);
assert(/\.\.\.\(_isSandboxFollowUp \? \{ sandbox_followup: true \} : \{\}\)/.test(source));
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/code_sandbox/test_chat_task_grants.py -q` and `node tests/sandbox_ui.test.js`
Expected: both FAIL.

- [ ] **Step 3: Implement**

`web/routes/chat.py`: add the field to `ChatRequest` (after `scoped_skill`):

```python
    sandbox_followup: bool = False            # automatic message after a sandbox Approve/Deny click
```

Add above `@router.post("/api/chat")` (import `from sandbox import task_grants` at the top of the file with the other imports):

```python
def _end_task_grants_for_new_message(req: "ChatRequest") -> None:
    """A real user message ends the tab's "allow for this task" approvals; the automatic follow-up does not."""
    if not req.sandbox_followup:
        task_grants.end_for_tab(req.context_id or "default")
```

As the first statement of `async def chat(req: ChatRequest):` (before the function's local imports and every early return), add `_end_task_grants_for_new_message(req)`.

`web/static/app.js`:

- Above `_sendSandboxFollowUp` add `let _sandboxFollowUpSending = false;`.
- In `_sendSandboxFollowUp`, replace the `try { form.requestSubmit(); } finally { _aigatorImages = images; }` block with:

```js
_sandboxFollowUpSending = true;
try {
  form.requestSubmit();
} finally {
  _sandboxFollowUpSending = false;
  _aigatorImages = images;
}
```

- In the submit handler (`form.addEventListener('submit', async (e) => {`), directly after `e.preventDefault();` add `const _isSandboxFollowUp = _sandboxFollowUpSending;` (`requestSubmit` dispatches `submit` synchronously, so the flag is still true here; `doSend` is a closure inside this handler and sees the constant).
- In `_postBody`'s object literal, after the `...(_wSuffix ? { system_prompt_suffix: _wSuffix } : {}),` line add `...(_isSandboxFollowUp ? { sandbox_followup: true } : {}),`.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/code_sandbox/test_chat_task_grants.py -q` and `node tests/sandbox_ui.test.js`
Expected: PASS ("sandbox_ui: all assertions passed").

- [ ] **Step 5: Commit**

```bash
git add web/routes/chat.py web/static/app.js tests/sandbox_ui.test.js tests/code_sandbox/test_chat_task_grants.py
git commit -m "feat: a new user message ends the tab's task approvals; the automatic approval follow-up does not"
```

---

### Task 7: Approval card for commands, and the Saved permissions page

**Files:**

- Modify: `web/static/app.js` (`_sandboxFollowUpText` ~8897; `_showSandboxApproval` ~8947-9078; `_initOnReady` ~15982; `openDrawer` ~5144; `activateTab` ~5491; new `_initSavedPermissions` after `_initSandboxSettings` ~16092)
- Modify: `web/static/index.html` (after the `sandbox-row` block, ~705)
- Modify: `tests/sandbox_ui.test.js`

**Interfaces:**

- Consumes: the card dict from Task 5 (`tool, command, saveable, programs, read_paths, write_paths, network_hosts, context_id, request_id`); `POST /api/sandbox/requests/{id}/approve` body `{context_id, scope?}` returning `{ok, request_id, status, scope, saved}`; `GET /api/sandbox/saved-permissions` -> `{"entries": [{"id", "description", "created"}]}`; `DELETE /api/sandbox/saved-permissions/{id}`; `DELETE /api/sandbox/saved-permissions` (all CSRF header `X-CSRF-Token`).
- Produces: `_sandboxFollowUpText(decision, requestId, tool = 'run_python')`; `_initSavedPermissions()`; `window._refreshSavedPermissions()`.

Rules: model-supplied strings (command, paths, hosts, program names, entry descriptions) go in with `textContent` only, never `innerHTML`. The `run_python` card is unchanged (same buttons, same POST body).

- [ ] **Step 1: Write the failing tests**

Edit `tests/sandbox_ui.test.js`:

1. Extend the first assertions (after the `followUp('deny', 'abc123')` lines):

```js
assert.match(
  followUp('approve', 'abc123', 'run_shell'),
  /Run the same run_shell call again with exactly the same command, cwd/,
);
assert.doesNotMatch(followUp('approve', 'abc123'), /run_shell/);
```

2. Add `'_initSavedPermissions'` to the no-`innerHTML` list `['_showSandboxApproval', '_initSandboxSettings', '_sendSandboxFollowUp']`, and after `assert(source.includes('  _initSandboxSettings();'));` add `assert(source.includes('  _initSavedPermissions();'));`.

3. Replace the existing assertion `assert(/_sendSandboxFollowUp\(tabId, _sandboxFollowUpText\(decision, requestId\)\)\.catch\(/.test(source));` with `assert(/_sendSandboxFollowUp\(tabId, _sandboxFollowUpText\(decision, requestId, tool\)\)\.catch\(/.test(source));`.

4. Add new behaviour tests inside the async IIFE, just before `console.log('sandbox_ui: all assertions passed');`:

```js
// ── run_shell card ──
const shellCard = {
  request_id: 'sh1',
  tool: 'run_shell',
  command: '<b>git pull</b> && echo "<img src=x onerror=alert(1)>"',
  read_paths: [],
  write_paths: ['C:/proj'],
  network_hosts: ['github.com:443'],
  context_id: 'tab-1',
  saveable: true,
  programs: ['git'],
};
const envS = makeEnv('tab-1');
envS.ctx._showSandboxApproval(shellCard, 'tab-1');
const allS = walk(envS.messages);
assert(allS.some((e) => e.textContent === 'AI Gator wants to run a command'));
assert(
  allS.some((e) => e.textContent === shellCard.command),
  'command rendered as text',
);
assert(!allS.some((e) => e.tag === 'img' || e.tag === 'b'), 'no elements created from the command');
const shellButtons = allS.filter((e) => e.tag === 'button');
assert.deepStrictEqual(
  shellButtons.map((b) => b.textContent),
  ['Allow for this task', 'Always allow this', 'Deny'],
);
await shellButtons[0].listeners.click({ stopPropagation() {} });
await flush();
assert.strictEqual(envS.fetches[0].url, '/api/sandbox/requests/sh1/approve');
assert.deepStrictEqual(JSON.parse(envS.fetches[0].opts.body), {
  context_id: 'tab-1',
  scope: 'task',
});
assert.match(envS.form.sent[0], /Run the same run_shell call again/);

// Always allow sends scope "always"; an unsaveable request has no such button.
const envA = makeEnv('tab-1');
envA.ctx._showSandboxApproval({ ...shellCard, request_id: 'sh2' }, 'tab-1');
await walk(envA.messages)
  .filter((e) => e.tag === 'button')[1]
  .listeners.click({ stopPropagation() {} });
await flush();
assert.deepStrictEqual(JSON.parse(envA.fetches[0].opts.body), {
  context_id: 'tab-1',
  scope: 'always',
});
const envU = makeEnv('tab-1');
envU.ctx._showSandboxApproval({ ...shellCard, request_id: 'sh3', saveable: false }, 'tab-1');
assert.deepStrictEqual(
  walk(envU.messages)
    .filter((e) => e.tag === 'button')
    .map((b) => b.textContent),
  ['Allow for this task', 'Deny'],
);

// Deny on a command card sends no scope.
const envD = makeEnv('tab-1');
envD.ctx._showSandboxApproval({ ...shellCard, request_id: 'sh4' }, 'tab-1');
const denyBtn = walk(envD.messages)
  .filter((e) => e.tag === 'button')
  .pop();
await denyBtn.listeners.click({ stopPropagation() {} });
await flush();
assert.deepStrictEqual(JSON.parse(envD.fetches[0].opts.body), { context_id: 'tab-1' });

// ── Settings: Saved permissions ──
function makeSettingsEnv(entries) {
  const list = makeEl('div');
  const clear = makeEl('button');
  clear.hidden = true;
  const row = makeEl('div');
  const byId = {
    'saved-permissions-row': row,
    'saved-permissions-list': list,
    'saved-permissions-clear': clear,
  };
  const calls = [];
  const state = { entries };
  const ctx = {
    document: { createElement: makeEl, getElementById: (id) => byId[id] || null },
    window: { __CSRF_TOKEN__: 'aigator-fake-api-key' },
    _showConnectivityToast: () => {},
    encodeURIComponent,
    Array,
    fetch: async (url, opts = {}) => {
      const method = opts.method || 'GET';
      calls.push({ url, method, headers: opts.headers });
      if (method === 'DELETE' && url.endsWith('/saved-permissions')) state.entries = [];
      else if (method === 'DELETE')
        state.entries = state.entries.filter((e) => !url.endsWith(encodeURIComponent(e.id)));
      return { ok: true, status: 200, json: async () => ({ ok: true, entries: state.entries }) };
    },
  };
  vm.createContext(ctx);
  vm.runInContext(extract('_initSavedPermissions'), ctx);
  return { ctx, list, clear, calls };
}
const evilDesc = '<img src=x onerror=alert(1)> git: network in C:/proj';
const sEnv = makeSettingsEnv([
  { id: 'e1', description: evilDesc, created: 1 },
  { id: 'e/2', description: 'second', created: 2 },
]);
sEnv.ctx._initSavedPermissions();
await flush();
assert.strictEqual(sEnv.calls[0].method, 'GET');
assert.strictEqual(sEnv.calls[0].headers['X-CSRF-Token'], 'aigator-fake-api-key');
let rows = walk(sEnv.list);
assert(
  rows.some((e) => e.textContent === evilDesc),
  'description rendered as text',
);
assert(!rows.some((e) => e.tag === 'img'));
assert.strictEqual(sEnv.clear.hidden, false);
assert.strictEqual(typeof sEnv.ctx.window._refreshSavedPermissions, 'function');

const removeBtns = walk(sEnv.list).filter((e) => e.tag === 'button');
await removeBtns[1].listeners.click({ stopPropagation() {} });
await flush();
const del = sEnv.calls.find((c) => c.method === 'DELETE');
assert.strictEqual(del.url, '/api/sandbox/saved-permissions/e%2F2');
assert.strictEqual(del.headers['X-CSRF-Token'], 'aigator-fake-api-key');
assert.strictEqual(
  walk(sEnv.list).filter((e) => e.tag === 'button').length,
  1,
  'list refreshed after Remove',
);

await sEnv.clear.listeners.click({ stopPropagation() {} });
await flush();
assert(sEnv.calls.some((c) => c.method === 'DELETE' && c.url === '/api/sandbox/saved-permissions'));
assert.strictEqual(sEnv.clear.hidden, true);
assert(
  walk(sEnv.list).some((e) => /Nothing saved/.test(e.textContent)),
  'empty state shown',
);
```

- [ ] **Step 2: Run to verify failure**

Run: `node tests/sandbox_ui.test.js`
Expected: FAIL (`_initSavedPermissions` not found, card assertions fail).

- [ ] **Step 3: Implement**

`web/static/app.js`, replace `_sandboxFollowUpText`:

```js
function _sandboxFollowUpText(decision, requestId, tool = 'run_python') {
  if (decision !== 'approve') {
    return `I denied sandbox access request ${requestId}. Do not retry it; continue without that access or tell me what you need.`;
  }
  const again =
    tool === 'run_shell'
      ? 'Run the same run_shell call again with exactly the same command, cwd, extra_read_paths, extra_write_paths and network_hosts.'
      : 'Run the same run_python call again with exactly the same extra_read_paths, extra_write_paths and network_hosts.';
  return `I approved sandbox access request ${requestId}. ${again}`;
}
```

Edit `_showSandboxApproval` (keep everything not listed):

- After the `box` element is created add `const isShell = data.tool === 'run_shell';` and `const tool = isShell ? 'run_shell' : 'run_python';`.
- Title: `title.textContent = isShell ? 'AI Gator wants to run a command' : 'Code wants extra access for one run';`.
- In `body`, before the `[ ['Read', ...], ... ].forEach(...)` block, add the command row:

```js
if (isShell && typeof data.command === 'string' && data.command) {
  const row = document.createElement('div');
  row.className = 'gcc-field-row gcc-field-row--block';
  const key = document.createElement('span');
  key.className = 'gcc-field-key';
  key.textContent = 'Command';
  const cmd = document.createElement('pre');
  cmd.className = 'gcc-field-val';
  cmd.textContent = data.command;
  row.append(key, cmd);
  body.appendChild(row);
}
```

- After the existing network-note block add:

```js
if (
  isShell &&
  data.saveable === true &&
  Array.isArray(data.network_hosts) &&
  data.network_hosts.length
) {
  const risk = document.createElement('div');
  risk.className = 'gcc-refine';
  risk.textContent =
    'Always allow lets these programs use the network in the folders shown. Programs such as git and npm run scripts stored in the project, so those scripts get network access too. You can remove it in Settings.';
  body.appendChild(risk);
}
```

- Buttons: replace the `approve`/`deny`/`actions.append` lines with:

```js
const approve = document.createElement('button');
approve.className = 'gcc-approve-btn';
approve.textContent = isShell ? 'Allow for this task' : 'Approve';
let always = null;
if (isShell && data.saveable === true) {
  always = document.createElement('button');
  always.className = 'btn-secondary';
  always.textContent = 'Always allow this';
}
const deny = document.createElement('button');
deny.className = 'btn-secondary';
deny.textContent = 'Deny';
actions.append(approve, ...(always ? [always] : []), deny);
```

- Footer note: `footNote.textContent = isShell ? 'Allowed until you send your next message, or for 10 minutes. Requests expire after 10 minutes.' : 'Applies to one run only. Requests expire after 10 minutes.';`.
- In `decide`: change the signature to `const decide = async (decision, scope = 'task') => {`; disable `always` too (`if (always) always.disabled = true;` next to the other two, and re-enable it in the `catch`); build the body as `JSON.stringify({ context_id: contextId, ...(isShell && decision === 'approve' ? { scope } : {}) })`; replace the success line `footNote.textContent = decision === 'approve' ? 'Approved for one run.' : 'Denied.';` with:

```js
let outcome = 'Denied.';
if (decision === 'approve') {
  if (!isShell) outcome = 'Approved for one run.';
  else if (scope === 'always') {
    const out = await res.json().catch(() => ({}));
    outcome =
      out && out.saved
        ? 'Always allowed. You can remove this in Settings.'
        : 'Allowed for this task (it could not be saved).';
  } else outcome = 'Allowed for this task.';
}
footNote.textContent = outcome;
```

and the follow-up call to `_sendSandboxFollowUp(tabId, _sandboxFollowUpText(decision, requestId, tool)).catch((e) =>`.

- Handlers: `approve` click -> `decide('approve', 'task')`; add `if (always) always.addEventListener('click', (e) => { e.stopPropagation(); decide('approve', 'always'); });`; deny unchanged.

Add after `_initSandboxSettings` (and call `_initSavedPermissions();` right after `_initSandboxSettings();` in `_initOnReady`; add `if (typeof window._refreshSavedPermissions === 'function') window._refreshSavedPermissions();` as the first line of `openDrawer()` and after `localStorage.setItem(STORAGE_KEY, tabName);` in `activateTab`):

```js
function _initSavedPermissions() {
  const row = document.getElementById('saved-permissions-row');
  const list = document.getElementById('saved-permissions-list');
  const clear = document.getElementById('saved-permissions-clear');
  if (!row || !list || !clear) return;
  const call = async (method, url) => {
    const send = () =>
      fetch(url, { method, headers: { 'X-CSRF-Token': window.__CSRF_TOKEN__ || '' } });
    let res = await send();
    if (res.status === 403) {
      const fresh = await fetch('/api/csrf')
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null);
      if (fresh?.csrf_token) window.__CSRF_TOKEN__ = fresh.csrf_token;
      res = await send();
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  };
  const render = (entries) => {
    list.replaceChildren();
    clear.hidden = entries.length === 0;
    if (!entries.length) {
      const empty = document.createElement('div');
      empty.className = 'srow-sub';
      empty.textContent =
        'Nothing saved yet. Choose "Always allow this" on a command approval to save one here.';
      list.appendChild(empty);
      return;
    }
    entries.forEach((entry) => {
      const item = document.createElement('div');
      item.className = 'srow-sub';
      const text = document.createElement('span');
      text.textContent = String(entry.description);
      const remove = document.createElement('button');
      remove.className = 'btn-secondary';
      remove.textContent = 'Remove';
      remove.addEventListener('click', (e) => {
        e.stopPropagation();
        act('DELETE', `/api/sandbox/saved-permissions/${encodeURIComponent(entry.id)}`);
      });
      item.append(text, remove);
      list.appendChild(item);
    });
  };
  const refresh = () =>
    call('GET', '/api/sandbox/saved-permissions')
      .then((d) => render(Array.isArray(d.entries) ? d.entries : []))
      .catch(() => {});
  const act = (method, url) =>
    call(method, url)
      .catch(() => _showConnectivityToast('Could not change saved permissions.', 'warn'))
      .then(refresh);
  clear.addEventListener('click', (e) => {
    e.stopPropagation();
    act('DELETE', '/api/sandbox/saved-permissions');
  });
  window._refreshSavedPermissions = refresh;
  refresh();
}
```

`web/static/index.html`, directly after the closing `</div>` of the `sandbox-row` block (~705):

```html
<!-- ═══ Saved command permissions ═══ -->
<div class="srow integration-row-sep" id="saved-permissions-row">
  <div class="srow-info">
    <div class="srow-label">Saved permissions</div>
    <div class="srow-sub">
      Commands you chose "Always allow this" for. Remove one and AI Gator asks again.
    </div>
    <div id="saved-permissions-list"></div>
  </div>
  <div class="srow-actions">
    <button id="saved-permissions-clear" class="btn-secondary" hidden>Remove all</button>
  </div>
</div>
```

- [ ] **Step 4: Run to verify pass**

Run: `node tests/sandbox_ui.test.js`
Expected: PASS ("sandbox_ui: all assertions passed"). Then run any other JS tests that load `app.js` (`ls tests/*.test.js`, run each with `node`).

- [ ] **Step 5: Browser check (the UI rule: use the feature, not only the tests)**

Start the dev server as `docs/BUILD_INSTRUCTIONS.md` describes, open the app with the browser tools, open Settings and confirm the "Saved permissions" row shows its empty state and no console errors. Then, with a dev-only temporary saved entry made through `python -c "from sandbox import saved_permissions as s; s.add([], [r'C:\\Users\\<you>\\pocs'], False, [])"` (use a folder that exists), reload, confirm the entry is listed in words, click Remove, and confirm it disappears. Do not commit anything from this step.

- [ ] **Step 6: Commit**

```bash
git add web/static/app.js web/static/index.html tests/sandbox_ui.test.js
git commit -m "feat: approval card for commands with Allow for this task and Always allow, and a Saved permissions section in Settings"
```

---

### Task 8: Documentation

**Files:**

- Modify: `docs/BUILD_INSTRUCTIONS.md` (policy example ~261 and its description ~264; smoke test ~270-280; Known gaps ~282)
- Modify: `docs/security/threatmodel-remediation.md` (the `H_Code_runner_skill_used_for_lateral_movem_06` row, line 16)

**Interfaces:**

- Consumes: the behavior built in Tasks 1-7. No code changes in this task.

- [ ] **Step 1: Update `docs/BUILD_INSTRUCTIONS.md`**

1. Line 244: after the first sentence add: ` `run_shell` runs in the same sandbox with the same approval card (see "run_shell in the sandbox" below).`
2. Replace the policy JSON example (line 261) with:

```json
{
  "code_runner": "enabled",
  "network": "ask",
  "filesystem": "ask",
  "require_sandbox": false,
  "saved_permissions": "allow"
}
```

3. At the end of the line-264 paragraph (before "A present but invalid file fails closed") insert: `` `saved_permissions: deny` hides "Always allow this" on command approvals and ignores permissions already saved (task approvals still work); the default is `allow`. `` And change the fail-closed list to `(`network: deny`, `filesystem: strict`, `require_sandbox: true`, `saved_permissions: deny`)`.
4. Insert a new section before "### Code sandbox smoke test (release gate)":

```markdown
### run_shell in the sandbox

`run_shell` uses the same launcher, deny list, policy file and approval card as `run_python`. A command runs with no card when it needs only its working folder (the scratch folder `~/.gator/work`, or a folder already approved), the system tools and no network. A new working folder, extra paths or network need a card with two choices: **Allow for this task** (until the next message you send in that tab, or 10 minutes) and **Always allow this** (saved in the encrypted store; managed under Settings, "Saved permissions"). "Always allow" is not offered for commands that run an interpreter or shell (`python`, `node`, `bash`, `powershell`, `cmd`, `wsl`, `npx`, ...) or that use command substitution, `eval`, `source` or `-c`-style code arguments.

Behavior to know about:

- Windows: with the sandbox enforced the shell is **cmd.exe only**. WSL is never used (it reaches the whole user profile through `/mnt/c`), Git Bash cannot start in an AppContainer, and PowerShell cannot set its working folder. A call that asks for `bash` or `powershell` returns an error that says so. This changes the default on machines where WSL was the default shell. `dir` and `git` do not work inside a project folder (Windows needs list access on the parent folders); the hint tells the model to use the file tools to list files and to ask you to run git.
- macOS and Linux: `bash` or `sh` under Seatbelt or bubblewrap, system tool folders read-only.
- `background=true` is refused while the sandbox is enforced.
- Credentialed commands (`git push`, `gh`, `ssh`) do not work: the sandbox has no access to `~/.gitconfig`, `~/.ssh` or tokens.
- Network approval is all or nothing per run. A saved network permission for `git` or `npm` lets scripts stored in the project use the network (the card says so).
```

5. Smoke test: add after step 5 two steps:
   `6. Ask: "Use run_shell to run \`echo hi > note.txt\` in ~/Documents/<some folder>": a card names the command and the folder; "Allow for this task" runs it; a second command in the same folder in the same task shows no card; after you send a new message the card appears again.`
`7. Choose "Always allow this" on a folder card, open Settings, confirm the entry appears under "Saved permissions" in plain words, Remove it, and confirm the card returns.`Update the Windows line (~270) to add:` Also on Windows: \`python -m pytest tests/shell_runner/test_run_shell_sandbox_real.py -q -s -m real_sandbox\`.`
6. Known gaps: replace `` `run_shell` is not sandboxed and bypasses this control; `` with `` `run_shell` is sandboxed (see above) but cannot run credentialed commands, and on Windows runs only cmd.exe without `dir`/`git`; ``.

- [ ] **Step 2: Update the tracker row**

In `docs/security/threatmodel-remediation.md` line 16 (the `_06` row):

- In the status cell keep **Implemented (Windows real-run tests passed; macOS/Linux real-system smoke test pending)** and change the plan link cell to also link `[run_shell design](../superpowers/specs/2026-10-06-run-shell-sandbox-design.md) / [plan](../superpowers/plans/2026-10-06-run-shell-sandbox.md)`.
- Replace the sentence fragment ``(the CSRF token is served only to the AI Gator shell, see `M_Localhost_CSRF_token_exposure_via_browse_05`, so code that reaches the localhost API, such as `run_shell` or a network-approved run on Linux, cannot obtain it)`` with ``(the CSRF token is served only to the AI Gator shell, see `M_Localhost_CSRF_token_exposure_via_browse_05`, so code that reaches the localhost API, such as a network-approved run on Linux, cannot obtain it)``.
- Replace ``Known gaps: `run_shell` (shell_runner) is unsandboxed and can run `python` (bypass, not named in the report, unchanged);`` with `` `run_shell` now runs in the same sandbox: same launcher, deny list and policy, an approval card with "Allow for this task" (ends at the next user message or after 10 minutes) and "Always allow this" (never for interpreters or substitution; stored in the encrypted store, managed in Settings, policy field `saved_permissions`). On Windows it is cmd.exe only (no WSL, no `dir`/`git`), background commands are refused, credentialed commands (`git push`, `gh`, `ssh`) do not work. Known gaps: ``.
- Append to the end of the row, before the final ` |`: ` run_shell sandbox verification: unit tests and fake-launcher tests everywhere; real runs on Windows (cmd under the AppContainer) and Linux (WSL); the macOS Seatbelt profile still has no real-Mac run (release gate, same smoke test plus the two run_shell steps).`

- [ ] **Step 3: Check for stale statements**

Run: `grep -rn "run_shell" docs/BUILD_INSTRUCTIONS.md docs/security/threatmodel-remediation.md README.md 2>/dev/null | grep -i "unsandboxed\|not sandboxed\|bypass"`
Expected: no output. Older dated files under `docs/superpowers/specs` and `docs/superpowers/plans` are historical and stay as they are.

- [ ] **Step 4: Run the full suites once**

Run: `python -m pytest tests -q -x -m "not real_sandbox"` and every `node tests/*.test.js`.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add docs/BUILD_INSTRUCTIONS.md docs/security/threatmodel-remediation.md
git commit -m "docs: run_shell sandbox in build instructions, policy field, smoke test and tracker"
```

---

## Self-Review

**Spec coverage:** same launcher/deny list/policy/card (Task 5, reuses `cr._check_requested_access`); two buttons (Task 7); task semantics with tab key, 10-minute expiry and end on next message including the automatic follow-up exception (Tasks 2, 4, 6); saved permissions via the card only, encrypted store, never for interpreters/substitution, honest network note, Settings list with Remove/Remove all, CSRF-guarded routes, policy field, telemetry values (Tasks 1, 3, 4, 7); shell choice per OS and Windows cmd-only limits, environment allow-list, credentials limit (Task 5, docs in Task 8); background refused (Task 5); delete blocklist, frozen-python routing, output files, timeout, fail-closed (Task 5 keeps the legacy body in `_run_unsandboxed` and the gate order); docs and tracker (Task 8). The REDLINE docx is updated by the controller after the final review, not by a task.

**Placeholder scan:** no TBD/TODO; every code step has the code. Task 7 Step 5 uses a placeholder folder name only as a prompt for the person running the browser check.

**Type consistency:** `task_grants.add/covers/end_for_tab/_reset` (Task 2) are used the same way in Tasks 4, 5 and 6; `saved_permissions` store name and entry fields (Task 3) match the routes (Task 4) and the Settings list (Task 7: `id`, `description`, `created`); approve response `{ok, request_id, status, scope, saved}` (Task 4) is what the card reads in Task 7; the card keys `tool, command, saveable, programs, read_paths, write_paths, network_hosts, context_id, request_id` come from Task 4/5 and are the ones Task 7 reads; `sandbox_followup` is spelled the same in Python and JS.
