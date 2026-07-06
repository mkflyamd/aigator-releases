# web/mcp/url_fetcher.py
"""Fetch MCP config from URLs — GitHub READMEs and generic documentation pages.

Replaces github_fetcher.py. Handles two cases:
  1. github.com repo URLs  → fetch README, extract JSON code fences (deterministic)
  2. Known doc-page domains → fetch HTML, strip to plain text, LLM-extract config

Returns NormalizeResult | None. None means "couldn't extract — fall through."
"""
from __future__ import annotations

import ipaddress
import json
import re
from urllib.parse import urlparse

import httpx

from mcp.normalizer import NormalizeResult, _try_json, _try_bare_command, GITHUB_API_BASE, _DANGEROUS

# ── Known MCP servers by doc-page URL pattern ─────────────────────────────────
# Many official MCP doc pages are JavaScript-rendered SPAs — raw HTTP fetch gets
# only the shell, not the content. For these we skip fetching entirely and return
# the known server config directly.
#
# Key: substring that must appear in the URL (lowercased).
# Value: NormalizeResult kwargs to return immediately.
_KNOWN_DOC_URLS: list[tuple[str, dict]] = [
    (
        "developers.google.com/workspace/gmail",
        {
            "transport": "http",
            "name": "Gmail",
            "url": "https://gmailmcp.googleapis.com/mcp/v1",
            "source": "doc_page",
            "confidence": "high",
        },
    ),
    (
        "developers.google.com/workspace/calendar",
        {
            "transport": "http",
            "name": "Google Calendar",
            "url": "https://calendarmcp.googleapis.com/mcp/v1",
            "source": "doc_page",
            "confidence": "high",
        },
    ),
    (
        "developers.google.com/workspace/drive",
        {
            "transport": "http",
            "name": "Google Drive",
            "url": "https://drivemcp.googleapis.com/mcp/v1",
            "source": "doc_page",
            "confidence": "high",
        },
    ),
]

# Domains that serve documentation pages (not MCP servers themselves).
# When a URL matches one of these, we fetch the page and try LLM extraction.
_DOC_DOMAINS = {
    "developers.google.com",
    "docs.anthropic.com",
    "docs.github.com",
    "learn.microsoft.com",
    "docs.aws.amazon.com",
    "platform.openai.com",
    "modelcontextprotocol.io",
    "glama.ai",
    "smithery.ai",
    "mcp.so",
}

# HTML stripping — cap input BEFORE applying DOTALL regex to avoid catastrophic
# backtracking on large/malformed pages (e.g. React SPAs with unclosed <script>).
_HTML_PRE_CAP = 300_000  # chars — process at most ~300K chars of raw HTML

_STRIP_TAGS = re.compile(
    r"<(script|style|nav|header|footer|aside|noscript)[^>]*>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)
_HTML_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\n{3,}")


def _html_to_text(html: str) -> str:
    """Strip HTML to plain readable text. Caps input first to prevent regex backtracking."""
    html = html[:_HTML_PRE_CAP]
    text = _STRIP_TAGS.sub("", html)
    text = _HTML_TAG.sub("\n", text)
    text = _WHITESPACE.sub("\n\n", text)
    return text.strip()


def _is_safe_mcp_url(url: str) -> bool:
    """Return True only for http/https URLs pointing to routable non-private hosts.

    Blocks: file://, javascript:, ftp://, internal IPs (127.x, 10.x, 192.168.x,
    169.254.x AWS IMDS, ::1, etc.), and shell metacharacters in the URL string.
    """
    if not url:
        return False
    # Reject shell metacharacters in URL
    if any(c in url for c in _DANGEROUS):
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname or ""
    if not host:
        return False
    # Reject bare IP addresses that are private/loopback/link-local
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            return False
    except ValueError:
        pass  # hostname, not a bare IP — allow
    return True


# ── GitHub README fetcher (deterministic) ─────────────────────────────────────

def _parse_github_url(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url.strip())
    if parsed.hostname not in ("github.com", "www.github.com"):
        return None
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) >= 2:
        return parts[0], parts[1].removesuffix(".git")
    return None


# Known MCP launcher commands — only try bare-command extraction from fences
# that start with one of these to avoid false positives from shell usage examples
# like `node server.js` or `docker run ...` in README installation sections.
_MCP_LAUNCHERS = {"npx", "uvx", "python", "python3"}


def _fetch_github(url: str) -> NormalizeResult | None:
    """Fetch README for a public GitHub repo and extract MCP configs from code fences."""
    parsed = _parse_github_url(url)
    if not parsed:
        return None
    owner, repo = parsed

    try:
        meta = httpx.get(f"{GITHUB_API_BASE}/repos/{owner}/{repo}", timeout=10).json()
        branch = meta.get("default_branch", "main")
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/README.md"
        readme = httpx.get(raw_url, timeout=10).text
    except Exception:
        return None

    # Extract all fenced code blocks (```json or plain ```)
    fences = re.findall(r"```(?:json)?\s*\n(.*?)\n```", readme, re.DOTALL)
    results: list[NormalizeResult] = []
    for fence in fences:
        stripped = fence.strip()
        r = _try_json(stripped)
        results.extend(r)
        if not r:
            # Only try bare-command on fences that start with a known MCP launcher
            # (npx/uvx/python/python3) to avoid false positives from shell examples.
            first_token = stripped.split()[0].lower() if stripped.split() else ""
            if first_token in _MCP_LAUNCHERS:
                cmd = _try_bare_command(stripped)
                if cmd:
                    results.append(cmd)

    if not results:
        return None

    for r in results:
        r.source = "github_readme"

    if len(results) == 1:
        return results[0]

    first = results[0]
    first.confidence = "medium"
    first.all_results = list(results)
    return first


# ── Generic doc-page fetcher (LLM-assisted) ───────────────────────────────────

_DOC_LLM_PROMPT = """\
The text below is from a documentation page that describes how to configure an MCP server.
Extract the MCP server configuration for a generic MCP client (not specific to any one app).

Return ONLY a JSON object with these exact fields:
{{
  "transport": "http" or "stdio",
  "name": "server display name",
  "url": "MCP server URL (for http transport, else empty string)",
  "command": "command to run (for stdio transport, else empty string)",
  "args": ["arg1", "arg2"],
  "env": {{"KEY": "value"}}
}}

Rules:
- Return ONLY the JSON object, no markdown fences, no explanation.
- If you cannot find a valid MCP server config, return {{"ok": false}}.
- Never invent values — only extract what is present in the text.
- For http transport, the url must be an MCP server endpoint (e.g. https://gmailmcp.googleapis.com/mcp/v1), NOT a documentation page URL.
- transport must be exactly "http" or "stdio".
- For env values that require user-supplied secrets, use empty string "" as the value.

Documentation text:
{text}"""


def _fetch_doc_page(url: str, llm) -> NormalizeResult | None:
    """Fetch a documentation page and LLM-extract MCP config from its content."""
    if llm is None:
        return None
    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True,
                         headers={"User-Agent": "aigator/1.0 (MCP-Config-Extractor)"})
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "html" not in content_type and "text" not in content_type:
            return None
        text = _html_to_text(resp.text)
    except Exception:
        return None

    # Limit to first 6000 chars — enough to cover installation sections without
    # blowing the LLM context for a simple config extraction task.
    truncated = text[:6000]

    try:
        raw = llm(_DOC_LLM_PROMPT.format(text=truncated))
        data = json.loads(raw)
    except Exception:
        return None

    if data.get("ok") is False:
        return None

    transport = data.get("transport", "")
    if transport not in ("http", "stdio"):
        return None

    name = str(data.get("name", "mcp") or "mcp")
    mcp_url = str(data.get("url", "") or "")
    cmd = str(data.get("command", "") or "")

    if transport == "http":
        # Security: reject doc-page URL echoed back, private IPs, bad schemes, shell chars
        if not _is_safe_mcp_url(mcp_url):
            return None
        # Reject if LLM returned the doc page URL itself (exact or normalised)
        doc_host = urlparse(url).hostname or ""
        mcp_host = urlparse(mcp_url).hostname or ""
        if mcp_host and mcp_host == doc_host:
            return None
        return NormalizeResult(
            ok=True, transport="http", name=name, url=mcp_url,
            source="doc_page", confidence="medium",
        )
    else:
        if not cmd:
            return None
        # Security: reject shell metacharacters in command and args
        if any(c in cmd for c in _DANGEROUS):
            return None
        args = [str(a) for a in data.get("args", [])]
        if any(any(c in a for c in _DANGEROUS) for a in args):
            return None
        env = {str(k): str(v) for k, v in (data.get("env") or {}).items()}
        return NormalizeResult(
            ok=True, transport="stdio", name=name, command=cmd, args=args, env=env,
            source="doc_page", confidence="medium",
            prerequisite_warning=f"{cmd} must be installed on your machine",
        )


# ── Public entry point ────────────────────────────────────────────────────────

def is_doc_page_url(url: str) -> bool:
    """Return True if this URL looks like a documentation page rather than an MCP server."""
    try:
        host = urlparse(url).hostname or ""
        return host in _DOC_DOMAINS or any(host.endswith("." + d) for d in _DOC_DOMAINS)
    except Exception:
        return False


def _check_known_doc_urls(url: str) -> NormalizeResult | None:
    """Return a hardcoded result for known JS-rendered doc pages that can't be fetched."""
    url_lower = url.lower()
    for pattern, kwargs in _KNOWN_DOC_URLS:
        if pattern in url_lower:
            return NormalizeResult(ok=True, **kwargs)
    return None


def url_fetcher(url: str, llm=None) -> NormalizeResult | None:
    """Main entry point. Tries in order:
    1. Known doc-page URL patterns (hardcoded — handles JS-rendered SPAs)
    2. GitHub README code-fence extraction (deterministic)
    3. Generic doc-page LLM extraction (for server-rendered pages)

    Returns None if extraction failed — caller falls through to next layer.
    """
    # Check hardcoded known URLs first — avoids fetching JS-rendered SPAs
    known = _check_known_doc_urls(url)
    if known is not None:
        return known

    # GitHub: deterministic extraction from README code fences
    if _parse_github_url(url):
        return _fetch_github(url)

    # Known doc domains: LLM-assisted extraction from page content
    if is_doc_page_url(url) and llm is not None:
        return _fetch_doc_page(url, llm)

    return None


# Backwards-compat alias
github_fetcher = url_fetcher
