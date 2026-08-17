"""Minimal plugin commands runtime (decision #11, 2026-08-07 milestone).

Registers `commands/*.md` from an installed plugin bundle and expands a
user-typed `/command args` message into the command's template body, with
`$ARGUMENTS` (whole remainder) and positional `$1`/`$2`/... substitution.

This is its OWN registry — deliberately not folded into shared.SKILL_PROMPTS
— because a command is a parameterized prompt-*template*, not a skill
activation (decision #11's rationale: Gator's existing `/plugin:capability`
router in routes/chat.py is skill-activation only). Advanced command
features (allowed-tools enforcement, per-command model override, inline
`!bash`, `@file` references) are explicitly deferred — decision #11a.
"""

import logging
import re
from pathlib import Path

from marketplace.registry import _parse_skill_md_frontmatter

logger = logging.getLogger(__name__)

# plugin-namespaced? No — Claude Code's own convention is a bare command
# name (filename without .md); two plugins bundling a same-named command
# would collide here (last-installed wins). That's an accepted minimal-scope
# gap for this increment (mirrors decision #11a's "long tail, deferred"
# framing) rather than a silent correctness bug — collisions are rare in
# practice (commands are far less numerous than skills) and namespacing
# would mean the user has to type a longer, plugin-qualified command name,
# which cuts against "minimal" runtime UX.
COMMAND_REGISTRY: dict[str, dict] = {}

_COMMAND_RE = re.compile(r"^/([a-zA-Z0-9_-]+)(?:\s+(.*))?$", re.DOTALL)
# Single combined pattern so expand_command can substitute in ONE pass over
# the ORIGINAL body (see expand_command's docstring for why this matters —
# finding #2, 2026-08-07 milestone adversarial review of Increment 2).
_SUBSTITUTION_RE = re.compile(r"\$ARGUMENTS|\$(\d+)")


def _parse_command_md(text: str) -> tuple[dict, str]:
    """Parse a commands/*.md file: optional YAML frontmatter (`---\\n...\\n---`)
    with a `description:` key, then the template body used verbatim as the
    command's expansion source.

    Returns (frontmatter_dict, body). The frontmatter half is delegated to
    marketplace.registry._parse_skill_md_frontmatter (cleanup #6, 2026-08-07
    milestone review) — that function already implements the identical
    key:value-pairs-from-a---block loop; only the body-slicing below is
    genuinely different (SKILL.md's body is discarded by that parser — here
    the body IS the payload, used verbatim as the expansion template).
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("---", 3)
    if end == -1:
        return {}, text
    fm = _parse_skill_md_frontmatter(text)
    body = text[end + 3 :].lstrip("\n")
    return fm, body


def expand_command(body: str, argument_string: str) -> str:
    """Substitute `$ARGUMENTS` (the whole raw argument string) and
    `$1`/`$2`/... (whitespace-split positional args) into a command
    template body. Missing positional args (e.g. `$2` when only one
    argument was typed) are replaced with an empty string, never left as
    the literal `$2`.

    Substitution happens in a SINGLE pass over the ORIGINAL `body` via one
    combined regex (`_SUBSTITUTION_RE`) — never substitute-then-rescan.
    Finding #2 (2026-08-07 milestone adversarial review): the previous
    implementation did `body.replace("$ARGUMENTS", argument_string)` and
    THEN ran the positional regex over the result, which meant a literal
    `$1`/`$150`/etc. typed by the user as part of their own argument text
    (e.g. `/refund $150 for order 42`) got re-scanned and corrupted by the
    positional substitution. Matching `$ARGUMENTS` and `$\\d+` in one regex
    over `body` guarantees replacement text is never re-scanned, since the
    regex only ever sees the template, not its own output.

    Known limitation (deliberate, undocumented-elsewhere so noted here): a
    literal `$<digits>` appearing in the TEMPLATE body itself (not in the
    user's typed argument text) with no corresponding positional argument
    typed is treated as an unmatched positional placeholder and replaced
    with an empty string, per the "missing positional -> empty string" rule
    above — e.g. a command template containing a literal dollar amount like
    `$100` with no args typed becomes `` (not `$100`). This mirrors
    Claude Code's own convention (no escape syntax for literal `$digits` in
    a command template) rather than inventing a new escaping mechanism for
    this minimal runtime (decision #11a's "long tail, deferred" framing).
    """
    args = argument_string.split()

    def _sub(m: re.Match) -> str:
        if m.group(0) == "$ARGUMENTS":
            return argument_string
        idx = int(m.group(1)) - 1
        return args[idx] if 0 <= idx < len(args) else ""

    return _SUBSTITUTION_RE.sub(_sub, body)


def discover_command_files(plugin_dir: Path) -> list[Path]:
    """Find commands/*.md under an installed plugin dir (decision #11),
    recursing to find every `commands/` directory anywhere in the bundle
    (mirrors how _discover_bundled_skill_dirs recurses for SKILL.md) — most
    plugins ship a single top-level `commands/`, but this doesn't assume it.

    Only direct children of each `commands/` dir are used — Claude Code's
    convention nests namespaced commands as `commands/<namespace>/<name>.md`,
    but that's an advanced-command-surface feature this minimal runtime
    doesn't attempt (decision #11a).
    """
    out: list[Path] = []
    for commands_dir in plugin_dir.rglob("commands"):
        if commands_dir.is_dir():
            out.extend(sorted(commands_dir.glob("*.md")))
    return sorted(out)


def register_plugin_commands(plugin_id: str, plugin_dir: Path) -> list[str]:
    """Discover and register commands/*.md for a freshly installed (or
    re-registered, e.g. after a server restart) plugin. Returns the list of
    command names registered so the caller can persist them as the install
    record's `command_ids` field for later cleanup on uninstall.

    Skips (does not register) any command name that collides with an
    existing skill id in shared.SKILL_PROMPTS (finding #4, 2026-08-07
    milestone adversarial review): without this check, a plugin command
    named e.g. "rocm-basics" that happens to match an installed skill's id
    would make try_expand_command() intercept and rewrite ANY message
    matching `/rocm-basics ...` — including ones the model itself emits for
    skill auto-activation (routes/chat.py's `_SKILL_REQUEST_RE`) — into an
    unrelated command template, silently hijacking skill activation. A
    logged warning (not a raised error) keeps a single bad/colliding
    command from failing the whole install.

    `shared` is imported locally (not at module top level) to avoid a
    circular import: shared.py imports from marketplace.installer at module
    load time, and installer.py imports marketplace.commands lazily inside
    function bodies for the same reason — mirrors that existing pattern.
    """
    import shared as _shared

    command_ids: list[str] = []
    for path in discover_command_files(plugin_dir):
        name = path.stem
        if name in _shared.SKILL_PROMPTS:
            logger.warning(
                "Plugin %r command %r collides with an existing skill id — "
                "skipping registration to avoid hijacking skill activation",
                plugin_id,
                name,
            )
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        fm, body = _parse_command_md(text)
        COMMAND_REGISTRY[name] = {
            "body": body,
            "description": fm.get("description", ""),
            "plugin_id": plugin_id,
        }
        command_ids.append(name)
    return command_ids


def deregister_plugin_commands(command_ids: list[str]) -> None:
    """Remove commands previously registered for a plugin. Called from
    uninstall_skill's plugin-bundle branch (marketplace/installer.py) so a
    removed plugin's commands stop being expandable."""
    for name in command_ids or []:
        COMMAND_REGISTRY.pop(name, None)


def load_installed_plugin_commands() -> None:
    """Rebuild COMMAND_REGISTRY from every installed plugin-bundle record on
    disk. COMMAND_REGISTRY is in-memory only (unlike shared.SKILL_PROMPTS,
    which is rebuilt by re-scanning USER_SKILL_DIRS), so a server restart
    needs this to make previously-installed plugins' commands expandable
    again. Mirrors the re-scan pattern of shared.load_installed_skill_prompts().
    """
    from marketplace.installer import load_installed, PLUGINS_DIR

    for entry in load_installed():
        command_ids = entry.get("command_ids")
        source = entry.get("source")
        version = entry.get("version")
        plugin_id = entry.get("id")
        if not command_ids or not source or not version or not plugin_id:
            continue
        plugin_dir = PLUGINS_DIR / "cache" / source / plugin_id / version
        if plugin_dir.exists():
            register_plugin_commands(plugin_id, plugin_dir)


def try_expand_command(message: str) -> str | None:
    """Detect a bare `/command args` message (decision #11) and expand it to
    the registered command's template body with `$ARGUMENTS`/`$1`/`$2`/...
    substituted.

    Returns None (leave message unchanged) when the message doesn't match a
    registered command — including `/plugin:capability` messages, which
    never match `_COMMAND_RE` (no colon allowed in the command-name group)
    and are routed instead by routes.chat.parse_slash_command. This keeps
    the two slash surfaces (skill-activation vs. command-expansion) from
    ever fighting over the same input, per decision #11's "own registry, not
    shoehorned into skills" requirement.
    """
    stripped = (message or "").strip()
    match = _COMMAND_RE.match(stripped)
    if not match:
        return None
    name = match.group(1)
    command = COMMAND_REGISTRY.get(name)
    if command is None:
        return None
    argument_string = (match.group(2) or "").strip()
    return expand_command(command["body"], argument_string)
