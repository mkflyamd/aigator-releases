"""Publish a Mine skill as an immutable version in a OneDrive folder."""

import json
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Sequence

from marketplace import installer
from marketplace import state as skill_state
from marketplace.permissions import files_digest

from . import bundle, destinations, messages
from .errors import ShareError


_publish_locks: dict[str, threading.Lock] = {}
_publish_locks_guard = threading.Lock()


def _publish_lock(skill_id: str) -> threading.Lock:
    """One lock per skill, so two publishes of the same skill in this process never interleave."""
    with _publish_locks_guard:
        return _publish_locks.setdefault(skill_id, threading.Lock())


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


@contextmanager
def _refusal_is_policy(message: str):
    """Once the skill folder exists we can write here, so a refusal after that is policy, not access."""
    try:
        yield
    except ShareError as err:
        if err.code == "forbidden":
            raise ShareError("policy_blocked", message) from err
        raise


_MAX_VERSION_CLAIMS = 5


def _claim_version(
    provider, folder: dict, version: int, skill_id: str, files: dict, zip_bytes: bytes, *, author: str, created_at: str
) -> tuple[int, dict]:
    """Write vN without ever overwriting an existing version folder. Returns (version, manifest).

    A version folder that skill.json does not list yet is either an earlier attempt of ours that stopped
    before skill.json was written, or another publish still in flight. Identical bytes are adopted (a retry);
    anything else is left alone and the next number is tried, so a stale or concurrent writer can never
    replace files another publish is about to commit.
    """
    for _ in range(_MAX_VERSION_CLAIMS):
        manifest = bundle.build_manifest(skill_id, version, files, zip_bytes, author=author, created_at=created_at)
        version_folder = provider.child_folder(folder, f"v{version}")
        try:
            provider.write_file_create(version_folder, "bundle.zip", zip_bytes)
        except ShareError as err:
            if err.code != "conflict":
                raise
            theirs = provider.read_file(version_folder, "bundle.zip")
            if theirs is None or theirs[0] != zip_bytes:
                version += 1
                continue
        try:
            provider.write_file_create(version_folder, "manifest.json", _json_bytes(manifest))
        except ShareError as err:
            if err.code != "conflict":
                raise
            found = provider.read_json(version_folder, "manifest.json")
            if not found or found[0].get("bundle_sha256") != manifest["bundle_sha256"]:
                version += 1
                continue
            manifest = {**manifest, **found[0]}
        return version, manifest
    raise ShareError(
        "conflict",
        "Other versions of this skill are being saved in the shared folder right now, so nothing was "
        "overwritten. Try again in a minute.",
    )


def _fixed_folder(entry: dict, skill_id: str) -> dict | None:
    fixed = entry.get("share_source") or {}
    if fixed.get("folder_id") and fixed.get("drive_id"):
        return {
            "drive_id": fixed["drive_id"],
            "folder_id": fixed["folder_id"],
            "web_url": fixed.get("web_url", ""),
            "name": skill_id,
        }
    return None


def _require_audience_ack(audience: dict, audience_ack: bool) -> None:
    if audience["kind"] != "private" and not audience_ack:
        raise ShareError(
            "audience_unacknowledged",
            f"{audience['name']} can already see this folder. Confirm who it is shared with before saving the skill here.",
        )


def _vet_root(provider, skill_id: str, root: dict | None, audience_ack: bool) -> tuple[dict, dict]:
    """Check the chosen folder (or the default) before anything is written. Returns (location, audience)."""
    if root:
        location = provider.describe_folder(root["drive_id"], root["folder_id"])
    else:
        default = provider.default_root()
        location = provider.describe_folder(default["drive_id"], default["folder_id"])
    audience = provider.audience(location["drive_id"], location["folder_id"], location["name"])
    _require_audience_ack(audience, audience_ack)
    existing = destinations.existing_skill(provider, location, skill_id)
    if existing and not existing["yours"]:
        raise ShareError(
            "not_yours",
            f'A skill named "{skill_id}" by {existing["author"] or "someone else"} is already in that folder.',
        )
    return location, audience


def publish(
    provider,
    skill_id: str,
    *,
    author: str,
    root: dict | None = None,
    people: Sequence[str] = (),
    audience_ack: bool = False,
    inventory_digest: str | None = None,
) -> dict:
    with _publish_lock(skill_id):
        return _publish(
            provider,
            skill_id,
            author=author,
            root=root,
            people=people,
            audience_ack=audience_ack,
            inventory_digest=inventory_digest,
        )


def _publish(
    provider,
    skill_id: str,
    *,
    author: str,
    root: dict | None,
    people: Sequence[str],
    audience_ack: bool,
    inventory_digest: str | None,
) -> dict:
    entry = skill_state.get_entry(skill_id)
    if not entry or entry.get("tier") != "Mine" or entry.get("id") != skill_id:
        raise ShareError("not_mine", "Only skills you created can be shared.")
    if not bundle.valid_share_name(skill_id):
        raise ShareError("invalid", f'The skill name "{skill_id[:80]}" cannot be shared. {bundle.INVALID_NAME_MESSAGE}')
    skill_dir = installer.INSTALLED_SKILLS_DIR / "mine" / skill_id
    if not skill_dir.is_dir():
        raise ShareError("not_found", "The skill's files could not be found.")

    files = bundle.read_skill_dir(skill_dir)
    digest = files_digest(files)
    if inventory_digest is not None and inventory_digest != digest:
        raise ShareError(
            "content_changed",
            "The skill's files changed since you reviewed the list. Review the files again before sharing.",
        )
    my_id = provider.my_user_id()
    if not my_id:
        raise ShareError("forbidden", "Could not confirm who you are in Microsoft 365, so nothing was shared.")
    folder = _fixed_folder(entry, skill_id)
    location = audience = None
    relinked = False
    if folder:
        try:
            saved_path = provider.describe_folder(folder["drive_id"], folder["folder_id"])["path"]
            audience = provider.audience(folder["drive_id"], folder["folder_id"], skill_id)
            _require_audience_ack(audience, audience_ack)
        except ShareError as err:
            if err.code != "not_found":
                raise
            folder, relinked = None, True
            saved_path = [skill_id]
    if not folder:
        location, audience = _vet_root(provider, skill_id, root, audience_ack)
        folder = provider.child_folder(location, skill_id)
        saved_path = [*location["path"], skill_id]

    current = provider.read_json(folder, "skill.json")
    doc, etag = (checked_doc(current[0]), current[1]) if current else (None, "")
    if doc is not None and doc.get("author_id") != my_id:
        raise ShareError(
            "not_yours",
            f'A skill named "{skill_id}" by {doc.get("author") or "someone else"} is already in that folder.',
        )

    if doc is not None and _latest_digest(doc) == digest:
        version, reused = doc["latest"], True
        title = doc.get("title") or skill_id
        description = doc.get("description") or ""
    else:
        version, reused = (doc["latest"] if doc else 0) + 1, False
        created_at = _now()
        zip_bytes = bundle.build_zip(files)
        with _refusal_is_policy("Your organization's policy blocked saving the skill there. Nothing was shared."):
            version, manifest = _claim_version(
                provider, folder, version, skill_id, files, zip_bytes, author=author, created_at=created_at
            )
            created_at = manifest["created_at"]
            new_doc = {
                "schema": bundle.SCHEMA,
                "name": skill_id,
                "title": manifest["title"],
                "description": manifest["description"],
                "author": author,
                "author_id": my_id,
                "latest": version,
                "versions": [
                    *(doc["versions"] if doc else []),
                    {"version": version, "files_digest": digest, "created_at": created_at},
                ],
                "updated_at": created_at,
            }
            title, description = manifest["title"], manifest["description"]
            if doc is None:
                provider.write_json_create(folder, "skill.json", new_doc)
            else:
                provider.write_json_replace(folder, "skill.json", new_doc, etag)

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
    with _refusal_is_policy("The skill was saved, but your organization does not allow sharing it with other people."):
        ungranted = provider.grant_read(folder, list(people))
    if root and location:
        destinations.remember(location)
    link = messages.make_share_link(folder)
    return {
        "skill_id": skill_id,
        "version": version,
        "reused": reused,
        "digest": digest,
        "folder": folder,
        "link": link,
        "web_url": folder["web_url"],
        "message": messages.share_message(title, author, description, link, folder["web_url"]),
        "ungranted": ungranted,
        "saved_path": saved_path,
        "audience": audience,
        "relinked": relinked,
    }


def inventory(skill_id: str) -> dict:
    """The exact files that publishing this Mine skill would upload, and what is left out."""
    entry = skill_state.get_entry(skill_id)
    if not entry or entry.get("tier") != "Mine" or entry.get("id") != skill_id:
        raise ShareError("not_mine", "Only skills you created can be shared.")
    skill_dir = installer.INSTALLED_SKILLS_DIR / "mine" / skill_id
    if not skill_dir.is_dir():
        raise ShareError("not_found", "The skill's files could not be found.")
    return bundle.inventory(skill_dir)
