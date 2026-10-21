"""Round trip through the real OS credential vault (macOS Keychain, Linux Secret Service).

Runs only when AIGATOR_REAL_VAULT=1 (set by CI) so a developer's own Keychain is never touched
by accident. When enabled, a missing vault fails the test instead of skipping it.
"""
import os
import sys

import pytest

import secure_store

pytestmark = [
    pytest.mark.real_vault,
    pytest.mark.skipif(os.environ.get("AIGATOR_REAL_VAULT") != "1", reason="set AIGATOR_REAL_VAULT=1 to use the real OS vault"),
    pytest.mark.skipif(sys.platform == "win32", reason="Windows uses DPAPI, not the vault"),
]

FAKE = "aigator-fake-api-key"


@pytest.fixture
def real_vault(tmp_path, monkeypatch):
    import keyring

    monkeypatch.setattr(secure_store, "_home", lambda: tmp_path)
    monkeypatch.setattr(secure_store, "_VAULT_SERVICE", "AI Gator CI test")
    monkeypatch.setattr(secure_store, "_MASTER", None)
    yield
    try:
        keyring.delete_password("AI Gator CI test", secure_store._VAULT_USER)
    except Exception:
        pass


def test_master_key_lives_in_the_real_os_vault(real_vault):
    secure_store.set("config/jira_pat", FAKE)
    assert secure_store.protection_level() == "os-vault"
    assert secure_store.get("config/jira_pat") == FAKE
    assert not secure_store._key_file().exists()


def test_key_survives_a_restart(real_vault, monkeypatch):
    secure_store.set("config/jira_pat", FAKE)
    monkeypatch.setattr(secure_store, "_MASTER", None)
    assert secure_store.get("config/jira_pat") == FAKE
