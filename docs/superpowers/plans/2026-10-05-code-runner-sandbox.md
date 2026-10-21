# Code-runner Sandbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run model-written `run_python` code in an OS-level sandbox on Windows, macOS and Linux, and gate every widening of access (extra paths, network) on a real human approval the model cannot grant itself.

**Architecture:** A new stdlib-only package `web/sandbox/` exposes `SandboxRequest`, `SandboxResult`, `sandbox_level()`, `sandbox_unavailable_reason()` and `launch_sandboxed()`, dispatching to `launcher_windows.py` (AppContainer through `ctypes`, ported from the 2026-10-05 spike), `launcher_macos.py` (Seatbelt) or `launcher_linux.py` (bubblewrap). `run_python` builds a request (run folder, runtime paths, allow-list environment, approved extras), refuses to run without a matching approval stored server-side, and fails closed when the sandbox is unavailable. Approvals are granted only through CSRF-guarded routes clicked in a chat card; an admin policy file can tighten everything. Spec: `docs/superpowers/specs/2026-10-05-code-runner-sandbox-design.md`.

**Tech Stack:** Python 3.12 (`ctypes`, `subprocess`, `dataclasses`), FastAPI, vanilla JS (`web/static/app.js`), PyInstaller, pytest, Node (`node tests/*.test.js`), WSL Ubuntu with bubblewrap 0.11.1 for real Linux runs.

## Global Constraints

- Spec is the requirement: `docs/superpowers/specs/2026-10-05-code-runner-sandbox-design.md`. Every section maps to a task (see Self-Review).
- No new dependency. Windows: `ctypes` only, no admin. macOS: `/usr/bin/sandbox-exec` (ships with the OS). Linux: `bwrap` from the distro (`bubblewrap` package).
- `web/sandbox/` imports only the standard library (it is also imported by a bare `python3` inside WSL in Task 6). Launcher modules must import on every OS; Windows-only `ctypes.WinDLL` calls happen lazily inside functions.
- Fail closed: no matching approval means nothing runs; an unavailable sandbox means `run_python` returns an error unless the user opted out and the policy allows it; a present but bad policy file means `network: deny`, `filesystem: strict`, `require_sandbox: true`.
- The model can never approve: approvals change state only through `POST /api/sandbox/requests/{id}/approve|deny` guarded by `verify_csrf`; the opt-out changes only through `POST /api/sandbox/opt-out` guarded by `verify_csrf`; `code_runner_sandbox` must never be added to `PATCHABLE_CONFIG_KEYS`.
- Never-grantable deny list (even by the user): filesystem and drive roots, the home directory and its ancestors, `~/.gator` (except `~/.gator/outputs`), `~/.ssh`, `~/.aws`, `~/.azure`, `~/.kube`, `~/.gnupg`, `~/.config/gcloud`, and any ancestor of those.
- Telemetry is metadata only: run id, skill id, sandbox level (`enforced|off`), network (bool), extra read count, extra write count, approval decision. No paths, hosts, code or output.
- UI: model-supplied strings (paths, hosts, reasons) are set with `textContent` only; the new UI functions never use `innerHTML`.
- Do not modify `web/skills/shell_runner/` (`run_shell` stays unsandboxed; stated known gap).
- Windows grant model (deviation from the spec, see Task 4 rationale): runtime directories keep a persistent inheritable `RX` ACE for one per-user container SID (`AIGator.CodeRunner`); the run folder and approved extras are granted per run and revoked in `finally`; sandboxed runs are serialized. Reason: `icacls` grant and revoke each took ~8.5 s on a 30,000-file tree on this machine (2026-10-05), and `build/python_dist` has 30,568 files.
- Tests are hermetic: `tests/conftest.py` already redirects `HOME`/`USERPROFILE`; Task 2 redirects the policy path; real Windows tests use a temporary AppContainer profile `AIGator.Test.<hex>` and a temporary ledger, and at teardown revoke every ACE they added and delete the profile. They do temporarily add then remove an `RX` ACE on the test interpreter's directories.
- macOS code cannot run on this Windows machine: macOS is verified by profile-builder unit tests (every OS) plus a manual smoke test on a real Mac, which is a release gate. Same for a real Linux desktop (WSL is used here).
- Fake credential in tests and docs: `aigator-fake-api-key` only.
- Commits: explicit `git add <paths>` only (never `git add -A`, never the untracked `pip/` dir); no `Co-Authored-By` line; the product is "AI Gator", never "POC".
- New sandbox tests live in `tests/code_sandbox/` (never `tests/sandbox/`): a test package named `sandbox` can shadow `web/sandbox` on import.
- Full-suite command used in this repo: `python -m pytest tests -q -x --deselect tests/test_marketplace_installer.py`.

---

### Task 1: Frozen `aigator-backend --run-python` is slow to start and exit (switch the sidecar to onedir)

The spike reported the frozen `aigator-backend.exe --run-python` "hangs at exit even unsandboxed". It was reproduced while writing this plan (2026-10-05, current `dist/backend/aigator-backend.exe`, 136 MB onefile):

- `--run-python -c "print(1)"`: the first output appears after ~37 s, the process exits ~4.5 s later (total ~42 s, three runs). Output is correct; it is not a deadlock.
- `%TEMP%` held 45 leftover `_MEI*` directories.

Root cause: the spec builds a PyInstaller **onefile** binary, so every `--run-python` child re-extracts the whole bundle into `%TEMP%\_MEIxxxx` before Python starts and deletes it on exit. Under the sandbox `TEMP` is the run folder, so each run would also extract ~136 MB into `~/.gator/outputs/<run_id>`. Fix: build **onedir** (`COLLECT`) into `dist/backend/` so the executable path (`dist/backend/aigator-backend[.exe]`) used by `shell/main.js` and the release workflow does not change.

This task does not block Tasks 2-9: they work with either layout (the frozen runtime path is `Path(sys.executable).parent`).

**Files:**

- Modify: `packaging/aigator-backend.spec` (the `exe = EXE(...)` block at the end)
- Modify: `.github/workflows/release-desktop.yml:78` (PyInstaller command)
- Modify: `docs/BUILD_INSTRUCTIONS.md:95` and `:101` (PyInstaller commands), `AGENTS.md:101`
- Test: `tests/test_desktop_packaging.py` (append)

**Interfaces:**

- Consumes: nothing.
- Produces: onedir sidecar at `dist/backend/aigator-backend[.exe]` with `dist/backend/_internal/`; `sys.executable` parent is the bundle directory (used by Task 7 `_runtime_paths`).

- [ ] **Step 1: Reproduce and record the timing (no code change)**

Run (Git Bash, repo root, with the existing onefile build):

```bash
python - <<'PY'
import subprocess, time
exe = r"dist\backend\aigator-backend.exe"
t0 = time.time()
p = subprocess.Popen([exe, "--run-python", "-c", "print('ready', flush=True)"], stdout=subprocess.PIPE, text=True)
p.stdout.readline(); t1 = time.time()
p.wait(timeout=300); t2 = time.time()
print(f"first output {t1 - t0:.1f}s, exit {t2 - t1:.1f}s later, total {t2 - t0:.1f}s, rc={p.returncode}")
PY
ls "$TEMP" | grep -c _MEI
```

Expected: first output ~35-40 s, exit ~4-5 s later, rc=0; a non-zero count of `_MEI` dirs. Keep the printed numbers for the commit message.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_desktop_packaging.py`:

```python
def test_backend_sidecar_is_onedir_so_run_python_starts_fast():
    """A onefile sidecar re-extracts ~136 MB on every `--run-python` child
    (~37 s before the first line of output on Windows, 2026-10-05). The
    sidecar is built onedir into dist/backend/ instead; the executable path
    used by shell/main.js and the release workflow is unchanged."""
    spec = (ROOT / "packaging" / "aigator-backend.spec").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "release-desktop.yml").read_text(
        encoding="utf-8"
    )
    build_doc = (ROOT / "docs" / "BUILD_INSTRUCTIONS.md").read_text(encoding="utf-8")

    assert "exclude_binaries=True" in spec
    assert "COLLECT(" in spec
    assert 'name="backend"' in spec
    assert "--distpath dist --workpath build/pyinstaller-desktop" in workflow
    assert "--distpath dist/backend" not in workflow
    assert "--distpath dist/backend" not in build_doc
    assert "--distpath dist\\backend" not in build_doc
```

- [ ] **Step 3: Run it to verify it fails**

Run: `python -m pytest tests/test_desktop_packaging.py::test_backend_sidecar_is_onedir_so_run_python_starts_fast -q`
Expected: FAIL (`exclude_binaries=True` not in spec).

- [ ] **Step 4: Implement**

In `packaging/aigator-backend.spec` replace the whole `exe = EXE(...)` block with:

```python
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="aigator-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
# Onedir, not onefile: a onefile sidecar re-extracts the whole bundle into
# %TEMP% on every `--run-python` child (~37 s before Python starts on
# Windows, 2026-10-05). Built with `--distpath dist`, COLLECT writes
# dist/backend/aigator-backend[.exe] plus dist/backend/_internal/, so the
# path used by shell/main.js and the release workflow does not change.
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="backend",
)
```

In `.github/workflows/release-desktop.yml` line 78 change the command to:

```yaml
run: uv run pyinstaller --clean --noconfirm packaging/aigator-backend.spec --distpath dist --workpath build/pyinstaller-desktop
```

In `docs/BUILD_INSTRUCTIONS.md` change the Windows command (line 95) to:

```powershell
uv run pyinstaller --clean --noconfirm packaging\aigator-backend.spec --distpath dist --workpath build\pyinstaller-desktop
```

and the macOS/Linux command (line 101) and `AGENTS.md` line 101 to:

```bash
uv run pyinstaller --clean --noconfirm packaging/aigator-backend.spec --distpath dist --workpath build/pyinstaller-desktop
```

In `docs/BUILD_INSTRUCTIONS.md` under "Expected output" add a third bullet: `- Plus the bundle folder `dist/backend/\_internal/`(onedir build; ship the whole`dist/backend/` folder).`

- [ ] **Step 5: Run the packaging tests**

Run: `python -m pytest tests/test_desktop_packaging.py -q`
Expected: all pass.

- [ ] **Step 6: Build and measure (decision rule)**

Run: `uv run pyinstaller --clean --noconfirm packaging/aigator-backend.spec --distpath dist --workpath build/pyinstaller-desktop` then the Step 1 timing script again.

Decision rule:

- Total under 5 s: done, go to Step 8.
- First output under 5 s but exit still over 3 s: apply Step 7.
- First output still over 5 s: stop here, record the numbers in the commit message and the Task 9 tracker row, and continue with Task 2 (the sandbox works either way; frozen runs are just slow).
- The build cannot run (no network for `uv`, missing toolchain): skip the measurement, say so in the commit message, continue with Task 2.

- [ ] **Step 7 (only if Step 6 says so): exit immediately after the script finishes**

Append to `tests/test_desktop_packaging.py`:

```python
def test_run_python_mode_exits_without_interpreter_teardown(monkeypatch, capsys):
    backend_entry = _load_backend_entry()
    exits = []
    monkeypatch.setattr(backend_entry.sys, "argv", ["aigator-backend", "--run-python", "-c", "print('ready')"])
    monkeypatch.setattr(backend_entry.os, "_exit", lambda code: exits.append(code))
    backend_entry.main()
    assert capsys.readouterr().out.strip() == "ready"
    assert exits == [0]


def test_run_python_mode_reports_uncaught_errors(monkeypatch, capsys):
    backend_entry = _load_backend_entry()
    exits = []
    monkeypatch.setattr(backend_entry.sys, "argv", ["aigator-backend", "--run-python", "-c", "raise ValueError('boom')"])
    monkeypatch.setattr(backend_entry.os, "_exit", lambda code: exits.append(code))
    backend_entry.main()
    assert "ValueError: boom" in capsys.readouterr().err
    assert exits == [1]
```

In `packaging/backend_entry.py` add `import traceback` to the imports and replace

```python
    if args.run_python is not None:
        run_python(args.run_python)
        return
```

with

```python
    if args.run_python is not None:
        code = 0
        try:
            run_python(args.run_python)
        except SystemExit as exc:
            if isinstance(exc.code, int):
                code = exc.code
            elif exc.code is not None:
                print(exc.code, file=sys.stderr)
                code = 1
        except BaseException:
            traceback.print_exc()
            code = 1
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(code)
        return
```

Run: `python -m pytest tests/test_desktop_packaging.py -q`, rebuild, and re-run the timing script. Expected: tests pass; total under 5 s.

- [ ] **Step 8: Commit**

```bash
git add packaging/aigator-backend.spec .github/workflows/release-desktop.yml docs/BUILD_INSTRUCTIONS.md AGENTS.md tests/test_desktop_packaging.py
# add packaging/backend_entry.py too if Step 7 was applied
git commit -m "fix: build the backend sidecar onedir so --run-python starts in seconds (onefile re-extracted ~136 MB per run, ~42 s)"
```

---

### Task 2: `web/sandbox` core (types, policy, paths and deny list, environment, telemetry)

**Files:**

- Create: `web/sandbox/__init__.py`
- Create: `web/sandbox/policy.py`
- Create: `web/sandbox/paths.py`
- Modify: `tests/conftest.py` (append an autouse fixture)
- Modify: `packaging/aigator-backend.spec` (hidden imports, after the `hiddenimports += ["httpx_sse", "sse_starlette", "secure_store"]` line)
- Create: `tests/code_sandbox/__init__.py` (empty), `tests/code_sandbox/test_core.py`, `tests/code_sandbox/test_policy.py`, `tests/code_sandbox/test_paths.py`

**Interfaces:**

- Produces (in `sandbox`): `SandboxUnavailable(RuntimeError)`; `SandboxRequest(argv: list[str], cwd: Path, env: dict[str, str], runtime_paths: list[Path], read_paths: list[Path], write_paths: list[Path], network: bool, timeout: int)` (frozen dataclass); `SandboxResult(returncode: int, stdout: str, stderr: str, timed_out: bool)`; `sandbox_level() -> str` (`"enforced"|"unavailable"`); `sandbox_unavailable_reason() -> str | None`; `launch_sandboxed(req: SandboxRequest) -> SandboxResult` (raises `SandboxUnavailable`); `build_env(parent: Mapping[str, str], run_dir: Path, node_path: str | None, platform: str | None = None) -> dict[str, str]`; `telemetry_record(run_id: str, skill_id: str, level: str, network: bool, extra_read: int, extra_write: int, approval: str | None) -> dict`; `run_process_group(argv: list[str], cwd: Path, env: dict[str, str], timeout: int) -> SandboxResult` (POSIX); module globals `_PROBE`, `_launcher()`.
- Produces (in `sandbox.policy`): `Policy(code_runner: str = "enabled", network: str = "ask", filesystem: str = "ask", require_sandbox: bool = False)` with `.as_dict() -> dict`; `DEFAULT_POLICY`, `FAIL_CLOSED_POLICY`; `platform_policy_path(platform: str | None = None) -> Path`; `policy_path() -> Path` (the path for this OS; tests patch it); `parse_policy(text: str) -> Policy` (raises `ValueError`); `load_policy() -> Policy`; `_is_posix() -> bool`; `_reset_cache() -> None`.
- Produces (in `sandbox.paths`): `HOME_DENY: tuple[str, ...]`; `PathNotGrantable(ValueError)`; `is_within(child: Path, parent: Path) -> bool`; `check_grantable(path: Path, home: Path) -> None`; `normalize_grant_paths(raw, home: Path | None = None) -> list[Path]`; `normalize_hosts(raw) -> list[str]`.
- Each launcher module (Tasks 4-6) must provide `probe() -> str | None` (None means usable, otherwise the human-readable reason with the fix) and `launch(req: SandboxRequest) -> SandboxResult`.

- [ ] **Step 1: Write the failing tests**

Create `tests/code_sandbox/__init__.py` (empty file).

Create `tests/code_sandbox/test_core.py`:

```python
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import sandbox

FAKE = "aigator-fake-api-key"


def _req(tmp_path):
    return sandbox.SandboxRequest(
        argv=["python", "x.py"], cwd=tmp_path, env={}, runtime_paths=[], read_paths=[],
        write_paths=[], network=False, timeout=5,
    )


def test_build_env_windows_keeps_allow_list_and_drops_tokens(tmp_path):
    parent = {
        "Path": r"C:\Windows\System32", "SystemRoot": r"C:\Windows", "windir": r"C:\Windows",
        "ComSpec": r"C:\Windows\System32\cmd.exe", "PATHEXT": ".EXE", "GITHUB_TOKEN": FAKE,
        "JIRA_API_TOKEN": FAKE, "USERPROFILE": r"C:\Users\me", "OPENAI_API_KEY": FAKE,
    }
    env = sandbox.build_env(parent, tmp_path, r"C:\npm\node_modules", platform="win32")
    assert env["PATH"] == r"C:\Windows\System32"
    assert env["SYSTEMROOT"] == r"C:\Windows"
    assert env["COMSPEC"].endswith("cmd.exe")
    for key in ("TEMP", "TMP", "LOCALAPPDATA", "APPDATA", "USERPROFILE"):
        assert env[key] == str(tmp_path)
    assert env["NODE_PATH"] == r"C:\npm\node_modules"
    assert env["NODE_OPTIONS"] == "--preserve-symlinks --preserve-symlinks-main"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert FAKE not in env.values()
    assert not any("TOKEN" in k or "KEY" in k for k in env)


def test_build_env_posix(tmp_path):
    parent = {"PATH": "/usr/bin", "LANG": "C.UTF-8", "HOME": "/home/me", "GITHUB_TOKEN": FAKE}
    env = sandbox.build_env(parent, tmp_path, None, platform="linux")
    assert env == {
        "PATH": "/usr/bin", "LANG": "C.UTF-8", "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path), "PYTHONIOENCODING": "utf-8",
    }


def test_telemetry_record_is_metadata_only():
    rec = sandbox.telemetry_record("r1", "pptx", "enforced", True, 2, 1, "approved")
    assert rec == {
        "run_id": "r1", "skill_id": "pptx", "level": "enforced", "network": True,
        "extra_read": 2, "extra_write": 1, "approval": "approved",
    }


def test_level_is_probed_once_and_cached(monkeypatch):
    calls = []
    fake = SimpleNamespace(probe=lambda: calls.append(1))
    monkeypatch.setattr(sandbox, "_PROBE", None)
    monkeypatch.setattr(sandbox, "_launcher", lambda: fake)
    assert sandbox.sandbox_level() == "enforced"
    assert sandbox.sandbox_unavailable_reason() is None
    assert sandbox.sandbox_level() == "enforced"
    assert calls == [1]


def test_unavailable_reason_and_launch_refused(monkeypatch, tmp_path):
    fake = SimpleNamespace(probe=lambda: "install bubblewrap", launch=lambda req: pytest.fail("ran"))
    monkeypatch.setattr(sandbox, "_PROBE", None)
    monkeypatch.setattr(sandbox, "_launcher", lambda: fake)
    assert sandbox.sandbox_level() == "unavailable"
    assert sandbox.sandbox_unavailable_reason() == "install bubblewrap"
    with pytest.raises(sandbox.SandboxUnavailable, match="install bubblewrap"):
        sandbox.launch_sandboxed(_req(tmp_path))


def test_probe_exception_means_unavailable(monkeypatch):
    def boom():
        raise OSError("nope")

    monkeypatch.setattr(sandbox, "_PROBE", None)
    monkeypatch.setattr(sandbox, "_launcher", lambda: SimpleNamespace(probe=boom))
    assert sandbox.sandbox_level() == "unavailable"
    assert "OSError" in sandbox.sandbox_unavailable_reason()


def test_launch_delegates_when_enforced(monkeypatch, tmp_path):
    result = sandbox.SandboxResult(0, "ok", "", False)
    fake = SimpleNamespace(probe=lambda: None, launch=lambda req: result)
    monkeypatch.setattr(sandbox, "_PROBE", None)
    monkeypatch.setattr(sandbox, "_launcher", lambda: fake)
    assert sandbox.launch_sandboxed(_req(tmp_path)) is result


@pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX only")
def test_run_process_group_times_out_and_kills(tmp_path):
    res = sandbox.run_process_group(
        [sys.executable, "-c", "import time; print('hi', flush=True); time.sleep(30)"],
        tmp_path, dict(os.environ), 2,
    )
    assert res.timed_out and res.returncode == -1
    assert "hi" in res.stdout


def test_spec_bundles_sandbox_modules():
    spec = (Path(__file__).parents[2] / "packaging" / "aigator-backend.spec").read_text(encoding="utf-8")
    for name in ("sandbox", "sandbox.policy", "sandbox.paths", "sandbox.approvals",
                 "sandbox.launcher_windows", "sandbox.launcher_macos", "sandbox.launcher_linux"):
        assert f'"{name}"' in spec
```

Create `tests/code_sandbox/test_policy.py`:

```python
import pytest

from sandbox import policy as pol


@pytest.fixture
def policy_file(tmp_path, monkeypatch):
    path = tmp_path / "sandbox-policy.json"
    monkeypatch.setattr(pol, "policy_path", lambda: path)
    monkeypatch.setattr(pol, "_is_posix", lambda: False)
    pol._reset_cache()
    return path


def test_missing_file_gives_defaults(policy_file):
    assert pol.load_policy() == pol.Policy("enabled", "ask", "ask", False)


def test_valid_file_is_parsed(policy_file):
    policy_file.write_text('{"code_runner": "disabled", "network": "deny", "filesystem": "strict", "require_sandbox": true}')
    assert pol.load_policy() == pol.Policy("disabled", "deny", "strict", True)


def test_partial_file_keeps_defaults_for_missing_keys(policy_file):
    policy_file.write_text('{"network": "deny"}')
    assert pol.load_policy() == pol.Policy("enabled", "deny", "ask", False)


@pytest.mark.parametrize("text", [
    "not json", "[]", '{"network": "allow"}', '{"filesystem": 1}',
    '{"require_sandbox": "yes"}', '{"code_runner": "on"}',
])
def test_invalid_file_fails_closed(policy_file, text):
    policy_file.write_text(text)
    assert pol.load_policy() == pol.FAIL_CLOSED_POLICY
    assert pol.FAIL_CLOSED_POLICY == pol.Policy("enabled", "deny", "strict", True)


def test_unreadable_path_fails_closed(policy_file):
    policy_file.mkdir()  # a directory where the file should be: stat works, read fails
    assert pol.load_policy() == pol.FAIL_CLOSED_POLICY


def test_posix_writable_or_non_root_file_fails_closed(policy_file, monkeypatch):
    policy_file.write_text('{"network": "ask"}')
    monkeypatch.setattr(pol, "_is_posix", lambda: True)
    # tmp files are never root-owned on Linux/macOS, and on Windows os.stat
    # reports mode 0o666 (group/world-writable bits set): both must fail closed.
    assert pol.load_policy() == pol.FAIL_CLOSED_POLICY


def test_owner_check_accepts_root_owned_0644():
    from types import SimpleNamespace
    assert pol._posix_owner_ok(SimpleNamespace(st_uid=0, st_mode=0o100644))
    assert not pol._posix_owner_ok(SimpleNamespace(st_uid=0, st_mode=0o100664))
    assert not pol._posix_owner_ok(SimpleNamespace(st_uid=501, st_mode=0o100644))


def test_cache_follows_mtime(policy_file):
    import os
    policy_file.write_text('{"network": "deny"}')
    assert pol.load_policy().network == "deny"
    policy_file.write_text('{"network": "ask", "filesystem": "strict"}')
    st = policy_file.stat()
    os.utime(policy_file, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    assert pol.load_policy() == pol.Policy("enabled", "ask", "strict", False)


def test_policy_paths_per_platform(monkeypatch):
    monkeypatch.setenv("ProgramData", r"C:\ProgramData")
    assert pol.platform_policy_path("win32").parts[-2:] == ("AIGator", "sandbox-policy.json")
    assert pol.platform_policy_path("darwin").as_posix() == "/Library/Application Support/AIGator/sandbox-policy.json"
    assert pol.platform_policy_path("linux").as_posix() == "/etc/aigator/sandbox-policy.json"


def test_as_dict():
    assert pol.Policy().as_dict() == {
        "code_runner": "enabled", "network": "ask", "filesystem": "ask", "require_sandbox": False,
    }
```

Create `tests/code_sandbox/test_paths.py`:

```python
import pytest

from sandbox.paths import PathNotGrantable, check_grantable, is_within, normalize_grant_paths, normalize_hosts


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    for sub in (".ssh", ".aws", ".gator/outputs/run1", ".config/gcloud", "Documents/project"):
        (h / sub).mkdir(parents=True)
    (h / "Documents" / "project" / "notes.txt").write_text("n")
    return h.resolve()


def test_normalizes_dedupes_and_sorts(home):
    doc = home / "Documents" / "project"
    raw = [str(doc), str(doc / "notes.txt"), str(doc) + "/", str(doc / ".." / "project")]
    assert normalize_grant_paths(raw, home) == sorted({doc, doc / "notes.txt"}, key=lambda p: str(p).lower())


@pytest.mark.parametrize("rel", ["", ".ssh", ".ssh/id_rsa", ".aws", ".gator", ".gator/secrets",
                                  ".config", ".config/gcloud", ".config/gcloud/x"])
def test_deny_list_is_never_grantable(home, rel):
    with pytest.raises(PathNotGrantable):
        normalize_grant_paths([str(home / rel)], home)


def test_parent_of_home_and_roots_are_denied(home):
    with pytest.raises(PathNotGrantable):
        check_grantable(home.parent, home)
    with pytest.raises(PathNotGrantable):
        check_grantable(type(home)(home.anchor), home)


def test_gator_outputs_is_grantable(home):
    assert normalize_grant_paths([str(home / ".gator" / "outputs" / "run1")], home) == [
        home / ".gator" / "outputs" / "run1"
    ]


def test_relative_missing_and_bad_types_rejected(home):
    with pytest.raises(PathNotGrantable, match="absolute"):
        normalize_grant_paths(["Documents"], home)
    with pytest.raises(PathNotGrantable, match="does not exist"):
        normalize_grant_paths([str(home / "Documents" / "nope.txt")], home)
    with pytest.raises(PathNotGrantable):
        normalize_grant_paths([""], home)
    with pytest.raises(PathNotGrantable):
        normalize_grant_paths({"a": 1}, home)


def test_empty_is_empty(home):
    assert normalize_grant_paths(None, home) == []
    assert normalize_grant_paths([], home) == []


def test_is_within(home):
    assert is_within(home / "a" / "b", home)
    assert is_within(home, home)
    assert not is_within(home.parent / "homeX", home)


def test_hosts_normalized_and_validated():
    assert normalize_hosts(["API.Example.com:443", "api.example.com:443", "[::1]:8080"]) == [
        "[::1]:8080", "api.example.com:443",
    ]
    for bad in (["example.com"], ["example.com:0"], ["example.com:70000"], ["http://x:1"], [3]):
        with pytest.raises(ValueError):
            normalize_hosts(bad)
    assert normalize_hosts(None) == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/code_sandbox -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'sandbox'`.

- [ ] **Step 3: Implement**

Create `web/sandbox/__init__.py`:

```python
"""OS-level sandbox for model-written code.

One small interface over three mechanisms: Windows AppContainer
(launcher_windows), macOS Seatbelt (launcher_macos) and Linux bubblewrap
(launcher_linux). Spec: docs/superpowers/specs/2026-10-05-code-runner-sandbox-design.md.

Standard library only: tests/code_sandbox/posix_sandbox_check.py imports this
package from a bare WSL python3.
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

_log = logging.getLogger(__name__)


class SandboxUnavailable(RuntimeError):
    """The platform sandbox cannot run this request; nothing was executed."""


@dataclass(frozen=True)
class SandboxRequest:
    argv: list[str]            # command to run (python/node + script)
    cwd: Path                  # run folder; always read/write
    env: dict[str, str]        # complete child environment (already filtered)
    runtime_paths: list[Path]  # read+execute: interpreter, stdlib, site-packages, SKILL_DIR, NODE_PATH root
    read_paths: list[Path]     # extra read-only paths the user approved for this run
    write_paths: list[Path]    # extra read-write paths the user approved for this run
    network: bool              # outbound network approved for this run
    timeout: int


@dataclass
class SandboxResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool


_PROBE_LOCK = threading.Lock()
_PROBE: tuple[str, str | None] | None = None


def _launcher():
    """The launcher module for this OS, or None when there is none."""
    if sys.platform == "win32":
        from . import launcher_windows as module
    elif sys.platform == "darwin":
        from . import launcher_macos as module
    elif sys.platform.startswith("linux"):
        from . import launcher_linux as module
    else:
        return None
    return module


def _probe() -> tuple[str, str | None]:
    global _PROBE
    with _PROBE_LOCK:
        if _PROBE is None:
            try:
                module = _launcher()
                if module is None:
                    reason = f"No sandbox is available for platform {sys.platform}."
                else:
                    reason = module.probe()
            except Exception as exc:  # a broken probe must fail closed, never crash
                reason = f"The sandbox check failed ({type(exc).__name__})."
            _PROBE = ("enforced", None) if reason is None else ("unavailable", reason)
            if reason is not None:
                _log.warning("code sandbox unavailable: %s", reason)
        return _PROBE


def sandbox_level() -> str:
    """'enforced' or 'unavailable'. Probed once per process."""
    return _probe()[0]


def sandbox_unavailable_reason() -> str | None:
    return _probe()[1]


def launch_sandboxed(req: SandboxRequest) -> SandboxResult:
    if sandbox_level() != "enforced":
        raise SandboxUnavailable(sandbox_unavailable_reason() or "The sandbox is unavailable.")
    return _launcher().launch(req)


# ── Environment allow-list ────────────────────────────────────────────────────
# Everything not listed here (every token, API key, proxy credential) is dropped.
_WINDOWS_ENV = (
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS",
)
_WINDOWS_RUN_DIR_ENV = ("TEMP", "TMP", "LOCALAPPDATA", "APPDATA", "USERPROFILE")
_POSIX_ENV = ("PATH", "LANG", "LC_ALL", "LC_CTYPE")
# Node in an AppContainer fails with `EPERM lstat 'C:\'` unless symlinks are
# preserved (spike, 2026-10-05). NODE_OPTIONS reaches Node started by user code.
_NODE_OPTIONS_WINDOWS = "--preserve-symlinks --preserve-symlinks-main"


def build_env(parent: Mapping[str, str], run_dir: Path, node_path: str | None,
              platform: str | None = None) -> dict[str, str]:
    platform = platform or sys.platform
    if platform == "win32":
        upper = {k.upper(): v for k, v in parent.items()}
        env = {k: upper[k] for k in _WINDOWS_ENV if k in upper}
        for key in _WINDOWS_RUN_DIR_ENV:
            env[key] = str(run_dir)
        env["NODE_OPTIONS"] = _NODE_OPTIONS_WINDOWS
    else:
        env = {k: parent[k] for k in _POSIX_ENV if k in parent}
        env["HOME"] = str(run_dir)
        env["TMPDIR"] = str(run_dir)
    if node_path:
        env["NODE_PATH"] = node_path
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def telemetry_record(run_id: str, skill_id: str, level: str, network: bool,
                     extra_read: int, extra_write: int, approval: str | None) -> dict:
    """One metadata-only line per run for turn telemetry. Never paths, hosts, code or output."""
    return {
        "run_id": run_id,
        "skill_id": skill_id or "",
        "level": level,
        "network": bool(network),
        "extra_read": int(extra_read),
        "extra_write": int(extra_write),
        "approval": approval,
    }


def run_process_group(argv: list[str], cwd: Path, env: dict[str, str], timeout: int) -> SandboxResult:
    """POSIX: run in a new session and kill the whole group on timeout."""
    proc = subprocess.Popen(
        argv, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
    )
    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            for stream in (proc.stdout, proc.stderr):
                stream.close()
            proc.wait()
            out, err = b"", b""
    return SandboxResult(
        returncode=-1 if timed_out else proc.returncode,
        stdout=(out or b"").decode("utf-8", "replace"),
        stderr=(err or b"").decode("utf-8", "replace"),
        timed_out=timed_out,
    )
```

Create `web/sandbox/policy.py`:

```python
"""Machine-wide, admin-controlled sandbox policy.

One JSON file, read on each run (mtime cached):
  Windows  %ProgramData%\\AIGator\\sandbox-policy.json  (inherits the admin-only ProgramData ACL; not checked)
  macOS    /Library/Application Support/AIGator/sandbox-policy.json
  Linux    /etc/aigator/sandbox-policy.json
Missing file: defaults. Present but unreadable, invalid, or (POSIX) not
root-owned or group/world-writable: fail closed (network deny, filesystem
strict, sandbox required), logged once per reason.
"""
from __future__ import annotations

import json
import logging
import os
import stat
import sys
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Policy:
    code_runner: str = "enabled"   # enabled | disabled
    network: str = "ask"           # ask | deny
    filesystem: str = "ask"        # ask | strict
    require_sandbox: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


DEFAULT_POLICY = Policy()
FAIL_CLOSED_POLICY = Policy(code_runner="enabled", network="deny", filesystem="strict", require_sandbox=True)
_ALLOWED = {
    "code_runner": {"enabled", "disabled"},
    "network": {"ask", "deny"},
    "filesystem": {"ask", "strict"},
}

_LOCK = threading.Lock()
_CACHE: tuple[tuple, Policy] | None = None
_LOGGED: set[str] = set()


def platform_policy_path(platform: str | None = None) -> Path:
    platform = platform or sys.platform
    if platform == "win32":
        return Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "AIGator" / "sandbox-policy.json"
    if platform == "darwin":
        return Path("/Library/Application Support/AIGator/sandbox-policy.json")
    return Path("/etc/aigator/sandbox-policy.json")


def policy_path() -> Path:
    """The policy file for this OS (tests replace this function)."""
    return platform_policy_path()


def _is_posix() -> bool:
    return os.name == "posix"


def _posix_owner_ok(st) -> bool:
    return st.st_uid == 0 and not (st.st_mode & (stat.S_IWGRP | stat.S_IWOTH))


def _fail_closed(reason: str) -> Policy:
    if reason not in _LOGGED:
        _LOGGED.add(reason)
        _log.error("sandbox policy file %s; failing closed (network deny, filesystem strict, sandbox required)", reason)
    return FAIL_CLOSED_POLICY


def parse_policy(text: str) -> Policy:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("policy must be a JSON object")
    values: dict = {}
    for key, allowed in _ALLOWED.items():
        if key in data:
            if data[key] not in allowed:
                raise ValueError(f"invalid value for {key}")
            values[key] = data[key]
    if "require_sandbox" in data:
        if not isinstance(data["require_sandbox"], bool):
            raise ValueError("require_sandbox must be true or false")
        values["require_sandbox"] = data["require_sandbox"]
    return Policy(**values)


def load_policy() -> Policy:
    global _CACHE
    path = policy_path()
    try:
        st = path.stat()
    except FileNotFoundError:
        return DEFAULT_POLICY
    except OSError as exc:
        return _fail_closed(f"is unreadable ({type(exc).__name__})")
    if _is_posix() and not _posix_owner_ok(st):
        return _fail_closed("is not root-owned or is group/world-writable")
    stamp = (str(path), st.st_mtime_ns, st.st_size)
    with _LOCK:
        if _CACHE is not None and _CACHE[0] == stamp:
            return _CACHE[1]
    try:
        policy = parse_policy(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _fail_closed(f"is invalid ({type(exc).__name__})")
    with _LOCK:
        _CACHE = (stamp, policy)
    return policy


def _reset_cache() -> None:
    global _CACHE
    with _LOCK:
        _CACHE = None
    _LOGGED.clear()
```

Create `web/sandbox/paths.py`:

```python
"""Normalization of model-requested extra paths and hosts, and the never-grantable deny list."""
from __future__ import annotations

import os
import re
from pathlib import Path

HOME_DENY = (".ssh", ".aws", ".azure", ".kube", ".gnupg", ".config/gcloud")

_HOST_RE = re.compile(r"^(?:\[[0-9a-f:.]+\]|[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?):(\d{1,5})$")


class PathNotGrantable(ValueError):
    """The path can never be granted, or is not a valid absolute existing path."""


def _key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def is_within(child: Path, parent: Path) -> bool:
    c, p = _key(child), _key(parent)
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


def check_grantable(path: Path, home: Path) -> None:
    if path.parent == path:
        raise PathNotGrantable(f"{path} is a filesystem or drive root and can never be granted.")
    if is_within(home, path):
        raise PathNotGrantable(f"{path} is the home folder or contains it and can never be granted.")
    outputs = home / ".gator" / "outputs"
    for protected in [home / ".gator", *(home / d for d in HOME_DENY)]:
        inside = is_within(path, protected) and not is_within(path, outputs)
        if inside or is_within(protected, path):
            raise PathNotGrantable(f"{path} is a protected location and can never be granted.")


def normalize_grant_paths(raw, home: Path | None = None) -> list[Path]:
    """Absolute, resolved, existing, deduplicated, sorted. Raises PathNotGrantable."""
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        raise PathNotGrantable("Extra paths must be a list of absolute paths.")
    home_resolved = (Path(home) if home is not None else Path.home()).resolve()
    found: dict[str, Path] = {}
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise PathNotGrantable("Extra paths must be non-empty strings.")
        candidate = Path(os.path.expanduser(item.strip()))
        if not candidate.is_absolute():
            raise PathNotGrantable(f"{item} is not an absolute path.")
        resolved = candidate.resolve()
        check_grantable(resolved, home_resolved)
        if not resolved.exists():
            raise PathNotGrantable(f"{resolved} does not exist. Request an existing file or its folder.")
        found.setdefault(_key(resolved), resolved)
    return [found[k] for k in sorted(found)]


def normalize_hosts(raw) -> list[str]:
    """Lower-cased, validated host:port strings, deduplicated and sorted. Raises ValueError."""
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        raise ValueError("network_hosts must be a list of host:port strings.")
    hosts = set()
    for item in raw:
        text = item.strip().lower() if isinstance(item, str) else ""
        match = _HOST_RE.match(text)
        if not match or not 0 < int(match.group(1)) < 65536:
            raise ValueError(f"{item!r} is not a host:port value such as api.example.com:443.")
        hosts.add(text)
    return sorted(hosts)
```

Append to `tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def _hermetic_sandbox_policy(tmp_path, monkeypatch):
    """Never read the machine-wide sandbox policy (ProgramData, /Library, /etc) in tests."""
    from sandbox import policy

    monkeypatch.setattr(policy, "policy_path", lambda: tmp_path / "sandbox-policy.json")
    policy._reset_cache()
    yield
    policy._reset_cache()
```

In `packaging/aigator-backend.spec`, directly after `hiddenimports += ["httpx_sse", "sse_starlette", "secure_store"]`:

```python
# web/sandbox is imported with bare names (web/ is on pathex); launchers are
# imported lazily per OS, so list them all explicitly.
hiddenimports += [
    "sandbox", "sandbox.policy", "sandbox.paths", "sandbox.approvals",
    "sandbox.launcher_windows", "sandbox.launcher_macos", "sandbox.launcher_linux",
]
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/code_sandbox tests/test_desktop_packaging.py -q`
Expected: all pass (the POSIX-only test is skipped on Windows).

- [ ] **Step 5: Commit**

```bash
git add web/sandbox/__init__.py web/sandbox/policy.py web/sandbox/paths.py tests/conftest.py packaging/aigator-backend.spec tests/code_sandbox/__init__.py tests/code_sandbox/test_core.py tests/code_sandbox/test_policy.py tests/code_sandbox/test_paths.py
git commit -m "feat: sandbox core (request/result types, fail-closed policy file, path deny list, env allow-list, telemetry record)"
```

---

### Task 3: Approval store, approve/deny routes, status and opt-out routes

**Files:**

- Create: `web/sandbox/approvals.py`
- Create: `web/routes/sandbox_routes.py`
- Modify: `web/app.py` (router import next to line 70 `from routes.config_routes import router as config_router`; `app.include_router(sandbox_router)` after line 747 `app.include_router(auth_router)`)
- Create: `tests/code_sandbox/test_approvals.py`, `tests/test_sandbox_routes.py`

**Interfaces:**

- Consumes: `sandbox.sandbox_level()`, `sandbox.sandbox_unavailable_reason()`, `sandbox.policy.load_policy() -> Policy`, `Policy.as_dict()`, `security.verify_csrf`, `config.load_config()`, `config.update_config(mutator)`.
- Produces (in `sandbox.approvals`): `APPROVAL_TTL_SECONDS = 600`; `ApprovalError(status_code: int, detail: str)`; `ApprovalRequest(id: str, context_id: str, read_paths: tuple[str, ...], write_paths: tuple[str, ...], network_hosts: tuple[str, ...], created_at: float, status: str = "pending")`; `create(context_id, read_paths, write_paths, network_hosts, now=None) -> ApprovalRequest`; `lookup(context_id, read_paths, write_paths, network_hosts, now=None) -> tuple[str, ApprovalRequest | None]` where the status is `"none" | "pending" | "approved" | "denied" | "expired"` and `approved` consumes the request; `decide(request_id, context_id, approve: bool, now=None) -> ApprovalRequest`; `_reset()`; `_REQUESTS: dict[str, ApprovalRequest]`.
- Produces (HTTP): `POST /api/sandbox/requests/{id}/approve` and `/deny` with body `{"context_id": str}` (CSRF) returning `{"ok": true, "request_id", "status"}`; 404 unknown/consumed, 409 other tab or already decided, 410 expired. `GET /api/sandbox/status` returning `{"level", "reason", "opted_out", "policy"}`. `POST /api/sandbox/opt-out` with `{"opted_out": bool}` (CSRF), 409 when the policy requires the sandbox; stores `code_runner_sandbox: "off"` or removes the key.

- [ ] **Step 1: Write the failing tests**

Create `tests/code_sandbox/test_approvals.py`:

```python
import pytest

from sandbox import approvals


@pytest.fixture(autouse=True)
def _fresh():
    approvals._reset()
    yield
    approvals._reset()


R, W, H = ["C:/data"], ["C:/out"], ["api.example.com:443"]


def test_unknown_set_is_none():
    assert approvals.lookup("tab-1", R, W, H) == ("none", None)


def test_pending_then_approved_is_consumed_once():
    req = approvals.create("tab-1", R, W, H, now=100.0)
    assert approvals.lookup("tab-1", R, W, H, now=101.0) == ("pending", req)
    approvals.decide(req.id, "tab-1", True, now=102.0)
    status, got = approvals.lookup("tab-1", R, W, H, now=103.0)
    assert (status, got.id) == ("approved", req.id)
    assert approvals.lookup("tab-1", R, W, H, now=104.0) == ("none", None)


def test_exact_set_match_only():
    req = approvals.create("tab-1", R, [], [], now=100.0)
    approvals.decide(req.id, "tab-1", True, now=101.0)
    assert approvals.lookup("tab-1", R + ["C:/other"], [], [], now=102.0) == ("none", None)
    assert approvals.lookup("tab-1", [], R, [], now=102.0) == ("none", None)
    assert approvals.lookup("tab-1", ["c:/DATA"], [], [], now=102.0)[0] in ("approved", "none")


def test_other_tab_does_not_match():
    req = approvals.create("tab-1", R, W, H, now=100.0)
    approvals.decide(req.id, "tab-1", True, now=101.0)
    assert approvals.lookup("tab-2", R, W, H, now=102.0) == ("none", None)


def test_denied_reported_once():
    req = approvals.create("tab-1", R, W, H, now=100.0)
    approvals.decide(req.id, "tab-1", False, now=101.0)
    assert approvals.lookup("tab-1", R, W, H, now=102.0)[0] == "denied"
    assert approvals.lookup("tab-1", R, W, H, now=103.0) == ("none", None)


def test_expiry_after_ten_minutes():
    req = approvals.create("tab-1", R, W, H, now=100.0)
    approvals.decide(req.id, "tab-1", True, now=200.0)
    assert approvals.lookup("tab-1", R, W, H, now=100.0 + 601)[0] == "expired"


def test_decide_errors():
    with pytest.raises(approvals.ApprovalError) as e:
        approvals.decide("nope", "tab-1", True)
    assert e.value.status_code == 404
    req = approvals.create("tab-1", R, W, H, now=100.0)
    with pytest.raises(approvals.ApprovalError) as e:
        approvals.decide(req.id, "tab-2", True, now=101.0)
    assert e.value.status_code == 409
    with pytest.raises(approvals.ApprovalError) as e:
        approvals.decide(req.id, "tab-1", True, now=100.0 + 601)
    assert e.value.status_code == 410
    req2 = approvals.create("tab-1", R, [], [], now=100.0)
    approvals.decide(req2.id, "tab-1", True, now=101.0)
    with pytest.raises(approvals.ApprovalError) as e:
        approvals.decide(req2.id, "tab-1", False, now=102.0)
    assert e.value.status_code == 409
```

Note on `test_exact_set_match_only`: the case-insensitive key is `os.path.normcase`, which lower-cases on Windows and is the identity on POSIX; the last assertion accepts both.

Create `tests/test_sandbox_routes.py`:

```python
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest
from fastapi.testclient import TestClient

import config
import sandbox
from app import app
from sandbox import approvals
from sandbox.policy import Policy
import routes.sandbox_routes as sandbox_routes


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def csrf():
    from security import get_csrf_token

    return {"X-CSRF-Token": get_csrf_token()}


@pytest.fixture(autouse=True)
def _fresh():
    approvals._reset()
    yield
    approvals._reset()


@pytest.fixture
def cfg(monkeypatch):
    store = {}

    def update(mutator):
        result = mutator(dict(store))
        store.clear()
        store.update(result if result is not None else {})
        return dict(store)

    monkeypatch.setattr(config, "load_config", lambda: dict(store))
    monkeypatch.setattr(config, "update_config", update)
    return store


def test_approve_requires_csrf(client):
    req = approvals.create("tab-1", ["C:/data"], [], [])
    r = client.post(f"/api/sandbox/requests/{req.id}/approve", json={"context_id": "tab-1"})
    assert r.status_code == 403
    assert approvals._REQUESTS[req.id].status == "pending"


def test_approve_and_deny(client, csrf):
    a = approvals.create("tab-1", ["C:/a"], [], [])
    d = approvals.create("tab-1", ["C:/d"], [], [])
    r = client.post(f"/api/sandbox/requests/{a.id}/approve", json={"context_id": "tab-1"}, headers=csrf)
    assert r.status_code == 200 and r.json() == {"ok": True, "request_id": a.id, "status": "approved"}
    r = client.post(f"/api/sandbox/requests/{d.id}/deny", json={"context_id": "tab-1"}, headers=csrf)
    assert r.json()["status"] == "denied"


def test_wrong_tab_unknown_and_repeat(client, csrf):
    a = approvals.create("tab-1", ["C:/a"], [], [])
    assert client.post(f"/api/sandbox/requests/{a.id}/approve", json={"context_id": "tab-2"}, headers=csrf).status_code == 409
    assert client.post("/api/sandbox/requests/nope/approve", json={"context_id": "tab-1"}, headers=csrf).status_code == 404
    client.post(f"/api/sandbox/requests/{a.id}/approve", json={"context_id": "tab-1"}, headers=csrf)
    assert client.post(f"/api/sandbox/requests/{a.id}/deny", json={"context_id": "tab-1"}, headers=csrf).status_code == 409


def test_expired_is_410(client, csrf):
    a = approvals.create("tab-1", ["C:/a"], [], [])
    a.created_at -= 601
    assert client.post(f"/api/sandbox/requests/{a.id}/approve", json={"context_id": "tab-1"}, headers=csrf).status_code == 410


def test_status(client, cfg, monkeypatch):
    monkeypatch.setattr(sandbox, "sandbox_level", lambda: "unavailable")
    monkeypatch.setattr(sandbox, "sandbox_unavailable_reason", lambda: "install bubblewrap")
    cfg["code_runner_sandbox"] = "off"
    r = client.get("/api/sandbox/status")
    assert r.status_code == 200
    assert r.json() == {
        "level": "unavailable", "reason": "install bubblewrap", "opted_out": True,
        "policy": {"code_runner": "enabled", "network": "ask", "filesystem": "ask", "require_sandbox": False},
    }


def test_opt_out_requires_csrf_and_round_trips(client, csrf, cfg):
    assert client.post("/api/sandbox/opt-out", json={"opted_out": True}).status_code == 403
    assert "code_runner_sandbox" not in cfg
    assert client.post("/api/sandbox/opt-out", json={"opted_out": True}, headers=csrf).json() == {"ok": True, "opted_out": True}
    assert cfg["code_runner_sandbox"] == "off"
    client.post("/api/sandbox/opt-out", json={"opted_out": False}, headers=csrf)
    assert "code_runner_sandbox" not in cfg


def test_opt_out_refused_when_policy_requires_sandbox(client, csrf, cfg, monkeypatch):
    monkeypatch.setattr(sandbox_routes, "load_policy", lambda: Policy(require_sandbox=True))
    r = client.post("/api/sandbox/opt-out", json={"opted_out": True}, headers=csrf)
    assert r.status_code == 409
    assert "code_runner_sandbox" not in cfg


def test_opt_out_is_not_patchable_through_generic_config_route():
    assert "code_runner_sandbox" not in config.PATCHABLE_CONFIG_KEYS
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/code_sandbox/test_approvals.py tests/test_sandbox_routes.py -q`
Expected: FAIL (`ImportError` for `sandbox.approvals` / `routes.sandbox_routes`).

- [ ] **Step 3: Implement**

Create `web/sandbox/approvals.py`:

```python
"""Server-side store of sandbox access requests.

The model cannot approve its own request: a request changes state only via
decide(), which is reachable only from the CSRF-guarded routes in
routes/sandbox_routes.py. A run may use an approval only for the same tab and
exactly the same normalized set; an approval is used once and expires 10
minutes after the request was created. In-memory (single-process desktop
backend): a restart forgets pending requests, which only means asking again.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass

APPROVAL_TTL_SECONDS = 600


class ApprovalError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code


@dataclass
class ApprovalRequest:
    id: str
    context_id: str
    read_paths: tuple[str, ...]
    write_paths: tuple[str, ...]
    network_hosts: tuple[str, ...]
    created_at: float
    status: str = "pending"  # pending | approved | denied


_LOCK = threading.Lock()
_REQUESTS: dict[str, ApprovalRequest] = {}


def _key(read_paths, write_paths, network_hosts) -> tuple:
    def paths(items):
        return tuple(sorted({os.path.normcase(str(p)) for p in items}))

    return paths(read_paths), paths(write_paths), tuple(sorted({h.lower() for h in network_hosts}))


def _expired(req: ApprovalRequest, now: float) -> bool:
    return now - req.created_at > APPROVAL_TTL_SECONDS


def _purge(now: float) -> None:
    for rid in [r.id for r in _REQUESTS.values() if now - r.created_at > 2 * APPROVAL_TTL_SECONDS]:
        del _REQUESTS[rid]


def create(context_id: str, read_paths, write_paths, network_hosts, now: float | None = None) -> ApprovalRequest:
    now = time.time() if now is None else now
    req = ApprovalRequest(
        id=uuid.uuid4().hex, context_id=context_id or "",
        read_paths=tuple(str(p) for p in read_paths), write_paths=tuple(str(p) for p in write_paths),
        network_hosts=tuple(network_hosts), created_at=now,
    )
    with _LOCK:
        _purge(now)
        _REQUESTS[req.id] = req
    return req


def lookup(context_id: str, read_paths, write_paths, network_hosts,
           now: float | None = None) -> tuple[str, ApprovalRequest | None]:
    """Newest request for this tab and exactly this set.

    approved -> consumed (removed); denied/expired -> reported once (removed);
    pending -> left in place; no match -> ("none", None).
    """
    now = time.time() if now is None else now
    key = _key(read_paths, write_paths, network_hosts)
    with _LOCK:
        matches = [
            r for r in _REQUESTS.values()
            if r.context_id == (context_id or "") and _key(r.read_paths, r.write_paths, r.network_hosts) == key
        ]
        if not matches:
            return "none", None
        req = max(matches, key=lambda r: r.created_at)
        if _expired(req, now):
            del _REQUESTS[req.id]
            return "expired", req
        if req.status == "pending":
            return "pending", req
        del _REQUESTS[req.id]
        return req.status, req


def decide(request_id: str, context_id: str, approve: bool, now: float | None = None) -> ApprovalRequest:
    now = time.time() if now is None else now
    with _LOCK:
        req = _REQUESTS.get(request_id)
        if req is None:
            raise ApprovalError(404, "This access request was not found or was already used. Ask AI Gator to run the code again.")
        if req.context_id != (context_id or ""):
            raise ApprovalError(409, "This access request belongs to a different tab.")
        if _expired(req, now):
            raise ApprovalError(410, "This access request expired (requests last 10 minutes). Ask AI Gator to run the code again.")
        if req.status != "pending":
            raise ApprovalError(409, f"This access request was already {req.status}.")
        req.status = "approved" if approve else "denied"
        return req


def _reset() -> None:
    with _LOCK:
        _REQUESTS.clear()
```

Create `web/routes/sandbox_routes.py`:

```python
"""Code-runner sandbox routes: approval decisions, status, opt-out.

Approve/deny and opt-out are guarded by verify_csrf (same guard as
/api/drafts/{id}/approve), so the in-process agent loop cannot forge them.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sandbox
from sandbox import approvals
from sandbox.policy import load_policy
from security import verify_csrf

router = APIRouter()
_log = logging.getLogger(__name__)


class SandboxDecisionRequest(BaseModel):
    context_id: str = ""


class SandboxOptOutRequest(BaseModel):
    opted_out: bool


def _decide(request_id: str, body: SandboxDecisionRequest, approve: bool) -> dict:
    try:
        req = approvals.decide(request_id, body.context_id, approve)
    except approvals.ApprovalError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    # Metadata only: never log the paths or hosts.
    _log.info("sandbox approval decision=%s", req.status)
    return {"ok": True, "request_id": req.id, "status": req.status}


@router.post("/api/sandbox/requests/{request_id}/approve", dependencies=[Depends(verify_csrf)])
def approve_sandbox_request(request_id: str, body: SandboxDecisionRequest):
    return _decide(request_id, body, True)


@router.post("/api/sandbox/requests/{request_id}/deny", dependencies=[Depends(verify_csrf)])
def deny_sandbox_request(request_id: str, body: SandboxDecisionRequest):
    return _decide(request_id, body, False)


@router.get("/api/sandbox/status")
def sandbox_status():  # sync: the first call probes the OS sandbox
    from config import load_config

    return {
        "level": sandbox.sandbox_level(),
        "reason": sandbox.sandbox_unavailable_reason(),
        "opted_out": load_config().get("code_runner_sandbox") == "off",
        "policy": load_policy().as_dict(),
    }


@router.post("/api/sandbox/opt-out", dependencies=[Depends(verify_csrf)])
def set_sandbox_opt_out(body: SandboxOptOutRequest):
    if load_policy().require_sandbox:
        raise HTTPException(status_code=409, detail="Your administrator requires the code sandbox; it cannot be turned off.")
    from config import update_config

    def _apply(cfg: dict) -> dict:
        if body.opted_out:
            cfg["code_runner_sandbox"] = "off"
        else:
            cfg.pop("code_runner_sandbox", None)
        return cfg

    update_config(_apply)
    return {"ok": True, "opted_out": body.opted_out}
```

In `web/app.py` add after line 70 (`from routes.config_routes import router as config_router`):

```python
from routes.sandbox_routes import router as sandbox_router
```

and after `app.include_router(auth_router)`:

```python
app.include_router(sandbox_router)
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/code_sandbox tests/test_sandbox_routes.py tests/test_auth_clear_route.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add web/sandbox/approvals.py web/routes/sandbox_routes.py web/app.py tests/code_sandbox/test_approvals.py tests/test_sandbox_routes.py
git commit -m "feat: sandbox approval store and CSRF-guarded approve/deny, status and opt-out routes"
```

---

### Task 4: Windows AppContainer launcher

Port of `.superpowers/spike-appcontainer/ac.py` (proven on this machine 2026-10-05: run folder writable, other user files unreadable, external and loopback network blocked, parent secrets absent, extra-path grant and revoke work, Job Object kills the tree). Changes from the spike: separate stdout and stderr pipes, optional `internetClient` capability, the suspended process is terminated if the Job Object cannot be attached, the job is closed before joining the pump threads (kills lingering grandchildren so the pipes close), a ledger of grants, and a startup sweep.

Grant model rationale (deviation from the spec's "removed after the run" for runtime directories): measured on this machine, `icacls /grant ... (OI)(CI)RX` on a 30,000-file tree took 8.5 s and `/remove:g` another 8.5 s; `build/python_dist` has 30,568 files, the dev `.venv` 26,599 and the base interpreter 40,101. Per-run grant and revoke of runtime directories would add 17-40 s to every run. So one per-user profile `AIGator.CodeRunner` is reused, runtime directories get a persistent `RX` ACE for its SID (granted once, recorded in the ledger), and only the run folder and approved extras are granted per run and revoked. Because the SID is shared, runs are serialized (`_RUN_LOCK`) so one run's grants are never visible to another.

**Files:**

- Create: `web/sandbox/launcher_windows.py`
- Modify: `web/sandbox/__init__.py` (add `sweep_stale_grants()` after `launch_sandboxed`)
- Modify: `web/app.py` lifespan (before `from mcp.supervisor import respawn_all_on_startup, start_supervisor, stop_supervisor`, around line 689)
- Modify: `tests/conftest.py` (append the `windows_container` session fixture)
- Modify: `pytest.ini` (register the `real_sandbox` marker)
- Create: `tests/code_sandbox/test_launcher_windows.py`

**Interfaces:**

- Consumes: `SandboxRequest`, `SandboxResult`, `SandboxUnavailable`, `build_env` (Task 2).
- Produces (in `sandbox.launcher_windows`): `PROFILE_NAME = "AIGator.CodeRunner"`; `INTERNET_CLIENT_SID = "S-1-15-3-1"`; `ledger_path() -> Path` (`~/.gator/sandbox/grants.json`); `ace_spec(sid: str, perm: str, is_dir: bool) -> str`; `acl_grants(req) -> tuple[list[tuple[Path, str]], list[tuple[Path, str]]]` (runtime, per-run); `ensure_profile(name: str) -> tuple[c_void_p, str]`; `delete_profile(name: str) -> int`; `probe() -> str | None`; `launch(req) -> SandboxResult`; `sweep_stale_grants() -> int`; `revoke_runtime_grants() -> int`; private `_api()`, `_grant(path, sid, perm) -> tuple[int, str]`, `_revoke(path, sid) -> tuple[int, str]`, `_ledger_load() -> dict`, `_ledger_save(data)`, `_ledger_add_per_run(sid, path)`, `_ledger_remove_per_run(sid, path)`.
- Produces (in `sandbox`): `sweep_stale_grants() -> int` (0 off Windows, never raises).
- Produces (tests): session fixture `windows_container` yielding the `launcher_windows` module bound to a temporary profile and ledger; marker `real_sandbox`.

- [ ] **Step 1: Write the failing tests**

Add to `pytest.ini` (after the `pythonpath = web .` line):

```ini
markers =
    real_sandbox: runs a real OS sandbox (Windows AppContainer, or bubblewrap natively or through WSL); skipped where the mechanism is absent
```

Append to `tests/conftest.py`:

```python
@pytest.fixture(scope="session")
def windows_container(tmp_path_factory):
    """Real AppContainer launcher bound to a temporary profile and ledger.

    Creates AppContainer profile AIGator.Test.<hex> (HKCU) and deletes it at
    the end, revoking every ACE it added (per-run leftovers and the runtime
    RX grants on the test interpreter's directories)."""
    if sys.platform != "win32":
        pytest.skip("AppContainer is Windows only")
    import uuid

    from sandbox import launcher_windows as lw

    name = f"AIGator.Test.{uuid.uuid4().hex[:8]}"
    ledger = tmp_path_factory.mktemp("sandbox-ledger") / "grants.json"
    mp = pytest.MonkeyPatch()
    mp.setattr(lw, "PROFILE_NAME", name)
    mp.setattr(lw, "ledger_path", lambda: ledger)
    try:
        yield lw
    finally:
        lw.sweep_stale_grants()
        lw.revoke_runtime_grants()
        lw.delete_profile(name)
        mp.undo()
```

Create `tests/code_sandbox/test_launcher_windows.py`:

```python
import json
import os
import socket
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import sandbox
from sandbox import SandboxRequest, build_env
from sandbox import launcher_windows as lw

FAKE = "aigator-fake-api-key"


# ── Pure helpers: every OS ───────────────────────────────────────────────────

def test_ace_spec_uses_inheritance_only_for_directories():
    assert lw.ace_spec("S-1-15-2-1", "RX", True) == "*S-1-15-2-1:(OI)(CI)RX"
    assert lw.ace_spec("S-1-15-2-1", "M", False) == "*S-1-15-2-1:M"


def test_acl_grants_split_runtime_from_per_run():
    req = SandboxRequest(
        argv=["python"], cwd=Path("C:/run"), env={}, runtime_paths=[Path("C:/py")],
        read_paths=[Path("C:/data")], write_paths=[Path("C:/out")], network=False, timeout=5,
    )
    runtime, per_run = lw.acl_grants(req)
    assert runtime == [(Path("C:/py"), "RX")]
    assert per_run == [(Path("C:/data"), "RX"), (Path("C:/out"), "M"), (Path("C:/run"), "M")]


def test_ledger_round_trip_and_corrupt_file(tmp_path, monkeypatch):
    ledger = tmp_path / "g.json"
    monkeypatch.setattr(lw, "ledger_path", lambda: ledger)
    lw._ledger_add_per_run("S-1-15-2-9", tmp_path)
    assert lw._ledger_load()["per_run"] == [["S-1-15-2-9", str(tmp_path)]]
    lw._ledger_remove_per_run("S-1-15-2-9", tmp_path)
    assert lw._ledger_load()["per_run"] == []
    ledger.write_text("not json")
    assert lw._ledger_load() == {"runtime": {}, "per_run": []}


def test_sweep_revokes_and_clears_ledger_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(lw, "ledger_path", lambda: tmp_path / "g.json")
    revoked = []
    monkeypatch.setattr(lw, "_revoke", lambda path, sid: revoked.append((str(path), sid)) or (0, ""))
    lw._ledger_add_per_run("S-1-15-2-9", tmp_path)
    assert lw.sweep_stale_grants() == 1
    assert revoked == [(str(tmp_path), "S-1-15-2-9")]
    assert lw._ledger_load()["per_run"] == []


def test_package_sweep_is_noop_off_windows(monkeypatch):
    monkeypatch.setattr(sandbox.sys, "platform", "linux")
    assert sandbox.sweep_stale_grants() == 0


def test_app_sweeps_stale_grants_at_startup():
    app_src = (Path(__file__).parents[2] / "web" / "app.py").read_text(encoding="utf-8")
    assert "_sandbox.sweep_stale_grants" in app_src


# ── Real AppContainer runs: Windows only ─────────────────────────────────────

PROBE = r'''
import json, os, socket, sys
r = {}
def t(name, f):
    try:
        r[name] = "OK:" + str(f())[:60]
    except Exception as e:
        r[name] = "DENIED:" + type(e).__name__
t("write_run_dir", lambda: open("out.txt", "w").write("hi"))
t("read_secret", lambda: open(sys.argv[1]).read())
t("read_extra", lambda: open(sys.argv[2]).read())
t("net_external", lambda: socket.create_connection(("1.1.1.1", 443), 3).getpeername())
t("net_loopback", lambda: socket.create_connection(("127.0.0.1", int(sys.argv[3])), 3).getpeername())
r["token"] = os.environ.get("GITHUB_TOKEN")
r["encoding"] = os.environ.get("PYTHONIOENCODING")
print(json.dumps(r))
'''

def _runtime():
    return sorted({Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve()}, key=str)


@pytest.fixture
def layout(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (tmp_path / "secret").mkdir()
    (tmp_path / "secret" / "s.txt").write_text("dummy-secret")
    (tmp_path / "extra").mkdir()
    (tmp_path / "extra" / "e.txt").write_text("extra-data")
    (run / "probe.py").write_text(PROBE, encoding="utf-8")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    yield SimpleNamespace(
        run=run, secret=tmp_path / "secret" / "s.txt", extra_dir=tmp_path / "extra",
        extra=tmp_path / "extra" / "e.txt", port=listener.getsockname()[1],
    )
    listener.close()


def _probe(lw_mod, layout, read_paths=(), network=False):
    env = build_env(dict(os.environ, GITHUB_TOKEN=FAKE), layout.run, None)
    req = SandboxRequest(
        argv=[sys.executable, str(layout.run / "probe.py"), str(layout.secret), str(layout.extra), str(layout.port)],
        cwd=layout.run, env=env, runtime_paths=_runtime(), read_paths=list(read_paths),
        write_paths=[], network=network, timeout=60,
    )
    res = lw_mod.launch(req)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


@pytest.mark.real_sandbox
@pytest.mark.skipif(sys.platform != "win32", reason="AppContainer is Windows only")
class TestRealAppContainer:
    def test_default_run_is_contained(self, windows_container, layout):
        r = _probe(windows_container, layout)
        assert r["write_run_dir"].startswith("OK")
        assert r["read_secret"].startswith("DENIED")
        assert r["read_extra"].startswith("DENIED")
        assert r["net_external"].startswith("DENIED")
        assert r["net_loopback"].startswith("DENIED")
        assert r["token"] is None
        assert r["encoding"] == "utf-8"

    def test_extra_read_grant_applies_to_one_run_only(self, windows_container, layout):
        assert _probe(windows_container, layout, read_paths=[layout.extra_dir])["read_extra"] == "OK:extra-data"
        assert _probe(windows_container, layout)["read_extra"].startswith("DENIED")
        assert json.loads(windows_container.ledger_path().read_text())["per_run"] == []

    def test_sweep_removes_grants_left_by_a_crash(self, windows_container, layout):
        lw_mod = windows_container
        psid, sid = lw_mod.ensure_profile(lw_mod.PROFILE_NAME)
        lw_mod._api().adv.FreeSid(psid)
        lw_mod._ledger_add_per_run(sid, layout.extra_dir)
        assert lw_mod._grant(layout.extra_dir, sid, "RX")[0] == 0
        assert _probe(lw_mod, layout)["read_extra"] == "OK:extra-data"
        assert lw_mod.sweep_stale_grants() == 1
        assert _probe(lw_mod, layout)["read_extra"].startswith("DENIED")

    def test_timeout_kills_the_process_tree(self, windows_container, tmp_path):
        import psutil

        run = tmp_path / "run"
        run.mkdir()
        (run / "tree.py").write_text(
            "import subprocess, sys, time\n"
            "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
            "open('child.pid', 'w').write(str(p.pid))\n"
            "print('started', flush=True)\n"
            "time.sleep(120)\n",
            encoding="utf-8",
        )
        res = windows_container.launch(SandboxRequest(
            argv=[sys.executable, str(run / "tree.py")], cwd=run, env=build_env(os.environ, run, None),
            runtime_paths=_runtime(), read_paths=[], write_paths=[], network=False, timeout=10,
        ))
        assert res.timed_out and res.returncode == -1
        time.sleep(1)
        assert not psutil.pid_exists(int((run / "child.pid").read_text()))

    def test_network_capability_only_when_approved(self, windows_container, layout):
        try:
            socket.create_connection(("1.1.1.1", 443), 3).close()
        except OSError:
            pytest.skip("this machine cannot reach 1.1.1.1:443")
        assert _probe(windows_container, layout, network=True)["net_external"].startswith("OK")
        assert _probe(windows_container, layout)["net_external"].startswith("DENIED")

    def test_overhead_after_runtime_grants_exist(self, windows_container, layout):
        _probe(windows_container, layout)
        started = time.monotonic()
        _probe(windows_container, layout)
        elapsed = time.monotonic() - started
        print(f"sandboxed probe run took {elapsed:.1f}s")
        assert elapsed < 15
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/code_sandbox/test_launcher_windows.py -q`
Expected: FAIL (`ImportError: cannot import name 'launcher_windows'`).

- [ ] **Step 3: Implement**

Create `web/sandbox/launcher_windows.py`:

```python
"""Windows AppContainer launcher: ctypes only, no admin, no new dependency.

Ported from the 2026-10-05 spike (.superpowers/spike-appcontainer/ac.py).

Grant model (plan Task 4): one per-user AppContainer profile (PROFILE_NAME) is
reused. Runtime directories get a persistent inheritable read+execute ACE for
its SID, granted once and recorded in the ledger (re-granting ~30k files costs
~8.5 s each way). The run folder and user-approved extras are granted for one
run and revoked in `finally`; runs are serialized so one run's grants are
never visible to another. Every per-run grant is written to the ledger before
icacls runs; sweep_stale_grants() (server startup) revokes leftovers of a
crashed run. icacls works without admin because the user owns these paths
(per-user install). System32 is covered by ALL APPLICATION PACKAGES.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

from . import SandboxRequest, SandboxResult, SandboxUnavailable

_log = logging.getLogger(__name__)

PROFILE_NAME = "AIGator.CodeRunner"
INTERNET_CLIENT_SID = "S-1-15-3-1"

PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
EXTENDED_STARTUPINFO_PRESENT = 0x80000
CREATE_UNICODE_ENVIRONMENT = 0x400
CREATE_SUSPENDED = 0x4
CREATE_NO_WINDOW = 0x08000000
STARTF_USESTDHANDLES = 0x100
HANDLE_FLAG_INHERIT = 0x1
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
WAIT_TIMEOUT = 258
SE_GROUP_ENABLED = 0x4
GENERIC_READ = 0x80000000
FILE_SHARE_READ_WRITE = 0x3
OPEN_EXISTING = 3
HRESULT_ALREADY_EXISTS = ctypes.c_long(0x800700B7).value

_RUN_LOCK = threading.Lock()
_LEDGER_LOCK = threading.Lock()
_API: SimpleNamespace | None = None


def ledger_path() -> Path:
    return Path.home() / ".gator" / "sandbox" / "grants.json"


# ── Pure helpers (unit-tested on every OS) ──────────────────────────────────

def ace_spec(sid: str, perm: str, is_dir: bool) -> str:
    return f"*{sid}:(OI)(CI){perm}" if is_dir else f"*{sid}:{perm}"


def acl_grants(req: SandboxRequest) -> tuple[list[tuple[Path, str]], list[tuple[Path, str]]]:
    """(persistent runtime grants, per-run grants)."""
    runtime = [(Path(p), "RX") for p in req.runtime_paths]
    per_run = (
        [(Path(p), "RX") for p in req.read_paths]
        + [(Path(p), "M") for p in req.write_paths]
        + [(Path(req.cwd), "M")]
    )
    return runtime, per_run


# ── Win32 API (loaded lazily so this module imports on every OS) ────────────

def _api() -> SimpleNamespace:
    global _API
    if _API is not None:
        return _API
    import ctypes.wintypes as wt

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    HANDLE, PVOID = wt.HANDLE, ctypes.c_void_p

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", PVOID), ("Attributes", wt.DWORD)]

    class SECURITY_CAPABILITIES(ctypes.Structure):
        _fields_ = [("AppContainerSid", PVOID), ("Capabilities", PVOID),
                    ("CapabilityCount", wt.DWORD), ("Reserved", wt.DWORD)]

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR), ("lpTitle", wt.LPWSTR),
                    ("dwX", wt.DWORD), ("dwY", wt.DWORD), ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
                    ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD),
                    ("dwFlags", wt.DWORD), ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
                    ("lpReserved2", PVOID), ("hStdInput", HANDLE), ("hStdOutput", HANDLE), ("hStdError", HANDLE)]

    class STARTUPINFOEXW(ctypes.Structure):
        _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", PVOID)]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", HANDLE), ("hThread", HANDLE), ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]

    class SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("nLength", wt.DWORD), ("lpSecurityDescriptor", PVOID), ("bInheritHandle", wt.BOOL)]

    class BASIC_LIMIT(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wt.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wt.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wt.DWORD), ("SchedulingClass", wt.DWORD)]

    class EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [("Basic", BASIC_LIMIT), ("IoInfo", ctypes.c_uint64 * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32.CreateProcessW.argtypes = [wt.LPCWSTR, wt.LPWSTR, PVOID, PVOID, wt.BOOL, wt.DWORD, PVOID, wt.LPCWSTR, PVOID, PVOID]
    k32.CreateProcessW.restype = wt.BOOL
    k32.CreatePipe.argtypes = [ctypes.POINTER(HANDLE), ctypes.POINTER(HANDLE), PVOID, wt.DWORD]
    k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, PVOID, wt.DWORD, wt.DWORD, HANDLE]
    k32.CreateFileW.restype = HANDLE
    k32.ReadFile.argtypes = [HANDLE, PVOID, wt.DWORD, ctypes.POINTER(wt.DWORD), PVOID]
    k32.CloseHandle.argtypes = [HANDLE]
    k32.WaitForSingleObject.argtypes = [HANDLE, wt.DWORD]
    k32.WaitForSingleObject.restype = wt.DWORD
    k32.GetExitCodeProcess.argtypes = [HANDLE, ctypes.POINTER(wt.DWORD)]
    k32.ResumeThread.argtypes = [HANDLE]
    k32.TerminateProcess.argtypes = [HANDLE, wt.UINT]
    k32.SetHandleInformation.argtypes = [HANDLE, wt.DWORD, wt.DWORD]
    k32.CreateJobObjectW.argtypes = [PVOID, wt.LPCWSTR]
    k32.CreateJobObjectW.restype = HANDLE
    k32.SetInformationJobObject.argtypes = [HANDLE, ctypes.c_int, PVOID, wt.DWORD]
    k32.AssignProcessToJobObject.argtypes = [HANDLE, HANDLE]
    k32.TerminateJobObject.argtypes = [HANDLE, wt.UINT]
    k32.InitializeProcThreadAttributeList.argtypes = [PVOID, wt.DWORD, wt.DWORD, ctypes.POINTER(ctypes.c_size_t)]
    k32.UpdateProcThreadAttribute.argtypes = [PVOID, wt.DWORD, ctypes.c_size_t, PVOID, ctypes.c_size_t, PVOID, PVOID]
    k32.DeleteProcThreadAttributeList.argtypes = [PVOID]
    k32.LocalFree.argtypes = [PVOID]
    userenv.CreateAppContainerProfile.argtypes = [wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, PVOID, wt.DWORD, ctypes.POINTER(PVOID)]
    userenv.CreateAppContainerProfile.restype = ctypes.c_long
    userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [wt.LPCWSTR, ctypes.POINTER(PVOID)]
    userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.c_long
    userenv.DeleteAppContainerProfile.argtypes = [wt.LPCWSTR]
    userenv.DeleteAppContainerProfile.restype = ctypes.c_long
    adv.ConvertSidToStringSidW.argtypes = [PVOID, ctypes.POINTER(wt.LPWSTR)]
    adv.ConvertStringSidToSidW.argtypes = [wt.LPCWSTR, ctypes.POINTER(PVOID)]
    adv.FreeSid.argtypes = [PVOID]

    _API = SimpleNamespace(
        wt=wt, k32=k32, adv=adv, userenv=userenv, HANDLE=HANDLE, PVOID=PVOID,
        SID_AND_ATTRIBUTES=SID_AND_ATTRIBUTES, SECURITY_CAPABILITIES=SECURITY_CAPABILITIES,
        STARTUPINFOEXW=STARTUPINFOEXW, PROCESS_INFORMATION=PROCESS_INFORMATION,
        SECURITY_ATTRIBUTES=SECURITY_ATTRIBUTES, EXTENDED_LIMIT=EXTENDED_LIMIT,
    )
    return _API


def _sid_str(psid) -> str:
    a = _api()
    s = a.wt.LPWSTR()
    if not a.adv.ConvertSidToStringSidW(psid, ctypes.byref(s)):
        raise ctypes.WinError(ctypes.get_last_error())
    value = s.value
    a.k32.LocalFree(s)
    return value


def ensure_profile(name: str):
    """Create (or reuse) the AppContainer profile; returns (psid, sid_string). Free psid with FreeSid."""
    a = _api()
    psid = a.PVOID()
    hr = a.userenv.CreateAppContainerProfile(name, name, "AI Gator code sandbox", None, 0, ctypes.byref(psid))
    if hr == HRESULT_ALREADY_EXISTS:
        hr = a.userenv.DeriveAppContainerSidFromAppContainerName(name, ctypes.byref(psid))
    if hr != 0:
        raise OSError(f"AppContainer profile failed hr=0x{hr & 0xFFFFFFFF:08X}")
    return psid, _sid_str(psid)


def delete_profile(name: str) -> int:
    return _api().userenv.DeleteAppContainerProfile(name) & 0xFFFFFFFF


# ── icacls and the grant ledger ─────────────────────────────────────────────

def _icacls(path: Path, *args: str) -> tuple[int, str]:
    r = subprocess.run(
        ["icacls", str(path), *args], capture_output=True, text=True, errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    return r.returncode, (r.stdout + r.stderr).strip()


def _grant(path: Path, sid: str, perm: str) -> tuple[int, str]:
    return _icacls(path, "/grant", ace_spec(sid, perm, Path(path).is_dir()), "/Q")


def _revoke(path: Path, sid: str) -> tuple[int, str]:
    return _icacls(path, "/remove:g", f"*{sid}", "/Q")


def _ledger_load() -> dict:
    try:
        data = json.loads(ledger_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError):
        _log.warning("sandbox grant ledger unreadable; starting a new one")
        data = {}
    if not isinstance(data, dict):
        data = {}
    runtime = data.get("runtime") if isinstance(data.get("runtime"), dict) else {}
    per_run = data.get("per_run") if isinstance(data.get("per_run"), list) else []
    return {"runtime": runtime, "per_run": per_run}


def _ledger_save(data: dict) -> None:
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def _ledger_add_per_run(sid: str, path: Path) -> None:
    with _LEDGER_LOCK:
        data = _ledger_load()
        data["per_run"].append([sid, str(path)])
        _ledger_save(data)


def _ledger_remove_per_run(sid: str, path: Path) -> None:
    with _LEDGER_LOCK:
        data = _ledger_load()
        entry = [sid, str(path)]
        if entry in data["per_run"]:
            data["per_run"].remove(entry)
            _ledger_save(data)


def _ensure_runtime_grants(sid: str, paths: list[Path]) -> None:
    with _LEDGER_LOCK:
        data = _ledger_load()
        done = set(data["runtime"].get(sid, []))
        changed = False
        for path in paths:
            key = os.path.normcase(str(path))
            if key in done:
                continue
            rc, out = _grant(path, sid, "RX")
            if rc == 0:
                done.add(key)
                changed = True
            else:
                # Not owned by the user (for example C:\Program Files\nodejs): rely on
                # the default ALL APPLICATION PACKAGES access. A missing grant can only
                # reduce access, never widen it.
                _log.info("sandbox: runtime path not granted (%s); relying on existing access", path)
        if changed:
            data["runtime"][sid] = sorted(done)
            _ledger_save(data)


def sweep_stale_grants() -> int:
    """Revoke per-run grants left by a crashed run. Returns the number of entries cleared."""
    with _RUN_LOCK, _LEDGER_LOCK:
        data = _ledger_load()
        entries = list(data["per_run"])
        for sid, path in entries:
            if Path(path).exists():
                _revoke(Path(path), sid)
        if entries:
            data["per_run"] = []
            _ledger_save(data)
        return len(entries)


def revoke_runtime_grants() -> int:
    """Remove the persistent runtime ACEs (tests and manual cleanup)."""
    with _RUN_LOCK, _LEDGER_LOCK:
        data = _ledger_load()
        count = 0
        for sid, paths in data["runtime"].items():
            for path in paths:
                if Path(path).exists():
                    _revoke(Path(path), sid)
                    count += 1
        data["runtime"] = {}
        _ledger_save(data)
        return count


# ── Process launch ──────────────────────────────────────────────────────────

def _run_contained(argv: list[str], cwd: Path, env: dict[str, str], psid, timeout: int, network: bool) -> SandboxResult:
    a = _api()
    k32, wt, HANDLE = a.k32, a.wt, a.HANDLE
    sa = a.SECURITY_ATTRIBUTES(ctypes.sizeof(a.SECURITY_ATTRIBUTES), None, True)

    def pipe():
        rd, wr = HANDLE(), HANDLE()
        if not k32.CreatePipe(ctypes.byref(rd), ctypes.byref(wr), ctypes.byref(sa), 0):
            raise ctypes.WinError(ctypes.get_last_error())
        k32.SetHandleInformation(rd, HANDLE_FLAG_INHERIT, 0)
        return rd, wr

    out_rd, out_wr = pipe()
    err_rd, err_wr = pipe()
    hin = k32.CreateFileW("NUL", GENERIC_READ, FILE_SHARE_READ_WRITE, ctypes.byref(sa), OPEN_EXISTING, 0, None)

    cap_sid = a.PVOID()
    caps = None
    if network:
        if not a.adv.ConvertStringSidToSidW(INTERNET_CLIENT_SID, ctypes.byref(cap_sid)):
            raise ctypes.WinError(ctypes.get_last_error())
        caps = (a.SID_AND_ATTRIBUTES * 1)(a.SID_AND_ATTRIBUTES(cap_sid, SE_GROUP_ENABLED))
    sc = a.SECURITY_CAPABILITIES(psid, ctypes.cast(caps, a.PVOID) if caps else None, 1 if caps else 0, 0)
    handles = (HANDLE * 3)(hin, out_wr, err_wr)

    size = ctypes.c_size_t()
    k32.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
    buf = ctypes.create_string_buffer(size.value)
    if not k32.InitializeProcThreadAttributeList(buf, 2, 0, ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    pi = a.PROCESS_INFORMATION()
    try:
        if not k32.UpdateProcThreadAttribute(buf, 0, PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
                                             ctypes.byref(sc), ctypes.sizeof(sc), None, None):
            raise ctypes.WinError(ctypes.get_last_error())
        if not k32.UpdateProcThreadAttribute(buf, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                                             ctypes.byref(handles), ctypes.sizeof(handles), None, None):
            raise ctypes.WinError(ctypes.get_last_error())
        si = a.STARTUPINFOEXW()
        si.StartupInfo.cb = ctypes.sizeof(si)
        si.StartupInfo.dwFlags = STARTF_USESTDHANDLES
        si.StartupInfo.hStdInput, si.StartupInfo.hStdOutput, si.StartupInfo.hStdError = hin, out_wr, err_wr
        si.lpAttributeList = ctypes.cast(buf, a.PVOID)
        block = "".join(f"{k}={v}\0" for k, v in sorted(env.items(), key=lambda kv: kv[0].upper())) or "\0"
        envbuf = ctypes.create_unicode_buffer(block, len(block) + 1)
        cmdline = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
        flags = EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT | CREATE_SUSPENDED | CREATE_NO_WINDOW
        ok = k32.CreateProcessW(None, cmdline, None, None, True, flags, envbuf, str(cwd), ctypes.byref(si), ctypes.byref(pi))
        err = ctypes.get_last_error()
    finally:
        k32.DeleteProcThreadAttributeList(buf)
        for h in (out_wr, err_wr, hin):
            k32.CloseHandle(h)
        if cap_sid:
            k32.LocalFree(cap_sid)
    if not ok:
        k32.CloseHandle(out_rd)
        k32.CloseHandle(err_rd)
        raise SandboxUnavailable(f"The sandboxed process could not start (winerror {err}: {ctypes.FormatError(err).strip()}).")

    job = k32.CreateJobObjectW(None, None)
    ext = a.EXTENDED_LIMIT()
    ext.Basic.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if job:
        k32.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(ext), ctypes.sizeof(ext))
    if not job or not k32.AssignProcessToJobObject(job, pi.hProcess):
        err = ctypes.get_last_error()
        k32.TerminateProcess(pi.hProcess, 1)
        for h in (out_rd, err_rd, pi.hProcess, pi.hThread):
            k32.CloseHandle(h)
        if job:
            k32.CloseHandle(job)
        raise SandboxUnavailable(f"The sandboxed process could not be placed in a job object (winerror {err}).")
    k32.ResumeThread(pi.hThread)

    out_chunks: list[bytes] = []
    err_chunks: list[bytes] = []

    def pump(handle, sink):
        chunk = ctypes.create_string_buffer(4096)
        n = wt.DWORD()
        while k32.ReadFile(handle, chunk, 4096, ctypes.byref(n), None) and n.value:
            sink.append(chunk.raw[: n.value])

    threads = [threading.Thread(target=pump, args=(out_rd, out_chunks), daemon=True),
               threading.Thread(target=pump, args=(err_rd, err_chunks), daemon=True)]
    for t in threads:
        t.start()
    timed_out = k32.WaitForSingleObject(pi.hProcess, int(timeout * 1000)) == WAIT_TIMEOUT
    if timed_out:
        k32.TerminateJobObject(job, 1)
        k32.WaitForSingleObject(pi.hProcess, 5000)
    code = wt.DWORD()
    k32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
    k32.CloseHandle(job)  # KILL_ON_JOB_CLOSE: grandchildren still running die here, closing the pipes
    for t in threads:
        t.join(5)
    for h in (out_rd, err_rd, pi.hProcess, pi.hThread):
        k32.CloseHandle(h)
    return SandboxResult(
        returncode=-1 if timed_out else int(code.value),
        stdout=b"".join(out_chunks).decode("utf-8", "replace"),
        stderr=b"".join(err_chunks).decode("utf-8", "replace"),
        timed_out=timed_out,
    )


def probe() -> str | None:
    try:
        psid, _sid = ensure_profile(PROFILE_NAME)
    except OSError as exc:
        return f"Windows could not create the AppContainer sandbox profile ({exc})."
    _api().adv.FreeSid(psid)
    return None


def launch(req: SandboxRequest) -> SandboxResult:
    with _RUN_LOCK:
        try:
            psid, sid = ensure_profile(PROFILE_NAME)
        except OSError as exc:
            raise SandboxUnavailable(f"Windows could not create the AppContainer sandbox profile ({exc}).") from exc
        try:
            runtime, per_run = acl_grants(req)
            _ensure_runtime_grants(sid, [path for path, _perm in runtime])
            try:
                for path, perm in per_run:
                    _ledger_add_per_run(sid, path)
                    rc, out = _grant(path, sid, perm)
                    if rc != 0:
                        raise SandboxUnavailable(f"The sandbox could not be given access to {path} ({out}).")
                return _run_contained(req.argv, req.cwd, req.env, psid, req.timeout, req.network)
            finally:
                for path, _perm in per_run:
                    _revoke(path, sid)
                    _ledger_remove_per_run(sid, path)
        finally:
            _api().adv.FreeSid(psid)
```

In `web/sandbox/__init__.py` add after `launch_sandboxed`:

```python
def sweep_stale_grants() -> int:
    """Remove sandbox ACEs a crashed run left behind (Windows only). Never raises."""
    if sys.platform != "win32":
        return 0
    try:
        from . import launcher_windows

        return launcher_windows.sweep_stale_grants()
    except Exception as exc:
        _log.warning("sandbox: stale grant sweep failed (%s)", type(exc).__name__)
        return 0
```

In `web/app.py` lifespan, directly before `from mcp.supervisor import respawn_all_on_startup, start_supervisor, stop_supervisor`:

```python
    # Remove AppContainer ACEs left by a crashed sandboxed run (Windows; no-op elsewhere).
    import sandbox as _sandbox
    asyncio.create_task(asyncio.to_thread(_sandbox.sweep_stale_grants))
```

- [ ] **Step 4: Run the unit tests (every OS)**

Run: `python -m pytest tests/code_sandbox/test_launcher_windows.py -q -k "not TestRealAppContainer"`
Expected: pass.

- [ ] **Step 5: Run the real AppContainer tests on this machine**

Run: `python -m pytest tests/code_sandbox/test_launcher_windows.py -q -s -m real_sandbox`
Expected: 6 pass (the network test may skip if `1.1.1.1:443` is unreachable from this network). The first test is slow (one-time runtime grants, roughly 10-20 s); the overhead test prints the steady-state run time. Afterwards `icacls "%LOCALAPPDATA%\Programs\Python\Python312"` must show no `S-1-15-2-` ACE for the test profile, and `HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppContainer\Mappings` must not contain `AIGator.Test.*`. Keep the printed run time for the Task 9 tracker row.

- [ ] **Step 6: Commit**

```bash
git add web/sandbox/launcher_windows.py web/sandbox/__init__.py web/app.py tests/conftest.py pytest.ini tests/code_sandbox/test_launcher_windows.py
git commit -m "feat: Windows AppContainer launcher (ctypes, no admin): per-run grants with ledger and startup sweep, job-object tree kill, network capability only when approved"
```

---

### Task 5: macOS Seatbelt launcher

This launcher **cannot be run on this Windows machine**. It is verified by profile-builder tests that run on every OS, a real-run test that only runs on macOS (skipped here), and the manual release-gate smoke test in Task 9.

**Files:**

- Create: `web/sandbox/launcher_macos.py`
- Create: `tests/code_sandbox/posix_sandbox_check.py` (shared with Task 6)
- Create: `tests/code_sandbox/test_launcher_macos.py`

**Interfaces:**

- Consumes: `SandboxRequest`, `SandboxResult`, `SandboxUnavailable`, `run_process_group`, `build_env`.
- Produces (in `sandbox.launcher_macos`): `SANDBOX_EXEC = "/usr/bin/sandbox-exec"`; `SYSTEM_READ_PATHS`; `build_profile(req: SandboxRequest) -> str`; `probe() -> str | None`; `launch(req) -> SandboxResult`.
- Produces (tests): `tests/code_sandbox/posix_sandbox_check.py <linux|macos>` printing one JSON object with keys `probe`, `default`, `with_extra`, `tree_kill`, `leftover_sleepers`.

- [ ] **Step 1: Write the failing tests**

Create `tests/code_sandbox/posix_sandbox_check.py`:

```python
"""Real-run checks for the POSIX launchers. Prints one JSON object.

Usage: python3 posix_sandbox_check.py linux|macos
Runs natively on Linux/macOS, or inside WSL from tests/code_sandbox/test_launcher_linux.py.
Imports only web/sandbox (standard library), so a bare python3 is enough.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "web"))

from sandbox import SandboxRequest, build_env  # noqa: E402

PROBE = r'''
import json, os, socket, sys
r = {}
def t(name, f):
    try:
        r[name] = "OK:" + str(f())[:60]
    except Exception as e:
        r[name] = "DENIED:" + type(e).__name__
t("write_run_dir", lambda: open("out.txt", "w").write("hi"))
t("read_secret", lambda: open(sys.argv[1]).read())
t("read_extra", lambda: open(sys.argv[2]).read())
t("net_external", lambda: socket.create_connection(("1.1.1.1", 443), 3).getpeername())
r["token"] = os.environ.get("GITHUB_TOKEN")
print(json.dumps(r))
'''

TREE = (
    "import subprocess, sys, time\n"
    "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
    "print('started', flush=True)\n"
    "time.sleep(120)\n"
)


def main(kind: str) -> None:
    if kind == "macos":
        from sandbox import launcher_macos as launcher
        platform = "darwin"
    else:
        from sandbox import launcher_linux as launcher
        platform = "linux"
    base = Path(os.path.realpath(tempfile.mkdtemp(prefix="aigator-sandbox-check-")))
    run, secret_dir, extra_dir = base / "run", base / "secret", base / "extra"
    for d in (run, secret_dir, extra_dir):
        d.mkdir()
    (secret_dir / "s.txt").write_text("dummy-secret")
    (extra_dir / "e.txt").write_text("extra-data")
    (run / "probe.py").write_text(PROBE)
    (run / "tree.py").write_text(TREE)
    env = build_env(dict(os.environ, GITHUB_TOKEN="aigator-fake-api-key"), run, None, platform=platform)
    runtime = [Path(sys.base_prefix), Path(sys.prefix)]

    def request(argv, read_paths=(), timeout=30):
        return SandboxRequest(argv=argv, cwd=run, env=env, runtime_paths=runtime, read_paths=list(read_paths),
                              write_paths=[], network=False, timeout=timeout)

    def probe_run(read_paths=()):
        res = launcher.launch(request([sys.executable, str(run / "probe.py"), str(secret_dir / "s.txt"),
                                       str(extra_dir / "e.txt")], read_paths))
        lines = res.stdout.strip().splitlines()
        return json.loads(lines[-1]) if lines else {"rc": res.returncode, "stderr": res.stderr[-500:]}

    out = {"probe": launcher.probe(), "default": probe_run(), "with_extra": probe_run([extra_dir])}
    started = time.time()
    res = launcher.launch(request([sys.executable, str(run / "tree.py")], timeout=3))
    out["tree_kill"] = {"timed_out": res.timed_out, "elapsed": round(time.time() - started, 1)}
    time.sleep(1)
    ps = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout
    out["leftover_sleepers"] = sum(1 for line in ps.splitlines() if "time.sleep(120)" in line)
    print(json.dumps(out))


if __name__ == "__main__":
    main(sys.argv[1])
```

Create `tests/code_sandbox/test_launcher_macos.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

import pytest

from sandbox import SandboxRequest
from sandbox import launcher_macos as lm


def _req(network=False):
    return SandboxRequest(
        argv=["/usr/bin/python3", "code.py"], cwd=Path("/Users/me/.gator/outputs/r1"), env={},
        runtime_paths=[Path("/opt/homebrew/opt/python@3.12")], read_paths=[Path('/Users/me/Docs "q"')],
        write_paths=[Path("/Users/me/out")], network=network, timeout=5,
    )


def test_profile_denies_by_default_and_scopes_access():
    profile = lm.build_profile(_req())
    assert profile.startswith("(version 1)\n(deny default)\n")
    assert '(allow file-read* (subpath "/usr") (subpath "/System") (subpath "/Library") (subpath "/bin") (subpath "/private/etc") (subpath "/opt/homebrew/opt/python@3.12") (subpath "/Users/me/Docs \\"q\\""))' in profile
    assert '(allow file-read* file-write* (subpath "/Users/me/.gator/outputs/r1") (subpath "/Users/me/out"))' in profile
    assert "network" not in profile
    assert '"/Users/me"' not in profile  # never the home folder itself


def test_profile_network_only_when_approved():
    profile = lm.build_profile(_req(network=True))
    assert "(allow network-outbound)" in profile
    assert "(allow system-socket)" in profile
    assert "com.apple.dnssd.service" in profile


def test_probe_reports_missing_sandbox_exec(monkeypatch, tmp_path):
    monkeypatch.setattr(lm, "SANDBOX_EXEC", str(tmp_path / "missing-sandbox-exec"))
    assert "sandbox-exec" in lm.probe()


@pytest.mark.real_sandbox
@pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt runs only on macOS (cannot run on the Windows dev machine)")
def test_real_seatbelt_run():
    script = Path(__file__).with_name("posix_sandbox_check.py")
    out = json.loads(subprocess.run([sys.executable, str(script), "macos"], capture_output=True, text=True,
                                    timeout=180, check=True).stdout.strip().splitlines()[-1])
    assert out["probe"] is None
    assert out["default"]["write_run_dir"].startswith("OK")
    assert out["default"]["read_secret"].startswith("DENIED")
    assert out["default"]["read_extra"].startswith("DENIED")
    assert out["default"]["net_external"].startswith("DENIED")
    assert out["default"]["token"] is None
    assert out["with_extra"]["read_extra"] == "OK:extra-data"
    assert out["tree_kill"]["timed_out"] is True
    assert out["leftover_sleepers"] == 0
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/code_sandbox/test_launcher_macos.py -q`
Expected: FAIL (`ImportError: cannot import name 'launcher_macos'`).

- [ ] **Step 3: Implement**

Create `web/sandbox/launcher_macos.py`:

```python
"""macOS Seatbelt launcher (/usr/bin/sandbox-exec -p <profile>).

Not runnable on the Windows development machine: verified by build_profile
tests on every OS plus the manual release-gate smoke test on a real Mac.
Children inherit the sandbox. Paths are passed through realpath before the
profile is built (/var -> /private/var, /tmp -> /private/tmp).
"""
from __future__ import annotations

import dataclasses
import os
import subprocess
from pathlib import Path, PurePath

from . import SandboxRequest, SandboxResult, SandboxUnavailable, run_process_group

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
SYSTEM_READ_PATHS = ("/usr", "/System", "/Library", "/bin", "/private/etc")
_MACH_SERVICES = ("com.apple.system.opendirectoryd.libinfo", "com.apple.system.logger", "com.apple.logd")
_NETWORK_MACH_SERVICES = ("com.apple.dnssd.service", "com.apple.trustd", "com.apple.SystemConfiguration.configd")


def _quote(path) -> str:
    text = path if isinstance(path, str) else PurePath(path).as_posix()
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _subpaths(paths) -> str:
    return " ".join(f"(subpath {_quote(p)})" for p in paths)


def _global_names(names) -> str:
    return " ".join(f'(global-name "{n}")' for n in names)


def build_profile(req: SandboxRequest) -> str:
    read = [*SYSTEM_READ_PATHS, *req.runtime_paths, *req.read_paths]
    write = [req.cwd, *req.write_paths]
    lines = [
        "(version 1)",
        "(deny default)",
        "(allow process-fork)",
        "(allow process-exec)",
        "(allow signal (target same-sandbox))",
        "(allow sysctl-read)",
        "(allow file-read-metadata)",
        f"(allow mach-lookup {_global_names(_MACH_SERVICES)})",
        f"(allow file-read* {_subpaths(read)})",
        f"(allow file-read* file-write* {_subpaths(write)})",
        '(allow file-read* file-write* (literal "/dev/null") (literal "/dev/zero") (literal "/dev/tty") (subpath "/dev/fd"))',
        '(allow file-read* (literal "/dev/random") (literal "/dev/urandom"))',
    ]
    if req.network:
        lines += [
            "(allow network-outbound)",
            "(allow system-socket)",
            f"(allow mach-lookup {_global_names(_NETWORK_MACH_SERVICES)})",
        ]
    return "\n".join(lines) + "\n"


def _real(path) -> Path:
    return Path(os.path.realpath(path))


def probe() -> str | None:
    if not os.path.exists(SANDBOX_EXEC):
        return "macOS sandbox-exec was not found at /usr/bin/sandbox-exec."
    try:
        r = subprocess.run([SANDBOX_EXEC, "-p", "(version 1)(allow default)", "/usr/bin/true"],
                           capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"macOS sandbox-exec could not run ({type(exc).__name__})."
    if r.returncode != 0:
        return "macOS sandbox-exec refused to start a sandbox on this machine."
    return None


def launch(req: SandboxRequest) -> SandboxResult:
    if not os.path.exists(SANDBOX_EXEC):
        raise SandboxUnavailable("macOS sandbox-exec was not found at /usr/bin/sandbox-exec.")
    real = dataclasses.replace(
        req,
        cwd=_real(req.cwd),
        runtime_paths=[_real(p) for p in req.runtime_paths],
        read_paths=[_real(p) for p in req.read_paths],
        write_paths=[_real(p) for p in req.write_paths],
    )
    argv = [SANDBOX_EXEC, "-p", build_profile(real), *req.argv]
    return run_process_group(argv, real.cwd, req.env, req.timeout)
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/code_sandbox/test_launcher_macos.py -q -rs`
Expected: 3 pass, 1 skipped with "Seatbelt runs only on macOS (cannot run on the Windows dev machine)".

- [ ] **Step 5: Commit**

```bash
git add web/sandbox/launcher_macos.py tests/code_sandbox/posix_sandbox_check.py tests/code_sandbox/test_launcher_macos.py
git commit -m "feat: macOS Seatbelt launcher (profile builder tested on every OS; real run is a macOS-only test)"
```

---

### Task 6: Linux bubblewrap launcher

Real runs use the WSL Ubuntu on this machine (checked 2026-10-05: `bwrap` 0.11.1 at `/usr/bin/bwrap`, `python3` 3.14; an `--unshare-all` run printed output and got `Network is unreachable`). If WSL or bubblewrap is missing, the real test is skipped with the install command in the reason.

**Files:**

- Create: `web/sandbox/launcher_linux.py`
- Create: `tests/code_sandbox/test_launcher_linux.py`

**Interfaces:**

- Consumes: `SandboxRequest`, `SandboxResult`, `SandboxUnavailable`, `run_process_group`, `tests/code_sandbox/posix_sandbox_check.py` (Task 5).
- Produces (in `sandbox.launcher_linux`): `SYSTEM_RO_PATHS`, `ETC_RO_PATHS`, `BWRAP_MISSING: str`, `BWRAP_BLOCKED: str`; `build_argv(req: SandboxRequest, bwrap: str = "bwrap") -> list[str]`; `probe() -> str | None`; `launch(req) -> SandboxResult`.

- [ ] **Step 1: Write the failing tests**

Create `tests/code_sandbox/test_launcher_linux.py`:

```python
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sandbox import SandboxRequest
from sandbox import launcher_linux as ll

CHECK = Path(__file__).with_name("posix_sandbox_check.py")


def _req(network=False):
    return SandboxRequest(
        argv=["/usr/bin/python3", "code.py"], cwd=Path("/home/me/.gator/outputs/r1"), env={"PATH": "/usr/bin"},
        runtime_paths=[Path("/home/me/app/.venv")], read_paths=[Path("/home/me/data")],
        write_paths=[Path("/home/me/out")], network=network, timeout=5,
    )


def test_argv_unshares_everything_and_binds_only_what_is_needed():
    argv = ll.build_argv(_req(), "/usr/bin/bwrap")
    assert argv[:4] == ["/usr/bin/bwrap", "--unshare-all", "--die-with-parent", "--new-session"]
    assert "--share-net" not in argv
    joined = " ".join(argv)
    assert "--ro-bind-try /usr /usr" in joined
    assert "--ro-bind-try /etc/resolv.conf /etc/resolv.conf" in joined
    assert "--proc /proc --dev /dev --tmpfs /tmp" in joined
    assert "--ro-bind /home/me/app/.venv /home/me/app/.venv" in joined
    assert "--ro-bind /home/me/data /home/me/data" in joined
    assert "--bind /home/me/out /home/me/out" in joined
    assert argv[argv.index("--") + 1:] == ["/usr/bin/python3", "code.py"]
    assert "--bind /home/me/.gator/outputs/r1 /home/me/.gator/outputs/r1 --chdir /home/me/.gator/outputs/r1 --" in joined
    assert "/home/me " not in joined + " "  # the home folder itself is never bound
    assert "--bind / " not in joined and "--ro-bind / " not in joined


def test_argv_tmpfs_comes_before_runtime_binds():
    argv = ll.build_argv(_req())
    assert argv.index("--tmpfs") < argv.index("/home/me/app/.venv")


def test_network_only_when_approved():
    assert "--share-net" in ll.build_argv(_req(network=True))


def test_probe_reports_missing_bwrap_with_the_fix(monkeypatch):
    monkeypatch.setattr(ll.shutil, "which", lambda name: None)
    assert "bubblewrap" in ll.probe() and "apt install bubblewrap" in ll.probe()


def test_probe_reports_blocked_user_namespaces(monkeypatch):
    monkeypatch.setattr(ll.shutil, "which", lambda name: "/usr/bin/bwrap")
    monkeypatch.setattr(ll.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, b"", b"setting up uid map: Permission denied"))
    assert ll.probe() == ll.BWRAP_BLOCKED


def _wsl_path(p: Path) -> str:
    s = str(p.resolve())
    return "/mnt/" + s[0].lower() + s[2:].replace("\\", "/")


def _check_command():
    """Command that runs the shared check script with real bubblewrap, or a skip reason."""
    if sys.platform.startswith("linux"):
        if not shutil.which("bwrap"):
            return None, "bubblewrap is not installed (sudo apt install bubblewrap)"
        return [sys.executable, str(CHECK), "linux"], None
    if sys.platform == "win32":
        if not shutil.which("wsl.exe"):
            return None, "wsl.exe not available"
        try:
            r = subprocess.run(["wsl.exe", "-d", "Ubuntu", "--", "sh", "-c", "command -v bwrap && command -v python3"],
                               capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return None, "WSL Ubuntu did not respond"
        if r.returncode != 0:
            return None, "WSL Ubuntu without bubblewrap/python3 (wsl -d Ubuntu -- sudo apt install -y bubblewrap python3)"
        return ["wsl.exe", "-d", "Ubuntu", "--", "env", "PYTHONDONTWRITEBYTECODE=1", "python3", _wsl_path(CHECK), "linux"], None
    return None, "Linux sandbox checks run on Linux or through WSL"


@pytest.mark.real_sandbox
def test_real_bwrap_run():
    cmd, reason = _check_command()
    if cmd is None:
        pytest.skip(reason)
    out = json.loads(subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=True).stdout.strip().splitlines()[-1])
    assert out["probe"] is None
    assert out["default"]["write_run_dir"].startswith("OK")
    assert out["default"]["read_secret"].startswith("DENIED")
    assert out["default"]["read_extra"].startswith("DENIED")
    assert out["default"]["net_external"].startswith("DENIED")
    assert out["default"]["token"] is None
    assert out["with_extra"]["read_extra"] == "OK:extra-data"
    assert out["tree_kill"]["timed_out"] is True
    assert out["leftover_sleepers"] == 0
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/code_sandbox/test_launcher_linux.py -q`
Expected: FAIL (`ImportError: cannot import name 'launcher_linux'`).

- [ ] **Step 3: Implement**

Create `web/sandbox/launcher_linux.py`:

```python
"""Linux bubblewrap launcher (bwrap --unshare-all).

Needs the distro `bubblewrap` package and unprivileged user namespaces.
Children inherit the sandbox; --die-with-parent plus the PID namespace means
killing bwrap kills the whole tree. Paths go through realpath before the argv
is built. The root is an empty tmpfs: only the binds below exist inside.
"""
from __future__ import annotations

import dataclasses
import os
import shutil
import subprocess
from pathlib import Path, PurePath

from . import SandboxRequest, SandboxResult, SandboxUnavailable, run_process_group

SYSTEM_RO_PATHS = ("/usr", "/lib", "/lib32", "/lib64", "/bin", "/sbin")
ETC_RO_PATHS = (
    "/etc/ld.so.cache", "/etc/ld.so.conf", "/etc/ld.so.conf.d", "/etc/alternatives", "/etc/localtime",
    "/etc/nsswitch.conf", "/etc/hosts", "/etc/resolv.conf", "/etc/ssl", "/etc/ca-certificates",
    "/etc/pki", "/etc/fonts",
)
BWRAP_MISSING = (
    "bubblewrap is not installed. Install the 'bubblewrap' package "
    "(for example `sudo apt install bubblewrap` or `sudo dnf install bubblewrap`) and restart AI Gator."
)
BWRAP_BLOCKED = (
    "bubblewrap is installed but cannot create a sandbox (unprivileged user namespaces are disabled or "
    "restricted on this system). See docs/BUILD_INSTRUCTIONS.md, 'Linux: bubblewrap'."
)


def _posix(path) -> str:
    return path if isinstance(path, str) else PurePath(path).as_posix()


def build_argv(req: SandboxRequest, bwrap: str = "bwrap") -> list[str]:
    argv = [bwrap, "--unshare-all", "--die-with-parent", "--new-session"]
    if req.network:
        argv.append("--share-net")
    for path in (*SYSTEM_RO_PATHS, *ETC_RO_PATHS):
        argv += ["--ro-bind-try", path, path]
    argv += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for path in (*req.runtime_paths, *req.read_paths):
        p = _posix(path)
        argv += ["--ro-bind", p, p]
    for path in req.write_paths:
        p = _posix(path)
        argv += ["--bind", p, p]
    cwd = _posix(req.cwd)
    argv += ["--bind", cwd, cwd, "--chdir", cwd, "--", *req.argv]
    return argv


def probe() -> str | None:
    path = shutil.which("bwrap")
    if not path:
        return BWRAP_MISSING
    try:
        r = subprocess.run([path, "--unshare-all", "--die-with-parent", "--ro-bind", "/", "/", "--", "true"],
                           capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"bubblewrap could not run ({type(exc).__name__})."
    if r.returncode != 0:
        return BWRAP_BLOCKED
    return None


def _real(path) -> Path:
    return Path(os.path.realpath(path))


def launch(req: SandboxRequest) -> SandboxResult:
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise SandboxUnavailable(BWRAP_MISSING)
    real = dataclasses.replace(
        req,
        cwd=_real(req.cwd),
        runtime_paths=[_real(p) for p in req.runtime_paths],
        read_paths=[_real(p) for p in req.read_paths],
        write_paths=[_real(p) for p in req.write_paths],
    )
    return run_process_group(build_argv(real, bwrap), real.cwd, req.env, req.timeout)
```

- [ ] **Step 4: Run the tests (including the real WSL run)**

Run: `python -m pytest tests/code_sandbox/test_launcher_linux.py -q -rs`
Expected: all pass, including `test_real_bwrap_run` through WSL. If it fails because `/lib` or `/lib64` cannot be bound on this distro, print `out` (add `-s` and a temporary `print(out)`), adjust `SYSTEM_RO_PATHS` handling, and re-run; do not loosen the containment assertions.

- [ ] **Step 5: Commit**

```bash
git add web/sandbox/launcher_linux.py tests/code_sandbox/test_launcher_linux.py
git commit -m "feat: Linux bubblewrap launcher (argv builder tested on every OS; real runs through WSL Ubuntu)"
```

---

### Task 7: `run_python` integration

**Files:**

- Modify: `web/skills/code_runner/tools.py` (imports at lines 3-20; new helpers after `_find_skill_dir`; `_tool_run_python` lines 232-477 replaced; `TOOL_DEFS` lines 480-518 replaced)
- Modify: `web/skills/code_runner/SKILL.md` (frontmatter `description`; "Local filesystem access" section; the "Editing the user's file?" rule)
- Modify: `web/agent_loop.py` (`_summarize_tool_calls`, lines 314-335)
- Create: `tests/code_runner/conftest.py`
- Modify: `tests/code_runner/test_run_python.py` (append the real Windows test)
- Create: `tests/code_runner/test_run_python_sandbox.py`, `tests/code_sandbox/test_run_python_mode.py`, `tests/test_agent_loop_sandbox.py`

**Interfaces:**

- Consumes: `sandbox.SandboxRequest`, `sandbox.SandboxResult`, `sandbox.SandboxUnavailable`, `sandbox.launch_sandboxed`, `sandbox.sandbox_level`, `sandbox.sandbox_unavailable_reason`, `sandbox.build_env`, `sandbox.telemetry_record` (Task 2); `sandbox.policy.load_policy`, `Policy` (Task 2); `sandbox.paths.normalize_grant_paths`, `normalize_hosts`, `PathNotGrantable`, `is_within` (Task 2); `sandbox.approvals.lookup`, `create` (Task 3); `windows_container` fixture (Task 4).
- Produces (in `skills.code_runner.tools`): `_tool_run_python(code, skill_id="", timeout=None, confirmed=False, packages=None, extra_read_paths=None, extra_write_paths=None, network_hosts=None, _install_timeout=120, _context_id="") -> dict`; `_sandbox_mode(cfg: dict, policy: Policy) -> tuple[str, str | None]` returning `("enforced"|"off"|"unavailable", reason)`; `_approval_gate(...) -> dict | tuple[list[Path], list[Path], list[str], str | None]`; `_runtime_paths(skill_dir: Path | None, npm_root: str | None) -> list[Path]`; `_with_sandbox_hint(stderr: str) -> str`; constants `_SANDBOX_HINT`, `_DISABLED_MSG`, `_NETWORK_REFUSED_MSG`, `_FS_REFUSED_MSG`, `_DENIED_MSG`, `_EXPIRED_MSG`, `_APPROVAL_MSG`. Every result after the gate carries `"sandbox": "enforced"|"off"` and `"_sandbox_telemetry"`; an approval request returns `{"approval_required": True, "request_id", "read_paths", "write_paths", "network_hosts", "message", "_sandbox_approval": {...}, "_sandbox_telemetry": {...}}` (the `_sandbox_approval` dict has keys `request_id`, `read_paths`, `write_paths`, `network_hosts`, `context_id`; consumed by Task 8).
- Produces (in `agent_loop`): `_summarize_tool_calls` entries gain `"sandbox": <telemetry record>` when the result carries `_sandbox_telemetry`.

- [ ] **Step 1: Write the failing tests**

Create `tests/code_runner/conftest.py`:

```python
import pytest


@pytest.fixture(autouse=True)
def _sandbox_off_for_legacy_suite(monkeypatch):
    """The pre-sandbox run_python suite exercises the unsandboxed path. Tests
    that need the sandbox re-patch `_sandbox_mode` (fake launcher) or use the
    real `windows_container` fixture."""
    import skills.code_runner.tools as cr_mod

    monkeypatch.setattr(cr_mod, "_sandbox_mode", lambda cfg, policy: ("off", None))
```

Create `tests/code_sandbox/test_run_python_mode.py`:

```python
import sandbox
import skills.code_runner.tools as cr
from sandbox.policy import Policy


def test_enforced_when_sandbox_works_even_if_opted_out(monkeypatch):
    monkeypatch.setattr(sandbox, "sandbox_level", lambda: "enforced")
    assert cr._sandbox_mode({"code_runner_sandbox": "off"}, Policy()) == ("enforced", None)


def test_unavailable_fails_closed_unless_opted_out(monkeypatch):
    monkeypatch.setattr(sandbox, "sandbox_level", lambda: "unavailable")
    monkeypatch.setattr(sandbox, "sandbox_unavailable_reason", lambda: "install bubblewrap")
    assert cr._sandbox_mode({}, Policy()) == ("unavailable", "install bubblewrap")
    assert cr._sandbox_mode({"code_runner_sandbox": "off"}, Policy()) == ("off", None)


def test_require_sandbox_ignores_the_opt_out(monkeypatch):
    monkeypatch.setattr(sandbox, "sandbox_level", lambda: "unavailable")
    monkeypatch.setattr(sandbox, "sandbox_unavailable_reason", lambda: "install bubblewrap")
    assert cr._sandbox_mode({"code_runner_sandbox": "off"}, Policy(require_sandbox=True)) == (
        "unavailable", "install bubblewrap",
    )


def test_hint_only_for_permission_and_network_errors():
    assert cr._with_sandbox_hint("ValueError: x") == "ValueError: x"
    for err in ("PermissionError: [Errno 13] Permission denied: 'C:\\\\x'",
                "OSError: [Errno 101] Network is unreachable",
                "socket.gaierror: [Errno 11001] getaddrinfo failed",
                "Error: EPERM: operation not permitted, lstat"):
        assert cr._with_sandbox_hint(err).endswith(cr._SANDBOX_HINT + "\n")


def test_runtime_paths_cover_interpreter_and_skill_dir(tmp_path, monkeypatch):
    import sys
    from pathlib import Path

    skill = tmp_path / "skill"
    skill.mkdir()
    monkeypatch.setattr(cr.shutil, "which", lambda name: None)
    paths = cr._runtime_paths(skill, None)
    assert skill.resolve() in paths
    assert any(Path(sys.executable).resolve().is_relative_to(p) for p in paths)
    assert len(paths) == len(set(paths))
    for a in paths:
        assert not any(a != b and a.is_relative_to(b) for b in paths)  # nested entries removed


def test_runtime_paths_frozen_is_bundle_dir(tmp_path, monkeypatch):
    exe = tmp_path / "backend" / "aigator-backend.exe"
    exe.parent.mkdir()
    exe.write_text("")
    monkeypatch.setattr(cr.sys, "frozen", True, raising=False)
    monkeypatch.setattr(cr.sys, "executable", str(exe))
    monkeypatch.setattr(cr.shutil, "which", lambda name: None)
    assert cr._runtime_paths(None, None) == [exe.parent.resolve()]


def test_tool_schema_and_skill_doc():
    from pathlib import Path

    props = cr.TOOL_DEFS[0]["input_schema"]["properties"]
    for name in ("extra_read_paths", "extra_write_paths", "network_hosts"):
        assert props[name]["type"] == "array"
    assert "_context_id" not in props
    assert "full read access" not in cr.TOOL_DEFS[0]["description"]
    skill_md = (Path(cr.__file__).parent / "SKILL.md").read_text(encoding="utf-8")
    assert "full read access" not in skill_md
    assert "extra_read_paths" in skill_md and "approval_required" in skill_md
```

Create `tests/code_runner/test_run_python_sandbox.py`:

```python
import os

import pytest

import sandbox
import skills.code_runner.tools as cr_mod
from sandbox import approvals
from sandbox.policy import Policy

FAKE = "aigator-fake-api-key"


@pytest.fixture
def calls(tmp_path, monkeypatch):
    import config as cfg_mod

    monkeypatch.setattr(cfg_mod, "OUTPUTS_DIR", tmp_path / "outputs")
    monkeypatch.setattr(cr_mod, "OUTPUTS_DIR", tmp_path / "outputs")
    monkeypatch.setattr(cr_mod, "_sandbox_mode", lambda cfg, policy: ("enforced", None))
    approvals._reset()
    seen = []

    def fake_launch(req):
        seen.append(req)
        (req.cwd / "made.txt").write_text("x")
        return sandbox.SandboxResult(returncode=0, stdout="fake-ok\n", stderr="", timed_out=False)

    monkeypatch.setattr(sandbox, "launch_sandboxed", fake_launch)
    yield seen
    approvals._reset()


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return d


def test_enforced_run_uses_launcher_with_filtered_env(calls, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", FAKE)
    result = cr_mod._tool_run_python(code="print('hi')", _context_id="tab-1")
    assert result["error"] is None and result["stdout"] == "fake-ok\n"
    assert result["sandbox"] == "enforced"
    assert [f["name"] for f in result["files"]] == ["made.txt"]
    (req,) = calls
    assert "GITHUB_TOKEN" not in req.env and FAKE not in req.env.values()
    assert req.cwd.name == result["_sandbox_telemetry"]["run_id"]
    assert req.read_paths == [] and req.write_paths == [] and req.network is False
    assert req.argv[-1].endswith("code.py")
    assert result["_sandbox_telemetry"] == {
        "run_id": req.cwd.name, "skill_id": "", "level": "enforced", "network": False,
        "extra_read": 0, "extra_write": 0, "approval": None,
    }


def test_extra_paths_need_approval_and_are_used_once(calls, data_dir):
    args = dict(code="print(1)", extra_read_paths=[str(data_dir)], network_hosts=["API.example.com:443"], _context_id="tab-1")
    first = cr_mod._tool_run_python(**args)
    assert first["approval_required"] is True and calls == []
    card = first["_sandbox_approval"]
    assert card["read_paths"] == [str(data_dir.resolve())]
    assert card["network_hosts"] == ["api.example.com:443"]
    assert card["context_id"] == "tab-1"
    assert first["_sandbox_telemetry"]["approval"] == "requested"
    assert str(data_dir) not in str(first["_sandbox_telemetry"])

    again = cr_mod._tool_run_python(**args)  # still pending: same request, no run
    assert again["request_id"] == first["request_id"] and calls == []

    approvals.decide(first["request_id"], "tab-1", True)
    ran = cr_mod._tool_run_python(**args)
    assert ran["error"] is None
    (req,) = calls
    assert req.read_paths == [data_dir.resolve()] and req.network is True
    assert ran["_sandbox_telemetry"]["approval"] == "approved"
    assert ran["_sandbox_telemetry"]["extra_read"] == 1 and ran["_sandbox_telemetry"]["network"] is True

    third = cr_mod._tool_run_python(**args)  # consumed
    assert third["approval_required"] is True and len(calls) == 1


def test_different_set_or_tab_needs_new_approval(calls, data_dir, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    first = cr_mod._tool_run_python(code="1", extra_read_paths=[str(data_dir)], _context_id="tab-1")
    approvals.decide(first["request_id"], "tab-1", True)
    assert cr_mod._tool_run_python(code="1", extra_read_paths=[str(data_dir), str(other)], _context_id="tab-1")["approval_required"]
    assert cr_mod._tool_run_python(code="1", extra_read_paths=[str(data_dir)], _context_id="tab-2")["approval_required"]
    assert calls == []


def test_denied_and_expired_return_fixed_errors(calls, data_dir):
    args = dict(code="1", extra_write_paths=[str(data_dir)], _context_id="tab-1")
    req = cr_mod._tool_run_python(**args)
    approvals.decide(req["request_id"], "tab-1", False)
    denied = cr_mod._tool_run_python(**args)
    assert denied["error"] == cr_mod._DENIED_MSG
    assert denied["_sandbox_telemetry"]["approval"] == "denied"
    req2 = cr_mod._tool_run_python(**args)
    approvals._REQUESTS[req2["request_id"]].created_at -= 601
    expired = cr_mod._tool_run_python(**args)
    assert expired["error"] == cr_mod._EXPIRED_MSG
    assert expired["_sandbox_telemetry"]["approval"] == "expired"
    assert calls == []


def test_never_grantable_path_is_refused_without_a_card(calls):
    import pathlib

    result = cr_mod._tool_run_python(code="1", extra_read_paths=[str(pathlib.Path.home() / ".ssh")], _context_id="tab-1")
    assert "can never be granted" in result["error"]
    assert "approval_required" not in result and approvals._REQUESTS == {} and calls == []


def test_policy_disabled_network_deny_and_strict(calls, data_dir, monkeypatch):
    monkeypatch.setattr(cr_mod, "load_policy", lambda: Policy(code_runner="disabled"))
    assert cr_mod._tool_run_python(code="1")["error"] == cr_mod._DISABLED_MSG
    monkeypatch.setattr(cr_mod, "load_policy", lambda: Policy(network="deny"))
    assert cr_mod._tool_run_python(code="1", network_hosts=["a.example.com:443"])["error"] == cr_mod._NETWORK_REFUSED_MSG
    monkeypatch.setattr(cr_mod, "load_policy", lambda: Policy(filesystem="strict"))
    assert cr_mod._tool_run_python(code="1", extra_read_paths=[str(data_dir)])["error"] == cr_mod._FS_REFUSED_MSG
    assert approvals._REQUESTS == {} and calls == []


def test_unavailable_fails_closed(calls, monkeypatch):
    monkeypatch.setattr(cr_mod, "_sandbox_mode", lambda cfg, policy: ("unavailable", "install bubblewrap"))
    result = cr_mod._tool_run_python(code="print(1)")
    assert "install bubblewrap" in result["error"] and calls == []


def test_launcher_unavailable_at_launch_time(calls, monkeypatch):
    def refuse(req):
        raise sandbox.SandboxUnavailable("profile creation failed")

    monkeypatch.setattr(sandbox, "launch_sandboxed", refuse)
    result = cr_mod._tool_run_python(code="print(1)")
    assert "profile creation failed" in result["error"] and result["sandbox"] == "enforced"


def test_permission_error_gets_the_hint(calls, monkeypatch):
    monkeypatch.setattr(sandbox, "launch_sandboxed", lambda req: sandbox.SandboxResult(
        1, "", "PermissionError: [Errno 13] Permission denied: 'x'", False))
    result = cr_mod._tool_run_python(code="open('x')")
    assert "extra_read_paths" in result["error"]


def test_launcher_timeout(calls, monkeypatch):
    monkeypatch.setattr(sandbox, "launch_sandboxed", lambda req: sandbox.SandboxResult(-1, "", "", True))
    result = cr_mod._tool_run_python(code="1", timeout=3)
    assert "timed out after 3s" in result["error"] and result["files"] == [] and result["sandbox"] == "enforced"


def test_off_mode_marks_results(tmp_path, monkeypatch):
    import config as cfg_mod

    monkeypatch.setattr(cfg_mod, "OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(cr_mod, "OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(cr_mod, "_sandbox_mode", lambda cfg, policy: ("off", None))
    result = cr_mod._tool_run_python(code="print('plain')")
    assert result["error"] is None and result["sandbox"] == "off"
    assert result["_sandbox_telemetry"]["level"] == "off"
```

Append to `tests/code_runner/test_run_python.py`:

```python
@pytest.mark.real_sandbox
@pytest.mark.skipif(sys.platform != "win32", reason="real AppContainer run needs Windows")
def test_real_sandboxed_run_on_windows(windows_container, monkeypatch, tmp_path):
    import sandbox
    import skills.code_runner.tools as cr_mod

    monkeypatch.setattr(sandbox, "_PROBE", ("enforced", None))
    monkeypatch.setattr(cr_mod, "_sandbox_mode", lambda cfg, policy: ("enforced", None))
    secret = tmp_path / "secret.txt"  # in the outputs root, outside this run's folder
    secret.write_text("dummy-secret")
    code = (
        "from pathlib import Path\n"
        "Path(OUTPUT_DIR, 'ok.txt').write_text('x')\n"
        "try:\n"
        f"    print(Path({str(secret)!r}).read_text())\n"
        "except PermissionError:\n"
        "    print('secret-denied')\n"
    )
    result = cr_mod._tool_run_python(code=code)
    assert result["error"] is None, result
    assert "secret-denied" in result["stdout"]
    assert result["sandbox"] == "enforced"
    assert [f["name"] for f in result["files"]] == ["ok.txt"]
```

Create `tests/test_agent_loop_sandbox.py`:

```python
import pathlib
import sys
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from agent_loop import _summarize_tool_calls


def test_sandbox_telemetry_is_attached_to_the_tool_call_entry():
    rec = {"run_id": "r1", "skill_id": "", "level": "enforced", "network": False,
           "extra_read": 0, "extra_write": 0, "approval": None}
    tc = SimpleNamespace(name="run_python")
    (entry,) = _summarize_tool_calls([tc], [{"error": None, "stdout": "secret output", "_sandbox_telemetry": rec}])
    assert entry == {"name": "run_python", "success": True, "sandbox": rec}
    (failed,) = _summarize_tool_calls([tc], [{"error": "boom", "_sandbox_telemetry": rec}])
    assert failed["sandbox"] == rec and failed["success"] is False


def test_other_tools_unchanged():
    (entry,) = _summarize_tool_calls([SimpleNamespace(name="x")], [{"result": "ok"}])
    assert entry == {"name": "x", "success": True}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/code_runner tests/code_sandbox/test_run_python_mode.py tests/test_agent_loop_sandbox.py -q`
Expected: FAIL (`AttributeError: ... has no attribute '_sandbox_mode'` and similar).

- [ ] **Step 3: Implement `tools.py`**

In `web/skills/code_runner/tools.py`, add to the imports (after `import re`):

```python
import shutil
```

and after the `from proc_utils import (...)` block:

```python
import sandbox
from sandbox import approvals as sandbox_approvals
from sandbox.paths import PathNotGrantable, is_within, normalize_grant_paths, normalize_hosts
from sandbox.policy import load_policy
```

After `_find_skill_dir` (before the `# --- AST:` comment) add:

```python
# --- OS sandbox (docs/superpowers/specs/2026-10-05-code-runner-sandbox-design.md) ---

_SANDBOX_HINT = (
    "[sandbox] This code can only use its own OUTPUT_DIR and has no network. If the task really "
    "needs more, re-call run_python with extra_read_paths, extra_write_paths or network_hosts; "
    "the user will be asked to approve."
)
_PERMISSION_PATTERNS = re.compile(
    r"PermissionError|Permission denied|Access is denied|EACCES|EPERM|Operation not permitted|"
    r"WinError 5\b|WinError 10013|Network is unreachable|ENETUNREACH|getaddrinfo failed|"
    r"Temporary failure in name resolution|Name or service not known|nodename nor servname",
    re.IGNORECASE,
)
_DISABLED_MSG = "Code execution is disabled on this computer by the administrator's AI Gator policy."
_NETWORK_REFUSED_MSG = (
    "Network access for code is blocked by the administrator's AI Gator policy. "
    "Do not retry with network_hosts."
)
_FS_REFUSED_MSG = (
    "Access to folders outside OUTPUT_DIR is blocked by the administrator's AI Gator policy. "
    "Do not retry with extra paths; work only inside OUTPUT_DIR."
)
_DENIED_MSG = (
    "The user denied this access request. Do not retry it; continue without that access "
    "or ask the user what to do."
)
_EXPIRED_MSG = (
    "This access approval expired (approvals last 10 minutes). Do not retry automatically; "
    "ask the user whether to request the access again."
)
_APPROVAL_MSG = (
    "The user must approve this access first; an approval card is now shown in the chat. Tell the "
    "user briefly what access you asked for and why, then stop and wait. When the user says they "
    "approved, call run_python again with exactly the same code, extra_read_paths, "
    "extra_write_paths and network_hosts. If they deny, do not retry."
)


def _unavailable_message(reason: str | None) -> str:
    return (
        "Code cannot run because the code sandbox is unavailable on this computer. "
        f"{reason or ''} Tell the user; details are in Settings under Code sandbox."
    ).replace("  ", " ")


def _sandbox_mode(cfg: dict, policy) -> tuple[str, str | None]:
    """('enforced', None), ('off', None) or ('unavailable', reason).

    The opt-out applies only when the sandbox cannot run and the policy does
    not require it; a working sandbox is always used."""
    if sandbox.sandbox_level() == "enforced":
        return "enforced", None
    reason = sandbox.sandbox_unavailable_reason() or "The sandbox is unavailable."
    if cfg.get("code_runner_sandbox") == "off" and not policy.require_sandbox:
        return "off", None
    return "unavailable", reason


def _with_sandbox_hint(stderr: str) -> str:
    if stderr and _PERMISSION_PATTERNS.search(stderr):
        return stderr.rstrip("\n") + "\n" + _SANDBOX_HINT + "\n"
    return stderr


def _runtime_paths(skill_dir: Path | None, npm_root: str | None) -> list[Path]:
    """Read+execute paths the sandboxed process needs (interpreter, libraries, skill folder, Node)."""
    import site

    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent)
    else:
        candidates += [Path(sys.base_prefix), Path(sys.prefix), Path(sys.executable).resolve().parent]
        try:
            candidates += [Path(p) for p in site.getsitepackages()]
        except AttributeError:
            pass
        if site.ENABLE_USER_SITE:
            candidates.append(Path(site.getusersitepackages()))
    node = shutil.which("node")
    if node:
        candidates.append(Path(node).resolve().parent)
    if npm_root:
        candidates.append(Path(npm_root))
    if skill_dir is not None:
        candidates.append(Path(skill_dir))
    kept: list[Path] = []
    for path in sorted({p.resolve() for p in candidates if p.exists()}, key=lambda p: len(str(p))):
        if not any(is_within(path, k) for k in kept):
            kept.append(path)
    return kept


def _approval_gate(extra_read_paths, extra_write_paths, network_hosts, policy, context_id: str, skill_id: str):
    """Return a result dict to send back (refusal or approval_required), or
    (read_paths, write_paths, hosts, approval) to run with."""
    try:
        read_paths = normalize_grant_paths(extra_read_paths)
        write_paths = normalize_grant_paths(extra_write_paths)
        hosts = normalize_hosts(network_hosts)
    except (PathNotGrantable, ValueError) as exc:
        return {"error": f"{exc} Do not retry with this value."}
    if hosts and policy.network == "deny":
        return {"error": _NETWORK_REFUSED_MSG}
    if (read_paths or write_paths) and policy.filesystem == "strict":
        return {"error": _FS_REFUSED_MSG}
    if not (read_paths or write_paths or hosts):
        return read_paths, write_paths, hosts, None

    read_s, write_s = [str(p) for p in read_paths], [str(p) for p in write_paths]

    def telemetry(decision: str) -> dict:
        return sandbox.telemetry_record("", skill_id, "enforced", bool(hosts), len(read_paths), len(write_paths), decision)

    status, req = sandbox_approvals.lookup(context_id, read_s, write_s, hosts)
    if status == "approved":
        return read_paths, write_paths, hosts, "approved"
    if status == "denied":
        return {"error": _DENIED_MSG, "_sandbox_telemetry": telemetry("denied")}
    if status == "expired":
        return {"error": _EXPIRED_MSG, "_sandbox_telemetry": telemetry("expired")}
    if req is None:
        req = sandbox_approvals.create(context_id, read_s, write_s, hosts)
    card = {
        "request_id": req.id,
        "read_paths": list(req.read_paths),
        "write_paths": list(req.write_paths),
        "network_hosts": list(req.network_hosts),
        "context_id": req.context_id,
    }
    return {
        "approval_required": True,
        "request_id": req.id,
        "read_paths": card["read_paths"],
        "write_paths": card["write_paths"],
        "network_hosts": card["network_hosts"],
        "message": _APPROVAL_MSG,
        "_sandbox_approval": card,
        "_sandbox_telemetry": telemetry("requested"),
    }
```

Replace the whole `_tool_run_python` function (lines 232-477) with:

```python
def _tool_run_python(
    code: str,
    skill_id: str = "",
    timeout: int = None,
    confirmed: bool = False,
    packages: list = None,
    extra_read_paths: list = None,
    extra_write_paths: list = None,
    network_hosts: list = None,
    _install_timeout: int = 120,
    _context_id: str = "",
) -> dict:
    """Execute Python code in an OS sandbox and return stdout and output files.

    Args:
        code: Python source to execute. OUTPUT_DIR variable is injected automatically.
        skill_id: The marketplace skill this runs under — used for tier lookup and SKILL_DIR.
        timeout: Override timeout in seconds. Defaults to config value based on tier.
        confirmed: Set True to skip AST destructive-op check (user has approved).
        extra_read_paths / extra_write_paths / network_hosts: access beyond the run
            folder; needs a user approval for this tab and exactly this set.
        _context_id: server-injected tab id (never supplied by the model).

    Returns:
        On success: {"stdout", "stderr", "files", "runtime_ms", "error": None, "sandbox"}
        On approval needed: {"approval_required": True, "request_id", ..., "message"}
        On HITL required: {"hitl_required": True, "flagged_operations": [...], "message": str}
        On error: {"error": str, "stdout": str, "files": []}
    """
    from config import load_config

    cfg = load_config()
    policy = load_policy()
    if policy.code_runner == "disabled":
        return {"error": _DISABLED_MSG}
    mode, reason = _sandbox_mode(cfg, policy)
    if mode == "unavailable":
        return {"error": _unavailable_message(reason)}
    read_paths: list[Path] = []
    write_paths: list[Path] = []
    hosts: list[str] = []
    approval = None
    if mode == "enforced":
        gate = _approval_gate(extra_read_paths, extra_write_paths, network_hosts, policy, _context_id, skill_id)
        if isinstance(gate, dict):
            return gate
        read_paths, write_paths, hosts, approval = gate

    tier = shared.TOOL_TIER_MAP.get(skill_id, "Verified")
    if timeout is None:
        key = (
            "code_runner_timeout_community"
            if tier == "Community"
            else "code_runner_timeout_verified"
        )
        timeout = int(cfg.get(key, 30 if tier == "Community" else 60))

    # A frozen desktop sidecar cannot modify its bundled environment. Reject
    # any package-install request up front, even if that package happens to be
    # importable in the build environment today.
    if packages and getattr(sys, "frozen", False):
        return {
            "error": "Package installation is not available in the packaged app."
        }

    # On-the-fly pip install (runs unsandboxed in the server process: known gap)
    missing_packages = _missing_packages(packages or [])
    if missing_packages:
        try:
            pip_result = subprocess.run(
                [sys.executable, "-m", "pip", "install"] + missing_packages,
                capture_output=True,
                timeout=_install_timeout,
                text=True,
                encoding="utf-8",
                **no_window_kwargs(),
            )
            if pip_result.returncode != 0 and "No module named pip" in pip_result.stderr:
                # Some interpreters (e.g. uv-managed venvs, which omit pip by
                # default for faster installs) have no pip at all. Bootstrap
                # it from the stdlib bundle rather than failing every install.
                subprocess.run(
                    [sys.executable, "-m", "ensurepip", "--default-pip"],
                    capture_output=True, timeout=_install_timeout, text=True,
                    encoding="utf-8", **no_window_kwargs(),
                )
                pip_result = subprocess.run(
                    [sys.executable, "-m", "pip", "install"] + packages,
                    capture_output=True,
                    timeout=_install_timeout,
                    text=True,
                    encoding="utf-8",
                    **no_window_kwargs(),
                )
            if pip_result.returncode != 0:
                return {
                    "error": f"Failed to install {missing_packages}: {pip_result.stderr[:500]}"
                }
        except subprocess.TimeoutExpired:
            return {"error": f"Package install timed out after {_install_timeout}s."}

    # AST scan — blocked ops are always rejected; flagged ops require HITL (skipped if confirmed=True)
    blocked, flagged = _ast_scan(code)
    if blocked:
        return {
            "error": (
                "File deletion is not supported. The code contains delete operations: "
                + ", ".join(blocked)
                + ". Please ask the user to delete files manually."
            ),
        }
    if not confirmed and flagged:
        return {
            "hitl_required": True,
            "flagged_operations": flagged,
            "message": (
                "This code contains operations that could modify files outside the output folder. "
                "Review the flagged lines and re-call run_python with confirmed=True if you want to proceed. "
                "Always explain to the user what was flagged before re-calling."
            ),
        }

    # Create per-run output directory
    run_id = uuid4().hex[:12]
    run_dir = OUTPUTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    skill_dir = _find_skill_dir(skill_id)
    skill_dir_line = ""
    if skill_dir is not None:
        skill_dir_line = (
            f"SKILL_DIR = {str(skill_dir)!r}\n"
            f"import sys as _sys; _sys.path.insert(0, SKILL_DIR)\n"
        )
    preamble = (
        f"OUTPUT_DIR = {str(run_dir)!r}\n{skill_dir_line}from pathlib import Path\n"
    )
    full_code = preamble + code

    # Snapshot ~/Downloads so we can report files the code writes OUTSIDE its
    # OUTPUT_DIR (run_dir files are already returned via `files` below). This
    # surfaces e.g. a deck the code saved to Downloads instead of OUTPUT_DIR,
    # from disk rather than the model's memory (issue #87).
    _home = Path.home()
    _watch_dirs = [d for d in (_home / "Downloads",) if d.is_dir()]
    _before = snapshot_outputs(_watch_dirs)

    # Persist the exact executed code (preamble + user code) so the full script
    # is recoverable on disk after a timeout/crash/restart. Best-effort.
    _write_forensic(run_dir / "code.py", full_code)

    # The run folder has no node_modules, so node scripts started by the code
    # can't resolve globally-installed packages (e.g. pptxgenjs). NODE_PATH
    # points at the global npm root. Prefer `npm root -g` (authoritative); on
    # Windows npm is a .cmd shim so it needs shell=True. Fall back to the
    # well-known %APPDATA%\npm\node_modules path if npm isn't invocable.
    _npm_root = None
    try:
        _npm_root = subprocess.run(
            "npm root -g",
            capture_output=True,
            text=True,
            timeout=5,
            shell=True,
            **no_window_kwargs(),
        ).stdout.strip()
        if not _npm_root or not Path(_npm_root).is_dir():
            _npm_root = None
    except Exception:
        _npm_root = None
    if not _npm_root:
        _fallback = Path.home() / "AppData" / "Roaming" / "npm" / "node_modules"
        if _fallback.is_dir():
            _npm_root = str(_fallback)

    telemetry = sandbox.telemetry_record(
        run_id, skill_id, mode, bool(hosts), len(read_paths), len(write_paths), approval
    )
    tags = {"sandbox": mode, "_sandbox_telemetry": telemetry}

    start = time.monotonic()
    try:
        if mode == "enforced":
            request = sandbox.SandboxRequest(
                argv=_python_command(run_dir / "code.py"),
                cwd=run_dir,
                env=sandbox.build_env(os.environ, run_dir, _npm_root),
                runtime_paths=_runtime_paths(skill_dir, _npm_root),
                read_paths=read_paths,
                write_paths=write_paths,
                network=bool(hosts),
                timeout=timeout,
            )
            res = sandbox.launch_sandboxed(request)
            returncode, timed_out = res.returncode, res.timed_out
            stdout, stderr = res.stdout or "", _with_sandbox_hint(res.stderr or "")
        else:
            # Opted out (sandbox unavailable, policy allows it): the old unsandboxed path.
            _subproc_env = os.environ.copy()
            if _npm_root:
                _subproc_env["NODE_PATH"] = _npm_root
            try:
                proc = subprocess.run(
                    _python_command(run_dir / "code.py"),
                    cwd=str(run_dir),
                    capture_output=True,
                    timeout=timeout,
                    text=True,
                    encoding="utf-8",
                    env=_subproc_env,
                    **no_window_kwargs(),
                )
                returncode, timed_out = proc.returncode, False
                stdout, stderr = proc.stdout or "", proc.stderr or ""
            except subprocess.TimeoutExpired as te:
                # Partial stdout/stderr (if any) are on the exception object.
                returncode, timed_out = -1, True
                stdout = te.stdout if isinstance(te.stdout, str) else ""
                stderr = te.stderr if isinstance(te.stderr, str) else ""
        elapsed_ms = int((time.monotonic() - start) * 1000)

        # Full stdout/stderr to disk (the tool result only carries stderr[:500]
        # back to the model; these logs keep the complete trace for forensics).
        _write_forensic(run_dir / "stdout.log", stdout)
        _write_forensic(run_dir / "stderr.log", stderr)

        if timed_out:
            return {
                "error": f"Code execution timed out after {timeout}s.",
                "stdout": "",
                "files": [],
                "runtime_ms": elapsed_ms,
                "forensic": _forensic_paths(run_id, run_dir),
                **tags,
            }

        import mimetypes as _mimetypes

        files = []
        for f in sorted(run_dir.iterdir()):
            if f.is_file() and f.name not in _FORENSIC_FILES:
                mime, _ = _mimetypes.guess_type(str(f))
                files.append(
                    {
                        "name": f.name,
                        "download_url": f"/api/files/{run_id}/{f.name}",
                        "size_bytes": f.stat().st_size,
                        "mime_type": mime or "application/octet-stream",
                    }
                )

        external_files = diff_outputs(_before, _watch_dirs)

        if returncode != 0:
            result = {
                "error": f"Code exited with code {returncode}. stderr: {stderr[:500]}"
                + (f"\n{_SANDBOX_HINT}" if _SANDBOX_HINT in stderr[500:] else ""),
                "stdout": stdout,
                "files": files,
                "runtime_ms": elapsed_ms,
                "forensic": _forensic_paths(run_id, run_dir),
                **tags,
            }
            if external_files:
                result["output_files"] = external_files
            return result

        result = {
            "stdout": stdout,
            "stderr": stderr,
            "files": files,
            "runtime_ms": elapsed_ms,
            "error": None,
            **tags,
        }
        if external_files:
            result["output_files"] = external_files
        return result

    except sandbox.SandboxUnavailable as exc:
        _write_forensic(run_dir / "stderr.log", f"sandbox unavailable: {exc}")
        return {
            "error": _unavailable_message(str(exc)),
            "stdout": "",
            "files": [],
            "forensic": _forensic_paths(run_id, run_dir),
            **tags,
        }
    except Exception as exc:
        _write_forensic(run_dir / "stderr.log", f"runner exception: {exc}")
        return {
            "error": str(exc),
            "stdout": "",
            "files": [],
            "forensic": _forensic_paths(run_id, run_dir),
            **tags,
        }
```

Replace `TOOL_DEFS` (lines 480-518) with:

```python
TOOL_DEFS = [
    {
        "name": "run_python",
        "description": (
            "Execute Python code in an OS sandbox. By default the code can read and write only its "
            "own OUTPUT_DIR (injected automatically — write all output files there) and read the "
            "Python/Node runtime and SKILL_DIR; it has no network and no access to the rest of the "
            "user's files. If the task needs to read or write other local paths or reach the network, "
            "pass extra_read_paths, extra_write_paths or network_hosts: the call returns "
            "approval_required and the user approves or denies in the chat; call again with exactly "
            "the same values only after the user says they approved. Returns stdout and a list of "
            "output files with download URLs. If the code contains destructive operations outside "
            "OUTPUT_DIR, returns hitl_required=True with flagged_operations — show these to the user "
            "and re-call with confirmed=True if they approve."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute. Use OUTPUT_DIR variable for all file writes.",
                },
                "skill_id": {
                    "type": "string",
                    "description": "Skill context for sandbox tier and SKILL_DIR (optional, e.g. 'slack-gif-creator')",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Override execution timeout in seconds (optional)",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "Set True to skip AST destructive-op check after user has approved flagged operations",
                },
                "packages": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "pip package names to install before running (optional, e.g. ['pandas', 'requests']). Already-installed packages are a no-op.",
                },
                "extra_read_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Absolute paths of existing files or folders outside OUTPUT_DIR the code must read. Needs the user's approval; request only what the task needs.",
                },
                "extra_write_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Absolute paths of existing folders or files outside OUTPUT_DIR the code must write. Needs the user's approval.",
                },
                "network_hosts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "host:port destinations the code must connect to, e.g. 'api.example.com:443'. Needs the user's approval; approval turns on outbound network for the whole run.",
                },
            },
            "required": ["code"],
        },
    }
]
```

- [ ] **Step 4: Implement the telemetry hook**

In `web/agent_loop.py`, `_summarize_tool_calls`, replace the loop body's result branch:

```python
        if results and i < len(results):
            r = results[i]
            if isinstance(r, dict) and r.get("error"):
                entry["success"] = False
                entry["error"] = str(r["error"])[:300]
            else:
                entry["success"] = True
        else:
            entry["success"] = None
        out.append(entry)
```

with:

```python
        if results and i < len(results):
            r = results[i]
            if isinstance(r, dict) and r.get("error"):
                entry["success"] = False
                entry["error"] = str(r["error"])[:300]
            else:
                entry["success"] = True
            # Code-runner sandbox: one metadata-only record per run (no paths, hosts, code or output).
            if isinstance(r, dict) and isinstance(r.get("_sandbox_telemetry"), dict):
                entry["sandbox"] = r["_sandbox_telemetry"]
        else:
            entry["success"] = None
        out.append(entry)
```

- [ ] **Step 5: Rewrite `SKILL.md`**

In `web/skills/code_runner/SKILL.md`, change the frontmatter `description` to:

```yaml
description: Execute Python code in an OS sandbox — produce files, run calculations, generate images and charts; reading or writing other local paths or using the network needs the user's approval
```

Change the first paragraph under `# Code Runner` to: "Use this skill any time you need to execute Python code — to produce output files, run calculations, process data, or (with the user's approval) read local files."

Replace the bullet "- Any task that requires reading from or writing to the local machine" with "- A task that needs a local file or folder the user named (request it with `extra_read_paths` / `extra_write_paths`)".

Replace the whole `## Local filesystem access` section (heading through the line "**Write operations outside OUTPUT_DIR** will be flagged by the AST scanner and require user confirmation.") with:

````markdown
## What the code can access

The code runs in an OS sandbox:

- It can read and write only its own `OUTPUT_DIR`, and read the Python/Node runtime and `SKILL_DIR`.
- It has **no network** and **no access** to the rest of the user's files (home folder, Documents, Downloads, other drives).
- Its environment contains no tokens or API keys.

If the task really needs more, ask for it in the call:

- `extra_read_paths=[...]` — absolute paths of existing files or folders to read.
- `extra_write_paths=[...]` — absolute paths of existing folders or files to write.
- `network_hosts=["host:port", ...]` — destinations to connect to (approval turns on network for the whole run).

The first call returns `approval_required` and shows the user an approval card. Tell the user briefly what you asked for and why, then stop and wait. When the user says they approved, call `run_python` again with **exactly the same** code and the same `extra_read_paths`, `extra_write_paths` and `network_hosts` (any difference needs a new approval). An approval is used by one run and expires after 10 minutes. If the user denies, or the approval expired, do not retry.

Some locations can never be granted, even by the user: drive roots, the home folder itself, `~/.gator`, `~/.ssh`, `~/.aws`, `~/.azure`, `~/.kube`, `~/.gnupg`, `~/.config/gcloud`.

If a run fails with a permission or network error, `stderr` ends with a `[sandbox]` hint: request the access only if the task truly needs it.

```python
run_python(
    code="from pathlib import Path\nprint(Path(r'C:\\Users\\me\\Documents\\notes.txt').read_text(encoding='utf-8'))",
    extra_read_paths=[r"C:\Users\me\Documents\notes.txt"],
)
```
````

Replace the rule beginning "- **Editing the user's file? Honor the file they named.**" with:

```markdown
- **Editing the user's file? Honor the file they named.** If the user asked you to update an existing file at a path they gave, write back to THAT path: pass it (or its folder) in `extra_write_paths` and wait for the user's approval. Do NOT silently emit a new file in `OUTPUT_DIR` when they asked to edit their original. Only create a separate file when they asked for a copy or when no destination exists — and then ASK where, never invent a path.
```

and change "- Use absolute paths when _reading_ existing local files — the user's path is real." to "- Use absolute paths when _reading_ existing local files — the user's path is real — and list them in `extra_read_paths`."

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/code_runner tests/code_sandbox tests/test_agent_loop_sandbox.py tests/test_agent_loop_indicator.py tests/test_desktop_packaging.py -q -rs`
Expected: all pass; `test_real_sandboxed_run_on_windows` runs on this machine (skipped elsewhere).

- [ ] **Step 7: Commit**

```bash
git add web/skills/code_runner/tools.py web/skills/code_runner/SKILL.md web/agent_loop.py tests/code_runner/conftest.py tests/code_runner/test_run_python.py tests/code_runner/test_run_python_sandbox.py tests/code_sandbox/test_run_python_mode.py tests/test_agent_loop_sandbox.py
git commit -m "feat: run_python runs in the OS sandbox with user-approved extra paths and network, fails closed, and logs metadata-only telemetry"
```

---

### Task 8: UI — approval card, follow-up chat message, Settings notice and opt-out

**Files:**

- Modify: `web/agent_loop.py` (`_run_tool_block` after the `_jira_target_selection` branch, lines 513-514; SSE branches after lines 971-972 and 1487-1488)
- Modify: `web/static/app.js` (stream handler after line 12092-12093 `msg.jira_target_selection` branch; new functions after `_showJiraTargetSelection`, which ends at line 8889; call in the Settings init after `_initClearCredentialsSettings();` at line 15781)
- Modify: `web/static/index.html` (new row after the "Stored credentials" row, which ends just before `<!-- ═══ Google Workspace ═══ -->`, around line 693)
- Modify: `tests/test_agent_loop_sandbox.py` (append)
- Create: `tests/sandbox_ui.test.js`

**Interfaces:**

- Consumes: result key `_sandbox_approval` (Task 7) with keys `request_id`, `read_paths`, `write_paths`, `network_hosts`, `context_id`; `POST /api/sandbox/requests/{id}/approve|deny` with `{context_id}`, `GET /api/sandbox/status`, `POST /api/sandbox/opt-out` (Task 3); existing `_activeTabId`, `_showConnectivityToast`, `#chat-input`, `#chat-form`, `#messages`, `window.__CSRF_TOKEN__`, `/api/csrf`.
- Produces: SSE event `{"sandbox_approval": {...}}`; JS functions `_sandboxFollowUpText(decision, requestId) -> string`, `_sendSandboxFollowUp(tabId, text)`, `_showSandboxApproval(data, ownerTabId)`, `_sandboxNoticeText(status) -> string`, `_initSandboxSettings()`; DOM ids `sandbox-row`, `sandbox-notice`, `sandbox-optout-label`, `sandbox-optout`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_loop_sandbox.py`:

```python
import asyncio

from agent_loop import _make_tool_runner


def test_runner_emits_sandbox_approval_event():
    card = {"request_id": "abc", "read_paths": ["C:/data"], "write_paths": [], "network_hosts": [], "context_id": "tab-1"}

    async def fake_execute(name, inputs, **kw):
        return {"approval_required": True, "request_id": "abc", "_sandbox_approval": card}

    run_tool_block, _, _ = _make_tool_runner(fake_execute, set(), {}, lambda n, r: None, "__slack_safe__")

    async def go():
        q = asyncio.Queue()
        await run_tool_block(SimpleNamespace(name="run_python", inputs={"code": "1"}, id="c1"), q)
        return [q.get_nowait() for _ in range(q.qsize())]

    loop = asyncio.new_event_loop()
    try:
        events = loop.run_until_complete(go())
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())
    assert {"kind": "sandbox_approval", "data": card} in events


def test_both_stream_loops_forward_sandbox_approval():
    src = (pathlib.Path(__file__).parent.parent / "web" / "agent_loop.py").read_text(encoding="utf-8")
    assert src.count("yield f\"data: {json.dumps({'sandbox_approval': evt.get('data', {})})}\\n\\n\"") == 2
```

Create `tests/sandbox_ui.test.js`:

```javascript
// Code-runner sandbox UI: approval card follow-up text, Settings notice text,
// and the rule that model-supplied strings are never put through innerHTML.
// Pure functions are extracted from app.js and run in isolation (no DOM).

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function extract(name) {
  const match = source.match(new RegExp(`function ${name}\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}`));
  assert(match, `${name} not found in app.js`);
  return match[0];
}

const followUp = vm.runInNewContext(
  extract('_sandboxFollowUpText') + '; _sandboxFollowUpText;',
  {},
);
const notice = vm.runInNewContext(extract('_sandboxNoticeText') + '; _sandboxNoticeText;', {});

assert.match(followUp('approve', 'abc123'), /approved sandbox access request abc123/);
assert.match(followUp('approve', 'abc123'), /exactly the same/);
assert.match(followUp('deny', 'abc123'), /denied sandbox access request abc123/);
assert.match(followUp('deny', 'abc123'), /Do not retry/);

assert.strictEqual(notice({ level: 'enforced', reason: null, opted_out: false, policy: {} }), '');
assert.strictEqual(notice(null), '');
assert.match(
  notice({ level: 'unavailable', reason: 'Install bubblewrap.', opted_out: false, policy: {} }),
  /Install bubblewrap\..*blocked/,
);
assert.match(
  notice({
    level: 'unavailable',
    reason: 'x',
    opted_out: true,
    policy: { require_sandbox: false },
  }),
  /without a sandbox/,
);
assert.match(
  notice({ level: 'unavailable', reason: 'x', opted_out: true, policy: { require_sandbox: true } }),
  /blocked/,
);

for (const name of ['_showSandboxApproval', '_initSandboxSettings', '_sendSandboxFollowUp']) {
  assert(!/innerHTML/.test(extract(name)), `${name} must not use innerHTML`);
}
assert(source.includes('_showSandboxApproval(msg.sandbox_approval, requestTabId)'));
assert(source.includes('  _initSandboxSettings();'));

console.log('sandbox_ui: all assertions passed');
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_agent_loop_sandbox.py -q && node tests/sandbox_ui.test.js`
Expected: the two new Python tests FAIL; the Node script fails with "\_sandboxFollowUpText not found in app.js".

- [ ] **Step 3: Implement the server side**

In `web/agent_loop.py` `_run_tool_block`, directly after

```python
        if isinstance(result, dict) and "_jira_target_selection" in result:
            await event_queue.put({"kind": "jira_target_selection", "data": result["_jira_target_selection"]})
```

add:

```python
        if isinstance(result, dict) and "_sandbox_approval" in result:
            await event_queue.put({"kind": "sandbox_approval", "data": result["_sandbox_approval"]})
```

In both SSE loops, directly after each

```python
                elif kind == "jira_target_selection":
                    yield f"data: {json.dumps({'jira_target_selection': evt.get('data', {})})}\n\n"
```

add:

```python
                elif kind == "sandbox_approval":
                    yield f"data: {json.dumps({'sandbox_approval': evt.get('data', {})})}\n\n"
```

- [ ] **Step 4: Implement the chat card**

In `web/static/app.js`, in the stream handler, directly after

```javascript
            } else if (msg.jira_target_selection) {
              _showJiraTargetSelection(msg.jira_target_selection, requestTabId);
```

add:

```javascript
            } else if (msg.sandbox_approval) {
              _showSandboxApproval(msg.sandbox_approval, requestTabId);
```

Directly after the closing `}` of `function _showJiraTargetSelection(...)` add:

```javascript
// ── Code-runner sandbox approval card ────────────────────────────────────────
// Paths and hosts come from the model: they are rendered with textContent
// only. Approve/Deny go to CSRF-guarded routes the agent loop cannot call;
// a short chat message then tells the model whether to re-call.
function _sandboxFollowUpText(decision, requestId) {
  return decision === 'approve'
    ? `I approved sandbox access request ${requestId}. Run the same run_python call again with exactly the same extra_read_paths, extra_write_paths and network_hosts.`
    : `I denied sandbox access request ${requestId}. Do not retry it; continue without that access or tell me what you need.`;
}

function _sendSandboxFollowUp(tabId, text) {
  if (tabId !== _activeTabId) {
    _showConnectivityToast(
      'Decision saved. Switch to that tab and tell AI Gator to continue.',
      'info',
    );
    return;
  }
  const input = document.getElementById('chat-input');
  const form = document.getElementById('chat-form');
  if (input && form) {
    input.textContent = text;
    form.requestSubmit();
  }
}

function _showSandboxApproval(data, ownerTabId) {
  const requestId = data && typeof data.request_id === 'string' ? data.request_id : '';
  if (!requestId) return;
  const seen = Array.from(document.querySelectorAll('[data-sandbox-request]')).some(
    (el) => el.dataset.sandboxRequest === requestId,
  );
  if (seen) return;
  const card = document.createElement('div');
  card.className = 'message assistant';
  card.dataset.sandboxRequest = requestId;
  const bubble = document.createElement('div');
  bubble.className = 'bubble card-bubble';
  const box = document.createElement('div');
  box.className = 'gator-compose-card gator-draft-card';

  const header = document.createElement('div');
  header.className = 'gcc-header';
  const title = document.createElement('div');
  title.className = 'gcc-title';
  title.textContent = 'Code wants extra access for one run';
  header.appendChild(title);

  const body = document.createElement('div');
  body.className = 'gcc-body';
  [
    ['Read', data.read_paths],
    ['Read and write', data.write_paths],
    ['Connect to', data.network_hosts],
  ].forEach(([label, items]) => {
    if (!Array.isArray(items) || !items.length) return;
    const row = document.createElement('div');
    row.className = 'gcc-field-row gcc-field-row--block';
    const key = document.createElement('span');
    key.className = 'gcc-field-key';
    key.textContent = label;
    const list = document.createElement('ul');
    list.className = 'gcc-field-val';
    items.forEach((item) => {
      const li = document.createElement('li');
      li.textContent = String(item);
      list.appendChild(li);
    });
    row.append(key, list);
    body.appendChild(row);
  });
  if (Array.isArray(data.network_hosts) && data.network_hosts.length) {
    const note = document.createElement('div');
    note.className = 'gcc-refine';
    note.textContent =
      'Approving turns on outbound network for this whole run; the host is shown to you but not enforced.';
    body.appendChild(note);
  }

  const actions = document.createElement('div');
  actions.className = 'gcc-actions';
  const approve = document.createElement('button');
  approve.className = 'gcc-approve-btn';
  approve.textContent = 'Approve';
  const deny = document.createElement('button');
  deny.className = 'btn-secondary';
  deny.textContent = 'Deny';
  actions.append(approve, deny);

  const footer = document.createElement('div');
  footer.className = 'gcc-footer';
  const footNote = document.createElement('span');
  footNote.className = 'gcc-refine';
  footNote.textContent = 'Applies to one run only. Requests expire after 10 minutes.';
  footer.appendChild(footNote);

  box.append(header, body, actions, footer);
  bubble.appendChild(box);
  card.appendChild(bubble);

  const tabId = ownerTabId || _activeTabId || 'default';
  const decide = async (decision) => {
    approve.disabled = true;
    deny.disabled = true;
    const post = () =>
      fetch(`/api/sandbox/requests/${encodeURIComponent(requestId)}/${decision}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': window.__CSRF_TOKEN__ || '',
        },
        body: JSON.stringify({ context_id: tabId }),
      });
    try {
      let res = await post();
      if (res.status === 403) {
        const fresh = await fetch('/api/csrf')
          .then((r) => (r.ok ? r.json() : null))
          .catch(() => null);
        if (fresh?.csrf_token) window.__CSRF_TOKEN__ = fresh.csrf_token;
        res = await post();
      }
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail?.detail || `HTTP ${res.status}`);
      }
      footNote.textContent = decision === 'approve' ? 'Approved for one run.' : 'Denied.';
      actions.remove();
      _sendSandboxFollowUp(tabId, _sandboxFollowUpText(decision, requestId));
    } catch (err) {
      approve.disabled = false;
      deny.disabled = false;
      // 'warn', not 'error': _showConnectivityToast mutes error toasts.
      _showConnectivityToast(`Could not record your decision: ${err.message}`, 'warn');
    }
  };
  approve.addEventListener('click', (e) => {
    e.stopPropagation();
    decide('approve');
  });
  deny.addEventListener('click', (e) => {
    e.stopPropagation();
    decide('deny');
  });
  document.getElementById('messages')?.appendChild(card);
  card.scrollIntoView({ behavior: 'smooth', block: 'end' });
}
```

- [ ] **Step 5: Implement the Settings notice and opt-out**

In `web/static/index.html`, directly after the "Stored credentials" `srow` block (just before `<!-- ═══ Google Workspace ═══ -->`):

```html
<!-- ═══ Code sandbox (shown only when the sandbox is unavailable) ═══ -->
<div class="srow integration-row-sep" id="sandbox-row" style="display: none">
  <div class="srow-info">
    <div class="srow-label">Code sandbox</div>
    <div class="srow-sub" id="sandbox-notice"></div>
    <label class="srow-sub" id="sandbox-optout-label" hidden>
      <input type="checkbox" id="sandbox-optout" />
      Allow code to run without a sandbox on this machine
    </label>
  </div>
</div>
```

In `web/static/app.js`, directly after the closing `}` of `function _initClearCredentialsSettings()` add:

```javascript
function _sandboxNoticeText(status) {
  if (!status || status.level !== 'unavailable') return '';
  const reason = status.reason || 'The sandbox could not start.';
  const required = !!(status.policy && status.policy.require_sandbox);
  if (status.opted_out && !required) {
    return `Code sandbox unavailable: ${reason} Code currently runs without a sandbox because you allowed it below.`;
  }
  return `Code sandbox unavailable: ${reason} Running code is blocked until this is fixed.`;
}

function _initSandboxSettings() {
  const row = document.getElementById('sandbox-row');
  const notice = document.getElementById('sandbox-notice');
  const label = document.getElementById('sandbox-optout-label');
  const box = document.getElementById('sandbox-optout');
  if (!row || !notice || !label || !box) return;
  const refresh = () =>
    fetch('/api/sandbox/status')
      .then((r) => (r.ok ? r.json() : null))
      .then((s) => {
        const text = _sandboxNoticeText(s);
        if (!text) {
          row.style.display = 'none';
          return;
        }
        notice.textContent = text;
        row.style.display = '';
        const required = !!(s.policy && s.policy.require_sandbox);
        label.hidden = required;
        box.checked = !!s.opted_out && !required;
      })
      .catch(() => {});
  refresh();
  box.addEventListener('change', async () => {
    const wanted = box.checked;
    const post = () =>
      fetch('/api/sandbox/opt-out', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': window.__CSRF_TOKEN__ || '',
        },
        body: JSON.stringify({ opted_out: wanted }),
      });
    try {
      let res = await post();
      if (res.status === 403) {
        const fresh = await fetch('/api/csrf')
          .then((r) => (r.ok ? r.json() : null))
          .catch(() => null);
        if (fresh?.csrf_token) window.__CSRF_TOKEN__ = fresh.csrf_token;
        res = await post();
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    } catch (e) {
      box.checked = !wanted;
      alert('Could not change the code sandbox setting.');
    }
    refresh();
  });
}
```

In the Settings init, directly after `  _initClearCredentialsSettings();` add:

```javascript
_initSandboxSettings();
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/test_agent_loop_sandbox.py tests/test_agent_loop_indicator.py tests/test_desktop_packaging.py -q && node tests/sandbox_ui.test.js && node tests/streaming_space_join.test.js`
Expected: all pass; Node prints `sandbox_ui: all assertions passed`.

- [ ] **Step 7: Manual check in the running app (Windows)**

Start the dev app (`./dev.ps1` or `launch-dev.ps1`), ask: "Use run_python to print the first line of C:\Windows\win.ini". Expected: an approval card listing `C:\Windows\win.ini` under "Read" (or, because `C:\Windows` is readable by ALL APPLICATION PACKAGES, the model may succeed without asking; then ask for a file under `Documents`). Click **Approve**: the card shows "Approved for one run." and a chat message "I approved sandbox access request …" is sent; the model re-calls and the file content appears. Repeat with **Deny** and confirm the model does not retry. Open Settings: the "Code sandbox" row is hidden (sandbox available).

- [ ] **Step 8: Commit**

```bash
git add web/agent_loop.py web/static/app.js web/static/index.html tests/test_agent_loop_sandbox.py tests/sandbox_ui.test.js
git commit -m "feat: sandbox approval card with follow-up chat message, and Settings notice and opt-out when the sandbox is unavailable"
```

---

### Task 9: Linux packaging, documentation, tracker, full verification

**Files:**

- Modify: `shell/package.json` (`build.deb.depends`)
- Modify: `tests/test_desktop_packaging.py` (append)
- Modify: `docs/BUILD_INSTRUCTIONS.md` (Prerequisites platform notes, line 23; new section before `## Troubleshooting`; Troubleshooting table)
- Modify: `docs/security/threatmodel-remediation.md` (row `H_Code_runner_skill_used_for_lateral_movem_06`, line 16)

**Interfaces:**

- Consumes: everything above; the measured run time from Task 4 Step 5 and the Task 1 decision.
- Produces: documentation only, plus the `.deb` dependency on `bubblewrap`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_desktop_packaging.py`:

```python
def test_linux_deb_depends_on_bubblewrap_and_docs_explain_it():
    package = json.loads((ROOT / "shell" / "package.json").read_text(encoding="utf-8"))
    depends = package["build"]["deb"]["depends"]
    assert "bubblewrap" in depends
    # electron-builder replaces (does not extend) its default list, so keep it.
    for default in ("libgtk-3-0", "libnotify4", "libnss3", "libxss1", "libxtst6",
                    "xdg-utils", "libatspi2.0-0", "libuuid1", "libsecret-1-0"):
        assert default in depends
    build_doc = (ROOT / "docs" / "BUILD_INSTRUCTIONS.md").read_text(encoding="utf-8")
    assert "Linux: bubblewrap" in build_doc
    assert "Code sandbox smoke test (release gate)" in build_doc
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_desktop_packaging.py::test_linux_deb_depends_on_bubblewrap_and_docs_explain_it -q`
Expected: FAIL (`KeyError: 'deb'`).

- [ ] **Step 3: Implement packaging and docs**

In `shell/package.json`, inside `"build"`, after the `"linux": {...}` object add:

```json
    "deb": {
      "depends": [
        "libgtk-3-0",
        "libnotify4",
        "libnss3",
        "libxss1",
        "libxtst6",
        "xdg-utils",
        "libatspi2.0-0",
        "libuuid1",
        "libsecret-1-0",
        "bubblewrap"
      ]
    },
```

(The first nine entries are electron-builder's default `deb.depends`, from `shell/node_modules/app-builder-lib/out/options/linuxOptions.d.ts`; setting `depends` replaces the default, so they must be repeated.)

In `docs/BUILD_INSTRUCTIONS.md`, Prerequisites "Platform notes", replace the Linux bullet with:

```markdown
- Linux: use a desktop session with the standard Electron/Chromium libraries supplied by mainstream desktop distributions, and install `bubblewrap` (see "Linux: bubblewrap" below). The `.deb` declares it; the AppImage cannot, so AppImage users must install it themselves.
```

Before `## Troubleshooting` add:

````markdown
## Code sandbox

AI Gator runs model-written `run_python` code in an OS sandbox: Windows AppContainer (built in, no admin), macOS Seatbelt (`/usr/bin/sandbox-exec`, built in), Linux bubblewrap. If the sandbox cannot start, running code is blocked and Settings shows the reason; the user may allow unsandboxed runs there unless the admin policy requires the sandbox.

### Linux: bubblewrap

```bash
sudo apt install bubblewrap      # Debian/Ubuntu
sudo dnf install bubblewrap      # Fedora/RHEL
bwrap --unshare-all --ro-bind / / -- true && echo ok
```

If the last command fails, unprivileged user namespaces are disabled or restricted (for example `kernel.unprivileged_userns_clone=0`, or the Ubuntu 24.04+ AppArmor restriction `kernel.apparmor_restrict_unprivileged_userns=1` without a bwrap profile). Ask the administrator to allow them for bubblewrap; AI Gator does not change system settings.

### Admin policy file

`%ProgramData%\AIGator\sandbox-policy.json` (Windows), `/Library/Application Support/AIGator/sandbox-policy.json` (macOS), `/etc/aigator/sandbox-policy.json` (Linux; must be root-owned and not group/world-writable):

```json
{ "code_runner": "enabled", "network": "ask", "filesystem": "ask", "require_sandbox": false }
```

`code_runner: disabled` blocks code execution, `network: deny` refuses network requests, `filesystem: strict` refuses extra paths, `require_sandbox: true` hides the user opt-out. A present but invalid file fails closed (`network: deny`, `filesystem: strict`, `require_sandbox: true`).

### Code sandbox smoke test (release gate)

The macOS and Linux launchers are verified by unit tests on Windows (and Linux through WSL Ubuntu). Before a release, run on a real Mac and on a real Linux desktop (installed package, not a dev checkout):

1. `python3 tests/code_sandbox/posix_sandbox_check.py macos` (or `linux`) from a checkout on that machine: `probe` is `null`, `default.read_secret`, `default.read_extra` and `default.net_external` start with `DENIED`, `default.token` is `null`, `with_extra.read_extra` is `OK:extra-data`, `tree_kill.timed_out` is `true`, `leftover_sleepers` is `0`.
2. In the installed app ask: "Use run_python to make a PNG chart in OUTPUT_DIR": the file is returned.
3. Ask: "Use run_python to read ~/Documents/<some file>": an approval card appears; Approve runs it once; asking again shows a new card; Deny is not retried.
4. Ask for a network call to `example.com:443`: card mentions network for the whole run; approved run succeeds; unapproved run fails with the `[sandbox]` hint.
5. Rename `bwrap` away (Linux) or run on a machine without it: Settings shows the notice and the opt-out checkbox; code is blocked until opted out.
   Record the result (date, OS version, pass/fail per step) in the PR before release.
````

In the Troubleshooting table add a row (keep the column alignment style of the table):

```markdown
| Code runs fail with "code sandbox is unavailable" | Linux: install `bubblewrap` and allow unprivileged user namespaces (see "Code sandbox"); Windows/macOS: see the reason in Settings |
```

- [ ] **Step 4: Update the tracker row**

In `docs/security/threatmodel-remediation.md`, replace the whole `H_Code_runner_skill_used_for_lateral_movem_06` row with (use the Task 4 Step 5 measured run time where it says "about N s"; if Task 1 Step 6 ended in "stop here", replace the Frozen sentence with the measured numbers):

```markdown
| `H_Code_runner_skill_used_for_lateral_movem_06` | Code-runner skill usable for lateral movement / unrestricted network & filesystem egress | **Implemented (Windows verified; macOS/Linux pending real-system smoke test)** | [design](../superpowers/specs/2026-10-05-code-runner-sandbox-design.md) / [plan](../superpowers/plans/2026-10-05-code-runner-sandbox.md) | `run_python` now runs model code in an OS sandbox behind one `web/sandbox` interface: Windows AppContainer (ctypes, no admin, Job Object tree kill), macOS Seatbelt, Linux bubblewrap. By default the code reads and writes only its run folder, reads the runtime, has no network, and gets an allow-list environment (every token dropped). Extra paths and network need a real user approval: a chat card whose Approve/Deny call CSRF-guarded routes the agent loop cannot reach; the approval must match the same tab and exactly the same normalized set, is used by one run and expires after 10 minutes. Drive roots, the home folder and its parents, `~/.gator` (except `outputs`), `~/.ssh`, `~/.aws`, `~/.azure`, `~/.kube`, `~/.gnupg`, `~/.config/gcloud` (and their parents) can never be granted. A machine-wide admin policy file can disable code, refuse network, refuse extra paths and forbid the user opt-out; a bad policy file fails closed. When the sandbox is unavailable code is blocked (Settings explains the fix) unless the user opts out and the policy allows it. Metadata-only telemetry per run (level, network, extra counts, approval decision). The frozen sidecar is now onedir: the reported `--run-python` "hang" was ~42 s of onefile re-extraction per run. Partial vs. the report: network approval is all or nothing per run (host shown, not enforced, no proxy); on Windows approved network uses only the `internetClient` capability, so private/intranet hosts stay unreachable. Known gaps: `run_shell` is unsandboxed and can run `python` (bypass, not named in the report, unchanged); `packages=[...]` pip installs run unsandboxed; same-user malware and OS sandbox escapes are out of scope; on Windows runtime directories keep a persistent read+execute ACE for the AI Gator container SID (per-run grants are revoked, a ledger plus startup sweep removes leftovers after a crash) and sandboxed runs are serialized; steady-state sandboxed run time about N s on the dev machine; approval decisions reach turn telemetry only when a later `run_python` call observes them (the decision itself is in the server log); the macOS launcher is verified by profile-builder tests only and the Linux launcher by WSL Ubuntu (bubblewrap 0.11.1), both need the manual smoke test on a real Mac and Linux desktop before release (release gate, not yet run); the macOS profile allows file metadata reads everywhere; AppImage FUSE mounts under bubblewrap, Windows 10, antivirus/EDR reactions, long paths and loopback exemptions were not tested. |
```

- [ ] **Step 5: Full verification**

Run: `python -m pytest tests -q -x --deselect tests/test_marketplace_installer.py`
Expected: all pass except known unrelated failures that also fail on `main` (confirm by name; do not deselect anything else).

Run: `node tests/sandbox_ui.test.js && node tests/streaming_space_join.test.js`
Expected: both print their "all assertions passed" line.

Run: `git status --short`
Expected: only the files of this task are modified; `pip/` remains untracked and is not staged.

- [ ] **Step 6: Commit**

```bash
git add shell/package.json tests/test_desktop_packaging.py docs/BUILD_INSTRUCTIONS.md docs/security/threatmodel-remediation.md
git commit -m "docs: code-runner sandbox tracker row, Linux bubblewrap requirement, admin policy and release-gate smoke test"
```

---

## Self-Review

- **Spec coverage:**
  - Problem / approach (AppContainer, Seatbelt, bwrap; no off-the-shelf library): Tasks 4, 5, 6.
  - Interface (`SandboxRequest`, `SandboxResult`, `sandbox_level`, `sandbox_unavailable_reason`, `launch_sandboxed` raising `SandboxUnavailable`, per-OS launchers, pure builders): Task 2 (types and dispatch), Task 4 (`acl_grants`, `ace_spec`), Task 5 (`build_profile`), Task 6 (`build_argv`).
  - Default contents: run folder read/write (Tasks 4-6), runtime paths incl. skill folder and npm root (Task 7 `_runtime_paths`), OS system directories (Task 5 `SYSTEM_READ_PATHS`, Task 6 `SYSTEM_RO_PATHS`/`ETC_RO_PATHS`, AppContainer none), no network (Tasks 4-6 tests), environment allow-list (Task 2 `build_env`), children inherit (tree-kill tests in Tasks 4-6), Node flags (Task 2 `NODE_OPTIONS`), icacls grants and revoke without admin (Task 4, with the documented persistent-runtime deviation).
  - Approval flow steps 1-6: normalization and deny list (Task 2), `approval_required` and server-side request (Task 7 `_approval_gate`, Task 3 store), card with CSRF routes and follow-up chat message (Tasks 3 and 8), tab plus exact-set plus 10 minutes plus consume-once (Task 3), network all or nothing (Tasks 4-6, card note in Task 8), denied/expired fixed errors (Task 7). Permission hint and SKILL.md/tool description rewrite (Task 7).
  - Policy file, locations, mtime cache, defaults, fail-closed rules, POSIX owner/mode check, Windows ACL not checked (Task 2); enforcement (Task 7); status (Task 3).
  - Unavailable: probes per OS (Tasks 4-6), fail closed with reason (Task 7), Settings notice and opt-out checkbox only without `require_sandbox` (Task 8), `code_runner_sandbox: "off"` and `GET /api/sandbox/status` (Task 3), results carry `sandbox: "off"` (Task 7).
  - Telemetry: record (Task 2), turn telemetry entry (Task 7), decisions (Task 7 via `_approval_gate`, server log in Task 3).
  - Packaging: Linux deb and docs (Task 9), frozen runtime path (Task 7), frozen `--run-python` diagnosis and fix (Task 1).
  - Testing: builders on every OS (Tasks 4-6), real Windows runs incl. stale-ACE sweep (Task 4), WSL real runs (Task 6), macOS builder-only plus release gate (Tasks 5, 9), existing suite kept green with an autouse fixture plus fake-launcher tests plus one real Windows run (Task 7).
  - Known gaps and out of scope: tracker row (Task 9); `shell_runner` untouched (Global Constraints).
- **Placeholders:** none in code steps. Task 9 Step 4 asks the implementer to put the measured number from Task 4 Step 5 into the tracker text ("about N s"); that value cannot be known before the run.
- **Type consistency:** `SandboxRequest`/`SandboxResult` fields, `telemetry_record(run_id, skill_id, level, network, extra_read, extra_write, approval)`, `approvals.lookup/create/decide`, `Policy(code_runner, network, filesystem, require_sandbox)`, `_sandbox_mode(cfg, policy)`, `_runtime_paths(skill_dir, npm_root)`, the `_sandbox_approval` keys (`request_id`, `read_paths`, `write_paths`, `network_hosts`, `context_id`) and the SSE key `sandbox_approval` are used with the same names in every task.
