import pytest


@pytest.fixture(autouse=True)
def _legacy_shell_is_unsandboxed(monkeypatch):
    from skills.code_runner import tools as cr

    monkeypatch.setattr(cr, "_sandbox_mode", lambda cfg, policy: ("off", None))
