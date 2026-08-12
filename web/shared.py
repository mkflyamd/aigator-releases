"""Mutable shared state — extracted from app.py so route modules can import
without circular dependencies.

Usage from other modules:
    import shared
    shared.cfg["api_key"]          # read/write the live config dict
    shared.TOOLS                   # current tool definitions list
    shared.notification_queue.put  # push a desktop notification
"""

import asyncio
import json
import logging
from pathlib import Path

log = logging.getLogger("notify")

from config import load_config

# ── Persistent config (loaded once at import time) ─────────────────────────
cfg: dict = load_config()

# ── Notification broadcast (supports multiple SSE consumers) ───────────────
notification_queue: asyncio.Queue = asyncio.Queue()  # legacy — still used by put_nowait callers
_notification_subscribers: list[asyncio.Queue] = []  # one queue per SSE connection


def notify_all(msg: dict):
    """Broadcast a notification to ALL connected SSE consumers."""
    for q in _notification_subscribers:
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            log.warning("Notification queue full, dropping event type=%s", msg.get('type', 'unknown'))
    # Also put on legacy queue for backwards compat
    try:
        notification_queue.put_nowait(msg)
    except asyncio.QueueFull:
        log.warning("Legacy notification queue full, dropping event type=%s", msg.get('type', 'unknown'))


def subscribe_notifications() -> asyncio.Queue:
    """Create a per-connection queue and register it for broadcasts."""
    q = asyncio.Queue(maxsize=200)
    _notification_subscribers.append(q)
    return q


def unsubscribe_notifications(q: asyncio.Queue):
    """Remove a subscriber queue when the SSE connection closes."""
    try:
        _notification_subscribers.remove(q)
    except ValueError:
        pass

# ── Skill / tool registries (populated by _load_skill_modules at startup) ──
TOOLS: list[dict] = []
TOOL_DISPATCH: dict = {}
TOOL_STATUS: dict[str, str] = {}
SKILL_TOOLS_MAP: dict[str, set[str]] = {}
SKILL_DEPENDENCIES_MAP: dict[str, list[dict]] = {}  # skill_id -> [{"id": ..., "reason": ...}]
_ALWAYS_ON_TOOLS: set[str] = set()
_ALWAYS_ON_SKILLS: set[str] = set()
FAILED_SKILLS: dict[str, str] = {}
TOOL_TIER_MAP: dict[str, str] = {}              # skill_id -> tier ("Verified", "Community", etc.)
INSTALLED_TOOL_MODULES: dict[str, str] = {}      # skill_id -> sys.modules key for cache eviction
SKILL_BIN_PATHS: dict[str, str] = {}             # skill_id -> bin dir string injected into PATH (for unload cleanup)
TOOL_SEMAPHORES: dict[str, asyncio.Semaphore] = {}  # skill_id -> concurrency lock (one at a time)
COM_BOUND_TOOLS: frozenset[str] = frozenset()
_COM_SKILL_IDS = {"excel", "docx", "ppt"}

# ── Slack safe-message sentinel ────────────────────────────────────────────
_SLACK_SAFE_MSG = (
    "The Slack MCP server is temporarily unreachable (network issue). "
    "No token or sign-in action is needed — this is a server-side connectivity problem. "
    "Try again in a moment."
)

# ── Teams channel search cache ─────────────────────────────────────────────
_CHANNELS_CACHE_TTL = 300  # 5 minutes
_channels_cache: dict = {"data": None, "ts": 0}

# ── Delta sync state (in-memory, single-user) ─────────────────────────────
_delta_state: dict[str, dict] = {}
_DELTA_MAX_ITEMS = 500  # cap stored items to prevent unbounded memory growth

_DELTA_UNSUPPORTED_FILE = Path.home() / ".config" / "gator" / "delta_unsupported.json"


def _load_delta_unsupported() -> set[str]:
    try:
        if _DELTA_UNSUPPORTED_FILE.exists():
            return set(json.loads(_DELTA_UNSUPPORTED_FILE.read_text()))
    except Exception:
        pass
    return set()


def _save_delta_unsupported() -> None:
    try:
        _DELTA_UNSUPPORTED_FILE.parent.mkdir(parents=True, exist_ok=True)
        _DELTA_UNSUPPORTED_FILE.write_text(json.dumps(list(_delta_unsupported)))
    except Exception:
        pass


_delta_unsupported: set[str] = _load_delta_unsupported()

# ── System / skill prompts (loaded from SKILL.md files) ────────────────────

_WEB_DIR = Path(__file__).parent


def _load_skill_prompt(path: Path) -> str:
    """Load a SKILL.md file, strip YAML frontmatter, return the body."""
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            text = text[end + 3 :].lstrip("\n")
    return text


def _parse_skill_description(path: Path) -> str:
    """Extract the `description:` field from SKILL.md YAML frontmatter.

    Handles plain single-line scalars (`description: foo`, optionally quoted)
    and YAML folded/literal block scalars (`description: >-` followed by indented
    continuation lines — the form the marketplace plugin skills use). Returns ""
    if absent. Minimal parser by design — we only need this one field, mirroring
    _parse_skill_requires.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return ""
    end = text.find("---", 3)
    if end == -1:
        return ""
    frontmatter = text[3:end]
    lines = frontmatter.splitlines()
    for i, line in enumerate(lines):
        if not line.strip().lower().startswith("description:"):
            continue
        rest = line.split(":", 1)[1].strip()
        # Folded/literal block scalar (>, >-, |, |-): collect the more-indented
        # continuation lines that follow.
        if rest and rest[0] in "|>":
            key_indent = len(line) - len(line.lstrip())
            collected: list[str] = []
            for nxt in lines[i + 1:]:
                if not nxt.strip():
                    continue
                if (len(nxt) - len(nxt.lstrip())) <= key_indent:
                    break
                collected.append(nxt.strip())
            return " ".join(collected).strip()
        # Plain scalar (possibly quoted)
        return rest.strip().strip("'\"")
    return ""


def _parse_skill_requires(path: Path) -> list[str]:
    """Extract a `requires:` list from SKILL.md YAML frontmatter.

    Accepts either inline list syntax (`requires: [jira, email]`) or block
    syntax (newline + `  - jira`). Returns [] if absent. Intentionally a
    minimal parser — we only care about this one field.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return []
    end = text.find("---", 3)
    if end == -1:
        return []
    frontmatter = text[3:end]
    out: list[str] = []
    lines = frontmatter.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.lower().startswith("requires:"):
            continue
        rest = stripped.split(":", 1)[1].strip()
        if rest.startswith("[") and rest.endswith("]"):
            for item in rest[1:-1].split(","):
                item = item.strip().strip("'\"")
                if item:
                    out.append(item)
            return out
        # Block list form
        for j in range(i + 1, len(lines)):
            nxt = lines[j]
            if not nxt.startswith((" ", "\t", "-")) and nxt.strip():
                break
            m = nxt.strip()
            if m.startswith("-"):
                val = m.lstrip("-").strip().strip("'\"")
                if val:
                    out.append(val)
        return out
    return []


_AIGATOR_SKILL_PATH = _WEB_DIR / "skills" / "aigator" / "SKILL.md"


def get_system_prompt() -> str:
    """Load the system prompt fresh from disk on every call so edits take effect without restart."""
    return _load_skill_prompt(_AIGATOR_SKILL_PATH)


# Keep SYSTEM_PROMPT as a module-level alias for backwards compatibility — callers
# that need the live version should call get_system_prompt() instead.
SYSTEM_PROMPT: str = _load_skill_prompt(_AIGATOR_SKILL_PATH)

SKILL_PROMPTS: dict[str, str] = {}
# Declarative dependencies: skill_id -> list of required skill IDs.
# Populated from `requires:` in SKILL.md frontmatter. Consumed in chat.py
# to auto-activate dependencies before tool filtering, eliminating the need
# for the model to emit `/skillname` tokens mid-stream.
SKILL_REQUIRES: dict[str, list[str]] = {}
# skill_id -> one-line description parsed from SKILL.md frontmatter. Populated
# alongside SKILL_PROMPTS so plugin-cache / installed skills (which are NOT in
# installed-skills.json) can still be offered to the skill classifier and the
# name matcher in routes/chat.py. Without this, marketplace *plugin* skills are
# loaded but invisible to auto-selection (activatable only by explicit mention).
SKILL_DESCRIPTIONS: dict[str, str] = {}
_skills_root = _WEB_DIR / "skills"
for _skill_dir in _skills_root.iterdir():
    if _skill_dir.name.startswith("_") or _skill_dir.name == "aigator":
        continue
    _skill_md = _skill_dir / "SKILL.md"
    if _skill_dir.is_dir() and _skill_md.exists():
        SKILL_PROMPTS[_skill_dir.name] = _load_skill_prompt(_skill_md)
        _reqs = _parse_skill_requires(_skill_md)
        if _reqs:
            SKILL_REQUIRES[_skill_dir.name] = _reqs
        _desc = _parse_skill_description(_skill_md)
        if _desc:
            SKILL_DESCRIPTIONS[_skill_dir.name] = _desc

# IDs of skills built into the app — never removed by load_installed_skill_prompts
_BUILTIN_SKILL_IDS: frozenset[str] = frozenset(SKILL_PROMPTS.keys())

# ── Installed / user skill prompts ─────────────────────────────────────────
from config import USER_SKILL_DIRS as _USER_SKILL_DIRS
from marketplace.installer import skill_id_for_cache_path as _skill_id_for_cache_path


def _resolve_skill_id(root: Path, candidate: Path) -> str:
    """Return the skill id to register a discovered SKILL.md under.

    Every root except PLUGINS_DIR/cache uses the bare parent-folder name —
    unchanged behavior. PLUGINS_DIR/cache holds marketplace plugin bundles at
    cache/{source}/{plugin_id}/{version}/[...]/SKILL.md; those are namespaced
    as "{plugin_id}__{relpath}" (bare {plugin_id} for a single top-level
    SKILL.md) via marketplace.installer.skill_id_for_cache_path, so two
    plugins bundling a same-named skill folder (e.g. "getting-started") don't
    silently collide, and a plugin whose SKILL.md sits at the version root
    doesn't register under the version string (finding #2, 2026-08-07
    milestone adversarial review).

    Root is recognized as the plugin-cache root by directory name ("cache")
    rather than identity-compared against config.PLUGINS_DIR / "cache", so
    this also works when a caller (e.g. a test) points _USER_SKILL_DIRS at a
    tmp_path-based "cache" dir instead of the real one.
    """
    if root.name == "cache":
        computed = _skill_id_for_cache_path(root, candidate)
        if computed is not None:
            return computed
    return candidate.parent.name


def load_installed_skill_prompts() -> None:
    """Sync SKILL_PROMPTS with the user skill roots (INSTALLED_SKILLS_DIR plus
    ~/.agents/skills, see config.USER_SKILL_DIRS): add new, remove deleted.

    Roots are scanned in precedence order — the first root to provide a given
    skill_id wins, so a marketplace install shadows a same-named folder dropped
    in ~/.agents/skills.
    """
    found_ids = set()
    any_root_reachable = False
    for root in _USER_SKILL_DIRS:
        if not root.exists():
            continue
        any_root_reachable = True
        for candidate in root.rglob("SKILL.md"):
            skill_id = _resolve_skill_id(root, candidate)
            if skill_id in found_ids:
                continue  # higher-precedence root already provided this skill
            found_ids.add(skill_id)
            # Always re-read so on-disk edits take effect without a server restart
            # (built-in skills are read once at module load; only installed/user
            # skills are re-scanned here on each call).
            if skill_id in _BUILTIN_SKILL_IDS:
                continue
            try:
                SKILL_PROMPTS[skill_id] = _load_skill_prompt(candidate)
                _reqs = _parse_skill_requires(candidate)
                if _reqs:
                    SKILL_REQUIRES[skill_id] = _reqs
                else:
                    SKILL_REQUIRES.pop(skill_id, None)
                _desc = _parse_skill_description(candidate)
                if _desc:
                    SKILL_DESCRIPTIONS[skill_id] = _desc
                else:
                    SKILL_DESCRIPTIONS.pop(skill_id, None)
            except Exception:
                pass
    # Remove skills that were uninstalled (dir deleted but still in dict).
    # Skip cleanup entirely when no root was reachable (transient outage / first
    # boot) so we don't wipe all skills from an otherwise healthy SKILL_PROMPTS.
    if not any_root_reachable:
        return
    for skill_id in list(SKILL_PROMPTS.keys()):
        if skill_id not in found_ids and skill_id not in _BUILTIN_SKILL_IDS:
            del SKILL_PROMPTS[skill_id]
            SKILL_REQUIRES.pop(skill_id, None)
            SKILL_DESCRIPTIONS.pop(skill_id, None)


load_installed_skill_prompts()

# ── Plugin commands (decision #11, 2026-08-07 milestone) ───────────────────
# COMMAND_REGISTRY (marketplace/commands.py) is in-memory only, so a server
# restart needs an explicit rebuild from installed-skills.json's plugin-bundle
# records — mirrors load_installed_skill_prompts() above, but is its own
# function/registry per decision #11 ("own registry, not shoehorned into
# skills"). Best-effort: a failure here must not block server startup.
try:
    from marketplace.commands import load_installed_plugin_commands as _load_installed_plugin_commands
    _load_installed_plugin_commands()
except Exception:
    log.warning("Failed to load installed plugin commands at startup", exc_info=True)

# ── Prompt caching (Anthropic cache_control, ephemeral, 5-min TTL) ─────────
# Set False if your gateway strips cache_control headers (check [cache] log lines).
PROMPT_CACHING_ENABLED: bool = True

# ── Server-side conversation store (keyed by context_id / tab ID) ──────────
from conversation_store import ConversationStore
conversation_store: ConversationStore = ConversationStore()

# ── Per-tab continuation classifier state ─────────────────────────────────
from task_state import TaskStateStore
task_state_store: TaskStateStore = TaskStateStore()

# ── Per-request chat chunk buffer (tab-switch safe streaming) ─────────────
from chat_task_store import ChatTaskStore
chat_task_store: ChatTaskStore = ChatTaskStore()


def _register_extension_setup_tools():
    """Register wizard scoped tools. Called at import time AND after each
    _load_skill_modules() clear in app.py (which wipes TOOL_DISPATCH)."""
    from extensions import tools as _ext_tools
    _ext_tools.register()


_register_extension_setup_tools()
