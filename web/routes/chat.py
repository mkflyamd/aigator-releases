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
    # Bare token: /jira or /outlook alone on a line (what the model now emits)
    r"^/([a-z0-9][a-z0-9_-]*)$"
    # Legacy verbose form: "activate the jira skill"
    r"|(?:add|activate|enable|load|use)\s+(?:the\s+)?[`'\"]?[@/]?([a-z0-9][a-z0-9_-]*)[`'\"]?\s+skill",
    _re.IGNORECASE | _re.MULTILINE,
)

# Map user-facing skill names to internal IDs for the auto-activate fallback.
# Keep this minimal — the only cases where UI label diverges from skill ID.
_SKILL_NAME_ALIASES = {
    "outlook": "email",
    "calendar": "m365-calendar",
}


def _resolve_skill_id(name: str) -> str:
    """Normalize a user-facing skill name to its internal skill id.

    Lowercases and applies _SKILL_NAME_ALIASES. Used by BOTH the explicit
    /plugin:capability slash-command path and the auto-activate fallback so a
    name like 'outlook' resolves to 'email' in both — otherwise the slash path
    yields an id absent from SKILL_PROMPTS/SKILL_TOOLS_MAP and exposes no tools (#40).
    """
    key = (name or "").lower()
    return _SKILL_NAME_ALIASES.get(key, key)


def _detect_requested_skills(turn_text: str, already_active) -> list[str]:
    """Collect every valid, not-yet-active skill id named in a model turn.

    A single turn can name several skills it needs (the #70 repro needs both
    /jira and /outlook). Returns them in first-seen order, resolved to internal
    ids, de-duplicated, and filtered to known (in SKILL_PROMPTS) and inactive —
    so the retry loop can activate them all at once instead of only the first
    `.search()` match.

    Gated skills (shell_runner/code_runner) are NEVER auto-activated here: they
    expose powerful tools and must go through the explicit user-approval gate, so
    a model that merely names `/code_runner` mid-turn cannot self-grant them.
    """
    active = set(already_active or [])
    found: list[str] = []
    for m in _SKILL_REQUEST_RE.finditer(turn_text or ""):
        sid = _resolve_skill_id(m.group(1) or m.group(2) or "")
        # Accept a skill if it has a prompt (built-in / installed) OR has tools
        # registered (MCP connections have tools in SKILL_TOOLS_MAP but no
        # SKILL.md prompt). Gated skills still excluded — they require the
        # explicit user-approval gate and can't be self-granted by the model.
        _known = sid in shared.SKILL_PROMPTS or sid in shared.SKILL_TOOLS_MAP
        if (_known and sid not in _GATED_DEP_SKILLS
                and sid not in active and sid not in found):
            found.append(sid)
    return found


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
    system_prompt_suffix: str | None = None   # extra rules appended to system prompt (e.g. wizard scope)
    scoped_skill: str | None = None           # skill ID injected into active_skills for this request


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
              "email them", "email me", "email us", "send me", "send an email",
              "invite him", "invite her", "invite them",
              "inbox", "unread", "check my email", "check email", "read my email",
              "my emails", "new emails", "latest email", "recent email",
              "mail from", "email from", "reply to",
              "compose", "recompose", "draft an email", "draft email", "write an email"],
    "m365-calendar": ["calendar", "my schedule", "my meetings", "free time", "availability",
                 "what meetings", "meeting today", "meeting tomorrow", "meeting this week",
                 "schedule a meeting", "book a meeting", "cancel meeting", "reschedule",
                 "next meeting", "upcoming meeting", "am i free", "when am i free",
                 "invite on my outlook", "invite on outlook", "what is the", "what's the",
                 "am invite", "pm invite", "morning invite", "afternoon invite",
                 "what is my", "what's on my", "on my calendar", "on my outlook",
                 "my invite", "the invite", "the meeting invite", "calendar invite",
                 "meeting invite", "on my schedule", "today's meetings", "today's invite"],
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
    """Scan user message for keywords and return skill IDs to auto-activate.

    Built-in keyword matching only. MCP connections and installed skills are
    routed by the LLM classifier (_classify_skills_via_llm), which is fed the
    full available-skill catalog — see _available_skill_catalog().
    """
    msg_lower = message.lower()
    found = [skill_id for skill_id, keywords in _SKILL_KEYWORDS.items()
             if any(kw in msg_lower for kw in keywords)]
    # Briefing intent → a daily/standup "brief" needs the comms+calendar trio.
    # Deterministic so scheduled briefings work even if the LLM classifier is
    # unreachable (and "brief/briefing/catch me up" is too vague for 1:1 keywords).
    _BRIEFING_SIGNALS = ["briefing", "daily brief", "morning brief", "give brief",
                         "give me a brief", "catch me up", "what did i miss",
                         "rundown", "daily digest", "standup", "stand-up"]
    if any(sig in msg_lower for sig in _BRIEFING_SIGNALS):
        for sid in ("email", "calendar", "teams"):
            if sid not in found:
                found.append(sid)
    return found


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


def _sanitize_catalog_text(s: str, max_len: int = 80) -> str:
    """Neutralize untrusted text (MCP server tool/connection names, marketplace
    descriptions) before it enters the system prompt / classifier prompt.

    These strings originate from third-party MCP servers and marketplace skills,
    so they're a prompt-injection vector. Strip control chars and newlines (which
    could fake a new prompt section) and clamp length so a verbose/hostile name
    can't dominate the prompt.
    """
    if not s:
        return ""
    # Drop chars that could forge a new prompt line/section: C0 controls + DEL
    # (0x00-0x1f, 0x7f) AND the Unicode line/paragraph separators (U+2028/2029,
    # NEL U+0085) which some renderers/tokenizers treat as line breaks. Replace
    # with spaces. Do NOT rely on str.split() alone to catch these — an explicit
    # set keeps the line-break neutralization self-documenting.
    _LINEBREAKISH = {0x85, 0x2028, 0x2029}  # NEL, LINE SEP, PARAGRAPH SEP
    cleaned = "".join(
        " " if (ord(c) < 0x20 or ord(c) == 0x7f or ord(c) in _LINEBREAKISH) else c
        for c in s
    )
    cleaned = " ".join(cleaned.split())  # collapse runs of whitespace
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip() + "…"
    return cleaned


def _mcp_catalog() -> dict[str, str]:
    """Return {connection_id: description} for every enabled MCP connection.

    Description is built from the connection name plus a short sample of its
    tool names — enough for the LLM classifier / manifest to know what it does,
    without loading full tool schemas (deferred-loading pattern). Read-only,
    rebuilt per request from live config so runtime-added connections appear.

    All names come from third-party MCP servers, so they're sanitized before
    they reach any prompt (_sanitize_catalog_text). Best-effort: any failure
    returns {} so chat routing never breaks.
    """
    out: dict[str, str] = {}
    try:
        from mcp.manager import _load_connections
        for conn in _load_connections():
            if not conn.get("enabled", True):
                continue
            cid = conn.get("id")
            name = _sanitize_catalog_text(conn.get("name") or cid or "", max_len=40)
            if not cid:
                continue
            tools = conn.get("cached_tools", []) or []
            tool_names = [_sanitize_catalog_text(t.get("name", ""), max_len=30)
                          for t in tools[:6] if t.get("name")]
            sample = ", ".join(n for n in tool_names if n)
            desc = name
            if sample:
                desc = _sanitize_catalog_text(f"{name} — tools: {sample}", max_len=160)
            out[cid] = desc
    except Exception:
        return {}
    return out


def _installed_skill_catalog() -> dict[str, str]:
    """Return {skill_id: description} for installed marketplace skills that are
    loaded (in SKILL_PROMPTS) and not built-in. Read-only, per request.
    Descriptions are third-party text and are sanitized before prompt use."""
    out: dict[str, str] = {}
    try:
        from marketplace.installer import load_installed
        for entry in load_installed():
            sid = entry.get("id", "")
            if not sid or sid not in shared.SKILL_PROMPTS:
                continue
            if sid in shared._BUILTIN_SKILL_IDS:
                continue
            desc = _sanitize_catalog_text(
                entry.get("description") or entry.get("display_name") or sid, max_len=120)
            out[sid] = desc
    except Exception:
        return {}
    return out


def _available_skill_catalog() -> dict[str, str]:
    """Single source of truth for everything the LLM may activate this turn.

    Order matters: MCP connections + installed skills come FIRST, built-ins last.
    The system-prompt manifest caps the list, and built-ins are mostly always-on
    or keyword-routed anyway — so the user-added MCP/installed skills (the whole
    point of this manifest) must not be truncated away behind the built-ins.

    Fed to BOTH the LLM classifier and the system-prompt manifest. Rebuilt per
    request from live registries — no startup caching, so connections/skills
    added at runtime appear on the next turn.
    """
    catalog: dict[str, str] = {}
    catalog.update(_mcp_catalog())
    catalog.update(_installed_skill_catalog())
    for sid, desc in _CLASSIFY_SKILL_IDS.items():
        catalog.setdefault(sid, desc)
    return catalog


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


# Auto-detected skills are ranked by PROVENANCE, not trust tier — native
# (in-house) skills have been hit-or-miss while Community-tier skills often come
# from official vendor sources (Atlassian, Anthropic). Lower rank = kept first.
_PROVENANCE_RANK = {"user": 0, "enterprise": 1, "verified": 2, "anthropic": 2, "clawhub": 3}
_MAX_AUTO_SKILLS = 4  # cap on auto-detected skills per turn (explicit + deps are exempt)


def _skill_provenance_rank(skill_id: str) -> int:
    """Rank a skill by source provenance. Native builtins rank lowest (4)."""
    if skill_id in shared._BUILTIN_SKILL_IDS:
        return 4
    try:
        from marketplace.installer import load_installed
        src = next((e.get("source", "") for e in load_installed() if e.get("id") == skill_id), "")
    except Exception:
        src = ""
    return _PROVENANCE_RANK.get(src, 3)


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
    # Also stop browser agent if running
    try:
        from browser_agent import is_browser_active, cancel_browser_task
        if is_browser_active():
            cancel_browser_task()
    except Exception:
        pass
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
    from app import execute_tool as _execute_tool_raw, _tool_toast
    from functools import partial as _partial

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
        # Resolve the user-facing name to its internal skill id BEFORE the
        # registry check, so aliased names (e.g. /outlook -> email) don't trip
        # the "unknown plugin" warning (#40).
        _resolved_plugin = _resolve_skill_id(slash_cmd["plugin"])
        if _resolved_plugin not in shared.SKILL_PROMPTS:
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
            "active_skill": _resolved_plugin,
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

    # When the Code tab is active, tell the main LLM which project/repo it's on
    # so it can answer "which repo are you on?" without saying "I don't have visibility".
    if "code_agent" in _active_sids or req.active_skill == "code_agent":
        try:
            from skills.code_agent.projects import get_active_project, get_project
            _ca_active = get_active_project()
            _ca_proj = get_project(_ca_active) if _ca_active else None
            if _ca_proj:
                system += (
                    f"\n\nACTIVE CODING PROJECT: {_ca_proj['name']}"
                    f"\nREPOSITORY PATH: {_ca_proj['repo_path']}"
                    f"\nIf the user asks which repo, project, or folder you are working on, "
                    f"answer with the above name and path directly."
                )
        except Exception:
            pass

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

    # AVAILABLE (inactive) skills manifest -- discovery layer. Lists everything the
    # user has connected/installed that ISN'T active this turn, so the model knows
    # it exists and can self-activate via the /id rule. Deferred-loading pattern:
    # only id + one-line description here (cheap); full tool schemas load on
    # activation. Without this, "do you have gmail?" returns "no" because the
    # model can't see inactive MCP connections.
    try:
        _catalog = _available_skill_catalog()
        _inactive = {sid: desc for sid, desc in _catalog.items()
                     if sid not in _explicit_skill_ids and sid != "gator"}
        if _inactive:
            _CATALOG_CAP = 15
            _items = list(_inactive.items())
            _shown = _items[:_CATALOG_CAP]
            _avail_lines = "\n".join(f"  \u2022 /{sid} \u2014 {desc}" for sid, desc in _shown)
            _more = len(_items) - len(_shown)
            _more_note = f"\n  \u2026and {_more} more \u2014 ask to list all." if _more > 0 else ""
            system += (
                f"\n\n\U0001f4e6 AVAILABLE SKILLS (not active yet) \u2014 the user has these connected/installed. "
                f"They are NOT loaded right now, but you CAN use them: to activate one, output ONLY its bare "
                f"`/id` token (per the activation rule above), and the server reloads with its tools.\n{_avail_lines}{_more_note}\n"
                f"When the user asks whether you have a capability that appears here (e.g. \"do you have gmail?\"), "
                f"answer YES and offer to use it \u2014 never say you lack it. When the user names one of these "
                f"services, activate it rather than substituting a different active skill."
            )
    except Exception as _e:
        print(f"[skill-manifest] could not build available-skills manifest: {_e}", flush=True)

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
                _od_drive = m.get('drive_id', '')
                _od_drive_hint = f", drive_id: {_od_drive}" if _od_drive else ""
                _od_call = f"read_onedrive_file(file_id={pid}, drive_id={_od_drive})" if _od_drive else f"read_onedrive_file(file_id={pid})"
                _pin_lines.append(f"- OneDrive: \"{lbl}\" (file_id: {pid}, path: {m.get('file_path','?')}{_od_drive_hint}) \u2192 use {_od_call}")
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
            "\n\nONEDRIVE/SHAREPOINT HONESTY RULES:"
            "\n- Never claim a name-search result is the same file as one identified by a URL or item ID without comparing canonical identifiers (item ID or sourcedoc GUID)."
            "\n- If given a SharePoint share-link you cannot resolve, say so explicitly. NEVER silently substitute a name-search guess — if you fall back to search, label it clearly as a guess and ask the user to confirm before continuing."
            "\n- If read_onedrive_file returns unresolved=True, stop and tell the user the link could not be resolved; do not proceed with assumptions."
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
    # Skip entirely for scoped requests (wizard, etc.) — the skill set is
    # fully controlled by scoped_skill and must not be polluted by URL/keyword
    # detection (e.g. the browser skill firing on a pasted MCP URL).
    _inferred = []
    _classifier_inherited = False
    if req.scoped_skill:
        print(f"[classifier] skipped — scoped_skill={req.scoped_skill!r}", flush=True)
    else:
        from continuation_classifier import classify as _classify, detect_pending as _detect_pending
        _tab_state = shared.task_state_store.get(_context_id)
        _clf = _classify(_msg_text, _tab_state)
        print(f"[classifier] mode={_clf.mode} reason={_clf.reason}", flush=True)
        if _clf.mode in ("confirmation", "data_input", "inherit") and _tab_state and _tab_state.active_skills:
            # Bypass skill detection — inherit the stored skill set
            _inferred = list(_tab_state.active_skills)
            _classifier_inherited = True
            if _clf.resolved_pending:
                shared.task_state_store.update(_context_id, pending=None)
            print(f"[classifier] inheriting skills {_inferred} (bypassing keyword/LLM detection)", flush=True)

    if not _classifier_inherited and not req.scoped_skill:
        _inferred = _infer_skills_from_message(_msg_text)
        # Also match installed marketplace skills by name (handles skills absent from static dicts)
        _installed_matches = _installed_skill_ids_from_message(_msg_text)
        if _installed_matches:
            _inferred = list(set(_inferred) | set(_installed_matches))
        if _inferred:
            print(f"[skill-detect] keywords/installed matched: {_inferred}", flush=True)
        # Build the non-builtin catalog once (MCP connections + installed skills).
        _extra_catalog = {k: v for k, v in _available_skill_catalog().items()
                          if k not in _CLASSIFY_SKILL_IDS}
        # Run the LLM classifier when EITHER no keyword matched, OR a built-in
        # keyword matched but the user also has non-builtin skills available that
        # could overlap (e.g. keyword 'inbox' -> email, but a Gmail MCP exists).
        # The classifier sees the full catalog and can route to the right service;
        # without this, a built-in keyword would always win and hide MCP skills.
        _should_classify = _msg_text.strip() and (not _inferred or _extra_catalog)
        if _should_classify:
            print(f"[skill-detect] running LLM classifier (extra={list(_extra_catalog)})...", flush=True)
            _classified = _classify_skills_via_llm(_msg_text, extra_skills=_extra_catalog or None)
            if _classified:
                # Union keyword + classifier results so we keep the built-in AND
                # surface the overlapping MCP/installed skill — the LLM then picks
                # (or asks) per the disambiguation rule.
                _inferred = list(set(_inferred) | set(_classified))
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
    # Refresh installed skill prompts so SKILL.md edits (including `requires:`)
    # take effect on the next request without a server restart.
    shared.load_installed_skill_prompts()
    _all_active = list(set(_explicit_no_gator + _pin_skills + _inferred))
    # Rank + cap AUTO-detected skills before dep expansion so a dropped skill
    # doesn't drag in its dependencies. Explicit skills are exempt (never capped).
    # Ranking is by provenance (official vendor sources beat flaky in-house native);
    # capping keeps the model's tool menu small on every multi-match turn.
    _auto_candidates = [s for s in _all_active if s not in _explicit_skill_ids]
    if len(_auto_candidates) > _MAX_AUTO_SKILLS:
        _ranked = sorted(_auto_candidates, key=_skill_provenance_rank)
        _kept = set(_ranked[:_MAX_AUTO_SKILLS])
        _dropped = _ranked[_MAX_AUTO_SKILLS:]
        _all_active = [s for s in _all_active if s in _explicit_skill_ids or s in _kept]
        print(f"[skill-cap] {len(_auto_candidates)} auto-skills -> kept {sorted(_kept)}, "
              f"dropped {_dropped} (provenance-ranked)", flush=True)
    # Inject scoped_skill (e.g. _extension_setup for the wizard) without modifying req.active_skills
    if req.scoped_skill and req.scoped_skill not in _all_active:
        _all_active.append(req.scoped_skill)
    # Expand declared dependencies (SKILL.md `requires:` frontmatter).
    # One-pass transitive expansion — covers requires-of-requires without deep recursion.
    _deps_added: list[str] = []
    for _seed in list(_all_active):
        for _dep in shared.SKILL_REQUIRES.get(_seed, []):
            if _dep in shared.SKILL_PROMPTS and _dep not in _all_active:
                _all_active.append(_dep)
                _deps_added.append(_dep)
    for _seed in list(_all_active):  # second pass for transitive
        for _dep in shared.SKILL_REQUIRES.get(_seed, []):
            if _dep in shared.SKILL_PROMPTS and _dep not in _all_active:
                _all_active.append(_dep)
                _deps_added.append(_dep)
    if _deps_added:
        print(f"[skill-deps] auto-activated declared dependencies: {_deps_added}", flush=True)
    active_tools = _filter_tools(_active_skill_no_gator, req.has_images, _all_active,
                                  unapproved_deps=req.unapproved_deps)
    print(f"[tokens] active_skill={req.active_skill} inferred={_inferred} -> {len(active_tools)} tools (of {len(shared.TOOLS)} total)", flush=True)

    # Inject skill prompts for auto-detected skills (pins + keywords) and
    # declared dependencies that weren't already injected in the explicit/always-on pass above.
    for _sid in sorted(set(_pin_skills + _inferred + _deps_added) - _active_sids):
        if _sid in shared.SKILL_PROMPTS and _sid in _all_active:  # respect the provenance cap
            system += "\n\n" + shared.SKILL_PROMPTS[_sid]
            print(f"[skill-prompt] injected SKILL.md for '{_sid}' ({len(shared.SKILL_PROMPTS[_sid])} chars)", flush=True)

    _context_only_skills = [s for s in _context_only_skills if s in _all_active]  # drop capped-out skills
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
        "\n\nIf you need a skill that is not currently active, output ONLY the bare token `/skillname` "
        "(e.g. `/jira` or `/email`) with absolutely no other text — not a sentence, not an explanation, "
        "not 'Activating now', nothing. The server detects the token, shows a status indicator to the user, "
        "activates the skill silently, and retries with the new tools. "
        "NEVER narrate the activation. NEVER ask the user to type anything. Just the token, alone.\n"
        "IMPORTANT skill routing: for calendar/meeting/schedule questions use `/m365-calendar`; "
        "for email/inbox questions use `/email`. Do NOT use `/outlook` — it only activates email, not calendar."
    )

    # MCP guidance — appended when any MCP connection's tools are in scope.
    # MCP responses come from arbitrary third-party servers and can be very large
    # (Atlassian, Confluence, etc. routinely return hundreds of KB). Nudge the
    # model toward narrow queries and serial dispatch so it doesn't poison its
    # own context. Server-side limit injection (mcp/manager.py) and response
    # capping (context_utils.py) are the safety nets if this prompt fails.
    if any(s.startswith("mcp-") for s in _all_active):
        system += (
            "\n\n## MCP tool guidance\n"
            "MCP tool responses can be very large (hundreds of KB of JSON). Follow these rules:\n"
            "1. **Narrow your queries first.** Always pass `limit`/`maxResults`/`pageSize` "
            "if the tool accepts them — start with 5–10, expand only if needed. Use date "
            "ranges, project keys, space keys, and other filters whenever possible.\n"
            "2. **Serial, not parallel, for expensive calls.** When calling MCP tools that "
            "might return large data (search, list, get-all), call ONE at a time. Inspect "
            "the result before dispatching the next.\n"
            "3. **Pick one server per question.** If multiple MCP servers cover the same "
            "domain (e.g. two Atlassian connections), pick the one most likely to have the "
            "answer based on the user's intent — do NOT call both in parallel.\n"
            "4. **Lookup-then-fetch.** For \"find X and read its body\" patterns, first run "
            "a lightweight search to get IDs/keys, then fetch only the specific items you "
            "need rather than asking for full bodies in the search response.\n"
            "5. **If a response was truncated** (marked `_truncation_note`), re-run with a "
            "narrower query — do NOT ask the user to re-paste anything."
        )

    # Disambiguation — general rule for overlapping tools/services.
    # Users bring their own MCP servers, so multiple tools can cover the same
    # domain (Outlook + Gmail for email, two Jira instances, several browsers,
    # etc.). Without guidance the model silently picks one — usually the built-in
    # — which surprises the user. Tell it to honor explicit signals and ASK when
    # genuinely ambiguous, rather than guessing.
    system += (
        "\n\n## Choosing between overlapping tools\n"
        "Multiple tools or connected services may cover the same task (e.g. two "
        "email providers, two issue trackers, several browsers). When more than "
        "one could satisfy the request:\n"
        "1. **Honor explicit signals.** If the user names a service or provider "
        "(e.g. \"gmail\", \"outlook\", a specific connection name), use that one "
        "— even if its capability lives in an MCP tool rather than a built-in skill.\n"
        "2. **Honor the active skill/pill.** If exactly one matching skill is "
        "active for this turn, prefer its tools.\n"
        "3. **When genuinely ambiguous, ASK.** If the request is generic (e.g. "
        "\"check my inbox\") and two or more connected services could handle it, "
        "ask the user which one in one short sentence — list the options — instead "
        "of guessing. Do NOT default to the built-in just because it was there first.\n"
        "4. **Don't call all of them.** Never fan out to every matching tool to "
        "cover your bases — pick one, or ask."
    )

    # Append wizard/scoped suffix (e.g. extra rules injected by setup wizard)
    if getattr(req, "system_prompt_suffix", None):
        system = system + "\n\n---\n\n" + req.system_prompt_suffix

    context_id = getattr(req, "context_id", None) or "default"
    # Bind context_id into execute_tool so handlers that opt-in by accepting
    # a _context_id kwarg (e.g. get_tab_pins) know the current tab without
    # the LLM having to pass it explicitly.
    execute_tool = _partial(_execute_tool_raw, context_id=context_id)

    # Shared mutable flag so stream()'s finally and _run_and_buffer's exception
    # handler can coordinate: if stream() already yielded [DONE], _run_and_buffer
    # must not append a second one. Use a list so both closures share the same ref.
    _done_emitted_flag: list[bool] = [False]

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
        history_window = await shared.conversation_store.get_window(context_id, model)
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
        # The direct router is a token-saving shortcut for UNAMBIGUOUS built-in
        # intents only. If a non-builtin skill (MCP connection / installed skill)
        # is active or was inferred for this turn, skip it — those can overlap a
        # built-in (e.g. Gmail MCP vs Outlook's read_email) and only the LLM,
        # which sees all tools + the disambiguation rule, can route correctly.
        _nonbuiltin_in_play = any(
            s not in shared._BUILTIN_SKILL_IDS
            for s in (_all_active or [])
            if s and s != "gator"
        )
        intent = None if _nonbuiltin_in_play else match_intent(_msg_text_raw)
        if intent:
            is_browser = intent.get("tool", "").startswith("browser")
            yield f"data: {_json.dumps({'status': '⚡ ' + intent['tool'] + '...'})}\n\n"

            if is_browser:
                # Browser tasks: run in background, browser pane streams screenshots via /api/browser/stream
                import asyncio as _aio
                _browser_task = _aio.ensure_future(
                    execute_direct(intent, execute_tool, user_message=_msg_text_raw)
                )
                yield f"data: {_json.dumps({'browser_hitl': 'active'})}\n\n"
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
                    context_id=context_id,
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
        # Tell the client which skills were auto-selected server-side (pins,
        # classifier, keyword inference, declared deps — minus the provenance
        # cap, minus gator, minus anything the user explicitly added). These
        # never become chips in the skill bar, so the UI surfaces them inline.
        _auto_selected = [s for s in _all_active if s not in _explicit_skill_ids and s != 'gator']
        if _auto_selected:
            _auto_payload = [{"id": s, "label": _SKILL_LABELS.get(s, s)} for s in sorted(_auto_selected)]
            yield f"data: {_json.dumps({'skills_auto': _auto_payload})}\n\n"

        def _build_loop(tools_list, sys_text, message_list):
            norm = [provider.normalize_tool_schema(t) for t in tools_list]
            if use_three_agent:
                return run_three_agent_loop(
                    provider=provider, model=model, system=sys_text, msgs=message_list,
                    normalized_tools=norm, execute_tool=execute_tool,
                    COM_BOUND_TOOLS=shared.COM_BOUND_TOOLS, TOOL_STATUS=shared.TOOL_STATUS,
                    _tool_toast=_tool_toast, _SLACK_SAFE_MSG=shared._SLACK_SAFE_MSG,
                    token_budget=token_budget,
                    context_id=context_id,
                )
            return _single_agent_loop(
                provider=provider, model=model, system=sys_text, msgs=message_list,
                normalized_tools=norm, execute_tool=execute_tool,
                COM_BOUND_TOOLS=shared.COM_BOUND_TOOLS, TOOL_STATUS=shared.TOOL_STATUS,
                _tool_toast=_tool_toast, _SLACK_SAFE_MSG=shared._SLACK_SAFE_MSG,
                context_id=context_id,
            )

        _current_loop = _build_loop(active_tools, system, msgs)
        _current_system = system
        _current_msgs = msgs
        _assistant_text_parts: list[str] = []
        _retry_count = 0
        # Allow several passes so a skill that pulls in deps which themselves
        # name further skills can fully chain (#70).
        _MAX_AUTO_ACTIVATE_RETRIES = 3
        _stream_emitted_done = False  # track whether agent loop already sent [DONE]

        try:
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

                # Detect "please activate /skillname" mentions in the just-completed
                # turn and auto-retry. A turn can name several skills at once (#70),
                # so collect ALL of them, not just the first match.
                _new_skills: list[str] = []
                if _retry_count < _MAX_AUTO_ACTIVATE_RETRIES and not use_three_agent:
                    _turn_text = "".join(_turn_text_parts)
                    _new_skills = _detect_requested_skills(_turn_text, _all_active)

                if not _new_skills:
                    if _done_chunk:
                        _stream_emitted_done = True
                        _done_emitted_flag[0] = True
                        yield _done_chunk
                    break

                # Auto-activate ALL requested skills and re-run the loop with expanded tools
                _all_active.extend(_new_skills)
                _new_tools = _filter_tools(_active_skill_no_gator, req.has_images, _all_active,
                                           unapproved_deps=req.unapproved_deps)
                # MCP skills have tools but no SKILL.md prompt — use .get() so they
                # don't KeyError; their tools alone are enough for the model to use.
                _new_system = _current_system + "".join(
                    "\n\n" + shared.SKILL_PROMPTS[s] for s in _new_skills
                    if s in shared.SKILL_PROMPTS)
                _labels = ", ".join(f"/{s}" for s in _new_skills)
                _new_msgs = list(_current_msgs) + [
                    {"role": "assistant", "content": "".join(_turn_text_parts) or "[continuing]"},
                    {"role": "user", "content": (
                        f"[System: Skill(s) {_labels} have just been auto-activated and their tools are now available. "
                        f"Continue the user's original request using these new tools — do NOT ask them to activate anything."
                    )},
                ]
                for _s in _new_skills:
                    shared.notify_all({"type": "skill_auto_activated", "skill_id": _s})
                yield f"data: {_json.dumps({'status': f'⚡ Activating {_labels}...'})}\n\n"
                print(f"[skill-auto-activate] {_labels} added mid-stream, retrying with {len(_new_tools)} tools", flush=True)
                _current_loop = _build_loop(_new_tools, _new_system, _new_msgs)
                _current_system = _new_system
                _current_msgs = _new_msgs
                _retry_count += 1

        finally:
            # Guaranteed [DONE]: if the agent loop exited without emitting [DONE]
            # (e.g. generator break without _done_chunk), emit it now so the UI
            # always unblocks the prompt bar.
            # Guard with try/except GeneratorExit: yielding inside a finally during
            # GeneratorExit (client disconnect / cancel) raises RuntimeError in async
            # generators. On cancellation, _run_and_buffer's exception handler appends
            # [DONE] itself, so the client is still unblocked.
            if not _stream_emitted_done:
                try:
                    yield "data: [DONE]\n\n"
                    _done_emitted_flag[0] = True
                except GeneratorExit:
                    pass

        # Post-turn: update task state with active skills + detect new pending state.
        # Always decay pending on stream completion — prevents frozen "Continue where
        # you left off" bar after errors or circuit-breaker aborts on on-prem models.
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

        # Persist new turns to server-side conversation store.
        # Use _current_msgs (not msgs) because auto-activation switches to a new
        # list mid-stream; any turns appended by the retry loop live there, not in msgs.
        _final_msgs = _current_msgs
        new_turns = _final_msgs[len(history_window):]
        if new_turns:
            await shared.conversation_store.append(context_id, new_turns)

        # Log usage after stream completes
        if _in_tok or _out_tok:
            _prompt = req.message if isinstance(req.message, str) else ""
            try:
                await log_usage("chat", _prompt[:100], _in_tok, _out_tok)
            except Exception:
                pass

    task_id = str(_uuid.uuid4())
    shared.chat_task_store.create_task(task_id, context_id)

    async def _run_and_buffer():
        # Serialize per context_id: two concurrent requests on the same context
        # (e.g. two browser tabs sharing localStorage's active-tab id) must not
        # interleave their tool_use/tool_result turns into the shared history.
        try:
            async with _asyncio.timeout(300):  # 5-minute max per request
                async with shared.conversation_store.lock_for(context_id):
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
                    import logging as _logging
                    _logging.getLogger(__name__).exception(
                        "[stream] unhandled error in background task: %s", _exc
                    )
                    print(f"[stream] unhandled error in background task: {_exc}", flush=True)
                    _tb.print_exc()
                    shared.chat_task_store.append_chunk(task_id, f"data: {json.dumps({'text': 'An unexpected error occurred. Please try again.'})}\n\n")
                    # stream()'s finally may have already yielded [DONE] before the
                    # exception propagated — only append a second one if it didn't,
                    # so the client never receives two [DONE] frames.
                    if not _done_emitted_flag[0]:
                        shared.chat_task_store.append_chunk(task_id, "data: [DONE]\n\n")
                  finally:
                    shared.chat_task_store.mark_done(task_id)
                    # Emit in finally (not at the end of stream()) so a hung,
                    # errored, or cancelled request still notifies other tabs.
                    # Otherwise the cross-tab alert and the in-progress tab
                    # indicator would only clear on the happy path, leaving a
                    # stalled chat silently stuck.
                    shared.notify_all({"type": "chat_done", "context_id": context_id})
        except _asyncio.TimeoutError:
            shared.chat_task_store.append_chunk(task_id, f"data: {json.dumps({'error': 'Request timed out waiting for previous response to complete. Please try again.'})}\n\n")
            shared.chat_task_store.append_chunk(task_id, "data: [DONE]\n\n")
            if not shared.chat_task_store.is_done(task_id):
                shared.chat_task_store.mark_done(task_id)

    _bg_task = _asyncio.create_task(_run_and_buffer())
    shared.chat_task_store.track_task(_bg_task)  # prevent GC from cancelling the task
    return JSONResponse({"task_id": task_id})
