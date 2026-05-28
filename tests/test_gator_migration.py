import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web'))

import json
from pathlib import Path


def test_migration_state_pending_when_old_dir_exists(tmp_path, monkeypatch):
    old_dir = tmp_path / ".config" / "teamspoc"
    old_dir.mkdir(parents=True)
    (old_dir / "config.json").write_text('{"api_key": "x"}')
    new_dir = tmp_path / ".gator"

    import migration
    state = migration.get_migration_state(old_dir, new_dir)
    assert state == "pending"


def test_migration_runs_and_copies_files(tmp_path, monkeypatch):
    old_dir = tmp_path / ".config" / "teamspoc"
    old_dir.mkdir(parents=True)
    (old_dir / "config.json").write_text('{"api_key": "x"}')
    new_dir = tmp_path / ".gator"

    import migration
    result = migration.run_migration(old_dir, new_dir)
    assert result["ok"] is True
    assert (new_dir / "config.json").exists()
    assert (new_dir / "migration_state.json").exists()
    state_data = json.loads((new_dir / "migration_state.json").read_text())
    assert state_data["status"] == "completed"


def test_migration_creates_backup(tmp_path):
    old_dir = tmp_path / ".config" / "teamspoc"
    old_dir.mkdir(parents=True)
    (old_dir / "config.json").write_text('{"api_key": "x"}')
    new_dir = tmp_path / ".gator"

    import migration
    migration.run_migration(old_dir, new_dir)
    backups = list((tmp_path / ".config").glob("teamspoc_backup_*"))
    assert len(backups) == 1
    assert (backups[0] / "config.json").exists()


def test_migration_noop_when_already_completed(tmp_path):
    old_dir = tmp_path / ".config" / "teamspoc"
    new_dir = tmp_path / ".gator"
    new_dir.mkdir(parents=True)
    (new_dir / "migration_state.json").write_text(
        '{"status": "completed", "completed_at": "2026-05-25T00:00:00Z"}'
    )

    import migration
    result = migration.run_migration(old_dir, new_dir)
    assert result["ok"] is True
    assert result.get("skipped") is True


def test_migration_noop_when_no_old_dir(tmp_path):
    old_dir = tmp_path / ".config" / "teamspoc"  # does not exist
    new_dir = tmp_path / ".gator"

    import migration
    result = migration.run_migration(old_dir, new_dir)
    assert result["ok"] is True
    assert result.get("skipped") is True


def test_migration_does_not_overwrite_existing_files_in_new_dir(tmp_path):
    """Idempotency guard: if a prior partial migration (or a user edit) left
    a file in ~/.gator/, a subsequent migration must not clobber it."""
    old_dir = tmp_path / ".config" / "teamspoc"
    old_dir.mkdir(parents=True)
    (old_dir / "config.json").write_text('{"from_old": true}')
    (old_dir / "skills").mkdir()
    (old_dir / "skills" / "marker.txt").write_text("from_old")

    new_dir = tmp_path / ".gator"
    new_dir.mkdir(parents=True)
    (new_dir / "config.json").write_text('{"user_edited": true}')

    import migration
    result = migration.run_migration(old_dir, new_dir)
    assert result["ok"] is True
    # user's existing file must be preserved
    assert '"user_edited"' in (new_dir / "config.json").read_text()
    # but new files from old_dir should still be copied
    assert (new_dir / "skills" / "marker.txt").exists()
