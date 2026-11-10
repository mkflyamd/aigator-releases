"""Daily per-user usage rows, written to a SharePoint list through Microsoft Graph.

Counts only: chat messages and tool runs per UTC day, read from tasks.db. Never
message text, file names or tool arguments.
"""

import asyncio
import base64
import json
import logging
import sqlite3
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

from config import GATOR_DIR, TASKS_DB
from identity import email_from_token
from log_sanitizer import sanitize

_log = logging.getLogger(__name__)

USAGE_SITE_ID = "amdcloud-my.sharepoint.com,10682248-af0e-4cf7-afaa-4644bb76721b,b6568823-c240-4e3f-9366-e7de15790fa6"
USAGE_LIST_ID = "8c849f55-edf0-4117-8f3c-cba1e6164241"
USAGE_LIST_LINK = "https://amdcloud-my.sharepoint.com/:l:/g/personal/maykulka_amd_com/JABVn4SM8O0XQY88y6HmFkJBARBWnKxSLXMJiUGH98lkULA?e=oaVZ4p"

STATE_FILE = GATOR_DIR / "usage_report.json"
MAX_AGE_DAYS = 7
_REPORT_INTERVAL_S = 24 * 60 * 60
_SENT_KEYS_KEPT = 60


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
    cfg = cfg or {}
    site = cfg.get("usage_list_site_id", USAGE_SITE_ID)
    list_id = cfg.get("usage_list_id", USAGE_LIST_ID)
    link = cfg.get("usage_list_link", USAGE_LIST_LINK)
    if not site or not list_id:
        return 0
    try:
        gc = await asyncio.to_thread(_graph_client)
        email = email_from_token(await asyncio.to_thread(gc.get_token))
        if not email:
            return 0
        today = today or datetime.now(timezone.utc).date()
        days = await asyncio.to_thread(_counts_by_day, (today - timedelta(days=MAX_AGE_DAYS)).isoformat())
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
