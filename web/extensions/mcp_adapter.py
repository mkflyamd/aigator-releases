"""MCP setup adapter — wraps existing web/mcp/* machinery."""
from __future__ import annotations

from urllib.parse import urlparse

from .base import ExtensionAdapter, TestResult, InstallResult

from mcp.normalizer import normalize
# NOTE: `mcp.manager` is imported lazily inside the methods that use it.
# Top-level import here would create a cycle: mcp.manager → shared (which
# eagerly registers extension tools at import time) → extensions.registry →
# this module. Lazy import breaks the cycle without changing semantics.


_KNOWN_PROVIDERS: dict[str, dict] = {
    "mcp.atlassian.com": {
        "name": "Atlassian", "auth_type": "oauth2",
        "doc_url": "https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/",
    },
    "mcp.linear.app": {
        "name": "Linear", "auth_type": "bearer",
        "doc_url": "https://linear.app/settings/api",
    },
    "mcp.notion.com": {
        "name": "Notion", "auth_type": "bearer",
        "doc_url": "https://www.notion.so/profile/integrations",
    },
}


class MCPAdapter(ExtensionAdapter):
    extension_type = "mcp"
    config_schema = {
        "fields": [
            {"path": "name", "label": "Name", "type": "text"},
            {"path": "transport", "label": "Transport", "type": "select",
             "options": ["http", "stdio"]},
            {"path": "url", "label": "Server URL", "type": "text",
             "visible_if": "transport in (http)"},
            {"path": "auth_type", "label": "Auth", "type": "select",
             "options": ["none", "bearer", "api_key", "basic", "oauth2"],
             "visible_if": "transport in (http)"},
            {"path": "auth_value", "label": "Token", "type": "password",
             "visible_if": "auth_type in (bearer,api_key,basic)"},
            {"path": "headers", "label": "Headers", "type": "kv",
             "visible_if": "transport in (http)"},
            {"path": "command", "label": "Command", "type": "text",
             "visible_if": "transport=stdio"},
            {"path": "args", "label": "Args", "type": "list", "visible_if": "transport=stdio"},
        ]
    }

    def normalize(self, raw: str) -> dict:
        result = normalize(raw)
        if not getattr(result, "ok", False):
            return {}
        # Support mock objects (in tests) that expose to_entry(), and real
        # NormalizeResult objects which expose fields directly.
        if hasattr(result, "to_entry") and callable(result.to_entry):
            return result.to_entry()
        # Build dict from NormalizeResult fields
        out: dict = {
            "transport": result.transport,
            "name": result.name,
        }
        if result.transport == "http":
            out["url"] = result.url
            out["auth_type"] = result.auth_type
            if result.auth_value:
                out["auth_value"] = result.auth_value
            if result.headers:
                out["headers"] = result.headers
        else:
            out["command"] = result.command
            out["args"] = result.args
            if result.env:
                out["env"] = result.env
        if result.prerequisite_warning:
            out["_prerequisite_warning"] = result.prerequisite_warning
        return out

    def prefill_from_url(self, url: str) -> dict:
        host = (urlparse(url).hostname or "").lower()
        hint = _KNOWN_PROVIDERS.get(host, {})
        out: dict = {"transport": "http", "url": url}
        if hint:
            out["name"] = hint["name"]
            out["auth_type"] = hint["auth_type"]
            out["_doc_url"] = hint.get("doc_url", "")
        return out

    def test_connection(self, config: dict) -> TestResult:
        from mcp.manager import add_or_update
        cfg = dict(config)
        cfg["_dry_run"] = True
        result = add_or_update(cfg)
        if result.get("ok"):
            n = int(result.get("tool_count") or 0)
            return TestResult(ok=True, detail=f"Found {n} tools", raw=result, tool_count=n)
        # Auth probe failure: tools were found but calls are rejected — highlight Headers field
        if result.get("auth_probe_failed"):
            return TestResult(
                ok=False,
                detail=result.get("error") or "Auth required",
                raw=result,
                tool_count=int(result.get("tool_count") or 0),
                highlight_field="headers",
            )
        return TestResult(ok=False, detail=result.get("error") or "Connection failed", raw=result)

    def install(self, config: dict) -> InstallResult:
        from mcp.manager import add_or_update
        cfg = dict(config)
        cfg.pop("_dry_run", None)
        result = add_or_update(cfg)
        if result.get("ok"):
            return InstallResult(ok=True, connection_id=result.get("id", ""), name=result.get("name", config.get("name", "")))
        return InstallResult(ok=False, error=result.get("error", "Install failed"))

    def tools_for_chat(self) -> list[str]:
        return [
            "extension_setup__set_field",
            "extension_setup__get_field",
            "extension_setup__fetch_doc",
            "extension_setup__normalize_input",
            "extension_setup__test_connection",
            "extension_setup__start_oauth_flow",
            "extension_setup__highlight_field",
            "extension_setup__show_instruction_panel",
            "extension_setup__mark_done",
        ]
