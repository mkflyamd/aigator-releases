"""pytest configuration — adds web/ to sys.path so bare imports like
'import shared' resolve correctly when testing web.routes modules.

Also snapshots and restores shared module state (TOOLS, SKILL_TOOLS_MAP,
TOOL_DISPATCH) and config paths (WORK_DIR, TASKS_DB) around each test so
tests that monkeypatch these can't leak into siblings — the root cause of
order-dependent failures in test_skill_cap_always_on, test_skill_slash_alias,
test_turn_telemetry, and shell_runner tests.
"""
import atexit
import copy
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

# Redirect the home directory before any web module is imported. Modules such
# as shared.py call load_config() at import time and config.py binds
# ~/.gator at import time, so per-test fixtures are too late to keep the suite
# away from a developer's real config, secrets and token files.
_SESSION_HOME = tempfile.mkdtemp(prefix="aigator-test-home-")
for _var in ("HOME", "USERPROFILE"):
    os.environ[_var] = _SESSION_HOME
atexit.register(shutil.rmtree, _SESSION_HOME, ignore_errors=True)

sys.path.insert(0, str(Path(__file__).parent.parent / "web"))

import pytest

_JIRA_TEST_URL = "https://ci-default.atlassian.net"


@pytest.fixture(autouse=True)
def _isolated_secure_store(tmp_path, monkeypatch):
    """Fake reversible backend + temp home so tests never touch real DPAPI or
    a developer's real ~/.config token files."""
    import secure_store

    monkeypatch.setattr(secure_store, "_home", lambda: tmp_path / "home")
    monkeypatch.setattr(secure_store, "_protect", lambda b: b"FAKE:" + b[::-1])
    monkeypatch.setattr(
        secure_store, "_unprotect", lambda b: b[len(b"FAKE:"):][::-1]
    )
    yield


@pytest.fixture(autouse=True)
def _jira_browse_url_default():
    """Ensure jira_browse_url() succeeds in CI where JIRA_BASE_URL is not set.

    Uses a URL that differs from every test target URL so the synthesized
    builtin target never deduplicates away a rovo-mcp target that shares
    its base_url (e.g. https://jira.example.com used by Rovo test targets).
    """
    if os.environ.get("JIRA_BASE_URL"):
        yield
        return
    with patch("skills.jira.api.jira_browse_url", return_value=_JIRA_TEST_URL), \
         patch("skills.jira.api.jira_is_cloud", return_value=True):
        yield


@pytest.fixture(autouse=True)
def _restore_shared_state():
    """Snapshot shared.* registries and config paths before each test, restore after.

    Several test files monkeypatch shared.TOOLS / shared.SKILL_TOOLS_MAP /
    shared.TOOL_DISPATCH (or import app, which mutates them as a side effect).
    Others change config.WORK_DIR or config.TASKS_DB. Without restoration, a
    test that runs later and reads these values sees the mutated state and fails
    — but only when the mutating test ran first, making the failures
    order-dependent and flaky.

    Lazy-imports inside the fixture so conftest doesn't force the import before
    app.py has a chance to populate it.
    """
    snapshots = {}
    try:
        import shared
        snapshots["shared"] = {
            "TOOLS": copy.deepcopy(shared.TOOLS),
            "SKILL_TOOLS_MAP": copy.deepcopy(shared.SKILL_TOOLS_MAP),
            "TOOL_DISPATCH": copy.deepcopy(shared.TOOL_DISPATCH),
            "MCP_TOOL_DIAGNOSTICS": copy.deepcopy(shared.MCP_TOOL_DIAGNOSTICS),
        }
    except ModuleNotFoundError:
        pass
    try:
        import config
        snapshots["config"] = {
            "WORK_DIR": getattr(config, "WORK_DIR", None),
            "TASKS_DB": getattr(config, "TASKS_DB", None),
        }
    except ModuleNotFoundError:
        pass
    yield
    if "shared" in snapshots:
        import shared
        shared.TOOLS = snapshots["shared"]["TOOLS"]
        shared.SKILL_TOOLS_MAP = snapshots["shared"]["SKILL_TOOLS_MAP"]
        shared.TOOL_DISPATCH = snapshots["shared"]["TOOL_DISPATCH"]
        shared.MCP_TOOL_DIAGNOSTICS = snapshots["shared"]["MCP_TOOL_DIAGNOSTICS"]
    if "config" in snapshots:
        import config
        if snapshots["config"]["WORK_DIR"] is not None:
            config.WORK_DIR = snapshots["config"]["WORK_DIR"]
        if snapshots["config"]["TASKS_DB"] is not None:
            config.TASKS_DB = snapshots["config"]["TASKS_DB"]


@pytest.fixture(autouse=True)
def _hermetic_sandbox_policy(tmp_path, monkeypatch):
    """Never read the machine-wide sandbox policy (ProgramData, /Library, /etc) in tests."""
    from sandbox import policy

    monkeypatch.setattr(policy, "policy_path", lambda: tmp_path / "sandbox-policy.json")
    policy._reset_cache()
    yield
    policy._reset_cache()


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
