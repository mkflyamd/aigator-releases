import pytest


@pytest.fixture(autouse=True)
def _legacy_shell_is_unsandboxed(monkeypatch):
    import sandbox
    from skills.code_runner import tools as cr

    monkeypatch.setattr(cr, "_sandbox_mode", lambda cfg, policy: ("off", None))
    monkeypatch.setattr(sandbox, "ungrantable_paths", lambda read, write: [])
