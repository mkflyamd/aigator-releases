import json

import config
import secure_store

FAKE = "aigator-fake-api-key"


def test_sweep_migrates_tokens_and_config(tmp_path, monkeypatch):
    f = tmp_path / "gator" / "config.json"
    f.parent.mkdir()
    monkeypatch.setattr(config, "CONFIG_FILE", f)
    f.write_text(json.dumps({"github_token": FAKE}))
    legacy = secure_store._home() / ".config" / "slack-mcp" / "token.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"access_token": FAKE}))

    config.sweep_legacy_secrets()

    assert not legacy.exists()
    assert FAKE not in f.read_text()
    assert secure_store.get_json("slack/token") == {"access_token": FAKE}


def test_sweep_never_raises(monkeypatch):
    monkeypatch.setattr(secure_store, "migrate_all", lambda: 1 / 0)
    config.sweep_legacy_secrets()


def test_sweep_scrubs_backup_copies(tmp_path, monkeypatch):
    f = tmp_path / "gator" / "config.json"
    f.parent.mkdir()
    monkeypatch.setattr(config, "CONFIG_FILE", f)
    f.write_text(json.dumps({"theme": "dark"}))
    bak = f.parent / "config.json.bak"
    bak.write_text(json.dumps({"theme": "dark", "jira_pat": FAKE}))
    damaged = f.parent / "config.json.1.damaged"
    damaged.write_text('{"github_token": "' + FAKE)  # unparseable

    config.sweep_legacy_secrets()

    assert FAKE not in bak.read_text()
    assert json.loads(bak.read_text()) == {"theme": "dark"}
    assert not damaged.exists()


def test_sweep_is_idempotent(tmp_path, monkeypatch):
    f = tmp_path / "gator" / "config.json"
    f.parent.mkdir()
    monkeypatch.setattr(config, "CONFIG_FILE", f)
    f.write_text(json.dumps({"jira_pat": FAKE, "theme": "dark"}))

    config.sweep_legacy_secrets()
    config.sweep_legacy_secrets()

    assert json.loads(f.read_text()) == {"theme": "dark"}
    assert secure_store.get("config/jira_pat") == FAKE


def test_app_calls_sweep_after_migration_and_before_shared_import():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "web" / "app.py").read_text(encoding="utf-8")
    mig = source.index("_mig = _run_migration()")
    sweep = source.index("\nsweep_legacy_secrets()")
    shared = source.index("\nimport shared\n")
    assert mig < sweep < shared
