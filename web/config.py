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

# Additional default search root for user-authored agent skills, mirroring the
# ~/.agents/skills convention used by other agent tooling. This directory is only
# *searched* (read) for skills — marketplace/`skill_manager` installs still write
# to INSTALLED_SKILLS_DIR. Drop a skill folder (containing SKILL.md) here and it
# becomes available to the agent on the next skill scan.
AGENTS_SKILLS_DIR = Path.home() / ".agents" / "skills"

# All roots searched for user/installed skills, in precedence order (earlier wins
# on skill_id collisions). Consumers that discover or resolve skills by id should
# iterate this list rather than hard-coding INSTALLED_SKILLS_DIR.
#
# PLUGINS_DIR/cache is included so shared.load_installed_skill_prompts()'s
# recursive rglob("SKILL.md") scan picks up skills bundled inside marketplace
# plugins (e.g. PLUGINS_DIR/cache/claude-plugins-official/amd-skills/1.0.0/
# local-ai-use/SKILL.md) without a separate registration mechanism — see the
# 2026-08-07 plugin-marketplace milestone, decision #3.
USER_SKILL_DIRS = [INSTALLED_SKILLS_DIR, AGENTS_SKILLS_DIR, PLUGINS_DIR / "cache"]

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
    "marketplace_claude_plugins_official_enabled",
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
    # Teams remote control of the OpenCode terminal - off by default, see
    # web/teams_remote_control.py
    "teams_remote_control_enabled",
    # Global kill-switch for agent-completed browser payments - default False,
    # deliberately not surfaced as a Settings UI toggle (see issue #152:
    # product decision is "not ready to let this app move money"). Enforced
    # in browser_agent.py's payment guard, independent of task wording or
    # which browser profile (including personal-profile autofill) is active.
    "allow_agent_payments",
    # Slack pane mode: "native" (DEFAULT when in the Electron shell — tiles the
    # real app.slack.com UI) or "classic" (custom API-built UI in third pane).
    # Unset => native in the shell, classic in a plain browser. Set "classic" to
    # force the old UI = instant full revert, no reinstall.
    "slack_pane_mode",
    # Teams pane mode: "native" (DEFAULT in the shell — tiles the real
    # teams.microsoft.com/v2 web client). Teams has no config opt-out wired up:
    # it's native whenever running in the shell, classic only outside it.
    "teams_pane_mode",
    # Outlook pane mode: "native" (DEFAULT when in the Electron shell — tiles the
    # real outlook.office.com / outlook.cloud.microsoft OWA client) or "classic"
    # (custom third-pane email UI on the Graph API in web/routes/email.py).
    # Unset => native in the shell. Set "classic" to force the old UI.
    "outlook_pane_mode",
    # OneDrive pane mode: "native" (DEFAULT in the shell — tiles the real
    # {tenant}-my.sharepoint.com OneDrive for Business web client) or "classic"
    # (custom third-pane file browser on the Graph API in web/routes/onedrive.py).
    # Unset => native in the shell. Set "classic" to force the old UI.
    "onedrive_pane_mode",
    # OneNote pane mode: "native" (DEFAULT in the shell — tiles the real
    # onenote.com / {tenant}-my.sharepoint.com OneNote for the web client) or
    # "classic" (custom third-pane notebook browser on the Graph API in
    # web/routes/onenote.py). Unset => native in the shell. Set "classic" to
    # force the old UI.
    "onenote_pane_mode",
    # Confluence pane mode: "native" (DEFAULT in the shell — tiles the real
    # atlassian.net/wiki Confluence web client) or "classic" (custom third-pane
    # page browser on the Atlassian REST API in web/routes/confluence.py).
    # Unset => native in the shell. Set "classic" to force the old UI.
    "confluence_pane_mode",
    # Jira pane mode: "native" (DEFAULT in the shell — tiles the real
    # atlassian.net/jira Jira web client) or "classic" (custom third-pane issue
    # browser on the Atlassian REST API in web/routes/jira.py).
    # Unset => native in the shell. Set "classic" to force the old UI.
    "jira_pane_mode",
    # GitHub pane mode: "native" (DEFAULT in the shell — tiles the real
    # github.com / github.enterprise.com web client) or "classic" (custom
    # third-pane PR/issue browser on the GitHub REST API in web/routes/github.py).
    # Unset => native in the shell. Set "classic" to force the old UI.
    "github_pane_mode",
    # Desktop + browser notifications and their sounds - both OFF by default.
    # When notifications_enabled is False the server-side
    # send_desktop_notification() call is skipped and the front-end
    # _showNotification() returns early. When notification_sounds_enabled is
    # False (the default), browser Notifications are created with silent:true.
    "notifications_enabled",
    "notification_sounds_enabled",
    # Coding-agent terminal theme: "dark" (default), "light", "auto" (follows
    # the Gator UI theme). TUI apps like Crush use dark-oriented color schemes,
    # so dark is the safe default. Users can toggle from the Code tab topbar.
    "terminal_theme",
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


def sync_active_llm_profile(cfg: dict) -> None:
    """Resolve the active LLM profile from *cfg* and load it into the runtime
    registry. Shared by startup (web/app.py) and the /api/config/reload-llm
    endpoint so a hand-edited config.json can be picked up without a restart.

    Also syncs env vars from the active profile so legacy code paths that read
    os.environ (api_key_status endpoint, browser_worker, browser_agent) work
    after the legacy top-level api_key/gateway_user_id keys were migrated into
    llm_profiles[]. Without this, those paths see empty env vars and falsely
    report "not configured" or build broken browser-use clients.

    Cleans up temporary profiles (temporary=True) on every call — these are
    test configs that should not survive a server restart. Production profiles
    are never removed.
    """
    import os
    from llm.registry import load_profile, set_active_model

    profiles = cfg.get("llm_profiles", [])

    # Auto-remove temporary profiles — they're test configs that leaked into
    # config.json during a session and should not persist across restarts.
    # Only removes profiles flagged temporary=True AND not the active profile.
    _active_id = cfg.get("llm_active_profile", "")
    _cleaned = [p for p in profiles if not (p.get("temporary") and p.get("id") != _active_id)]
    if len(_cleaned) != len(profiles):
        cfg["llm_profiles"] = _cleaned
        profiles = _cleaned
        # Persist the cleanup so it survives across reloads
        try:
            from config import save_config as _save
            _save(cfg)
        except Exception:
            pass  # best-effort — don't block startup if write fails

    active_profile_id = cfg.get("llm_active_profile", "")
    active_profile = next((p for p in profiles if p.get("id") == active_profile_id), None)
    if active_profile is None and profiles:
        active_profile = profiles[0]
    if not active_profile:
        return
    load_profile(active_profile)

    # Sync env vars from the active profile (post-migration: the legacy
    # top-level keys are gone, so app.py's startup env-var block skips them).
    if active_profile.get("api_key"):
        os.environ["ANTHROPIC_API_KEY"] = active_profile["api_key"]
    if active_profile.get("user_id"):
        os.environ["GATEWAY_USER_ID"] = active_profile["user_id"]
    if active_profile.get("base_url"):
        os.environ["LLM_GATEWAY_URL"] = active_profile["base_url"]
    if active_profile.get("api_key_header"):
        os.environ["GATEWAY_KEY_HEADER"] = active_profile["api_key_header"]
        os.environ["GATEWAY_USER_FIELD"] = "user"

    # Sync model selection: only apply legacy cfg["model"] if it belongs to the active profile
    cfg_model = cfg.get("model", "")
    if cfg_model and cfg_model in (active_profile.get("models") or []):
        try:
            set_active_model(cfg_model)
        except ValueError:
            pass


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
