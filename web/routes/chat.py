"""Chat route — POST /api/chat streaming endpoint with skill detection and context injection."""

import json
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import load_config as _load_config
import shared

import re as _re


def parse_slash_command(message: str) -> dict | None:
    """Parse /plugin:capability [message] syntax.

    Returns {"plugin": str, "capability": str, "message": str} or None.

    Matches only if the message starts with /word:word (colon required) AND
    the capability is followed by whitespace or end-of-string. Malformed
    forms like `/a:b:c diagnose` (three+ colons) return None and fall through
    to plain LLM input — better than silently leaking `:c diagnose` into the
    rewritten message.
    """
    message = message.strip()
    match = _re.match(r"^/([\w-]+):([\w-]+)(?:\s+(.*))?$", message, _re.DOTALL)
    if not match:
        return None
    trailing = match.group(3) or ""
    return {
        "plugin": match.group(1),
        "capability": match.group(2),
        "message": trailing.strip(),
    }


router = APIRouter()


# ── Pydantic models ───────────────────────────────────────────────────────────

_GATED_DEP_SKILLS: frozenset[str] = frozenset({"shell_runner", "code_runner"})

# Detects phrases like "add the @outlook skill", "activate /teams skill",
# "load the confluence skill" — used to auto-activate the requested skill
# mid-conversation and retry the LLM call with the expanded toolset.
_SKILL_REQUEST_RE = _re.compile(
    r"(?:add|activate|enable|load|use)\s+(?:the\s+)?[`'\"]?[@/]?([a-z0-9][a-z0-9_-]*)[`'\"]?\s+skill",
    _re.IGNORECASE,
)


class ChatRequest(BaseModel):
    message: str | list
    history: list = []
    active_skill: str = ""
    active_skills: list[str] | None = None
    has_images: bool = False
    image_names: list[str] | None = None   # filenames of uploaded images (issue #12)
    image_paths: list[str] | None = None   # saved paths on disk for uploaded images (issue #12)
    active_channels: list[dict] | None = None  # [{team_id, channel_id, channel_name, team_name}]
    context_id: str = "default"  # tab-scoped context for pins
    model: str = ""  # model selected in prompt bar; sent explicitly so server never relies on global state
    unapproved_deps: list[str] | None = None  # gated dep IDs not yet approved this conversation


# ── Tool filtering ────────────────────────────────────────────────────────────

def _filter_tools(active_skill: str, has_images: bool, active_skills: list[str] | None = None,
                  unapproved_deps: list[str] | None = None) -> list:
    """Return the shared.TOOLS subset for the active skill(s). Falls back to always-on tools when no skill is active."""
    skill_ids = set()
    if active_skill and active_skill in shared.SKILL_TOOLS_MAP:
        skill_ids.add(active_skill)
    for sid in (active_skills or []):
        if sid in shared.SKILL_TOOLS_MAP:
            skill_ids.add(sid)

    _unapproved = set(unapproved_deps or [])
    # Auto-include approved dependency skills in the tool set; skip gated deps that are still unapproved
    for primary_sid in list(skill_ids):
        for dep in shared.SKILL_DEPENDENCIES_MAP.get(primary_sid, []):
            dep_id = dep["id"]
            if dep_id in shared.SKILL_TOOLS_MAP:
                if dep_id not in _GATED_DEP_SKILLS or dep_id not in _unapproved:
                    skill_ids.add(dep_id)

    if not skill_ids:
        allowed = set(shared._ALWAYS_ON_TOOLS)
    else:
        allowed = set(shared._ALWAYS_ON_TOOLS)
        for sid in skill_ids:
            allowed |= shared.SKILL_TOOLS_MAP[sid]
    return [t for t in shared.TOOLS if t["name"] in allowed]


# ── Auto-skill detection from user message keywords ──────────────────────────

_SKILL_KEYWORDS = {
    "docx": ["word doc", "word document", ".docx", "write a doc", "create a doc",
             "open word", "in word", "to word", "into word",
             "fill out", "fill in", "fill this", "skills chart", "perm chart",
             "the form", "the template", "the table"],
    "excel": ["excel", "spreadsheet", ".xlsx", "workbook", "worksheet",
              "open excel", "in excel", "to excel", "into excel"],
    "ppt": ["powerpoint", "presentation", ".pptx", "slide deck",
            "open powerpoint", "in powerpoint", "to powerpoint", "into powerpoint", "into ppt"],
    "email": ["forward", "send him", "send her", "send them", "email him", "email her",
              "email them", "email me", "email us", "send me", "send an email", "send the invite",
              "forward the invite", "forward the meeting", "invite him", "invite her", "invite them",
              "inbox", "unread", "check my email", "check email", "read my email",
              "my emails", "outlook", "new emails", "latest email", "recent email",
              "mail from", "email from", "reply to",
              "compose", "recompose", "draft an email", "draft email", "write an email"],
    "calendar": ["calendar", "my schedule", "my meetings", "free time", "availability",
                 "what meetings", "meeting today", "meeting tomorrow", "meeting this week",
                 "schedule a meeting", "book a meeting", "cancel meeting", "reschedule",
                 "next meeting", "upcoming meeting", "am i free", "when am i free"],
    "teams": ["teams message", "teams chat", "in teams", "on teams", "teams channel",
              "post in teams", "send in teams", "teams conversation",
              "send a message", "send message", "message to",
              "dm him", "dm her", "dm them", "dm to",
              "message him", "message her", "message them",
              "send a dm", "send dm", "chat with", "ping "],
    "slack": ["slack message", "in slack", "on slack", "slack channel",
              "post in slack", "send in slack", "slack conversation"],
    "jira": ["jira", "ticket", "create a ticket", "open a ticket", "jira issue",
             "bug report", "story point", "sprint", "backlog"],
    "confluence": ["confluence", "wiki page", "confluence page", "knowledge base",
                   "write a page", "create a page", "documentation page"],
    "browser": ["@browse", "/browse", "browse to", "open website", "go to website", "visit website",
                "search on google", "open the site", "go to the site",
                "web search", "look up online", "find online",
                "on priceline", "on amazon", "on expedia", "on airbnb",
                "on walmart", "on target", "on ebay", "on etsy", "on bestbuy",
                "on linkedin", "on youtube", "on reddit", "on twitter", "on x.com",
                "on the web", "on google", "on bing",
                "research online", "check the site", "check their site",
                "go to http", "go to https", "go to www",
                "look up http", "look up https", "look up www",
                ".com", ".org", ".net", ".io", ".gov",
                "find on ", "search on ", "buy on ", "shop on ", "price on "],
    "code_runner": [
        "create", "generate", "make me", "build", "script",
        "write code", "run", "produce", "gif", "animated",
        "chart", "plot", "image", "render",
        "what is at", "what's at", "list files", "list folder", "list directory",
        "what files", "what's in", "show me the files", "read file", "open file",
        "local file", "local folder", "local path", "my machine", "my computer",
        "c:\\", "c:/", "/users/", "show directory",
    ],
    "shell_runner": [
        "run command", "terminal", "shell", "powershell", "bash",
        "git ", "npm ", "pip install", "build script", "cmd ",
        "wsl", "run script", "run this script", "run the script",
        "execute", "command line",
    ],
    "file_ops": [
        "read file", "open file", "write file", "save file",
        # "delete file", "delete this file", "delete the file", "remove file",  # deletion not supported
        "list files", "list folder", "list directory",
        "what files", "what's in", "find files", "search files",
        "grep", "glob", "file contents", "local file", "local folder",
    ],
}


def _infer_skills_from_message(message: str) -> list[str]:
    """Scan user message for keywords and return skill IDs to auto-activate."""
    msg_lower = message.lower()
    return [skill_id for skill_id, keywords in _SKILL_KEYWORDS.items()
            if any(kw in msg_lower for kw in keywords)]


# ── LLM-based skill classification (fallback when keywords miss) ──────────

_CLASSIFY_SKILL_IDS = {
    "email":      "Read/send email, check inbox, search Outlook messages",
    "calendar":   "View schedule, check meetings, book/cancel/reschedule meetings, check availability",
    "teams":      "Read/send Teams chats, channels, DMs",
    "slack":      "Read/send Slack messages, channels, DMs",
    "jira":       "Search/create/update Jira tickets, bugs, stories",
    "confluence": "Search/read/create Confluence wiki pages",
    "docx":       "Create, read, edit, or fill out Word documents (.docx) — includes filling forms, charts, templates, or tables in a Word file",
    "excel":      "Create or edit Excel spreadsheets (.xlsx)",
    "ppt":        "Create or edit PowerPoint presentations (.pptx)",
    "onenote":    "Read or create OneNote notebook pages",
    "sharepoint": "Browse SharePoint sites and files",
    "github":     "Interact with GitHub repos, PRs, issues",
    "contacts":   "Look up contact details from address book",
    "browser":     "Open websites, search the web, browse pages, interact with web forms, book flights/hotels online",
    "code_runner": "Write and execute Python code to produce files, images, GIFs, charts, or other output",
    "shell_runner": "Run shell commands (PowerShell, bash/WSL, cmd) — git, npm, build scripts, terminal operations",
    "file_ops":     "Read, write, list, search, and find local files and directories on the user's machine",
}

_CLASSIFY_PROMPT = """You are a skill router. Given a user message, return which skills are needed.

Available skills:
{skills}

Rules:
- Return ONLY a JSON array of skill IDs, e.g. ["email", "calendar"]
- Return [] if the message is general chat requiring no skills
- Be generous: if there's any chance a skill is relevant, include it
- Multiple skills are fine

User message: {message}

JSON array:"""


def _installed_skill_ids_from_message(message: str) -> list[str]:
    """Match message against installed SKILL.md-only skill IDs and display names.

    Runs before the LLM classifier so name mentions always win without a network call.
    Only matches skills that are in SKILL_PROMPTS (installed and loaded).
    """
    from marketplace.installer import load_installed
    msg_lower = message.lower()
    matched = []
    for entry in load_installed():
        sid = entry.get("id", "")
        if not sid or sid not in shared.SKILL_PROMPTS:
            continue
        # Match by skill ID (e.g. "slack-gif-creator") or display name words
        tokens = {sid, sid.replace("-", " ")}
        display = entry.get("display_name", "")
        if display:
            tokens.add(display.lower())
        if any(t in msg_lower for t in tokens):
            matched.append(sid)
    return matched


def _classify_skills_via_llm(message: str, extra_skills: dict | None = None) -> list[str]:
    """Use a fast LLM call to classify which skills a message needs."""
    import re as _re
    try:
        from llm import get_provider
        provider = get_provider()
        all_skills = {**_CLASSIFY_SKILL_IDS, **(extra_skills or {})}
        skills_text = "\n".join(f"- {sid}: {desc}" for sid, desc in all_skills.items())
        prompt = _CLASSIFY_PROMPT.format(skills=skills_text, message=message)

        text = provider.simple_complete(prompt, model="Claude-Haiku-4.5", max_tokens=100)
        # Parse JSON array from response
        match = _re.search(r'\[.*?\]', text)
        if match:
            skills = json.loads(match.group())
            result = [s for s in skills if isinstance(s, str) and s in all_skills]
            print(f"[skill-classify] LLM raw='{text}' -> {result}", flush=True)
            return result
        print(f"[skill-classify] LLM returned no JSON array: '{text}'", flush=True)
    except Exception as exc:
        print(f"[skill-classify] LLM classification failed: {exc}", flush=True)
    return []


# ── Chat stream + cancel endpoints ───────────────────────────────────────────

@router.get("/api/chat/stream/{task_id}")
async def chat_stream(task_id: str, request: Request):
    """SSE stream for a running chat task. Supports Last-Event-ID reconnect/replay."""
    from_seq = 0
    last_event_id = request.headers.get("Last-Event-ID", "")
    if last_event_id:
        try:
            from_seq = int(last_event_id) + 1
        except ValueError:
            pass

    async def _gen():
        import asyncio as _asyncio

        # Subscribe FIRST to avoid the race where mark_done fires between
        # replay and subscribe (which would mean __DONE__ is never delivered).
        q = shared.chat_task_store.subscribe(task_id)

        try:
            # Replay already-buffered chunks (handles reconnect)
            seq = from_seq
            for chunk in shared.chat_task_store.get_chunks(task_id, from_seq=seq):
                if chunk == "data: [DONE]\n\n":
                    yield "data: [DONE]\n\n"
                    return
                yield f"id: {seq}\n{chunk}"
                seq += 1

            # If task finished during/before replay, drain any remaining and close.
            # The subscribe above ensures we haven't missed any __DONE__ signals.
            if q is None or shared.chat_task_store.is_done(task_id):
                # Drain anything appended after our replay snapshot
                for chunk in shared.chat_task_store.get_chunks(task_id, from_seq=seq):
                    if chunk != "data: [DONE]\n\n":
                        yield f"id: {seq}\n{chunk}"
                        seq += 1
                yield "data: [DONE]\n\n"
                return

            while True:
                try:
                    chunk = await _asyncio.wait_for(q.get(), timeout=15.0)
                except _asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue

                if chunk == "__DONE__":
                    # Drain any chunks appended after subscribe (race guard)
                    for c in shared.chat_task_store.get_chunks(task_id, from_seq=seq):
                        if c != "data: [DONE]\n\n":
                            yield f"id: {seq}\n{c}"
                            seq += 1
                    yield "data: [DONE]\n\n"
                    return

                yield f"id: {seq}\n{chunk}"
                seq += 1
        finally:
            shared.chat_task_store.unsubscribe(task_id, q)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/chat/{task_id}/cancel")
async def cancel_chat(task_id: str):
    """Cancel a running chat task."""
    cancelled = shared.chat_task_store.cancel(task_id)
    return {"cancelled": cancelled}


# ── Chat Endpoint ─────────────────────────────────────────────────────────────

@router.post("/api/chat")
async def chat(req: ChatRequest):
    import uuid as _uuid
    import asyncio as _asyncio
    from fastapi.responses import JSONResponse
    from llm import get_provider, get_active_model
    from routes.config_routes import _get_active_persona_prompt
    # Import execute_tool and _tool_toast from the app module (they stay in app.py
    # because they are also used by the lifespan background worker).
    from app import execute_tool, _tool_toast

    # Check for /plugin:capability slash command prefix
    slash_cmd = None
    raw_message = req.message if isinstance(req.message, str) else ""
    if raw_message:
        slash_cmd = parse_slash_command(raw_message)
    if slash_cmd:
        # Validate the plugin name against the registry. SKILL_PROMPTS is
        # populated for every built-in skill AND every installed plugin (synced
        # from INSTALLED_SKILLS_DIR). If the user types `/notinstalled:thing`,
        # log a warning so the silent no-op shows up in logs/server.log instead
        # of leaving the user staring at a confusing empty response.
        if slash_cmd["plugin"] not in shared.SKILL_PROMPTS:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "Slash command targets unknown plugin %r — message will reach the "
                "LLM with active_skill set to a non-existent skill",
                slash_cmd["plugin"],
            )
        # Override active_skill to the named plugin; rewrite message to strip the
        # prefix. Empty trailing text means "open capability with no argument" —
        # keep message as "" rather than falling back to the raw prefixed string,
        # which would leak `/plugin:capability` into the LLM prompt verbatim.
        req = req.model_copy(update={
            "active_skill": slash_cmd["plugin"],
            "message": slash_cmd["message"],
        })

    # ── Permission gate: block gated dependency skills that haven't been approved ──
    if req.unapproved_deps and req.active_skill:
        _all_deps = shared.SKILL_DEPENDENCIES_MAP.get(req.active_skill, [])
        _blocked_deps = [
            d for d in _all_deps
            if d["id"] in req.unapproved_deps and d["id"] in _GATED_DEP_SKILLS
        ]
        if _blocked_deps:
            def _resolve_dep_label(dep_id: str) -> str:
                prompt_text = shared.SKILL_PROMPTS.get(dep_id, "")
                for _line in prompt_text.splitlines():
                    if _line.startswith("# "):
                        return _line[2:].strip()
                return dep_id.replace("-", " ").title()

            _deps_payload = [
                {"id": d["id"], "label": _resolve_dep_label(d["id"]), "reason": d["reason"]}
                for d in _blocked_deps
            ]

            _gate_task_id = str(_uuid.uuid4())
            _gate_context_id = getattr(req, "context_id", None) or "default"
            shared.chat_task_store.create_task(_gate_task_id, _gate_context_id)

            _perm_chunk = f"data: {json.dumps({'type': 'permission_required', 'skill': req.active_skill, 'deps': _deps_payload})}\n\n"

            async def _run_permission_gate():
                try:
                    shared.chat_task_store.append_chunk(_gate_task_id, _perm_chunk)
                    shared.chat_task_store.append_chunk(_gate_task_id, "data: [DONE]\n\n")
                finally:
                    shared.chat_task_store.mark_done(_gate_task_id)

            _gate_bg = _asyncio.create_task(_run_permission_gate())
            shared.chat_task_store.track_task(_gate_bg)
            return JSONResponse({"task_id": _gate_task_id})

    _now = datetime.now()
    system = shared.get_system_prompt().replace("{date}", _now.strftime("%B %d, %Y")).replace(
        "{unix_ts}", str(int(_now.timestamp()))
    )

    # Prepend active persona prompt
    _persona_prompt = _get_active_persona_prompt()
    if _persona_prompt:
        system = _persona_prompt + "\n\n" + system

    # Inject per-skill prompt instructions — ONLY for explicitly active skills,
    # NOT all always-on skills (those add 10K+ tokens of irrelevant context).
    # Auto-detected skills get their prompts injected later (line ~326).
    _active_sids = set()
    if req.active_skill and req.active_skill in shared.SKILL_PROMPTS:
        _active_sids.add(req.active_skill)
    for _sid in (req.active_skills or []):
        if _sid in shared.SKILL_PROMPTS:
            _active_sids.add(_sid)

    # Include SKILL.md prompts for dependency skills
    for _primary_sid in list(_active_sids):
        for _dep in shared.SKILL_DEPENDENCIES_MAP.get(_primary_sid, []):
            _dep_id = _dep["id"]
            if _dep_id in shared.SKILL_PROMPTS and _dep_id not in _active_sids:
                _active_sids.add(_dep_id)

    for _sid in sorted(_active_sids):
        system += "\n\n" + shared.SKILL_PROMPTS[_sid]
        print(f"[skill-prompt] injected SKILL.md for '{_sid}' ({len(shared.SKILL_PROMPTS[_sid])} chars) [explicit]", flush=True)

    if req.has_images:
        system += "\n\nThe user has uploaded image(s) in this message. Analyze them visually. Use the describe_images tool to signal your intent (describe, compare, extract_data, or assess), then provide detailed visual analysis in your text response."
        # Issue #12 — surface filename & saved path so the AI can locate the image on disk
        # (e.g. when asked to attach it to a GitHub issue, upload to OneDrive, etc.)
        if req.image_paths:
            _pairs = []
            for i, p in enumerate(req.image_paths):
                _nm = (req.image_names or [])[i] if i < len(req.image_names or []) else ""
                _pairs.append(f"  - {_nm or 'image'} → {p}")
            system += "\n\n📎 UPLOADED IMAGE FILE PATHS (use these EXACT paths when you need to read/attach the image file — do NOT search temp folders):\n" + "\n".join(_pairs)
        elif req.image_names:
            system += "\n\n📎 Uploaded image filename(s): " + ", ".join(req.image_names) + ". If you need the file path, search ~/Pictures/Screenshots/ first, then ~/Downloads/, then AppData/Local/Temp (match by name, recency, dimensions)."

    # Inject active channel/groupchat context so Claude can call the right tool directly
    if req.active_channels:
        team_channels = [c for c in req.active_channels if c.get("type") != "groupchat" and c.get("channel_id")]
        group_chats = [c for c in req.active_channels if c.get("type") == "groupchat" or not c.get("channel_id")]
        if team_channels:
            ch_lines = "\n".join(
                f"- #{c.get('channel_name','')} (team: {c.get('team_name','')}, team_id: {c.get('team_id','')}, channel_id: {c.get('channel_id','')})"
                for c in team_channels
            )
            system += f"\n\n\U0001f4e2 ACTIVE CHANNELS (user mentioned these with #): call read_channel_messages with the team_id and channel_id below - do NOT ask the user for IDs:\n{ch_lines}"
        if group_chats:
            gc_lines = "\n".join(
                f"- #{c['channel_name']} (chat_id: {c.get('chat_id', '')})"
                for c in group_chats
            )
            system += f"\n\n\U0001f4ac ACTIVE GROUP CHATS (user mentioned these with #): call read_teams_chats with filter_topic matching the chat name below:\n{gc_lines}"

    # Inject which skills are currently loaded — Claude must never tell the user
    # to load a skill that is already active.
    _SKILL_LABELS = {
        "teams":       "Teams (read/send chats, channels, DMs)",
        "email":       "Email/Outlook (read/send email, search inbox)",
        "calendar":    "Calendar (read events, schedule meetings, check availability)",
        "jira":        "Jira (search/create/update tickets)",
        "onenote":     "OneNote (read/create/update notebook pages)",
        "onedrive":    "OneDrive (list/search/upload files)",
        "sharepoint":  "SharePoint (browse sites and files)",
        "confluence":  "Confluence (search/read pages)",
        "slack":       "Slack (search channels/threads via MCP \u2014 NO token, no auth, no Settings page)",
        "gator":       "Gator (general AI assistant \u2014 no workspace tools)",
    }
    _explicit_skill_ids: set[str] = set()
    if req.active_skill:
        _explicit_skill_ids.add(req.active_skill)
    for _sid in (req.active_skills or []):
        _explicit_skill_ids.add(_sid)
    if _explicit_skill_ids:
        skill_lines = "\n".join(
            f"  \u2022 {_SKILL_LABELS.get(sid, sid)}"
            for sid in sorted(_explicit_skill_ids)
            if sid != "gator"
        )
        if skill_lines:
            system += (
                f"\n\n\U0001f7e2 ACTIVE SKILLS \u2014 you have these tools available RIGHT NOW. "
                f"Use them proactively without asking the user to load anything:\n{skill_lines}\n"
                f"NEVER tell the user to load a skill that appears in this list. "
                f"If the user references data from an active skill (e.g. 'my conversation with X' when /teams is active), "
                f"call the relevant tool immediately to fetch it \u2014 do NOT say you don't have access."
            )

    # Inject pinned context (universal — OneDrive, OneNote, etc.)
    from skills.context.state import get_pins as _get_pins
    _context_id = getattr(req, 'context_id', 'default') or 'default'
    _pins = _get_pins(_context_id)
    if _pins:
        _pin_lines = []
        for p in _pins:
            s, pid, lbl, m = p["source"], p["id"], p["label"], p.get("meta", {})
            if s == "onenote":
                _pin_lines.append(f"- OneNote: \"{lbl}\" (page_id: {pid}, notebook: {m.get('notebook','?')}, section: {m.get('section','?')}) \u2192 use update_onenote_page or read with this page_id")
            elif s == "onedrive":
                _pin_lines.append(f"- OneDrive: \"{lbl}\" (file_id: {pid}, path: {m.get('file_path','?')}) \u2192 use read_onedrive_file(file_id={pid})")
            elif s == "teams":
                _pin_lines.append(f"- Teams chat: \"{lbl}\" (chat_id: {pid}) \u2192 use read_teams_chats to get messages from this conversation")
            elif s == "email":
                _pin_lines.append(f"- Email: \"{lbl}\" (message_id: {pid}, from: {m.get('from','?')}) \u2192 this email is pinned for reference")
            elif s == "slack":
                _type = m.get('type', 'channel')
                if _type == 'thread':
                    _ch_id = pid.split(':')[0] if ':' in pid else pid
                    _msg_ts = m.get('message_ts', pid.split(':')[1] if ':' in pid else '')
                    _pin_lines.append(f"- Slack thread: \"{lbl}\" (channel_id: {_ch_id}, message_ts: \"{_msg_ts}\", channel: {m.get('channel','?')}) \u2192 use slack_read_thread(channel_id=\"{_ch_id}\", message_ts=\"{_msg_ts}\") to read this thread")
                else:
                    _pin_lines.append(f"- Slack channel: \"{lbl}\" (channel_id: {pid}) \u2192 use slack_read_channel with this channel_id")
            elif s == "jira":
                _pin_lines.append(f"- Jira: \"{lbl}\" (key: {pid}) \u2192 use jira_get_issue to read this ticket")
            elif s == "word":
                _mode = m.get("mode", "open")
                if _mode == "open":
                    _pin_lines.append(f'- Word: "{lbl}" \u2192 use file_path="open" for all docx tools (get_docx_info, read_docx, update_docx). The user has Word open \u2014 target the active document via COM.')
                else:
                    _pin_lines.append(f'- Word: "{lbl}" \u2192 use create_docx to create a new document. Ask the user for a save location first.')
            elif s == "excel":
                _mode = m.get("mode", "open")
                if _mode == "open":
                    _pin_lines.append(f'- Excel: "{lbl}" \u2192 use file_path="open" for all excel tools (get_excel_info, read_excel, update_excel). The user has Excel open \u2014 target the active workbook via COM.')
                else:
                    _pin_lines.append(f'- Excel: "{lbl}" \u2192 use create_excel to create a new workbook. Ask the user for a save location first.')
            elif s == "ppt":
                _mode = m.get("mode", "open")
                if _mode == "open":
                    _pin_lines.append(f'- PowerPoint: "{lbl}" \u2192 use file_path="open" for all pptx tools (get_pptx_info, read_pptx, update_pptx). The user has PowerPoint open \u2014 target the active presentation via COM.')
                else:
                    _pin_lines.append(f'- PowerPoint: "{lbl}" \u2192 use create_pptx to create a new presentation. Ask the user for a save location first.')
            elif s == "teams_transcript":
                _dur = m.get("duration_min", 0)
                _spk = m.get("speaker_count", 0)
                _size = int(m.get("size_tokens_estimate") or 0)
                # Pin id format: "{drive_id}:{item_id}:{transcript_id}".
                # drive_id / item_id / transcript_id never contain ':' in practice.
                _parts = pid.split(":", 2)
                if len(_parts) != 3:
                    _pin_lines.append(f"- teams_transcript: \"{lbl}\" (id: {pid}) \u2014 malformed pin id, skipping")
                    continue
                _did, _iid, _tid = _parts
                _args = (
                    f"drive_id=\"{_did}\", item_id=\"{_iid}\", transcript_id=\"{_tid}\""
                )
                # FULL_FETCH_TOKEN_THRESHOLD mirrors transcript_config.py default (50_000).
                # Kept inline to avoid pulling the skills module into the chat route.
                _TX_THRESHOLD = 50_000
                if _size and _size <= _TX_THRESHOLD:
                    _guidance = (
                        f"\u2192 use get_meeting_transcript_full({_args}) for the full body."
                    )
                else:
                    _guidance = (
                        f"\u2192 call get_meeting_transcript_header({_args}) FIRST, then "
                        f"get_meeting_transcript_range, search_meeting_transcript, or "
                        f"get_meeting_transcript_speaker as needed. Transcript exceeds "
                        f"{_TX_THRESHOLD} tokens \u2014 do NOT request the full body in one call."
                    )
                _size_str = f"~{_size}" if _size else "?"
                _pin_lines.append(
                    f"- Teams meeting transcript: \"{lbl}\" "
                    f"({_dur} min, {_spk} speakers, {_size_str} tokens) {_guidance}"
                )
            else:
                _pin_lines.append(f"- {s}: \"{lbl}\" (id: {pid})")
        system += (
            f"\n\n\U0001f4cc PINNED CONTEXT ({len(_pin_lines)} item{'s' if len(_pin_lines) != 1 else ''}):\n" + "\n".join(_pin_lines)
            + "\n\nIMPORTANT: If you already read/fetched a pinned item earlier in this conversation, "
            "do NOT re-read it. The content is already in the conversation history. "
            "Only re-read if the user explicitly asks you to refresh or re-read it."
        )
    # Legacy: keep OneNote state in sync for tools that read it directly,
    # but ONLY inject into prompt if this is the default context (no tabs)
    # to prevent pin bleed across tabs.
    if _context_id == 'default' and not _pins:
        from skills.onenote.state import pinned_onenote_pages as _pinned_onenote_pages
        if _pinned_onenote_pages:
            pins = "\n".join(f"- \"{p['title']}\" (page_id: {p['page_id']}, notebook: {p.get('notebook','?')}, section: {p.get('section','?')})"
                             for p in _pinned_onenote_pages.values())
            system += f"\n\n\U0001f4cc PINNED ONENOTE PAGES (use update_onenote_page with these page_ids directly \u2014 no need to re-navigate):\n{pins}"

    # Auto-detect skills needed from pinned items — no manual chip required
    _source_skill_map = {"word": "docx", "excel": "excel", "ppt": "ppt"}
    _pin_skills = list({_source_skill_map.get(p["source"], p["source"]) for p in _pins}) if _pins else []

    # Auto-detect skills from user message: keywords first (fast), LLM fallback (smart)
    # When message has file attachments, req.message is a list of content blocks — extract text.
    if isinstance(req.message, str):
        _msg_text = req.message
    elif isinstance(req.message, list):
        _msg_text = " ".join(
            b.get("text", "") if isinstance(b, dict) else (b.text if hasattr(b, "text") else "")
            for b in req.message
        )
    else:
        _msg_text = ""

    # ── Continuation classifier: runs before skill detection ────────────────
    from continuation_classifier import classify as _classify, detect_pending as _detect_pending
    _tab_state = shared.task_state_store.get(_context_id)
    _clf = _classify(_msg_text, _tab_state)
    print(f"[classifier] mode={_clf.mode} reason={_clf.reason}", flush=True)
    _classifier_inherited = False
    if _clf.mode in ("confirmation", "data_input", "inherit") and _tab_state and _tab_state.active_skills:
        # Bypass skill detection — inherit the stored skill set
        _inferred = list(_tab_state.active_skills)
        _classifier_inherited = True
        if _clf.resolved_pending:
            shared.task_state_store.update(_context_id, pending=None)
        print(f"[classifier] inheriting skills {_inferred} (bypassing keyword/LLM detection)", flush=True)

    if not _classifier_inherited:
        _inferred = _infer_skills_from_message(_msg_text)
        # Also match installed marketplace skills by name (handles skills absent from static dicts)
        _installed_matches = _installed_skill_ids_from_message(_msg_text)
        if _installed_matches:
            _inferred = list(set(_inferred) | set(_installed_matches))
        if _inferred:
            print(f"[skill-detect] keywords/installed matched: {_inferred}", flush=True)
        if not _inferred and _msg_text.strip():
            # No keywords matched — ask the LLM regardless of explicit skill chips,
            # because the user may have email selected but be asking about calendar
            print(f"[skill-detect] no keywords, calling LLM classifier...", flush=True)
            from marketplace.installer import load_installed as _load_installed
            _extra = {
                e["id"]: e.get("display_name", e["id"])
                for e in _load_installed()
                if e.get("id") in shared.SKILL_PROMPTS
            }
            _inferred = _classify_skills_via_llm(_msg_text, extra_skills=_extra or None)
        if _inferred:
            print(f"[skill-detect] final inferred skills: {_inferred}", flush=True)

        # Carry forward skills from recent history when the current message gives no signal
        # (e.g. "go ahead", "yes", "looks good", "try again"). The frontend stores only text
        # in history (no tool_use blocks), so scan the recent text for skill keywords.
        if not _inferred:
            def _extract_text(content):
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    return " ".join(
                        b.get("text", "") if isinstance(b, dict) and b.get("type") == "text" else ""
                        for b in content
                    )
                return ""
            _recent_text = " ".join(
                _extract_text(m.get("content", ""))
                for m in req.history[-6:]
            ).lower()
            _history_skills = [
                sid for sid, kws in _SKILL_KEYWORDS.items()
                if any(kw in _recent_text for kw in kws)
            ]
            # Only carry forward skills not already explicit (avoid double-loading)
            _carried = [s for s in _history_skills if s not in _explicit_skill_ids]
            if _carried:
                print(f"[skill-detect] carrying forward from history text: {_carried}", flush=True)
                _inferred = _carried

    # Separate context-only skills (auto-detected) from explicitly selected skills
    _context_only_skills = list(set(_pin_skills + _inferred) - _explicit_skill_ids)

    # Exclude 'gator' from tool filtering — it's the default home skill, not a toolset.
    # Its manifest bundles 14 Office tools (Excel/Word/PPT) that shouldn't load on every request.
    _explicit_no_gator = [s for s in (req.active_skills or []) if s != 'gator']
    _active_skill_no_gator = req.active_skill if req.active_skill != 'gator' else None
    _all_active = list(set(_explicit_no_gator + _pin_skills + _inferred))
    active_tools = _filter_tools(_active_skill_no_gator, req.has_images, _all_active,
                                  unapproved_deps=req.unapproved_deps)
    print(f"[tokens] active_skill={req.active_skill} inferred={_inferred} -> {len(active_tools)} tools (of {len(shared.TOOLS)} total)", flush=True)

    # Inject skill prompts for auto-detected skills (pins + keywords) that weren't
    # already injected in the explicit/always-on pass above.
    for _sid in sorted(set(_pin_skills + _inferred) - _active_sids):
        if _sid in shared.SKILL_PROMPTS:
            system += "\n\n" + shared.SKILL_PROMPTS[_sid]
            print(f"[skill-prompt] injected SKILL.md for '{_sid}' ({len(shared.SKILL_PROMPTS[_sid])} chars)", flush=True)

    if _context_only_skills:
        ctx_labels = ", ".join(sorted(_SKILL_LABELS.get(s, s) for s in _context_only_skills))
        system += (
            f"\n\n\U0001f535 CONTEXT SKILLS (auto-detected, NOT explicitly selected by user): {ctx_labels}\n"
            f"These tools are available because the user is viewing related content (e.g. a Teams tab is open, "
            f"or a pinned item references this skill). They provide CONTEXT ONLY.\n"
            f"IMPORTANT: Do NOT proactively read chats, fetch data, draft messages, or suggest follow-up actions "
            f"for context skills unless the user EXPLICITLY asks you to act on them. "
            f"Answer the user's question directly first. Only use context skill tools when the user's request "
            f"clearly requires it (e.g. 'read that chat', 'send a message', 'summarize the thread').\n"
            f"NEVER tell the user to 'load a skill' or 'click /skillname' \u2014 if the tools are available, use them directly."
        )

    # Universal rule: never ask the user to load skills — tools are auto-managed
    system += (
        "\n\nIf you need a skill that is not currently active, simply name it as `/skillname` in your response "
        "(e.g. `/outlook`, `/teams`) — the server auto-activates it and you'll get a second chance to use its tools. "
        "Do NOT tell the user to 'click' or 'load' a skill; the activation is automatic. "
        "If the requested skill cannot be found, the original response will be shown."
    )

    context_id = getattr(req, "context_id", None) or "default"

    async def stream():
        import json as _json
        from agent_loop import _single_agent_loop, run_three_agent_loop
        from task_queue import log_usage
        from skill_router import match_intent, execute_direct
        model = req.model or get_active_model()
        provider = get_provider(model)
        print(f"[chat] req.model={req.model!r} resolved={model!r} provider={type(provider).__name__} history_turns={len(req.history)}", flush=True)
        cfg = _load_config()
        _msg_text_raw = req.message if isinstance(req.message, str) else ""
        # Seed store from browser history on first message (backward compat)
        if req.history and not shared.conversation_store.has(context_id):
            await shared.conversation_store.seed(context_id, req.history)
        history_window = await shared.conversation_store.get_window(context_id)
        msgs = history_window + [{"role": "user", "content": req.message}]
        token_budget = int(cfg.get("token_budget_per_task", 0) or 0)
        use_three_agent = cfg.get("three_agent_mode", False)
        _in_tok, _out_tok = 0, 0

        # ── HITL course-correction: if browser is paused, forward message as guidance ──
        from browser_agent import is_browser_active, is_browser_paused, send_hitl_guidance
        if is_browser_active() and is_browser_paused() and _msg_text_raw.strip():
            accepted = send_hitl_guidance(_msg_text_raw)
            if accepted:
                yield f"data: {_json.dumps({'status': 'Sending correction to browser agent...'})}\n\n"
                yield f"data: {_json.dumps({'text': f'Got it — adjusting the search: *{_msg_text_raw}*'})}\n\n"
                yield "data: [DONE]\n\n"
                return

        # ── Skill Router: try direct dispatch first ──────────────
        intent = match_intent(_msg_text_raw)
        if intent:
            is_browser = intent.get("tool", "").startswith("browser")
            yield f"data: {_json.dumps({'status': '⚡ ' + intent['tool'] + '...'})}\n\n"

            if is_browser:
                # Browser tasks: run in background, browser pane streams screenshots via /api/browser/stream
                yield f"data: {_json.dumps({'browser_hitl': 'active'})}\n\n"
                import asyncio as _aio
                _browser_task = _aio.ensure_future(
                    execute_direct(intent, execute_tool, user_message=_msg_text_raw)
                )
                # Wait for completion — screenshots handled by /api/browser/stream SSE
                while not _browser_task.done():
                    try:
                        await _aio.wait_for(_aio.shield(_browser_task), timeout=3)
                    except _aio.TimeoutError:
                        pass  # Keep waiting — browser pane handles live updates
                direct = _browser_task.result()
                yield f"data: {_json.dumps({'browser_hitl': 'done'})}\n\n"
            else:
                # Non-browser direct intents: run normally (fast, no streaming needed)
                direct = await execute_direct(intent, execute_tool, user_message=_msg_text_raw)

            if direct.get("ok"):
                # ONE LLM call with pre-fetched data, NO tools
                data_summary = _json.dumps(direct["data"], default=str)
                if len(data_summary) > 8000:
                    data_summary = data_summary[:8000] + "\n... (truncated)"
                routed_system = system + "\n\nYou have the data below. Summarize it directly for the user. Do NOT call any tools — the data is already fetched."
                routed_msgs = [{"role": "user", "content": f"{_msg_text_raw}\n\n[Data from {intent['tool']}]:\n{data_summary}"}]
                print(f"[skill-router] DIRECT PATH: {intent['tool']} -> 1 LLM call, 0 tools", flush=True)
                loop = _single_agent_loop(
                    provider=provider, model=model, system=routed_system,
                    msgs=routed_msgs, normalized_tools=[],
                    execute_tool=execute_tool, COM_BOUND_TOOLS=shared.COM_BOUND_TOOLS,
                    TOOL_STATUS=shared.TOOL_STATUS, _tool_toast=_tool_toast,
                    _SLACK_SAFE_MSG=shared._SLACK_SAFE_MSG,
                )
                async for chunk in loop:
                    if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
                        try:
                            _m = _json.loads(chunk[6:])
                            if "usage" in _m:
                                _in_tok = _m["usage"].get("input_tokens", 0)
                                _out_tok = _m["usage"].get("output_tokens", 0)
                        except Exception:
                            pass
                    yield chunk
                if _in_tok or _out_tok:
                    try:
                        await log_usage("chat-direct", _msg_text_raw[:100], _in_tok, _out_tok)
                    except Exception:
                        pass
                return

        # ── Standard path: LLM picks tools ───────────────────────
        def _build_loop(tools_list, sys_text, message_list):
            norm = [provider.normalize_tool_schema(t) for t in tools_list]
            if use_three_agent:
                return run_three_agent_loop(
                    provider=provider, model=model, system=sys_text, msgs=message_list,
                    normalized_tools=norm, execute_tool=execute_tool,
                    COM_BOUND_TOOLS=shared.COM_BOUND_TOOLS, TOOL_STATUS=shared.TOOL_STATUS,
                    _tool_toast=_tool_toast, _SLACK_SAFE_MSG=shared._SLACK_SAFE_MSG,
                    token_budget=token_budget,
                )
            return _single_agent_loop(
                provider=provider, model=model, system=sys_text, msgs=message_list,
                normalized_tools=norm, execute_tool=execute_tool,
                COM_BOUND_TOOLS=shared.COM_BOUND_TOOLS, TOOL_STATUS=shared.TOOL_STATUS,
                _tool_toast=_tool_toast, _SLACK_SAFE_MSG=shared._SLACK_SAFE_MSG,
            )

        _current_loop = _build_loop(active_tools, system, msgs)
        _current_system = system
        _current_msgs = msgs
        _assistant_text_parts: list[str] = []
        _retry_count = 0
        _MAX_AUTO_ACTIVATE_RETRIES = 1

        while True:
            _turn_text_parts: list[str] = []
            _done_chunk = None
            async for chunk in _current_loop:
                # Capture usage for logging
                if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
                    try:
                        _m = _json.loads(chunk[6:])
                        if "usage" in _m:
                            _in_tok = _m["usage"].get("input_tokens", 0)
                            _out_tok = _m["usage"].get("output_tokens", 0)
                        elif "token" in _m:
                            _turn_text_parts.append(_m["token"])
                            _assistant_text_parts.append(_m["token"])
                    except Exception:
                        pass
                if chunk.startswith("data: [DONE]"):
                    _done_chunk = chunk
                    break
                yield chunk

            # Detect "please activate /skillname" in the just-completed turn and auto-retry
            _new_skill = None
            if _retry_count < _MAX_AUTO_ACTIVATE_RETRIES and not use_three_agent:
                _turn_text = "".join(_turn_text_parts)
                _match = _SKILL_REQUEST_RE.search(_turn_text)
                if _match:
                    _sid = _match.group(1).lower()
                    if _sid in shared.SKILL_PROMPTS and _sid not in _all_active:
                        _new_skill = _sid

            if not _new_skill:
                if _done_chunk:
                    yield _done_chunk
                break

            # Auto-activate the requested skill and re-run the loop with expanded tools
            _all_active.append(_new_skill)
            _new_tools = _filter_tools(_active_skill_no_gator, req.has_images, _all_active,
                                       unapproved_deps=req.unapproved_deps)
            _new_system = _current_system + "\n\n" + shared.SKILL_PROMPTS[_new_skill]
            _new_msgs = list(_current_msgs) + [
                {"role": "assistant", "content": "".join(_turn_text_parts) or "[continuing]"},
                {"role": "user", "content": (
                    f"[System: Skill '/{_new_skill}' has just been auto-activated and its tools are now available. "
                    f"Continue the user's original request using these new tools — do NOT ask them to activate anything."
                )},
            ]
            shared.notify_all({"type": "skill_auto_activated", "skill_id": _new_skill})
            yield f"data: {_json.dumps({'status': f'⚡ Auto-activating /{_new_skill}...'})}\n\n"
            yield f"data: {_json.dumps({'token': f'\n\n*→ Auto-activated `/{_new_skill}`, continuing…*\n\n'})}\n\n"
            print(f"[skill-auto-activate] '{_new_skill}' added mid-stream, retrying with {len(_new_tools)} tools", flush=True)
            _current_loop = _build_loop(_new_tools, _new_system, _new_msgs)
            _current_system = _new_system
            _current_msgs = _new_msgs
            _retry_count += 1

        # Post-turn: update task state with active skills + detect new pending state
        _all_active_skills = list(set(_explicit_skill_ids) | set(_inferred))
        if _all_active_skills:
            _turn_index = len(msgs)
            _assistant_text = "".join(_assistant_text_parts)
            _new_pending = _detect_pending(_assistant_text, _turn_index) if _assistant_text else None
            # Compute confidence: explicit > inferred, more skills = lower per-skill confidence
            _confidence = 0.90 if _explicit_skill_ids else (0.80 if _inferred else 0.0)
            shared.task_state_store.update(
                context_id,
                active_skills=_all_active_skills,
                pending=_new_pending,
                confidence=_confidence,
            )
            print(f"[classifier] state updated: skills={_all_active_skills} pending={_new_pending} conf={_confidence}", flush=True)
        else:
            shared.task_state_store.decay(context_id)

        # Persist new turns to server-side conversation store
        new_turns = msgs[len(history_window):]
        if new_turns:
            await shared.conversation_store.append(context_id, new_turns)

        # Log usage after stream completes
        if _in_tok or _out_tok:
            _prompt = req.message if isinstance(req.message, str) else ""
            try:
                await log_usage("chat", _prompt[:100], _in_tok, _out_tok)
            except Exception:
                pass

        # Notify other tabs that this tab's request is done
        shared.notify_all({"type": "chat_done", "context_id": context_id})

    task_id = str(_uuid.uuid4())
    shared.chat_task_store.create_task(task_id, context_id)

    async def _run_and_buffer():
        try:
            async for chunk in stream():
                if shared.chat_task_store.is_cancelled(task_id):
                    break
                shared.chat_task_store.append_chunk(task_id, chunk)
                # Backup delivery: forward pane/draft signals via notification
                # stream so they arrive even if the chat SSE connection drops.
                # Frontend dedup prevents double-processing.
                if chunk.startswith("data: ") and ('"pane"' in chunk or '"draft"' in chunk):
                    try:
                        _sig = json.loads(chunk[6:])
                        if "pane" in _sig:
                            shared.notify_all({"type": "pane_signal", "pane": _sig["pane"], "paneData": _sig.get("paneData", {})})
                        elif "draft" in _sig:
                            shared.notify_all({"type": "draft_signal", "draft": _sig["draft"], "draftData": _sig.get("draftData", {})})
                    except Exception:
                        pass
        except Exception as _exc:
            import traceback as _tb
            print(f"[stream] unhandled error in background task: {_exc}", flush=True)
            _tb.print_exc()
            shared.chat_task_store.append_chunk(task_id, f"data: {json.dumps({'text': 'An unexpected error occurred. Please try again.'})}\n\n")
            shared.chat_task_store.append_chunk(task_id, "data: [DONE]\n\n")
        finally:
            shared.chat_task_store.mark_done(task_id)

    _bg_task = _asyncio.create_task(_run_and_buffer())
    shared.chat_task_store.track_task(_bg_task)  # prevent GC from cancelling the task
    return JSONResponse({"task_id": task_id})
