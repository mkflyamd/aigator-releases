"""One-time state machine: migrate ~/.config/teamspoc/ → ~/.gator/"""

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_OLD_DIR = Path.home() / ".config" / "teamspoc"
_NEW_DIR = Path.home() / ".gator"


def get_migration_state(old_dir: Path, new_dir: Path) -> str:
    """Return 'completed', 'failed', 'in_progress', or 'pending'."""
    state_file = new_dir / "migration_state.json"
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())["status"]
        except Exception:
            pass
    if not old_dir.exists():
        return "completed"  # nothing to migrate
    return "pending"


def run_migration(
    old_dir: Path = _OLD_DIR,
    new_dir: Path = _NEW_DIR,
) -> dict:
    """Run migration if needed. Returns {"ok": True} or {"ok": False, "error": ...}."""
    state = get_migration_state(old_dir, new_dir)

    if state in ("completed",):
        return {"ok": True, "skipped": True}

    if not old_dir.exists():
        # No old dir → nothing to do; mark completed so we don't check again
        new_dir.mkdir(parents=True, exist_ok=True)
        _write_state(new_dir, "completed")
        return {"ok": True, "skipped": True}

    new_dir.mkdir(parents=True, exist_ok=True)
    _write_state(new_dir, "in_progress")

    try:
        # Backup old dir
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        backup_dir = old_dir.parent / f"teamspoc_backup_{timestamp}"
        if not backup_dir.exists():
            shutil.copytree(old_dir, backup_dir)
            logger.info("Migration: backup created at %s", backup_dir)

        # Copy contents (not the dir itself) to new_dir
        for item in old_dir.iterdir():
            dest = new_dir / item.name
            if item.is_dir():
                if not dest.exists():
                    shutil.copytree(item, dest)
            else:
                if not dest.exists():
                    shutil.copy2(item, dest)

        _write_state(new_dir, "completed")
        logger.info("Migration: completed — data now at %s", new_dir)
        return {"ok": True}

    except Exception as exc:
        _write_state(new_dir, "failed", error=str(exc))
        logger.error("Migration failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def _write_state(new_dir: Path, status: str, error: str = "") -> None:
    state = {
        "status": status,
        f"{status}_at": datetime.now(timezone.utc).isoformat(),
    }
    if error:
        state["error"] = error
    (new_dir / "migration_state.json").write_text(json.dumps(state, indent=2))
