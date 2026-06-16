"""Marketplace REST endpoints — browse catalog, install, uninstall, create user skills."""

import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import load_config as _load_config
from marketplace.registry import fetch_catalog, normalize_entry, _parse_skill_md_frontmatter
from marketplace.installer import load_installed, install_skill_md, uninstall_skill, create_user_skill, _slugify
from marketplace.loader import load_skill_tools, unload_skill_tools
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


class CreateSkillRequest(BaseModel):
    name: str
    description: str
    instructions: str


class PreviewRequest(BaseModel):
    url: str


def _skill_already_installed(skill_id: str) -> bool:
    return any(e.get("id") == skill_id for e in load_installed())


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
