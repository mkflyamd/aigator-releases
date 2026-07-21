"""Code Agent skill — read-only access to the active project's code changes so
Gator chat can act as an on-demand tutor, explaining what changed in plain
English for non-technical users.

This is deliberately read-only: it never edits files or runs the coding agent
(that's the Code workspace / OpenCode). It only *reads* diffs so the chat LLM
can explain them. The tutoring tone/level lives in SKILL.md.

Growth seam (not built yet): a future "teach over time" layer would persist a
per-project learning profile (concepts already explained, the user's level) —
e.g. ~/.gator/projects/<name>/learning.json — and summarize it into the system
prompt so explanations compound into a curriculum. get_code_changes already
returns structured data an explainer could record against; wire that in when
the on-demand tutor has proven useful.
"""
from __future__ import annotations

import subprocess

SKILL_ID = "code_agent"

# Cap each diff section so a large change set can't blow the chat context. The
# tutor explains intent, not every line - a few thousand chars per section is
# plenty, and we flag truncation so the LLM can say "showing the first part".
_MAX_DIFF_CHARS = 6000


def _git(repo: str, args: list[str], timeout: int = 15) -> str:
    """Run a git command in repo and return stdout ('' on any failure)."""
    try:
        r = subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
        return r.stdout or ""
    except Exception:
        return ""


def _truncate(text: str) -> tuple[str, bool]:
    if len(text) <= _MAX_DIFF_CHARS:
        return text, False
    return text[:_MAX_DIFF_CHARS] + "\n… (diff truncated — ask about a specific file for the rest)", True


TOOL_DEFS = [
    {
        "name": "get_code_changes",
        "description": (
            "Read the code changes in the user's ACTIVE coding project so you can explain them in "
            "plain English. Read-only — this never edits files. Use it when the user asks things like "
            "\"what did that change do?\", \"explain the last change\", \"what have you changed\", or "
            "\"walk me through this\". Returns the uncommitted working-tree changes (staged + unstaged), "
            "the list of new/untracked files, and the most recent commit with its diff. Base your "
            "explanation ONLY on what this returns — do not invent changes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["all", "working", "last_commit"],
                    "description": (
                        "Which changes to fetch. 'working' = uncommitted edits only; "
                        "'last_commit' = the most recent commit only; 'all' (default) = both."
                    ),
                },
            },
            "required": [],
        },
    },
]


TOOL_STATUS = {
    "get_code_changes": "📖 Reading the code changes…",
}


def _tool_get_code_changes(scope: str = "all", _context_id: str | None = None) -> dict:
    from skills.code_agent.projects import get_active_project, get_project

    name = get_active_project()
    proj = get_project(name) if name else None
    if not proj:
        return {
            "error": "No active coding project.",
            "_user_message": "There's no project open in the Code workspace yet — pick one first, then I can explain its changes.",
        }
    repo = proj["repo_path"]
    scope = scope if scope in ("all", "working", "last_commit") else "all"

    out: dict = {"project": proj["name"], "repo_path": repo}
    out["branch"] = _git(repo, ["rev-parse", "--abbrev-ref", "HEAD"]).strip() or "?"

    truncated = False

    if scope in ("all", "working"):
        staged, t1 = _truncate(_git(repo, ["diff", "--staged"]))
        unstaged, t2 = _truncate(_git(repo, ["diff"]))
        untracked = [f for f in _git(repo, ["ls-files", "--others", "--exclude-standard"]).splitlines() if f]
        out["staged_diff"] = staged
        out["unstaged_diff"] = unstaged
        out["untracked_files"] = untracked
        out["has_uncommitted"] = bool(staged.strip() or unstaged.strip() or untracked)
        truncated = truncated or t1 or t2

    if scope in ("all", "last_commit"):
        # %x1f = unit separator, safe against messages containing pipes/newlines.
        meta = _git(repo, ["log", "-1", "--format=%H%x1f%s%x1f%an%x1f%ar"]).strip()
        if meta:
            parts = meta.split("\x1f")
            h, msg, author, when = (parts + ["", "", "", ""])[:4]
            # `show HEAD` with empty format = just the patch; works for the
            # very first commit too (unlike diff HEAD~1..HEAD).
            diff, t3 = _truncate(_git(repo, ["show", "HEAD", "--format=", "--patch"]))
            out["last_commit"] = {
                "hash": h[:10], "message": msg, "author": author, "when": when, "diff": diff,
            }
            truncated = truncated or t3

    out["_truncated"] = truncated
    parts_summary = []
    if out.get("has_uncommitted"):
        parts_summary.append("uncommitted edits")
    if out.get("last_commit"):
        parts_summary.append("the last commit")
    out["_user_message"] = (
        f"Read {' and '.join(parts_summary)} in {proj['name']}."
        if parts_summary else f"No changes to show in {proj['name']} yet."
    )
    return out


TOOL_HANDLERS = {
    "get_code_changes": _tool_get_code_changes,
}
