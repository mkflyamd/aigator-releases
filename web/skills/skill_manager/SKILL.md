---
name: Skill Manager
description: Create, update, and inspect user skills stored in ~/.gator/skills/mine/
version: "1.0"
---

# Skill Manager

Use these tools to create and manage user skills (instructions for AI Gator stored in SKILL.md files).

## When to use

- User asks to "create a skill", "make a new skill", "add a skill for X"
- User asks to "update", "edit", or "change" an existing skill
- User asks "what skills do I have?" or "show me skill X"

## Tools

### create_skill

Creates a new user skill at `~/.gator/skills/mine/<skill_id>/SKILL.md` and registers it immediately.

- `skill_id`: kebab-case identifier, e.g. `git-issue-creator`
- `display_name`: human-readable label shown in the UI
- `content`: full SKILL.md body (plain markdown, no frontmatter — frontmatter is generated)

**Always ask the user what the skill should do before calling this.**
Generate a complete SKILL.md body describing the skill's purpose, when to use it, and any instructions for the AI.

### update_skill

Overwrites the SKILL.md for an existing skill and reloads it in-process. Optionally renames the display name.

- `skill_id`: existing skill ID
- `content`: new full SKILL.md body (plain markdown, no frontmatter)
- `display_name` (optional): new human-readable label. If omitted, existing name is preserved.

### get_skill_content

Returns the raw SKILL.md content (with frontmatter) for any installed skill.

- `skill_id`: skill to read

### list_skills

Returns all installed skills — native built-ins (Native tier) and user-installed skills.

## Rules

- Never write code files, only SKILL.md markdown
- Never include frontmatter in `content` — it is generated automatically
- Always confirm with the user before calling `update_skill` (show them the new content first)
