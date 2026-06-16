"""Extension adapter protocol — common shape for MCP / plugin / skill setup.

⚠️  POST-MVP — DO NOT MODIFY FOR MVP WORK ⚠️

This adapter framework backs the deferred agentic setup wizard
(web/routes/extension_setup.py, web/static/extension_setup_modal.js).
The supported MVP "Add MCP" path is the legacy modal at
web/static/mcp_add_modal.js → web/routes/mcp_routes.py → web/mcp/manager.py.
Bug fixes for MCP add/edit/test belong in those files — NOT here.
Only modify anything under web/extensions/ if the user has explicitly
asked for post-MVP wizard work.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

ExtensionType = Literal["mcp", "plugin", "skill"]


@dataclass
class TestResult:
    ok: bool
    detail: str = ""
    raw: dict = field(default_factory=dict)
    tool_count: int = 0
    highlight_field: str | None = None  # field path to pulse on auth failure


@dataclass
class InstallResult:
    ok: bool
    connection_id: str = ""
    name: str = ""
    error: str = ""


@dataclass
class FieldUpdate:
    field_path: str
    value: object


@runtime_checkable
class ExtensionAdapter(Protocol):
    extension_type: ExtensionType
    config_schema: dict

    def normalize(self, raw: str) -> dict: ...
    def prefill_from_url(self, url: str) -> dict: ...
    def test_connection(self, config: dict) -> TestResult: ...
    def install(self, config: dict) -> InstallResult: ...
    def tools_for_chat(self) -> list[str]: ...
