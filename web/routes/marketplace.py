"""Marketplace REST endpoints — browse catalog, install, uninstall, create user skills."""

import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import load_config as _load_config
from marketplace.registry import fetch_catalog, normalize_entry, _parse_skill_md_frontmatter
from marketplace.installer import load_installed, install_skill_md, uninstall_skill, create_user_skill
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


class CreateSkillRequest(BaseModel):
    name: str
    description: str
    instructions: str


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


@router.post("/api/marketplace/install")
async def install_skill(req: InstallRequest):
    if not req.skill_id:
        raise HTTPException(status_code=400, detail="skill_id is required")
    if not req.skill_md and not req.install_url:
        raise HTTPException(status_code=400, detail="Either skill_md or install_url is required")
    result = install_skill_md(req.skill_id, req.skill_md, req.version, req.tier, req.install_url)
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "Install failed"))
    load_installed_skill_prompts()  # refresh SKILL_PROMPTS without restart
    # Hot-load tools.py if present (no-op for SKILL.md-only skills)
    from config import INSTALLED_SKILLS_DIR
    skill_dir = INSTALLED_SKILLS_DIR / req.skill_id
    load_skill_tools(req.skill_id, skill_dir, req.tier)
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


@router.post("/api/marketplace/create")
async def create_skill(req: CreateSkillRequest):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    result = create_user_skill(req.name.strip(), req.description.strip(), req.instructions.strip())
    if result.get("ok"):
        load_installed_skill_prompts()  # refresh SKILL_PROMPTS without restart
        result["display_name"] = req.name.strip()
    return result
