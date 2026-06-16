"""Config file helpers — extracted from app.py for reuse without circular imports."""

import json
import logging
import shutil
import uuid
from pathlib import Path

_log = logging.getLogger(__name__)

# New canonical path — everything uses GATOR_DIR going forward
GATOR_DIR = Path.home() / ".gator"
PLUGINS_DIR = GATOR_DIR / "plugins"
CATALOG_CACHE = GATOR_DIR / "catalog_cache.json"

# Aliases kept for backward compatibility during migration window
# After migration completes on user's machine, these resolve to the same paths as above
CONFIG_FILE = GATOR_DIR / "config.json"
INSTALLED_SKILLS_DIR = GATOR_DIR / "skills"
OUTPUTS_DIR = GATOR_DIR / "outputs"
# App-owned scratch/working dir for shell commands that don't target a specific
# project. Keeps transient build artifacts (node_modules, generators) out of the
# user's home/repo. Stable (not per-call) so multi-step builds — npm install then
# node build.js — share one folder and relative paths resolve across calls.
WORK_DIR = GATOR_DIR / "work"

# Legacy location where the SQLite DBs used to live (Windows-only path).
# DBs now live in GATOR_DIR alongside the rest of the user state.
_LEGACY_DB_DIR = Path.home() / "AppData" / "Roaming" / "AIGator"


def _relocated_db(filename: str) -> Path:
    """Return the GATOR_DIR path for *filename*, moving any legacy copy once.

    The two SQLite DBs (tasks.db, scheduler.db) used to live under
    ``~/AppData/Roaming/AIGator``. On first run after the move, carry an
    existing DB (plus its -wal/-shm sidecars) over to ``~/.gator`` so users
    keep their queued tasks and scheduled jobs. Idempotent and cross-platform.
    """
    new = GATOR_DIR / filename
    old = _LEGACY_DB_DIR / filename
    if old.exists() and not new.exists():
        try:
            GATOR_DIR.mkdir(parents=True, exist_ok=True)
            # Move the main DB first so its arrival at `new` is the success marker.
            for suffix in ("", "-wal", "-shm"):
                src = old.with_name(old.name + suffix)
                if src.exists():
                    shutil.move(str(src), str(new.with_name(new.name + suffix)))
            _log.info("Relocated %s from %s to %s", filename, _LEGACY_DB_DIR, GATOR_DIR)
        except OSError as exc:
            # Old DB locked (app still running) or move blocked — don't crash
            # startup. Fall back to wherever the main DB currently is and retry
            # next launch (only if it didn't already land at `new`).
            _log.warning("Could not relocate %s: %s", filename, exc)
    # Prefer the new path; only fall back to the legacy one if the DB is still
    # sitting there (move was skipped or failed). Fresh users always get `new`.
    return old if (old.exists() and not new.exists()) else new


TASKS_DB = _relocated_db("tasks.db")
SCHEDULER_DB = _relocated_db("scheduler.db")

PATCHABLE_CONFIG_KEYS = frozenset({
    "token_budget_per_task", "token_budget_daily",
    "cost_input_rate", "cost_output_rate",
    "three_agent_mode",
    "browser_mode",     # fast | balanced | thorough
    "browser_display",  # pane | external
    "browser_timeout",  # seconds (default 300)
    "browser_native",   # true → use installed Chrome/Edge via CDP instead of Playwright Chromium
    "browser_prefer",   # chrome | edge | auto (used when browser_native=true)
    "browser_profile",        # gator | personal (used when browser_native=true)
    "browser_profile_name",   # Chrome profile directory name e.g. "Default", "Profile 1" (personal mode)
    # LLM Gateway
    "llm_gateway_url",
    "llm_gateway_key_header",
    "llm_gateway_user_field",
    # Marketplace
    "marketplace_enabled",
    "marketplace_allowed_tiers",
    "marketplace_clawhub_url",
    "marketplace_verified_url",
    "marketplace_anthropic_enabled",
    "marketplace_enterprise_url",
    # Marketplace Phase 2
    "code_runner_timeout_verified",
    "code_runner_timeout_community",
    "marketplace_verified_manifest_url",
    # OTA updates
    "update_check_interval_days",
    # LLM profiles
    "llm_profiles",
    "llm_active_profile",
    "theme",   # "system" | "light" | "dark"
})


def load_config() -> dict:
    """Load saved config (API key etc.) from disk."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}


def save_config(data: dict) -> None:
    """Write config dict to disk."""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2))


def migrate_llm_config(cfg: dict) -> bool:
    """Migrate legacy api_key/gateway_user_id to llm_profiles format.

    Returns True if a migration was performed (caller should save cfg).
    No-op if llm_profiles already exists or there is nothing to migrate.
    """
    if cfg.get("llm_profiles"):
        return False
    api_key = cfg.get("api_key", "")
    if not api_key:
        return False

    profile_id = str(uuid.uuid4())
    base_url = cfg.get("llm_gateway_url", "") or "https://llm-api.company.com/Unified"
    profile = {
        "id": profile_id,
        "name": "Enterprise Gateway",
        "type": "gateway",
        "base_url": base_url,
        "api_key": api_key,
        "api_key_header": "Ocp-Apim-Subscription-Key",
        "user_id": cfg.get("gateway_user_id", ""),
        "models": [],          # populated on first /v1/models call
        "active_model": cfg.get("model", ""),
    }
    cfg["llm_profiles"] = [profile]
    cfg["llm_active_profile"] = profile_id
    cfg.pop("api_key", None)
    cfg.pop("gateway_user_id", None)
    return True
