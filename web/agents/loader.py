"""Load agent markdown files, enforcing an allow-list on marketplace agent frontmatter."""

import logging
import re
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Allow-list per spec section 6: only these frontmatter fields survive on
# marketplace-sourced agents. Anything else — hooks, mcpServers, permissionMode,
# command, env, lifecycle, alternate-case bypasses like `Hooks`/`HOOKS`, or
# any future Claude Code field that carries execution semantics — is dropped.
# Note: the body (markdown after the frontmatter) is NOT sanitized here.
# Callers must escape/sanitize before rendering to a browser.
_ALLOWED_MARKETPLACE_FIELDS = frozenset(
    {"name", "description", "model", "tools", "context_window", "max_tokens"}
)


def load_agent_file(path: Path, is_marketplace: bool) -> dict:
    """Parse a markdown+YAML agent file.

    Returns:
        {"name": str, "model": str, "frontmatter": dict, "body": str, "source_path": str}
    For marketplace agents, frontmatter is filtered down to the allow-list above.
    """
    content = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(content)

    if is_marketplace:
        frontmatter = {k: v for k, v in frontmatter.items() if k in _ALLOWED_MARKETPLACE_FIELDS}

    return {
        "name": frontmatter.get("name", path.stem),
        "model": frontmatter.get("model", ""),
        "frontmatter": frontmatter,
        "body": body.strip(),
        "source_path": str(path),
    }


def scan_agents_dir(agents_dir: Path, is_marketplace: bool) -> list[dict]:
    """Return all agent dicts from .md files in agents_dir. Returns [] if dir missing.

    Symlinks are skipped for marketplace agents to prevent a malicious plugin
    from pointing agents/escape.md at a file outside its install directory.
    """
    if not agents_dir.is_dir():
        return []
    agents = []
    for md_file in sorted(agents_dir.glob("*.md")):
        if is_marketplace and md_file.is_symlink():
            logger.warning("Skipping symlinked marketplace agent: %s", md_file)
            continue
        try:
            agent = load_agent_file(md_file, is_marketplace=is_marketplace)
            agents.append(agent)
        except Exception as exc:
            logger.warning("Failed to load agent %s: %s", md_file, exc)
    return agents


def _split_frontmatter(content: str) -> tuple[dict, str]:
    """Split markdown content into (frontmatter_dict, body_string)."""
    match = re.match(r"^---\n(.*?)\n---\n?(.*)", content, re.DOTALL)
    if not match:
        return {}, content
    try:
        fm = yaml.safe_load(match.group(1)) or {}
    except Exception:
        fm = {}
    if not isinstance(fm, dict):
        fm = {}
    return fm, match.group(2)
