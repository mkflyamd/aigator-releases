"""Built-in skill: create and manage user skills in ~/.gator/skills/mine/."""

import re
from datetime import datetime, timezone
from pathlib import Path

import shared
from config import INSTALLED_SKILLS_DIR, AGENTS_SKILLS_DIR
from marketplace.installer import load_installed, save_installed

SKILL_ID = "skill_manager"
ALWAYS_ON = True

_MINE_BASE = INSTALLED_SKILLS_DIR / "mine"
_VALID_SKILL_ID = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$")
_BUILTIN_SKILLS_DIR = Path(__file__).parent.parent  # web/skills/


def _validate_skill_id(skill_id: str) -> str | None:
    if not _VALID_SKILL_ID.match(skill_id):
        return "skill_id must be lowercase letters, digits, and hyphens only"
    _MINE_BASE.mkdir(parents=True, exist_ok=True)
    target = (_MINE_BASE / skill_id).resolve()
    if not str(target).startswith(str(_MINE_BASE.resolve())):
        return "skill_id failed path traversal check"
    return None


def _build_frontmatter(display_name: str, version: str = "1.0") -> str:
    return f"---\nname: {display_name}\ndescription: User skill\nversion: \"{version}\"\n---\n\n"


def _sync_prompts(skill_id: str, skill_md_path: Path, is_new: bool) -> None:
    body = shared._load_skill_prompt(skill_md_path)
    if is_new:
        shared.load_installed_skill_prompts()
    shared.SKILL_PROMPTS[skill_id] = body


def _tool_create_skill(skill_id: str, display_name: str, content: str) -> dict:
    err = _validate_skill_id(skill_id)
    if err:
        return {"error": err}

    skill_dir = _MINE_BASE / skill_id
    if skill_dir.exists():
        return {"error": f"Skill '{skill_id}' already exists. Use update_skill to modify it."}

    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(_build_frontmatter(display_name) + content, encoding="utf-8")

    entries = load_installed()
    entries.append({
        "id": skill_id,
        "version": "1.0",
        "tier": "Mine",
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "has_tools": False,
        "display_name": display_name,
    })
    save_installed(entries)

    _sync_prompts(skill_id, skill_md, is_new=True)
    shared.notify_all({
        "type": "skill_registered",
        "skill_id": skill_id,
        "display_name": display_name,
        "tier": "Mine",
    })
    return {"ok": True, "skill_id": skill_id, "path": str(skill_md)}


def _tool_update_skill(skill_id: str, content: str, display_name: str | None = None) -> dict:
    candidates = [
        _MINE_BASE / skill_id / "SKILL.md",
        INSTALLED_SKILLS_DIR / skill_id / "SKILL.md",
    ]
    skill_md = next((p for p in candidates if p.exists()), None)
    if skill_md is None:
        return {"error": f"Skill '{skill_id}' not found. Use list_skills to see available skills."}

    existing = skill_md.read_text(encoding="utf-8")
    current_name = skill_id
    current_version = "1.0"
    if existing.startswith("---"):
        end = existing.find("---", 3)
        if end != -1:
            for line in existing[3:end].splitlines():
                if line.startswith("name:"):
                    current_name = line.split(":", 1)[1].strip()
                elif line.startswith("version:"):
                    current_version = line.split(":", 1)[1].strip().strip('"')

    new_name = display_name if display_name else current_name
    skill_md.write_text(_build_frontmatter(new_name, current_version) + content, encoding="utf-8")
    _sync_prompts(skill_id, skill_md, is_new=False)

    if display_name and display_name != current_name:
        entries = load_installed()
        for entry in entries:
            if entry.get("id") == skill_id:
                entry["display_name"] = display_name
                break
        save_installed(entries)
        shared.notify_all({
            "type": "skill_renamed",
            "skill_id": skill_id,
            "display_name": display_name,
        })

    return {"ok": True, "skill_id": skill_id, "display_name": new_name}


def _tool_get_skill_content(skill_id: str) -> dict:
    candidates = [
        _BUILTIN_SKILLS_DIR / skill_id / "SKILL.md",
        _MINE_BASE / skill_id / "SKILL.md",
        INSTALLED_SKILLS_DIR / skill_id / "SKILL.md",
        AGENTS_SKILLS_DIR / skill_id / "SKILL.md",
    ]
    skill_md = next((p for p in candidates if p.exists()), None)
    if skill_md is None:
        return {"error": f"Skill '{skill_id}' not found."}
    return {"skill_id": skill_id, "content": skill_md.read_text(encoding="utf-8")}


def _tool_list_skills(include_native: bool = True) -> dict:
    skills = []
    if include_native:
        for skill_dir in sorted(_BUILTIN_SKILLS_DIR.iterdir()):
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                skills.append({"id": skill_dir.name, "tier": "Native", "display_name": skill_dir.name})

    for entry in load_installed():
        skills.append({
            "id": entry.get("id"),
            "tier": entry.get("tier", "Unknown"),
            "display_name": entry.get("display_name") or entry.get("id"),
            "version": entry.get("version"),
        })
    return {"skills": skills}


TOOL_DEFS = [
    {
        "name": "create_skill",
        "description": "Create a new user skill at ~/.gator/skills/mine/<skill_id>/SKILL.md and register it immediately.",
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string", "description": "Kebab-case identifier, e.g. git-issue-creator"},
                "display_name": {"type": "string", "description": "Human-readable label shown in the UI"},
                "content": {"type": "string", "description": "Full SKILL.md body (plain markdown — do NOT include frontmatter)"},
            },
            "required": ["skill_id", "display_name", "content"],
        },
    },
    {
        "name": "update_skill",
        "description": "Overwrite the SKILL.md for an existing skill and reload it in-process.",
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string", "description": "Existing skill ID to update"},
                "content": {"type": "string", "description": "New full SKILL.md body (plain markdown — do NOT include frontmatter)"},
                "display_name": {"type": "string", "description": "Optional new human-readable label. If omitted, existing name is preserved."},
            },
            "required": ["skill_id", "content"],
        },
    },
    {
        "name": "get_skill_content",
        "description": "Return the raw SKILL.md content (with frontmatter) for any installed skill.",
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string", "description": "Skill ID to read"},
            },
            "required": ["skill_id"],
        },
    },
    {
        "name": "list_skills",
        "description": "List all installed skills — native built-ins and user-installed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_native": {"type": "boolean", "description": "Include native built-in skills (default: true)"},
            },
        },
    },
]

TOOL_STATUS = {
    "create_skill": "Creating skill...",
    "update_skill": "Updating skill...",
    "get_skill_content": "Reading skill...",
    "list_skills": "Listing skills...",
}

TOOL_HANDLERS = {
    "create_skill": _tool_create_skill,
    "update_skill": _tool_update_skill,
    "get_skill_content": _tool_get_skill_content,
    "list_skills": _tool_list_skills,
}
