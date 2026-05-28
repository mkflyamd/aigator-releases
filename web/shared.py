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
from pathlib import Path

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
            pass
    # Also put on legacy queue for backwards compat
    try:
        notification_queue.put_nowait(msg)
    except asyncio.QueueFull:
        pass


def subscribe_notifications() -> asyncio.Queue:
    """Create a per-connection queue and register it for broadcasts."""
    q = asyncio.Queue(maxsize=50)
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


_AIGATOR_SKILL_PATH = _WEB_DIR / "skills" / "aigator" / "SKILL.md"


def get_system_prompt() -> str:
    """Load the system prompt fresh from disk on every call so edits take effect without restart."""
    return _load_skill_prompt(_AIGATOR_SKILL_PATH)


# Keep SYSTEM_PROMPT as a module-level alias for backwards compatibility — callers
# that need the live version should call get_system_prompt() instead.
SYSTEM_PROMPT: str = _load_skill_prompt(_AIGATOR_SKILL_PATH)

SKILL_PROMPTS: dict[str, str] = {}
_skills_root = _WEB_DIR / "skills"
for _skill_dir in _skills_root.iterdir():
    if _skill_dir.name.startswith("_") or _skill_dir.name == "aigator":
        continue
    _skill_md = _skill_dir / "SKILL.md"
    if _skill_dir.is_dir() and _skill_md.exists():
        SKILL_PROMPTS[_skill_dir.name] = _load_skill_prompt(_skill_md)

# IDs of skills built into the app — never removed by load_installed_skill_prompts
_BUILTIN_SKILL_IDS: frozenset[str] = frozenset(SKILL_PROMPTS.keys())

# ── Installed marketplace skill prompts ────────────────────────────────────
from config import INSTALLED_SKILLS_DIR as _INSTALLED_SKILLS_DIR


def load_installed_skill_prompts() -> None:
    """Sync SKILL_PROMPTS with INSTALLED_SKILLS_DIR: add new, remove deleted."""
    if not _INSTALLED_SKILLS_DIR.exists():
        return
    found_ids = set()
    for candidate in _INSTALLED_SKILLS_DIR.rglob("SKILL.md"):
        skill_id = candidate.parent.name
        found_ids.add(skill_id)
        if skill_id not in SKILL_PROMPTS:
            try:
                SKILL_PROMPTS[skill_id] = _load_skill_prompt(candidate)
            except Exception:
                pass
    # Remove skills that were uninstalled (dir deleted but still in dict)
    for skill_id in list(SKILL_PROMPTS.keys()):
        if skill_id not in found_ids and skill_id not in _BUILTIN_SKILL_IDS:
            del SKILL_PROMPTS[skill_id]


load_installed_skill_prompts()

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
