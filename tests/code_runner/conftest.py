import pytest


@pytest.fixture(autouse=True)
def _sandbox_off_for_legacy_suite(monkeypatch):
    """The pre-sandbox run_python suite exercises the unsandboxed path. Tests
    that need the sandbox re-patch `_sandbox_mode` (fake launcher) or use the
    real `windows_container` fixture."""
    import skills.code_runner.tools as cr_mod

    monkeypatch.setattr(cr_mod, "_sandbox_mode", lambda cfg, policy: ("off", None))
