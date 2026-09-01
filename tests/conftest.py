"""pytest configuration — adds web/ to sys.path so bare imports like
'import shared' resolve correctly when testing web.routes modules.

Also snapshots and restores shared module state (TOOLS, SKILL_TOOLS_MAP,
TOOL_DISPATCH) and config paths (WORK_DIR, TASKS_DB) around each test so
tests that monkeypatch these can't leak into siblings — the root cause of
order-dependent failures in test_skill_cap_always_on, test_skill_slash_alias,
test_turn_telemetry, and shell_runner tests.
"""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "web"))

import pytest


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
    if "config" in snapshots:
        import config
        if snapshots["config"]["WORK_DIR"] is not None:
            config.WORK_DIR = snapshots["config"]["WORK_DIR"]
        if snapshots["config"]["TASKS_DB"] is not None:
            config.TASKS_DB = snapshots["config"]["TASKS_DB"]
