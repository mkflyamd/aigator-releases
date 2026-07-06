"""Always-on skill -- 3 tools (always available regardless of active skill)."""
import json
import re
import urllib.request
from pathlib import Path

import shared
import dataclasses
import urllib.request as _urllib
from mcp.normalizer import normalize as _normalize, NormalizeResult as _NR, _make_gateway_llm
from mcp.url_fetcher import url_fetcher as _url_fetcher

ROOT = Path(__file__).parent.parent.parent.parent

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
        "description": "Signal intent to describe, compare, or analyze images the user has uploaded in this conversation. Claude already has the images as vision input \u2014 calling this tool triggers visual analysis. Use task='describe' for a single image, 'compare' for two images, 'extract_data' to extract text/data from images, 'assess' to generate a structured assessment report.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "enum": ["describe", "compare", "extract_data", "assess"], "description": "What visual analysis task to perform"},
            },
            "required": ["task"],
        },
    },
    {
        "name": "fetch_webpage",
        "description": "Fetch and read the content of any public webpage URL. Use when the user shares a link (GitHub issue, documentation, blog post, article, etc.) and asks you to read or analyze it. Returns the page content as plain text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The full URL to fetch (must start with http:// or https://)"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "read_skill",
        "description": "Read the full capability guide (SKILL.md) and manifest for an installed skill. Call this when the user asks what a skill can do, or before invoking skill-specific tools for the first time in a session. skill_id examples: 'calendar', 'excel', 'email'.",
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
]

TOOL_STATUS = {
    "describe_images": "\U0001f5bc\ufe0f Analyzing images...",
    "fetch_webpage": "\U0001f310 Fetching webpage...",
    "read_skill": "\U0001f4d6 Reading skill guide...",
    "schedule_task": "\U0001f4c5 Creating schedule...",
    "list_schedules": "\U0001f4cb Checking schedules...",
    "analyze_mcp_server": "\U0001f50e Analyzing MCP server...",
    "connect_mcp_server": "\U0001f517 Connecting MCP server...",
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
            f"This page is protected by {blocker}, which requires a JavaScript-capable "
            f"browser to pass a challenge. AI Gator's fetch tool retrieves raw HTML and "
            f"cannot execute JavaScript, so it can't get past this. Open the link directly "
            f"in your browser instead: {url}"
        ),
        "blocked_by": blocker,
        "js_challenge": True,
        "url": url,
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
        return {"error": f"HTTP {e.code}: {e.reason}", "url": url}
    except Exception as e:
        return {"error": str(e), "url": url}


def _tool_describe_images(task: str) -> dict:
    return {"ok": True, "task": task, "instruction": "Perform the visual analysis now in your response text based on the images in this conversation."}


_SKILL_ALIASES = {"word": "docx", "powerpoint": "ppt", "outlook": "email", "excel": "xlsx"}


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
        if skill_id in shared.SKILL_TOOLS_MAP:
            tool_names = sorted(shared.SKILL_TOOLS_MAP[skill_id])
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
        return f"✓ **{data.get('name', name)}** added successfully ({tool_count} tool{'s' if tool_count != 1 else ''} available). Use `/{name.lower()}` to activate it."
    return f"Connection failed: {data.get('error', 'unknown error')}"


TOOL_HANDLERS = {
    "describe_images": _tool_describe_images,
    "fetch_webpage": _tool_fetch_webpage,
    "read_skill": _tool_read_skill,
    "schedule_task": _tool_schedule_task,
    "list_schedules": _tool_list_schedules,
    "analyze_mcp_server": _tool_analyze_mcp_server,
    "connect_mcp_server": _tool_connect_mcp_server,
}
