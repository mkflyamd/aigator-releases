import base64
import os
import stat
import sys
import types

import pytest

import secure_store

FAKE = "aigator-fake-api-key"
NAME = "config/jira_pat"


@pytest.fixture
def vault(monkeypatch):
    store = {}
    state = {"available": True}

    def get():
        if not state["available"]:
            raise secure_store._VaultUnavailable("no keyring")
        return store.get("key")

    def put(value):
        if not state["available"]:
            raise secure_store._VaultUnavailable("no keyring")
        store["key"] = value

    monkeypatch.setattr(secure_store, "_vault_get", get)
    monkeypatch.setattr(secure_store, "_vault_set", put)
    monkeypatch.setattr(secure_store, "_MASTER", None)
    monkeypatch.setattr(secure_store, "_LEVEL", "os-vault")
    monkeypatch.setattr(secure_store, "_platform", lambda: "linux")
    monkeypatch.setattr(secure_store, "_protect", secure_store._vault_protect)
    monkeypatch.setattr(secure_store, "_unprotect", secure_store._vault_unprotect)
    return types.SimpleNamespace(store=store, state=state)


def test_round_trip_and_unique_nonce(vault):
    a = secure_store._vault_protect(b"hello")
    b = secure_store._vault_protect(b"hello")
    assert a != b
    assert a[:1] == b"\x02"
    assert secure_store._vault_unprotect(a) == b"hello"


def test_key_created_once_and_reused(vault):
    secure_store.set(NAME, FAKE)
    first = vault.store["key"]
    secure_store._MASTER = None
    assert secure_store.get(NAME) == FAKE
    assert vault.store["key"] == first


def test_tampered_blob_returns_none(vault):
    secure_store.set(NAME, FAKE)
    path = secure_store._path(NAME)
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 0x01
    path.write_bytes(bytes(raw))
    assert secure_store.get(NAME) is None


def test_lost_key_returns_none(vault):
    secure_store.set(NAME, FAKE)
    vault.store.clear()
    secure_store._MASTER = None
    assert secure_store.get(NAME) is None


def test_linux_without_vault_uses_user_only_key_file(vault):
    vault.state["available"] = False
    secure_store.set(NAME, FAKE)
    key_file = secure_store._key_file()
    assert key_file.exists()
    if os.name == "posix":
        assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert secure_store.protection_level() == "key-file"
    secure_store._MASTER = None
    assert secure_store.get(NAME) == FAKE


def test_macos_without_vault_fails_closed(vault, monkeypatch):
    monkeypatch.setattr(secure_store, "_platform", lambda: "darwin")
    vault.state["available"] = False
    with pytest.raises(secure_store.SecureStoreError):
        secure_store.set(NAME, FAKE)
    assert secure_store.protection_level() == "unavailable"
    assert not secure_store._key_file().exists()


def test_key_file_is_adopted_when_vault_appears(vault):
    vault.state["available"] = False
    secure_store.set(NAME, FAKE)
    key_file = secure_store._key_file()
    file_key = key_file.read_text().strip()
    vault.state["available"] = True
    secure_store._MASTER = None
    assert secure_store.get(NAME) == FAKE
    assert vault.store["key"] == file_key
    assert not key_file.exists()
    assert secure_store.protection_level() == "os-vault"


def test_first_use_race_uses_the_key_the_vault_returns(vault, monkeypatch):
    other = base64.b64encode(b"\x07" * 32).decode()
    monkeypatch.setattr(
        secure_store, "_vault_set", lambda value: vault.store.__setitem__("key", other)
    )
    assert secure_store._master_key() == b"\x07" * 32


def test_invalid_vault_value_raises(vault):
    vault.store["key"] = "not-base64!!"
    with pytest.raises(secure_store.SecureStoreError):
        secure_store._master_key()


def test_windows_level_does_not_touch_the_vault(vault, monkeypatch):
    monkeypatch.setattr(secure_store, "_platform", lambda: "win32")
    monkeypatch.setattr(secure_store, "_vault_get", lambda: pytest.fail("vault touched"))
    assert secure_store.protection_level() == "os-vault"


def test_legacy_plaintext_migrates_through_the_vault_backend(vault):
    legacy = secure_store._home() / ".config" / "slack-mcp" / "token.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"access_token": "%s"}' % FAKE)
    assert secure_store.get_json("slack/token") == {"access_token": FAKE}
    assert not legacy.exists()
    # The migrated blob is a vault-format blob, keyed by the vault master key.
    blob = secure_store._path("slack/token").read_bytes()
    assert blob[:1] == b"\x02"
    assert FAKE.encode() not in blob
    assert "key" in vault.store
    secure_store._MASTER = None
    assert secure_store.get_json("slack/token") == {"access_token": FAKE}


def test_transient_vault_outage_does_not_mint_a_new_key(vault):
    secure_store.set(NAME, FAKE)
    vault.state["available"] = False
    secure_store._MASTER = None
    with pytest.raises(secure_store.SecureStoreError):
        secure_store.set("config/other", FAKE)
    with pytest.raises(secure_store.SecureStoreError):
        secure_store.get(NAME)
    assert not secure_store._key_file().exists()
    assert secure_store.protection_level() == "unavailable"
    # Vault returns: the original blob still decrypts with the original key.
    vault.state["available"] = True
    assert secure_store.get(NAME) == FAKE


def test_key_file_write_leaves_no_temp_files(vault):
    vault.state["available"] = False
    secure_store.set(NAME, FAKE)
    leftovers = [p.name for p in secure_store._root().iterdir() if p.name.startswith(".tmp_master_")]
    assert leftovers == []
    assert len(secure_store._read_key_file()) == 32


class _KeyringError(Exception):
    pass


@pytest.fixture
def fake_keyring(monkeypatch):
    calls = []
    behavior = {"error": None, "value": None}

    def get_password(service, user):
        calls.append(("get", service, user))
        if behavior["error"]:
            raise behavior["error"]
        return behavior["value"]

    def set_password(service, user, value):
        calls.append(("set", service, user, value))
        if behavior["error"]:
            raise behavior["error"]

    kr = types.ModuleType("keyring")
    kr.get_password = get_password
    kr.set_password = set_password
    errors = types.ModuleType("keyring.errors")
    errors.KeyringError = _KeyringError
    kr.errors = errors
    monkeypatch.setitem(sys.modules, "keyring", kr)
    monkeypatch.setitem(sys.modules, "keyring.errors", errors)
    return types.SimpleNamespace(calls=calls, behavior=behavior)


def test_vault_wrappers_pass_through_service_and_user(fake_keyring):
    fake_keyring.behavior["value"] = "abc"
    assert secure_store._vault_get() == "abc"
    secure_store._vault_set("xyz")
    assert fake_keyring.calls == [
        ("get", "AI Gator", "secure-store-master-key"),
        ("set", "AI Gator", "secure-store-master-key", "xyz"),
    ]


@pytest.mark.parametrize("exc", [_KeyringError("locked"), RuntimeError("dbus down")])
def test_vault_wrappers_convert_backend_errors(fake_keyring, exc):
    fake_keyring.behavior["error"] = exc
    with pytest.raises(secure_store._VaultUnavailable):
        secure_store._vault_get()
    with pytest.raises(secure_store._VaultUnavailable):
        secure_store._vault_set("xyz")


def test_vault_wrappers_convert_missing_keyring(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", None)
    with pytest.raises(secure_store._VaultUnavailable):
        secure_store._vault_get()
    with pytest.raises(secure_store._VaultUnavailable):
        secure_store._vault_set("xyz")
