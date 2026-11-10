"""Daily per-user usage rows, written to a SharePoint list through Microsoft Graph.

Counts only: chat messages and tool runs per UTC day, read from tasks.db. Never
message text, file names or tool arguments.
"""

import asyncio
import base64
import json
import logging
import re
import sqlite3
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from config import GATOR_DIR, TASKS_DB
from identity import email_from_token
from log_sanitizer import sanitize

_log = logging.getLogger(__name__)

STATE_FILE = GATOR_DIR / "usage_report.json"
MAX_AGE_DAYS = 7
_REPORT_INTERVAL_S = 24 * 60 * 60
_SENT_KEYS_KEPT = 60
_MAX_TOP_TOOLS = 10
_PLAIN_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_SIGNAL_FIELDS = (
    "InputTokens", "OutputTokens", "Conversations", "BackgroundTasks", "ToolErrors",
    "McpToolRuns", "LlmErrors", "Failovers", "Drafts", "AvgTurnMs",
)
_SCALAR_SIGNALS = (
    ("InputTokens", "COALESCE(SUM(input_tokens), 0)", "usage_log", ""),
    ("OutputTokens", "COALESCE(SUM(output_tokens), 0)", "usage_log", ""),
    ("Conversations", "COUNT(DISTINCT context_id)", "turn_log", ""),
    ("BackgroundTasks", "COUNT(*)", "tasks", ""),
    ("ToolErrors", "COUNT(*)", "tool_call_log", "AND outcome = 'error'"),
    ("McpToolRuns", "COUNT(*)", "tool_call_log", "AND is_mcp = 1"),
    ("LlmErrors", "COUNT(*)", "turn_log", "AND llm_error IS NOT NULL AND llm_error != ''"),
    ("Failovers", "COUNT(*)", "turn_log", "AND failover_used != 0"),
    ("Drafts", "COUNT(*)", "task_drafts", ""),
    ("AvgTurnMs", "CAST(ROUND(AVG(duration_ms)) AS INTEGER)", "turn_log", "AND duration_ms IS NOT NULL"),
)


def is_enabled(cfg: dict | None) -> bool:
    cfg = cfg or {}
    return bool(cfg.get("usage_list_site_id") and cfg.get("usage_list_id"))


def _graph_client():
    from skills._m365.helpers import GraphClient

    return GraphClient()


def _app_version() -> str:
    from updater import get_current_version

    return get_current_version()


def _os_name() -> str:
    return {"win32": "Windows", "darwin": "macOS"}.get(sys.platform, "Linux")


def _load_state() -> dict:
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    state.setdefault("install_id", str(uuid.uuid4()))
    state.setdefault("sent", [])
    return state


def _save_state(state: dict) -> None:
    state["sent"] = state["sent"][-_SENT_KEYS_KEPT:]
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def _counts_by_day(since_day: str) -> dict[str, list[int]]:
    """Return {day: [messages, tool_runs]} for UTC days on or after *since_day*."""
    days: dict[str, list[int]] = {}
    queries = (
        (0, "SELECT substr(created_at, 1, 10), COUNT(*) FROM usage_log "
            "WHERE source IN ('chat', 'chat-direct') AND created_at >= ? GROUP BY 1"),
        (1, "SELECT substr(created_at, 1, 10), COUNT(*) FROM tool_call_log "
            "WHERE created_at >= ? GROUP BY 1"),
    )
    con = sqlite3.connect(f"file:{TASKS_DB}?mode=ro", uri=True)
    try:
        for idx, sql in queries:
            try:
                for day, n in con.execute(sql, (since_day,)):
                    days.setdefault(day, [0, 0])[idx] = n
            except sqlite3.OperationalError:
                continue
    finally:
        con.close()
    return days


def _query(con: sqlite3.Connection, sql: str, params: tuple) -> list:
    try:
        return con.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []


def _builtin_skills() -> set[str]:
    root = Path(__file__).parent / "skills"
    return {p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")}


def _blank_details() -> dict:
    return {"models": {}, "skills": {}, "tools": {}, "errors": {}}


def _details_json(details: dict) -> str:
    return json.dumps(details, separators=(",", ":"), sort_keys=True)


def _blank_signals() -> dict:
    return {**{name: 0 for name in _SIGNAL_FIELDS}, "Details": _details_json(_blank_details())}


def _signals_by_day(since_day: str) -> dict[str, dict]:
    """Return {day: signal fields} for UTC days on or after *since_day*. Missing tables or columns give zeros."""
    builtin = _builtin_skills()
    scalars: dict[str, dict] = {}
    details: dict[str, dict] = {}

    def detail(day: str) -> dict:
        return details.setdefault(day, _blank_details())

    con = sqlite3.connect(f"file:{TASKS_DB}?mode=ro", uri=True)
    try:
        for field, expr, table, cond in _SCALAR_SIGNALS:
            sql = f"SELECT substr(created_at, 1, 10), {expr} FROM {table} WHERE created_at >= ? {cond} GROUP BY 1"
            for day, value in _query(con, sql, (since_day,)):
                scalars.setdefault(day, _blank_signals())[field] = value or 0

        for day, provider, model, n in _query(
            con,
            "SELECT substr(created_at, 1, 10), provider, model, COUNT(*) FROM turn_log "
            "WHERE created_at >= ? GROUP BY 1, 2, 3",
            (since_day,),
        ):
            if provider or model:
                detail(day)["models"][f"{provider}/{model}"] = n

        for day, raw in _query(
            con,
            "SELECT substr(created_at, 1, 10), active_skills FROM turn_log "
            "WHERE created_at >= ? AND active_skills IS NOT NULL",
            (since_day,),
        ):
            try:
                names = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(names, list):
                continue
            skills = detail(day)["skills"]
            for name in names:
                key = name if isinstance(name, str) and name in builtin else "custom"
                skills[key] = skills.get(key, 0) + 1

        for day, name, n in _query(
            con,
            "SELECT substr(created_at, 1, 10), tool_name, COUNT(*) FROM tool_call_log "
            "WHERE created_at >= ? AND is_mcp = 0 GROUP BY 1, 2 ORDER BY 3 DESC",
            (since_day,),
        ):
            tools = detail(day)["tools"]
            if _PLAIN_NAME.match(name or "") and len(tools) < _MAX_TOP_TOOLS:
                tools[name] = n

        for day, code, n in _query(
            con,
            "SELECT substr(created_at, 1, 10), error_code, COUNT(*) FROM tool_call_log "
            "WHERE created_at >= ? AND outcome = 'error' AND error_code IS NOT NULL GROUP BY 1, 2",
            (since_day,),
        ):
            if _PLAIN_NAME.match(code):
                detail(day)["errors"][code] = n
    finally:
        con.close()

    for day, sig in scalars.items():
        if sig["McpToolRuns"]:
            detail(day)["tools"]["mcp"] = sig["McpToolRuns"]

    result: dict[str, dict] = {}
    for day in scalars.keys() | details.keys():
        sig = dict(scalars.get(day) or _blank_signals())
        sig["Details"] = _details_json(details.get(day) or _blank_details())
        result[day] = sig
    return result


def _share_id(link: str) -> str:
    return "u!" + base64.urlsafe_b64encode(link.encode()).decode().rstrip("=")


def _is_duplicate(exc: Exception) -> bool:
    text = str(exc).lower()
    return getattr(exc, "status_code", 0) in (400, 409) and ("unique" in text or "duplicate" in text)


def _send(gc, site: str, list_id: str, link: str, fields: dict) -> str:
    """Return 'sent' or 'duplicate'; raise on any other failure."""
    redeemed = False
    while True:
        try:
            gc.post(f"/sites/{site}/lists/{list_id}/items", {"fields": fields})
            return "sent"
        except Exception as exc:
            if _is_duplicate(exc):
                return "duplicate"
            if getattr(exc, "status_code", 0) == 403 and link and not redeemed:
                redeemed = True
                gc.get(f"/shares/{_share_id(link)}/list")
                continue
            raise


async def report_pending(cfg: dict | None = None, today: date | None = None) -> int:
    """Send each unsent active past day (up to MAX_AGE_DAYS back). Returns rows sent. Never raises."""
    if not is_enabled(cfg):
        return 0
    site = cfg["usage_list_site_id"]
    list_id = cfg["usage_list_id"]
    link = cfg.get("usage_list_link", "")
    try:
        gc = await asyncio.to_thread(_graph_client)
        email = email_from_token(await asyncio.to_thread(gc.get_token))
        if not email:
            return 0
        today = today or datetime.now(timezone.utc).date()
        since = (today - timedelta(days=MAX_AGE_DAYS)).isoformat()
        days = await asyncio.to_thread(_counts_by_day, since)
        signals = await asyncio.to_thread(_signals_by_day, since)
        state = _load_state()
        sent_keys = set(state["sent"])
        version = _app_version()
        sent = 0
        for day in sorted(days):
            key = f"{email}|{day}"
            if day >= today.isoformat() or key in sent_keys:
                continue
            messages, tool_runs = days[day]
            fields = {
                "Title": key,
                "Email": email,
                "ReportDate": day,
                "OS": _os_name(),
                "AppVersion": version,
                "InstallId": state["install_id"],
                "Messages": messages,
                "ToolRuns": tool_runs,
            }
            fields.update(signals.get(day) or _blank_signals())
            try:
                outcome = await asyncio.to_thread(_send, gc, site, list_id, link, fields)
            except Exception as exc:
                _log.warning("Usage report for %s not sent: %s", day, sanitize(str(exc)))
                break
            state["sent"].append(key)
            sent += outcome == "sent"
        _save_state(state)
        return sent
    except Exception as exc:
        _log.warning("Usage report failed: %s", sanitize(str(exc)))
        return 0


async def run_usage_report_loop(cfg: dict) -> None:
    """Background loop: report at startup, then once a day."""
    try:
        while True:
            await report_pending(cfg)
            await asyncio.sleep(_REPORT_INTERVAL_S)
    except asyncio.CancelledError:
        pass
