"""Review and install a shared skill. Nothing is trusted except the digest the user approved."""

from pathlib import Path

from marketplace import installer
from marketplace.github_fetcher import MAX_TOTAL_BYTES
from marketplace import state as skill_state
from marketplace.permissions import declared_permissions, files_digest, summarize_package

from . import bundle
from .errors import ShareError
from .provider import JSON_MAX_BYTES as MAX_JSON_BYTES
from .publisher import checked_doc

MAX_BUNDLE_BYTES = MAX_TOTAL_BYTES + 1024 * 1024  # the extraction cap plus zip overhead
_NATIVE_DIR = Path(__file__).resolve().parent.parent
_COLLISION_TEXT = {
    "mine": "You already have a skill of your own with this name.",
    "installed": "A skill with this name is already installed.",
    "native": "This name is used by a built-in skill.",
}


def _invalid(message: str) -> ShareError:
    return ShareError("invalid", message)


def _check_manifest(manifest, version: int) -> None:
    ok = (
        isinstance(manifest, dict)
        and manifest.get("schema") == bundle.SCHEMA
        and manifest.get("version") == version
        and bundle.valid_share_name(manifest.get("name"))
        and isinstance(manifest.get("bundle_sha256"), str)
        and isinstance(manifest.get("files_digest"), str)
    )
    if not ok:
        raise _invalid("This shared skill's manifest is not valid, so it was not opened.")


def _fetch(provider, ref: dict, version: int | None) -> dict:
    found = provider.read_json(ref, "skill.json", MAX_JSON_BYTES)
    if found is None:
        raise ShareError("not_found", "This shared skill could not be found. It may have been removed.")
    doc = checked_doc(found[0])
    wanted = doc["latest"] if version is None else version
    if isinstance(wanted, bool) or not isinstance(wanted, int) or not 1 <= wanted <= doc["latest"]:
        raise ShareError("not_found", "That version of the shared skill is not available.")

    version_folder = provider.child_folder(ref, f"v{wanted}", create=False)
    manifest_read = provider.read_json(version_folder, "manifest.json", MAX_JSON_BYTES) if version_folder else None
    bundle_read = provider.read_file(version_folder, "bundle.zip", MAX_BUNDLE_BYTES) if version_folder else None
    if manifest_read is None or bundle_read is None:
        raise ShareError("not_found", f"Version {wanted} of this shared skill is incomplete.")
    manifest, zip_bytes = manifest_read[0], bundle_read[0]
    _check_manifest(manifest, wanted)
    listed = next((v for v in doc["versions"] if v.get("version") == wanted), None)
    if listed is None:
        raise ShareError("invalid", "This shared skill's version list is damaged, so it was not opened.")
    if listed.get("files_digest") != manifest["files_digest"]:
        raise ShareError("tampered", "The published version does not match its manifest.")

    if bundle.bundle_sha256(zip_bytes) != manifest["bundle_sha256"]:
        raise ShareError("tampered", "The downloaded skill does not match what the author published.")
    preview = installer.preview_package(local_zip_bytes=zip_bytes)
    if not preview.get("ok"):
        raise _invalid(preview.get("error", "The shared skill could not be read."))
    files = preview["files"]
    if "SKILL.md" not in files:
        raise _invalid("The shared skill has no SKILL.md.")
    digest = files_digest(files)
    if digest != manifest["files_digest"]:
        raise ShareError("tampered", "The skill's files do not match what the author published.")
    return {
        "doc": doc,
        "manifest": manifest,
        "version": wanted,
        "zip_bytes": zip_bytes,
        "files": files,
        "digest": digest,
    }


def _collision(skill_id: str) -> str:
    entry = skill_state.get_entry(skill_id)
    if entry:
        return "mine" if entry.get("tier") == "Mine" else "installed"
    if (_NATIVE_DIR / skill_id).exists():
        return "native"
    return ""


def _author(manifest: dict) -> str:
    return str(manifest.get("author") or "")[:200]


def review(provider, ref: dict, version: int | None = None) -> dict:
    got = _fetch(provider, ref, version)
    manifest, files = got["manifest"], got["files"]
    return {
        "skill_id": manifest["name"],
        "title": str(manifest.get("title") or manifest["name"]),
        "description": str(manifest.get("description") or ""),
        "author": _author(manifest),
        "version": got["version"],
        "latest": got["doc"]["latest"],
        "created_at": str(manifest.get("created_at") or ""),
        "digest": got["digest"],
        "has_scripts": bundle.has_scripts(files),
        "requested_tools": declared_permissions(files).to_dict(),
        "summary": summarize_package(files),
        "collision": _collision(manifest["name"]),
    }


def install(provider, ref: dict, *, version: int, digest: str) -> dict:
    got = _fetch(provider, ref, version)
    if not digest or got["digest"] != digest:
        raise ShareError("content_changed", "The skill changed since you reviewed it. Review it again before installing.")
    skill_id = got["manifest"]["name"]
    collision = _collision(skill_id)
    if collision:
        raise ShareError("collision", _COLLISION_TEXT[collision])

    result = installer.install_skill_md(
        skill_id, "", str(got["version"]), "Community", "", got["zip_bytes"], expected_digest=digest
    )
    if not result.get("ok"):
        return result
    author = _author(got["manifest"])
    skill_state.update_entry(
        result["skill_id"],
        {
            "share_source": {"drive_id": ref["drive_id"], "folder_id": ref["folder_id"]},
            "shared_version": got["version"],
            "files_digest": digest,
            "shared_by": author,
        },
    )
    return {**result, "version": got["version"], "digest": digest, "shared_by": author}
