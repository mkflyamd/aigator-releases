"""Always-on skill -- 3 tools (always available regardless of active skill)."""
import json
import logging
import re
import urllib.request
from pathlib import Path

import shared
import dataclasses
import urllib.request as _urllib
from mcp.normalizer import normalize as _normalize, NormalizeResult as _NR, _make_gateway_llm
from mcp.url_fetcher import url_fetcher as _url_fetcher

ROOT = Path(__file__).parent.parent.parent.parent

_log = logging.getLogger(__name__)

ALWAYS_ON = True


def _normalize_mcp(raw_input: str) -> _NR:
    """Wrapper so tests can patch this cleanly."""
    return _normalize(raw_input, fetcher=_url_fetcher, llm=_make_gateway_llm())


def _save_mcp_connection(payload: dict) -> dict:
    """POST to /api/config/mcp and return the JSON response."""
    import json as _json
    data = _json.dumps(payload).encode()
    req = _urllib.Request(
        "http://localhost:8765/api/config/mcp",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with _urllib.urlopen(req, timeout=30) as resp:
        return _json.loads(resp.read())


TOOL_DEFS = [
    {
        "name": "describe_images",
        "description": (
            "Describe, extract data from, or analyze a sequence of images. "
            "task='describe': describe a single image already uploaded in this conversation. "
            "task='compare': compare two images already in this conversation. "
            "task='extract_data': read image_paths from disk and extract named fields as structured JSON — use for receipts, screenshots, forms. "
            "task='assess': generate a structured assessment report from images in this conversation. "
            "task='analyze_sequence': read a list of video frames from disk (image_paths), label each with its timestamp, "
            "and return a per-frame timeline describing what is visible, what actions are happening, and any text/UI visible. "
            "Use analyze_sequence for video keyframe analysis — do NOT ask the user to upload frames, pass image_paths directly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "enum": ["describe", "compare", "extract_data", "assess", "analyze_sequence"],
                    "description": "What visual analysis task to perform",
                },
                "image_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                    "description": (
                        "File paths to read from disk. "
                        "For extract_data: paths to images to extract fields from. "
                        "For analyze_sequence: ordered list of video frame paths — each is read, "
                        "labeled with its index/timestamp, and described in the returned timeline."
                    ),
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                    "description": "With task='extract_data': field names to extract (e.g. ['fee_amount', 'due_date']). Returns schema-validated JSON.",
                },
                "fps": {
                    "type": "number",
                    "default": 0.2,
                    "description": "For analyze_sequence: frames-per-second used during extraction (default 0.2 = 1 frame per 5s). Used to calculate timestamps from frame index.",
                },
            },
            "required": ["task"],
        },
    },
    {
        "name": "fetch_webpage",
        "description": "Fetch and read the content of a specific public webpage by URL. Use when the user shares a link and asks you to read or analyse it. Do NOT use for general searches — use web_search instead. If the result contains 'suggest_search: true' or says 'REQUIRED NEXT STEP', you MUST call web_search immediately — do NOT call browser_search or browser_navigate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The full URL to fetch (must start with http:// or https://)"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "web_search",
        "description": "Search the web and return top results with titles, URLs, and snippets. Use for general information lookup, recent news, or when fetch_webpage is blocked (403/bot-challenge). No browser or API key needed — always available. Do NOT use when you already have the full content from fetch_webpage.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "Number of results to return (default 5, max 10)", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_skill",
        "description": "Read the full capability guide (SKILL.md) and manifest for an installed skill. Call this when the user asks what a skill can do, or when you are about to use a skill's tools for the first time in a session and want to confirm correct usage. Do NOT call this before every single tool use — only when you genuinely need to check capabilities or parameters. skill_id examples: 'calendar', 'excel', 'email'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string", "description": "The skill folder name under /skills/, e.g. 'calendar' or 'excel'"},
            },
            "required": ["skill_id"],
        },
    },
    {
        "name": "schedule_task",
        "description": "Create a recurring or one-shot scheduled task. Use when the user asks for something to run at a specific time or on a recurring basis (e.g. 'every Monday at 9am', 'every 30 minutes', 'at 5pm today'). Parse the user's natural language schedule into the structured parameters below.\n\nIMPORTANT — resolve skills BEFORE scheduling: a scheduled task runs unattended later, so it must already know which tools it needs. Determine the skills the prompt requires (email, calendar, teams, slack, jira, etc.). If the request is vague about its data sources — e.g. 'give me a brief', 'daily digest', 'catch me up', 'summarize my day' — do NOT guess or pass an empty skills list. First ASK the user which sources to include (e.g. 'Should the daily brief cover your email, calendar, and Teams?'), then schedule with the confirmed skills. Only skip asking when the needed skills are unambiguous from the request.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Short descriptive name (e.g. 'Sprint Brief', 'Daily Digest')"},
                "prompt": {"type": "string", "description": "Full instruction for what the AI should do when this schedule fires"},
                "trigger_type": {"type": "string", "enum": ["cron", "interval", "date"], "description": "cron=recurring days/times, interval=every N minutes, date=one-shot at specific datetime"},
                "cron_day_of_week": {"type": "string", "description": "For cron: day(s) of week. E.g. 'mon', 'mon-fri', '*'. Optional."},
                "cron_hour": {"type": "integer", "description": "For cron: hour (0-23)"},
                "cron_minute": {"type": "integer", "description": "For cron: minute (0-59)", "default": 0},
                "cron_timezone": {"type": "string", "description": "For cron: IANA timezone name (e.g. 'America/New_York', 'Asia/Kolkata'). If the user specifies a timezone or location, use it. Otherwise omit and the server uses system local time."},
                "interval_minutes": {"type": "integer", "description": "For interval: minutes between runs"},
                "run_date": {"type": "string", "description": "For date (one-shot): ISO8601 datetime string"},
                "end_date": {"type": "string", "description": "Optional ISO8601 datetime when recurring schedule should stop. Use when user says 'till EOD', 'until 5pm', 'for the next 2 hours'. E.g. '2026-05-11T17:00:00'."},
                "token_budget": {"type": "integer", "description": "Max tokens per run. Default 50000.", "default": 50000},
                "skills": {"type": "array", "items": {"type": "string"}, "description": "Skill IDs this job needs when it runs (e.g. ['teams'], ['email', 'calendar']). REQUIRED and must be non-empty for any task that reads or sends data. If you cannot confidently determine the skills from the user's request, do NOT call this tool with an empty or guessed list — ask the user which data sources to include first, then schedule. Briefings/digests typically need ['email', 'calendar', 'teams']."},
            },
            "required": ["name", "prompt", "trigger_type", "skills"],
        },
    },
    {
        "name": "list_schedules",
        "description": "List all currently scheduled tasks with their next run times and last run status. Use when the user asks 'what's scheduled?', 'show my schedules', 'what agents are running?'.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "analyze_mcp_server",
        "description": (
            "Analyze any MCP server input and return what was found. "
            "Accepts a GitHub URL, a JSON config snippet in any IDE format, a bare server URL, "
            "or a command line (e.g. 'npx @playwright/mcp@latest'). "
            "Always call this first to show the user what was found. "
            "Then ask for confirmation before calling connect_mcp_server."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "raw_input": {
                    "type": "string",
                    "description": "The raw text, URL, JSON, or command the user provided",
                },
            },
            "required": ["raw_input"],
        },
    },
    {
        "name": "connect_mcp_server",
        "description": (
            "Save and connect an MCP server after the user has confirmed. "
            "Only call this after the user has explicitly approved the details shown by analyze_mcp_server."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "transport":  {"type": "string", "enum": ["http", "stdio"]},
                "name":       {"type": "string"},
                "url":        {"type": "string", "description": "For http transport"},
                "auth_type":  {"type": "string", "enum": ["none", "bearer", "api_key"], "default": "none"},
                "auth_value": {"type": "string", "default": ""},
                "command":    {"type": "string", "description": "For stdio transport"},
                "args":       {"type": "array", "items": {"type": "string"}, "default": []},
                "env":        {"type": "object", "default": {}},
            },
            "required": ["transport", "name"],
        },
    },
    {
        "name": "mcp_connection_status",
        "description": (
            "Check the setup/connection status of MCP servers configured in AI Gator "
            "(including those bundled with marketplace plugins like datadog, atlassian). "
            "Call this BEFORE following a plugin's own MCP setup instructions — it tells you "
            "whether the server is already working, or still needs the user to configure it. "
            "If a connection reports needs_setup, tell the user to open Settings → Connections, "
            "find that connection, and click 'Complete setup' to enter the required values — do "
            "NOT instruct the user to run CLI slash commands or edit files. Returns masked status "
            "only; never returns secret values."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": (
                        "Optional: a plugin id, connection name, or substring to narrow results, "
                        "e.g. 'datadog'. Omit to list all MCP connections."
                    ),
                },
            },
            "required": [],
        },
    },
]

TOOL_STATUS = {
    "describe_images": "\U0001f5bc\ufe0f Analyzing images...",
    "fetch_webpage": "\U0001f310 Fetching webpage...",
    "web_search": "\U0001f50d Searching the web...",
    "read_skill": "\U0001f4d6 Reading skill guide...",
    "schedule_task": "\U0001f4c5 Creating schedule...",
    "list_schedules": "\U0001f4cb Checking schedules...",
    "analyze_mcp_server": "\U0001f50e Analyzing MCP server...",
    "connect_mcp_server": "\U0001f517 Connecting MCP server...",
    "mcp_connection_status": "\U0001f50c Checking connection status...",
}


def _html_to_text(html: str, max_len: int = 0) -> str:
    """Convert HTML to readable plain text."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>|</div>|</tr>|</li>|</h[1-6]>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#39;", "'", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if max_len and len(text) > max_len:
        text = text[:max_len] + "..."
    return text


# Markers for JavaScript bot-protection challenges. Such pages often return HTTP
# 200 with a "solve this in a browser" interstitial, so a plain HTTP fetch
# silently captures the challenge instead of the real content (#47).
# Specific strings are safe to match anywhere in the body; generic English
# phrases must be confined to the <title> to avoid false positives on real prose.
_JS_CHALLENGE_BODY_MARKERS = [
    ("cf-browser-verification", "Cloudflare"),
    ("/cdn-cgi/challenge-platform", "Cloudflare"),
    ("checking your browser before accessing", "Cloudflare"),
    ("enable javascript and cookies to continue", "a JavaScript bot-protection challenge"),
    ("attention required! | cloudflare", "Cloudflare"),
]
_JS_CHALLENGE_TITLE_MARKERS = [
    ("just a moment", "Cloudflare"),
]
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)


def _detect_js_challenge(status_code: int, headers, body_text: str):
    """Return the name of the blocking mechanism if this response is a JS bot
    challenge rather than real content, else None. Pure/side-effect-free."""
    h = {str(k).lower(): str(v).lower() for k, v in dict(headers or {}).items()}
    body_lc = (body_text or "").lower()
    for marker, label in _JS_CHALLENGE_BODY_MARKERS:
        if marker in body_lc:
            return label
    title_match = _TITLE_RE.search(body_lc)
    title_lc = title_match.group(1) if title_match else ""
    for marker, label in _JS_CHALLENGE_TITLE_MARKERS:
        if marker in title_lc:
            return label
    if h.get("cf-mitigated") == "challenge":
        return "Cloudflare"
    if status_code in (403, 503) and "cloudflare" in h.get("server", ""):
        return "Cloudflare"
    return None


def _js_challenge_error(blocker: str, url: str) -> dict:
    return {
        "error": (
            f"This page is bot-protected ({blocker}) and cannot be fetched directly. "
            f"REQUIRED NEXT STEP: call web_search with a query based on the URL to get this content. "
            f"Do NOT use browser_search or browser_navigate."
        ),
        "blocked_by": blocker,
        "js_challenge": True,
        "url": url,
        "suggest_search": True,
        "search_hint": f"site content from {url}",
    }


def _tool_fetch_webpage(url: str) -> dict:
    """Fetch a public webpage and return its content as text."""
    if not url.startswith(("http://", "https://")):
        return {"error": "URL must start with http:// or https://"}
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; GatorBot/1.0)",
            "Accept": "text/html,application/json,text/plain",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read()
            # Try to decode
            encoding = "utf-8"
            if "charset=" in content_type:
                encoding = content_type.split("charset=")[-1].split(";")[0].strip()
            text = raw.decode(encoding, errors="replace")
            # Fail fast on JS bot-challenge interstitials (often served as 200 HTML)
            blocker = _detect_js_challenge(getattr(resp, "status", 200), resp.headers, text)
            if blocker:
                return _js_challenge_error(blocker, url)
            # If HTML, convert to plain text
            if "html" in content_type.lower():
                text = _html_to_text(text, max_len=12000)
            elif len(text) > 12000:
                text = text[:12000] + "..."
            return {"url": url, "content": text, "content_type": content_type}
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        blocker = _detect_js_challenge(e.code, e.headers, err_body)
        if blocker:
            return _js_challenge_error(blocker, url)
        if e.code in (403, 401, 429):
            return {
                "error": (
                    f"HTTP {e.code}: access blocked. "
                    f"REQUIRED NEXT STEP: call web_search with a query based on the URL to get this content. "
                    f"Do NOT use browser_search or browser_navigate."
                ),
                "url": url,
                "suggest_search": True,
                "search_hint": f"site content from {url}",
            }
        return {"error": f"HTTP {e.code}: {e.reason}", "url": url}
    except Exception as e:
        return {"error": str(e), "url": url}


def _tool_web_search(query: str, max_results: int = 5) -> dict:
    """Search the web using DuckDuckGo — no API key, no browser."""
    try:
        from ddgs import DDGS
    except ImportError:
        return {
            "error": "Web search (ddgs) not installed. Cannot search. Do NOT fall back to browser tools — tell the user the search is unavailable.",
            "query": query,
        }
    try:
        max_results = min(int(max_results), 10)
        results = list(DDGS().text(query, max_results=max_results))
        if not results:
            return {"query": query, "results": [], "note": "No results found. Do NOT try browser tools — report no results to the user."}
        formatted = [
            {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
            for r in results
        ]
        return {"query": query, "results": formatted}
    except Exception as e:
        return {
            "error": f"Search failed: {e}. Do NOT fall back to browser tools — report this error to the user.",
            "query": query,
        }


_IMAGE_MEDIA_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp",
}


async def _tool_describe_images(task: str, image_paths: list | None = None,
                               fields: list | None = None, fps: float = 0.2) -> dict:
    if task == "analyze_sequence" and image_paths:
        # Validate image_paths exist on disk BEFORE calling the gateway — the
        # common failure mode used to be masked as "image_paths don't exist"
        # when actually the gateway call failed. Check the filesystem first so
        # the error message is accurate either way.
        missing = [p for p in image_paths if not isinstance(p, str) or not Path(p).exists()]
        if missing:
            return {
                "ok": False,
                "error": (
                    f"Frame sequence analysis failed: {len(missing)} of {len(image_paths)} "
                    f"image path(s) do not exist on disk. First missing: {missing[:3]}"
                ),
            }
        result = await _analyze_frame_sequence(image_paths, fps)
        if result is not None and result.get("ok"):
            return result
        if result is not None:
            # _analyze_frame_sequence already returned a structured error with
            # the real gateway/timeout/HTTP details — pass it through verbatim.
            return result
        # Defensive: should not happen now, but keep a fallback.
        return {"ok": False, "error": "Frame sequence analysis failed for an unknown reason (no error detail returned)."}
    if task == "extract_data" and image_paths and fields:
        result = _extract_structured_fields(image_paths, fields)
        if result is not None:
            return result
        # Fall through to prose path if structured extraction fails.
    return {"ok": True, "task": task, "instruction": "Perform the visual analysis now in your response text based on the images in this conversation."}


def _extract_structured_fields(image_paths: list, fields: list) -> dict | None:
    """Schema-constrained extraction: reads the given image file(s) from disk,
    makes a dedicated gateway-routed vision call with tool_choice pinned to a
    tool whose input_schema is built from `fields`, and returns the model's
    validated JSON directly — not prose the calling model has to reformat and
    potentially transcribe wrong (e.g. a numeric fee).

    Returns None (not an error dict) on any failure — missing/bad file,
    gateway/auth failure, or the model declining to call the tool — so the
    caller can fall back to the existing prose-based behavior silently.
    """
    import base64
    import os
    import anthropic
    from llm.gateway import gateway_headers, get_gateway_url, profile_headers
    from llm.registry import get_active_profile, get_active_model

    content = []
    for p in image_paths:
        if not isinstance(p, str):
            return None
        path = Path(p)
        media_type = _IMAGE_MEDIA_TYPES.get(path.suffix.lower())
        if not media_type or not path.exists():
            return None
        try:
            data = base64.b64encode(path.read_bytes()).decode()
        except Exception:
            return None
        content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}})
    if not content:
        return None
    content.append({
        "type": "text",
        "text": "Extract exactly these fields from the image(s) above and call extract_fields with your answer. "
                "Use an empty string for any field you cannot find with confidence — do not guess.",
    })

    extract_tool = {
        "name": "extract_fields",
        "description": "Return the requested fields extracted from the image(s).",
        "input_schema": {
            "type": "object",
            "properties": {f: {"type": "string"} for f in fields},
            "required": fields,
        },
    }

    # Same api_key/header/base_url resolution as create_gateway_chat_anthropic
    # (llm/gateway.py) — this app's real config is profile-based, so
    # shared.cfg["api_key"] alone is empty in the common case; profile_headers
    # is preferred over the legacy gateway_headers() for the same reason
    # create_gateway_chat_anthropic prefers it (correct subscription-key
    # header even when GATEWAY_KEY_HEADER isn't set).
    profile = get_active_profile()
    api_key = (
        (profile.get("api_key") if profile else "")
        or shared.cfg.get("api_key", "")
        or os.environ.get("ANTHROPIC_API_KEY", "")
    )
    if not api_key:
        return None
    base_url = (profile.get("anthropic_url") if profile else "") or f"{get_gateway_url()}/"
    try:
        extra_headers = profile_headers(profile) if profile else gateway_headers(api_key)
    except Exception:
        extra_headers = gateway_headers(api_key)
    model = get_active_model() or shared.cfg.get("model", "claude-opus-4-7")

    client = anthropic.Anthropic(
        api_key=api_key,
        base_url=base_url,
        default_headers=extra_headers or None,
    )
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=1024,
            tools=[extract_tool],
            tool_choice={"type": "tool", "name": "extract_fields"},
            messages=[{"role": "user", "content": content}],
        )
    except Exception:
        return None

    for block in msg.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "extract_fields":
            return {"ok": True, "task": "extract_data", "extracted": block.input}
    return None


async def _analyze_frame_sequence(image_paths: list, fps: float = 0.2) -> dict | None:
    """Read video frames from disk and return a per-frame timeline via vision API.

    Uses httpx.AsyncClient instead of the synchronous Anthropic SDK so the
    uvicorn event loop is never blocked — even on large payloads / slow gateways.
    Hard-capped at 8 frames; callers must slice before passing.
    """
    import asyncio, base64, json, os
    import httpx
    from llm.gateway import gateway_headers, get_gateway_url, profile_headers
    from llm.registry import get_active_profile, get_active_model

    MAX_FRAMES = 8
    image_paths = image_paths[:MAX_FRAMES]

    content = []
    frame_meta = []
    for i, p in enumerate(image_paths):
        if not isinstance(p, str):
            return None
        path = Path(p)
        media_type = _IMAGE_MEDIA_TYPES.get(path.suffix.lower())
        if not media_type or not path.exists():
            continue
        try:
            data = base64.b64encode(path.read_bytes()).decode()
        except Exception:
            continue
        time_sec = round(i / fps) if fps > 0 else i * 5
        time_label = f"{time_sec // 60:02d}:{time_sec % 60:02d}"
        content.append({
            "type": "text",
            "text": f"--- Frame {i + 1}: {path.name} (timestamp {time_label}) ---",
        })
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": data},
        })
        frame_meta.append({"frame": path.name, "time_sec": time_sec, "time_label": time_label})

    if not frame_meta:
        return None

    content.append({
        "type": "text",
        "text": (
            "These are sequential frames from a screen recording. "
            "For each labeled frame, describe: (1) what application/UI is visible, "
            "(2) what action is happening or has just happened, "
            "(3) any visible text, results, or responses on screen. "
            "Be concise — 1-2 sentences per frame. "
            "Call the analyze_frames tool with your analysis."
        ),
    })

    analyze_tool = {
        "name": "analyze_frames",
        "description": "Return per-frame descriptions for the video sequence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "frames": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "frame": {"type": "string"},
                            "description": {"type": "string"},
                        },
                        "required": ["frame", "description"],
                    },
                },
                "summary": {
                    "type": "string",
                    "description": "One paragraph summarizing the entire recording.",
                },
            },
            "required": ["frames", "summary"],
        },
    }

    profile = get_active_profile()
    api_key = (
        (profile.get("api_key") if profile else "")
        or shared.cfg.get("api_key", "")
        or os.environ.get("ANTHROPIC_API_KEY", "")
    )
    if not api_key:
        return None
    base_url = (profile.get("anthropic_url") if profile else "") or f"{get_gateway_url()}/"
    base_url = base_url.rstrip("/")
    try:
        extra_headers = profile_headers(profile) if profile else gateway_headers(api_key)
    except Exception:
        extra_headers = gateway_headers(api_key)
    model = get_active_model() or shared.cfg.get("model", "claude-opus-4-7")

    payload = {
        "model": model,
        "max_tokens": 4096,
        "tools": [analyze_tool],
        "tool_choice": {"type": "tool", "name": "analyze_frames"},
        "messages": [{"role": "user", "content": content}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
        **(extra_headers or {}),
    }

    _err = None
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{base_url}/v1/messages", json=payload, headers=headers)
        if r.status_code >= 400:
            body = r.text
            if len(body) > 500:
                body = body[:500] + f"...[+{len(body) - 500} chars]"
            _err = f"Gateway returned HTTP {r.status_code} for vision analysis: {body}"
            _log.error("describe_images.analyze_sequence: %s", _err)
            return {"ok": False, "error": _err}
        msg = r.json()
    except httpx.TimeoutException as e:
        _err = f"Vision analysis timed out after 120s calling {base_url}/v1/messages (model={model}, frames={len(frame_meta)}). The gateway or upstream LLM did not respond. Retry with fewer frames or check gateway health."
        _log.error("describe_images.analyze_sequence: %s [%s: %s]", _err, type(e).__name__, e)
        return {"ok": False, "error": _err}
    except httpx.HTTPError as e:
        _err = f"Network error calling gateway for vision analysis: {type(e).__name__}: {e}"
        _log.error("describe_images.analyze_sequence: %s", _err)
        return {"ok": False, "error": _err}
    except Exception as e:
        _err = f"Unexpected error during vision analysis: {type(e).__name__}: {e}"
        _log.error("describe_images.analyze_sequence: %s", _err)
        return {"ok": False, "error": _err}

    for block in (msg.get("content") or []):
        if block.get("type") == "tool_use" and block.get("name") == "analyze_frames":
            inp = block.get("input", {})
            raw_frames = inp.get("frames", [])
            timeline = []
            for i, rf in enumerate(raw_frames):
                meta = frame_meta[i] if i < len(frame_meta) else {}
                timeline.append({
                    "frame": rf.get("frame", meta.get("frame", "")),
                    "time_sec": meta.get("time_sec", i * 5),
                    "time_label": meta.get("time_label", "00:00"),
                    "description": rf.get("description", ""),
                })
            return {
                "ok": True,
                "task": "analyze_sequence",
                "timeline": timeline,
                "summary": inp.get("summary", ""),
                "frame_count": len(timeline),
            }
    _err = (f"Vision analysis completed but the model did not call the analyze_frames tool "
            f"(model={model}, frames={len(frame_meta)}). Response had "
            f"{len(msg.get('content') or [])} content blocks.")
    _log.error("describe_images.analyze_sequence: %s", _err)
    return {"ok": False, "error": _err}


_SKILL_ALIASES = {"word": "docx", "powerpoint": "ppt", "outlook": "email", "excel": "xlsx",
                   "m365-calendar": "calendar"}


def _tool_read_skill(skill_id: str) -> dict:
    """Return the SKILL.md content for the requested skill so Claude can learn its capabilities."""
    skill_id = _SKILL_ALIASES.get(skill_id.lower(), skill_id)
    web_skills_root = ROOT / "web" / "skills"
    skill_md_path = web_skills_root / skill_id / "SKILL.md"
    result: dict = {}
    if skill_md_path.exists():
        result["skill_guide"] = skill_md_path.read_text(encoding='utf-8')
    if not result:
        # Also search user skill roots (installed marketplace + ~/.agents/skills)
        from config import USER_SKILL_DIRS
        for root in USER_SKILL_DIRS:
            if not root.exists():
                continue
            for candidate in root.rglob("SKILL.md"):
                if candidate.parent.name == skill_id:
                    result["skill_guide"] = candidate.read_text(encoding='utf-8')
                    break
            if result:
                break
    if not result:
        # Check if this is a registered MCP connection — no SKILL.md needed, describe its tools
        # g-* synthetic skills (g-gmail, g-sheets, etc.) route to the mcp-google-workspace connection
        ws_skill_id = skill_id
        if skill_id.startswith("g-") and not skill_id in shared.SKILL_TOOLS_MAP:
            ws_skill_id = next((sid for sid in shared.SKILL_TOOLS_MAP if sid.startswith("mcp-google-workspace")), skill_id)
        if ws_skill_id in shared.SKILL_TOOLS_MAP:
            tool_names = sorted(shared.SKILL_TOOLS_MAP[ws_skill_id])
            # For g-* synthetic skills, filter to only tools matching that service's prefix
            if skill_id.startswith("g-"):
                service_prefix = skill_id.removeprefix("g-")
                tool_names = [tn for tn in tool_names if service_prefix in tn.lower()]
            tool_descs = []
            for tn in tool_names:
                tool_def = next((t for t in shared.TOOLS if t["name"] == tn), None)
                if tool_def:
                    tool_descs.append(f"- `{tn}`: {tool_def.get('description', 'no description')}")
            conn_name = skill_id.removeprefix("mcp-").replace("-", " ").title()
            guide = f"# {conn_name} (MCP Connection)\n\nThis skill connects to an external MCP server.\n\n## Available Tools\n\n" + "\n".join(tool_descs)
            return {"skill_guide": guide}
        available = [d.name for d in web_skills_root.iterdir() if d.is_dir() and (d / "SKILL.md").exists()] if web_skills_root.exists() else []
        return {"error": f"No SKILL.md found for skill '{skill_id}'. Available skills: {available}"}
    return result


async def _tool_schedule_task(name, prompt, trigger_type, **kwargs):
    """Create a scheduled job via the scheduler module."""
    import scheduler as sched
    trigger_args = {}
    if trigger_type == "cron":
        if kwargs.get("cron_day_of_week"): trigger_args["day_of_week"] = kwargs["cron_day_of_week"]
        if kwargs.get("cron_hour") is not None: trigger_args["hour"] = kwargs["cron_hour"]
        trigger_args["minute"] = kwargs.get("cron_minute", 0)
        if kwargs.get("cron_timezone"): trigger_args["timezone"] = kwargs["cron_timezone"]
    elif trigger_type == "interval":
        mins = kwargs.get("interval_minutes", 0)
        if mins < 1: return {"error": "interval_minutes must be >= 1"}
        trigger_args["minutes"] = mins
    elif trigger_type == "date":
        if not kwargs.get("run_date"): return {"error": "run_date required for one-shot schedules"}
        trigger_args["run_date"] = kwargs["run_date"]
    else:
        return {"error": f"Unknown trigger_type: {trigger_type}"}
    end_date = kwargs.get("end_date") or None
    skills = kwargs.get("skills") or []
    # Auto-bind the job to the tab it was created from, so pinned items
    # in that tab get injected on every run. _context_id is server-injected
    # by execute_tool — the LLM never supplies it. Skip the "default" sentinel
    # to avoid binding ad-hoc chats with no real tab identity.
    _ctx = kwargs.get("_context_id")
    tab_context_id = _ctx if _ctx and _ctx != "default" else None
    job = await sched.add_job(name=name, prompt=prompt, trigger_type=trigger_type,
                               trigger_args=trigger_args, token_budget=kwargs.get("token_budget", 50000),
                               end_date=end_date, skills=skills,
                               tab_context_id=tab_context_id)
    end_note = f" (runs until {end_date})" if end_date else ""
    return {"ok": True, "job_id": job["job_id"], "name": name,
            "next_run_time": job.get("next_run_time"),
            "message": f"Scheduled '{name}' successfully{end_note}. View in the Agents pane."}


async def _tool_list_schedules():
    """List all scheduled jobs."""
    import scheduler as sched
    jobs = await sched.list_jobs()
    return {"ok": True, "jobs": jobs, "message": "No scheduled tasks." if not jobs else None}


def _tool_analyze_mcp_server(raw_input: str) -> str:
    result = _normalize_mcp(raw_input)
    if not result.ok:
        return (
            f"I couldn't recognize that format ({result.error}). "
            "Please try pasting a GitHub URL, a JSON config snippet, a server URL, "
            "or a command like `npx @playwright/mcp@latest`."
        )
    lines = []
    if result.confidence in ("low", "medium"):
        lines.append("⚠ I'm not fully certain — please review before confirming.")
    if result.transport == "stdio":
        lines.append(f"Found **{result.name}** — local MCP server (stdio)")
        lines.append(f"Runs: `{result.command} {' '.join(result.args)}`")
        if result.prerequisite_warning:
            lines.append(f"Note: {result.prerequisite_warning}")
    else:
        lines.append(f"Found **{result.name}** — remote MCP server (HTTP)")
        lines.append(f"URL: `{result.url}`")
    lines.append("")
    lines.append("Want me to add it?")
    return "\n".join(lines)


def _tool_connect_mcp_server(
    transport: str, name: str,
    url: str = "", auth_type: str = "none", auth_value: str = "",
    command: str = "", args: list = None, env: dict = None,
) -> str:
    payload = {
        "transport": transport, "name": name,
        "url": url, "auth_type": auth_type, "auth_value": auth_value,
        "command": command, "args": args or [], "env": env or {},
    }
    try:
        data = _save_mcp_connection(payload)
    except Exception as e:
        return f"Connection failed: {e}"
    if data.get("ok"):
        tool_count = data.get("tool_count", 0)
        status = data.get("status")
        name = data.get("name", name)
        if status == "connecting":
            return (
                f"✓ **{name}** is connecting in the background. "
                f"It may take up to 2 minutes for tools to appear. "
                f"Check Settings > Connections to monitor progress."
            )
        return f"✓ **{name}** added successfully ({tool_count} tool{'s' if tool_count != 1 else ''} available). Use `/{name.lower()}` to activate it."
    return f"Connection failed: {data.get('error', 'unknown error')}"


def _mcp_list_with_status() -> list:
    """Wrapper so tests can patch this cleanly (see _normalize_mcp above)."""
    from mcp.manager import list_with_status
    return list_with_status()


_CE_MAX = 200


def _sanitize_connect_error(msg: str) -> str:
    """Strip embedded credentials from an MCP connect-error before surfacing it
    to the model: URL userinfo credentials and sensitive query-string values
    such as tokens, keys, secrets, passwords, API keys, and authorization data.
    Truncate to a bounded length. Defensive: connect_error can echo a server URL
    that a plugin baked a literal credential into, and this tool is the first
    thing to pipe that field into the model's context (unlike the Settings UI,
    which only shows it to the user). Consistent with the milestone's "never
    surface a credential-bearing field unmasked" posture."""
    if not msg:
        return ""
    s = str(msg)
    s = re.sub(r"(\w+://)[^/@\s]*@", r"\1", s)
    s = re.sub(
        r"([?&](?:[^=&\s]*(?:token|key|secret|password|apikey|auth|access)[^=&\s]*)=)[^&\s]+",
        r"\1REDACTED",
        s,
        flags=re.IGNORECASE,
    )
    if len(s) > _CE_MAX:
        s = s[:_CE_MAX] + "…"
    return s


def _tool_mcp_connection_status(filter: str = "") -> dict:
    """Report setup/connection status for MCP connections, built entirely on
    top of mcp.manager.list_with_status()'s already-masked, UI-safe rows —
    SECURITY: never reads raw connection records or config.json directly, and
    never surfaces a field (auth_value, env, extra_headers, etc.) that
    list_with_status() doesn't already expose to the Settings > Connections UI.
    """
    rows = _mcp_list_with_status()
    needle = (filter or "").strip().lower()
    if needle:
        rows = [
            r for r in rows
            if needle in str(r.get("id", "")).lower()
            or needle in str(r.get("name", "")).lower()
            or needle in str(r.get("plugin_id", "")).lower()
        ]
        if not rows:
            return {
                "connections": [],
                "message": f"No MCP connection matches '{filter}'. It may not be installed yet.",
            }

    connections = []
    for r in rows:
        enabled = bool(r.get("enabled", False))
        tool_count = r.get("tool_count", 0) or 0
        missing_secrets = r.get("missing_secrets") or []
        connect_error = _sanitize_connect_error(r.get("connect_error") or "")
        needs_setup = (not enabled) and bool(missing_secrets)

        if enabled and tool_count > 0:
            # connect_error takes priority — health_check writes it back when
            # the server is down, so "Ready" must not override a known failure.
            if connect_error:
                status = f"Connection error: {connect_error}"
            else:
                status = "Ready"
        elif needs_setup:
            status = "Needs setup — open Settings → Connections and click Complete setup"
        elif connect_error:
            status = f"Connection error: {connect_error}"
        elif not enabled:
            status = "Disabled"
        else:
            status = "Enabled (no tools discovered yet)"

        entry = {
            "id": r.get("id"),
            "name": r.get("name"),
            "enabled": enabled,
            "tool_count": tool_count,
            "needs_setup": needs_setup,
            "status": status,
        }
        if r.get("plugin_id"):
            entry["plugin_id"] = r["plugin_id"]
        if missing_secrets:
            entry["missing_secrets"] = missing_secrets
        if connect_error:
            entry["connect_error"] = connect_error
        connections.append(entry)

    return {"connections": connections, "message": None}


TOOL_HANDLERS = {
    "describe_images": _tool_describe_images,
    "fetch_webpage": _tool_fetch_webpage,
    "web_search": _tool_web_search,
    "read_skill": _tool_read_skill,
    "schedule_task": _tool_schedule_task,
    "list_schedules": _tool_list_schedules,
    "analyze_mcp_server": _tool_analyze_mcp_server,
    "connect_mcp_server": _tool_connect_mcp_server,
    "mcp_connection_status": _tool_mcp_connection_status,
}
