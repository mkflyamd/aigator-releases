# Marketplace Skill Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Meet the five acceptance criteria of finding `H_Malicious_marketplace_or_MCP_skill_execu_03` (sandboxing, declared permissions, install approval, outbound logging, kill switch) for marketplace skills.

**Architecture:** Reuse the existing OS sandbox launcher (`web/sandbox`), the install consent modal, `installed-skills.json` and the CSRF guard. A new `permissions.py` parses declared permissions and builds the install-card summary. A new `sandbox_launch.py` wraps `launch_sandboxed` for hooks and `tools.py`. Marketplace `tools.py` is never imported into the app: a runner script runs it in the sandbox per call and the app registers stubs. A per-skill `disabled` flag is the kill switch.

**Tech Stack:** Python 3 / FastAPI / pytest (run `python -m pytest <path> -q` from the repo root `C:\Users\maykulka\pocs\aigator-releases`), PyYAML, vanilla JS (`web/static/marketplace-pane.js`) tested with node `vm` and regex-extracted functions (no jsdom). Shell is Git Bash on Windows 11.

Spec: `docs/superpowers/specs/2026-10-07-marketplace-skill-controls-design.md` (read it first).

## Global Constraints

- Scope is limited to the five acceptance criteria. No policy engine, no admin switch, no persistent launcher. "Please dont add more friction then needed."
- "Marketplace skill" means a skill installed through the marketplace (catalog, URL, ZIP or folder). Native skills and `Mine` / `~/.agents/skills` skills are unchanged.
- Declared `permissions` block: `filesystem: [paths]` (read-only grants), `network: [hosts]` (shown and logged, not enforced; the launcher is all-or-nothing). Missing block means no filesystem and no network. Malformed block (not a list of strings, an entry over 200 characters, more than 20 entries) is treated as "no permissions" and the card says the declaration was invalid.
- Nothing is written to the skills folder before the user approves (`consent=True` plus the `digest` the card showed). A digest mismatch is HTTP 409 `content_changed`.
- Hooks: sandboxed, working folder is a fresh run folder under `config.OUTPUTS_DIR` (never the skill folder), read access to the skill folder and the approved declared paths (deny list in `web/sandbox/paths.py` applies), no write beyond the run folder, network only for an approved non-empty `network`. 30 s timeout. Non-zero exit blocks the send. Sandbox failure fails closed (blocked). Never fall back to running unsandboxed.
- `tools.py` is never imported into the app process. Each call is one sandboxed run: `build_env` (no API keys), skill folder and interpreter as runtime paths, approved `filesystem` as read paths, run folder as the only writable path, `network` only if approved, timeouts from config keys `code_runner_timeout_community` (30) and `code_runner_timeout_verified` (60). Test: a no-op call takes under 2 s with the real sandbox (a no-op measured about 0.6 s).
- Kill switch: `disabled` flag in `installed-skills.json`; `POST /api/marketplace/disable/{skill_id}` and `POST /api/marketplace/enable/{skill_id}`. Disabled means prompt not loaded, tools unloaded and refused, `bin/` off PATH, bundle MCP servers removed (`remove_plugin_mcp_servers`, which wipes their saved credentials), slash commands deregistered, hooks skipped. Survives restart. Files stay on disk.
- Install, install-local, disable and enable routes get `dependencies=[Depends(verify_csrf)]` (`from security import verify_csrf`). No other route gets CSRF in this change.
- Outbound logging: logger `aigator.skill_audit`; `skill-launch skill=<id> kind=<hook|tool> network=<true|false> declared_hosts=<list>` for every sandboxed launch; `skill-outbound skill=<id> dest=<host>:<port>` for each connection seen by the runner's audit hook (events `socket.connect`, `socket.getaddrinfo`). Logging only.
- All LLM calls go through `llm.gateway` (this change makes none).
- Git commits: do NOT add `Co-Authored-By` lines. Stage files by name; never stage the untracked `pip/` folder.
- Naming: the project is **AI Gator**, never "POC".
- Fake credentials: `aigator-fake-api-key` is the only fake credential in tests, fixtures, examples and docs. Do not invent other fake keys, tokens, passwords or secrets.
- Human-in-the-loop: email, Teams and Slack messages never auto-send; this change must not touch that (hooks only gate sends).
- Known baseline failures that are not ours: 2 `test_browser_competitive_fixes`, 2 `test_chat_link_rendering`, 7 Slack source-text tests, Teams tests (`test_teams_file_attachments`, `test_teams_history_window`, `test_teams_location_lookup`), `test_teams_pane_config::test_edited_message_applied_before_dtype_branch`, 2 errors in `tests/marketplace/test_installer.py` (no `httpserver` fixture).

---

## File Structure

New files (all under `web/marketplace/` unless noted):

| File | Responsibility |
|---|---|
| `permissions.py` | `Permissions` dataclass, `parse_permissions`, `declared_permissions(files)`, `files_digest`, `summarize_package`, `readable_paths` |
| `skill_audit.py` | `log_launch`, `log_outbound`, `extract_outbound` (logger `aigator.skill_audit`) |
| `sandbox_launch.py` | `SkillRun`, `new_run_dir`, `run_in_sandbox` (one place that builds the `SandboxRequest` for hooks and tools) |
| `state.py` | Per-skill flags in `installed-skills.json`: `disabled`, `permissions`, `approved_at` |
| `kill_switch.py` | `disable(skill_id)` and `enable(skill_id)` |
| `tool_runner_source.py` | `RUNNER_SOURCE`: the script that runs inside the sandbox |
| `tool_sandbox.py` | `describe_skill_tools`, `call_skill_tool`, `make_stub` |
| `tests/marketplace/test_permissions.py`, `test_install_digest.py`, `test_skill_audit.py`, `test_sandbox_launch.py`, `test_state.py`, `test_tool_sandbox.py`, `test_kill_switch.py`, `test_consent_routes.py` | Tests |
| `tests/hooks/test_hooks_sandboxed.py` | Sandboxed hook tests |
| `tests/marketplace_controls.test.js` | Node-based JS tests (run as `node tests/marketplace_controls.test.js`) |

Modified: `tests/conftest.py` (fixtures `fake_sandbox`, `make_skill_dir`), `web/marketplace/installer.py`, `web/marketplace/loader.py`, `web/hooks/executor.py`, `web/routes/marketplace.py`, `web/shared.py` (prompt loader skip), `web/commands.py` (plugin command loader skip), `web/static/marketplace-pane.js`, existing tests `tests/marketplace/test_loader.py`, `tests/marketplace/test_routes.py`, `tests/hooks/test_hooks_executor.py`, tracker `docs/security/threatmodel-remediation.md`.

Conventions in this repo that the tasks rely on:

- Tests run as `python -m pytest <path> -q`. `tests/conftest.py` redirects HOME to a temp dir and has autouse fixtures `_isolated_secure_store`, `_restore_shared_state`, `_hermetic_sandbox_policy`.
- `web/` is on `sys.path` (imports are `from marketplace import ...`, `import sandbox`, `import config`).
- `installer.load_installed()` / `save_installed(entries)` read and write `installed-skills.json`. `installer._INSTALL_INDEX_LOCK` is a **non-reentrant** `threading.Lock` taken by `_upsert_installed_entry`; `load_installed` and `save_installed` do not take it. The `_upsert_*` functions replace the whole record, so anything stored on a record (`permissions`, `approved_at`, `disabled`) must be written AFTER the install.
- A bundle entry is one with `entry.get("skill_ids") is not None and entry.get("source")`; its folder is `config.PLUGINS_DIR/"cache"/source/id/version`. A plain skill's folder is `config.INSTALLED_SKILLS_DIR/id`.

---

### Task 1: Declared permissions and the package summary

**Files:**
- Create: `web/marketplace/permissions.py`
- Test: `tests/marketplace/test_permissions.py`

**Interfaces:**
- Consumes: `sandbox.paths.normalize_grant_paths(raw) -> list[Path]` (raises `PathNotGrantable`), `sandbox.paths.is_secrets_path(path) -> bool`, `marketplace.installer._discover_plugin_mcp_manifest_from_files(files) -> dict[name, cfg]` (imported lazily).
- Produces (later tasks use these exact names):
  - `Permissions(filesystem: tuple[str,...]=(), network: tuple[str,...]=(), invalid: bool=False)` frozen dataclass; property `wants_network -> bool`; `to_dict() -> dict`; `Permissions.from_dict(d) -> Permissions`.
  - `parse_permissions(raw) -> Permissions`
  - `declared_permissions(files: dict[str, bytes]) -> Permissions`
  - `files_digest(files: dict[str, bytes]) -> str` (hex sha256)
  - `summarize_package(files) -> {"permissions": dict, "has_tools": bool, "hooks": list[str], "bin": list[str], "mcp_servers": list[str], "lines": list[str], "digest": str}`
  - `readable_paths(perms: Permissions) -> list[Path]`

- [ ] **Step 1: Write the failing tests**

Create `tests/marketplace/test_permissions.py`:

```python
import json
from pathlib import Path

from marketplace import permissions as P


def _skill_md(front: str) -> bytes:
    return f"---\nname: demo\ndescription: d\n{front}---\nBody\n".encode()


def test_missing_block_means_nothing_declared():
    perms = P.declared_permissions({"SKILL.md": _skill_md("")})
    assert perms == P.Permissions()
    assert not perms.wants_network


def test_valid_block_in_frontmatter():
    front = "permissions:\n  filesystem: ['~/Documents/reports']\n  network: ['api.example.com']\n"
    perms = P.declared_permissions({"SKILL.md": _skill_md(front)})
    assert perms.filesystem == ("~/Documents/reports",)
    assert perms.network == ("api.example.com",)
    assert perms.wants_network


def test_plugin_json_wins_over_skill_md():
    files = {
        ".claude-plugin/plugin.json": json.dumps({"permissions": {"network": ["a.example.com"]}}).encode(),
        "skills/x/SKILL.md": _skill_md("permissions:\n  network: ['b.example.com']\n"),
    }
    assert P.declared_permissions(files).network == ("a.example.com",)


def test_union_across_skill_md_files_is_deduped():
    files = {
        "skills/a/SKILL.md": _skill_md("permissions:\n  network: ['a.example.com']\n"),
        "skills/b/SKILL.md": _skill_md("permissions:\n  network: ['a.example.com', 'b.example.com']\n"),
    }
    assert P.declared_permissions(files).network == ("a.example.com", "b.example.com")


def test_malformed_blocks_are_invalid_and_grant_nothing():
    for bad in (
        "permissions: yes\n",
        "permissions:\n  network: 'api.example.com'\n",
        "permissions:\n  network: [1]\n",
        "permissions:\n  network: ['']\n",
        "permissions:\n  network: ['" + "a" * 201 + "']\n",
        "permissions:\n  network: [" + ",".join(f"'h{i}'" for i in range(21)) + "]\n",
    ):
        perms = P.declared_permissions({"SKILL.md": _skill_md(bad)})
        assert perms.invalid, bad
        assert not perms.wants_network
        assert P.readable_paths(perms) == []


def test_one_invalid_skill_makes_the_package_invalid():
    files = {
        "skills/a/SKILL.md": _skill_md("permissions:\n  network: ['a.example.com']\n"),
        "skills/b/SKILL.md": _skill_md("permissions: yes\n"),
    }
    assert P.declared_permissions(files).invalid


def test_to_dict_from_dict_round_trip_and_bad_stored_data():
    perms = P.Permissions(filesystem=("~/x",), network=("h.example.com",))
    assert P.Permissions.from_dict(perms.to_dict()) == perms
    assert P.Permissions.from_dict(None) == P.Permissions()
    assert P.Permissions.from_dict({"network": "nope"}).invalid


def test_digest_is_stable_and_content_sensitive():
    a = {"SKILL.md": b"one", "tools.py": b"two"}
    assert P.files_digest(a) == P.files_digest(dict(reversed(list(a.items()))))
    assert P.files_digest(a) != P.files_digest({"SKILL.md": b"one", "tools.py": b"changed"})
    assert P.files_digest(a) != P.files_digest({"SKILL.md": b"one"})


def test_summary_for_a_plain_skill_with_nothing():
    summary = P.summarize_package({"SKILL.md": _skill_md("")})
    assert summary["has_tools"] is False
    assert summary["hooks"] == [] and summary["bin"] == [] and summary["mcp_servers"] == []
    text = "\n".join(summary["lines"])
    assert "none declared" in text
    assert summary["digest"] == P.files_digest({"SKILL.md": _skill_md("")})


def test_summary_names_tools_hooks_bin_and_mcp(monkeypatch):
    from marketplace import installer

    monkeypatch.setattr(installer, "_discover_plugin_mcp_manifest_from_files",
                        lambda files: {"srv": {"command": "npx", "args": ["x"]}})
    files = {
        "SKILL.md": _skill_md("permissions:\n  network: ['api.example.com']\n"),
        "tools.py": b"TOOL_DEFS = []\n",
        "hooks.json": json.dumps({"hooks": [{"event": "pre_email_send", "command": "python check.py"}]}).encode(),
        "bin/run.sh": b"#!/bin/sh\n",
    }
    summary = P.summarize_package(files)
    assert summary["has_tools"] is True
    assert summary["hooks"] == ["python check.py"]
    assert summary["bin"] == ["bin/run.sh"]
    assert summary["mcp_servers"] == ["srv"]
    text = "\n".join(summary["lines"])
    assert "api.example.com" in text
    assert "not limited to" in text
    assert "python check.py" in text
    assert "restricted sandbox" in text
    assert "bin/run.sh" in text
    assert "srv" in text and "not sandboxed" in text


def test_summary_cuts_long_hook_commands_and_notes_invalid_declaration():
    files = {
        "SKILL.md": _skill_md("permissions: yes\n"),
        "hooks.json": json.dumps({"hooks": [{"event": "e", "command": "x" * 500}]}).encode(),
    }
    summary = P.summarize_package(files)
    assert len(summary["hooks"][0]) == 300
    assert "invalid" in "\n".join(summary["lines"]).lower()


def test_summary_survives_broken_hooks_json():
    summary = P.summarize_package({"SKILL.md": _skill_md(""), "hooks.json": b"{not json"})
    assert summary["hooks"] == []


def test_readable_paths_keeps_real_folders_and_drops_the_rest(tmp_path):
    keep = tmp_path / "reports"
    keep.mkdir()
    perms = P.Permissions(filesystem=(str(keep), str(tmp_path / "does-not-exist")))
    assert P.readable_paths(perms) == [keep.resolve()]


def test_readable_paths_drops_secrets_folder():
    import secure_store

    secrets = Path(secure_store.__file__).resolve().parent
    perms = P.Permissions(filesystem=(str(Path.home() / ".gator"),))
    assert all(not str(p).startswith(str(Path.home() / ".gator" / "secrets")) for p in P.readable_paths(perms))
    assert secrets  # keeps the import used
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/marketplace/test_permissions.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'marketplace.permissions'` or an ImportError on `P`).

- [ ] **Step 3: Write the implementation**

Create `web/marketplace/permissions.py`:

```python
"""Declared permissions of a marketplace skill and the summary the install card shows."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

MAX_ENTRIES = 20
MAX_ENTRY_LEN = 200
MAX_HOOK_LEN = 300
_FRONTMATTER = re.compile(r"^---\r?\n(.*?)\r?\n---", re.DOTALL)
_PLUGIN_JSON = ".claude-plugin/plugin.json"


def _clean_list(value) -> tuple[str, ...] | None:
    """() for a missing value, a deduped tuple for a valid list, None when malformed."""
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > MAX_ENTRIES:
        return None
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item) > MAX_ENTRY_LEN:
            return None
        if item not in out:
            out.append(item)
    return tuple(out)


@dataclass(frozen=True)
class Permissions:
    filesystem: tuple[str, ...] = ()
    network: tuple[str, ...] = ()
    invalid: bool = False

    @property
    def wants_network(self) -> bool:
        return bool(self.network) and not self.invalid

    def to_dict(self) -> dict:
        return {"filesystem": list(self.filesystem), "network": list(self.network), "invalid": self.invalid}

    @classmethod
    def from_dict(cls, data) -> "Permissions":
        if not isinstance(data, dict):
            return cls()
        fs, net = _clean_list(data.get("filesystem")), _clean_list(data.get("network"))
        if fs is None or net is None or data.get("invalid"):
            return cls(invalid=True)
        return cls(filesystem=fs, network=net)


def parse_permissions(raw) -> Permissions:
    if raw is None:
        return Permissions()
    if not isinstance(raw, dict):
        return Permissions(invalid=True)
    fs, net = _clean_list(raw.get("filesystem")), _clean_list(raw.get("network"))
    if fs is None or net is None:
        return Permissions(invalid=True)
    return Permissions(filesystem=fs, network=net)


def _frontmatter(data: bytes) -> dict:
    match = _FRONTMATTER.match(data.decode("utf-8", errors="replace").lstrip("\ufeff"))
    if not match:
        return {}
    try:
        parsed = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def declared_permissions(files: dict[str, bytes]) -> Permissions:
    """plugin.json's `permissions` wins; otherwise the union over every SKILL.md frontmatter."""
    raw_plugin = files.get(_PLUGIN_JSON)
    if raw_plugin is not None:
        try:
            plugin = json.loads(raw_plugin.decode("utf-8", errors="replace"))
        except ValueError:
            plugin = None
        if isinstance(plugin, dict) and "permissions" in plugin:
            return parse_permissions(plugin["permissions"])
    fs: list[str] = []
    net: list[str] = []
    for path in sorted(files):
        if path.rsplit("/", 1)[-1] != "SKILL.md":
            continue
        front = _frontmatter(files[path])
        if "permissions" not in front:
            continue
        perms = parse_permissions(front["permissions"])
        if perms.invalid:
            return Permissions(invalid=True)
        fs += [p for p in perms.filesystem if p not in fs]
        net += [h for h in perms.network if h not in net]
    return Permissions(filesystem=tuple(fs), network=tuple(net))


def files_digest(files: dict[str, bytes]) -> str:
    outer = hashlib.sha256()
    for path in sorted(files):
        outer.update(path.encode("utf-8"))
        outer.update(b"\0")
        outer.update(hashlib.sha256(files[path]).digest())
    return outer.hexdigest()


def _hook_commands(files: dict[str, bytes]) -> list[str]:
    raw = files.get("hooks.json")
    if raw is None:
        return []
    try:
        config = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return []
    hooks = config.get("hooks") if isinstance(config, dict) else None
    out: list[str] = []
    for hook in hooks if isinstance(hooks, list) else []:
        command = hook.get("command") if isinstance(hook, dict) else None
        if isinstance(command, str) and command.strip():
            out.append(command[:MAX_HOOK_LEN])
    return out


def _mcp_server_names(files: dict[str, bytes]) -> list[str]:
    from marketplace import installer

    try:
        return sorted(installer._discover_plugin_mcp_manifest_from_files(files) or {})
    except Exception:
        return []


def summarize_package(files: dict[str, bytes]) -> dict:
    perms = declared_permissions(files)
    hooks = _hook_commands(files)
    bin_files = sorted(p for p in files if p.startswith("bin/"))
    servers = _mcp_server_names(files)
    has_tools = "tools.py" in files
    lines: list[str] = []
    if perms.invalid:
        lines.append("The permission declaration in this package is invalid, so it gets no folder or network access.")
    if perms.filesystem:
        lines.append("Reads these folders: " + ", ".join(perms.filesystem))
    else:
        lines.append("Reads these folders: none declared")
    if perms.network:
        lines.append("Network access, not limited to these hosts: " + ", ".join(perms.network))
    else:
        lines.append("Network access: none declared")
    if has_tools:
        lines.append("Adds tools the assistant can call. They run in a restricted sandbox, "
                     "with the folders and network access shown above.")
    for command in hooks:
        lines.append("Runs this command on your computer before an email or Teams message is sent, "
                     "in a restricted sandbox: " + command)
    if bin_files:
        lines.append("Ships programs: " + ", ".join(bin_files))
    for name in servers:
        lines.append(f"Starts the MCP server '{name}' on your computer (not sandboxed).")
    return {
        "permissions": perms.to_dict(),
        "has_tools": has_tools,
        "hooks": hooks,
        "bin": bin_files,
        "mcp_servers": servers,
        "lines": lines,
        "digest": files_digest(files),
    }


def readable_paths(perms: Permissions) -> list[Path]:
    """Declared folders that exist and may be granted. The never-grantable list always wins."""
    from sandbox.paths import PathNotGrantable, is_secrets_path, normalize_grant_paths

    if perms.invalid:
        return []
    out: list[Path] = []
    for item in perms.filesystem:
        try:
            resolved = normalize_grant_paths([item])
        except (PathNotGrantable, OSError, ValueError):
            continue
        out += [p for p in resolved if not is_secrets_path(p) and p not in out]
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/marketplace/test_permissions.py -q`
Expected: all pass. If `normalize_grant_paths` does not expand `~` or rejects a tmp_path under the (redirected) home, adapt only `readable_paths`'s call, not the tests' intent: the test folder must be kept and the missing one dropped.

- [ ] **Step 5: Commit**

```bash
git add web/marketplace/permissions.py tests/marketplace/test_permissions.py
git commit -m "feat: declared permissions parser, package summary and content digest for marketplace skills"
```

### Task 2: Audit logging, sandbox launch wrapper, skill state, fixtures

**Files:**
- Create: `web/marketplace/skill_audit.py`, `web/marketplace/sandbox_launch.py`, `web/marketplace/state.py`
- Modify: `tests/conftest.py` (append two fixtures)
- Test: `tests/marketplace/test_skill_audit.py`, `tests/marketplace/test_sandbox_launch.py`, `tests/marketplace/test_state.py`

**Interfaces:**
- Consumes: `marketplace.permissions.Permissions`, `readable_paths` (Task 1); `sandbox.SandboxRequest`, `sandbox.SandboxResult(returncode, stdout, stderr, timed_out)`, `sandbox.launch_sandboxed`, `sandbox.SandboxUnavailable`, `sandbox.SandboxRunError`, `sandbox.build_env(parent, run_dir, node_path)`; `skills.code_runner.tools` helpers `_runtime_paths(skill_dir, npm_root)`, `_runtime_path_refused(path)`, `_unavailable_message(reason)`, `_RUN_ERROR_MSG`; `marketplace.installer.load_installed/save_installed/_INSTALL_INDEX_LOCK`; `config.OUTPUTS_DIR`, `config.PLUGINS_DIR`, `config.INSTALLED_SKILLS_DIR`.
- Produces:
  - `skill_audit.MARKER = "AIGATOR-SKILL-OUTBOUND "`; `log_launch(skill_id, kind, network, declared)`; `log_outbound(skill_id, destinations)`; `extract_outbound(stderr) -> (list[str], str)`.
  - `sandbox_launch.SkillRun(ok, returncode, stdout, stderr, timed_out, error="")`; `new_run_dir() -> Path`; `run_in_sandbox(skill_id, kind, argv, skill_dir, run_dir, perms, timeout) -> SkillRun`.
  - `state.disabled_ids() -> set[str]`; `is_disabled(skill_id) -> bool`; `get_entry(skill_id) -> dict | None`; `update_entry(skill_id, changes: dict) -> bool` (a `None` value deletes the key); `set_disabled(skill_id, disabled: bool) -> bool`; `record_approval(skill_id, perms_dict) -> bool`; `approved_permissions(skill_id) -> Permissions`; `skill_dir_for(entry) -> Path`.
  - conftest fixtures `fake_sandbox` (records `.requests`; set `.result`, `.raises` or `.handler`) and `make_skill_dir(files: dict[str, str|bytes], name="demo") -> Path`.

- [ ] **Step 1: Append the fixtures to `tests/conftest.py`**

Add at the end of the file (add `import pytest` only if the file does not already import it):

```python
class _FakeSandbox:
    """Stands in for sandbox.launch_sandboxed. Records every request."""

    def __init__(self):
        import sandbox

        self.requests = []
        self.result = sandbox.SandboxResult(returncode=0, stdout="", stderr="", timed_out=False)
        self.raises = None
        self.handler = None

    def __call__(self, request):
        self.requests.append(request)
        if self.raises is not None:
            raise self.raises
        if self.handler is not None:
            return self.handler(request)
        return self.result


@pytest.fixture
def fake_sandbox(monkeypatch):
    import sandbox

    fake = _FakeSandbox()
    monkeypatch.setattr(sandbox, "launch_sandboxed", fake)
    return fake


@pytest.fixture
def make_skill_dir(tmp_path):
    def make(files, name="demo"):
        root = tmp_path / "skills-under-test" / name
        for rel, content in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return root

    return make
```

- [ ] **Step 2: Write the failing tests**

`tests/marketplace/test_skill_audit.py`:

```python
import logging

from marketplace import skill_audit as A


def test_extract_outbound_pulls_marker_lines_and_cleans_stderr():
    stderr = "warn\n" + A.MARKER + "api.example.com:443\nmore\n" + A.MARKER + "api.example.com:443\n"
    dests, cleaned = A.extract_outbound(stderr)
    assert dests == ["api.example.com:443"]
    assert cleaned == "warn\nmore\n"


def test_extract_outbound_caps_destinations():
    stderr = "".join(f"{A.MARKER}h{i}.example.com:443\n" for i in range(200))
    dests, _ = A.extract_outbound(stderr)
    assert len(dests) == A.MAX_DEST


def test_log_launch_and_outbound_lines(caplog):
    with caplog.at_level(logging.INFO, logger="aigator.skill_audit"):
        A.log_launch("demo", "hook", True, ("a.example.com", "b.example.com"))
        A.log_outbound("demo", ["a.example.com:443"])
    text = caplog.text
    assert "skill-launch skill=demo kind=hook network=true declared_hosts=a.example.com,b.example.com" in text
    assert "skill-outbound skill=demo dest=a.example.com:443" in text


def test_log_values_cannot_inject_new_lines(caplog):
    with caplog.at_level(logging.INFO, logger="aigator.skill_audit"):
        A.log_outbound("demo\nskill-launch skill=fake", ["x\ny:1"])
    assert "\nskill-launch skill=fake" not in caplog.text
```

`tests/marketplace/test_sandbox_launch.py`:

```python
import sandbox
from marketplace import sandbox_launch as L
from marketplace.permissions import Permissions


def _run(skill_dir, perms=Permissions(), argv=("python", "x.py")):
    return L.run_in_sandbox("demo", "tool", list(argv), skill_dir, L.new_run_dir(), perms, 30)


def test_request_shape_default_is_no_network_no_extra_paths(fake_sandbox, make_skill_dir):
    skill = make_skill_dir({"SKILL.md": "x"})
    fake_sandbox.result = sandbox.SandboxResult(returncode=0, stdout="ok", stderr="", timed_out=False)
    run = _run(skill)
    assert run.ok and run.stdout == "ok" and run.returncode == 0
    req = fake_sandbox.requests[0]
    assert req.network is False
    assert list(req.read_paths) == [] and list(req.write_paths) == []
    assert skill.resolve() in [p.resolve() for p in req.runtime_paths]
    assert req.timeout == 30
    assert "ANTHROPIC_API_KEY" not in req.env and "GATEWAY_USER_ID" not in req.env


def test_network_only_for_an_approved_non_empty_declaration(fake_sandbox, make_skill_dir):
    skill = make_skill_dir({"SKILL.md": "x"})
    _run(skill, Permissions(network=("a.example.com",)))
    _run(skill, Permissions(network=("a.example.com",), invalid=True))
    assert [r.network for r in fake_sandbox.requests] == [True, False]


def test_declared_folders_become_read_paths(fake_sandbox, make_skill_dir, tmp_path):
    skill = make_skill_dir({"SKILL.md": "x"})
    docs = tmp_path / "docs"
    docs.mkdir()
    _run(skill, Permissions(filesystem=(str(docs),)))
    assert [p.resolve() for p in fake_sandbox.requests[0].read_paths] == [docs.resolve()]


def test_run_folder_is_the_working_folder_not_the_skill_folder(fake_sandbox, make_skill_dir):
    skill = make_skill_dir({"SKILL.md": "x"})
    _run(skill)
    assert fake_sandbox.requests[0].cwd != skill


def test_failures_fail_closed_and_never_run_unsandboxed(fake_sandbox, make_skill_dir):
    skill = make_skill_dir({"SKILL.md": "x"})
    for exc in (sandbox.SandboxUnavailable("no sandbox"), sandbox.SandboxRunError("boom"), OSError("ledger")):
        fake_sandbox.raises = exc
        run = _run(skill)
        assert run.ok is False and run.error
    fake_sandbox.raises = None


def test_timeout_is_reported(fake_sandbox, make_skill_dir):
    skill = make_skill_dir({"SKILL.md": "x"})
    fake_sandbox.result = sandbox.SandboxResult(returncode=-1, stdout="", stderr="", timed_out=True)
    run = _run(skill)
    assert run.ok and run.timed_out


def test_a_protected_skill_folder_is_refused_before_launch(fake_sandbox):
    from pathlib import Path

    run = _run(Path.home())
    assert run.ok is False
    assert fake_sandbox.requests == []


def test_every_launch_is_logged(fake_sandbox, make_skill_dir, caplog):
    import logging

    skill = make_skill_dir({"SKILL.md": "x"})
    with caplog.at_level(logging.INFO, logger="aigator.skill_audit"):
        _run(skill, Permissions(network=("a.example.com",)))
    assert "skill-launch skill=demo kind=tool network=true declared_hosts=a.example.com" in caplog.text
```

`tests/marketplace/test_state.py`:

```python
import pytest

import config
from marketplace import installer, state
from marketplace.permissions import Permissions


@pytest.fixture(autouse=True)
def _index():
    installer.save_installed([
        {"id": "solo", "version": "1.0", "tier": "community"},
        {"id": "bundle", "version": "2.0", "source": "mkt", "skill_ids": ["inner-a", "inner-b"]},
        {"id": "legacy", "version": "1.0"},
    ])


def test_disable_and_enable_round_trip_and_survive_reload():
    assert state.is_disabled("solo") is False
    assert state.set_disabled("solo", True) is True
    assert state.is_disabled("solo") is True
    assert state.get_entry("solo")["disabled"] is True
    assert state.set_disabled("solo", False) is True
    assert state.is_disabled("solo") is False
    assert "disabled" not in state.get_entry("solo")


def test_disabling_a_bundle_disables_its_skill_ids():
    state.set_disabled("bundle", True)
    assert state.disabled_ids() == {"bundle", "inner-a", "inner-b"}
    assert state.is_disabled("inner-a")


def test_unknown_skill_returns_false():
    assert state.set_disabled("nope", True) is False
    assert state.record_approval("nope", {}) is False


def test_record_approval_stores_permissions_and_clears_disabled():
    state.set_disabled("solo", True)
    perms = Permissions(filesystem=("~/x",), network=("h.example.com",))
    assert state.record_approval("solo", perms.to_dict()) is True
    entry = state.get_entry("solo")
    assert entry["permissions"] == perms.to_dict()
    assert entry["approved_at"]
    assert "disabled" not in entry
    assert state.approved_permissions("solo") == perms


def test_legacy_entry_has_no_grants():
    assert state.approved_permissions("legacy") == Permissions()
    assert state.approved_permissions("not-installed") == Permissions()


def test_bundle_inner_skill_uses_the_bundles_approval():
    perms = Permissions(network=("h.example.com",))
    state.record_approval("bundle", perms.to_dict())
    assert state.approved_permissions("inner-a") == perms


def test_skill_dir_for_matches_the_hook_folder_rules():
    assert state.skill_dir_for({"id": "solo"}) == config.INSTALLED_SKILLS_DIR / "solo"
    assert state.skill_dir_for({"id": "bundle", "source": "mkt", "version": "2.0"}) == (
        config.PLUGINS_DIR / "cache" / "mkt" / "bundle" / "2.0"
    )


def test_update_entry_none_deletes_a_key():
    state.update_entry("solo", {"note": "x"})
    assert state.get_entry("solo")["note"] == "x"
    state.update_entry("solo", {"note": None})
    assert "note" not in state.get_entry("solo")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/marketplace/test_skill_audit.py tests/marketplace/test_sandbox_launch.py tests/marketplace/test_state.py -q`
Expected: collection errors (`ModuleNotFoundError`) for the three new modules.

- [ ] **Step 4: Write `web/marketplace/skill_audit.py`**

```python
"""Outbound-destination logging for marketplace skills (logging only, never blocks)."""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("aigator.skill_audit")

MARKER = "AIGATOR-SKILL-OUTBOUND "
MAX_DEST = 50
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _clean(value, limit: int = 200) -> str:
    return _CONTROL.sub("?", str(value))[:limit]


def log_launch(skill_id: str, kind: str, network: bool, declared) -> None:
    hosts = ",".join(_clean(h) for h in declared) or "-"
    logger.info("skill-launch skill=%s kind=%s network=%s declared_hosts=%s",
                _clean(skill_id), _clean(kind, 20), "true" if network else "false", hosts)


def log_outbound(skill_id: str, destinations) -> None:
    for dest in destinations:
        logger.info("skill-outbound skill=%s dest=%s", _clean(skill_id), _clean(dest))


def extract_outbound(stderr: str) -> tuple[list[str], str]:
    """Split the runner's marker lines out of stderr. A skill can forge marker lines; this is a log, not a control."""
    dests: list[str] = []
    kept: list[str] = []
    for line in (stderr or "").splitlines(keepends=True):
        if line.startswith(MARKER):
            dest = line[len(MARKER):].strip()
            if dest and dest not in dests and len(dests) < MAX_DEST:
                dests.append(dest)
        else:
            kept.append(line)
    return dests, "".join(kept)
```

- [ ] **Step 5: Write `web/marketplace/sandbox_launch.py`**

```python
"""The one place that turns a hook or tools.py run into a SandboxRequest."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from marketplace import skill_audit
from marketplace.permissions import Permissions, readable_paths

_REFUSED_MSG = ("The skill sandbox refused to start because a runtime folder is not allowed. "
                "Nothing was run.")


@dataclass(frozen=True)
class SkillRun:
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    error: str = ""


def _failed(message: str) -> SkillRun:
    return SkillRun(False, -1, "", "", False, message)


def new_run_dir() -> Path:
    import config

    run_dir = Path(config.OUTPUTS_DIR) / uuid4().hex[:12]
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def run_in_sandbox(skill_id: str, kind: str, argv: list[str], skill_dir: Path, run_dir: Path,
                   perms: Permissions, timeout: int) -> SkillRun:
    """Run argv in the OS sandbox. Never falls back to running unsandboxed."""
    import sandbox
    from skills.code_runner import tools as cr

    runtime_paths = cr._runtime_paths(skill_dir, None)
    if cr._runtime_path_refused(skill_dir) or any(cr._runtime_path_refused(p) for p in runtime_paths):
        return _failed(_REFUSED_MSG)
    request = sandbox.SandboxRequest(
        argv=argv,
        cwd=run_dir,
        env=sandbox.build_env(os.environ, run_dir, None),
        runtime_paths=runtime_paths,
        read_paths=readable_paths(perms),
        write_paths=[],
        network=perms.wants_network,
        timeout=timeout,
    )
    skill_audit.log_launch(skill_id, kind, perms.wants_network, perms.network)
    try:
        res = sandbox.launch_sandboxed(request)
    except sandbox.SandboxUnavailable as exc:
        return _failed(cr._unavailable_message(str(exc)))
    except sandbox.SandboxRunError:
        return _failed(cr._RUN_ERROR_MSG)
    except OSError as exc:
        return _failed(f"The skill sandbox could not start ({type(exc).__name__}) and nothing was run.")
    return SkillRun(True, res.returncode, res.stdout or "", res.stderr or "", bool(res.timed_out))
```

- [ ] **Step 6: Write `web/marketplace/state.py`**

```python
"""Per-skill flags kept on the installed-skills.json entry: disabled, permissions, approved_at."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from marketplace.permissions import Permissions


def _installer():
    from marketplace import installer

    return installer


def disabled_ids() -> set[str]:
    out: set[str] = set()
    for entry in _installer().load_installed():
        if entry.get("disabled"):
            if entry.get("id"):
                out.add(entry["id"])
            out.update(entry.get("skill_ids") or [])
    return out


def is_disabled(skill_id: str) -> bool:
    return skill_id in disabled_ids()


def get_entry(skill_id: str) -> dict | None:
    """The entry whose id is skill_id, or the bundle entry that lists it in skill_ids."""
    entries = _installer().load_installed()
    for entry in entries:
        if entry.get("id") == skill_id:
            return entry
    for entry in entries:
        if skill_id in (entry.get("skill_ids") or []):
            return entry
    return None


def update_entry(skill_id: str, changes: dict) -> bool:
    inst = _installer()
    with inst._INSTALL_INDEX_LOCK:
        entries = inst.load_installed()
        for entry in entries:
            if entry.get("id") != skill_id:
                continue
            for key, value in changes.items():
                if value is None:
                    entry.pop(key, None)
                else:
                    entry[key] = value
            inst.save_installed(entries)
            return True
    return False


def set_disabled(skill_id: str, disabled: bool) -> bool:
    return update_entry(skill_id, {"disabled": True if disabled else None})


def record_approval(skill_id: str, perms_dict: dict) -> bool:
    return update_entry(skill_id, {
        "permissions": perms_dict,
        "approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "disabled": None,
    })


def approved_permissions(skill_id: str) -> Permissions:
    entry = get_entry(skill_id)
    return Permissions.from_dict(entry.get("permissions")) if entry else Permissions()


def skill_dir_for(entry: dict) -> Path:
    import config

    source, version, skill_id = entry.get("source", ""), entry.get("version", ""), entry.get("id", "")
    if source and version:
        return config.PLUGINS_DIR / "cache" / source / skill_id / version
    return config.INSTALLED_SKILLS_DIR / skill_id
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/marketplace/test_skill_audit.py tests/marketplace/test_sandbox_launch.py tests/marketplace/test_state.py tests/marketplace/test_permissions.py -q`
Expected: all pass. If `sandbox.SandboxResult` or `build_env` have different parameter names than used here, adapt the call in the code and fixture, not the assertions. If `test_a_protected_skill_folder_is_refused_before_launch` passes a path the backstop does not refuse in this repo, use another protected path (the home folder itself is refused by `_runtime_path_refused`).

- [ ] **Step 8: Commit**

```bash
git add web/marketplace/skill_audit.py web/marketplace/sandbox_launch.py web/marketplace/state.py tests/conftest.py tests/marketplace/test_skill_audit.py tests/marketplace/test_sandbox_launch.py tests/marketplace/test_state.py
git commit -m "feat: audit logging, sandbox launch wrapper and per-skill state for marketplace skills"
```

### Task 3: Installer reads the whole package first, checks a content digest, reports permissions

Every install path must be able to fetch the package, show what is in it, and install exactly that content after approval. This task changes `web/marketplace/installer.py` only (the routes follow in Task 4). Nothing about the existing public names changes except new optional parameters and extra keys in return dicts.

**Files:**
- Modify: `web/marketplace/installer.py` (`install_skill_md` at ~146-324, `_install_github_folder` at ~327-396, `get_claude_plugins_official_capabilities` at ~1369-1497, `install_claude_plugins_official_plugin` at ~1500-1741, `get_github_url_capabilities` at ~1764-1873, `install_github_url_plugin` at ~1876-1978)
- Test: `tests/marketplace/test_install_digest.py` (new)

**Interfaces:**
- Consumes: `marketplace.permissions.declared_permissions(files) -> Permissions`, `Permissions.to_dict()`, `files_digest(files) -> str` (Task 1).
- Produces (Task 4 uses these exact names):
  - `installer.preview_package(skill_md: str = "", install_url: str = "", local_zip_bytes: bytes | None = None) -> {"ok": True, "files": dict[str, bytes]} | {"ok": False, "error": str}`. Fetches or reads the package, writes nothing.
  - `installer.install_skill_md(skill_id, skill_md, version, tier, install_url="", _local_zip_bytes=None, expected_digest="")` returns `{"ok": True, "skill_id", "permissions": dict}` or `{"ok": False, "error": ...}`. `error == "content_changed"` means the digest did not match and nothing was written.
  - `installer.install_github_url(install_url, skill_id, version="1.0", orphan_resolution=None, expected_digest="")`: one fetch, digest check, then dispatches to the plugin or the plain-folder installer. Returns the installer result plus `"permissions"` on success. Error `"content_changed"` as above.
  - `installer.install_claude_plugins_official_plugin(entry, consented=False, pinned_ref=None, expected_digest="")`: both success returns carry `"permissions"`; error `"content_changed"`.
  - `installer.install_github_url_plugin(install_url, plugin_id, consented=False, _files=None)` and `installer._install_github_folder(install_url, skill_id, version="1.0", orphan_resolution=None, _files=None)`: when `_files` is given they do not fetch.
  - `get_claude_plugins_official_capabilities(entry)` and `get_github_url_capabilities(install_url)` each return one extra key `"package": dict[str, bytes]` (the fetched files). The caller must pop it before building a JSON response.

- [ ] **Step 1: Write the failing tests**

Create `tests/marketplace/test_install_digest.py`:

```python
import io
import json
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from marketplace import installer
from marketplace.permissions import files_digest

SKILL_MD = (
    "---\nname: demo-skill\ndescription: d\n"
    "permissions:\n  filesystem: []\n  network: [api.example.com]\n---\nBody\n"
)


@pytest.fixture(autouse=True)
def _dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "INSTALLED_SKILLS_DIR", tmp_path / "skills")
    monkeypatch.setattr(installer, "PLUGINS_DIR", tmp_path / "plugins")


def _zip(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _urlopen_returning(data: bytes):
    resp = MagicMock()
    resp.read.return_value = data
    cm = MagicMock()
    cm.__enter__.return_value = resp
    cm.__exit__.return_value = False
    return MagicMock(return_value=cm)


def _index():
    return installer.load_installed()


# ── preview_package ──────────────────────────────────────────────────────────

def test_preview_inline_returns_files_and_writes_nothing():
    res = installer.preview_package(skill_md=SKILL_MD)
    assert res["ok"] is True
    assert res["files"] == {"SKILL.md": SKILL_MD.encode()}
    assert not installer.INSTALLED_SKILLS_DIR.exists()


def test_preview_local_zip_strips_the_root_folder():
    data = _zip({"demo/SKILL.md": SKILL_MD, "demo/tools.py": "TOOL_DEFS = []\n", "other/x.txt": "x"})
    res = installer.preview_package(local_zip_bytes=data)
    assert res["ok"] is True
    assert set(res["files"]) == {"SKILL.md", "tools.py"}


@pytest.mark.parametrize(
    "data, message",
    [
        (b"not a zip", "not a ZIP"),
        (_zip({"readme.txt": "x"}), "No SKILL.md"),
        (_zip({"SKILL.md": SKILL_MD, "../evil.py": "x"}), "path traversal"),
    ],
)
def test_preview_local_zip_rejects_bad_archives(data, message):
    res = installer.preview_package(local_zip_bytes=data)
    assert res["ok"] is False
    assert message in res["error"]


def test_preview_url_accepts_a_zip_and_a_raw_skill_md():
    with patch("urllib.request.urlopen", _urlopen_returning(_zip({"SKILL.md": SKILL_MD}))):
        zipped = installer.preview_package(install_url="https://example.com/s.zip")
    with patch("urllib.request.urlopen", _urlopen_returning(SKILL_MD.encode())):
        raw = installer.preview_package(install_url="https://example.com/SKILL.md")
    assert zipped["files"] == raw["files"] == {"SKILL.md": SKILL_MD.encode()}


def test_preview_url_rejects_other_schemes_and_wraps_download_errors():
    assert "http" in installer.preview_package(install_url="ftp://example.com/s")["error"]
    boom = MagicMock(side_effect=OSError("offline"))
    with patch("urllib.request.urlopen", boom):
        res = installer.preview_package(install_url="https://example.com/s")
    assert res["ok"] is False and res["error"].startswith("Download failed")


# ── install_skill_md ─────────────────────────────────────────────────────────

def test_install_with_matching_digest_writes_and_reports_permissions():
    files = installer.preview_package(skill_md=SKILL_MD)["files"]
    res = installer.install_skill_md(
        "demo-skill", SKILL_MD, "1.0", "Community", expected_digest=files_digest(files)
    )
    assert res["ok"] is True
    assert res["skill_id"] == "demo-skill"
    assert res["permissions"]["network"] == ["api.example.com"]
    assert (installer.INSTALLED_SKILLS_DIR / "demo-skill" / "SKILL.md").read_text(encoding="utf-8") == SKILL_MD
    assert [e["id"] for e in _index()] == ["demo-skill"]


def test_install_with_wrong_digest_writes_nothing():
    res = installer.install_skill_md(
        "demo-skill", SKILL_MD, "1.0", "Community", expected_digest="0" * 64
    )
    assert res == {"ok": False, "error": "content_changed"}
    assert not (installer.INSTALLED_SKILLS_DIR / "demo-skill").exists()
    assert _index() == []


def test_install_without_a_digest_still_works():
    assert installer.install_skill_md("demo-skill", SKILL_MD, "1.0", "Community")["ok"] is True


def test_install_still_rejects_an_id_that_escapes_the_skills_folder():
    res = installer.install_skill_md("../evil", SKILL_MD, "1.0", "Community")
    assert res["ok"] is False and "escapes" in res["error"]


def test_install_local_zip_derives_the_id_from_the_frontmatter_name():
    data = _zip({"folder/SKILL.md": SKILL_MD, "folder/tools.py": "TOOL_DEFS = []\n"})
    res = installer.install_skill_md("", "", "1.0", "Community", _local_zip_bytes=data)
    assert res["ok"] is True and res["skill_id"] == "demo-skill"
    assert (installer.INSTALLED_SKILLS_DIR / "demo-skill" / "tools.py").exists()
    assert _index()[0]["has_tools"] is True


def test_install_local_zip_with_root_level_skill_md_and_no_name_falls_back():
    data = _zip({"SKILL.md": "No frontmatter here\n"})
    res = installer.install_skill_md("", "", "1.0", "Community", _local_zip_bytes=data)
    assert res["ok"] is True and res["skill_id"] == "skill"


def test_install_local_zip_with_wrong_digest_writes_nothing():
    data = _zip({"SKILL.md": SKILL_MD})
    res = installer.install_skill_md(
        "", "", "1.0", "Community", _local_zip_bytes=data, expected_digest="0" * 64
    )
    assert res["error"] == "content_changed"
    assert not installer.INSTALLED_SKILLS_DIR.exists()


def test_install_url_zip_with_wrong_digest_writes_nothing():
    with patch("urllib.request.urlopen", _urlopen_returning(_zip({"SKILL.md": SKILL_MD}))):
        res = installer.install_skill_md(
            "demo-skill", "", "1.0", "Community",
            install_url="https://example.com/s.zip", expected_digest="0" * 64,
        )
    assert res["error"] == "content_changed"
    assert not (installer.INSTALLED_SKILLS_DIR / "demo-skill").exists()


# ── install_github_url ───────────────────────────────────────────────────────

GITHUB_URL = "https://github.com/octo/repo/tree/main/skills/demo"


def test_github_url_plain_skill_fetches_once_and_installs():
    files = {"SKILL.md": SKILL_MD.encode(), "notes.md": b"n"}
    with patch.object(installer.github_fetcher, "download_skill_tarball", return_value=files) as dl:
        res = installer.install_github_url(
            GITHUB_URL, "demo", expected_digest=files_digest(files)
        )
    assert dl.call_count == 1
    assert res["ok"] is True and res["permissions"]["network"] == ["api.example.com"]
    assert (installer.INSTALLED_SKILLS_DIR / "demo" / "notes.md").exists()


def test_github_url_bundle_goes_to_the_plugin_installer_with_the_same_files():
    files = {"a/SKILL.md": b"A", "b/SKILL.md": b"B"}
    with patch.object(installer.github_fetcher, "download_skill_tarball", return_value=files), \
         patch.object(installer, "install_github_url_plugin",
                      return_value={"ok": True, "plugin_id": "bundle"}) as plug:
        res = installer.install_github_url(GITHUB_URL, "bundle")
    plug.assert_called_once()
    assert plug.call_args.kwargs["_files"] is files
    assert plug.call_args.kwargs["consented"] is True
    assert res["ok"] is True and "permissions" in res


def test_github_url_wrong_digest_installs_nothing():
    files = {"SKILL.md": SKILL_MD.encode()}
    with patch.object(installer.github_fetcher, "download_skill_tarball", return_value=files), \
         patch.object(installer, "_install_github_folder") as folder:
        res = installer.install_github_url(GITHUB_URL, "demo", expected_digest="0" * 64)
    assert res == {"ok": False, "error": "content_changed"}
    folder.assert_not_called()


def test_github_url_without_skill_md_and_raw_urls_are_errors():
    with patch.object(installer.github_fetcher, "download_skill_tarball", return_value={"x.txt": b"x"}):
        assert "No SKILL.md" in installer.install_github_url(GITHUB_URL, "demo")["error"]
    raw = "https://raw.githubusercontent.com/octo/repo/main/SKILL.md"
    assert "install_skill_md" in installer.install_github_url(raw, "demo")["error"]


def test_folder_installer_with_files_does_not_fetch():
    files = {"SKILL.md": SKILL_MD.encode()}
    with patch.object(installer.github_fetcher, "download_skill_tarball") as dl:
        res = installer._install_github_folder(GITHUB_URL, "demo", _files=files)
    dl.assert_not_called()
    assert res["ok"] is True


# ── capabilities carry the fetched package ───────────────────────────────────

def test_github_capabilities_return_the_package():
    files = {"SKILL.md": SKILL_MD.encode()}
    with patch.object(installer.github_fetcher, "download_skill_tarball", return_value=files):
        caps = installer.get_github_url_capabilities(GITHUB_URL)
    assert caps["ok"] is True and caps["package"] == files


def test_catalog_capabilities_return_the_package_and_install_checks_the_digest():
    files = {"skills/x/SKILL.md": SKILL_MD.encode(), "plugin.json": json.dumps({"version": "1.2"}).encode()}
    entry = {"id": "cat-plugin", "plugin_source": {"url": "https://github.com/o/r.git"}}
    with patch.object(installer, "_fetch_plugin_source_tree", return_value=("cat-plugin", files, "abc")):
        caps = installer.get_claude_plugins_official_capabilities(entry)
        assert caps["package"] == files
        bad = installer.install_claude_plugins_official_plugin(
            entry, consented=True, pinned_ref="abc", expected_digest="0" * 64
        )
    assert bad == {"ok": False, "error": "content_changed"}
    assert not (installer.PLUGINS_DIR / "cache").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/marketplace/test_install_digest.py -q`
Expected: failures such as `AttributeError: module 'marketplace.installer' has no attribute 'preview_package'` and `TypeError: install_skill_md() got an unexpected keyword argument 'expected_digest'`.

- [ ] **Step 3: Replace `install_skill_md` with the package-first version**

In `web/marketplace/installer.py`, replace the whole `install_skill_md` function (from `def install_skill_md(` through its final `return {"ok": True, "skill_id": skill_id}`, currently lines 146-324) with the block below. `_safe_skill_dir`, `_write_files_atomically`, `load_installed`, `save_installed` and `_slugify` already exist in this module.

```python
def _zip_name_is_unsafe(name: str) -> bool:
    return (
        name.startswith(("/", "\\"))
        or (len(name) > 1 and name[1] == ":")
        or ".." in name.replace("\\", "/").split("/")
    )


def _read_zip_package(data: bytes) -> tuple[dict[str, bytes], str]:
    """Read a skill ZIP into ({path relative to the skill root: bytes}, SKILL.md member name).

    The skill root is the folder of the shallowest SKILL.md. Raises ValueError
    with a user-facing message; nothing is written to disk."""
    from marketplace.github_fetcher import MAX_FILES, MAX_TOTAL_BYTES

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"File is not a valid ZIP archive: {exc}") from exc
    with zf:
        names = [n for n in zf.namelist() if n.endswith("SKILL.md")]
        if not names:
            raise ValueError("No SKILL.md found in package")
        # Reject any traversal or absolute entry BEFORE choosing a root: a
        # malicious archive is not trusted because the bad entry sits outside
        # the chosen subtree.
        all_files = [n for n in zf.namelist() if not n.endswith("/")]
        for n in all_files:
            if _zip_name_is_unsafe(n):
                raise ValueError(f"path traversal not allowed: {n}")
        skill_md_name = min(names, key=lambda n: n.count("/"))
        root_prefix = skill_md_name[: -len("SKILL.md")]
        members = [n for n in all_files if n.startswith(root_prefix)]
        if len(members) > MAX_FILES:
            raise ValueError(f"Skill has too many files (> {MAX_FILES})")
        total = sum(zf.getinfo(n).file_size for n in members)
        if total > MAX_TOTAL_BYTES:
            raise ValueError(f"Skill too large (> {MAX_TOTAL_BYTES // (1024 * 1024)} MB)")
        files = {n[len(root_prefix):]: zf.read(n) for n in members}
    return files, skill_md_name


def _load_package(
    skill_md: str, install_url: str, local_zip_bytes: bytes | None
) -> tuple[dict[str, bytes], str]:
    """Return ({relative path: bytes}, SKILL.md member name) for the three
    non-GitHub sources: local ZIP bytes, an http(s) URL (ZIP or raw SKILL.md),
    or inline SKILL.md text. Raises ValueError with a user-facing message."""
    if local_zip_bytes is not None:
        if local_zip_bytes[:4] != b"PK\x03\x04":
            raise ValueError("File is not a ZIP archive")
        return _read_zip_package(local_zip_bytes)

    if install_url and not skill_md:
        if not install_url.startswith(("https://", "http://")):
            raise ValueError("install_url must be an http:// or https:// URL")
        try:
            req = urllib.request.Request(install_url, headers={"User-Agent": "AIGator/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read(20 * 1024 * 1024)  # 20 MB limit
            if data[:4] != b"PK\x03\x04":
                data.decode("utf-8")
        except Exception as exc:
            raise ValueError(f"Download failed: {exc}") from exc
        # ZIP magic bytes are PK\x03\x04; anything else is a plain SKILL.md.
        if data[:4] == b"PK\x03\x04":
            return _read_zip_package(data)
        return {"SKILL.md": data}, "SKILL.md"

    return {"SKILL.md": skill_md.encode("utf-8")}, "SKILL.md"


def preview_package(
    skill_md: str = "", install_url: str = "", local_zip_bytes: bytes | None = None
) -> dict:
    """Fetch or read a package exactly as install_skill_md would, without
    writing anything. Returns {"ok": True, "files": {...}} or {"ok": False, "error"}."""
    try:
        files, _member = _load_package(skill_md, install_url, local_zip_bytes)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "files": files}


def install_skill_md(
    skill_id: str,
    skill_md: str,
    version: str,
    tier: str,
    install_url: str = "",
    _local_zip_bytes: bytes | None = None,
    expected_digest: str = "",
) -> dict:
    """Install a skill from inline SKILL.md, a URL, or raw ZIP bytes.

    The whole package is read first. If expected_digest is given and the
    content's digest differs (the content changed since the user approved it),
    nothing is written and the error is "content_changed". skill_id may be
    empty when _local_zip_bytes is supplied; it is derived from the SKILL.md
    frontmatter name (or the folder name) in that case.

    A URL ZIP is extracted in full (SKILL.md, tools.py, scripts/, reference
    docs) subject to size caps and path-traversal guards; a plain SKILL.md URL
    is written as the single file."""
    from marketplace.permissions import declared_permissions, files_digest

    if skill_id:
        try:
            _safe_skill_dir(INSTALLED_SKILLS_DIR, skill_id)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    try:
        files, skill_md_member = _load_package(skill_md, install_url, _local_zip_bytes)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    if expected_digest and files_digest(files) != expected_digest:
        return {"ok": False, "error": "content_changed"}

    if not skill_id:
        fm = _parse_skill_md_frontmatter(files["SKILL.md"].decode("utf-8", errors="replace"))
        parts = skill_md_member.split("/")
        parent = parts[-2] if len(parts) > 1 else ""
        skill_id = _slugify(fm.get("name") or parent or "skill")

    try:
        skill_dir = _safe_skill_dir(INSTALLED_SKILLS_DIR, skill_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    # Only remove a directory this call created if the write fails.
    created_now = not skill_dir.exists()
    try:
        skill_dir.mkdir(parents=True, exist_ok=True)
        _write_files_atomically(skill_dir, files)
    except ValueError as exc:
        if created_now:
            shutil.rmtree(skill_dir, ignore_errors=True)
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        if created_now:
            shutil.rmtree(skill_dir, ignore_errors=True)
        logger.warning("Skill install write failed for %s: %s", skill_id, exc)
        return {"ok": False, "error": f"Install failed: {exc}"}

    entries = [e for e in load_installed() if e.get("id") != skill_id]
    entries.append(
        {
            "id": skill_id,
            "version": version,
            "tier": tier,
            "installed_at": datetime.now(timezone.utc).isoformat(),
            "has_tools": (skill_dir / "tools.py").exists(),
        }
    )
    save_installed(entries)
    return {
        "ok": True,
        "skill_id": skill_id,
        "permissions": declared_permissions(files).to_dict(),
    }
```

- [ ] **Step 4: Let `_install_github_folder` accept already-fetched files**

In `_install_github_folder`, change the signature and the fetch section. Replace

```python
def _install_github_folder(
    install_url: str,
    skill_id: str,
    version: str = "1.0",
    orphan_resolution: str | None = None,
) -> dict:
```

with

```python
def _install_github_folder(
    install_url: str,
    skill_id: str,
    version: str = "1.0",
    orphan_resolution: str | None = None,
    _files: dict[str, bytes] | None = None,
) -> dict:
```

and replace the block that starts at `try:\n        parsed = github_fetcher.parse_github_url(install_url)` and ends at the `return {"ok": False, "error": f"Download failed: {exc}"}` of the download `except Exception` (the lines between the `_safe_skill_dir` check and `if "SKILL.md" not in files:`) with:

```python
    if _files is None:
        try:
            parsed = github_fetcher.parse_github_url(install_url)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if parsed["kind"] == "raw_file":
            return {"ok": False, "error": "Use install_skill_md for raw SKILL.md URLs"}

        try:
            files = github_fetcher.download_skill_tarball(
                parsed["owner"], parsed["repo"], parsed["branch"], parsed["path"]
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            logger.warning("Codeload download failed: %s", exc)
            return {"ok": False, "error": f"Download failed: {exc}"}
    else:
        files = _files
```

Leave `if "SKILL.md" not in files:` and everything after it unchanged.

- [ ] **Step 5: Add the `install_github_url` dispatcher**

Add this function directly after `install_github_url_plugin` (end of the file), after Step 7 has changed that function:

```python
def install_github_url(
    install_url: str,
    skill_id: str,
    version: str = "1.0",
    orphan_resolution: str | None = None,
    expected_digest: str = "",
) -> dict:
    """Install a GitHub tree/blob URL after approval: fetch once, check the
    content digest the user approved, then install the same bytes as a plugin
    bundle or as a plain skill folder."""
    from marketplace.permissions import declared_permissions, files_digest

    try:
        parsed = github_fetcher.parse_github_url(install_url)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if parsed["kind"] == "raw_file":
        return {"ok": False, "error": "Use install_skill_md for raw SKILL.md URLs"}

    try:
        files = github_fetcher.download_skill_tarball(
            parsed["owner"], parsed["repo"], parsed["branch"], parsed["path"]
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.warning("GitHub URL fetch failed for %s: %s", install_url, exc)
        return {"ok": False, "error": f"Download failed: {exc}"}

    if not any(r.endswith("SKILL.md") for r in files):
        return {"ok": False, "error": "No SKILL.md found at this URL"}
    if expected_digest and files_digest(files) != expected_digest:
        return {"ok": False, "error": "content_changed"}

    if _is_plugin_bundle(files):
        result = install_github_url_plugin(
            install_url, skill_id, consented=True, _files=files
        )
    else:
        result = _install_github_folder(
            install_url, skill_id, version, orphan_resolution, _files=files
        )
    if result.get("ok"):
        result["permissions"] = declared_permissions(files).to_dict()
    return result
```

- [ ] **Step 6: Let `install_github_url_plugin` accept already-fetched files**

Change its signature to

```python
def install_github_url_plugin(
    install_url: str,
    plugin_id: str,
    consented: bool = False,
    _files: dict[str, bytes] | None = None,
) -> dict:
```

and replace the block from `try:\n        parsed = github_fetcher.parse_github_url(install_url)` through the `except Exception as exc:` handler that returns `Download failed` (the lines before `if not any(r.endswith("SKILL.md") for r in files):`) with:

```python
    if _files is None:
        try:
            parsed = github_fetcher.parse_github_url(install_url)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        try:
            files = github_fetcher.download_skill_tarball(
                parsed["owner"], parsed["repo"], parsed["branch"], parsed["path"]
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            logger.warning("GitHub URL plugin fetch failed: %s", exc)
            return {"ok": False, "error": f"Download failed: {exc}"}
    else:
        files = _files
```

- [ ] **Step 7: Digest check and permissions on the catalog plugin install**

In `install_claude_plugins_official_plugin`:

1. Change the signature to
   `entry: dict, consented: bool = False, pinned_ref: str | None = None, expected_digest: str = ""`.
2. Directly after the line `plugin_id, files, resolved_ref = fetched` (the one inside this function, followed by `version = _extract_plugin_version(files) or "unknown"`), insert:

```python
    from marketplace.permissions import declared_permissions, files_digest

    if expected_digest and files_digest(files) != expected_digest:
        return {"ok": False, "error": "content_changed"}
    permissions = declared_permissions(files).to_dict()
```

3. Add `"permissions": permissions,` to BOTH success return dicts of this function (the one in the "already installed, reuse existing record" branch that ends with `"mcp_compatibility_warnings": mcp_compatibility_warnings,` and the final one).

- [ ] **Step 8: Return the fetched package from both capability functions**

In `get_claude_plugins_official_capabilities`, add `"package": files,` to the final returned dict (after `"resolved_ref": resolved_ref,`). In `get_github_url_capabilities`, add `"package": files,` to the final returned dict (after `"total_size": ...`). Add this sentence to each docstring: `The returned dict also carries "package" (the fetched files, bytes); callers must pop it before serializing to JSON.`

- [ ] **Step 9: Run the new tests**

Run: `python -m pytest tests/marketplace/test_install_digest.py -q`
Expected: all pass.

- [ ] **Step 10: Run the existing installer tests**

Run: `python -m pytest tests/marketplace/test_installer.py tests/marketplace/test_installer_plugin_bundle.py tests/marketplace/test_installer_plugin_mcp.py tests/marketplace/test_claude_plugins_official.py tests/marketplace/test_p0_archive_root_and_plugin_bundle.py -q`
Expected: pass except the 2 baseline errors in `test_installer.py` (no `httpserver` fixture). The routes are not touched in this task, so route tests still pass. If an existing test fails, fix the installer change, not the test.

- [ ] **Step 11: Commit**

```bash
git add web/marketplace/installer.py tests/marketplace/test_install_digest.py
git commit -m "feat: installers read the whole package first, check an approved content digest and report declared permissions"
```

### Task 4: Install routes: consent on every path, digest, CSRF, recorded grants

Every install route returns a summary of the package first, installs nothing until the client resubmits with `consent=True` and the digest it was shown, and records the approved permissions on the install record. This task changes `web/routes/marketplace.py` and the existing tests that call the install routes. The disable and enable routes belong to Task 7 (they need the kill switch module).

**Files:**
- Modify: `web/routes/marketplace.py` (imports at 1-26, `InstallRequest` at 64-81, helpers after `_skill_already_installed` at 94, `_install_claude_plugins_official` at 143-241, `install_skill` at 426-533, `LocalInstallRequest` at 609-613, `install_local` at 616-674)
- Test: `tests/marketplace/test_consent_routes.py` (new)
- Modify (existing tests that call these routes): `tests/marketplace/test_routes.py`, `tests/marketplace/test_preview_endpoint.py`, `tests/marketplace/test_installer.py` (the four `install-local` tests at ~512-617)

**Interfaces:**
- Consumes (Task 1): `marketplace.permissions.summarize_package(files) -> dict` (keys `permissions`, `has_tools`, `hooks`, `bin`, `mcp_servers`, `lines`, `digest`). (Task 2): `marketplace.state.record_approval(skill_id, perms_dict)`. (Task 3): `installer.preview_package`, `installer.install_github_url`, `installer.install_skill_md(..., expected_digest=)`, `installer.install_claude_plugins_official_plugin(..., expected_digest=)`, the `"package"` key on both capability functions, the `"permissions"` key on successful install results, and the error string `"content_changed"`.
- Produces (Task 8, the JS, depends on these shapes):
  - `InstallRequest.digest: str = ""`; `LocalInstallRequest.consent: bool = False`, `LocalInstallRequest.digest: str = ""`.
  - Consent response, plugin bundle or catalog plugin: `{"ok": False, "consent_required": True, "plugin_id", "resolved_ref", "capabilities": {...}, "summary": <summarize_package dict>}`.
  - Consent response, plain skill (raw `SKILL.md` URL, ZIP URL, GitHub folder that is not a bundle, inline `skill_md`, local ZIP or folder): `{"ok": False, "consent_required": True, "skill_id": <str, "" for local installs>, "resolved_ref": "", "summary": <summarize_package dict>}`.
  - `consent=True` with an empty `digest` is HTTP 400 `"digest is required to approve an install"`. A digest that no longer matches the content is HTTP 409 with detail `{"error": "content_changed", "message": ...}` and nothing written.
  - `install`, `install-local` require the CSRF header (`verify_csrf`): HTTP 403 without it.
  - After a successful install the route calls `state.record_approval(<plugin_id or skill_id>, result["permissions"])` before it loads tools.

- [ ] **Step 1: Write the failing tests**

Create `tests/marketplace/test_consent_routes.py`:

```python
import base64
import io
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from marketplace import installer, state
from marketplace.permissions import files_digest
from routes.marketplace import router
from security import get_csrf_token

SKILL_MD = (
    "---\nname: demo-skill\ndescription: d\n"
    "permissions:\n  filesystem: []\n  network: [api.example.com]\n---\nBody\n"
)
SKILL_FILES = {"SKILL.md": SKILL_MD.encode()}


def _headers():
    return {"X-CSRF-Token": get_csrf_token()}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "INSTALLED_SKILLS_DIR", tmp_path / "skills")
    monkeypatch.setattr(installer, "PLUGINS_DIR", tmp_path / "plugins")
    app = FastAPI()
    app.include_router(router)
    with (
        patch("routes.marketplace.load_installed_skill_prompts") as prompts,
        patch("routes.marketplace.load_skill_tools") as load_tools,
        patch("routes.marketplace.fetch_catalog", return_value=[]),
    ):
        yield SimpleNamespace(
            client=TestClient(app),
            prompts=prompts,
            load_tools=load_tools,
            skills_dir=tmp_path / "skills",
        )


def _zip_b64(entries: dict[str, str]) -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return base64.b64encode(buf.getvalue()).decode()


# ── CSRF ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/api/marketplace/install", "/api/marketplace/install-local"])
def test_install_routes_reject_a_missing_or_wrong_csrf_token(env, path):
    body = {"skill_id": "demo-skill", "skill_md": SKILL_MD, "kind": "zip", "name": "x"}
    assert env.client.post(path, json=body).status_code == 403
    assert env.client.post(path, json=body, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert not env.skills_dir.exists()


# ── Plain skill: consent first, nothing written before it ────────────────────

def test_inline_skill_returns_a_summary_and_writes_nothing(env):
    r = env.client.post(
        "/api/marketplace/install",
        json={"skill_id": "demo-skill", "skill_md": SKILL_MD},
        headers=_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and body["consent_required"] is True
    assert body["skill_id"] == "demo-skill"
    assert body["summary"]["permissions"]["network"] == ["api.example.com"]
    assert body["summary"]["digest"] == files_digest(SKILL_FILES)
    assert any("api.example.com" in line for line in body["summary"]["lines"])
    assert not env.skills_dir.exists()
    assert installer.load_installed() == []
    env.load_tools.assert_not_called()


def test_consent_without_a_digest_is_refused(env):
    r = env.client.post(
        "/api/marketplace/install",
        json={"skill_id": "demo-skill", "skill_md": SKILL_MD, "consent": True},
        headers=_headers(),
    )
    assert r.status_code == 400
    assert "digest" in r.json()["detail"]
    assert not env.skills_dir.exists()


def test_a_digest_that_no_longer_matches_is_a_409_and_writes_nothing(env):
    r = env.client.post(
        "/api/marketplace/install",
        json={"skill_id": "demo-skill", "skill_md": SKILL_MD, "consent": True, "digest": "0" * 64},
        headers=_headers(),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "content_changed"
    assert not env.skills_dir.exists()
    assert installer.load_installed() == []


def test_consent_with_the_shown_digest_installs_and_records_the_grant(env):
    shown = env.client.post(
        "/api/marketplace/install",
        json={"skill_id": "demo-skill", "skill_md": SKILL_MD},
        headers=_headers(),
    ).json()["summary"]["digest"]

    seen_at_load = {}

    def _capture(skill_id, skill_dir, tier):
        seen_at_load["network"] = list(state.approved_permissions(skill_id).network)

    env.load_tools.side_effect = _capture

    r = env.client.post(
        "/api/marketplace/install",
        json={"skill_id": "demo-skill", "skill_md": SKILL_MD, "consent": True, "digest": shown},
        headers=_headers(),
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    entry = state.get_entry("demo-skill")
    assert entry["permissions"] == {"filesystem": [], "network": ["api.example.com"], "invalid": False}
    assert entry["approved_at"]
    assert (env.skills_dir / "demo-skill" / "SKILL.md").exists()
    assert seen_at_load["network"] == ["api.example.com"]


def test_a_skill_with_no_declaration_is_recorded_with_no_grants(env):
    md = "---\nname: plain\ndescription: d\n---\nBody\n"
    digest = files_digest({"SKILL.md": md.encode()})
    r = env.client.post(
        "/api/marketplace/install",
        json={"skill_id": "plain", "skill_md": md, "consent": True, "digest": digest},
        headers=_headers(),
    )
    assert r.status_code == 200, r.text
    assert state.approved_permissions("plain").network == ()
    assert state.approved_permissions("plain").filesystem == ()


# ── Other plain paths ────────────────────────────────────────────────────────

def test_zip_url_returns_a_summary_without_installing(env):
    with patch(
        "marketplace.installer.preview_package",
        return_value={"ok": True, "files": SKILL_FILES},
    ) as preview:
        r = env.client.post(
            "/api/marketplace/install",
            json={"skill_id": "demo-skill", "install_url": "https://example.com/demo.zip"},
            headers=_headers(),
        )
    assert r.status_code == 200
    assert r.json()["consent_required"] is True
    assert r.json()["summary"]["digest"] == files_digest(SKILL_FILES)
    preview.assert_called_once_with(skill_md="", install_url="https://example.com/demo.zip")
    assert not env.skills_dir.exists()


def test_a_package_that_cannot_be_read_is_a_400(env):
    with patch(
        "marketplace.installer.preview_package",
        return_value={"ok": False, "error": "Could not download the file"},
    ):
        r = env.client.post(
            "/api/marketplace/install",
            json={"skill_id": "demo-skill", "install_url": "https://example.com/demo.zip"},
            headers=_headers(),
        )
    assert r.status_code == 400
    assert "Could not download" in r.json()["detail"]


def test_github_folder_plain_skill_consent_uses_the_fetched_package(env):
    caps = {"ok": True, "is_plugin": False, "skill_id": "demo-skill", "package": SKILL_FILES}
    with patch("marketplace.installer.get_github_url_capabilities", return_value=caps), patch(
        "marketplace.installer.install_github_url"
    ) as install:
        r = env.client.post(
            "/api/marketplace/install",
            json={"skill_id": "demo-skill", "install_url": "https://github.com/o/r/tree/main/demo"},
            headers=_headers(),
        )
    assert r.status_code == 200
    body = r.json()
    assert body["consent_required"] is True and body["skill_id"] == "demo-skill"
    assert body["summary"]["digest"] == files_digest(SKILL_FILES)
    assert "package" not in str(body)
    install.assert_not_called()


def test_github_folder_bundle_consent_carries_capabilities_and_summary(env):
    caps = {
        "ok": True, "is_plugin": True, "skill_id": "my-bundle", "skill_count": 1,
        "command_count": 0, "has_mcp": False, "has_local_code": False,
        "mcp_servers": [], "has_compat_risk": False, "package": SKILL_FILES,
    }
    with patch("marketplace.installer.get_github_url_capabilities", return_value=caps):
        r = env.client.post(
            "/api/marketplace/install",
            json={"skill_id": "my-bundle", "install_url": "https://github.com/o/r/tree/main/b"},
            headers=_headers(),
        )
    body = r.json()
    assert body["consent_required"] is True and body["plugin_id"] == "my-bundle"
    assert body["capabilities"]["skill_count"] == 1
    assert body["summary"]["digest"] == files_digest(SKILL_FILES)


def test_github_folder_consent_dispatches_with_the_digest_and_records_the_grant(env):
    perms = {"filesystem": [], "network": [], "invalid": False}
    result = {"ok": True, "skill_id": "demo-skill", "permissions": perms}
    installer.save_installed([{"id": "demo-skill", "version": "1.0", "tier": "Community"}])
    with patch("marketplace.installer.install_github_url", return_value=result) as install:
        r = env.client.post(
            "/api/marketplace/install",
            json={
                "skill_id": "demo-skill",
                "install_url": "https://github.com/o/r/tree/main/demo",
                "consent": True,
                "digest": "d1",
                "orphan_resolution": "keep",
            },
            headers=_headers(),
        )
    assert r.status_code == 200, r.text
    install.assert_called_once_with(
        "https://github.com/o/r/tree/main/demo", "demo-skill", "1.0",
        orphan_resolution="keep", expected_digest="d1",
    )
    assert state.get_entry("demo-skill")["permissions"] == perms


def test_github_folder_content_changed_is_a_409(env):
    with patch(
        "marketplace.installer.install_github_url",
        return_value={"ok": False, "error": "content_changed"},
    ):
        r = env.client.post(
            "/api/marketplace/install",
            json={
                "skill_id": "demo-skill",
                "install_url": "https://github.com/o/r/tree/main/demo",
                "consent": True,
                "digest": "d1",
            },
            headers=_headers(),
        )
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "content_changed"


def test_orphan_resolution_is_still_a_400_with_the_orphan_list(env):
    with patch(
        "marketplace.installer.install_github_url",
        return_value={"ok": False, "error": "orphan_resolution_required", "orphans": ["old.txt"]},
    ):
        r = env.client.post(
            "/api/marketplace/install",
            json={
                "skill_id": "demo-skill",
                "install_url": "https://github.com/o/r/tree/main/demo",
                "consent": True,
                "digest": "d1",
            },
            headers=_headers(),
        )
    assert r.status_code == 400
    assert r.json()["detail"]["orphans"] == ["old.txt"]


# ── Catalog plugin ───────────────────────────────────────────────────────────

_CPO = {
    "id": "amd-skills", "name": "amd-skills", "tier": "Verified",
    "source": "claude-plugins-official", "installable": True, "coding_class": "none",
}


def test_catalog_plugin_consent_carries_a_summary_and_no_package_bytes(env):
    caps = {
        "ok": True, "plugin_id": "amd-skills", "skill_count": 1, "has_mcp": False,
        "has_local_code": False, "mcp_servers": [], "package": SKILL_FILES,
    }
    with patch("routes.marketplace.fetch_catalog", return_value=[_CPO]), patch(
        "marketplace.installer.get_claude_plugins_official_capabilities", return_value=caps
    ):
        r = env.client.post(
            "/api/marketplace/install", json={"skill_id": "amd-skills"}, headers=_headers()
        )
    body = r.json()
    assert r.status_code == 200
    assert body["summary"]["digest"] == files_digest(SKILL_FILES)
    assert "package" not in body and "package" not in body["capabilities"]


def test_catalog_plugin_consent_requires_the_digest_and_passes_it_through(env):
    result = {"ok": True, "plugin_id": "amd-skills", "skill_ids": [], "permissions": {"filesystem": [], "network": [], "invalid": False}}
    with patch("routes.marketplace.fetch_catalog", return_value=[_CPO]), patch(
        "marketplace.installer.install_claude_plugins_official_plugin", return_value=result
    ) as install:
        missing = env.client.post(
            "/api/marketplace/install",
            json={"skill_id": "amd-skills", "consent": True},
            headers=_headers(),
        )
        ok = env.client.post(
            "/api/marketplace/install",
            json={"skill_id": "amd-skills", "consent": True, "digest": "d1", "pinned_ref": "abc"},
            headers=_headers(),
        )
    assert missing.status_code == 400
    assert ok.status_code == 200, ok.text
    install.assert_called_once()
    kwargs = install.call_args.kwargs
    assert kwargs["consented"] is True
    assert kwargs["pinned_ref"] == "abc"
    assert kwargs["expected_digest"] == "d1"


def test_catalog_plugin_content_changed_is_a_409(env):
    with patch("routes.marketplace.fetch_catalog", return_value=[_CPO]), patch(
        "marketplace.installer.install_claude_plugins_official_plugin",
        return_value={"ok": False, "error": "content_changed"},
    ):
        r = env.client.post(
            "/api/marketplace/install",
            json={"skill_id": "amd-skills", "consent": True, "digest": "d1"},
            headers=_headers(),
        )
    assert r.status_code == 409


# ── Local install ────────────────────────────────────────────────────────────

def test_local_zip_returns_a_summary_then_installs_with_the_digest(env):
    b64 = _zip_b64({"local-skill/SKILL.md": SKILL_MD})
    first = env.client.post(
        "/api/marketplace/install-local",
        json={"kind": "zip", "name": "local-skill.zip", "b64": b64},
        headers=_headers(),
    )
    assert first.status_code == 200
    body = first.json()
    assert body["consent_required"] is True and body["skill_id"] == ""
    assert body["summary"]["permissions"]["network"] == ["api.example.com"]
    assert not env.skills_dir.exists()
    env.load_tools.assert_not_called()

    second = env.client.post(
        "/api/marketplace/install-local",
        json={
            "kind": "zip", "name": "local-skill.zip", "b64": b64,
            "consent": True, "digest": body["summary"]["digest"],
        },
        headers=_headers(),
    )
    assert second.status_code == 200, second.text
    skill_id = second.json()["skill_id"]
    assert state.get_entry(skill_id)["permissions"]["network"] == ["api.example.com"]
    env.load_tools.assert_called_once()


def test_local_install_consent_without_a_digest_is_refused(env):
    r = env.client.post(
        "/api/marketplace/install-local",
        json={"kind": "zip", "name": "x.zip", "b64": _zip_b64({"s/SKILL.md": SKILL_MD}), "consent": True},
        headers=_headers(),
    )
    assert r.status_code == 400
    assert not env.skills_dir.exists()


def test_local_install_with_a_stale_digest_is_a_409(env):
    r = env.client.post(
        "/api/marketplace/install-local",
        json={
            "kind": "zip", "name": "x.zip", "b64": _zip_b64({"s/SKILL.md": SKILL_MD}),
            "consent": True, "digest": "0" * 64,
        },
        headers=_headers(),
    )
    assert r.status_code == 409
    assert not env.skills_dir.exists()
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python -m pytest tests/marketplace/test_consent_routes.py -q`
Expected: FAIL (the routes return 200 without consent or reject nothing; `digest` is not a field).

- [ ] **Step 3: Update `web/routes/marketplace.py`**

3a. Imports. Change the first imports and add the new ones:

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import load_config as _load_config
from marketplace import state as skill_state
from marketplace.permissions import summarize_package
from marketplace.registry import (
    fetch_catalog,
    normalize_entry,
    _parse_skill_md_frontmatter,
)
```

and, after `from shared import load_installed_skill_prompts`, add:

```python
from security import verify_csrf
```

3b. In `InstallRequest`, after the `pinned_ref: str = ""` line, add:

```python
    # Content digest the client was shown with the consent card; required with consent=True.
    digest: str = ""
```

In `LocalInstallRequest`, after `files: list[LocalInstallFile] = []  # folder: ...` add:

```python
    consent: bool = False
    digest: str = ""
```

3c. Add these helpers directly after `_skill_already_installed`:

```python
def _require_digest(digest: str) -> None:
    if not digest:
        raise HTTPException(
            status_code=400, detail="digest is required to approve an install"
        )


def _install_failure(result: dict) -> HTTPException:
    error = result.get("error", "Install failed")
    if error == "content_changed":
        return HTTPException(
            status_code=409,
            detail={
                "error": "content_changed",
                "message": "The package changed since you reviewed it. Review it again before installing.",
            },
        )
    if error == "orphan_resolution_required":
        return HTTPException(
            status_code=400,
            detail={
                "error": "Orphan files require resolution",
                "orphans": result.get("orphans", []),
            },
        )
    return HTTPException(status_code=500, detail=error)


def _plain_consent(skill_id: str, summary: dict) -> dict:
    return {
        "ok": False,
        "consent_required": True,
        "skill_id": skill_id,
        "resolved_ref": "",
        "summary": summary,
    }


def _record_grants(result: dict, skill_id: str) -> None:
    """Store what the user approved on the install record. An installer result
    with no permissions records an empty grant, which is the safe default."""
    skill_state.record_approval(skill_id, result.get("permissions") or {})
```

3d. Replace `_install_claude_plugins_official` (the whole function, lines 143-241) with:

```python
def _install_claude_plugins_official(
    entry: dict, consent: bool, pinned_ref: str = "", digest: str = ""
) -> dict:
    """Server-side consent gate + installable enforcement for
    claude-plugins-official plugins (decisions #7/#8).

    Refuses coding_hard (LSP) entries outright. Without consent it fetches
    (but does not install) the plugin and returns its capabilities and a
    package summary with a content digest. With consent the digest the user
    was shown is required and the installer refuses content that no longer
    matches it. `pinned_ref` pins the real install to the previewed commit.
    """
    from marketplace.installer import (
        install_claude_plugins_official_plugin,
        get_claude_plugins_official_capabilities,
    )

    # Fail closed: a catalog entry missing `installable` is NOT installable.
    if not entry.get("installable", False):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "not_installable",
                "message": (
                    f"{entry.get('name') or entry.get('id')} is a coding-oriented "
                    "(LSP) plugin and can't run in Gator chat. Use the Coding Agent instead."
                ),
                "coding_class": entry.get("coding_class"),
            },
        )

    if not consent:
        caps = get_claude_plugins_official_capabilities(entry)
        if not caps.get("ok"):
            raise HTTPException(
                status_code=502,
                detail=caps.get("error", "Could not fetch plugin capabilities"),
            )
        package = caps.pop("package", None) or {}
        return {
            "ok": False,
            "consent_required": True,
            "plugin_id": caps["plugin_id"],
            "resolved_ref": caps.get("resolved_ref", ""),
            "capabilities": {
                "skill_count": caps["skill_count"],
                "command_count": caps.get("command_count", 0),
                "has_mcp": caps["has_mcp"],
                "has_local_code": caps["has_local_code"],
                "mcp_servers": caps.get("mcp_servers", []),
                "has_compat_risk": caps.get("has_compat_risk", False),
            },
            "summary": summarize_package(package),
        }

    _require_digest(digest)
    result = install_claude_plugins_official_plugin(
        entry,
        consented=True,
        pinned_ref=pinned_ref or None,
        expected_digest=digest,
    )
    if not result.get("ok"):
        raise _install_failure(result)
    _record_grants(result, result.get("plugin_id") or entry.get("id", ""))
    load_installed_skill_prompts()  # refresh SKILL_PROMPTS without restart
    # Enrich command_ids into {name, description, plugin_id} so the "/" menu
    # can register them without a reload.
    result["commands"] = _commands_payload(result.get("command_ids") or [])
    return result
```

3e. Replace the `install_skill` route (decorator through `return result`, lines 426-533) with:

```python
@router.post("/api/marketplace/install", dependencies=[Depends(verify_csrf)])
async def install_skill(req: InstallRequest):
    if not req.skill_id:
        raise HTTPException(status_code=400, detail="skill_id is required")

    # claude-plugins-official entries route to the plugin-bundle installer,
    # looked up server-side from the cached catalog (never from a client
    # field) so installable/coding_class enforcement cannot be bypassed.
    catalog_entry = _find_catalog_entry(req.skill_id)
    if (
        catalog_entry is not None
        and catalog_entry.get("source") == "claude-plugins-official"
    ):
        return _install_claude_plugins_official(
            catalog_entry, req.consent, req.pinned_ref, req.digest
        )

    if not req.skill_md and not req.install_url:
        raise HTTPException(
            status_code=400, detail="Either skill_md or install_url is required"
        )

    import marketplace.installer as _installer

    is_github_folder = bool(req.install_url) and (
        req.install_url.startswith("https://github.com/")
        and ("/tree/" in req.install_url or "/blob/" in req.install_url)
    )
    if is_github_folder:
        if not req.consent:
            caps = _installer.get_github_url_capabilities(req.install_url)
            if not caps.get("ok"):
                raise HTTPException(
                    status_code=400, detail=caps.get("error", "Preview failed")
                )
            summary = summarize_package(caps.pop("package", None) or {})
            if caps.get("is_plugin"):
                return {
                    "ok": False,
                    "consent_required": True,
                    "plugin_id": caps["skill_id"],
                    "resolved_ref": "",
                    "capabilities": {
                        "skill_count": caps["skill_count"],
                        "command_count": caps["command_count"],
                        "has_mcp": caps["has_mcp"],
                        "has_local_code": caps["has_local_code"],
                        "mcp_servers": caps["mcp_servers"],
                        "has_compat_risk": caps["has_compat_risk"],
                    },
                    "summary": summary,
                }
            return _plain_consent(req.skill_id, summary)
        _require_digest(req.digest)
        result = _installer.install_github_url(
            req.install_url,
            req.skill_id,
            req.version,
            orphan_resolution=req.orphan_resolution,
            expected_digest=req.digest,
        )
    else:
        if not req.consent:
            preview = _installer.preview_package(
                skill_md=req.skill_md, install_url=req.install_url
            )
            if not preview.get("ok"):
                raise HTTPException(
                    status_code=400, detail=preview.get("error", "Preview failed")
                )
            return _plain_consent(req.skill_id, summarize_package(preview["files"]))
        _require_digest(req.digest)
        result = install_skill_md(
            req.skill_id,
            req.skill_md,
            req.version,
            req.tier,
            req.install_url,
            expected_digest=req.digest,
        )

    if not result.get("ok"):
        raise _install_failure(result)
    # Record the approval before tools load: the sandbox grants come from it.
    _record_grants(result, result.get("plugin_id") or result.get("skill_id") or req.skill_id)
    load_installed_skill_prompts()  # refresh SKILL_PROMPTS without restart
    if result.get("plugin_id"):
        result["commands"] = _commands_payload(result.get("command_ids") or [])
    else:
        from config import INSTALLED_SKILLS_DIR

        skill_dir = INSTALLED_SKILLS_DIR / req.skill_id
        effective_tier = "Community" if req.install_url else req.tier
        load_skill_tools(req.skill_id, skill_dir, effective_tier)
    return result
```

3f. Replace the `install_local` decorator line with:

```python
@router.post("/api/marketplace/install-local", dependencies=[Depends(verify_csrf)])
```

and replace everything from `result = install_skill_md(` (line 660) to the end of the file with:

```python
    import marketplace.installer as _installer

    if not req.consent:
        preview = _installer.preview_package(local_zip_bytes=zip_bytes)
        if not preview.get("ok"):
            raise HTTPException(
                status_code=400, detail=preview.get("error", "Preview failed")
            )
        return _plain_consent("", summarize_package(preview["files"]))

    _require_digest(req.digest)
    result = install_skill_md(
        skill_id="",
        skill_md="",
        version="1.0",
        tier="Community",
        install_url="",
        _local_zip_bytes=zip_bytes,
        expected_digest=req.digest,
    )
    if not result.get("ok"):
        if result.get("error") == "content_changed":
            raise _install_failure(result)
        raise HTTPException(status_code=400, detail=result.get("error", "Install failed"))

    _record_grants(result, result["skill_id"])
    load_installed_skill_prompts()
    skill_dir = __import__("config").INSTALLED_SKILLS_DIR / result["skill_id"]
    load_skill_tools(result["skill_id"], skill_dir, "Community")
    return result
```

Also update the docstring sentence in `install_local` ("ZIP: extract using the same logic ...") only if it no longer reads true; leave it otherwise.

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `python -m pytest tests/marketplace/test_consent_routes.py -q`
Expected: all pass. If `test_inline_skill_returns_a_summary_and_writes_nothing` fails on the `lines` assertion, print `body["summary"]["lines"]` and check the text `summarize_package` produces for network (Task 1); fix the assertion to match that text, not the code.

- [ ] **Step 5: Update the existing route tests**

5a. `tests/marketplace/test_routes.py`:

- Under `from routes.marketplace import router` add `from security import verify_csrf`, and after `app.include_router(router)` add `app.dependency_overrides[verify_csrf] = lambda: None`.
- Replace every occurrence (replace_all) of `json={"skill_id": "amd-skills", "consent": True}` with `json={"skill_id": "amd-skills", "consent": True, "digest": "d1"}`.
- In `test_install_with_consent_true_installs_and_threads_consented`, after `assert kwargs.get("consented") is True` add `assert kwargs.get("expected_digest") == "d1"`.
- In `test_install_without_consent_is_refused_and_returns_capabilities`, after `mock_install.assert_not_called()` add `assert "digest" in body["summary"]`.
- In `test_install_non_claude_plugins_official_entry_unaffected`, change the payload to `json={"skill_id": "powerbi", "skill_md": "---\nname: x\n---\nbody", "consent": True, "digest": "d1"}` and after `mock_legacy.assert_called_once()` add `assert mock_legacy.call_args.kwargs["expected_digest"] == "d1"`.
- In `test_preview_then_consent_install_real_state_handoff`, after `resolved_ref = body1["resolved_ref"]` add `digest = body1["summary"]["digest"]`, and add `"digest": digest,` to the second call's JSON (next to `"pinned_ref": resolved_ref,`).

5b. `tests/marketplace/test_preview_endpoint.py`:

- Change `_client()` to:

```python
def _client():
    from security import verify_csrf

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_csrf] = lambda: None
    return TestClient(app)
```

- Replace the four install tests (`test_install_standalone_skill_no_consent_routes_to_folder_installer`, `test_install_plugin_bundle_without_consent_returns_consent_required`, `test_install_plugin_bundle_with_consent_calls_url_plugin_installer`, `test_install_orphan_resolution_passed_to_folder_installer`, lines 184-295) with:

```python
_PKG = {"SKILL.md": b"---\nname: docx\ndescription: d\n---\nBody\n"}


def test_install_standalone_skill_no_consent_returns_consent_required(tmp_path, monkeypatch):
    """A GitHub tree URL for a plain skill now asks for approval first and
    installs nothing."""
    import marketplace.installer as inst
    monkeypatch.setattr(inst, "INSTALLED_SKILLS_DIR", tmp_path)

    with (
        patch(
            "marketplace.installer.get_github_url_capabilities",
            return_value=_fake_caps(is_plugin=False, package=_PKG),
        ),
        patch("marketplace.installer._install_github_folder") as fake_inst,
        patch("marketplace.installer.install_github_url") as fake_dispatch,
    ):
        r = _client().post(
            "/api/marketplace/install",
            json={
                "skill_id": "docx",
                "install_url": "https://github.com/foo/bar/tree/main/skills/docx",
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["consent_required"] is True
    assert body["skill_id"] == "docx"
    assert body["summary"]["digest"]
    fake_inst.assert_not_called()
    fake_dispatch.assert_not_called()


def test_install_standalone_skill_with_consent_uses_the_dispatcher(tmp_path, monkeypatch):
    import marketplace.installer as inst
    monkeypatch.setattr(inst, "INSTALLED_SKILLS_DIR", tmp_path)

    with (
        patch(
            "marketplace.installer.install_github_url",
            return_value={"ok": True, "skill_id": "docx", "permissions": {}},
        ) as fake_dispatch,
        patch("routes.marketplace.load_installed_skill_prompts"),
        patch("routes.marketplace.load_skill_tools"),
    ):
        r = _client().post(
            "/api/marketplace/install",
            json={
                "skill_id": "docx",
                "install_url": "https://github.com/foo/bar/tree/main/skills/docx",
                "consent": True,
                "digest": "d1",
            },
        )
    assert r.status_code == 200
    fake_dispatch.assert_called_once_with(
        "https://github.com/foo/bar/tree/main/skills/docx",
        "docx",
        "1.0",
        orphan_resolution=None,
        expected_digest="d1",
    )


def test_install_plugin_bundle_without_consent_returns_consent_required(tmp_path, monkeypatch):
    """A GitHub tree URL with MCP/commands and no consent returns consent_required."""
    import marketplace.installer as inst
    monkeypatch.setattr(inst, "INSTALLED_SKILLS_DIR", tmp_path)

    with patch(
        "marketplace.installer.get_github_url_capabilities",
        return_value=_fake_caps(is_plugin=True, has_mcp=True,
                                mcp_servers=[{"name": "s", "needs_secrets": []}],
                                package=_PKG),
    ):
        r = _client().post(
            "/api/marketplace/install",
            json={
                "skill_id": "my-plugin",
                "install_url": "https://github.com/owner/repo/tree/main/my-plugin",
                "consent": False,
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["consent_required"] is True
    assert body["capabilities"]["has_mcp"] is True
    assert body["summary"]["digest"]


def test_install_plugin_bundle_with_consent_uses_the_dispatcher(tmp_path, monkeypatch):
    """With consent a GitHub tree URL goes through install_github_url, which
    decides between the bundle and the plain-skill installer."""
    import marketplace.installer as inst
    monkeypatch.setattr(inst, "INSTALLED_SKILLS_DIR", tmp_path)

    with (
        patch(
            "marketplace.installer.install_github_url",
            return_value={
                "ok": True,
                "plugin_id": "my-plugin",
                "path": str(tmp_path),
                "skill_ids": ["my-plugin"],
                "command_ids": [],
                "mcp_connection_ids": [],
                "mcp_compatibility_warnings": [],
                "permissions": {},
            },
        ) as fake_inst,
        patch("routes.marketplace.load_installed_skill_prompts"),
    ):
        r = _client().post(
            "/api/marketplace/install",
            json={
                "skill_id": "my-plugin",
                "install_url": "https://github.com/owner/repo/tree/main/my-plugin",
                "consent": True,
                "digest": "d1",
            },
        )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    fake_inst.assert_called_once_with(
        "https://github.com/owner/repo/tree/main/my-plugin",
        "my-plugin",
        "1.0",
        orphan_resolution=None,
        expected_digest="d1",
    )


def test_install_orphan_resolution_passed_to_the_dispatcher(monkeypatch, tmp_path):
    """orphan_resolution is forwarded for standalone skills."""
    import marketplace.installer as inst
    monkeypatch.setattr(inst, "INSTALLED_SKILLS_DIR", tmp_path)
    captured = {}

    def fake_install(install_url, skill_id, version="1.0", orphan_resolution=None, expected_digest=""):
        captured["orphan_resolution"] = orphan_resolution
        return {"ok": True, "skill_id": skill_id, "permissions": {}}

    with (
        patch("marketplace.installer.install_github_url", side_effect=fake_install),
        patch("routes.marketplace.load_installed_skill_prompts"),
        patch("routes.marketplace.load_skill_tools"),
    ):
        resp = _client().post(
            "/api/marketplace/install",
            json={
                "skill_id": "foo",
                "install_url": "https://github.com/owner/repo/tree/main/skills/foo",
                "orphan_resolution": "delete",
                "consent": True,
                "digest": "d1",
            },
        )
    assert resp.status_code == 200
    assert captured["orphan_resolution"] == "delete"
```

5c. `tests/marketplace/test_installer.py`: add this helper above the `# /api/marketplace/install-local route` section (after the heading comment block):

```python
def _route_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes.marketplace import router
    from security import verify_csrf

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_csrf] = lambda: None
    return TestClient(app)
```

In `test_install_local_route_rejects_invalid_kind` and `test_install_local_route_rejects_non_zip_bytes`, replace the five lines that import `TestClient`, `FastAPI`, `router` and build `app`/`client` with `client = _route_client()`.

Replace `test_install_local_route_zip` and `test_install_local_route_folder` with:

```python
def test_install_local_route_zip(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    monkeypatch.setattr("marketplace.installer.PLUGINS_DIR", tmp_path / "plugins")
    import importlib
    import marketplace.installer as _inst
    importlib.reload(_inst)

    from unittest.mock import patch

    client = _route_client()
    zip_bytes = _make_zip({
        "local-skill/SKILL.md": "---\nname: Local Skill\n---\n# Local\nDo it.",
    })
    b64 = _base64.b64encode(zip_bytes).decode()
    payload = {"kind": "zip", "name": "local-skill.zip", "b64": b64}

    with (
        patch("routes.marketplace.load_installed_skill_prompts"),
        patch("routes.marketplace.load_skill_tools"),
        patch("routes.marketplace.install_skill_md", wraps=_inst.install_skill_md),
    ):
        first = client.post("/api/marketplace/install-local", json=payload)
        assert first.status_code == 200, first.text
        assert first.json()["consent_required"] is True
        assert not (_inst.INSTALLED_SKILLS_DIR / "local-skill").exists()
        resp = client.post(
            "/api/marketplace/install-local",
            json={**payload, "consent": True, "digest": first.json()["summary"]["digest"]},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    assert resp.json()["skill_id"] == "local-skill"


def test_install_local_route_folder(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    monkeypatch.setattr("marketplace.installer.PLUGINS_DIR", tmp_path / "plugins")
    import importlib
    import marketplace.installer as _inst
    importlib.reload(_inst)

    from unittest.mock import patch

    client = _route_client()
    files = [
        {"path": "SKILL.md", "b64": _base64.b64encode(b"---\nname: Folder Skill\n---\n# Folder\nDo it.").decode()},
        {"path": "tools.py", "b64": _base64.b64encode(b"TOOL_DEFS = []").decode()},
    ]
    payload = {"kind": "folder", "name": "my-folder", "files": files}

    with (
        patch("routes.marketplace.load_installed_skill_prompts"),
        patch("routes.marketplace.load_skill_tools"),
        patch("routes.marketplace.install_skill_md", wraps=_inst.install_skill_md),
    ):
        first = client.post("/api/marketplace/install-local", json=payload)
        assert first.status_code == 200, first.text
        assert first.json()["summary"]["has_tools"] is True
        resp = client.post(
            "/api/marketplace/install-local",
            json={**payload, "consent": True, "digest": first.json()["summary"]["digest"]},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    assert resp.json()["skill_id"] == "folder-skill"
```

- [ ] **Step 6: Run the marketplace suite**

Run: `python -m pytest tests/marketplace -q`
Expected: everything passes except the 2 known `httpserver` errors in `tests/marketplace/test_installer.py` (no `httpserver` fixture). Any other failure is a test that posts to an install route: give it the CSRF override (as above) or, for `consent=True` requests, a `"digest"` value.

- [ ] **Step 7: Commit**

```bash
git add web/routes/marketplace.py tests/marketplace/test_consent_routes.py tests/marketplace/test_routes.py tests/marketplace/test_preview_endpoint.py tests/marketplace/test_installer.py
git commit -m "feat: marketplace install routes ask for approval on every path, bind it to a content digest, require CSRF and record the approved permissions"
```

### Task 5: Hooks run in the OS sandbox

`fire_event` stops using `subprocess.run(shell=True)` and runs each hook command through `run_in_sandbox`. A hook that cannot be started in the sandbox blocks the send (fail closed). Disabled skills are skipped.

**Files:**
- Modify: `web/hooks/executor.py` (whole file)
- Modify: `tests/hooks/test_hooks_executor.py` (rewrite lines 1-158 and 186-243; keep lines 160-183 unchanged)
- Create: `tests/hooks/test_hooks_sandboxed.py`

**Interfaces:**
- Consumes (Task 2): `marketplace.sandbox_launch.run_in_sandbox(skill_id, kind, argv, skill_dir, run_dir, perms, timeout) -> SkillRun(ok, returncode, stdout, stderr, timed_out, error)`, `new_run_dir() -> Path`; `marketplace.state.disabled_ids()`, `approved_permissions(skill_id) -> Permissions`, `skill_dir_for(entry) -> Path`; `marketplace.permissions.Permissions`; fixtures `fake_sandbox`, `make_skill_dir`.
- Produces: `fire_event(event_name, skill_dir, skill_id="", perms=None) -> {"blocked": bool, "reason": str}` (the two new parameters are optional, so existing callers keep working with no grants); `fire_all_skill_hooks(event_name)` unchanged signature. `_BLOCKED_ENV_VARS` and `_safe_env` are deleted: the sandbox environment comes from `sandbox.build_env`, which never carries API keys.

- [ ] **Step 1: Rewrite `tests/hooks/test_hooks_executor.py`**

Replace lines 1-158 (everything above the `from unittest.mock import patch` line) with:

```python
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "web"))

import json
from pathlib import Path

import sandbox


def _hooks(make_skill_dir, hooks: list[dict]) -> Path:
    return make_skill_dir({"hooks.json": json.dumps({"hooks": hooks})})


def _result(returncode=0, stdout="", stderr="", timed_out=False):
    return sandbox.SandboxResult(returncode=returncode, stdout=stdout, stderr=stderr, timed_out=timed_out)


def test_fire_hook_allows_on_exit_0(make_skill_dir, fake_sandbox):
    skill = _hooks(make_skill_dir, [{"event": "PreToolUse", "command": "exit 0"}])

    from hooks.executor import fire_event

    assert fire_event("PreToolUse", skill)["blocked"] is False
    assert len(fake_sandbox.requests) == 1


def test_fire_hook_blocks_on_nonzero_exit_and_reports_stderr(make_skill_dir, fake_sandbox):
    skill = _hooks(make_skill_dir, [{"event": "PreToolUse", "command": "exit 1"}])
    fake_sandbox.result = _result(returncode=1, stderr="needs approval\n")

    from hooks.executor import fire_event

    result = fire_event("PreToolUse", skill)
    assert result["blocked"] is True
    assert result["reason"] == "needs approval"


def test_fire_hook_reason_falls_back_to_stdout_then_exit_code(make_skill_dir, fake_sandbox):
    skill = _hooks(make_skill_dir, [{"event": "PreToolUse", "command": "x"}])

    from hooks.executor import fire_event

    fake_sandbox.result = _result(returncode=2, stdout="from stdout")
    assert fire_event("PreToolUse", skill)["reason"] == "from stdout"
    fake_sandbox.result = _result(returncode=2)
    assert fire_event("PreToolUse", skill)["reason"] == "exit 2"


def test_fire_hook_only_runs_matching_event(make_skill_dir, fake_sandbox):
    skill = _hooks(
        make_skill_dir,
        [
            {"event": "BeforeEmailSend", "command": "exit 1"},
            {"event": "PreToolUse", "command": "exit 0"},
        ],
    )

    from hooks.executor import fire_event

    result = fire_event("PreToolUse", skill)
    assert result["blocked"] is False
    assert len(fake_sandbox.requests) == 1  # only the PreToolUse hook ran


def test_fire_hook_noop_when_no_hooks_json(make_skill_dir, fake_sandbox):
    skill = make_skill_dir({"SKILL.md": "x"})

    from hooks.executor import fire_event

    assert fire_event("PreToolUse", skill)["blocked"] is False
    assert fake_sandbox.requests == []


def test_fire_hook_noop_when_no_matching_event(make_skill_dir, fake_sandbox):
    skill = _hooks(make_skill_dir, [{"event": "AfterAgentComplete", "command": "exit 1"}])

    from hooks.executor import fire_event

    assert fire_event("PreToolUse", skill)["blocked"] is False
    assert fake_sandbox.requests == []


def test_malformed_hooks_json_still_allows(make_skill_dir, fake_sandbox):
    skill = make_skill_dir({"hooks.json": "{not json"})

    from hooks.executor import fire_event

    assert fire_event("BeforeEmailSend", skill)["blocked"] is False


def test_before_email_send_event_constant():
    from hooks.events import (
        BEFORE_EMAIL_SEND,
        BEFORE_TEAMS_MESSAGE,
        BEFORE_SLACK_MESSAGE,
    )

    assert BEFORE_EMAIL_SEND == "BeforeEmailSend"
    assert BEFORE_TEAMS_MESSAGE == "BeforeTeamsMessage"
    assert BEFORE_SLACK_MESSAGE == "BeforeSlackMessage"


def test_fire_hook_fails_closed_when_the_sandbox_cannot_start(make_skill_dir, fake_sandbox):
    """A sandbox failure must block the send, never allow it or run the hook unsandboxed.
    CLAUDE.md: email/Teams/Slack must never auto-send without explicit approval."""
    skill = _hooks(make_skill_dir, [{"event": "BeforeEmailSend", "command": "anything"}])

    from hooks.executor import fire_event

    for exc in (sandbox.SandboxUnavailable("no sandbox"), sandbox.SandboxRunError("boom"), OSError("simulated")):
        fake_sandbox.raises = exc
        result = fire_event("BeforeEmailSend", skill)
        assert result["blocked"] is True
        assert "hook error" in result["reason"]


def test_fire_hook_blocks_on_timeout(make_skill_dir, fake_sandbox):
    """A stuck hook shouldn't be interpreted as approval."""
    skill = _hooks(make_skill_dir, [{"event": "BeforeEmailSend", "command": "sleep 999"}])
    fake_sandbox.result = _result(returncode=-1, timed_out=True)

    from hooks.executor import fire_event

    result = fire_event("BeforeEmailSend", skill)
    assert result["blocked"] is True
    assert "timed out" in result["reason"]
    assert fake_sandbox.requests[0].timeout == 30


def test_fire_hook_environment_has_no_gateway_credentials(make_skill_dir, fake_sandbox, monkeypatch):
    """AMD gateway key, NTID, and gateway URL must NOT be visible to author-supplied
    hook commands. The sandbox environment is built by sandbox.build_env."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "aigator-fake-api-key")
    monkeypatch.setenv("GATEWAY_USER_ID", "aigator-fake-api-key")
    monkeypatch.setenv("LLM_GATEWAY_URL", "https://llm-api.example.com/Anthropic")
    skill = _hooks(make_skill_dir, [{"event": "BeforeEmailSend", "command": "env"}])

    from hooks.executor import fire_event

    fire_event("BeforeEmailSend", skill)
    env = fake_sandbox.requests[0].env
    assert "ANTHROPIC_API_KEY" not in env
    assert "GATEWAY_USER_ID" not in env
    assert "LLM_GATEWAY_URL" not in env
    assert not any("aigator-fake-api-key" in str(v) for v in env.values())

```

Then keep the existing `from unittest.mock import patch` block and the two `test_send_email_*` tests exactly as they are, and replace the two `test_fire_all_skill_hooks_*` tests (lines 186-243) with:

```python
def test_fire_all_skill_hooks_resolves_hooks_json_at_skill_root(tmp_path, monkeypatch, fake_sandbox):
    """Regression: skill_dir passed to fire_event must be the skill root, NOT
    a hooks/ subdirectory — otherwise fire_event resolves hooks.json one level
    too deep and silently no-ops every hook."""
    skill_root = tmp_path / "cache" / "my-marketplace" / "blocker-skill" / "1.0.0"
    skill_root.mkdir(parents=True)
    (skill_root / "hooks.json").write_text(
        json.dumps({"hooks": [{"event": "BeforeEmailSend", "command": "exit 1"}]})
    )
    fake_sandbox.result = _result(returncode=1)

    import config

    monkeypatch.setattr(config, "PLUGINS_DIR", tmp_path)

    from marketplace import installer

    monkeypatch.setattr(
        installer,
        "load_installed",
        lambda: [
            {"id": "blocker-skill", "source": "my-marketplace", "version": "1.0.0"}
        ],
    )

    from hooks.executor import fire_all_skill_hooks

    result = fire_all_skill_hooks("BeforeEmailSend")
    assert result["blocked"] is True, "hooks.json at skill root must be discovered"
    assert fake_sandbox.requests[0].runtime_paths  # the skill folder is readable inside the sandbox


def test_fire_all_skill_hooks_runs_for_plugin_without_tools_py(tmp_path, monkeypatch, fake_sandbox):
    """Regression: a plugin shipping hooks.json without tools.py must still
    have its hooks fired. Iterating INSTALLED_TOOL_MODULES would skip these
    (they're never registered there) and silently bypass a compliance plugin."""
    skill_root = tmp_path / "cache" / "mp" / "hooks-only" / "1.0.0"
    skill_root.mkdir(parents=True)
    (skill_root / "hooks.json").write_text(
        json.dumps({"hooks": [{"event": "BeforeTeamsMessage", "command": "exit 1"}]})
    )
    fake_sandbox.result = _result(returncode=1)
    # Deliberately no tools.py — and no entry in INSTALLED_TOOL_MODULES

    import config, shared

    monkeypatch.setattr(config, "PLUGINS_DIR", tmp_path)
    monkeypatch.setattr(shared, "INSTALLED_TOOL_MODULES", {})

    from marketplace import installer

    monkeypatch.setattr(
        installer,
        "load_installed",
        lambda: [{"id": "hooks-only", "source": "mp", "version": "1.0.0"}],
    )

    from hooks.executor import fire_all_skill_hooks

    result = fire_all_skill_hooks("BeforeTeamsMessage")
    assert result["blocked"] is True, "hooks-only plugins must not be silently skipped"
```

- [ ] **Step 2: Write `tests/hooks/test_hooks_sandboxed.py`**

```python
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "web"))

import json

import pytest

import sandbox
from marketplace import installer, state
from marketplace.permissions import Permissions


def _skill(make_skill_dir, command="exit 0", event="BeforeEmailSend", name="demo"):
    return make_skill_dir({"hooks.json": json.dumps({"hooks": [{"event": event, "command": command}]})}, name)


def test_hook_runs_in_a_throwaway_run_folder_with_no_grants_by_default(make_skill_dir, fake_sandbox):
    skill = _skill(make_skill_dir)

    from hooks.executor import fire_event

    fire_event("BeforeEmailSend", skill, skill_id="demo")
    req = fake_sandbox.requests[0]
    assert req.network is False
    assert list(req.read_paths) == [] and list(req.write_paths) == []
    assert req.cwd != skill                      # the sandbox makes cwd writable, so never the skill folder
    assert skill.resolve() in [p.resolve() for p in req.runtime_paths]
    assert req.argv[-1] == "exit 0"              # the author's command is one argument to the shell


def test_hook_argv_uses_the_platform_shell(make_skill_dir, fake_sandbox):
    skill = _skill(make_skill_dir, "echo hi")

    from hooks.executor import fire_event

    fire_event("BeforeEmailSend", skill)
    argv = fake_sandbox.requests[0].argv
    if os.name == "nt":
        assert argv[0].lower().endswith("cmd.exe") and argv[1] == "/c"
    else:
        assert argv[:2] == ["/bin/sh", "-c"]
    assert argv[-1] == "echo hi"


def test_approved_permissions_widen_exactly_the_declared_access(make_skill_dir, fake_sandbox, tmp_path):
    skill = _skill(make_skill_dir)
    docs = tmp_path / "reports"
    docs.mkdir()
    perms = Permissions(filesystem=(str(docs),), network=("api.example.com",))

    from hooks.executor import fire_event

    fire_event("BeforeEmailSend", skill, skill_id="demo", perms=perms)
    req = fake_sandbox.requests[0]
    assert req.network is True
    assert [p.resolve() for p in req.read_paths] == [docs.resolve()]
    assert list(req.write_paths) == []


def test_a_declared_secrets_path_is_not_granted(make_skill_dir, fake_sandbox):
    from pathlib import Path

    skill = _skill(make_skill_dir)
    secrets = Path.home() / ".ssh"
    perms = Permissions(filesystem=(str(secrets),))

    from hooks.executor import fire_event

    fire_event("BeforeEmailSend", skill, skill_id="demo", perms=perms)
    granted = [p.resolve() for p in fake_sandbox.requests[0].read_paths]
    assert secrets.resolve() not in granted


def test_fire_all_skill_hooks_passes_the_approved_grant_for_each_skill(make_skill_dir, fake_sandbox, monkeypatch):
    skill = _skill(make_skill_dir, name="granted")
    installer.save_installed([{"id": "granted", "version": "1.0", "source": "mp"}])
    state.record_approval("granted", Permissions(network=("api.example.com",)).to_dict())
    monkeypatch.setattr(state, "skill_dir_for", lambda entry: skill)

    from hooks.executor import fire_all_skill_hooks

    assert fire_all_skill_hooks("BeforeEmailSend")["blocked"] is False
    assert fake_sandbox.requests[0].network is True


def test_a_legacy_skill_with_no_recorded_approval_gets_no_grants(make_skill_dir, fake_sandbox, monkeypatch):
    skill = _skill(make_skill_dir, name="legacy")
    installer.save_installed([{"id": "legacy", "version": "1.0"}])
    monkeypatch.setattr(state, "skill_dir_for", lambda entry: skill)

    from hooks.executor import fire_all_skill_hooks

    fire_all_skill_hooks("BeforeEmailSend")
    req = fake_sandbox.requests[0]
    assert req.network is False and list(req.read_paths) == []


def test_a_disabled_skills_hooks_do_not_run(make_skill_dir, fake_sandbox, monkeypatch):
    skill = _skill(make_skill_dir, name="off")
    installer.save_installed([{"id": "off", "version": "1.0", "disabled": True}])
    monkeypatch.setattr(state, "skill_dir_for", lambda entry: skill)

    from hooks.executor import fire_all_skill_hooks

    assert fire_all_skill_hooks("BeforeEmailSend")["blocked"] is False
    assert fake_sandbox.requests == []


def test_the_run_folder_is_removed_after_the_hook(make_skill_dir, fake_sandbox):
    skill = _skill(make_skill_dir)

    from hooks.executor import fire_event

    fire_event("BeforeEmailSend", skill)
    assert not fake_sandbox.requests[0].cwd.exists()


needs_sandbox = pytest.mark.skipif(
    sandbox.sandbox_level() != "enforced", reason="OS sandbox is not enforced on this machine"
)


@needs_sandbox
def test_real_sandbox_exit_codes_decide_the_gate(make_skill_dir):
    from hooks.executor import fire_event

    assert fire_event("BeforeEmailSend", _skill(make_skill_dir, "exit 0", name="ok"), skill_id="ok")["blocked"] is False
    blocked = fire_event("BeforeEmailSend", _skill(make_skill_dir, "exit 3", name="no"), skill_id="no")
    assert blocked["blocked"] is True


@needs_sandbox
def test_real_sandbox_hook_cannot_write_into_the_skill_folder(make_skill_dir):
    skill = make_skill_dir({}, name="writer")
    target = skill / "pwned.txt"
    (skill / "hooks.json").write_text(
        json.dumps({"hooks": [{"event": "BeforeEmailSend", "command": f'echo x > "{target}"'}]})
    )

    from hooks.executor import fire_event

    result = fire_event("BeforeEmailSend", skill, skill_id="writer")
    assert result["blocked"] is True
    assert not target.exists()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/hooks/test_hooks_executor.py tests/hooks/test_hooks_sandboxed.py -q`
Expected: FAIL (the old executor still calls `subprocess.run`, `fire_event` has no `skill_id` parameter).

- [ ] **Step 4: Replace `web/hooks/executor.py`**

```python
"""Fire hook shell commands for a given event. Exit code 0 = allow, non-zero = block.

Hook commands are author-supplied (untrusted), so each one runs in the OS
sandbox (see marketplace.sandbox_launch): throwaway working folder, read access
to the skill folder and the folders the user approved, no write access outside
the throwaway folder, network only when the user approved a network declaration,
and an environment with no API keys. If the sandbox cannot start the hook
blocks the send.
"""

import json
import logging
import os
import shutil
from pathlib import Path

from marketplace.permissions import Permissions

logger = logging.getLogger(__name__)

_HOOK_TIMEOUT = 30


def _hook_argv(command: str) -> list[str]:
    if os.name == "nt":
        comspec = os.environ.get("COMSPEC") or os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cmd.exe"
        )
        return [comspec, "/c", command]
    return ["/bin/sh", "-c", command]


def fire_event(
    event_name: str,
    skill_dir: Path,
    skill_id: str = "",
    perms: Permissions | None = None,
) -> dict:
    """Fire all hooks matching event_name in skill_dir/hooks.json.

    Returns {"blocked": bool, "reason": str}.
    blocked=True if any hook exits with a non-zero code, times out, or cannot be
    started in the sandbox. `perms` is what the user approved at install; with
    none, the hook gets no extra folders and no network.
    """
    from marketplace.sandbox_launch import new_run_dir, run_in_sandbox

    hooks_file = skill_dir / "hooks.json"
    if not hooks_file.exists():
        return {"blocked": False, "reason": ""}

    try:
        config = json.loads(hooks_file.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Malformed hooks.json in %s: %s", skill_dir, exc)
        return {"blocked": False, "reason": ""}

    perms = perms or Permissions()
    label = skill_id or skill_dir.name

    for hook in config.get("hooks", []):
        if hook.get("event") != event_name:
            continue
        command = hook.get("command", "")
        if not command:
            continue
        run_dir = None
        try:
            run_dir = new_run_dir()
            run = run_in_sandbox(
                label, "hook", _hook_argv(command), skill_dir, run_dir, perms, _HOOK_TIMEOUT
            )
            if not run.ok:
                logger.warning("Hook could not start for event %s: %s", event_name, run.error)
                return {"blocked": True, "reason": f"hook error: {run.error}"}
            if run.timed_out:
                logger.warning("Hook timed out for event %s in %s", event_name, skill_dir)
                return {"blocked": True, "reason": "hook timed out"}
            if run.returncode != 0:
                reason = (
                    run.stderr.strip()
                    or run.stdout.strip()
                    or f"exit {run.returncode}"
                )
                logger.info("Hook blocked event %s: %s", event_name, reason)
                return {"blocked": True, "reason": reason}
        except Exception as exc:
            # Fail closed: if we can't determine whether the hook would allow,
            # treat as a block. For send-style events (email/Teams/Slack) this
            # is the safe default — better to surface an error than silently send.
            logger.warning("Hook error for event %s: %s", event_name, exc)
            return {"blocked": True, "reason": f"hook error: {exc}"}
        finally:
            if run_dir is not None:
                shutil.rmtree(run_dir, ignore_errors=True)

    return {"blocked": False, "reason": ""}


def fire_all_skill_hooks(event_name: str) -> dict:
    """Fire event across all installed plugin skill directories.

    Iterates the installed-skills index — NOT `INSTALLED_TOOL_MODULES` —
    because a plugin can ship `hooks.json` with no `tools.py` (MCP-only or
    CLI-shim plugin) and would otherwise be invisible to the hook gate,
    silently bypassing a compliance-enforcement plugin. Disabled skills are
    skipped.

    Returns {"blocked": True, "reason": ...} if any hook blocks, else
    {"blocked": False, "reason": ""}.
    """
    try:
        from marketplace import state
        from marketplace.installer import load_installed
    except ImportError as exc:
        # Surface real import bugs in the log instead of silently bypassing
        # every hook — a typo in config.py shouldn't disarm the gate.
        logger.error("fire_all_skill_hooks: import failure (hooks not fired): %s", exc)
        return {"blocked": False, "reason": ""}

    disabled = state.disabled_ids()
    for entry in load_installed():
        skill_id = entry.get("id")
        if not skill_id or skill_id in disabled:
            continue
        # NOTE: fire_event appends `hooks.json` to skill_dir, so we pass the
        # skill ROOT here — adding a `/hooks` segment would yield .../hooks/hooks.json
        # and silently miss every file.
        result = fire_event(
            event_name,
            state.skill_dir_for(entry),
            skill_id=skill_id,
            perms=state.approved_permissions(skill_id),
        )
        if result["blocked"]:
            return result

    return {"blocked": False, "reason": ""}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/hooks -q`
Expected: all pass; the two `needs_sandbox` tests are skipped when the OS sandbox is not enforced on the machine (report that if so). If `test_fire_all_skill_hooks_*` in `test_hooks_executor.py` fail with the sandbox refusing the folder, the cause is `tmp_path` sitting under the redirected HOME: build the skill folder with `make_skill_dir` instead and monkeypatch `state.skill_dir_for` as the new tests do.

- [ ] **Step 6: Run the email and Teams suites that fire hooks**

Run: `python -m pytest tests/test_email_tools.py tests/hooks -q -k "hook or send"` (if `tests/test_email_tools.py` does not exist, run `python -m pytest tests -q -k "BeforeEmailSend or fire_all_skill_hooks"`).
Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add web/hooks/executor.py tests/hooks/test_hooks_executor.py tests/hooks/test_hooks_sandboxed.py
git commit -m "feat: marketplace hook commands run in the OS sandbox with only the approved access and fail closed"
```
### Task 6: Run `tools.py` in the sandbox, one call per process

After this task the app process never imports a marketplace skill's `tools.py`. Each tool call (and the one-time read of the tool list at install/Enable) runs `tools.py` in the OS sandbox with only the approved access. Outbound destinations are logged on every run.

**Files:**
- Create: `web/marketplace/tool_runner_source.py`, `web/marketplace/tool_sandbox.py`
- Modify: `web/marketplace/loader.py` (imports, top of `load_skill_tools`, the in-process import block, the module eviction in `unload_skill_tools`), `tests/conftest.py` (append one fixture)
- Test: `tests/marketplace/test_tool_runner.py` (new), `tests/marketplace/test_tool_sandbox.py` (new), `tests/marketplace/test_loader.py` (rewritten)

**Interfaces:**
- Consumes (Task 2): `skill_audit.MARKER`, `skill_audit.extract_outbound(stderr) -> (list[str], str)`, `skill_audit.log_outbound(skill_id, destinations)`; `sandbox_launch.new_run_dir() -> Path`, `sandbox_launch.run_in_sandbox(skill_id, kind, argv, skill_dir, run_dir, perms, timeout) -> SkillRun(ok, returncode, stdout, stderr, timed_out, error)`; `state.is_disabled(skill_id)`, `state.approved_permissions(skill_id) -> Permissions`; fixtures `fake_sandbox` and `make_skill_dir`; `skills.code_runner.tools._python_command(script_path)`; `config.load_config()`.
- Produces:
  - `tool_runner_source.RUNNER_SOURCE: str`, `RUNNER_NAME`, `ARGS_NAME`, `RESULT_NAME` (file names inside the run folder).
  - `tool_sandbox.describe_skill_tools(skill_id, skill_dir, perms) -> {"ok": True, "defs": list[dict], "status": dict[str, str]} | {"ok": False, "error": str}`.
  - `tool_sandbox.call_skill_tool(skill_id, skill_dir, name, args, tier) -> dict` (a tool error is `{"error": str}`, the shape `execute_tool` already expects).
  - `tool_sandbox.make_stub(skill_id, skill_dir, name, tier) -> Callable[[dict], dict]`: a sync function with one parameter annotated `dict`, so `execute_tool` calls `fn(inputs)` on a worker thread.
  - `loader.load_skill_tools` refuses a disabled skill (`{"ok": False, "error": "skill is disabled"}`) and registers stubs in `shared.TOOL_DISPATCH` instead of imported handlers.
  - conftest fixture `passthrough_sandbox` (a `fake_sandbox` whose handler really runs the argv, without confinement; for tests only).

How the runner works (so the tests make sense): `tool_sandbox` writes `RUNNER_SOURCE` into a fresh run folder, then launches `python runner.py <describe|call> <skill_dir> [tool_name]` in the sandbox with the run folder as the working folder. The runner installs an audit hook that prints `AIGATOR-SKILL-OUTBOUND host:port` lines to stderr for every `socket.connect` / `socket.getaddrinfo`, imports `tools.py`, and writes its answer to `_aigator_result.json` in the run folder (a file, so anything the tool prints cannot corrupt the answer). Arguments arrive in `_aigator_args.json`.

- [ ] **Step 1: Append the `passthrough_sandbox` fixture to `tests/conftest.py`**

```python
@pytest.fixture
def passthrough_sandbox(fake_sandbox):
    """fake_sandbox that really runs the command, unconfined. Tests only: it checks the runner and wrapper logic, not confinement."""
    import os
    import subprocess

    import sandbox

    def run(request):
        env = {**os.environ, **request.env}
        env.pop("PYTHONPATH", None)
        try:
            proc = subprocess.run(
                list(request.argv), cwd=str(request.cwd), env=env, capture_output=True,
                text=True, encoding="utf-8", timeout=request.timeout, stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            return sandbox.SandboxResult(returncode=-1, stdout="", stderr="", timed_out=True)
        return sandbox.SandboxResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr, timed_out=False)

    fake_sandbox.handler = run
    return fake_sandbox
```

- [ ] **Step 2: Write the runner tests (they run the runner script directly, no sandbox)**

`tests/marketplace/test_tool_runner.py`:

```python
import json
import subprocess
import sys

from marketplace import skill_audit
from marketplace.tool_runner_source import ARGS_NAME, RESULT_NAME, RUNNER_NAME, RUNNER_SOURCE

HEADER = (
    'TOOL_DEFS = [{"name": "t", "description": "d", "input_schema": {"type": "object", "properties": {}}}]\n'
    'TOOL_STATUS = {"t": "Working"}\n'
)


def _run(tmp_path, tools_py, mode, name="", args=None, extra_files=None):
    skill = tmp_path / "skill"
    skill.mkdir(exist_ok=True)
    (skill / "tools.py").write_text(tools_py, encoding="utf-8")
    for rel, content in (extra_files or {}).items():
        (skill / rel).write_text(content, encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir(exist_ok=True)
    (run_dir / RUNNER_NAME).write_text(RUNNER_SOURCE, encoding="utf-8")
    argv = [sys.executable, "-X", "utf8", str(run_dir / RUNNER_NAME), mode, str(skill)]
    if name:
        argv.append(name)
        (run_dir / ARGS_NAME).write_text(json.dumps(args or {}), encoding="utf-8")
    proc = subprocess.run(argv, cwd=run_dir, capture_output=True, text=True, encoding="utf-8", timeout=60)
    result_file = run_dir / RESULT_NAME
    data = json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else None
    return proc, data


def test_describe_returns_defs_and_status(tmp_path):
    _, data = _run(tmp_path, HEADER + "def t(): return {}\nTOOL_HANDLERS = {'t': t}\n", "describe")
    assert data["ok"] is True
    assert data["defs"][0]["name"] == "t"
    assert data["status"] == {"t": "Working"}


def test_describe_flags_a_contract_mismatch(tmp_path):
    _, data = _run(tmp_path, HEADER + "TOOL_HANDLERS = {}\n", "describe")
    assert data["ok"] is False
    assert "tool contract mismatch" in data["error"]


def test_describe_reports_an_import_time_failure(tmp_path):
    _, data = _run(tmp_path, "raise RuntimeError('boom at import')\n", "describe")
    assert data["ok"] is False
    assert "boom at import" in data["error"]


def test_describe_reports_a_syntax_error(tmp_path):
    _, data = _run(tmp_path, "this is not python !!!\n", "describe")
    assert data["ok"] is False


def test_call_passes_keyword_arguments(tmp_path):
    src = HEADER + "def t(a, b=2): return {'sum': a + b}\nTOOL_HANDLERS = {'t': t}\n"
    _, data = _run(tmp_path, src, "call", "t", {"a": 5})
    assert data == {"ok": True, "result": {"sum": 7}}


def test_call_drops_unknown_arguments_and_context_id(tmp_path):
    src = HEADER + "def t(a): return {'a': a}\nTOOL_HANDLERS = {'t': t}\n"
    _, data = _run(tmp_path, src, "call", "t", {"a": 1, "extra": 2, "_context_id": "tab-1"})
    assert data["result"] == {"a": 1}


def test_call_gives_a_var_keyword_handler_everything_except_context_id(tmp_path):
    src = HEADER + "def t(**kw): return {'kw': sorted(kw)}\nTOOL_HANDLERS = {'t': t}\n"
    _, data = _run(tmp_path, src, "call", "t", {"a": 1, "b": 2, "_context_id": "x"})
    assert data["result"] == {"kw": ["a", "b"]}


def test_call_passes_the_whole_dict_to_a_single_dict_handler(tmp_path):
    src = HEADER + "def t(args: dict): return {'got': args}\nTOOL_HANDLERS = {'t': t}\n"
    _, data = _run(tmp_path, src, "call", "t", {"x": 1})
    assert data["result"] == {"got": {"x": 1}}


def test_call_awaits_an_async_handler(tmp_path):
    src = HEADER + "async def t(a): return {'a': a}\nTOOL_HANDLERS = {'t': t}\n"
    _, data = _run(tmp_path, src, "call", "t", {"a": 3})
    assert data["result"] == {"a": 3}


def test_call_reports_a_handler_exception(tmp_path):
    src = HEADER + "def t(): raise ValueError('bad input')\nTOOL_HANDLERS = {'t': t}\n"
    _, data = _run(tmp_path, src, "call", "t")
    assert data["ok"] is False and "bad input" in data["error"]


def test_call_reports_a_missing_required_argument(tmp_path):
    src = HEADER + "def t(a): return {}\nTOOL_HANDLERS = {'t': t}\n"
    _, data = _run(tmp_path, src, "call", "t", {})
    assert data["ok"] is False


def test_call_rejects_a_non_dict_result(tmp_path):
    src = HEADER + "def t(): return 'text'\nTOOL_HANDLERS = {'t': t}\n"
    _, data = _run(tmp_path, src, "call", "t")
    assert data["ok"] is False


def test_call_unknown_tool(tmp_path):
    src = HEADER + "def t(): return {}\nTOOL_HANDLERS = {'t': t}\n"
    _, data = _run(tmp_path, src, "call", "nope")
    assert data["ok"] is False and "nope" in data["error"]


def test_printing_does_not_corrupt_the_answer(tmp_path):
    src = HEADER + "def t():\n    print('noise on stdout')\n    return {'ok': True}\nTOOL_HANDLERS = {'t': t}\n"
    _, data = _run(tmp_path, src, "call", "t")
    assert data["result"] == {"ok": True}


def test_a_helper_module_next_to_tools_py_imports(tmp_path):
    src = HEADER + "import helper\ndef t(): return {'v': helper.VALUE}\nTOOL_HANDLERS = {'t': t}\n"
    _, data = _run(tmp_path, src, "call", "t", extra_files={"helper.py": "VALUE = 41\n"})
    assert data["result"] == {"v": 41}


def test_outbound_lookups_and_connections_are_reported_on_stderr(tmp_path):
    src = HEADER + (
        "import socket\n"
        "def t():\n"
        "    try:\n"
        "        socket.getaddrinfo('example.invalid', 443)\n"
        "    except OSError:\n"
        "        pass\n"
        "    return {}\n"
        "TOOL_HANDLERS = {'t': t}\n"
    )
    proc, data = _run(tmp_path, src, "call", "t")
    assert data["ok"] is True
    dests, _ = skill_audit.extract_outbound(proc.stderr)
    assert "example.invalid:443" in dests
```

- [ ] **Step 3: Write the wrapper tests**

`tests/marketplace/test_tool_sandbox.py`:

```python
import inspect
import json
import logging
import time
from pathlib import Path

import pytest

import config
import sandbox
from marketplace import installer, state
from marketplace import tool_sandbox as T
from marketplace.permissions import Permissions

NOOP = (
    'TOOL_DEFS = [{"name": "noop", "description": "d", "input_schema": {"type": "object", "properties": {}}}]\n'
    'TOOL_STATUS = {"noop": "Working"}\n'
    "def noop():\n"
    "    return {'ok': True}\n"
    "TOOL_HANDLERS = {'noop': noop}\n"
)

needs_sandbox = pytest.mark.skipif(
    sandbox.sandbox_level() != "enforced", reason="OS sandbox is not enforced on this machine"
)


@pytest.fixture(autouse=True)
def _index():
    installer.save_installed([{"id": "demo", "version": "1.0", "tier": "community"}])


def _outputs():
    root = Path(config.OUTPUTS_DIR)
    return set(root.iterdir()) if root.exists() else set()


def test_describe_returns_the_tool_list(passthrough_sandbox, make_skill_dir):
    skill = make_skill_dir({"tools.py": NOOP})
    data = T.describe_skill_tools("demo", skill, Permissions())
    assert data["ok"] is True
    assert [d["name"] for d in data["defs"]] == ["noop"]
    assert data["status"] == {"noop": "Working"}


def test_call_returns_the_tools_result(passthrough_sandbox, make_skill_dir):
    skill = make_skill_dir({"tools.py": NOOP})
    assert T.call_skill_tool("demo", skill, "noop", {}, "Community") == {"ok": True}


def test_a_tool_that_raises_becomes_a_tool_error(passthrough_sandbox, make_skill_dir):
    src = NOOP.replace("return {'ok': True}", "raise ValueError('bad input')")
    skill = make_skill_dir({"tools.py": src})
    result = T.call_skill_tool("demo", skill, "noop", {}, "Community")
    assert "bad input" in result["error"]


def test_a_broken_tools_py_is_a_describe_failure(passthrough_sandbox, make_skill_dir):
    skill = make_skill_dir({"tools.py": "this is not python !!!\n"})
    data = T.describe_skill_tools("demo", skill, Permissions())
    assert data["ok"] is False and data["error"]


def test_a_tools_py_that_imports_the_apps_modules_gets_a_clear_message(passthrough_sandbox, make_skill_dir):
    skill = make_skill_dir({"tools.py": "import shared\n" + NOOP})
    data = T.describe_skill_tools("demo", skill, Permissions())
    assert data["ok"] is False
    assert "cannot reach" in data["error"]


def test_sandbox_unavailable_means_no_tool_result_and_nothing_runs(fake_sandbox, make_skill_dir):
    skill = make_skill_dir({"tools.py": NOOP})
    fake_sandbox.raises = sandbox.SandboxUnavailable("no sandbox")
    result = T.call_skill_tool("demo", skill, "noop", {}, "Community")
    assert result["error"]
    assert T.describe_skill_tools("demo", skill, Permissions())["ok"] is False


def test_a_timeout_is_a_tool_error(passthrough_sandbox, make_skill_dir, monkeypatch):
    monkeypatch.setattr(T, "_timeout_for", lambda tier: 1)
    src = "import time\n" + NOOP.replace("return {'ok': True}", "time.sleep(5)\n    return {}")
    skill = make_skill_dir({"tools.py": src})
    result = T.call_skill_tool("demo", skill, "noop", {}, "Community")
    assert "timed out after 1 seconds" in result["error"]


def test_timeouts_come_from_config_by_tier(monkeypatch):
    monkeypatch.setattr(config, "load_config", lambda: {"code_runner_timeout_community": 7})
    assert T._timeout_for("Community") == 7
    assert T._timeout_for("Verified") == 60


def test_the_run_folder_is_removed_after_every_call(passthrough_sandbox, make_skill_dir):
    skill = make_skill_dir({"tools.py": NOOP})
    before = _outputs()
    T.call_skill_tool("demo", skill, "noop", {}, "Community")
    T.describe_skill_tools("demo", skill, Permissions())
    passthrough_sandbox.raises = sandbox.SandboxRunError("boom")
    T.call_skill_tool("demo", skill, "noop", {}, "Community")
    assert _outputs() == before


def test_the_approved_permissions_decide_network(passthrough_sandbox, make_skill_dir):
    skill = make_skill_dir({"tools.py": NOOP})
    T.call_skill_tool("demo", skill, "noop", {}, "Community")
    state.record_approval("demo", Permissions(network=("api.example.com",)).to_dict())
    T.call_skill_tool("demo", skill, "noop", {}, "Community")
    assert [r.network for r in passthrough_sandbox.requests] == [False, True]


def test_describe_uses_the_permissions_it_is_given(passthrough_sandbox, make_skill_dir):
    skill = make_skill_dir({"tools.py": NOOP})
    T.describe_skill_tools("demo", skill, Permissions(network=("a.example.com",)))
    assert passthrough_sandbox.requests[0].network is True


def test_a_disabled_skill_is_refused_without_launching(fake_sandbox, make_skill_dir):
    skill = make_skill_dir({"tools.py": NOOP})
    state.set_disabled("demo", True)
    assert T.call_skill_tool("demo", skill, "noop", {}, "Community") == {"error": "skill is disabled"}
    assert fake_sandbox.requests == []


def test_outbound_destinations_are_logged(passthrough_sandbox, make_skill_dir, caplog):
    src = (
        "import socket\n"
        + NOOP.replace(
            "return {'ok': True}",
            "try:\n        socket.getaddrinfo('example.invalid', 443)\n    except OSError:\n        pass\n    return {'ok': True}",
        )
    )
    skill = make_skill_dir({"tools.py": src})
    with caplog.at_level(logging.INFO, logger="aigator.skill_audit"):
        result = T.call_skill_tool("demo", skill, "noop", {}, "Community")
    assert result == {"ok": True}
    assert "skill-outbound skill=demo dest=example.invalid:443" in caplog.text


def test_every_run_is_logged_as_a_launch(passthrough_sandbox, make_skill_dir, caplog):
    skill = make_skill_dir({"tools.py": NOOP})
    with caplog.at_level(logging.INFO, logger="aigator.skill_audit"):
        T.call_skill_tool("demo", skill, "noop", {}, "Community")
    assert "skill-launch skill=demo kind=tool" in caplog.text


def test_the_stub_is_a_single_dict_argument_function(make_skill_dir):
    stub = T.make_stub("demo", make_skill_dir({"tools.py": NOOP}), "noop", "Community")
    params = list(inspect.signature(stub).parameters.values())
    assert len(params) == 1 and params[0].annotation in (dict, "dict")
    assert not inspect.iscoroutinefunction(stub)


def test_the_stub_calls_the_tool(passthrough_sandbox, make_skill_dir):
    stub = T.make_stub("demo", make_skill_dir({"tools.py": NOOP}), "noop", "Community")
    assert stub({}) == {"ok": True}


@needs_sandbox
def test_real_sandbox_noop_call_stays_under_two_seconds(make_skill_dir):
    skill = make_skill_dir({"tools.py": NOOP})
    started = time.monotonic()
    result = T.call_skill_tool("demo", skill, "noop", {}, "Community")
    elapsed = time.monotonic() - started
    assert result == {"ok": True}
    assert elapsed < 2.0, f"a no-op sandboxed tool call took {elapsed:.2f}s"


@needs_sandbox
def test_real_sandbox_tool_cannot_read_a_file_it_was_not_granted(make_skill_dir, tmp_path):
    secret = tmp_path / "outside.txt"
    secret.write_text("secret-content", encoding="utf-8")
    src = NOOP.replace("return {'ok': True}", f"return {{'text': open({str(secret)!r}).read()}}")
    skill = make_skill_dir({"tools.py": src})
    result = T.call_skill_tool("demo", skill, "noop", {}, "Community")
    assert "secret-content" not in json.dumps(result)
    assert result.get("error")


@needs_sandbox
def test_real_sandbox_tool_cannot_write_into_its_own_folder(make_skill_dir):
    src = NOOP.replace("return {'ok': True}", "open(__file__ + '.pwned', 'w').write('x')\n    return {'ok': True}")
    skill = make_skill_dir({"tools.py": src})
    result = T.call_skill_tool("demo", skill, "noop", {}, "Community")
    assert result.get("error")
    assert not (skill / "tools.py.pwned").exists()
```

- [ ] **Step 4: Run the new tests to verify they fail**

Run: `python -m pytest tests/marketplace/test_tool_runner.py tests/marketplace/test_tool_sandbox.py -q`
Expected: collection errors (`ModuleNotFoundError: marketplace.tool_runner_source` / `marketplace.tool_sandbox`).

- [ ] **Step 5: Write `web/marketplace/tool_runner_source.py`**

The runner is a string so the app can drop it into each run folder; it must stay pure standard library and must not import anything from the app.

```python
"""The script that runs inside the sandbox and executes a marketplace skill's tools.py."""
from marketplace.skill_audit import MARKER

RUNNER_NAME = "_aigator_tool_runner.py"
ARGS_NAME = "_aigator_args.json"
RESULT_NAME = "_aigator_result.json"

_TEMPLATE = r'''
import asyncio
import importlib.util
import inspect
import json
import os
import sys

MARKER = "@@MARKER@@"
ARGS_FILE = "@@ARGS@@"
RESULT_FILE = "@@RESULT@@"
_seen = set()


def _audit(event, args):
    try:
        if event == "socket.connect":
            address = args[1]
            if not isinstance(address, tuple) or not address:
                return
            dest = str(address[0]) + (":" + str(address[1]) if len(address) > 1 else "")
        elif event == "socket.getaddrinfo":
            dest = str(args[0]) + ":" + str(args[1])
        else:
            return
        if dest in _seen or len(_seen) >= 50:
            return
        _seen.add(dest)
        sys.stderr.write(MARKER + dest.replace("\r", " ").replace("\n", " ") + "\n")
        sys.stderr.flush()
    except Exception:
        pass


sys.addaudithook(_audit)


def _write(obj):
    with open(RESULT_FILE, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, default=str)


def _load(skill_dir):
    sys.dont_write_bytecode = True
    sys.path.insert(0, skill_dir)
    spec = importlib.util.spec_from_file_location("_skill_tools", os.path.join(skill_dir, "tools.py"))
    if spec is None or spec.loader is None:
        raise ImportError("could not build a module spec for tools.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_skill_tools"] = module
    spec.loader.exec_module(module)
    return module


def _contract_issues(module):
    defs = getattr(module, "TOOL_DEFS", [])
    handlers = getattr(module, "TOOL_HANDLERS", {})
    status = getattr(module, "TOOL_STATUS", {})
    names = {d["name"] for d in defs}
    issues = []
    if names - set(handlers):
        issues.append("tools defined but no handler: " + str(sorted(names - set(handlers))))
    if set(handlers) - names:
        issues.append("handlers with no tool definition: " + str(sorted(set(handlers) - names)))
    if names - set(status):
        issues.append("tools missing status message: " + str(sorted(names - set(status))))
    return issues


def _describe(module):
    issues = _contract_issues(module)
    if issues:
        return {"ok": False, "error": "tool contract mismatch (" + "; ".join(issues) + ")"}
    defs = [dict(d) for d in getattr(module, "TOOL_DEFS", [])]
    status = {str(k): str(v) for k, v in getattr(module, "TOOL_STATUS", {}).items()}
    return {"ok": True, "defs": defs, "status": status}


async def _await(value):
    return await value


def _invoke(handler, args):
    params = list(inspect.signature(handler).parameters.values())
    first = params[0] if len(params) == 1 else None
    single_dict = (
        first is not None
        and first.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.POSITIONAL_ONLY)
        and (
            first.annotation in (dict, "dict")
            or (first.annotation is inspect.Parameter.empty and first.default is inspect.Parameter.empty)
        )
    )
    if single_dict:
        result = handler(args)
    else:
        kwargs = {k: v for k, v in args.items() if k != "_context_id"}
        if not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params):
            accepted = {p.name for p in params}
            kwargs = {k: v for k, v in kwargs.items() if k in accepted}
        result = handler(**kwargs)
    if inspect.isawaitable(result):
        result = asyncio.run(_await(result))
    return result


def main():
    mode, skill_dir = sys.argv[1], sys.argv[2]
    try:
        module = _load(skill_dir)
        if mode == "describe":
            _write(_describe(module))
            return
        name = sys.argv[3]
        handler = getattr(module, "TOOL_HANDLERS", {}).get(name)
        if handler is None:
            _write({"ok": False, "error": "unknown tool " + name})
            return
        with open(ARGS_FILE, encoding="utf-8") as fh:
            args = json.load(fh)
        if not isinstance(args, dict):
            args = {}
        result = _invoke(handler, args)
        if not isinstance(result, dict):
            _write({"ok": False, "error": "the tool returned something that is not a JSON object"})
            return
        _write({"ok": True, "result": result})
    except BaseException as exc:
        _write({"ok": False, "error": type(exc).__name__ + ": " + str(exc)[:500]})


main()
'''

RUNNER_SOURCE = (
    _TEMPLATE.replace("@@MARKER@@", MARKER)
    .replace("@@ARGS@@", ARGS_NAME)
    .replace("@@RESULT@@", RESULT_NAME)
)
```

- [ ] **Step 6: Write `web/marketplace/tool_sandbox.py`**

```python
"""Runs a marketplace skill's tools.py inside the OS sandbox, one process per call."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from marketplace import skill_audit, state
from marketplace.permissions import Permissions
from marketplace.sandbox_launch import new_run_dir, run_in_sandbox
from marketplace.tool_runner_source import ARGS_NAME, RESULT_NAME, RUNNER_NAME, RUNNER_SOURCE

DESCRIBE_TIMEOUT = 30
MAX_RESULT_BYTES = 10_000_000
_SHARED_HINT = (
    "This skill's tools import the app's internal modules, which a sandboxed skill cannot reach. "
    "Its tools are unavailable."
)


def _timeout_for(tier: str) -> int:
    from config import load_config

    community = tier == "Community"
    key = "code_runner_timeout_community" if community else "code_runner_timeout_verified"
    return int(load_config().get(key, 30 if community else 60))


def _friendly(message: str) -> str:
    return _SHARED_HINT if "No module named 'shared'" in message else message


def _stopped(stderr: str, returncode: int) -> str:
    lines = [line for line in stderr.strip().splitlines() if line.strip()]
    tail = lines[-1][:300] if lines else ""
    return _friendly(f"The skill's tool stopped without a result (exit {returncode}). {tail}".strip())


def _run(skill_id: str, skill_dir: Path, mode: str, perms: Permissions, timeout: int,
         tool_name: str = "", args: dict | None = None) -> dict:
    from skills.code_runner import tools as cr

    run_dir = new_run_dir()
    try:
        runner = run_dir / RUNNER_NAME
        runner.write_text(RUNNER_SOURCE, encoding="utf-8")
        argv = cr._python_command(runner) + [mode, str(skill_dir)]
        if tool_name:
            argv.append(tool_name)
            (run_dir / ARGS_NAME).write_text(json.dumps(args or {}, default=str), encoding="utf-8")
        run = run_in_sandbox(skill_id, "tool", argv, Path(skill_dir), run_dir, perms, timeout)
        if not run.ok:
            return {"ok": False, "error": run.error}
        destinations, stderr = skill_audit.extract_outbound(run.stderr)
        skill_audit.log_outbound(skill_id, destinations)
        if run.timed_out:
            return {"ok": False, "error": f"The skill's tool timed out after {timeout} seconds."}
        result_file = run_dir / RESULT_NAME
        try:
            if result_file.stat().st_size > MAX_RESULT_BYTES:
                return {"ok": False, "error": "The skill's tool returned more than 10 MB."}
            data = json.loads(result_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"ok": False, "error": _stopped(stderr, run.returncode)}
        if not isinstance(data, dict):
            return {"ok": False, "error": _stopped(stderr, run.returncode)}
        if not data.get("ok"):
            data["error"] = _friendly(str(data.get("error") or "the skill's tool failed"))
        return data
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def describe_skill_tools(skill_id: str, skill_dir: Path, perms: Permissions) -> dict:
    data = _run(skill_id, skill_dir, "describe", perms, DESCRIBE_TIMEOUT)
    if data.get("ok") and not isinstance(data.get("defs"), list):
        return {"ok": False, "error": "The skill's tool list could not be read."}
    return data


def call_skill_tool(skill_id: str, skill_dir: Path, name: str, args: dict, tier: str) -> dict:
    if state.is_disabled(skill_id):
        return {"error": "skill is disabled"}
    data = _run(skill_id, skill_dir, "call", state.approved_permissions(skill_id),
                _timeout_for(tier), name, args)
    if not data.get("ok"):
        return {"error": data.get("error") or "the skill's tool failed"}
    result = data.get("result")
    return result if isinstance(result, dict) else {"error": "the skill's tool returned an unreadable result"}


def make_stub(skill_id: str, skill_dir: Path, name: str, tier: str):
    def stub(args: dict) -> dict:
        return call_skill_tool(skill_id, skill_dir, name, args, tier)

    stub.__name__ = f"{skill_id}__{name}"
    return stub
```

- [ ] **Step 7: Run the new tests to verify they pass**

Run: `python -m pytest tests/marketplace/test_tool_runner.py tests/marketplace/test_tool_sandbox.py -q`
Expected: all pass; the three `needs_sandbox` tests are skipped when the OS sandbox is not enforced (say so in the report). If a runner test fails only on Windows because the child cannot start, the cause is the environment in `passthrough_sandbox`: it already merges `os.environ` under `request.env`, so check the error text first. If a real-sandbox test fails because the AppContainer profile cannot be created under the test's redirected HOME, use the `windows_container` fixture the way `tests/code_runner/test_run_python.py` does for its real-sandbox tests.

- [ ] **Step 8: Rewrite `tests/marketplace/test_loader.py`**

Replace the whole file. The old tests imported `tools.py` into the app process; the new ones check that the app registers stubs and never executes `tools.py` itself.

```python
# tests/marketplace/test_loader.py
import inspect
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "web"))

import pytest
from pathlib import Path

from marketplace import installer, state
from marketplace import tool_sandbox


def _tools_py(tool_name="fake_tool", body="return {'ok': True}"):
    return (
        f'TOOL_DEFS = [{{"name": "{tool_name}", "description": "x", "input_schema": {{"type": "object", "properties": {{}}, "required": []}}}}]\n'
        f'TOOL_STATUS = {{"{tool_name}": "Running..."}}\n'
        f"def _handler(): {body}\n"
        f'TOOL_HANDLERS = {{"{tool_name}": _handler}}\n'
    )


def _described(tool_name="fake_tool"):
    return {
        "ok": True,
        "defs": [{"name": tool_name, "description": "x", "input_schema": {"type": "object", "properties": {}, "required": []}}],
        "status": {tool_name: "Running..."},
    }


@pytest.fixture
def described(monkeypatch):
    """Make describe_skill_tools return a canned answer instead of launching anything."""
    box = {"value": _described(), "calls": []}

    def fake(skill_id, skill_dir, perms):
        box["calls"].append((skill_id, perms))
        return box["value"]

    monkeypatch.setattr(tool_sandbox, "describe_skill_tools", fake)
    return box


@pytest.fixture
def skill_folder(make_skill_dir):
    return make_skill_dir({"tools.py": _tools_py()}, name="fake-skill")


def test_load_skill_tools_registers_namespaced_tool(skill_folder, described):
    import shared
    from marketplace.loader import load_skill_tools

    result = load_skill_tools("fake-skill", skill_folder, "Verified")
    assert result["ok"] is True
    assert "fake-skill__fake_tool" in shared.TOOL_DISPATCH
    assert shared.TOOL_TIER_MAP["fake-skill"] == "Verified"
    entry = next(d for d in shared.TOOLS if d["name"] == "fake-skill__fake_tool")
    assert entry["description"] == "[Verified] x"
    assert shared.TOOL_STATUS["fake-skill__fake_tool"] == "Running..."
    assert "fake-skill__fake_tool" in shared.SKILL_TOOLS_MAP["fake-skill"]


def test_registered_handler_is_the_sandbox_stub(skill_folder, described):
    import shared
    from marketplace.loader import load_skill_tools

    load_skill_tools("fake-skill", skill_folder, "Verified")
    fn = shared.TOOL_DISPATCH["fake-skill__fake_tool"]
    params = list(inspect.signature(fn).parameters.values())
    assert len(params) == 1 and params[0].annotation in (dict, "dict")
    assert not inspect.iscoroutinefunction(fn)


def test_tools_py_is_never_executed_in_the_app_process(make_skill_dir, described):
    from marketplace.loader import load_skill_tools

    skill = make_skill_dir(
        {"tools.py": "open(__file__ + '.ran', 'w').write('x')\n" + _tools_py()}, name="fake-skill"
    )
    load_skill_tools("fake-skill", skill, "Community")
    assert not (skill / "tools.py.ran").exists()
    assert "_marketplace_skill_fake_skill" not in sys.modules


def test_describe_runs_with_the_approved_permissions(skill_folder, described):
    from marketplace.loader import load_skill_tools
    from marketplace.permissions import Permissions

    installer.save_installed([{"id": "fake-skill", "version": "1.0"}])
    perms = Permissions(network=("api.example.com",))
    state.record_approval("fake-skill", perms.to_dict())
    load_skill_tools("fake-skill", skill_folder, "Community")
    assert described["calls"][0] == ("fake-skill", perms)


def test_load_skill_tools_no_tools_py_is_ok(tmp_path):
    from marketplace.loader import load_skill_tools

    result = load_skill_tools("no-tools-skill", tmp_path, "Mine")
    assert result["ok"] is True


def test_a_disabled_skill_does_not_load(skill_folder, described):
    import shared
    from marketplace.loader import load_skill_tools

    installer.save_installed([{"id": "fake-skill", "version": "1.0", "disabled": True}])
    result = load_skill_tools("fake-skill", skill_folder, "Verified")
    assert result == {"ok": False, "error": "skill is disabled"}
    assert "fake-skill__fake_tool" not in shared.TOOL_DISPATCH
    assert described["calls"] == []


def test_unload_removes_tools(skill_folder, described):
    import shared
    from marketplace.loader import load_skill_tools, unload_skill_tools

    load_skill_tools("fake-skill", skill_folder, "Verified")
    assert "fake-skill__fake_tool" in shared.TOOL_DISPATCH

    unload_skill_tools("fake-skill")
    assert "fake-skill__fake_tool" not in shared.TOOL_DISPATCH
    assert not any(d["name"].startswith("fake-skill__") for d in shared.TOOLS)
    assert "fake-skill" not in shared.TOOL_TIER_MAP
    assert "fake-skill" not in shared.INSTALLED_TOOL_MODULES


def test_reinstall_gets_the_new_tool_list(skill_folder, described):
    import shared
    from marketplace.loader import load_skill_tools, unload_skill_tools

    described["value"] = _described("tool_v1")
    load_skill_tools("fake-skill", skill_folder, "Verified")
    assert "fake-skill__tool_v1" in shared.TOOL_DISPATCH

    unload_skill_tools("fake-skill")
    described["value"] = _described("tool_v2")
    load_skill_tools("fake-skill", skill_folder, "Verified")
    assert "fake-skill__tool_v2" in shared.TOOL_DISPATCH
    assert "fake-skill__tool_v1" not in shared.TOOL_DISPATCH


def test_a_failed_describe_is_recorded_and_registers_nothing(skill_folder, described):
    import shared
    from marketplace.loader import load_skill_tools

    described["value"] = {"ok": False, "error": "tool contract mismatch (tools defined but no handler)"}
    result = load_skill_tools("broken-skill", skill_folder, "Community")
    assert result["ok"] is False
    assert "contract mismatch" in shared.FAILED_SKILLS["broken-skill"]
    assert not any(d["name"].startswith("broken-skill__") for d in shared.TOOLS)


def test_a_successful_load_clears_an_earlier_failure(skill_folder, described):
    import shared
    from marketplace.loader import load_skill_tools

    shared.FAILED_SKILLS["fake-skill"] = "old"
    load_skill_tools("fake-skill", skill_folder, "Community")
    assert "fake-skill" not in shared.FAILED_SKILLS


def test_end_to_end_the_registered_tool_runs_tools_py_in_the_sandbox_path(make_skill_dir, passthrough_sandbox):
    import shared
    from marketplace.loader import load_skill_tools

    src = (
        'TOOL_DEFS = [{"name": "add", "description": "adds", "input_schema": {"type": "object", "properties": {}}}]\n'
        'TOOL_STATUS = {"add": "Adding"}\n'
        "def add(a, b): return {'sum': a + b}\n"
        'TOOL_HANDLERS = {"add": add}\n'
    )
    skill = make_skill_dir({"tools.py": src}, name="fake-skill")
    installer.save_installed([{"id": "fake-skill", "version": "1.0"}])
    assert load_skill_tools("fake-skill", skill, "Community")["ok"] is True
    assert shared.TOOL_DISPATCH["fake-skill__add"]({"a": 2, "b": 3}) == {"sum": 5}
    assert len(passthrough_sandbox.requests) == 2  # one describe, one call


def test_bad_tools_py_logs_to_failed_skills(make_skill_dir, passthrough_sandbox):
    import shared
    from marketplace.loader import load_skill_tools

    skill = make_skill_dir({"tools.py": "this is not valid python !!!"}, name="broken-skill")
    result = load_skill_tools("broken-skill", skill, "Community")
    assert result["ok"] is False
    assert "broken-skill" in shared.FAILED_SKILLS
```

- [ ] **Step 9: Run the loader tests to verify they fail**

Run: `python -m pytest tests/marketplace/test_loader.py -q`
Expected: failures (the old loader imports `tools.py` in-process and never calls `describe_skill_tools`).

- [ ] **Step 10: Edit `web/marketplace/loader.py`**

(a) Imports. Replace the import block at the top (lines 3-17 today) with:

```python
import json
import logging
import os as _os
import re as _re
import threading
from pathlib import Path

# Guards concurrent read-modify-write of os.environ["PATH"] across parallel skill loads.
_PATH_LOCK = threading.Lock()

import shared
from marketplace import state, tool_sandbox
```

(`importlib.util`, `shutil`, `sys` and `validate_tool_contract` are no longer used in this file. Check with a search for `sys.`, `shutil.` and `validate_tool_contract` in the file before saving; if any other use remains, keep that import.)

(b) Disabled check. Replace the first lines of the `load_skill_tools` body, i.e. the comment and the two calls before "Register skill dependencies":

```python
    if state.is_disabled(skill_id):
        return {"ok": False, "error": "skill is disabled"}

    # bin/ and .mcp.json must be processed regardless of whether tools.py exists
    # — a plugin can ship MCP-bridged tools or CLI shims with no Python tools.py.
    inject_bin_path(skill_dir, skill_id)
    load_plugin_mcp(skill_id, skill_dir)
```

Also update the function docstring's first line to: `"""Register a skill's tools. tools.py is never imported here: its tool list is read, and each call runs, in the OS sandbox.`

(c) Replace everything from the line `# Unload first if already registered (prevents duplicate TOOLS list entries)` to the end of `load_skill_tools` (`return {"ok": True}` after the logger.info) with:

```python
    # Unload first if already registered (prevents duplicate TOOLS list entries)
    if skill_id in shared.INSTALLED_TOOL_MODULES:
        unload_skill_tools(skill_id)

    perms = state.approved_permissions(skill_id)
    described = tool_sandbox.describe_skill_tools(skill_id, skill_dir, perms)
    if not described.get("ok"):
        err = described.get("error") or "the skill's tools could not be read"
        shared.FAILED_SKILLS[skill_id] = err
        logger.warning("Failed to read tools.py for skill %s: %s", skill_id, err)
        return {"ok": False, "error": err}

    shared.FAILED_SKILLS.pop(skill_id, None)  # clear any previous failure

    defs = described["defs"]
    status = described["status"]

    # Namespace all tool names: skill_id__tool_name (hyphens preserved in skill_id portion)
    # Prefix every description with the marketplace tier ([Verified], [Community],
    # [Mine]) so the LLM can prefer higher-fidelity variants over [Native] ones
    # of the same domain (e.g. Anthropic's docx skill beats native docx).
    prefix = skill_id + "__"
    tier_tag = f"[{tier}] " if tier else ""
    namespaced_defs = []
    stubs = {}
    for d in defs:
        nd = dict(d)
        nd["name"] = prefix + d["name"]
        nd["description"] = f"{tier_tag}{d.get('description', '')}".rstrip()
        namespaced_defs.append(nd)
        stubs[nd["name"]] = tool_sandbox.make_stub(skill_id, skill_dir, d["name"], tier)
    namespaced_status = {prefix + k: v for k, v in status.items()}

    # Register into shared state
    shared.TOOLS.extend(namespaced_defs)
    shared.TOOL_DISPATCH.update(stubs)
    shared.TOOL_STATUS.update(namespaced_status)
    tool_names = {d["name"] for d in namespaced_defs}
    shared.SKILL_TOOLS_MAP.setdefault(skill_id, set()).update(tool_names)

    # Track tier; the value in INSTALLED_TOOL_MODULES is only a marker now (nothing is imported)
    shared.TOOL_TIER_MAP[skill_id] = tier
    shared.INSTALLED_TOOL_MODULES[skill_id] = f"_marketplace_skill_{skill_id.replace('-', '_')}"

    logger.info(
        "Loaded tools for skill %s (tier=%s, sandboxed): %s", skill_id, tier, sorted(tool_names)
    )
    return {"ok": True}
```

(d) In `unload_skill_tools`, replace the block

```python
    # Evict cached module
    module_key = shared.INSTALLED_TOOL_MODULES.pop(skill_id, None)
    if module_key and module_key in sys.modules:
        del sys.modules[module_key]
```

with

```python
    shared.INSTALLED_TOOL_MODULES.pop(skill_id, None)
```

Also change the `shared.py` comment at line 91-93 to `# skill_id -> marker for a loaded marketplace tools.py (nothing is imported; the tools run in the sandbox)`.

- [ ] **Step 11: Run the loader tests and everything else that loads skills**

Run: `python -m pytest tests/marketplace tests/test_skill_dependencies.py tests/hooks tests/code_runner -q`
Expected: pass, apart from the two known `httpserver` errors in `tests/marketplace/test_installer.py`. A test that reaches `load_skill_tools` for a skill that has a real `tools.py` (route tests that install one) will now try to launch the sandbox; give that test `monkeypatch.setattr("marketplace.tool_sandbox.describe_skill_tools", lambda *a, **k: {"ok": True, "defs": [], "status": {}})`, or use `passthrough_sandbox` if it needs the tool to run. Do not weaken the new loader tests to make an old test pass.

- [ ] **Step 12: Commit**

```bash
git add web/marketplace/tool_runner_source.py web/marketplace/tool_sandbox.py web/marketplace/loader.py web/shared.py tests/conftest.py tests/marketplace/test_tool_runner.py tests/marketplace/test_tool_sandbox.py tests/marketplace/test_loader.py
git commit -m "feat: marketplace tools.py runs in the OS sandbox per call instead of inside the app process"
```
Stage any other test file you had to adjust in Step 11 by name too.


### Task 7: Kill switch (disable and re-enable) with routes

After this task a user can switch an installed skill or plugin bundle off in one call. A disabled skill's prompt, tools, hooks (Task 5), commands and MCP servers stop working, and it stays off across restarts and reloads. Enable turns it back on.

**Files:**
- Create: `web/marketplace/kill_switch.py`
- Modify: `web/routes/marketplace.py` (one import, two routes), `web/shared.py:336-389` (`load_installed_skill_prompts` skips disabled ids), `web/marketplace/commands.py:186-195` (`load_installed_plugin_commands` skips disabled entries), `web/skills/code_runner/tools.py:116` (`_find_skill_dir` refuses a disabled skill)
- Test: `tests/marketplace/test_kill_switch.py` (new)

**Interfaces:**
- Consumes (Task 2): `state.get_entry`, `state.set_disabled`, `state.disabled_ids`, `state.skill_dir_for`. (Task 4): `routes/marketplace.py` already imports `Depends`, `HTTPException` and `verify_csrf`. (Task 6): `loader.load_skill_tools(skill_id, skill_dir, tier)` and `loader.unload_skill_tools(skill_id)`. Existing: `installer._teardown_plugin_mcp(plugin_id)`, `installer._register_plugin_mcp_servers(plugin_id, plugin_dir)`, `commands.register_plugin_commands(plugin_id, plugin_dir)`, `commands.deregister_plugin_commands(command_ids)`, `shared.load_installed_skill_prompts()`.
- Produces: `kill_switch.disable(skill_id) -> {"ok": True} | {"ok": False, "error": "skill not found: <id>"}`; `kill_switch.enable(skill_id)` (same shape); routes `POST /api/marketplace/disable/{skill_id}` and `POST /api/marketplace/enable/{skill_id}` (CSRF-protected), each returning `{"ok": True, "skill_id": str, "disabled": bool}`, 404 for an unknown id.

Design notes (so the tests make sense):
- Only an entry itself can be disabled. A bundle's inner skill ids follow the bundle (`state.disabled_ids()` already includes them); asking to disable an inner id alone is "not found".
- The disabled flag is written first. The teardown steps after it each run on their own, so one failing step is logged and the rest still run. The kill switch must never half-apply because of one error.
- Disabling a bundle wipes its MCP connections and their stored credentials (that is what `_teardown_plugin_mcp` does). Enable re-registers the servers from disk; the user re-enters any credential. This is listed under Known limits.
- Enable re-reads the tool list for a standalone skill only if its folder is at the install location. Bundles have no `tools.py` loading, and "Mine" skills live elsewhere and are not marketplace code.

- [ ] **Step 1: Write the failing tests**

`tests/marketplace/test_kill_switch.py`:

```python
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import config
import shared
from marketplace import commands, installer, kill_switch, loader, state
from marketplace.installer import skill_id_for_cache_path
from routes.marketplace import router
from security import get_csrf_token

SOLO_MD = "---\nname: Solo\ndescription: solo skill\n---\n# Solo\nDo solo things.\n"
HELPER_MD = "---\nname: Helper\ndescription: helper skill\n---\n# Helper\nHelp.\n"
COMMAND_MD = "---\ndescription: say hello\n---\nSay hello to $ARGUMENTS\n"


@pytest.fixture
def env(tmp_path, monkeypatch):
    skills = tmp_path / "skills-under-test"
    plugins = tmp_path / "plugins"
    cache = plugins / "cache"
    for module in (installer, config):
        monkeypatch.setattr(module, "INSTALLED_SKILLS_DIR", skills)
        monkeypatch.setattr(module, "PLUGINS_DIR", plugins)
    monkeypatch.setattr(shared, "_USER_SKILL_DIRS", [skills, cache])

    (skills / "solo").mkdir(parents=True)
    (skills / "solo" / "SKILL.md").write_text(SOLO_MD, encoding="utf-8")

    bundle_dir = cache / "mkt" / "bundle" / "2.0"
    helper_md = bundle_dir / "skills" / "helper" / "SKILL.md"
    helper_md.parent.mkdir(parents=True)
    helper_md.write_text(HELPER_MD, encoding="utf-8")
    (bundle_dir / "commands").mkdir()
    (bundle_dir / "commands" / "hello-cmd.md").write_text(COMMAND_MD, encoding="utf-8")
    inner = skill_id_for_cache_path(cache, helper_md)
    assert inner

    installer.save_installed([
        {"id": "solo", "version": "1.0", "tier": "Community"},
        {"id": "mine-one", "version": "1.0", "tier": "Mine"},
        {"id": "bundle", "version": "2.0", "tier": "Verified", "source": "mkt",
         "skill_ids": [inner], "command_ids": ["hello-cmd"]},
    ])
    shared.load_installed_skill_prompts()
    commands.register_plugin_commands("bundle", bundle_dir)
    assert "solo" in shared.SKILL_PROMPTS and inner in shared.SKILL_PROMPTS
    assert "hello-cmd" in commands.COMMAND_REGISTRY

    yield SimpleNamespace(inner=inner, skills=skills, bundle_dir=bundle_dir)

    for registry in (shared.SKILL_PROMPTS, shared.SKILL_REQUIRES, shared.SKILL_DESCRIPTIONS, shared.SKILL_OUTPUT_FORMATS):
        for key in ("solo", inner):
            registry.pop(key, None)
    commands.COMMAND_REGISTRY.pop("hello-cmd", None)


@pytest.fixture
def calls(monkeypatch):
    seen = SimpleNamespace(unloaded=[], loaded=[], torn=[], registered_mcp=[])
    monkeypatch.setattr(loader, "unload_skill_tools", lambda sid: seen.unloaded.append(sid))
    monkeypatch.setattr(loader, "load_skill_tools", lambda sid, d, tier: seen.loaded.append((sid, d, tier)) or {"ok": True})
    monkeypatch.setattr(installer, "_teardown_plugin_mcp", lambda pid: seen.torn.append(pid))
    monkeypatch.setattr(installer, "_register_plugin_mcp_servers",
                        lambda pid, d: seen.registered_mcp.append((pid, d)) or [])
    return seen


def test_unknown_skill_is_not_found(env, calls):
    assert kill_switch.disable("nope") == {"ok": False, "error": "skill not found: nope"}
    assert kill_switch.enable("nope")["ok"] is False


def test_a_bundles_inner_skill_cannot_be_disabled_on_its_own(env, calls):
    result = kill_switch.disable(env.inner)
    assert result["ok"] is False
    assert not state.is_disabled(env.inner)


def test_disable_a_standalone_skill(env, calls):
    assert kill_switch.disable("solo") == {"ok": True}
    assert state.is_disabled("solo")
    assert "solo" not in shared.SKILL_PROMPTS
    assert calls.unloaded == ["solo"]
    assert calls.torn == []


def test_disable_a_bundle_takes_down_skills_commands_and_mcp(env, calls):
    assert kill_switch.disable("bundle") == {"ok": True}
    assert env.inner not in shared.SKILL_PROMPTS
    assert "hello-cmd" not in commands.COMMAND_REGISTRY
    assert calls.torn == ["bundle"]
    assert set(calls.unloaded) == {"bundle", env.inner}


def test_disabled_state_survives_prompt_and_command_reloads(env, calls):
    kill_switch.disable("bundle")
    kill_switch.disable("solo")
    shared.load_installed_skill_prompts()
    commands.load_installed_plugin_commands()
    assert "solo" not in shared.SKILL_PROMPTS
    assert env.inner not in shared.SKILL_PROMPTS
    assert "hello-cmd" not in commands.COMMAND_REGISTRY


def test_enable_a_standalone_skill_restores_prompt_and_reloads_tools(env, calls):
    kill_switch.disable("solo")
    assert kill_switch.enable("solo") == {"ok": True}
    assert not state.is_disabled("solo")
    assert "solo" in shared.SKILL_PROMPTS
    assert calls.loaded == [("solo", env.skills / "solo", "Community")]


def test_enable_a_bundle_restores_skills_commands_and_mcp_without_loading_tools(env, calls):
    kill_switch.disable("bundle")
    assert kill_switch.enable("bundle") == {"ok": True}
    assert env.inner in shared.SKILL_PROMPTS
    assert "hello-cmd" in commands.COMMAND_REGISTRY
    assert calls.registered_mcp == [("bundle", env.bundle_dir)]
    assert calls.loaded == []


def test_enable_skips_the_tool_load_when_the_folder_is_not_at_the_install_location(env, calls):
    kill_switch.disable("mine-one")
    assert kill_switch.enable("mine-one") == {"ok": True}
    assert calls.loaded == []


def test_one_failing_step_does_not_stop_the_others(env, monkeypatch, calls):
    def boom(_sid):
        raise RuntimeError("unload failed")

    monkeypatch.setattr(loader, "unload_skill_tools", boom)
    assert kill_switch.disable("solo") == {"ok": True}
    assert state.is_disabled("solo")
    assert "solo" not in shared.SKILL_PROMPTS


def test_run_python_cannot_borrow_a_disabled_skills_folder(env, monkeypatch, calls):
    from skills.code_runner import tools as cr

    monkeypatch.setattr(cr, "USER_SKILL_DIRS", [env.skills])
    assert cr._find_skill_dir("solo") == env.skills / "solo"
    kill_switch.disable("solo")
    assert cr._find_skill_dir("solo") is None


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _post(client, path, token=True):
    return client.post(path, headers={"X-CSRF-Token": get_csrf_token()} if token else {})


def test_routes_require_the_csrf_token(env, calls, client):
    assert _post(client, "/api/marketplace/disable/solo", token=False).status_code == 403
    assert _post(client, "/api/marketplace/enable/solo", token=False).status_code == 403
    assert not state.is_disabled("solo")


def test_routes_return_404_for_an_unknown_skill(env, calls, client):
    assert _post(client, "/api/marketplace/disable/nope").status_code == 404
    assert _post(client, "/api/marketplace/enable/nope").status_code == 404


def test_routes_round_trip_and_the_listing_reports_the_flag(env, calls, client):
    resp = _post(client, "/api/marketplace/disable/solo")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "skill_id": "solo", "disabled": True}
    listing = client.get("/api/marketplace/installed").json()["skills"]
    assert next(s for s in listing if s["id"] == "solo")["disabled"] is True

    resp = _post(client, "/api/marketplace/enable/solo")
    assert resp.json() == {"ok": True, "skill_id": "solo", "disabled": False}
    listing = client.get("/api/marketplace/installed").json()["skills"]
    assert "disabled" not in next(s for s in listing if s["id"] == "solo")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/marketplace/test_kill_switch.py -q`
Expected: collection error (`cannot import name 'kill_switch'`).

- [ ] **Step 3: Write `web/marketplace/kill_switch.py`**

```python
"""Kill switch: turn an installed marketplace skill or plugin bundle off and back on."""
from __future__ import annotations

import logging

from marketplace import installer, loader, state
from marketplace.commands import deregister_plugin_commands, register_plugin_commands

logger = logging.getLogger(__name__)


def _step(label: str, fn, *args) -> None:
    try:
        fn(*args)
    except Exception:
        logger.warning("kill switch: %s failed", label, exc_info=True)


def _find(skill_id: str):
    entry = state.get_entry(skill_id)
    if entry is None or entry.get("id") != skill_id:
        return None, {"ok": False, "error": f"skill not found: {skill_id}"}
    return entry, None


def _refresh_prompts() -> None:
    import shared

    shared.load_installed_skill_prompts()


def disable(skill_id: str) -> dict:
    entry, error = _find(skill_id)
    if error:
        return error
    state.set_disabled(skill_id, True)
    inner_ids = entry.get("skill_ids")
    for sid in [skill_id, *(inner_ids or [])]:
        _step(f"unload tools of {sid}", loader.unload_skill_tools, sid)
    if inner_ids is not None:
        _step(f"stop MCP servers of {skill_id}", installer._teardown_plugin_mcp, skill_id)
        _step(f"remove commands of {skill_id}", deregister_plugin_commands, entry.get("command_ids") or [])
    _step("refresh skill prompts", _refresh_prompts)
    return {"ok": True}


def _enable_tools(skill_id: str, entry: dict, skill_dir) -> None:
    if entry.get("skill_ids") is not None:
        installer._register_plugin_mcp_servers(skill_id, skill_dir)
        register_plugin_commands(skill_id, skill_dir)
    elif skill_dir.exists():
        result = loader.load_skill_tools(skill_id, skill_dir, entry.get("tier") or "Community")
        if not result.get("ok"):
            logger.warning("kill switch: tools of %s did not reload: %s", skill_id, result.get("error"))


def enable(skill_id: str) -> dict:
    entry, error = _find(skill_id)
    if error:
        return error
    state.set_disabled(skill_id, False)
    _step("refresh skill prompts", _refresh_prompts)
    _step(f"restore {skill_id}", _enable_tools, skill_id, entry, state.skill_dir_for(entry))
    return {"ok": True}
```

- [ ] **Step 4: Add the two routes to `web/routes/marketplace.py`**

Add `from marketplace import kill_switch` next to the other `from marketplace...` imports at the top of the file, then append at the end of the file:

```python
def _switch(skill_id: str, action, disabled: bool) -> dict:
    result = action(skill_id)
    if not result.get("ok"):
        error = result.get("error", "failed")
        raise HTTPException(status_code=404 if "not found" in error else 500, detail=error)
    return {"ok": True, "skill_id": skill_id, "disabled": disabled}


@router.post("/api/marketplace/disable/{skill_id}", dependencies=[Depends(verify_csrf)])
def disable_installed_skill(skill_id: str):
    return _switch(skill_id, kill_switch.disable, True)


@router.post("/api/marketplace/enable/{skill_id}", dependencies=[Depends(verify_csrf)])
def enable_installed_skill(skill_id: str):
    return _switch(skill_id, kill_switch.enable, False)
```

- [ ] **Step 5: Skip disabled skills when prompts are rebuilt (`web/shared.py`)**

In `load_installed_skill_prompts`, replace

```python
    found_ids = set()
    any_root_reachable = False
```

with

```python
    try:
        from marketplace.state import disabled_ids

        disabled = disabled_ids()
    except Exception:
        log.warning("could not read the disabled-skill list; loading every skill", exc_info=True)
        disabled = set()
    found_ids = set()
    any_root_reachable = False
```

and replace

```python
            skill_id = _resolve_skill_id(root, candidate)
            if skill_id in found_ids:
                continue  # higher-precedence root already provided this skill
            found_ids.add(skill_id)
```

with

```python
            skill_id = _resolve_skill_id(root, candidate)
            if skill_id in found_ids:
                continue  # higher-precedence root already provided this skill
            if skill_id in disabled:
                continue  # left out of found_ids on purpose: the cleanup loop below removes it
            found_ids.add(skill_id)
```

- [ ] **Step 6: Skip disabled bundles when commands are rebuilt (`web/marketplace/commands.py`)**

In `load_installed_plugin_commands`, replace

```python
    for entry in load_installed():
        command_ids = entry.get("command_ids")
```

with

```python
    for entry in load_installed():
        if entry.get("disabled"):
            continue
        command_ids = entry.get("command_ids")
```

- [ ] **Step 7: Refuse a disabled skill's folder in `web/skills/code_runner/tools.py`**

In `_find_skill_dir`, replace

```python
    if not skill_id or not _valid_skill_id(skill_id):
        return None
    candidates = [
```

with

```python
    if not skill_id or not _valid_skill_id(skill_id):
        return None
    from marketplace import state

    if state.is_disabled(skill_id):
        return None
    candidates = [
```

- [ ] **Step 8: Run the tests**

Run: `python -m pytest tests/marketplace/test_kill_switch.py tests/marketplace/test_state.py tests/code_runner tests/hooks -q`
Expected: all pass. If `test_run_python_cannot_borrow_a_disabled_skills_folder` fails on `_in_skill_roots`, the temp folder is outside the roots: also `monkeypatch.setattr(cr, "INSTALLED_SKILLS_DIR", env.skills)` in that test (the test fixes the roots, not the assertions).

- [ ] **Step 9: Commit**

```bash
git add web/marketplace/kill_switch.py web/routes/marketplace.py web/shared.py web/marketplace/commands.py web/skills/code_runner/tools.py tests/marketplace/test_kill_switch.py
git commit -m "feat: kill switch to disable and re-enable an installed marketplace skill or plugin"
```
### Task 8: Marketplace pane, permission card on every install path and Disable/Enable controls

After this task every install in the marketplace pane sends the CSRF header, shows the package's permission lines before anything is installed, and resends with `consent: true` plus the digest it showed. Installed rows get a Disable / Enable button that calls the Task 7 routes.

**Files:**
- Modify: `web/static/marketplace-pane.js`, `web/static/style.css` (append only)
- Test: `tests/marketplace_controls.test.js` (new). The repo runs JS tests as `node tests/<name>.test.js`; they pull functions out of the pane file by regex and run them in `vm` (no DOM, no jsdom).

**Interfaces:**
- Consumes (Tasks 4 and 7):
  - `POST /api/marketplace/install` and `/api/marketplace/install-local` without `consent` answer HTTP 200 `{"ok": false, "consent_required": true, "skill_id", "resolved_ref", "summary": {"lines": [str], "digest": str, ...}}`. Plugin and catalog answers also carry `plugin_id` and `capabilities`.
  - The same routes with `consent: true` and a missing `digest` are HTTP 400; a changed package is HTTP 409 with `detail = {"error": "content_changed", "message": str}` (the existing `_errorMessage` already shows `detail.message`).
  - All three routes require the `X-CSRF-Token` header. `GET /api/csrf` returns `{"csrf_token": str}`.
  - `POST /api/marketplace/disable/{skill_id}` and `/enable/{skill_id}` answer `{"ok": true, "skill_id", "disabled": bool}`.
  - `GET /api/marketplace/installed` entries carry `disabled: true` (absent when enabled) and `permissions` (absent on legacy entries).
- Produces (all inside the pane's IIFE, none exported):
  - `_postJson(url, payload) -> Promise<{resp, body}>` (`body` is `null` when the answer is not JSON).
  - `_permissionLines(summary) -> string[]`.
  - `_consentPayload(payload, firstBody) -> object`.
  - `_toggleState(skill) -> {action: 'enable'|'disable', label: string}`.
  - `_postWithApproval(url, payload, title, confirmLabel) -> Promise<{resp, body} | {cancelled: true}>`.
  - `_confirmPermissions(title, summary, confirmLabel) -> Promise<boolean>`, `_appendPermissionList(container, summary)`, `_decorateInstalledRow(row, meta, actions, skill)`, `_setSkillDisabled(skillId, disable)`.

How the approval works: the first call (no consent) comes back as `consent_required` with the summary. The card shows `summary.lines`. On approval the pane resends the same payload with `consent: true` and `digest: summary.digest` (plus `pinned_ref` when the server returned a `resolved_ref`). One extra click is added only where the old flow had none to spare: URL imports, local picks and URL plugins. Browse-tab installs (`_install`) show the permission lines inside the confirmation dialog they already had, and Verified plugins show them inside their existing consent dialog.

- [ ] **Step 1: Write the failing test file**

Create `tests/marketplace_controls.test.js`:

```js
// Marketplace skill controls: CSRF + approval helpers, install wiring, Disable/Enable.
// Same harness as marketplace_verified_consent.test.js: functions are pulled out of
// marketplace-pane.js by regex and run in vm. There is no DOM here, so the wiring tests
// check the function source and the pure helpers are run for real.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'marketplace-pane.js'),
  'utf8',
);

function fnSource(name) {
  const re = new RegExp('(?:async\\s+)?function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n  \\}');
  const match = source.match(re);
  assert(match, name + ' not found in marketplace-pane.js');
  return match[0];
}

function extractFn(name, ctx) {
  const context = vm.createContext(ctx || {});
  return vm.runInContext(fnSource(name) + ';' + name + ';', context);
}

// Objects built inside a vm context have another realm's prototypes; compare as JSON.
function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

// ── _permissionLines ─────────────────────────────────────────────────────
{
  const _permissionLines = extractFn('_permissionLines');
  assert.deepStrictEqual(
    plain(_permissionLines({ lines: ['Reads these folders: none declared', '', '  ', 7, null, 'Network access: none declared'] })),
    ['Reads these folders: none declared', 'Network access: none declared'],
  );
  assert.deepStrictEqual(plain(_permissionLines(null)), []);
  assert.deepStrictEqual(plain(_permissionLines({})), []);
  assert.deepStrictEqual(plain(_permissionLines({ lines: 'not a list' })), []);
}

// ── _consentPayload ──────────────────────────────────────────────────────
{
  const _consentPayload = extractFn('_consentPayload');
  assert.deepStrictEqual(
    plain(_consentPayload({ skill_id: 'a', tier: 'Community' }, { summary: { digest: 'abc' }, resolved_ref: 'deadbeef' })),
    { skill_id: 'a', tier: 'Community', consent: true, digest: 'abc', pinned_ref: 'deadbeef' },
  );
  // No resolved_ref from the server: no pinned_ref is sent.
  assert.deepStrictEqual(
    plain(_consentPayload({ skill_id: 'a' }, { summary: { digest: 'abc' }, resolved_ref: '' })),
    { skill_id: 'a', consent: true, digest: 'abc' },
  );
  // No summary at all: an empty digest, which the server refuses with a 400.
  assert.deepStrictEqual(plain(_consentPayload({ skill_id: 'a' }, {})), { skill_id: 'a', consent: true, digest: '' });
  // The original payload is not modified.
  const original = { skill_id: 'a' };
  _consentPayload(original, { summary: { digest: 'x' } });
  assert.deepStrictEqual(plain(original), { skill_id: 'a' });
}

// ── _toggleState ─────────────────────────────────────────────────────────
{
  const _toggleState = extractFn('_toggleState');
  assert.deepStrictEqual(plain(_toggleState({ id: 's' })), { action: 'disable', label: 'Disable' });
  assert.deepStrictEqual(plain(_toggleState({ id: 's', disabled: true })), { action: 'enable', label: 'Enable' });
  assert.deepStrictEqual(plain(_toggleState(null)), { action: 'disable', label: 'Disable' });
}

// ── _postJson: CSRF header and one retry ─────────────────────────────────
function fakeResponse(status, body) {
  return { status, ok: status >= 200 && status < 300, json: async () => body };
}

async function postJsonCase(initialToken, script) {
  const calls = [];
  const win = { __CSRF_TOKEN__: initialToken };
  const fetchFake = async (url, opts) => {
    calls.push({ url, opts });
    return script.shift();
  };
  const _postJson = extractFn('_postJson', { fetch: fetchFake, window: win, JSON });
  const result = await _postJson('/api/marketplace/install', { skill_id: 'a' });
  return { calls, win, result };
}

(async () => {
  // The token is sent as a header.
  {
    const { calls, result } = await postJsonCase('tok-1', [fakeResponse(200, { ok: true })]);
    assert.strictEqual(calls.length, 1);
    assert.strictEqual(calls[0].opts.headers['X-CSRF-Token'], 'tok-1');
    assert.strictEqual(calls[0].opts.method, 'POST');
    assert.strictEqual(calls[0].opts.body, JSON.stringify({ skill_id: 'a' }));
    assert.strictEqual(result.resp.ok, true);
    assert.deepStrictEqual(plain(result.body), { ok: true });
  }

  // No token yet: an empty header, never the string "undefined".
  {
    const { calls } = await postJsonCase(undefined, [fakeResponse(200, { ok: true })]);
    assert.strictEqual(calls[0].opts.headers['X-CSRF-Token'], '');
  }

  // A 403 with a stale token: fetch a fresh token, store it, retry once.
  {
    const { calls, win, result } = await postJsonCase('old', [
      fakeResponse(403, { detail: 'CSRF token missing or invalid' }),
      fakeResponse(200, { csrf_token: 'new' }),
      fakeResponse(200, { ok: true }),
    ]);
    assert.deepStrictEqual(calls.map((c) => c.url), [
      '/api/marketplace/install',
      '/api/csrf',
      '/api/marketplace/install',
    ]);
    assert.strictEqual(calls[2].opts.headers['X-CSRF-Token'], 'new');
    assert.strictEqual(win.__CSRF_TOKEN__, 'new');
    assert.deepStrictEqual(plain(result.body), { ok: true });
  }

  // A 403 that is not about the token (same token comes back): no second attempt.
  {
    const { calls, result } = await postJsonCase('same', [
      fakeResponse(403, { detail: { error: 'not_installable' } }),
      fakeResponse(200, { csrf_token: 'same' }),
    ]);
    assert.strictEqual(calls.filter((c) => c.url === '/api/marketplace/install').length, 1);
    assert.strictEqual(result.resp.status, 403);
  }

  // An answer that is not JSON gives body null instead of throwing.
  {
    const res = { status: 502, ok: false, json: async () => { throw new Error('not json'); } };
    const { result } = await postJsonCase('t', [res]);
    assert.strictEqual(result.body, null);
    assert.strictEqual(result.resp.status, 502);
  }

  // ── _postWithApproval ──────────────────────────────────────────────────
  function approvalHarness(postScript, approve) {
    const posts = [];
    const confirms = [];
    const ctx = {
      _postJson: async (url, payload) => {
        posts.push({ url, payload: plain(payload) });
        return postScript.shift();
      },
      _confirmPermissions: async (title, summary, label) => {
        confirms.push({ title, summary: plain(summary), label });
        return approve;
      },
      _consentPayload: extractFn('_consentPayload'),
    };
    return { posts, confirms, run: extractFn('_postWithApproval', ctx) };
  }

  // Not a consent answer: returned as is, no card.
  {
    const h = approvalHarness([{ resp: { ok: false, status: 400 }, body: { detail: 'bad' } }], true);
    const out = await h.run('/api/marketplace/install', { skill_id: 'a' }, 'T', 'Install');
    assert.strictEqual(out.resp.status, 400);
    assert.strictEqual(h.confirms.length, 0);
    assert.strictEqual(h.posts.length, 1);
  }

  // Approved: the card gets the summary, the second call carries consent and the digest.
  {
    const consent = {
      ok: false,
      consent_required: true,
      resolved_ref: '',
      summary: { lines: ['Network access: none declared'], digest: 'd1' },
    };
    const h = approvalHarness(
      [
        { resp: { ok: true, status: 200 }, body: consent },
        { resp: { ok: true, status: 200 }, body: { ok: true, skill_id: 'a' } },
      ],
      true,
    );
    const out = await h.run('/api/marketplace/install', { skill_id: 'a', tier: 'Community' }, 'Install a?', 'Install');
    assert.deepStrictEqual(h.confirms.map((c) => [c.title, c.label]), [['Install a?', 'Install']]);
    assert.deepStrictEqual(h.confirms[0].summary, consent.summary);
    assert.strictEqual(h.posts.length, 2);
    assert.deepStrictEqual(h.posts[1].payload, { skill_id: 'a', tier: 'Community', consent: true, digest: 'd1' });
    assert.strictEqual(out.body.ok, true);
  }

  // Declined: one call only, nothing is sent with consent.
  {
    const h = approvalHarness(
      [{ resp: { ok: true, status: 200 }, body: { ok: false, consent_required: true, summary: { lines: [], digest: 'd' } } }],
      false,
    );
    const out = await h.run('/api/marketplace/install', { skill_id: 'a' }, 'T', 'Install');
    assert.deepStrictEqual(plain(out), { cancelled: true });
    assert.strictEqual(h.posts.length, 1);
  }

  // The package changed between the card and the install: the 409 is handed back to the caller.
  {
    const h = approvalHarness(
      [
        { resp: { ok: true, status: 200 }, body: { consent_required: true, summary: { lines: [], digest: 'd' } } },
        { resp: { ok: false, status: 409 }, body: { detail: { error: 'content_changed', message: 'changed' } } },
      ],
      true,
    );
    const out = await h.run('/api/marketplace/install-local', { kind: 'zip' }, 'T', 'Install');
    assert.strictEqual(out.resp.status, 409);
    assert.strictEqual(out.body.detail.error, 'content_changed');
  }

  // ── Wiring: no install call bypasses the helpers ───────────────────────
  assert(!/fetch\('\/api\/marketplace\/install/.test(source), 'an install call still uses raw fetch');
  for (const name of ['_pickLocalSkill', '_importInstall', '_installUrlPlugin']) {
    assert(fnSource(name).includes('_postWithApproval('), name + ' must go through _postWithApproval');
  }
  const install = fnSource('_install');
  assert(install.includes('_postJson(') && install.includes('_consentPayload(') && install.includes('body.summary'));
  const verified = fnSource('_installVerifiedPlugin');
  assert(verified.includes('_postJson(') && verified.includes('_consentPayload('));
  assert(fnSource('_showVerifiedConsentModal').includes('_appendPermissionList('));
  assert(fnSource('_showInstallModal').includes('_appendPermissionList('));
  const click = fnSource('_handleContentClick');
  assert(click.includes("'disable'") && click.includes("'enable'") && click.includes('_setSkillDisabled('));
  assert(fnSource('_renderInstalled').split('_decorateInstalledRow(').length - 1 === 2, 'bundle rows and standalone rows both get the toggle');
  const toggle = fnSource('_setSkillDisabled');
  assert(toggle.includes('_postJson(') && toggle.includes('refresh()'));

  console.log('marketplace_controls.test.js: ok');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `node tests/marketplace_controls.test.js`
Expected: FAIL with `AssertionError: _permissionLines not found in marketplace-pane.js`.

- [ ] **Step 3: Add the helpers to `web/static/marketplace-pane.js`**

Insert this block directly before the comment line that starts `  // Collision-detection predicate for decision #10` (it follows `_errorMessage`):

```js
  // ── Install approval (permission card) and CSRF ───────────────────────────
  // Every install POST carries the CSRF header; on a 403 the token is fetched
  // again and the call is retried once, but only when the token actually
  // changed (a 403 for another reason, e.g. not_installable, is not retried).
  async function _postJson(url, payload) {
    const sent = window.__CSRF_TOKEN__ || '';
    const send = () =>
      fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': window.__CSRF_TOKEN__ || '',
        },
        body: JSON.stringify(payload || {}),
      });
    let resp = await send();
    if (resp.status === 403) {
      const fresh = await fetch('/api/csrf');
      if (fresh.ok) {
        const token = (await fresh.json()).csrf_token || '';
        if (token && token !== sent) {
          window.__CSRF_TOKEN__ = token;
          resp = await send();
        }
      }
    }
    let body = null;
    try {
      body = await resp.json();
    } catch (e) {
      body = null;
    }
    return { resp, body };
  }

  function _permissionLines(summary) {
    const lines = summary && Array.isArray(summary.lines) ? summary.lines : [];
    return lines.filter((l) => typeof l === 'string' && l.trim() !== '');
  }

  // The second install call: the same payload plus the approval and the digest
  // the card showed. pinned_ref is sent only when the server returned one.
  function _consentPayload(payload, firstBody) {
    const out = Object.assign({}, payload, {
      consent: true,
      digest: (firstBody && firstBody.summary && firstBody.summary.digest) || '',
    });
    if (firstBody && firstBody.resolved_ref) out.pinned_ref = firstBody.resolved_ref;
    return out;
  }

  function _toggleState(skill) {
    return skill && skill.disabled
      ? { action: 'enable', label: 'Enable' }
      : { action: 'disable', label: 'Disable' };
  }

  function _appendPermissionList(container, summary) {
    const lines = _permissionLines(summary);
    if (!lines.length) return;
    const intro = document.createElement('p');
    intro.textContent = 'This package asks for the access below:';
    container.appendChild(intro);
    const ul = document.createElement('ul');
    ul.className = 'mp-permission-list';
    lines.forEach((line) => {
      const li = document.createElement('li');
      li.textContent = line;
      ul.appendChild(li);
    });
    container.appendChild(ul);
  }

  // Standalone permission card. Resolves true on approval, false on cancel or Escape.
  function _confirmPermissions(title, summary, confirmLabel) {
    return new Promise((resolve) => {
      const prevFocus = document.activeElement;
      const titleId = 'mp-perm-title-' + Date.now();
      const overlay = document.createElement('div');
      overlay.className = 'mp-modal-overlay';
      const modal = document.createElement('div');
      modal.className = 'mp-modal';
      modal.setAttribute('role', 'dialog');
      modal.setAttribute('aria-modal', 'true');
      modal.setAttribute('aria-labelledby', titleId);

      const heading = document.createElement('div');
      heading.className = 'mp-modal-title';
      heading.id = titleId;
      heading.textContent = title;

      const body = document.createElement('div');
      body.className = 'mp-modal-body';
      _appendPermissionList(body, summary);
      const note = document.createElement('p');
      note.textContent = 'Nothing is installed until you approve.';
      body.appendChild(note);

      const actions = document.createElement('div');
      actions.className = 'mp-modal-actions';
      const cancelBtn = document.createElement('button');
      cancelBtn.className = 'ap-card-btn';
      cancelBtn.textContent = 'Cancel';
      const approveBtn = document.createElement('button');
      approveBtn.className = 'ap-card-btn primary';
      approveBtn.textContent = confirmLabel || 'Install';

      const finish = (approved) => {
        overlay.remove();
        document.removeEventListener('keydown', onKey, true);
        if (prevFocus && typeof prevFocus.focus === 'function') prevFocus.focus();
        resolve(approved);
      };
      const onKey = (e) => {
        if (e.key === 'Escape') {
          e.stopPropagation();
          e.preventDefault();
          finish(false);
          return;
        }
        if (e.key === 'Tab') {
          if (e.shiftKey && document.activeElement === cancelBtn) {
            e.preventDefault();
            approveBtn.focus();
          } else if (!e.shiftKey && document.activeElement === approveBtn) {
            e.preventDefault();
            cancelBtn.focus();
          }
        }
      };
      cancelBtn.addEventListener('click', () => finish(false));
      approveBtn.addEventListener('click', () => finish(true));

      actions.appendChild(cancelBtn);
      actions.appendChild(approveBtn);
      modal.appendChild(heading);
      modal.appendChild(body);
      modal.appendChild(actions);
      overlay.appendChild(modal);
      document.body.appendChild(overlay);
      document.addEventListener('keydown', onKey, true);
      cancelBtn.focus();
    });
  }

  // First call without consent, card, second call with consent and the digest.
  // Anything that is not a consent answer (an error, an unexpected success) is
  // returned untouched for the caller to handle.
  async function _postWithApproval(url, payload, title, confirmLabel) {
    const first = await _postJson(url, payload);
    if (!first.resp.ok || !first.body || !first.body.consent_required) return first;
    const approved = await _confirmPermissions(title, first.body.summary, confirmLabel);
    if (!approved) return { cancelled: true };
    return _postJson(url, _consentPayload(payload, first.body));
  }

```

- [ ] **Step 4: Run the helper tests**

Run: `node tests/marketplace_controls.test.js`
Expected: the helper cases pass and the run then fails at the first wiring assertion (`an install call still uses raw fetch`). That is the expected state before Step 5.

- [ ] **Step 5: Route every install site through the helpers**

Make these edits in `web/static/marketplace-pane.js`. Find each block by its text, not by line number (earlier edits shift lines).

5a. `_pickLocalSkill`: replace the statements from `const resp = await fetch('/api/marketplace/install-local', {` through the closing `}` of the `if (!resp.ok || !data.ok) { ... }` block. Old text:

```js
      const resp = await fetch('/api/marketplace/install-local', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (previewArea) {
        previewArea.classList.remove('active');
        while (previewArea.firstChild) previewArea.removeChild(previewArea.firstChild);
      }
      if (!resp.ok || !data.ok) {
        if (errorArea) errorArea.textContent = (data && data.detail) || 'Install failed.';
        return;
      }
```

New text:

```js
      const out = await _postWithApproval(
        '/api/marketplace/install-local',
        payload,
        'Install “' + (picked.name || 'skill') + '”?',
        'Install',
      );
      if (previewArea) {
        previewArea.classList.remove('active');
        while (previewArea.firstChild) previewArea.removeChild(previewArea.firstChild);
      }
      if (out.cancelled) return;
      const data = out.body || {};
      if (!out.resp.ok || !data.ok) {
        if (errorArea) errorArea.textContent = _errorMessage(data);
        return;
      }
```

The lines after it (`const skill = { id: data.skill_id, ...`) stay as they are; `resp` is not used after this block.

5b. `_installUrlPlugin`: old text:

```js
      const resp = await fetch('/api/marketplace/install', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ skill_id: skillId, install_url: url, consent: true }),
      });
      const data = await resp.json();
      if (!resp.ok || data.ok !== true) {
        if (errorArea) errorArea.textContent = _errorMessage(data);
        return;
      }
```

New text:

```js
      const out = await _postWithApproval(
        '/api/marketplace/install',
        { skill_id: skillId, install_url: url },
        'Approve “' + (previewBody.name || skillId) + '”?',
        'Approve and install',
      );
      if (out.cancelled) return;
      const data = out.body || {};
      if (!out.resp.ok || data.ok !== true) {
        if (errorArea) errorArea.textContent = _errorMessage(data);
        return;
      }
```

5c. `_importInstall`: replace everything inside its `try {` up to and including the closing `}` of `if (!resp.ok || body.ok !== true) { ... }` (the block that starts `const resp = await fetch('/api/marketplace/install', {` and ends just before the comment line `// Success → refresh installed list and switch tab`). That block contains the long comment about HTTP 200 with `consent_required` and the "needs the consent flow" message; both go. New text:

```js
      const out = await _postWithApproval(
        '/api/marketplace/install',
        payload,
        'Install “' + skillId + '”?',
        'Install',
      );
      if (out.cancelled) {
        btn.disabled = false;
        btn.textContent = 'Install';
        return;
      }
      const body = out.body || {};
      if (!out.resp.ok || body.ok !== true) {
        const err = document.getElementById('mp-import-error');
        if (err) err.textContent = _errorMessage(body);
        btn.disabled = false;
        btn.textContent = 'Install';
        return;
      }
```

5d. `_install`: replace the `_showInstallModal(skill, async () => { ... });` call (the last statement of the function) with:

```js
    const payload = {
      skill_id: skill.id,
      skill_md: '',
      version: skill.version || '1.0',
      tier: skill.tier,
      install_url: skill.install_url || '',
    };
    let first;
    try {
      first = await _postJson('/api/marketplace/install', payload);
    } catch (err) {
      _showAlert('Install error: ' + err.message, 'error');
      return;
    }
    const body = first.body || {};
    if (!first.resp.ok || !body.consent_required) {
      _handleInstallOutcome(first.resp.ok && body.ok === true, body, skill);
      return;
    }
    _showInstallModal(
      skill,
      async () => {
        try {
          const second = await _postJson('/api/marketplace/install', _consentPayload(payload, body));
          const data = second.body || {};
          const ok = second.resp.ok && data.ok === true;
          if (ok && typeof window.registerUserSkill === 'function') {
            window.registerUserSkill(skill.id, skill.name, skill.tier);
          }
          _handleInstallOutcome(ok, data, skill);
        } catch (err) {
          _showAlert('Install error: ' + err.message, 'error');
        }
      },
      body.summary,
    );
```

5e. `_showInstallModal`: change the signature `function _showInstallModal(skill, onConfirm) {` to `function _showInstallModal(skill, onConfirm, summary) {`, and insert this directly before the line `const actions = document.createElement('div');` that follows the Community warning block in that function (the first `actions` declaration after `body.appendChild(communityWarning)`; it is the one preceded by the `if (skill.tier === 'Community') { ... }` block):

```js
    _appendPermissionList(body, summary);

```

5f. `_installVerifiedPlugin`, first call. Old text:

```js
      resp = await fetch('/api/marketplace/install', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ skill_id: skill.id }),
      });
      body = await resp.json();
```

New text:

```js
      const first = await _postJson('/api/marketplace/install', { skill_id: skill.id });
      resp = first.resp;
      body = first.body || {};
```

5g. `_installVerifiedPlugin`, second call. Old text:

```js
          resp2 = await fetch('/api/marketplace/install', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              skill_id: skill.id,
              consent: true,
              pinned_ref: body.resolved_ref || '',
            }),
          });
          body2 = await resp2.json();
```

New text:

```js
          const second = await _postJson(
            '/api/marketplace/install',
            _consentPayload({ skill_id: skill.id }, body),
          );
          resp2 = second.resp;
          body2 = second.body || {};
```

5h. `_showVerifiedConsentModal`: insert directly before `const trust = document.createElement('p');` (the paragraph that says "Part of Anthropic's curated marketplace"):

```js
    _appendPermissionList(body, previewBody.summary);

```

- [ ] **Step 6: Add the Disable / Enable controls**

6a. In `_handleContentClick`, replace the tail

```js
    } else if (action === 'mp-import-install') {
      _importInstall(btn);
    }
  }
```

with

```js
    } else if (action === 'mp-import-install') {
      _importInstall(btn);
    } else if (action === 'disable' || action === 'enable') {
      _setSkillDisabled(btn.dataset.skillId, action === 'disable');
    }
  }

  async function _setSkillDisabled(skillId, disable) {
    const verb = disable ? 'disable' : 'enable';
    try {
      const { resp, body } = await _postJson(
        '/api/marketplace/' + verb + '/' + encodeURIComponent(skillId),
        {},
      );
      if (!resp.ok || !body || body.ok !== true) {
        _showAlert('Could not ' + verb + ': ' + _errorMessage(body), 'error');
        return;
      }
      await refresh();
    } catch (err) {
      _showAlert('Network error: ' + err.message, 'error');
    }
  }

  // Disabled label, dimmed row and the Disable / Enable button for one installed row.
  function _decorateInstalledRow(row, meta, actions, skill) {
    const state = _toggleState(skill);
    if (skill.disabled) {
      row.classList.add('mp-installed-disabled');
      const label = document.createElement('span');
      label.className = 'mp-installed-disabled-label';
      label.textContent = 'Disabled';
      meta.appendChild(label);
    }
    const toggleBtn = document.createElement('button');
    toggleBtn.className = 'mp-row-btn';
    toggleBtn.textContent = state.label;
    toggleBtn.dataset.action = state.action;
    toggleBtn.dataset.skillId = skill.id;
    actions.appendChild(toggleBtn);
  }
```

6b. In `_renderInstalled`, bundle rows. Old text (8-space indent, followed by the Remove button):

```js
        actions.className = 'mp-installed-actions';
        const removeBtn = document.createElement('button');
```

New text:

```js
        actions.className = 'mp-installed-actions';
        _decorateInstalledRow(row, meta, actions, skill);
        const removeBtn = document.createElement('button');
```

6c. In `_renderInstalled`, standalone rows. Old text (6-space indent, followed by the Mine check):

```js
      actions.className = 'mp-installed-actions';
      if (skill.tier === 'Mine') {
```

New text:

```js
      actions.className = 'mp-installed-actions';
      _decorateInstalledRow(row, meta, actions, skill);
      if (skill.tier === 'Mine') {
```

6d. Append to the end of `web/static/style.css` (use `cat >> web/static/style.css <<'EOF'`; do not rewrite the file, it holds non-ASCII characters elsewhere):

```css

/* Install permission list and disabled rows (marketplace skill controls) */
.mp-permission-list {
  margin: 0 0 10px 18px;
  padding: 0;
  font-size: 0.875rem;
  color: var(--text-dim, #aaa);
}

.mp-installed-row.mp-installed-disabled .mp-installed-text {
  opacity: 0.6;
}

.mp-installed-disabled-label {
  font-size: 0.7rem;
  color: var(--warn, #f0a040);
}
```

- [ ] **Step 7: Run the tests and the syntax check**

Run:
```bash
node tests/marketplace_controls.test.js
node --check web/static/marketplace-pane.js
node tests/marketplace_verified_consent.test.js
node tests/marketplace_p0_ui.test.js
node tests/marketplace_p0_dom_render.test.js
node tests/marketplace_bundled_skill_registration.test.js
```
Expected: `marketplace_controls.test.js: ok`, `--check` prints nothing, the four older tests pass unchanged. If a wiring assertion fails, the named function still contains a raw `fetch(`; fix the site, not the test.

- [ ] **Step 8: Check it in a browser**

Start the app the usual way (`python web/app.py` or the dev launcher already used in this repo), open the Marketplace pane and check:
1. Browse tab, install a Community skill: the confirmation dialog lists the permission lines (`Reads these folders: ...`, `Network access: ...`), one click installs, and the skill appears under Installed.
2. Add tab, import a skill by URL and by local ZIP: after Install a permission card appears, Cancel installs nothing (Installed list unchanged), Install completes.
3. Installed tab: click Disable on a skill; the row dims with a "Disabled" label and the button reads Enable; ask the assistant for something that needs the skill and confirm it is not offered; click Enable and confirm it is back.
4. Open the browser console: no CSRF 403 errors during any of the above.

Report what was and was not checked; if the app cannot be started in the session, say so.

- [ ] **Step 9: Commit**

```bash
git add web/static/marketplace-pane.js web/static/style.css tests/marketplace_controls.test.js
git commit -m "feat: marketplace pane shows the permission card on every install path, sends the CSRF header, and adds Disable/Enable"
```
Do not add a Co-Authored-By line (project rule, CLAUDE.md).

### Task 9: Whole-suite check, acceptance walk-through, tracker and docs

After this task the full suite is green apart from the known baseline failures, the five acceptance criteria are each shown working against the real sandbox, and the tracker and plugin docs describe what was built and where it stops.

**Files:**
- Modify: `docs/security/threatmodel-remediation.md` (the `H_Malicious_marketplace_or_MCP_skill_execu_03` row), `docs/pluginArchitecture.md` (insert one section), `docs/superpowers/specs/2026-10-07-marketplace-skill-controls-design.md` (status line only)
- No new test files. Steps 1 and 2 only run existing tests.

**Interfaces:**
- Consumes: everything from Tasks 1 to 8.
- Produces: nothing code-level.

- [ ] **Step 1: Run the whole Python suite and the JS tests**

```bash
python -m pytest tests web/tests -q -x --deselect tests/marketplace/test_installer.py 2>&1 | tail -30
```
If `-x` stops on a known baseline failure (listed in Global Constraints), rerun without `-x`:
```bash
python -m pytest tests web/tests -q 2>&1 | tail -40
cd shell && node --test ../tests/*.test.js ../web/tests/*.test.js 2>&1 | tail -15; cd ..
python tools/check_javascript.py
```
Expected: the only failures and errors are the known baseline set from Global Constraints. Any other failure is ours: fix it before going on. Changed behaviour that existing tests encoded (a consent-less install now answering `consent_required`, hooks now sandboxed, `tools.py` no longer imported in-process) should already have been updated in Tasks 3 to 7; if one is still red, update the test to the new behaviour and note it in the commit message.

- [ ] **Step 2: Walk the five acceptance criteria against the real sandbox**

Run these as a scratch session (nothing here is committed). Use a temporary skill folder and the real sandbox, not the fakes.

1. Sandbox active (criterion 1): `python -c "import sys; sys.path.insert(0,'web'); import sandbox; print(sandbox.sandbox_level())"` prints a level that is not `none`. Then run the real-sandbox tests: `python -m pytest tests/marketplace/test_tool_sandbox.py tests/marketplace/test_hook_runner.py -q -k needs_sandbox -rs`. List any skipped test in the report.
2. Declared permissions only (criterion 2): from the `test_tool_sandbox.py` real-sandbox cases, confirm one passes that proves a tool cannot read a file outside its folder and the approved paths, and one that proves a tool with no approved network cannot connect.
3. Approval at install (criterion 3): start the app, install a skill from a local folder that has a `permissions:` block. The card must list the paths and hosts. Cancel and check that the skill is not in `installed-skills.json` and not on disk. Install again, approve, and check `installed-skills.json` now carries the `permissions` grant. Edit the source folder between the card and the Install click: the install must be refused with "The package changed since you reviewed it."
4. Outbound log (criterion 4): call a tool that connects to a host; `grep skill-outbound` in the app log shows `dest=<host>:<port>`, and a `skill-launch` line precedes it for every run.
5. Kill switch (criterion 5): Disable the skill in the Installed tab. Its tools are no longer offered, a direct call returns `skill is disabled`, its hooks do not run, and `installed-skills.json` shows `disabled: true`. Restart the app: it is still disabled. Enable: it works again.

Write what you ran and saw (and anything you could not run, such as macOS or Linux) into the report for the final review. If a criterion fails, stop and fix it in the task that owns it.

- [ ] **Step 3: Update the tracker row**

Run this from the repo root. It replaces the one row; it fails loudly if the row is not found.

```bash
python - <<'EOF'
import io, re
path = "docs/security/threatmodel-remediation.md"
text = io.open(path, encoding="utf-8").read()
prefix = "| `H_Malicious_marketplace_or_MCP_skill_execu_03` |"
lines = text.split("\n")
idx = [i for i, l in enumerate(lines) if l.startswith(prefix)]
assert len(idx) == 1, idx
lines[idx[0]] = (
    prefix
    + " Malicious marketplace/MCP skill execution | **Implemented (macOS/Linux not exercised; stdio MCP servers not sandboxed)**"
    + " | [design](../superpowers/specs/2026-10-07-marketplace-skill-controls-design.md) / [plan](../superpowers/plans/2026-10-07-marketplace-skill-controls.md)"
    + " | (1) Marketplace `tools.py` is never imported into the app: each tool call runs it in the OS sandbox (the same launcher the code runner uses), with no API keys in its environment, the skill folder and interpreter as runtime paths, only the approved `filesystem` paths readable, a fresh run folder as the only writable place, and network only when approved. Hooks run in the sandbox the same way and fail closed. (2) A skill declares `permissions: {filesystem: [...], network: [...]}` in its `SKILL.md` or `plugin.json`; a missing block means no filesystem beyond the skill folder and no network; a malformed block is treated as none and the card says so. Filesystem paths are read-only grants; hosts are shown and logged, not enforced per host. (3) Every install path (catalog, Verified plugin, URL import, URL plugin, local ZIP or folder) first answers `consent_required` with a plain list of the declared permissions, hooks, `bin/` files and MCP server commands plus a content digest, and writes nothing until the user approves; the approved call must carry the digest the card showed (a changed package is a 409). The grant is recorded in `installed-skills.json`. Install, install-local, disable and enable require the CSRF token. (4) Every sandboxed launch logs `skill-launch` (skill, kind, network, declared hosts) and every connection or name lookup made inside a `tools.py` run logs `skill-outbound dest=host:port` under logger `aigator.skill_audit`. (5) Kill switch: Disable on the Installed tab (or `POST /api/marketplace/disable/{id}`) stops the prompt loading, unloads and refuses its tools, takes `bin/` off the path, removes a bundle's MCP servers, deregisters its slash commands and skips its hooks; it survives restart and Enable restores it. Limits: stdio MCP servers shipped in a bundle are not sandboxed (the launcher is one-shot; the user sees each server's exact command before approving, and Disable stops them), so criterion 1 is partly met for bundles; network is all-or-nothing per run, so per-host limits are logged, not enforced; outbound logging sees only Python connections inside a `tools.py` handler (for hooks and scripts it logs the launch and the network flag), and a hostile skill can bypass or forge that log, so it is a record, not a control; Disable on a bundle wipes the credentials saved for its MCP servers; `tools.py` sandboxing covers standalone skills (a bundle's `tools.py` is not loaded by the app); a skill installed before this change has no recorded approval and gets no grants until it is reinstalled through the card; marketplace tools are loaded at install and Enable, not at app start (unchanged); URL imports and local picks now need one approval click; each tool call costs one process start (a no-op measured about 0.6 s, test limit 2 s); a slash command may stay in the menu until the next reload after Disable. Not exercised on macOS or Linux. |"
)
io.open(path, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
EOF
git diff --stat docs/security/threatmodel-remediation.md
```
Expected: one file changed, one line replaced (about 1 insertion and 1 deletion). Also check the severity summary at the top still reads right (it counts findings, not statuses, so it needs no edit).

- [ ] **Step 4: Add the controls section to `docs/pluginArchitecture.md`**

The file has non-ASCII characters, so insert with Python rather than the Edit tool. The new section goes directly above the line that starts `## 2026-08-07 Milestone`.

```bash
python - <<'EOF'
import io
path = "docs/pluginArchitecture.md"
text = io.open(path, encoding="utf-8").read()
marker = "## 2026-08-07 Milestone"
assert text.count("\n" + marker) == 1
section = """## Marketplace skill controls (2026-10-07)

Skills that arrive through the marketplace (catalog, URL, ZIP or folder) run under these controls. Native skills and your own skills are unchanged. Design: [marketplace skill controls](superpowers/specs/2026-10-07-marketplace-skill-controls-design.md).

- **Declared permissions.** A skill may declare `permissions:` with `filesystem` (paths it may read) and `network` (hosts it needs). No block means no filesystem access beyond its own folder and no network.
- **Approval at install.** Every install path shows what the package declares (permissions, hooks, `bin/` files, MCP server commands) and installs nothing until you approve. The approval is tied to the exact package you reviewed.
- **Sandbox.** `tools.py`, hooks and `bin/` shims run in the OS sandbox with only the approved access. `tools.py` is run once per tool call in its own process, so a tool call is a little slower than before and a `tools.py` that imports AI Gator internals will report an error.
- **Outbound log.** Every sandboxed launch and every connection made from inside a `tools.py` handler is logged (`skill-launch`, `skill-outbound`). This is a record, not a block.
- **Kill switch.** Disable on the Installed tab turns a skill off without deleting it; Enable turns it back on. Disabling a plugin bundle also removes its MCP connections and the credentials saved for them.

Known limits: stdio MCP servers in a bundle are not sandboxed, network access is all-or-nothing per run, and a skill installed before this change has no grants until it is reinstalled.

---

"""
i = text.index("\n" + marker) + 1
text = text[:i] + section + text[i:]
io.open(path, "w", encoding="utf-8", newline="").write(text)
EOF
git diff --stat docs/pluginArchitecture.md
```
Expected: only insertions. If `git diff` shows the whole file changed, the line endings were altered: run `git checkout -- docs/pluginArchitecture.md` after confirming `git status` shows nothing else of yours in that file, then redo the insert opening the file with `newline=""` for both read and write.

- [ ] **Step 5: Mark the spec as implemented**

In `docs/superpowers/specs/2026-10-07-marketplace-skill-controls-design.md`, add this line directly under the title line (line 1), with a blank line after it:

```
**Status:** Implemented on branch `security/threatmodel-remediation`. Plan: `docs/superpowers/plans/2026-10-07-marketplace-skill-controls.md`.
```

- [ ] **Step 6: Commit**

```bash
git status --short
git add docs/security/threatmodel-remediation.md docs/pluginArchitecture.md docs/superpowers/specs/2026-10-07-marketplace-skill-controls-design.md
git commit -m "docs: tracker, plugin architecture note and spec status for the marketplace skill controls"
```
`git status --short` before the add must show only your files plus the untracked `pip/` folder; never stage `pip/`. Do not add a Co-Authored-By line (project rule, CLAUDE.md).

---

## Self-review

**Spec coverage** (spec section, then where it is built):
- 1 Declared permissions: Task 1 (`permissions.py`, parse, summary, digest, malformed handling).
- 2 Install approval on every install path: Task 3 (installer reads the whole package, digest check, nothing written before approval), Task 4 (consent on catalog, Verified plugin, URL import, URL plugin, local ZIP or folder; CSRF; recorded grants), Task 8 (permission card on every path in the pane).
- 3 Enforcement: Task 5 (hooks in the sandbox, fail closed), Task 6 (`tools.py` per call in the sandbox, no in-process import, 2 s no-op timing test, `passthrough_sandbox` fixture).
- 4 Kill switch: Task 2 (`state.py` flag), Task 7 (`kill_switch.py`, routes, guards in `shared`, `commands`, `code_runner`), Task 8 (Disable / Enable button, dimmed row).
- 5 Outbound monitoring: Task 2 (`skill_audit.py`, launch log), Task 6 (runner audit hook and `skill-outbound`), Task 5 (launch log for hooks).
- Known limits to state: Task 9 tracker row and `pluginArchitecture.md` section; the same list goes in the final report.
- Testing section: unit tests in every task, real-sandbox acceptance walk-through in Task 9 Step 2.
- No gap found.

**Placeholder scan:** searched the assembled plan for TBD, TODO, "implement later", "fill in" and "similar to Task": none.

**Type consistency:** names were checked across tasks: `Permissions`, `summarize_package`, `files_digest`, `declared_permissions`, `readable_paths` (Task 1) are the ones Tasks 3 to 6 call; `state.is_disabled`, `state.set_disabled`, `state.record_approval`, `state.approved_permissions` (Task 2) are the ones Tasks 4 to 7 call; `sandbox_launch.run_in_sandbox` / `new_run_dir` and `skill_audit.extract_outbound` / `log_outbound` / `log_launch` (Task 2) are the ones Tasks 5 and 6 call; `kill_switch.disable` / `enable` (Task 7) are called only by the routes; the JS helpers `_postJson`, `_consentPayload`, `_postWithApproval`, `_confirmPermissions`, `_appendPermissionList`, `_toggleState`, `_decorateInstalledRow`, `_setSkillDisabled` are defined and used within Task 8 only. Response shapes (`consent_required`, `summary.lines`, `summary.digest`, `resolved_ref`, 409 `content_changed`, `{ok, skill_id, disabled}`) are the ones Task 4 and Task 7 produce and Task 8 consumes.
