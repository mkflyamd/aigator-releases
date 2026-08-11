"""Marketplace REST endpoints — browse catalog, install, uninstall, create user skills."""

import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import load_config as _load_config
from marketplace.registry import fetch_catalog, normalize_entry, _parse_skill_md_frontmatter
from marketplace.installer import load_installed, install_skill_md, uninstall_skill, create_user_skill, _slugify
from marketplace.loader import load_skill_tools, unload_skill_tools
from marketplace.commands import COMMAND_REGISTRY
from shared import load_installed_skill_prompts

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
            skills.append(normalize_entry({
                "id": skill_id,
                "name": fm.get("name", skill_id),
                "description": fm.get("description", ""),
                "version": fm.get("version", "1.0"),
                "tier": "Native",
                "source": "native",
                "has_tools": (skill_md_path.parent / "tools.py").exists(),
            }))
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
    consent: bool = False  # decision #7 — required True to install a claude-plugins-official plugin
    # fix #1 (2026-08-07 milestone adversarial review — TOCTOU): the client
    # echoes back the "resolved_ref" a prior no-consent preview call
    # returned, so the real (consent=True) install pins to the exact
    # content that was previewed rather than re-resolving from the entry's
    # (possibly since-changed) plugin_source. Empty string when the client
    # never previewed first (e.g. a legacy/simplified caller) — the
    # installer falls back to today's best-effort resolution in that case.
    pinned_ref: str = ""


class CreateSkillRequest(BaseModel):
    name: str
    description: str
    instructions: str


class PreviewRequest(BaseModel):
    url: str


def _skill_already_installed(skill_id: str) -> bool:
    return any(e.get("id") == skill_id for e in load_installed())


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
        out.append({"name": name, "description": c.get("description", ""), "plugin_id": c.get("plugin_id", "")})
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


def _install_claude_plugins_official(entry: dict, consent: bool, pinned_ref: str = "") -> dict:
    """Server-side consent gate + installable enforcement for
    claude-plugins-official plugins (decisions #7/#8, Increment 2).

    Refuses installation outright for coding_hard (LSP) entries regardless
    of consent (decision #8). Otherwise, without consent==True, fetches (but
    does not install) the plugin to report its declared capabilities so a
    future consent dialog (Increment 4) can render an accurate prompt —
    nothing is written to disk or to installed-skills.json on this path.
    Only when consent==True does the real install proceed, with consented
    threaded through to the install record.

    `pinned_ref` (fix #1, 2026-08-07 milestone adversarial review — TOCTOU):
    when the client echoes back the "resolved_ref" a prior preview call
    returned, it's passed straight through to the installer so the real
    install fetches the exact content the user was shown consenting to,
    rather than independently re-resolving `ref` from the entry (which may
    have changed since the preview call — see
    installer._fetch_plugin_source_tree's docstring). Empty string (the
    default) preserves today's best-effort behavior for callers that never
    captured a preview response.
    """
    from marketplace.installer import (
        install_claude_plugins_official_plugin,
        get_claude_plugins_official_capabilities,
    )

    # Fix #3 (2026-08-07 milestone adversarial review): default False
    # (fail-closed) — a catalog entry missing the `installable` key entirely
    # (stale cache, future schema drift) must NOT be treated as installable.
    # Defaulting True (fail-open) would silently skip decision #8's hard
    # LSP block for any entry that lost/never had this field.
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
                status_code=502, detail=caps.get("error", "Could not fetch plugin capabilities")
            )
        return {
            "ok": False,
            "consent_required": True,
            "plugin_id": caps["plugin_id"],
            "resolved_ref": caps.get("resolved_ref", ""),
            "capabilities": {
                "skill_count": caps["skill_count"],
                "has_mcp": caps["has_mcp"],
                "has_local_code": caps["has_local_code"],
                # Phase E, Increment 3 (decision #7): per-server names +
                # which ones need a secret Increment 4's consent dialog will
                # have to collect — lets that dialog say "needs a Datadog
                # API key" instead of just "runs a local server".
                "mcp_servers": caps.get("mcp_servers", []),
            },
        }

    result = install_claude_plugins_official_plugin(
        entry, consented=True, pinned_ref=pinned_ref or None
    )
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "Install failed"))
    load_installed_skill_prompts()  # refresh SKILL_PROMPTS without restart
    # Decision #12 (2026-08-07 milestone, Increment 4b): enrich command_ids
    # (already on the install record — decisions #11/Increment 2) into full
    # {name, description, plugin_id} objects so the frontend can call
    # window.registerPluginCommand() per command and have a freshly
    # installed plugin's commands show up in the "/" dropdown immediately,
    # without a page reload — mirrors how registerUserSkill already works
    # for skills. Read from COMMAND_REGISTRY (already updated in-process by
    # register_plugin_commands during the install above) rather than
    # re-deriving descriptions from disk.
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


@router.get("/api/marketplace/installed")
async def get_installed():
    # Native skills are always active — prepend them so they appear at top
    native = _load_native_skills()
    user_installed = load_installed()
    return {"skills": native + user_installed}


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
            raise HTTPException(status_code=400, detail=f"Could not fetch SKILL.md: {exc}")
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

    try:
        files = github_fetcher.download_skill_tarball(
            parsed["owner"], parsed["repo"], parsed["branch"], parsed["path"]
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if "SKILL.md" not in files:
        raise HTTPException(status_code=400, detail="No SKILL.md found. Not a valid skill.")

    md_text = files["SKILL.md"].decode("utf-8", errors="replace")
    fm = _parse_skill_md_frontmatter(md_text)
    skill_id = _slugify(fm.get("name") or parsed["path"].rstrip("/").split("/")[-1])
    warnings = ["overwrite"] if _skill_already_installed(skill_id) else []

    # Imported inside the handler so tests can monkeypatch config.INSTALLED_SKILLS_DIR
    # — a top-level import would freeze the value at module load.
    from config import INSTALLED_SKILLS_DIR
    from marketplace.installer import list_existing_skill_files
    existing_files = list_existing_skill_files(INSTALLED_SKILLS_DIR / skill_id)
    orphans = sorted(set(existing_files) - set(files.keys()))

    return {
        "skill_id": skill_id,
        "name": fm.get("name", skill_id),
        "description": fm.get("description", ""),
        "files": [{"path": p, "size": len(b)} for p, b in sorted(files.items())],
        "total_size": sum(len(b) for b in files.values()),
        "warnings": warnings,
        "existing_files": sorted(existing_files),
        "orphans": orphans,
    }


@router.post("/api/marketplace/install")
async def install_skill(req: InstallRequest):
    if not req.skill_id:
        raise HTTPException(status_code=400, detail="skill_id is required")

    # claude-plugins-official entries must route to the plugin-bundle
    # installer (decisions #3/#4), NOT fall through to install_skill_md /
    # _install_github_folder below — those would corrupt-install a plugin
    # bundle (write the raw GitHub HTML as SKILL.md and report ok:true, per
    # the Increment 1 review finding). Looked up server-side by skill_id
    # from the cached catalog rather than trusting a client-supplied
    # "source" field, so installable/coding_class enforcement (decision #8)
    # can't be bypassed by a client lying about the entry's source.
    catalog_entry = _find_catalog_entry(req.skill_id)
    if catalog_entry is not None and catalog_entry.get("source") == "claude-plugins-official":
        return _install_claude_plugins_official(catalog_entry, req.consent, req.pinned_ref)

    if not req.skill_md and not req.install_url:
        raise HTTPException(status_code=400, detail="Either skill_md or install_url is required")

    # Route GitHub tree/blob URLs to the folder installer.
    # Raw SKILL.md URLs and ZIP URLs continue through install_skill_md.
    is_github_folder = bool(req.install_url) and (
        req.install_url.startswith("https://github.com/")
        and ("/tree/" in req.install_url or "/blob/" in req.install_url)
    )
    if is_github_folder:
        # Attribute access (not `from ... import`) so test patches of
        # marketplace.installer._install_github_folder take effect.
        import marketplace.installer as _installer
        result = _installer._install_github_folder(
            req.install_url, req.skill_id, req.version,
            orphan_resolution=req.orphan_resolution,
        )
    else:
        result = install_skill_md(req.skill_id, req.skill_md, req.version, req.tier, req.install_url)

    if not result.get("ok"):
        if result.get("error") == "orphan_resolution_required":
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Orphan files require resolution",
                    "orphans": result.get("orphans", []),
                },
            )
        raise HTTPException(status_code=500, detail=result.get("error", "Install failed"))
    load_installed_skill_prompts()  # refresh SKILL_PROMPTS without restart
    # Hot-load tools.py if present (no-op for SKILL.md-only skills).
    # Force Community tier for URL-imported skills — the loader uses tier
    # for runtime restrictions and URL imports are unverified by definition.
    from config import INSTALLED_SKILLS_DIR
    skill_dir = INSTALLED_SKILLS_DIR / req.skill_id
    effective_tier = "Community" if req.install_url else req.tier
    load_skill_tools(req.skill_id, skill_dir, effective_tier)
    return result


@router.delete("/api/marketplace/uninstall/{skill_id}")
async def uninstall(skill_id: str):
    result = uninstall_skill(skill_id)
    if not result.get("ok"):
        error_msg = result.get("error", "")
        status = 404 if "not found" in error_msg.lower() else 500
        raise HTTPException(status_code=status, detail=error_msg or "Uninstall failed")
    load_installed_skill_prompts()  # remove skill from SKILL_PROMPTS without restart
    unload_skill_tools(skill_id)    # remove tools from TOOL_DISPATCH without restart
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
    return {"ok": True, "skill_id": skill_id, "skill_md": path.read_text(encoding="utf-8")}


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
    result = create_user_skill(req.name.strip(), req.description.strip(), req.instructions.strip())
    if result.get("ok"):
        load_installed_skill_prompts()  # refresh SKILL_PROMPTS without restart
        result["display_name"] = req.name.strip()
    return result
