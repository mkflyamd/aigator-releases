"""Marketplace REST endpoints — browse catalog, install, uninstall, create user skills."""

import base64
import io
import logging
import zipfile
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import load_config as _load_config
from marketplace import kill_switch
from marketplace import state as skill_state
from marketplace.permissions import summarize_package
from marketplace.registry import (
    fetch_catalog,
    normalize_entry,
    _parse_skill_md_frontmatter,
)
from marketplace.installer import (
    load_installed,
    install_skill_md,
    uninstall_skill,
    create_user_skill,
    _slugify,
)
from marketplace.loader import load_skill_tools, unload_skill_tools
from marketplace.commands import COMMAND_REGISTRY
from shared import load_installed_skill_prompts
from security import verify_csrf

_SKILLS_DIR = Path(__file__).parent.parent / "skills"


def _load_native_skills() -> list[dict]:
    """Return catalog entries for all native skills that have a SKILL.md."""
    skills = []
    if not _SKILLS_DIR.exists():
        return skills
    for skill_md_path in sorted(_SKILLS_DIR.glob("*/SKILL.md")):
        skill_id = skill_md_path.parent.name
        if skill_id.startswith("_"):
            continue
        try:
            fm = _parse_skill_md_frontmatter(skill_md_path.read_text(encoding="utf-8"))
            skills.append(
                normalize_entry(
                    {
                        "id": skill_id,
                        "name": fm.get("name", skill_id),
                        "description": fm.get("description", ""),
                        "version": fm.get("version", "1.0"),
                        "tier": "Native",
                        "source": "native",
                        "has_tools": (skill_md_path.parent / "tools.py").exists(),
                    }
                )
            )
        except Exception:
            pass
    return skills


router = APIRouter()
logger = logging.getLogger(__name__)


class InstallRequest(BaseModel):
    skill_id: str
    skill_md: str = ""
    version: str = "1.0"
    tier: str = "Community"
    install_url: str = ""
    orphan_resolution: str | None = None  # "keep" | "delete" | None
    consent: bool = (
        False  # decision #7 — required True to install a claude-plugins-official plugin
    )
    # fix #1 (2026-08-07 milestone adversarial review — TOCTOU): the client
    # echoes back the "resolved_ref" a prior no-consent preview call
    # returned, so the real (consent=True) install pins to the exact
    # content that was previewed rather than re-resolving from the entry's
    # (possibly since-changed) plugin_source. Empty string when the client
    # never previewed first (e.g. a legacy/simplified caller) — the
    # installer falls back to today's best-effort resolution in that case.
    pinned_ref: str = ""
    # Content digest the client was shown with the consent card; required with consent=True.
    digest: str = ""


class CreateSkillRequest(BaseModel):
    name: str
    description: str
    instructions: str


class PreviewRequest(BaseModel):
    url: str


def _skill_already_installed(skill_id: str) -> bool:
    return any(e.get("id") == skill_id for e in load_installed())


def _require_digest(digest: str) -> None:
    if not digest:
        raise HTTPException(
            status_code=400, detail="digest is required to approve an install"
        )


def _note_tools_error(result: dict, loaded) -> None:
    """The install succeeded but the skill's tools could not be read: say so instead of hiding it."""
    if isinstance(loaded, dict) and not loaded.get("ok"):
        result["tools_error"] = loaded.get("error") or "the skill's tools could not be read"


def _install_failure(result: dict) -> HTTPException:
    error = result.get("error", "Install failed")
    if error == "content_changed":
        return HTTPException(
            status_code=409,
            detail={
                "error": "content_changed",
                "message": "The package changed since you reviewed it. Review it again before installing.",
            },
        )
    if error == "orphan_resolution_required":
        return HTTPException(
            status_code=400,
            detail={
                "error": "Orphan files require resolution",
                "orphans": result.get("orphans", []),
            },
        )
    return HTTPException(status_code=500, detail=error)


def _plain_consent(skill_id: str, summary: dict) -> dict:
    return {
        "ok": False,
        "consent_required": True,
        "skill_id": skill_id,
        "resolved_ref": "",
        "summary": summary,
    }


def _record_grants(result: dict, skill_id: str) -> None:
    """Store what the user approved on the install record. An installer result
    with no permissions records an empty grant, which is the safe default."""
    skill_state.record_approval(skill_id, result.get("permissions") or {})


def _commands_payload(command_ids: list[str]) -> list[dict]:
    """Map a list of command names to {name, description, plugin_id} using
    the in-memory COMMAND_REGISTRY (marketplace/commands.py) — shared by the
    install-response enrichment above and the standalone listing endpoint
    below so the two never drift apart on shape."""
    out = []
    for name in command_ids:
        c = COMMAND_REGISTRY.get(name)
        if c is None:
            continue
        out.append(
            {
                "name": name,
                "description": c.get("description", ""),
                "plugin_id": c.get("plugin_id", ""),
            }
        )
    return out


@router.get("/api/marketplace/commands")
async def list_commands():
    """Decision #12 (2026-08-07 milestone, Increment 4b): expose every
    installed plugin's registered commands (web/marketplace/commands.py's
    COMMAND_REGISTRY) so the "/" compose-bar dropdown can list them as a
    COMMANDS section — without this, an installed plugin's commands are
    usable (Increment 2's runtime already expands them) but undiscoverable."""
    return {"commands": _commands_payload(sorted(COMMAND_REGISTRY.keys()))}


def _find_catalog_entry(skill_id: str) -> dict | None:
    """Look up a catalog entry by id from the server's own cached catalog
    (never from anything the client sent) — this is how the install route
    decides a claude-plugins-official entry must route to the plugin-bundle
    installer (Increment 2, item 1) and how it enforces `installable` /
    `coding_class` (decision #8) without trusting client-supplied
    classification fields, which a client could otherwise spoof to bypass
    the coding-hard block."""
    cfg = _load_config()
    for entry in fetch_catalog(cfg):
        if entry.get("id") == skill_id:
            return entry
    return None


def _install_claude_plugins_official(
    entry: dict, consent: bool, pinned_ref: str = "", digest: str = ""
) -> dict:
    """Server-side consent gate + installable enforcement for
    claude-plugins-official plugins (decisions #7/#8).

    Refuses coding_hard (LSP) entries outright. Without consent it fetches
    (but does not install) the plugin and returns its capabilities and a
    package summary with a content digest. With consent the digest the user
    was shown is required and the installer refuses content that no longer
    matches it. `pinned_ref` pins the real install to the previewed commit.
    """
    from marketplace.installer import (
        install_claude_plugins_official_plugin,
        get_claude_plugins_official_capabilities,
    )

    # Fail closed: a catalog entry missing `installable` is NOT installable.
    if not entry.get("installable", False):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "not_installable",
                "message": (
                    f"{entry.get('name') or entry.get('id')} is a coding-oriented "
                    "(LSP) plugin and can't run in Gator chat. Use the Coding Agent instead."
                ),
                "coding_class": entry.get("coding_class"),
            },
        )

    if not consent:
        caps = get_claude_plugins_official_capabilities(entry)
        if not caps.get("ok"):
            raise HTTPException(
                status_code=502,
                detail=caps.get("error", "Could not fetch plugin capabilities"),
            )
        package = caps.pop("package", None) or {}
        return {
            "ok": False,
            "consent_required": True,
            "plugin_id": caps["plugin_id"],
            "resolved_ref": caps.get("resolved_ref", ""),
            "capabilities": {
                "skill_count": caps["skill_count"],
                "command_count": caps.get("command_count", 0),
                "has_mcp": caps["has_mcp"],
                "has_local_code": caps["has_local_code"],
                "mcp_servers": caps.get("mcp_servers", []),
                "has_compat_risk": caps.get("has_compat_risk", False),
            },
            "summary": summarize_package(package),
        }

    _require_digest(digest)
    result = install_claude_plugins_official_plugin(
        entry,
        consented=True,
        pinned_ref=pinned_ref or None,
        expected_digest=digest,
    )
    if not result.get("ok"):
        raise _install_failure(result)
    _record_grants(result, result.get("plugin_id") or entry.get("id", ""))
    load_installed_skill_prompts()  # refresh SKILL_PROMPTS without restart
    # Enrich command_ids into {name, description, plugin_id} so the "/" menu
    # can register them without a reload.
    result["commands"] = _commands_payload(result.get("command_ids") or [])
    return result


@router.get("/api/marketplace/catalog")
async def get_catalog():
    cfg = _load_config()
    if not cfg.get("marketplace_enabled", True):
        return {"skills": [], "disabled": True}
    remote = fetch_catalog(cfg)
    # Exclude Native from browse — they're always active and not installable
    skills = [s for s in remote if s.get("tier") != "Native"]
    allowed = cfg.get("marketplace_allowed_tiers")
    if allowed:
        allowed_set = set(allowed)
        skills = [s for s in skills if s.get("tier") in allowed_set]
    return {"skills": skills, "count": len(skills)}


def _enrich_plugin_bundle_mcp_state(entries: list[dict]) -> list[dict]:
    """Attach live MCP state to each persisted plugin-bundle entry.

    `mcp_status` is a dict with:
      - `total`   — count of MCP connections registered by this plugin
      - `enabled` — count that are currently enabled/active
      - `pending` — count that need secrets (missing_secrets non-empty)
      - `failed`  — count whose last connect attempt errored
      - `quarantined` — count with at least one quarantined tool

    This is computed at request time (not persisted) so it always reflects the
    live connection state rather than the state captured at install time.
    Fails soft: if list_with_status() raises, entries are returned unchanged.
    """
    plugin_bundles = [
        e for e in entries if isinstance(e.get("skill_ids"), list)
        and e.get("mcp_connection_ids")
    ]
    if not plugin_bundles:
        return entries

    try:
        from mcp.manager import list_with_status
        connections = {c["id"]: c for c in list_with_status()}
    except Exception:
        return entries

    result = []
    for entry in entries:
        if (
            not isinstance(entry.get("skill_ids"), list)
            or not entry.get("mcp_connection_ids")
        ):
            result.append(entry)
            continue
        ids = entry["mcp_connection_ids"]
        total = len(ids)
        enabled_count = 0
        pending_count = 0
        failed_count = 0
        disabled_count = 0
        missing_count = 0
        quarantined_count = 0
        for cid in ids:
            conn = connections.get(cid)
            if conn is None:
                # Connection id in the install record but not found in the live
                # connections list — the record was lost (e.g. manual config.json
                # edit, or a bug in teardown). Distinct from 'pending' (record
                # exists but needs secrets) and 'failed' (record exists, connect
                # errored).
                missing_count += 1
                continue
            if conn.get("missing_secrets"):
                pending_count += 1
            elif conn.get("connect_error"):
                failed_count += 1
            elif not conn.get("enabled", True):
                # Explicitly disabled — has no secrets gap and no connect error,
                # but enabled=False. Could be user-disabled or a state the
                # complete-secrets flow hasn't visited yet.
                disabled_count += 1
            else:
                enabled_count += 1
            q = (conn.get("tool_compatibility") or {}).get("quarantined", 0)
            if q:
                quarantined_count += 1
        enriched = dict(entry)
        enriched["mcp_status"] = {
            "total": total,
            "enabled": enabled_count,
            "pending": pending_count,
            "failed": failed_count,
            "disabled": disabled_count,
            "missing": missing_count,
            "quarantined": quarantined_count,
        }
        result.append(enriched)
    return result


@router.get("/api/marketplace/installed")
async def get_installed():
    # Native skills are always active — prepend them so they appear at top
    native = _load_native_skills()
    user_installed = load_installed()
    enriched = _enrich_plugin_bundle_mcp_state(user_installed)
    return {"skills": native + enriched}


@router.post("/api/marketplace/preview")
async def preview_skill(req: PreviewRequest):
    """Fetch metadata for a URL-imported skill without writing to disk."""
    from marketplace import github_fetcher

    try:
        parsed = github_fetcher.parse_github_url(req.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if parsed["kind"] == "raw_file":
        try:
            md_text = github_fetcher.fetch_raw_bytes(req.url, 256 * 1024).decode(
                "utf-8", errors="replace"
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"Could not fetch SKILL.md: {exc}"
            )
        fm = _parse_skill_md_frontmatter(md_text)
        # Guard against top-level paths where split("/")[-2] would IndexError.
        path_parts = parsed["path"].split("/")
        fallback_name = path_parts[-2] if len(path_parts) >= 2 else path_parts[-1]
        skill_id = _slugify(fm.get("name") or fallback_name)
        warnings = ["overwrite"] if _skill_already_installed(skill_id) else []
        return {
            "skill_id": skill_id,
            "name": fm.get("name", skill_id),
            "description": fm.get("description", ""),
            "files": [{"path": "SKILL.md", "size": len(md_text.encode())}],
            "total_size": len(md_text.encode()),
            "warnings": warnings,
            "existing_files": [],
            "orphans": [],
        }

    # P1 MVP: use get_github_url_capabilities for full capability inspection
    # (skills, commands, MCP, compat risk). This replaces the previous raw
    # tarball download + root-SKILL.md check, and handles bundles (multiple
    # SKILL.md files) that have no root-level SKILL.md.
    from marketplace.installer import get_github_url_capabilities

    caps = get_github_url_capabilities(req.url)
    if not caps.get("ok"):
        raise HTTPException(status_code=400, detail=caps.get("error", "Preview failed"))

    skill_id = caps["skill_id"]
    warnings = ["overwrite"] if _skill_already_installed(skill_id) else []

    from config import INSTALLED_SKILLS_DIR
    from marketplace.installer import list_existing_skill_files

    existing_files = list_existing_skill_files(INSTALLED_SKILLS_DIR / skill_id)

    return {
        "skill_id": skill_id,
        "name": caps["name"],
        "description": caps["description"],
        "files": [],  # not enumerated individually — use files_count
        "files_count": caps["files_count"],
        "total_size": caps["total_size"],
        "warnings": warnings,
        "existing_files": sorted(existing_files),
        "orphans": [],
        # Plugin bundle fields — frontend uses these to decide consent modal
        "is_plugin": caps["is_plugin"],
        "skill_count": caps["skill_count"],
        "command_count": caps["command_count"],
        "has_mcp": caps["has_mcp"],
        "has_local_code": caps["has_local_code"],
        "mcp_servers": caps["mcp_servers"],
        "has_compat_risk": caps["has_compat_risk"],
    }


@router.post("/api/marketplace/install", dependencies=[Depends(verify_csrf)])
async def install_skill(req: InstallRequest):
    if not req.skill_id:
        raise HTTPException(status_code=400, detail="skill_id is required")

    # claude-plugins-official entries route to the plugin-bundle installer,
    # looked up server-side from the cached catalog (never from a client
    # field) so installable/coding_class enforcement cannot be bypassed.
    catalog_entry = _find_catalog_entry(req.skill_id)
    if (
        catalog_entry is not None
        and catalog_entry.get("source") == "claude-plugins-official"
    ):
        return _install_claude_plugins_official(
            catalog_entry, req.consent, req.pinned_ref, req.digest
        )

    if not req.skill_md and not req.install_url:
        raise HTTPException(
            status_code=400, detail="Either skill_md or install_url is required"
        )

    import marketplace.installer as _installer

    is_github_folder = bool(req.install_url) and (
        req.install_url.startswith("https://github.com/")
        and ("/tree/" in req.install_url or "/blob/" in req.install_url)
    )
    if is_github_folder:
        if not req.consent:
            caps = _installer.get_github_url_capabilities(req.install_url)
            if not caps.get("ok"):
                raise HTTPException(
                    status_code=400, detail=caps.get("error", "Preview failed")
                )
            summary = summarize_package(caps.pop("package", None) or {})
            if caps.get("is_plugin"):
                return {
                    "ok": False,
                    "consent_required": True,
                    "plugin_id": caps["skill_id"],
                    "resolved_ref": "",
                    "capabilities": {
                        "skill_count": caps["skill_count"],
                        "command_count": caps["command_count"],
                        "has_mcp": caps["has_mcp"],
                        "has_local_code": caps["has_local_code"],
                        "mcp_servers": caps["mcp_servers"],
                        "has_compat_risk": caps["has_compat_risk"],
                    },
                    "summary": summary,
                }
            return _plain_consent(req.skill_id, summary)
        _require_digest(req.digest)
        result = _installer.install_github_url(
            req.install_url,
            req.skill_id,
            req.version,
            orphan_resolution=req.orphan_resolution,
            expected_digest=req.digest,
        )
    else:
        if not req.consent:
            preview = _installer.preview_package(
                skill_md=req.skill_md, install_url=req.install_url
            )
            if not preview.get("ok"):
                raise HTTPException(
                    status_code=400, detail=preview.get("error", "Preview failed")
                )
            return _plain_consent(req.skill_id, summarize_package(preview["files"]))
        _require_digest(req.digest)
        result = install_skill_md(
            req.skill_id,
            req.skill_md,
            req.version,
            req.tier,
            req.install_url,
            expected_digest=req.digest,
        )

    if not result.get("ok"):
        raise _install_failure(result)
    # Record the approval before tools load: the sandbox grants come from it.
    _record_grants(result, result.get("plugin_id") or result.get("skill_id") or req.skill_id)
    load_installed_skill_prompts()  # refresh SKILL_PROMPTS without restart
    if result.get("plugin_id"):
        result["commands"] = _commands_payload(result.get("command_ids") or [])
    else:
        from config import INSTALLED_SKILLS_DIR

        skill_dir = INSTALLED_SKILLS_DIR / req.skill_id
        effective_tier = "Community" if req.install_url else req.tier
        _note_tools_error(result, load_skill_tools(req.skill_id, skill_dir, effective_tier))
    return result


@router.delete("/api/marketplace/uninstall/{skill_id}")
async def uninstall(skill_id: str):
    result = uninstall_skill(skill_id)
    if not result.get("ok"):
        error_msg = result.get("error", "")
        status = 404 if "not found" in error_msg.lower() else 500
        raise HTTPException(status_code=status, detail=error_msg or "Uninstall failed")
    load_installed_skill_prompts()  # remove skill from SKILL_PROMPTS without restart
    unload_skill_tools(skill_id)  # remove tools from TOOL_DISPATCH without restart
    return result


class UpdateSkillMdRequest(BaseModel):
    skill_md: str


def _resolve_mine_skill_md(skill_id: str) -> Path:
    """Return the SKILL.md path for a Mine skill, refusing path traversal and
    refusing skills that aren't tier=Mine."""
    from config import INSTALLED_SKILLS_DIR

    entry = next((e for e in load_installed() if e.get("id") == skill_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail="skill not found")
    if entry.get("tier") != "Mine":
        raise HTTPException(status_code=403, detail="only Mine skills are editable")
    mine_root = (INSTALLED_SKILLS_DIR / "mine").resolve()
    candidate = (mine_root / skill_id / "SKILL.md").resolve()
    if mine_root not in candidate.parents:
        raise HTTPException(status_code=400, detail="invalid skill id")
    if not candidate.exists():
        raise HTTPException(status_code=404, detail="SKILL.md not found")
    return candidate


@router.get("/api/marketplace/skill-md/{skill_id}")
async def get_skill_md(skill_id: str):
    path = _resolve_mine_skill_md(skill_id)
    return {
        "ok": True,
        "skill_id": skill_id,
        "skill_md": path.read_text(encoding="utf-8"),
    }


@router.put("/api/marketplace/skill-md/{skill_id}")
async def update_skill_md(skill_id: str, req: UpdateSkillMdRequest):
    path = _resolve_mine_skill_md(skill_id)
    if not req.skill_md.strip():
        raise HTTPException(status_code=400, detail="skill_md is empty")
    path.write_text(req.skill_md, encoding="utf-8")
    load_installed_skill_prompts()  # pick up edits without restart
    return {"ok": True, "skill_id": skill_id}


@router.post("/api/marketplace/create")
async def create_skill(req: CreateSkillRequest):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    result = create_user_skill(
        req.name.strip(), req.description.strip(), req.instructions.strip()
    )
    if result.get("ok"):
        load_installed_skill_prompts()  # refresh SKILL_PROMPTS without restart
        result["display_name"] = req.name.strip()
    return result


class LocalInstallFile(BaseModel):
    path: str
    b64: str


class LocalInstallRequest(BaseModel):
    kind: str  # 'zip' | 'folder'
    name: str  # original filename or folder name, for display only
    b64: str = ""  # zip: base64-encoded zip bytes
    files: list[LocalInstallFile] = []  # folder: list of {path, b64} entries
    consent: bool = False
    digest: str = ""


@router.post("/api/marketplace/install-local", dependencies=[Depends(verify_csrf)])
async def install_local(req: LocalInstallRequest):
    """Install a skill from a local ZIP file or folder selected via the
    native file dialog. The Electron main process reads the file(s) and
    sends them as base64 so no filesystem access is needed here.

    ZIP:    extract using the same logic as install_skill_md's ZIP branch.
    Folder: treat the files list as a {relpath: bytes} tree, same shape
            as download_skill_tarball, and run through install_skill_md's
            ZIP branch by re-packing into a ZIP in memory first — that
            reuses all existing zip-slip, size, and path-traversal guards
            without duplicating them.
    """
    from marketplace.github_fetcher import MAX_FILES, MAX_TOTAL_BYTES

    if req.kind == 'zip':
        if not req.b64:
            raise HTTPException(status_code=400, detail="b64 is required for kind=zip")
        try:
            raw = base64.b64decode(req.b64)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid base64 data")
        if raw[:4] != b"PK\x03\x04":
            raise HTTPException(status_code=400, detail="File is not a ZIP archive")
        zip_bytes = raw

    elif req.kind == 'folder':
        if not req.files:
            raise HTTPException(status_code=400, detail="files list is empty")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in req.files:
                try:
                    data = base64.b64decode(f.b64)
                except Exception:
                    raise HTTPException(
                        status_code=400, detail=f"Invalid base64 for {f.path}"
                    )
                zf.writestr(f.path, data)
        zip_bytes = buf.getvalue()

    else:
        raise HTTPException(status_code=400, detail="kind must be 'zip' or 'folder'")

    import marketplace.installer as _installer

    if not req.consent:
        preview = _installer.preview_package(local_zip_bytes=zip_bytes)
        if not preview.get("ok"):
            raise HTTPException(
                status_code=400, detail=preview.get("error", "Preview failed")
            )
        return _plain_consent("", summarize_package(preview["files"]))

    _require_digest(req.digest)
    result = install_skill_md(
        skill_id="",
        skill_md="",
        version="1.0",
        tier="Community",
        install_url="",
        _local_zip_bytes=zip_bytes,
        expected_digest=req.digest,
    )
    if not result.get("ok"):
        if result.get("error") == "content_changed":
            raise _install_failure(result)
        raise HTTPException(status_code=400, detail=result.get("error", "Install failed"))

    _record_grants(result, result["skill_id"])
    load_installed_skill_prompts()
    skill_dir = __import__("config").INSTALLED_SKILLS_DIR / result["skill_id"]
    _note_tools_error(result, load_skill_tools(result["skill_id"], skill_dir, "Community"))
    return result


def _switch(skill_id: str, action, disabled: bool) -> dict:
    result = action(skill_id)
    if not result.get("ok"):
        error = result.get("error", "failed")
        raise HTTPException(status_code=404 if "not found" in error else 500, detail=error)
    return {"ok": True, "skill_id": skill_id, "disabled": disabled}


@router.post("/api/marketplace/disable/{skill_id}", dependencies=[Depends(verify_csrf)])
def disable_installed_skill(skill_id: str):
    return _switch(skill_id, kill_switch.disable, True)


@router.post("/api/marketplace/enable/{skill_id}", dependencies=[Depends(verify_csrf)])
def enable_installed_skill(skill_id: str):
    return _switch(skill_id, kill_switch.enable, False)
