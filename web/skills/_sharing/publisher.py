"""Publish a Mine skill as an immutable version in a OneDrive folder."""

import json
from datetime import datetime, timezone
from typing import Sequence

from marketplace import installer
from marketplace import state as skill_state
from marketplace.permissions import files_digest

from . import bundle, messages
from .errors import ShareError


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_bytes(doc: dict) -> bytes:
    return json.dumps(doc, indent=2, sort_keys=True).encode("utf-8")


def checked_doc(doc: dict) -> dict:
    versions = doc.get("versions")
    if (
        not isinstance(doc.get("latest"), int)
        or isinstance(doc.get("latest"), bool)
        or not isinstance(versions, list)
        or not all(isinstance(v, dict) for v in versions)
    ):
        raise ShareError("invalid", "The shared skill's skill.json is damaged, so it was not changed.")
    return doc


def _latest_digest(doc: dict) -> str:
    for v in doc["versions"]:
        if v.get("version") == doc["latest"]:
            return v.get("files_digest", "")
    return ""


def _skill_folder(provider, entry: dict, skill_id: str, root: dict | None) -> dict:
    fixed = entry.get("share_source") or {}
    if fixed.get("folder_id") and fixed.get("drive_id"):
        return {
            "drive_id": fixed["drive_id"],
            "folder_id": fixed["folder_id"],
            "web_url": fixed.get("web_url", ""),
            "name": skill_id,
        }
    return provider.child_folder(root or provider.default_root(), skill_id)


def publish(provider, skill_id: str, *, author: str, root: dict | None = None, people: Sequence[str] = ()) -> dict:
    entry = skill_state.get_entry(skill_id)
    if not entry or entry.get("tier") != "Mine" or entry.get("id") != skill_id:
        raise ShareError("not_mine", "Only skills you created can be shared.")
    skill_dir = installer.INSTALLED_SKILLS_DIR / "mine" / skill_id
    if not skill_dir.is_dir():
        raise ShareError("not_found", "The skill's files could not be found.")

    files = bundle.read_skill_dir(skill_dir)
    digest = files_digest(files)
    folder = _skill_folder(provider, entry, skill_id, root)

    current = provider.read_json(folder, "skill.json")
    doc, etag = (checked_doc(current[0]), current[1]) if current else (None, "")

    if doc is not None and _latest_digest(doc) == digest:
        version, reused = doc["latest"], True
    else:
        version, reused = (doc["latest"] if doc else 0) + 1, False
        created_at = _now()
        zip_bytes = bundle.build_zip(files)
        manifest = bundle.build_manifest(skill_id, version, files, zip_bytes, author=author, created_at=created_at)
        version_folder = provider.child_folder(folder, f"v{version}")
        provider.write_file(version_folder, "bundle.zip", zip_bytes)
        provider.write_file(version_folder, "manifest.json", _json_bytes(manifest))
        new_doc = {
            "schema": bundle.SCHEMA,
            "name": skill_id,
            "title": manifest["title"],
            "description": manifest["description"],
            "author": author,
            "latest": version,
            "versions": [
                *(doc["versions"] if doc else []),
                {"version": version, "files_digest": digest, "created_at": created_at},
            ],
            "updated_at": created_at,
        }
        if doc is None:
            provider.write_json_create(folder, "skill.json", new_doc)
        else:
            provider.write_json_replace(folder, "skill.json", new_doc, etag)

    provider.grant_read(folder, list(people))
    skill_state.update_entry(
        skill_id,
        {
            "share_source": {
                "drive_id": folder["drive_id"],
                "folder_id": folder["folder_id"],
                "web_url": folder["web_url"],
            },
            "published_version": version,
            "published_digest": digest,
        },
    )
    return {
        "skill_id": skill_id,
        "version": version,
        "reused": reused,
        "digest": digest,
        "folder": folder,
        "link": messages.make_share_link(folder),
        "web_url": folder["web_url"],
    }
