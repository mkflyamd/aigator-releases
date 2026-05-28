# web/mcp/normalizer.py
"""Universal MCP config normalizer — accepts any input format, returns a structured result.

Layers (tried in order, first success wins):
  1. URL detection (bare URL → remote HTTP, github.com URL → README fetch)
  2. JSON parsers (7 sub-formats)
  3. TOML parser (Codex [mcp_servers.*] format)
  4. Bare command sniffer (npx / uvx / python / node / docker)
  5. LLM fallback (injected callable — gateway in prod, mock in tests)
  6. Failure (ok=False)

Call: normalize(raw_text, fetcher=None, llm=None) → NormalizeResult
fetcher: callable(url: str) → NormalizeResult | None  (for GitHub fetch)
llm:     callable(prompt: str) → str                  (for LLM fallback)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlparse

# ── Feature flags ────────────────────────────────────────────────────────────
LLM_FALLBACK_ENABLED = True
GITHUB_FETCH_ENABLED = True
GITHUB_API_BASE = "https://api.github.com"
LLM_FALLBACK_CONFIDENCE = "low"

# ── Known stdio launchers ─────────────────────────────────────────────────────
_KNOWN_LAUNCHERS = {"npx", "uvx", "python", "python3", "node", "docker", "deno", "bun"}

# ── Shell metacharacter guard ─────────────────────────────────────────────────
_DANGEROUS = set(";& |><$`")


# ── Placeholder helpers ───────────────────────────────────────────────────────

_PLACEHOLDER_RE = re.compile(r'\{([A-Za-z_][A-Za-z0-9_]*)\}')


def _find_placeholders(d: dict) -> list[str]:
    """Return variable names from {variable} patterns in dict string values. Order-preserving, no duplicates."""
    seen: set[str] = set()
    result: list[str] = []
    for v in d.values():
        if isinstance(v, str):
            for m in _PLACEHOLDER_RE.finditer(v):
                name = m.group(1)
                if name not in seen:
                    seen.add(name)
                    result.append(name)
    return result


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class NormalizeResult:
    ok: bool
    transport: str = ""          # "http" | "stdio"
    name: str = ""
    # remote:
    url: str = ""
    auth_type: str = "none"      # "none" | "bearer" | "api_key"
    auth_value: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    # stdio:
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    # metadata:
    source: str = ""             # "json_mcpservers" | "json_servers" | "registry_schema" |
                                 # "toml" | "github_readme" | "url" | "bare_command" | "llm"
    confidence: str = "high"     # "high" | "medium" | "low"
    all_results: list = field(default_factory=list)   # populated when multiple found
    prerequisite_warning: str = ""
    error: str = ""


# ── Layer 2: JSON parsers ─────────────────────────────────────────────────────

def _url_to_name(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    return path.split("/")[-1] or urlparse(url).netloc or "mcp"


def _parse_server_entry(name: str, server: dict) -> NormalizeResult | None:
    """Parse one entry from mcpServers / servers dict."""
    if not isinstance(server, dict):
        return None
    # stdio: has "command"
    if "command" in server and server["command"]:
        cmd = str(server["command"])
        # Reject shell metacharacters — guard against injection via untrusted JSON
        if any(c in cmd for c in _DANGEROUS):
            return None
        args = [str(a) for a in server.get("args", [])]
        env = {str(k): str(v) for k, v in server.get("env", {}).items()}
        # Only warn for commands the app doesn't bundle (not python/python3 — those are included)
        _BUNDLED = {"python", "python3"}
        warning = "" if cmd.lower() in _BUNDLED else f"{cmd} must be installed on your machine"
        return NormalizeResult(
            ok=True, transport="stdio", name=name,
            command=cmd, args=args, env=env,
            source="json_mcpservers", confidence="high",
            prerequisite_warning=warning,
        )
    # remote: has "url"
    if "url" in server and server["url"]:
        raw_hdrs = server.get("headers", {})
        headers = {str(k): str(v) for k, v in raw_hdrs.items()} if isinstance(raw_hdrs, dict) else {}
        return NormalizeResult(
            ok=True, transport="http", name=name,
            url=str(server["url"]),
            headers=headers,
            source="json_mcpservers", confidence="high",
        )
    return None


def _try_json(text: str) -> list[NormalizeResult]:
    """Try all JSON sub-formats. Returns list of results (empty if none match)."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []

    results: list[NormalizeResult] = []

    # Sub-format 1+2+3: mcpServers key (Claude Desktop / Cursor / Claude Code)
    if "mcpServers" in data and isinstance(data["mcpServers"], dict):
        for name, server in data["mcpServers"].items():
            r = _parse_server_entry(name, server)
            if r:
                results.append(r)
        if results:
            return results

    # Sub-format 4: servers key (VS Code)
    if "servers" in data and isinstance(data["servers"], dict):
        for name, server in data["servers"].items():
            r = _parse_server_entry(name, server)
            if r:
                r.source = "json_servers"
                results.append(r)
        if results:
            return results

    # Sub-format 5: remotes array (MCP registry schema)
    if "remotes" in data and isinstance(data["remotes"], list):
        name = data.get("title") or data.get("name", "mcp").split("/")[-1]
        for remote in data["remotes"]:
            if isinstance(remote, dict) and remote.get("url"):
                results.append(NormalizeResult(
                    ok=True, transport="http", name=str(name),
                    url=str(remote["url"]),
                    source="registry_schema", confidence="high",
                ))
        # Always return after seeing remotes key — don't fall through to bare-object formats
        return results

    # Sub-format 7: bare URL object {"url": "https://..."}
    if "url" in data and isinstance(data.get("url"), str) and data["url"] and "command" not in data:
        url = data["url"]
        return [NormalizeResult(
            ok=True, transport="http", name=_url_to_name(url),
            url=url, source="json_mcpservers", confidence="high",
        )]

    # Sub-format 6: bare server object {"command": ...}
    r = _parse_server_entry("mcp", data)
    if r:
        r.source = "json_mcpservers"
        return [r]

    return []


# ── Layer 1: URL helpers ──────────────────────────────────────────────────────

def _looks_like_url(text: str) -> bool:
    t = text.strip()
    return t.startswith("http://") or t.startswith("https://")


def _is_github_repo_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    if parsed.netloc not in ("github.com", "www.github.com"):
        return False
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    return len(parts) >= 2


# ── Layer 3: TOML parser ──────────────────────────────────────────────────────

def _try_toml(text: str) -> list[NormalizeResult]:
    """Parse Codex-style TOML: [mcp_servers.name] sections with url = "..." entries."""
    results: list[NormalizeResult] = []
    current_name: str | None = None
    current_url: str | None = None

    for line in text.splitlines():
        stripped = line.strip()
        m = re.match(r"^\[mcp_servers\.(.+)\]$", stripped)
        if m:
            if current_name and current_url:
                results.append(NormalizeResult(
                    ok=True, transport="http",
                    name=current_name, url=current_url,
                    source="toml", confidence="high",
                ))
            current_name = m.group(1)
            current_url = None
        else:
            m2 = re.match(r'^url\s*=\s*"(.+)"$', stripped)
            if m2 and current_name:
                current_url = m2.group(1)

    if current_name and current_url:
        results.append(NormalizeResult(
            ok=True, transport="http",
            name=current_name, url=current_url,
            source="toml", confidence="high",
        ))
    return results


# ── Layer 4: Bare command ─────────────────────────────────────────────────────

def _try_bare_command(text: str) -> NormalizeResult | None:
    """Detect 'npx foo' / 'uvx foo' / 'python -m foo' style command lines."""
    t = text.strip()
    if "{" in t or not t:
        return None
    tokens = t.split()
    if not tokens or tokens[0].lower() not in _KNOWN_LAUNCHERS:
        return None
    cmd = tokens[0]
    args = tokens[1:]
    # Derive a friendly name from the first arg that looks like a package
    if args:
        raw_name = args[0].lstrip("-")            # skip flags like --port
        name = raw_name.split("@")[0].split("/")[-1] or cmd
    else:
        name = cmd
    return NormalizeResult(
        ok=True, transport="stdio", name=name,
        command=cmd, args=args,
        source="bare_command", confidence="high",
        prerequisite_warning=f"{cmd} must be installed on your machine",
    )


# ── Layer 5: LLM fallback ─────────────────────────────────────────────────────

_LLM_PROMPT = """\
Extract the MCP server configuration from the text below.
Return ONLY a JSON object with these exact fields:
{{
  "transport": "http" or "stdio",
  "name": "server display name",
  "url": "server URL (for http transport, else empty string)",
  "command": "command to run (for stdio transport, else empty string)",
  "args": ["arg1", "arg2"],
  "env": {{"KEY": "value"}}
}}
Rules:
- Return ONLY the JSON object, no markdown fences, no explanation.
- If you cannot extract a valid config, return {{"ok": false}}.
- Never invent values — only extract what is present in the text.
- transport must be exactly "http" or "stdio".

Text:
{text}"""


def _try_llm(text: str, llm: Callable[[str], str] | None) -> NormalizeResult | None:
    if llm is None or not LLM_FALLBACK_ENABLED:
        return None
    try:
        raw = llm(_LLM_PROMPT.format(text=text))
        data = json.loads(raw)
    except Exception:
        return None

    if data.get("ok") is False:
        return None

    transport = data.get("transport", "")
    if transport not in ("http", "stdio"):
        return None

    name = str(data.get("name", "mcp") or "mcp")
    cmd = str(data.get("command", "") or "")
    url = str(data.get("url", "") or "")

    # Security: reject shell metacharacters in command or url
    if any(c in cmd for c in _DANGEROUS) or any(c in url for c in _DANGEROUS):
        return None

    if transport == "http":
        if not url:
            return None
        return NormalizeResult(
            ok=True, transport="http", name=name, url=url,
            source="llm", confidence=LLM_FALLBACK_CONFIDENCE,
        )
    else:
        if not cmd:
            return None
        args = [str(a) for a in data.get("args", [])]
        env = {str(k): str(v) for k, v in (data.get("env") or {}).items()}
        return NormalizeResult(
            ok=True, transport="stdio", name=name, command=cmd, args=args, env=env,
            source="llm", confidence=LLM_FALLBACK_CONFIDENCE,
            prerequisite_warning=f"{cmd} must be installed on your machine",
        )


def _make_gateway_llm() -> Callable[[str], str]:
    """Create a callable that sends a prompt to Claude via the configured LLM gateway."""
    import os
    import httpx
    from llm.gateway import gateway_headers, LLM_GATEWAY_URL

    def call(prompt: str) -> str:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        resp = httpx.post(
            f"{LLM_GATEWAY_URL}/v1/messages",
            headers={
                **gateway_headers(api_key),
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 512,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]

    return call


# ── Main entry point ──────────────────────────────────────────────────────────

def normalize(
    raw_text: str,
    fetcher: Callable[[str], "NormalizeResult | None"] | None = None,
    llm: Callable[[str], str] | None = None,
) -> NormalizeResult:
    """Normalize any MCP input to a structured NormalizeResult.

    Layers tried in order; first success wins.
    Pass fetcher=github_fetcher and llm=_make_gateway_llm() in production.
    """
    text = raw_text.strip()
    if not text:
        return NormalizeResult(ok=False, error="empty input")

    # Layer 1 — URL
    if _looks_like_url(text):
        if GITHUB_FETCH_ENABLED and _is_github_repo_url(text) and fetcher is not None:
            result = fetcher(text)
            if result is not None:
                return result
        # Any non-GitHub URL (or GitHub URL with no fetcher) → remote HTTP
        return NormalizeResult(
            ok=True, transport="http", url=text,
            name=_url_to_name(text), source="url", confidence="high",
        )

    # Layer 2 — JSON parsers
    json_results = _try_json(text)
    if json_results:
        if len(json_results) == 1:
            return json_results[0]
        first = json_results[0]
        first.confidence = "medium"
        first.all_results = json_results
        return first

    # Layer 3 — TOML
    toml_results = _try_toml(text)
    if toml_results:
        if len(toml_results) == 1:
            return toml_results[0]
        first = toml_results[0]
        first.confidence = "medium"
        first.all_results = toml_results
        return first

    # Layer 4 — Bare command
    cmd_result = _try_bare_command(text)
    if cmd_result:
        return cmd_result

    # Layer 5 — LLM fallback
    llm_result = _try_llm(text, llm)
    if llm_result:
        return llm_result

    # Layer 6 — Failure
    return NormalizeResult(ok=False, error="unrecognized format")
