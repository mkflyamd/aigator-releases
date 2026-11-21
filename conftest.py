"""Isolation for web/tests, which tests/conftest.py does not cover. Without
this a test that reads or migrates a token file reaches the real OS vault (on
macOS, a Keychain write that blocks a headless runner)."""
import pytest


@pytest.fixture(autouse=True)
def _isolated_secure_store(tmp_path, monkeypatch):
    import secure_store

    monkeypatch.setattr(secure_store, "_home", lambda: tmp_path / "home")
    monkeypatch.setattr(secure_store, "_protect", lambda b: b"FAKE:" + b[::-1])
    monkeypatch.setattr(secure_store, "_unprotect", lambda b: b[len(b"FAKE:"):][::-1])
    yield
