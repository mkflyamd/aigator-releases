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
    behavior = {"error": None, "value": None, "backend": _backend("keyring.backends.macOS")}

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
    kr.get_keyring = lambda: behavior["backend"]
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


# ── Final-review fixes ──────────────────────────────────────────────────────


def _backend(module):
    cls = type("Backend", (), {"__module__": module})
    return cls()


def test_unavailable_error_tells_user_how_to_reset(vault):
    secure_store.set(NAME, FAKE)
    vault.state["available"] = False
    secure_store._MASTER = None
    with pytest.raises(secure_store.SecureStoreError, match="Clear stored credentials"):
        secure_store.get(NAME)


def test_leftover_key_file_is_removed_when_vault_already_holds_the_key(vault):
    vault.state["available"] = False
    secure_store.set(NAME, FAKE)
    key_file = secure_store._key_file()
    vault.store["key"] = key_file.read_text().strip()
    vault.state["available"] = True
    secure_store._MASTER = None
    assert secure_store.get(NAME) == FAKE
    assert not key_file.exists()


def test_key_file_with_a_different_key_is_left_alone(vault):
    vault.state["available"] = False
    secure_store.set(NAME, FAKE)
    key_file = secure_store._key_file()
    vault.store["key"] = base64.b64encode(b"\x09" * 32).decode()
    vault.state["available"] = True
    secure_store._MASTER = None
    secure_store._master_key()
    assert key_file.exists()


def test_minting_a_new_key_over_existing_blobs_warns(vault, caplog):
    secure_store.set(NAME, FAKE)
    vault.store.clear()
    secure_store._MASTER = None
    with caplog.at_level("WARNING", logger="secure_store"):
        secure_store._master_key()
    assert any("1 existing" in r.getMessage() and "unreadable" in r.getMessage()
               for r in caplog.records if r.levelname == "WARNING")


def test_first_minting_with_no_blobs_does_not_warn(vault, caplog):
    with caplog.at_level("WARNING", logger="secure_store"):
        secure_store._master_key()
    assert not [r for r in caplog.records if "unreadable" in r.getMessage()]


def test_adopted_key_mismatch_over_existing_blobs_warns(vault, monkeypatch, caplog):
    vault.state["available"] = False
    secure_store.set(NAME, FAKE)
    vault.state["available"] = True
    other = base64.b64encode(b"\x07" * 32).decode()
    monkeypatch.setattr(secure_store, "_vault_set", lambda v: vault.store.__setitem__("key", other))
    secure_store._MASTER = None
    with caplog.at_level("WARNING", logger="secure_store"):
        secure_store._master_key()
    assert any("unreadable" in r.getMessage() for r in caplog.records if r.levelname == "WARNING")


def test_missing_cryptography_is_a_secure_store_error(vault, monkeypatch):
    secure_store.set(NAME, FAKE)
    monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives.ciphers.aead", None)
    with pytest.raises(secure_store.SecureStoreError):
        secure_store.get(NAME)  # must not be swallowed as a corrupt blob
    with pytest.raises(secure_store.SecureStoreError):
        secure_store.set(NAME, FAKE)


def test_key_file_oserror_is_a_secure_store_error(vault, monkeypatch):
    vault.state["available"] = False

    def boom(*a, **k):
        raise PermissionError("read-only home")

    monkeypatch.setattr(secure_store.tempfile, "mkstemp", boom)
    with pytest.raises(secure_store.SecureStoreError):
        secure_store._master_key()
    assert secure_store.protection_level() == "unavailable"


def test_secrets_dir_is_created_0700(vault, monkeypatch):
    calls = []
    real = os.chmod
    monkeypatch.setattr(secure_store.os, "chmod", lambda p, m: calls.append((str(p), m)) or real(p, m))
    secure_store.set(NAME, FAKE)
    assert (str(secure_store._root()), 0o700) in calls


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_secrets_dir_mode_on_posix(vault):
    secure_store.set(NAME, FAKE)
    assert stat.S_IMODE(secure_store._root().stat().st_mode) == 0o700


def test_reset_key_material_clears_cache_and_key_file(vault):
    vault.state["available"] = False
    secure_store.set(NAME, FAKE)
    assert secure_store._MASTER is not None and secure_store._key_file().exists()
    secure_store.reset_key_material()
    assert secure_store._MASTER is None
    assert not secure_store._key_file().exists()


@pytest.mark.parametrize(
    "module,ok",
    [
        ("keyring.backends.macOS", True),
        ("keyring.backends.SecretService", True),
        ("keyring.backends.kwallet", True),
        ("keyring.backends.libsecret", True),
        ("keyrings.alt.file", False),
        ("keyring.backends.fail", False),
    ],
)
def test_backend_allow_list(fake_keyring, module, ok):
    fake_keyring.behavior["backend"] = _backend(module)
    fake_keyring.behavior["value"] = "abc"
    if ok:
        assert secure_store._vault_get() == "abc"
    else:
        with pytest.raises(secure_store._VaultUnavailable):
            secure_store._vault_get()
        with pytest.raises(secure_store._VaultUnavailable):
            secure_store._vault_set("xyz")
        assert fake_keyring.calls == []


def test_chainer_backend_is_judged_by_its_first_backend(fake_keyring):
    chainer = _backend("keyring.backends.chainer")
    fake_keyring.behavior["value"] = "abc"
    chainer.backends = [_backend("keyrings.alt.file"), _backend("keyring.backends.macOS")]
    fake_keyring.behavior["backend"] = chainer
    with pytest.raises(secure_store._VaultUnavailable):
        secure_store._vault_get()
    chainer.backends = [_backend("keyring.backends.SecretService"), _backend("keyrings.alt.file")]
    assert secure_store._vault_get() == "abc"
