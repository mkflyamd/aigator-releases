import json

import pytest

import config
import secure_store

FAKE = "aigator-fake-api-key"


@pytest.fixture
def cfgfile(tmp_path, monkeypatch):
    f = tmp_path / "gator" / "config.json"
    f.parent.mkdir()
    monkeypatch.setattr(config, "CONFIG_FILE", f)
    return f


def test_save_moves_pats_out_of_json(cfgfile):
    config.save_config({"model": "x", "jira_pat": FAKE, "github_token": FAKE})
    on_disk = json.loads(cfgfile.read_text())
    assert on_disk == {"model": "x"}
    loaded = config.load_config()
    assert loaded["jira_pat"] == FAKE and loaded["github_token"] == FAKE
    assert secure_store.get("config/jira_pat") == FAKE


def test_backup_never_contains_pat(cfgfile):
    config.save_config({"jira_pat": FAKE})
    config.save_config({"jira_pat": FAKE, "x": 1})
    for p in cfgfile.parent.iterdir():
        assert FAKE not in p.read_text()


def test_backup_of_legacy_plaintext_file_is_stripped(cfgfile):
    # A save that lands on a file still holding plaintext PATs (no load_config
    # first) must not copy them into the .bak.
    cfgfile.write_text(json.dumps({"model": "old", "github_token": FAKE}))
    config.save_config({"model": "new"})
    bak = cfgfile.parent / "config.json.bak"
    assert json.loads(bak.read_text()) == {"model": "old"}
    assert FAKE not in cfgfile.read_text()


def test_backup_of_unparseable_file_with_pat_is_not_copied(cfgfile):
    cfgfile.write_text('{"github_token": "' + FAKE + '" oops')
    config.save_config({"model": "new"})
    for p in cfgfile.parent.iterdir():
        assert FAKE not in p.read_text(), p.name


def test_absent_key_is_deleted_like_full_replace(cfgfile):
    config.save_config({"jira_pat": FAKE})
    cfg = config.load_config()
    cfg.pop("jira_pat")
    config.save_config(cfg)
    assert "jira_pat" not in config.load_config()
    assert secure_store.get("config/jira_pat") is None


def test_empty_value_is_deleted(cfgfile):
    config.save_config({"confluence_pat": FAKE})
    config.save_config({"confluence_pat": "  "})
    assert secure_store.get("config/confluence_pat") is None
    assert "confluence_pat" not in config.load_config()


def test_update_config_round_trip(cfgfile):
    config.update_config(lambda c: c.update({"confluence_pat": FAKE}))
    assert config.load_config()["confluence_pat"] == FAKE
    assert "confluence_pat" not in json.loads(cfgfile.read_text())


def test_update_config_preserves_other_pats(cfgfile):
    config.save_config({"github_token": FAKE, "jira_pat": FAKE})
    config.update_config(lambda c: c.update({"theme": "dark"}))
    loaded = config.load_config()
    assert loaded["github_token"] == FAKE and loaded["jira_pat"] == FAKE
    assert loaded["theme"] == "dark"


def test_legacy_plaintext_keys_migrate_and_backups_scrubbed(cfgfile):
    cfgfile.write_text(json.dumps({"model": "x", "jira_api_token": FAKE}))
    (cfgfile.parent / "config.json.bak").write_text(json.dumps({"jira_api_token": FAKE}))
    (cfgfile.parent / "config.json.bak2").write_text(json.dumps({"github_token": FAKE}))
    (cfgfile.parent / "config.corrupt.damaged").write_text('{"jira_pat": "' + FAKE + '" oops')
    cfg = config.load_config()
    assert cfg["jira_api_token"] == FAKE and cfg["model"] == "x"
    assert FAKE not in cfgfile.read_text()
    assert secure_store.get("config/jira_api_token") == FAKE
    for p in cfgfile.parent.iterdir():
        assert FAKE not in p.read_text(), p.name
    assert not (cfgfile.parent / "config.corrupt.damaged").exists()


def test_load_without_config_file_still_overlays(cfgfile):
    secure_store.set("config/github_token", FAKE)
    assert config.load_config()["github_token"] == FAKE


def test_migration_failure_keeps_plaintext_and_backups(cfgfile, monkeypatch, caplog):
    cfgfile.write_text(json.dumps({"model": "x", "github_token": FAKE}))
    bak = cfgfile.parent / "config.json.bak"
    bak.write_text(json.dumps({"github_token": FAKE}))

    def boom(name, value):
        raise secure_store.SecureStoreError("unsupported")

    monkeypatch.setattr(secure_store, "set", boom)
    with caplog.at_level("DEBUG"):
        cfg = config.load_config()
    assert cfg["github_token"] == FAKE  # still usable, not lost
    assert json.loads(cfgfile.read_text())["github_token"] == FAKE
    assert json.loads(bak.read_text())["github_token"] == FAKE
    assert FAKE not in caplog.text


def test_migration_verification_mismatch_keeps_plaintext(cfgfile, monkeypatch):
    cfgfile.write_text(json.dumps({"jira_pat": FAKE, "model": "x"}))
    monkeypatch.setattr(secure_store, "set", lambda name, value: None)  # silently drops
    cfg = config.load_config()
    assert cfg["jira_pat"] == FAKE
    assert json.loads(cfgfile.read_text())["jira_pat"] == FAKE


def test_migration_partial_failure_only_strips_verified_keys(cfgfile, monkeypatch):
    cfgfile.write_text(json.dumps({"jira_pat": FAKE, "github_token": FAKE}))
    real_set = secure_store.set

    def flaky(name, value):
        if name == "config/github_token":
            raise OSError("disk")
        real_set(name, value)

    monkeypatch.setattr(secure_store, "set", flaky)
    config.load_config()
    on_disk = json.loads(cfgfile.read_text())
    assert "jira_pat" not in on_disk
    assert on_disk["github_token"] == FAKE
    assert secure_store.get("config/jira_pat") == FAKE


def test_existing_store_value_wins_over_legacy_plaintext(cfgfile):
    secure_store.set("config/github_token", FAKE)
    cfgfile.write_text(json.dumps({"github_token": "aigator-fake-api-key-old"}))
    cfg = config.load_config()
    assert cfg["github_token"] == FAKE
    assert "github_token" not in json.loads(cfgfile.read_text())


def test_save_fails_closed_when_store_unavailable(cfgfile, monkeypatch):
    config.save_config({"model": "old"})

    def boom(name, value):
        raise secure_store.SecureStoreError("unsupported")

    monkeypatch.setattr(secure_store, "set", boom)
    with pytest.raises(secure_store.SecureStoreError):
        config.save_config({"model": "new", "github_token": FAKE})
    assert json.loads(cfgfile.read_text()) == {"model": "old"}
    for p in cfgfile.parent.iterdir():
        assert FAKE not in p.read_text()


def test_load_survives_store_read_error(cfgfile, monkeypatch):
    cfgfile.write_text(json.dumps({"model": "x"}))

    def boom(name):
        raise secure_store.SecureStoreError("unsupported")

    monkeypatch.setattr(secure_store, "get", boom)
    assert config.load_config() == {"model": "x"}


def test_non_dict_json_still_loads_as_empty(cfgfile):
    cfgfile.write_text("[1, 2]")
    assert config.load_config() == {}


def test_sweep_legacy_secrets_scrubs_clean_config_backups(cfgfile):
    # config.json already clean (earlier run died before scrubbing the .bak).
    cfgfile.write_text(json.dumps({"model": "x"}))
    bak = cfgfile.parent / "config.json.bak"
    bak.write_text(json.dumps({"jira_pat": FAKE}))
    config.sweep_legacy_secrets()
    assert FAKE not in bak.read_text()
