"""Per-skill flags kept on the installed-skills.json entry: disabled, permissions, approved_at."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from marketplace.permissions import Permissions


def _installer():
    from marketplace import installer

    return installer


def disabled_ids() -> set[str]:
    out: set[str] = set()
    for entry in _installer().load_installed():
        if entry.get("disabled"):
            if entry.get("id"):
                out.add(entry["id"])
            out.update(entry.get("skill_ids") or [])
    return out


def is_disabled(skill_id: str) -> bool:
    return skill_id in disabled_ids()


def get_entry(skill_id: str) -> dict | None:
    """The entry whose id is skill_id, or the bundle entry that lists it in skill_ids."""
    entries = _installer().load_installed()
    for entry in entries:
        if entry.get("id") == skill_id:
            return entry
    for entry in entries:
        if skill_id in (entry.get("skill_ids") or []):
            return entry
    return None


def update_entry(skill_id: str, changes: dict) -> bool:
    inst = _installer()
    with inst._INSTALL_INDEX_LOCK:
        entries = inst.load_installed()
        for entry in entries:
            if entry.get("id") != skill_id:
                continue
            for key, value in changes.items():
                if value is None:
                    entry.pop(key, None)
                else:
                    entry[key] = value
            inst.save_installed(entries)
            return True
    return False


def set_disabled(skill_id: str, disabled: bool) -> bool:
    return update_entry(skill_id, {"disabled": True if disabled else None})


def record_approval(skill_id: str, perms_dict: dict) -> bool:
    return update_entry(skill_id, {
        "permissions": perms_dict,
        "approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "disabled": None,
    })


def approved_permissions(skill_id: str) -> Permissions:
    entry = get_entry(skill_id)
    return Permissions.from_dict(entry.get("permissions")) if entry else Permissions()


def skill_dir_for(entry: dict) -> Path:
    import config

    source, version, skill_id = entry.get("source", ""), entry.get("version", ""), entry.get("id", "")
    installed = config.INSTALLED_SKILLS_DIR / skill_id
    cache = config.PLUGINS_DIR / "cache" / source / skill_id / version
    if source and version:
        if entry.get("skill_ids") is not None:
            return cache  # a plugin bundle always lives in the versioned cache
        # A plain skill: a GitHub-URL install records source "url" + version but lives in
        # INSTALLED_SKILLS_DIR; only an install_plugin() skill lives in the cache.
        if not installed.exists() and cache.exists():
            return cache
    return installed
