"""Health, system, and utility routes — prefetch, skills index, status, logo, server lifecycle,
keepalive, root page, people/channel search."""

import asyncio
import json
import os
import re
import subprocess
import sys
import time as _time_mod
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

import shared
import updater

router = APIRouter()

ROOT = Path(__file__).parent.parent.parent  # web/routes -> web -> project root


# ── Version ───────────────────────────────────────────────────────────────────

APP_VERSION = updater.get_current_version()
APP_STARTED_AT = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ── Prefetch ──────────────────────────────────────────────────────────────────

@router.get("/api/prefetch")
async def prefetch_all():
    """Combined prefetch for splash — runs Teams + Email in parallel threads."""
    import time as _t

    def _fetch_teams():
        t0 = _t.perf_counter()
        try:
            from routes.teams import _get_skype_module, _normalize_skype_chats, _resolve_chat_names
            _rc = _get_skype_module()
            skype_token, messaging_service = _rc.get_auth()
            convs, _ = _rc.list_chats(skype_token, messaging_service, limit=50)
            chats = _normalize_skype_chats(convs)
            _resolve_chat_names(chats)
            ms = (_t.perf_counter() - t0) * 1000
            print(f"[prefetch:teams] {ms:.0f}ms — {len(chats)} chats", flush=True)
            return {"chats": chats, "has_viewpoint": True, "has_more": False}
        except Exception as e:
            ms = (_t.perf_counter() - t0) * 1000
            print(f"[prefetch:teams] {ms:.0f}ms — failed: {e}", flush=True)
            return {"chats": [], "has_viewpoint": False, "error": str(e)}

    def _fetch_email():
        t0 = _t.perf_counter()
        try:
            from skills._m365.helpers import GraphClient
            from routes.email import _format_email_message
            gc = GraphClient()
            select = "id,subject,from,receivedDateTime,bodyPreview,isRead,importance,hasAttachments"
            params = {"$top": "50", "$select": select, "$orderby": "receivedDateTime desc"}
            result = gc.get("/me/mailFolders/inbox/messages", params)
            folder = gc.get("/me/mailFolders/inbox", {"$select": "unreadItemCount"})
            messages = [_format_email_message(m) for m in result.get("value", [])]
            ms = (_t.perf_counter() - t0) * 1000
            print(f"[prefetch:email] {ms:.0f}ms — {len(messages)} emails", flush=True)
            return {"messages": messages, "total_unread": folder.get("unreadItemCount", 0)}
        except Exception as e:
            print(f"[prefetch:email] failed: {e}", flush=True)
            return {"messages": [], "total_unread": 0, "error": str(e)}

    # Phase 1: fetch Teams + Email lists in parallel with a hard timeout so the
    # splash never hangs forever if Graph is slow or auth is broken.
    try:
        teams, email = await asyncio.wait_for(
            asyncio.gather(
                asyncio.to_thread(_fetch_teams),
                asyncio.to_thread(_fetch_email),
            ),
            timeout=20,  # seconds — splash dismisses after this even if still loading
        )
    except asyncio.TimeoutError:
        print("[prefetch] phase-1 timed out after 20s", flush=True)
        teams = {"chats": [], "has_viewpoint": False, "error": "timeout"}
        email = {"messages": [], "total_unread": 0, "error": "timeout"}

    threads = {}
    emails = {}

    # Build all pre-warm tasks (threads + emails) and run in parallel
    warmup_tasks = []

    if teams.get("chats") and not teams.get("error"):
        def _fetch_thread(chat):
            try:
                from skills._m365.helpers import make_teams_gc, html_to_text, get_cached_me
                gc = make_teams_gc()
                me = get_cached_me(gc)
                my_id = me.get("id", "")
                my_name = me.get("displayName", "")
                result = gc.get(f"/me/chats/{chat['id']}/messages", {"$top": "50"}, base_url="https://graph.microsoft.com/beta")
                raw = result.get("value", [])
                messages = []
                for m in raw:
                    if m.get("messageType", "message") != "message":
                        continue
                    sender = ((m.get("from") or {}).get("user") or {})
                    sender_id = sender.get("id", "")
                    sender_name = sender.get("displayName", "")
                    is_mine = bool(
                        (my_id and sender_id and sender_id == my_id) or
                        (my_name and sender_name and sender_name == my_name)
                    )
                    body_content = (m.get("body") or {}).get("content", "")
                    content_type = (m.get("body") or {}).get("contentType", "text")
                    body_html = ""
                    if content_type == "html" and body_content:
                        body_html = re.sub(
                            r'src="(https://(?:graph\.microsoft\.com|[^"]*\.teams\.microsoft\.com|[^"]*\.sfbassets\.com)[^"]+)"',
                            r'src="" data-teams-src="\1"',
                            body_content
                        )
                    body_text = html_to_text(body_content, max_len=2000) if content_type == "html" else body_content
                    attachments_raw = m.get("attachments") or []
                    attachments = [{"id": a.get("id", ""), "name": a.get("name", ""),
                                    "content_type": a.get("contentType", ""), "content_url": a.get("contentUrl", ""),
                                    "thumbnail_url": a.get("thumbnailUrl", "")}
                                   for a in attachments_raw if a.get("name")]
                    messages.append({
                        "id": m.get("id", ""),
                        "sender_name": sender_name,
                        "sender_id": sender_id,
                        "is_mine": is_mine,
                        "body": body_text,
                        "body_html": body_html,
                        "created_at": m.get("createdDateTime", ""),
                        "last_modified_at": m.get("lastModifiedDateTime", ""),
                        "reactions": [],
                        "attachments": attachments,
                    })
                # Graph returns newest-first — reverse to chronological
                messages.reverse()
                return ("thread", chat["id"], {"messages": messages, "my_id": my_id})
            except Exception:
                return None

        top_chats = [c for c in teams["chats"] if not c["id"].startswith("ch::")][:3]
        for c in top_chats:
            warmup_tasks.append(asyncio.to_thread(_fetch_thread, c))

    if email.get("messages") and not email.get("error"):
        def _fetch_email_detail(msg_id):
            try:
                from skills._m365.helpers import GraphClient, html_to_text
                gc = GraphClient()
                select = "id,subject,from,toRecipients,ccRecipients,receivedDateTime,body,isRead,importance"
                m = gc.get(f"/me/messages/{msg_id}", {"$select": select})
                from_obj = (m.get("from") or {}).get("emailAddress") or {}
                body_obj = m.get("body") or {}
                content_type = body_obj.get("contentType", "text")
                body_content = body_obj.get("content", "")
                def _recip(r):
                    ea = (r.get("emailAddress") or {})
                    return {"name": ea.get("name", ""), "email": ea.get("address", "")}
                return ("email", msg_id, {
                    "id": m.get("id", ""),
                    "subject": m.get("subject", ""),
                    "from_name": from_obj.get("name", ""),
                    "from_email": from_obj.get("address", ""),
                    "to": [_recip(r) for r in (m.get("toRecipients") or [])],
                    "cc": [_recip(r) for r in (m.get("ccRecipients") or [])],
                    "received_at": m.get("receivedDateTime", ""),
                    "body_html": body_content if content_type == "html" else "",
                    "body_text": html_to_text(body_content, max_len=3000) if content_type == "html" else body_content,
                    "is_read": m.get("isRead", True),
                    "importance": m.get("importance", "normal"),
                    "meeting_message_type": "",
                    "event_id": "",
                    "meeting_details": {},
                })
            except Exception:
                return None

        top_emails = email["messages"][:3]
        for em in top_emails:
            warmup_tasks.append(asyncio.to_thread(_fetch_email_detail, em["id"]))

    if warmup_tasks:
        try:
            results = await asyncio.wait_for(asyncio.gather(*warmup_tasks), timeout=15)
        except asyncio.TimeoutError:
            print("[prefetch] warmup timed out after 15s", flush=True)
            results = []
        for r in results:
            if not r:
                continue
            kind, item_id, data = r
            if kind == "thread":
                threads[item_id] = data
            elif kind == "email":
                emails[item_id] = data
        print(f"[prefetch:warmup] {len(threads)} threads + {len(emails)} emails pre-warmed", flush=True)

    return {"teams": teams, "email": email, "threads": threads, "emails": emails}


# ── Skills Index ──────────────────────────────────────────────────────────────

@router.get("/api/skills")
async def list_skills():
    """Return installed skills index — reads every manifest.json under web/skills/."""
    skills_root = Path(__file__).parent.parent / "skills"
    result = []
    if skills_root.exists():
        for skill_dir in sorted(skills_root.iterdir()):
            manifest_path = skill_dir / "manifest.json"
            if skill_dir.is_dir() and manifest_path.exists():
                try:
                    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                    manifest.setdefault("id", skill_dir.name)
                    result.append(manifest)
                except Exception:
                    pass
    return {"skills": result}


# ── Status / Health ───────────────────────────────────────────────────────────

@router.get("/status")
async def status():
    return {"ok": True, "running": True}

@router.get("/health")
async def health():
    skills_root = Path(__file__).parent.parent / "skills"
    scan_errors = []
    found_manifests = []
    if skills_root.exists():
        for d in skills_root.iterdir():
            mp = d / "manifest.json"
            if d.is_dir() and mp.exists():
                try:
                    m = json.loads(mp.read_text(encoding='utf-8'))
                    found_manifests.append({"dir": d.name, "id": m.get("id"), "tools": m.get("tools", [])})
                except Exception as e:
                    scan_errors.append({"dir": d.name, "error": str(e)})
    return {
        "status": "ok",
        "version": APP_VERSION,
        "started_at": APP_STARTED_AT,
        "file": __file__,
        "skills_root": str(skills_root),
        "skills_root_exists": skills_root.exists(),
        "found_manifests": found_manifests,
        "scan_errors": scan_errors,
        "skill_tools_map": {k: sorted(v) for k, v in shared.SKILL_TOOLS_MAP.items()},
        "tool_count": len(shared.TOOLS),
        "failed_skills": shared.FAILED_SKILLS,
    }


# ── Logo ──────────────────────────────────────────────────────────────────────

@router.get("/logo")
async def logo():
    from fastapi.responses import FileResponse
    # Dev: ROOT/tray/  Installed: ROOT is {app}/app, PNG is at {app}/tray/
    for candidate in [ROOT / "tray" / "aigator_icon.png",
                      ROOT.parent / "tray" / "aigator_icon.png"]:
        if candidate.exists():
            return FileResponse(candidate, media_type="image/png")
    svg = Path(__file__).parent.parent / "static" / "favicon.svg"
    return FileResponse(svg, media_type="image/svg+xml")


# ── Server Lifecycle ──────────────────────────────────────────────────────────

@router.post("/api/server/restart")
async def server_restart():
    async def _restart():
        await asyncio.sleep(1)
        subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "web.app:app", "--port", "8000", "--reload"],
            cwd=str(ROOT),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )
        await asyncio.sleep(1)
        os._exit(0)
    asyncio.create_task(_restart())
    return {"ok": True}


@router.post("/api/server/stop")
async def server_stop():
    async def _stop():
        await asyncio.sleep(1)
        os._exit(0)
    asyncio.create_task(_stop())
    return {"ok": True}


# ── Keepalive (mouse jiggle to prevent idle/sleep) ────────────────────────────

@router.post("/api/keepalive/jiggle")
def keepalive_jiggle():
    """Simulate real mouse input to reset Windows idle timer (Teams uses GetLastInputInfo)."""
    try:
        import ctypes
        import ctypes.wintypes

        # SendInput structures — simulates hardware-level mouse event
        INPUT_MOUSE = 0
        MOUSEEVENTF_MOVE = 0x0001

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                        ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                        ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

        class INPUT(ctypes.Structure):
            class _INPUT(ctypes.Union):
                _fields_ = [("mi", MOUSEINPUT)]
            _fields_ = [("type", ctypes.c_ulong), ("_input", _INPUT)]

        def _send_mouse_move(dx, dy):
            mi = MOUSEINPUT(dx, dy, 0, MOUSEEVENTF_MOVE, 0, ctypes.pointer(ctypes.c_ulong(0)))
            inp = INPUT(type=INPUT_MOUSE)
            inp._input.mi = mi
            ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

        # Move 1px right, then 1px back — resets GetLastInputInfo
        _send_mouse_move(1, 0)
        import time as _t; _t.sleep(0.05)
        _send_mouse_move(-1, 0)

        # Prevent display/system sleep
        ES_CONTINUOUS = 0x80000000
        ES_DISPLAY_REQUIRED = 0x00000002
        ES_SYSTEM_REQUIRED = 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Root (serve index.html) ──────────────────────────────────────────────────

def _mcp_skills_bootstrap() -> str:
    """Build a <script> block that injects MCP connection data into the page before app.js runs.

    Reads from the shared registry (already loaded at startup via load_all_from_cache).
    No network calls — pure in-memory data.
    """
    from config import load_config
    connections = load_config().get("mcp_connections", [])
    skills = []
    for conn in connections:
        if not conn.get("enabled", True):
            continue
        tool_count = len(conn.get("cached_tools", []))
        if not tool_count:
            continue
        skills.append({
            "id": conn.get("id"),
            "name": conn.get("name", conn.get("id", "")),
            "url": conn.get("url", ""),
            "tool_count": tool_count,
        })
    payload = json.dumps(skills)
    return f'<script>window.__MCP_SKILLS__ = {payload};</script>'


def _user_skills_bootstrap() -> str:
    """Build a <script> block that injects installed marketplace skills (Community, Verified, Mine)
    into the page so they appear in slash commands without a page reload."""
    from marketplace.installer import load_installed
    skills = []
    for e in load_installed():
        entry = {
            "id": e["id"],
            "name": e.get("display_name", e["id"]),
            "tier": e.get("tier", "Community"),
        }
        deps = shared.SKILL_DEPENDENCIES_MAP.get(e["id"])
        if deps:
            entry["requires"] = deps
        skills.append(entry)
    payload = json.dumps(skills)
    return f'<script>window.__USER_SKILLS__ = {payload};</script>'


@router.get("/", response_class=HTMLResponse)
async def root():
    from security import get_csrf_token
    html = (Path(__file__).parent.parent / "static" / "index.html").read_text(encoding="utf-8")
    csrf = f'<script>window.__CSRF_TOKEN__ = {json.dumps(get_csrf_token())};</script>'
    bootstrap = csrf + '\n' + _mcp_skills_bootstrap() + '\n' + _user_skills_bootstrap()
    injections = bootstrap
    if os.environ.get("DEV_MODE"):
        injections += '\n<script src="/static/dev-overlay.js"></script>'
    # Inject before </head> so data is available before app.js parses SKILL_REGISTRY
    return html.replace("</head>", f"{injections}\n</head>", 1)


# ── People Search ─────────────────────────────────────────────────────────────

@router.get("/api/people/search")
def people_search(q: str = ""):
    q = re.sub(r"[._]+", " ", q.lstrip('@')).strip()
    if not q or len(q) < 2:
        return {"people": []}
    from skills.people.tools import _tool_search_people
    result = _tool_search_people(query=q, count=10)
    return {"people": result.get("people", [])}


# ── Teams Channel Search (for # mention dropdown) ────────────────────────────

@router.get("/api/channels/search")
def channels_search(q: str = "", bust: bool = False):
    """Return Teams channels matching query, formatted for the # dropdown."""
    from skills._m365.helpers import make_teams_gc
    now = _time_mod.time()
    if bust:
        shared._channels_cache["data"] = None
    # Rebuild cache if stale
    if not shared._channels_cache["data"] or now - shared._channels_cache["ts"] > shared._CHANNELS_CACHE_TTL:
        try:
            gc = make_teams_gc()
            channels = []

            # 1) Team channels — use $batch to avoid N+1 pattern
            teams_resp = gc.get("/me/joinedTeams", {"$select": "id,displayName"})
            teams = teams_resp.get("value", [])
            if teams:
                batch_reqs = [
                    {"id": str(i), "method": "GET", "url": f"/teams/{t['id']}/channels?$select=id,displayName"}
                    for i, t in enumerate(teams)
                ]
                try:
                    batch_results = gc.batch(batch_reqs)
                    results_by_id = {r["id"]: r for r in batch_results}
                    for i, team in enumerate(teams):
                        r = results_by_id.get(str(i), {})
                        if r.get("status", 0) == 200:
                            for ch in r.get("body", {}).get("value", []):
                                channels.append({
                                    "type": "channel",
                                    "team_id": team["id"],
                                    "team_name": team.get("displayName", ""),
                                    "channel_id": ch["id"],
                                    "channel_name": ch.get("displayName", ""),
                                })
                except Exception:
                    # Fallback to individual calls if $batch fails
                    for team in teams:
                        try:
                            ch_resp = gc.get(f"/teams/{team['id']}/channels", {"$select": "id,displayName"})
                            for ch in ch_resp.get("value", []):
                                channels.append({
                                    "type": "channel",
                                    "team_id": team["id"],
                                    "team_name": team.get("displayName", ""),
                                    "channel_id": ch["id"],
                                    "channel_name": ch.get("displayName", ""),
                                })
                        except Exception:
                            continue

            # 2) Group chats via Skype API (no Graph scope needed)
            try:
                from routes.teams import _get_skype_module, _normalize_skype_chats
                _rc = _get_skype_module()
                skype_token, messaging_service = _rc.get_auth()
                convs, _ = _rc.list_chats(skype_token, messaging_service, limit=50)
                skype_chats = _normalize_skype_chats(convs)
                for chat in skype_chats:
                    if chat.get("chat_type") != "group":
                        continue
                    topic = chat.get("topic", "") or "Group Chat"
                    channels.append({
                        "type": "groupchat",
                        "chat_id": chat["id"],
                        "channel_name": topic,
                        "team_name": "Group Chat",
                    })
            except Exception as gc_err:
                print(f"[channels_search] group chat error: {gc_err}")

            shared._channels_cache["data"] = channels
            shared._channels_cache["ts"] = now
        except Exception as e:
            return {"channels": [], "error": str(e)}

    all_channels = shared._channels_cache["data"] or []
    if q:
        ql = q.lower()
        all_channels = [c for c in all_channels
                        if ql in c["channel_name"].lower() or ql in c["team_name"].lower()]
    return {"channels": all_channels[:20]}
