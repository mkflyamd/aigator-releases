import os as _os_early
_os_early.environ.setdefault("ANONYMIZED_TELEMETRY", "False")  # must be set before browser_use loads
del _os_early

import asyncio
import importlib
import inspect
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).parent.parent
_web_dir = str(Path(__file__).parent)
if _web_dir not in sys.path:
    sys.path.insert(0, _web_dir)

from config import load_config as _load_config, save_config as _save_config

# Run one-time config migration (~/.config/teamspoc → ~/.gator) BEFORE importing
# shared, which calls load_config() at module import. If migration runs in
# lifespan instead, shared.cfg is frozen as {} by the time the migration copies
# the real config into place and the app boots with empty/missing settings.
from migration import run_migration as _run_migration
_mig = _run_migration()
if not _mig.get("ok"):
    logging.getLogger(__name__).error(
        "Config migration failed: %s — falling back to old path",
        _mig.get("error"),
    )

import shared

# ── Route imports ─────────────────────────────────────────────────────────────
from routes.email import router as email_router
from routes.slack import router as slack_router
from routes.teams import router as teams_router
from routes.jira import router as jira_router
from routes.confluence import router as confluence_router
from routes.onedrive import router as onedrive_router
from routes.onenote import router as onenote_router
from routes.calendar import router as calendar_router
from routes.actions import router as actions_router
from routes.aigator import router as aigator_router
from routes.config_routes import router as config_router
from routes.auth import router as auth_router
from routes.health import router as health_router
from routes.chat import router as chat_router
from routes.tasks import router as tasks_router
from routes.utils import router as utils_router
from routes.scheduler import router as scheduler_router
from routes.conversation_routes import router as conversation_router
from routes.marketplace import router as marketplace_router
from routes.files import router as files_router, cleanup_old_outputs
from routes.updater import router as updater_router
from routes.mcp_routes import router as mcp_router
from routes.terminal import router as terminal_router
import updater as _updater

# ── Apply config to environment ──────────────────────────────────────────────
if shared.cfg.get("api_key"):
    os.environ["ANTHROPIC_API_KEY"] = shared.cfg["api_key"]
if shared.cfg.get("jira_base_url"):
    os.environ["JIRA_BASE_URL"] = shared.cfg["jira_base_url"]
if shared.cfg.get("jira_email"):
    os.environ["JIRA_EMAIL"] = shared.cfg["jira_email"]
if shared.cfg.get("jira_api_token"):
    os.environ["JIRA_API_TOKEN"] = shared.cfg["jira_api_token"]
if shared.cfg.get("jira_pat"):
    os.environ["JIRA_PAT_TOKEN"] = shared.cfg["jira_pat"]
if shared.cfg.get("confluence_email"):
    os.environ["CONFLUENCE_EMAIL"] = shared.cfg["confluence_email"]
if shared.cfg.get("confluence_pat"):
    os.environ["CONFLUENCE_PAT"] = shared.cfg["confluence_pat"]
if shared.cfg.get("confluence_base_url"):
    os.environ["CONFLUENCE_BASE_URL"] = shared.cfg["confluence_base_url"]
if shared.cfg.get("slack_username"):
    os.environ["AIGATOR_SLACK_USER"] = shared.cfg["slack_username"]
if shared.cfg.get("gateway_user_id"):
    os.environ["GATEWAY_USER_ID"] = shared.cfg["gateway_user_id"]
if shared.cfg.get("llm_gateway_url"):
    os.environ["LLM_GATEWAY_URL"] = shared.cfg["llm_gateway_url"]
if shared.cfg.get("llm_gateway_key_header"):
    os.environ["GATEWAY_KEY_HEADER"] = shared.cfg["llm_gateway_key_header"]
if shared.cfg.get("llm_gateway_user_field"):
    os.environ["GATEWAY_USER_FIELD"] = shared.cfg["llm_gateway_user_field"]
if shared.cfg.get("github_token"):
    os.environ.setdefault("GITHUB_TOKEN", shared.cfg["github_token"])
    os.environ.setdefault("GITHUB_BASE_URL", shared.cfg.get("github_base_url", ""))

# ── Ensure web/ is on sys.path so skills.* and llm.* imports resolve ─────────
_web_dir = str(Path(__file__).parent)
if _web_dir not in sys.path:
    sys.path.insert(0, _web_dir)

import browser_agent  # noqa: F401 -- confirms ANONYMIZED_TELEMETRY=False (web/ now on path)

# LLM provider abstraction
from llm import get_provider, get_active_model, set_active_model
from llm.registry import load_profile
from config import migrate_llm_config, save_config

# ── Migrate legacy api_key → llm_profiles if needed ─────────────────────────
if migrate_llm_config(shared.cfg):
    save_config(shared.cfg)

# ── Load active LLM profile ──────────────────────────────────────────────────
_profiles = shared.cfg.get("llm_profiles", [])
_active_profile_id = shared.cfg.get("llm_active_profile", "")
_active_profile = next((p for p in _profiles if p.get("id") == _active_profile_id), None)
if _active_profile is None and _profiles:
    _active_profile = _profiles[0]
if _active_profile:
    load_profile(_active_profile)
    # Sync model selection: only apply legacy cfg["model"] if it belongs to the active profile
    _cfg_model = shared.cfg.get("model", "")
    if _cfg_model and _cfg_model in (_active_profile.get("models") or []):
        try:
            set_active_model(_cfg_model)
        except ValueError:
            pass


# ── Skill Module Loader ──────────────────────────────────────────────────────

def _load_manifest_skill_maps(skill_map: dict) -> None:
    """Legacy: read manifest.json files to create SKILL_TOOLS_MAP entries for
    composite skills (like aigator) that bundle tools from multiple skill modules."""
    skills_root = Path(__file__).parent / "skills"
    if not skills_root.exists():
        return
    for skill_dir in skills_root.iterdir():
        manifest_path = skill_dir / "manifest.json"
        if not skill_dir.is_dir() or not manifest_path.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            tools = manifest.get("tools", [])
            if not tools:
                continue
            tool_set = set(tools)
            for key in filter(None, [manifest.get("id"), manifest.get("chip_alias"), skill_dir.name]):
                skill_map.setdefault(key, set()).update(tool_set)
        except Exception:
            pass


def _load_skill_modules() -> None:
    """Auto-discover web/skills/*/tools.py and build shared.TOOLS, shared.TOOL_DISPATCH, etc."""

    all_defs: list[dict] = []
    all_dispatch: dict = {}
    all_status: dict = {}
    skill_map: dict[str, set[str]] = {}
    com_tools: set[str] = set()
    shared.FAILED_SKILLS.clear()

    skills_pkg = Path(__file__).parent / "skills"
    if skills_pkg.exists():
        for entry in sorted(skills_pkg.iterdir()):
            if not entry.is_dir():
                continue
            # Skip __pycache__ and _m365 (helper, not a skill), but allow _always_on
            if entry.name.startswith("__"):
                continue
            if entry.name.startswith("_") and entry.name != "_always_on":
                continue
            tools_py = entry / "tools.py"
            if not tools_py.exists():
                continue
            try:
                mod = importlib.import_module(f"skills.{entry.name}.tools")
            except Exception as exc:
                logging.exception("Failed to load skill %s", entry.name)
                shared.FAILED_SKILLS[entry.name] = str(exc)
                continue

            defs = getattr(mod, "TOOL_DEFS", [])
            handlers = getattr(mod, "TOOL_HANDLERS", {})
            status = getattr(mod, "TOOL_STATUS", {})
            skill_id = getattr(mod, "SKILL_ID", entry.name)
            aliases = getattr(mod, "SKILL_ALIASES", [])
            is_always_on = getattr(mod, "ALWAYS_ON", False)

            # Validate tool contract at startup
            from skills._skill_utils import validate_tool_contract
            if not validate_tool_contract(mod, entry.name):
                shared.FAILED_SKILLS[entry.name] = "tool contract mismatch (see logs)"

            all_defs.extend(defs)
            all_dispatch.update(handlers)
            all_status.update(status)

            # Auto-discover direct intents for the Skill Router
            direct_intents = getattr(mod, "DIRECT_INTENTS", [])
            if direct_intents:
                from skill_router import register_intents
                register_intents(skill_id, direct_intents)

            tool_names = {d["name"] for d in defs}
            for key in [skill_id] + aliases:
                skill_map.setdefault(key, set()).update(tool_names)
            if is_always_on:
                shared._ALWAYS_ON_TOOLS.update(tool_names)
                shared._ALWAYS_ON_SKILLS.add(skill_id)
            if entry.name in shared._COM_SKILL_IDS:
                com_tools.update(tool_names)

    # Legacy: manifest.json composite skills (aigator bundles excel+ppt)
    _load_manifest_skill_maps(skill_map)

    shared.TOOLS[:] = all_defs
    shared.TOOL_DISPATCH.clear()
    shared.TOOL_DISPATCH.update(all_dispatch)
    shared.TOOL_STATUS.clear()
    shared.TOOL_STATUS.update(all_status)
    shared.SKILL_TOOLS_MAP.clear()
    shared.SKILL_TOOLS_MAP.update(skill_map)
    shared.COM_BOUND_TOOLS = frozenset(com_tools)


# Load skill modules eagerly at import time
_load_skill_modules()

# Load MCP connections from cached config (no network calls at startup)
from mcp.manager import load_all_from_cache as _load_mcp_connections
_load_mcp_connections()


# ── Tool execution (used by lifespan worker and chat route) ──────────────────

async def execute_tool(name: str, inputs: dict) -> dict:
    try:
        fn = shared.TOOL_DISPATCH.get(name)
        if fn is None:
            return {"error": f"Unknown tool: {name}"}
        # Strip any kwargs the function doesn't accept to prevent TypeError retries.
        sig = inspect.signature(fn)
        accepted = set(sig.parameters)
        has_var_keyword = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        if not has_var_keyword:
            unknown = set(inputs) - accepted
            if unknown:
                logging.getLogger(__name__).warning(
                    "execute_tool(%s): dropping unknown kwargs %s", name, unknown
                )
                inputs = {k: v for k, v in inputs.items() if k in accepted}
        if asyncio.iscoroutinefunction(fn):
            result = await fn(**inputs)
        else:
            result = await asyncio.to_thread(fn, **inputs)
        # For Slack tools: scrub ANY error before the AI sees it
        if name.startswith("slack_") and isinstance(result, dict):
            r_text = result.get("result", "")
            if isinstance(r_text, str):
                try:
                    parsed = json.loads(r_text)
                    if isinstance(parsed, dict) and parsed.get("status") == "error":
                        return {"result": shared._SLACK_SAFE_MSG}
                except (json.JSONDecodeError, TypeError):
                    pass
                low = r_text.lower()
                if any(kw in low for kw in ("invalid_auth", "token_expired", "not_authed", "invalid_token")):
                    return {"result": shared._SLACK_SAFE_MSG}
            if "error" in result and "result" not in result:
                return {"result": shared._SLACK_SAFE_MSG}
        return result
    except Exception as e:
        if name.startswith("slack_"):
            return {"result": shared._SLACK_SAFE_MSG}
        return {"error": str(e)}


def _tool_toast(name: str, result: object) -> dict[str, str] | None:
    """Return toast metadata when a tool reports a failure or fallback."""
    if not isinstance(result, dict):
        return None

    def _msg_from_result(default: str) -> str:
        return (
            (isinstance(result.get("error"), str) and result["error"])
            or (isinstance(result.get("note"), str) and result["note"])
            or (isinstance(result.get("message"), str) and result["message"])
            or default
        )

    if result.get("error"):
        return {"level": "error", "message": str(result["error"])}

    for key, default in (
        ("deleted", "Couldn't cancel the calendar event."),
        ("updated", "Couldn't update the calendar event."),
        ("forwarded", "Couldn't add the attendee to the meeting."),
        ("responded", "Couldn't update the RSVP."),
        ("created", "Failed to create the calendar event."),
    ):
        if key in result and not result[key]:
            return {"level": "error", "message": _msg_from_result(default)}

    if result.get("organizer_required"):
        return {"level": "error", "message": _msg_from_result("You must be the organizer to make that change.")}
    if result.get("series_master"):
        return {"level": "error", "message": _msg_from_result("Select a specific occurrence before cancelling this recurring meeting.")}
    if result.get("fallback_forward"):
        return {"level": "warn", "message": _msg_from_result("Invite forwarded as FYI email — attendee was not added as a meeting participant.")}

    missing = result.get("missing")
    if isinstance(missing, list) and missing:
        return {"level": "error", "message": _msg_from_result(f"Unable to update entries: {', '.join(map(str, missing))}.")}

    return None


# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app):
    # Migration runs at module import (above `import shared`) — it must happen
    # before shared.cfg is populated by load_config().
    from task_queue import start_worker, stop_worker, set_notify_callback
    from notifications import send_desktop_notification
    import scheduler as sched

    async def _on_task_done(task_id: str, result_summary: str, status: str,
                            in_tok: int = 0, out_tok: int = 0):
        msg = {"type": "task_done", "task_id": task_id, "status": status, "summary": result_summary[:100]}
        await sched.update_history_for_task(task_id, status, in_tok, out_tok)
        job_info = await sched.get_job_for_task(task_id)
        if job_info:
            label = f"{job_info['name']} {'completed' if status == 'done' else 'failed'}"
            msg["job_name"] = job_info["name"]
        else:
            label = "complete" if status == "done" else "failed"
        shared.notify_all(msg)
        send_desktop_notification(f"Gator task {label}", result_summary[:80])

    set_notify_callback(_on_task_done)

    async def _bg_run_fn(prompt: str, skills: list[str] | None = None):
        import json as _json
        from agent_loop import _single_agent_loop
        from routes.chat import _infer_skills_from_message, _filter_tools
        from skill_router import match_intent, execute_direct
        provider = get_provider()
        model = get_active_model()
        _now = datetime.now()
        system = shared.get_system_prompt().replace("{date}", _now.strftime("%B %d, %Y")).replace(
            "{unix_ts}", str(int(_now.timestamp()))
        )

        # ── Skill Router: try direct dispatch first ──────────────
        intent = match_intent(prompt)
        if intent:
            direct = await execute_direct(intent, execute_tool, user_message=prompt)
            if direct.get("ok"):
                data_summary = _json.dumps(direct["data"], default=str)
                if len(data_summary) > 8000:
                    data_summary = data_summary[:8000] + "\n... (truncated)"
                routed_system = system + "\n\nYou have the data below. Summarize it directly for the user. Do NOT call any tools."
                routed_msgs = [{"role": "user", "content": f"{prompt}\n\n[Data from {intent['tool']}]:\n{data_summary}"}]
                async for chunk in _single_agent_loop(
                    provider=provider, model=model, system=routed_system,
                    msgs=routed_msgs, normalized_tools=[],
                    execute_tool=execute_tool, COM_BOUND_TOOLS=shared.COM_BOUND_TOOLS,
                    TOOL_STATUS=shared.TOOL_STATUS, _tool_toast=_tool_toast,
                    _SLACK_SAFE_MSG=shared._SLACK_SAFE_MSG,
                ):
                    yield chunk
                return

        # ── Standard path: filtered tools ────────────────────────
        # Use pre-captured skills from scheduler if available; fall back to inference
        if skills:
            inferred = list(skills)
        else:
            inferred = _infer_skills_from_message(prompt)
            if not inferred and prompt.strip():
                from routes.chat import _classify_skills_via_llm
                inferred = _classify_skills_via_llm(prompt)
        # Always filter — never fall back to ALL tools
        active_tools = _filter_tools(None, False, inferred)
        for sid in inferred:
            if sid in shared.SKILL_PROMPTS:
                system += "\n\n" + shared.SKILL_PROMPTS[sid]
        normalized_tools = [provider.normalize_tool_schema(t) for t in active_tools]
        async for chunk in _single_agent_loop(
            provider=provider, model=model, system=system,
            msgs=[{"role": "user", "content": prompt}],
            normalized_tools=normalized_tools,
            execute_tool=execute_tool, COM_BOUND_TOOLS=shared.COM_BOUND_TOOLS,
            TOOL_STATUS=shared.TOOL_STATUS, _tool_toast=_tool_toast,
            _SLACK_SAFE_MSG=shared._SLACK_SAFE_MSG,
        ):
            yield chunk

    cleanup_old_outputs()  # remove stale code_runner output dirs

    # Clean up orphaned Chrome processes from previous sessions
    from browser_agent import _kill_orphaned_chrome, shutdown_browser
    _kill_orphaned_chrome()

    await start_worker(_bg_run_fn)
    await sched.init_scheduler()

    async def _chat_store_cleanup():
        while True:
            await asyncio.sleep(300)
            try:
                n = shared.chat_task_store.cleanup_expired()
                if n:
                    print(f"[chat-store] cleaned {n} expired tasks", flush=True)
            except Exception:
                pass

    _cleanup_task = asyncio.create_task(_chat_store_cleanup())

    _update_check_task = asyncio.create_task(
        _updater.run_update_check_loop(shared.cfg)
    )

    async def _catalog_sync_loop():
        from marketplace.registry import refresh_catalog, _CATALOG_REFRESH_HOURS
        cfg = shared.cfg
        while True:
            try:
                await asyncio.to_thread(refresh_catalog, cfg)
            except Exception as exc:
                logger.warning("Catalog sync failed: %s", exc)
            await asyncio.sleep(_CATALOG_REFRESH_HOURS * 3600)

    _catalog_sync_task = asyncio.create_task(_catalog_sync_loop())

    yield

    _update_check_task.cancel()
    _cleanup_task.cancel()
    _catalog_sync_task.cancel()
    for _t in (_update_check_task, _cleanup_task, _catalog_sync_task):
        try:
            await _t
        except asyncio.CancelledError:
            pass
    await shutdown_browser()
    await sched.shutdown_scheduler()
    await stop_worker()


# ── App creation ─────────────────────────────────────────────────────────────

app = FastAPI(title="AI Gator", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(email_router)
app.include_router(slack_router)
app.include_router(teams_router)
app.include_router(jira_router)
app.include_router(confluence_router)
app.include_router(onedrive_router)
app.include_router(onenote_router)
app.include_router(calendar_router)
app.include_router(actions_router)
app.include_router(aigator_router)
app.include_router(config_router)
app.include_router(auth_router)
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(tasks_router)
app.include_router(utils_router)
app.include_router(scheduler_router)
app.include_router(conversation_router)
app.include_router(marketplace_router)
app.include_router(files_router)
app.include_router(updater_router)
app.include_router(mcp_router)
app.include_router(terminal_router)

# ── Middleware ────────────────────────────────────────────────────────────────

@app.middleware("http")
async def _latency_logger(request, call_next):
    import time as _t
    path = request.url.path
    if path.startswith("/static") or path in ("/logo", "/favicon.ico"):
        return await call_next(request)
    start = _t.perf_counter()
    response = await call_next(request)
    ms = (_t.perf_counter() - start) * 1000
    tag = "\033[33m SLOW\033[0m" if ms > 2000 else ""
    print(f"[{ms:7.0f}ms] {request.method} {path}{tag}")
    return response
