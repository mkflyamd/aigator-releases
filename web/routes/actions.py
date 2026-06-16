"""Quick-action route group -- jira, confluence, teams, news, calendar, onedrive actions."""

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import shared
from proc_utils import no_window_kwargs

ROOT = Path(__file__).parent.parent.parent

router = APIRouter()


# ── Pydantic models ──────────────────────────────────────────────────────────


class ActionRequest(BaseModel):
    query: str = ""


# ── Action endpoints ─────────────────────────────────────────────────────────


@router.post("/api/actions/jira")
async def action_jira(req: ActionRequest):
    from skills.jira.api import jira_api, jira_browse_url
    data = jira_api("GET", "search?jql=assignee%3DcurrentUser()%20ORDER%20BY%20updated%20DESC&maxResults=10&fields=summary,status,priority")
    issues = [
        {
            "key": i["key"],
            "summary": i["fields"].get("summary", ""),
            "status": i["fields"].get("status", {}).get("name", ""),
            "priority": (i["fields"].get("priority") or {}).get("name", ""),
            "url": f"{jira_browse_url()}/browse/{i['key']}",
        }
        for i in data.get("issues", [])
    ]
    return {"issues": issues}


@router.post("/api/actions/confluence")
async def action_confluence(req: ActionRequest):
    import urllib.parse
    from skills.confluence.api import confluence_api
    query = req.query or "claude code"
    cql = f'title ~ "{query}" AND type = page'
    params = urllib.parse.urlencode({"cql": cql, "limit": 8})
    data = confluence_api("GET", f"content/search?{params}")
    wiki_prefix = os.environ.get("CONFLUENCE_BASE_URL", "https://amd.atlassian.net/wiki")
    results = [
        {
            "title": r.get("title", ""),
            "space": r.get("resultGlobalContainer", {}).get("title", ""),
            "url": f"{wiki_prefix}{r.get('_links', {}).get('webui', '')}",
            "excerpt": r.get("excerpt", "")[:200],
        }
        for r in data.get("results", [])
    ]
    return {"results": results, "total": data.get("totalSize", len(results))}


@router.post("/api/actions/teams")
async def action_teams(req: ActionRequest):
    try:
        import re
        from skills._m365.helpers import make_teams_gc, get_current_user_display_name, html_to_text
        gc = make_teams_gc()

        # Fetch recent chats -- optionally filtered by topic keyword
        filter_topic = (req.query or "").strip().lower()
        resp = gc.get("/me/chats", {"$expand": "members", "$top": "20"})
        chats = resp.get("value", [])

        since = datetime.now(timezone.utc) - timedelta(hours=24)
        results = []

        for chat in chats:
            cid = chat["id"]
            topic = chat.get("topic") or ", ".join(
                m.get("displayName", "") for m in chat.get("members", [])[:3]
                if m.get("displayName") != get_current_user_display_name(gc)
            )
            chat_type = chat.get("chatType", "")

            if filter_topic and filter_topic not in topic.lower():
                continue

            msgs_resp = gc.get(f"/me/chats/{cid}/messages", {"$top": "20"})
            msgs = msgs_resp.get("value", []) if msgs_resp else []

            recent = []
            for m in msgs:
                if not m or not m.get("createdDateTime"):
                    continue
                t = datetime.fromisoformat(m["createdDateTime"].replace("Z", "+00:00"))
                if t < since:
                    continue
                sender = (m.get("from") or {}).get("user", {}).get("displayName", "")
                body = html_to_text((m.get("body") or {}).get("content", ""), max_len=300)
                if body and sender:
                    recent.append({
                        "sender": sender,
                        "time": m["createdDateTime"][:16].replace("T", " "),
                        "body": body,
                    })

            if recent:
                results.append({
                    "topic": topic[:60],
                    "type": chat_type,
                    "message_count": len(recent),
                    "messages": list(reversed(recent)),
                })

        results.sort(key=lambda x: x["message_count"], reverse=True)
        return {"chats": results, "total": len(results)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/actions/news")
async def action_news(req: ActionRequest):
    script = ROOT / "update_news_live.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True, text=True, timeout=30,
        **no_window_kwargs(),
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr or "PPT not open or update failed")
    return {"status": "ok", "message": result.stdout.strip()}


@router.post("/api/actions/calendar")
async def action_calendar(req: ActionRequest):
    try:
        from skills._m365.helpers import get_cal_client
        from skills.calendar.helpers import cal_day_range_utc, get_user_win_tz, fmt_cal_time
        gc = get_cal_client()
        today, tomorrow = cal_day_range_utc("", 1)
        events = gc.get("/me/calendarView", params={
            "startDateTime": today.isoformat().replace("+00:00", "Z"),
            "endDateTime": tomorrow.isoformat().replace("+00:00", "Z"),
            "$top": "10",
            "$select": "id,subject,start,end,location,isAllDay,organizer",
            "$orderby": "start/dateTime",
        }, extra_headers={"Prefer": f'outlook.timezone="{get_user_win_tz()}"'})
        return {"events": [
            {
                "id": e.get("id", ""),
                "subject": e.get("subject", "(no subject)"),
                "start": fmt_cal_time(e.get("start", {}).get("dateTime", "")),
                "end": fmt_cal_time(e.get("end", {}).get("dateTime", "")),
                "location": e.get("location", {}).get("displayName", ""),
                "isAllDay": e.get("isAllDay", False),
                "organizer": e.get("organizer", {}).get("emailAddress", {}).get("name", ""),
            }
            for e in events.get("value", [])
        ]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/actions/jira-urgent")
async def action_jira_urgent(req: ActionRequest):
    try:
        import urllib.parse
        from skills.jira.api import jira_api, jira_browse_url
        jql = "priority in (High,Urgent) AND status not in (Done,Closed,Resolved)"
        params = urllib.parse.urlencode({"jql": jql, "maxResults": 10, "fields": "summary,status,priority"})
        data = jira_api("GET", f"search?{params}")
        return {"issues": [
            {
                "key": i["key"],
                "summary": i["fields"].get("summary", ""),
                "status": i["fields"].get("status", {}).get("name", ""),
                "priority": (i["fields"].get("priority") or {}).get("name", ""),
                "url": f"{jira_browse_url()}/browse/{i['key']}",
            }
            for i in data.get("issues", [])
        ]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/actions/jira-custom")
async def action_jira_custom(req: ActionRequest):
    """Run an arbitrary JQL query passed via req.query."""
    import urllib.parse
    from skills.jira.api import jira_api, jira_browse_url
    jql = req.query.strip() if req.query else "assignee = currentUser() AND status != Done"
    try:
        params = urllib.parse.urlencode({"jql": jql, "maxResults": 15, "fields": "summary,status,priority"})
        data = jira_api("GET", f"search?{params}")
        return {"issues": [
            {
                "key": i["key"],
                "summary": i["fields"].get("summary", ""),
                "status": i["fields"].get("status", {}).get("name", ""),
                "priority": (i["fields"].get("priority") or {}).get("name", ""),
                "url": f"{jira_browse_url()}/browse/{i['key']}",
            }
            for i in data.get("issues", [])
        ], "jql": jql}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/actions/teams-mentions")
async def action_teams_mentions(req: ActionRequest):
    try:
        import re
        from skills._m365.helpers import make_teams_gc, get_current_user_display_name, html_to_text, _CURRENT_USER_CACHE
        gc = make_teams_gc()
        since = datetime.now(timezone.utc) - timedelta(hours=48)
        chats = gc.get("/me/chats", {"$expand": "members", "$top": "30"}).get("value", [])
        mentions = []
        for chat in chats:
            cid = chat["id"]
            topic = chat.get("topic") or ", ".join(
                m.get("displayName", "") for m in chat.get("members", [])[:3]
                if m.get("displayName") != get_current_user_display_name(gc)
            )
            msgs = gc.get(f"/me/chats/{cid}/messages", {"$top": "20"}).get("value", []) or []
            for m in msgs:
                if not m or not m.get("createdDateTime"):
                    continue
                t = datetime.fromisoformat(m["createdDateTime"].replace("Z", "+00:00"))
                if t < since:
                    continue
                body_raw = (m.get("body") or {}).get("content", "")
                me_name = get_current_user_display_name(gc)
                me_upn = _CURRENT_USER_CACHE.get("upn", "")
                me_alias = me_upn.split("@")[0] if me_upn else ""
                name_parts = [p for p in me_name.replace(",", "").split() if len(p) > 2]
                if not any((p in body_raw) for p in name_parts + ([me_alias] if me_alias else [])):
                    continue
                body = html_to_text(body_raw, max_len=300)
                sender = (m.get("from") or {}).get("user", {}).get("displayName", "")
                if body and sender:
                    mentions.append({
                        "topic": topic[:50],
                        "sender": sender,
                        "time": m["createdDateTime"][:16].replace("T", " "),
                        "body": body,
                    })
        return {"mentions": mentions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/actions/onedrive")
async def action_onedrive(req: ActionRequest):
    try:
        from skills._m365.helpers import GraphClient
        gc = GraphClient()
        items = gc.get("/me/drive/recent", params={
            "$top": "8",
            "$select": "name,lastModifiedDateTime,webUrl,size,file",
        })
        def _fmt_size(b: int) -> str:
            if b < 1024: return f"{b} B"
            if b < 1048576: return f"{b//1024} KB"
            return f"{b//1048576} MB"
        return {"files": [
            {
                "name": f.get("name", ""),
                "modified": f.get("lastModifiedDateTime", "")[:10],
                "url": f.get("webUrl", ""),
                "size": _fmt_size(f.get("size", 0)),
            }
            for f in items.get("value", [])
            if f.get("file")
        ]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
