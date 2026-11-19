"""Where a skill is saved: the default folder, recently used folders, and what is already in a chosen one."""

import json
import os

from marketplace import installer
from marketplace import state as skill_state

from .errors import ShareError
from .provider import ROOT_FOLDER_NAME

RECENT_MAX = 5


def _store():
    return installer.INSTALLED_SKILLS_DIR / "share-locations.json"


def _same(a: dict, b: dict) -> bool:
    return a["drive_id"] == b["drive_id"] and a["folder_id"] == b["folder_id"]


def load_recent() -> list[dict]:
    try:
        items = json.loads(_store().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    keys = ("drive_id", "folder_id", "name", "path", "web_url")
    return [{k: i[k] for k in keys} for i in items if isinstance(i, dict) and all(k in i for k in keys)]


def remember(location: dict) -> None:
    items = [location, *(i for i in load_recent() if not _same(i, location))][:RECENT_MAX]
    installer.INSTALLED_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _store().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, indent=2), encoding="utf-8")
    os.replace(tmp, _store())


def default_location(provider) -> dict:
    """The personal "AI Gator Skills" folder. folder_id is empty until the first publish creates it."""
    root = provider.default_root(create=False)
    if root:
        return provider.describe_folder(root["drive_id"], root["folder_id"])
    return {
        "drive_id": provider.my_drive_id(),
        "folder_id": "",
        "name": ROOT_FOLDER_NAME,
        "path": ["OneDrive", ROOT_FOLDER_NAME],
        "web_url": "",
    }


def existing_skill(provider, root: dict, skill_id: str, author: str) -> dict | None:
    """The skill.json already at <root>/<skill_id>, as {title, version, author, yours}."""
    folder = provider.child_folder(root, skill_id, create=False)
    found = provider.read_json(folder, "skill.json") if folder else None
    if not found:
        return None
    doc = found[0]
    doc_author = str(doc.get("author") or "")
    return {
        "title": doc.get("title") or skill_id,
        "version": doc.get("latest"),
        "author": doc_author,
        "yours": bool(author) and doc_author.strip().lower() == author.strip().lower(),
    }


def locations(provider, skill_id: str) -> dict:
    entry = skill_state.get_entry(skill_id) or {}
    fixed = entry.get("share_source") or {}
    current = None
    if fixed.get("drive_id") and fixed.get("folder_id"):
        try:
            current = provider.describe_folder(fixed["drive_id"], fixed["folder_id"])
        except ShareError:
            current = None
    return {"default": default_location(provider), "recent": load_recent(), "current": current}


def check(provider, skill_id: str, drive_id: str, folder_id: str, author: str) -> dict:
    if drive_id and folder_id:
        try:
            location = provider.describe_folder(drive_id, folder_id)
        except ShareError as err:
            if err.code not in ("not_found", "invalid"):
                raise
            reason = "not_found" if err.code == "not_found" else "not_a_folder"
            return {"ok": False, "reason": reason, "can_write": None, "location": None, "audience": None, "existing": None}
        audience = provider.audience(drive_id, folder_id, location["name"])
        can_write = True if drive_id == provider.my_drive_id() else None
    else:
        location = default_location(provider)
        audience = {"kind": "private", "name": "Only you", "approx_count": None}
        can_write = True
    existing = existing_skill(provider, location, skill_id, author) if location["folder_id"] else None
    return {"ok": True, "reason": "", "can_write": can_write, "location": location, "audience": audience, "existing": existing}
