"""Canonical tool compatibility helpers shared by MCP, routing, and LLM providers.

Raw MCP metadata is deliberately preserved in config.  This module derives the
bounded names and provider-facing schemas used for an individual request.
"""

from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import dataclass
from typing import Iterable

from jsonschema import Draft202012Validator, SchemaError


ALIAS_VERSION = "v2"
GATEWAY_ALIAS_MAX_LENGTH = 64
_VALID_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9_-]")


class ToolCompatibilityError(ValueError):
    """A tool cannot be represented safely for an LLM provider."""


class UnsupportedToolSchema(ToolCompatibilityError):
    """A schema uses dialect semantics we cannot convert without guessing."""


class ToolBudgetExceeded(ToolCompatibilityError):
    """The selected tools exceed the active provider's request limit."""


@dataclass(frozen=True)
class ToolSelection:
    tools: list[dict]
    omitted_names: list[str]
    required_overflow: bool = False


class ToolDefinitionError(RuntimeError):
    """A gateway rejected one tool definition before producing output."""

    def __init__(self, message: str, *, tool_index: int, field: str):
        super().__init__(message)
        self.tool_index = tool_index
        self.field = field


_TOOL_DEFINITION_PATHS = (
    re.compile(r"tools(?:\.|\[)(\d+)(?:\])?\.custom\.(name|input_schema)"),
    re.compile(r"tools(?:\.|\[)(\d+)(?:\])?\.function\.(name|parameters)"),
)


def parse_tool_definition_error(exc: Exception, *, tool_count: int) -> ToolDefinitionError | None:
    """Parse only the gateway's indexed tool-definition validation failures."""
    if isinstance(exc, ToolDefinitionError):
        return exc if 0 <= exc.tool_index < tool_count else None
    status_code = getattr(exc, "status_code", None)
    message = str(exc)
    if status_code not in (400, 422) and not re.search(r"\b(?:400|422)\b", message):
        return None
    match = next((pattern.search(message) for pattern in _TOOL_DEFINITION_PATHS if pattern.search(message)), None)
    if not match:
        return None
    index = int(match.group(1))
    if index < 0 or index >= tool_count:
        return None
    field = "input_schema" if match.group(2) == "parameters" else match.group(2)
    return ToolDefinitionError(message, tool_index=index, field=field)


@dataclass(frozen=True)
class ToolFailure:
    category: str
    code: str
    retryable: bool
    terminal: bool
    user_message: str


def gateway_tool_alias(
    connection_id: str,
    raw_tool_name: str,
    *,
    existing_names: Iterable[str] = (),
    max_length: int = GATEWAY_ALIAS_MAX_LENGTH,
) -> str:
    """Return a stable, legal LLM-facing alias without changing MCP identity."""
    if not isinstance(raw_tool_name, str):
        raise ToolCompatibilityError("MCP tool name must be a string")
    raw_name = raw_tool_name.strip()
    if not raw_name:
        raise ToolCompatibilityError("MCP tool name is empty")
    if max_length < 16:
        raise ToolCompatibilityError("tool-name limit is too small for safe aliases")

    original = f"{connection_id}__{raw_name}"
    occupied = set(existing_names)
    digest = hashlib.sha256(
        f"{ALIAS_VERSION}\0{connection_id}\0{raw_name}".encode("utf-8")
    ).hexdigest()[:10]
    # Keep a legal raw tool name after the conventional ``__`` separator so
    # existing capability discovery (browser MCP, suffix lookups) continues to
    # work. Put the digest in the connection portion where it disambiguates
    # sanitized IDs without changing the server tool-name suffix.
    if _VALID_TOOL_NAME.fullmatch(raw_name) and len(raw_name) + len(digest) + 3 < max_length:
        conn_stem = _UNSAFE_NAME_CHARS.sub("_", str(connection_id)).strip("_") or "mcp"
        suffix = f"_{digest}__{raw_name}"
        alias = f"{conn_stem[: max_length - len(suffix)]}{suffix}"
    else:
        stem = _UNSAFE_NAME_CHARS.sub("_", original).strip("_") or "tool"
        suffix = f"__{digest}"
        alias = f"{stem[: max_length - len(suffix)]}{suffix}"
    if alias in occupied:
        raise ToolCompatibilityError(
            f"gateway alias collision for MCP tool {raw_name!r}"
        )
    return alias


_SCHEMA_MAP_KEYS = {
    "properties",
    "patternProperties",
    "definitions",
    "$defs",
    "dependentSchemas",
}
_SCHEMA_SINGLE_KEYS = {
    "additionalProperties",
    "unevaluatedProperties",
    "unevaluatedItems",
    "propertyNames",
    "contains",
    "not",
    "if",
    "then",
    "else",
    "contentSchema",
}
_SCHEMA_LIST_KEYS = {"allOf", "anyOf", "oneOf", "prefixItems"}
_KNOWN_DIALECTS = (
    "draft-04",
    "draft-06",
    "draft-07",
    "2019-09",
    "2020-12",
)


def _dialect_from_uri(value: object) -> str | None:
    if not isinstance(value, str):
        raise UnsupportedToolSchema("$schema must be a string")
    lowered = value.lower()
    dialect = next((item for item in _KNOWN_DIALECTS if item in lowered), None)
    if dialect is None:
        raise UnsupportedToolSchema(f"unsupported JSON Schema dialect: {value}")
    return dialect


def _check_dialect_sensitive_keywords(node: dict, dialect: str | None) -> None:
    if isinstance(node.get("items"), list):
        raise UnsupportedToolSchema("tuple-form items requires a dialect-aware conversion")
    if isinstance(node.get("exclusiveMinimum"), bool) or isinstance(node.get("exclusiveMaximum"), bool):
        raise UnsupportedToolSchema("boolean exclusive bounds require a dialect-aware conversion")
    if "dependencies" in node:
        raise UnsupportedToolSchema("dependencies requires a dialect-aware conversion")
    if "additionalItems" in node:
        raise UnsupportedToolSchema("additionalItems requires a dialect-aware conversion")
    if dialect in {"draft-04", "draft-06", "draft-07"} and "id" in node:
        raise UnsupportedToolSchema("legacy id scopes cannot be converted safely")
    if dialect in {"draft-04", "draft-06", "draft-07"} and "$ref" in node:
        annotation_keys = {
            "$schema", "$ref", "$comment", "title", "description", "default",
            "examples", "readOnly", "writeOnly", "deprecated",
        }
        if any(key not in annotation_keys for key in node):
            raise UnsupportedToolSchema(
                "legacy $ref siblings cannot be converted without changing semantics"
            )


def _project_schema_node(node: object, inherited_dialect: str | None = None) -> object:
    if isinstance(node, bool):
        return node
    if not isinstance(node, dict):
        raise UnsupportedToolSchema("schema nodes must be objects or booleans")

    dialect = inherited_dialect
    if "$schema" in node:
        dialect = _dialect_from_uri(node["$schema"])
    _check_dialect_sensitive_keywords(node, dialect)

    out: dict = {}
    for key, value in node.items():
        if key == "$schema":
            continue
        target_key = "$defs" if key == "definitions" else key
        if target_key in out:
            raise UnsupportedToolSchema(f"conflicting schema keyword {target_key}")
        if key == "$ref" and isinstance(value, str):
            # Only rewrite pointers into this schema document. An external
            # resource owns its own dialect and definitions vocabulary.
            out[key] = (
                "#/$defs/" + value[len("#/definitions/"):]
                if value.startswith("#/definitions/")
                else value
            )
        elif key in _SCHEMA_MAP_KEYS and isinstance(value, dict):
            out[target_key] = {
                child_name: _project_schema_node(child, dialect)
                for child_name, child in value.items()
            }
        elif key == "items" and isinstance(value, (dict, bool)):
            out[key] = _project_schema_node(value, dialect)
        elif key in _SCHEMA_SINGLE_KEYS and isinstance(value, (dict, bool)):
            out[key] = _project_schema_node(value, dialect)
        elif key in _SCHEMA_LIST_KEYS and isinstance(value, list):
            out[key] = [_project_schema_node(child, dialect) for child in value]
        else:
            out[key] = copy.deepcopy(value)
    return out


def project_json_schema(schema: dict) -> dict:
    """Project a supported MCP input schema to the gateway's 2020-12 shape.

    Unsupported dialect-sensitive constructs are rejected instead of guessed.
    The source object is never mutated.
    """
    if not isinstance(schema, dict):
        raise UnsupportedToolSchema("input schema must be an object")
    projected = _project_schema_node(schema)
    if not isinstance(projected, dict):  # defensive; root MCP schemas are objects
        raise UnsupportedToolSchema("input schema must be an object")
    schema_type = projected.get("type")
    if schema_type not in (None, "object"):
        raise UnsupportedToolSchema("MCP input schema root must describe an object")
    try:
        Draft202012Validator.check_schema(projected)
    except SchemaError as exc:
        raise UnsupportedToolSchema("input schema is not valid Draft 2020-12 JSON Schema") from exc
    return projected


def _projected_tool_name(tool: dict) -> str:
    if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
        return str(tool["function"].get("name", ""))
    return str(tool.get("name", ""))


def prepare_tool_definitions(provider, model: str, tools: list[dict]) -> list[dict]:
    """Validate the request budget and project canonical tools for a provider."""
    max_tools = int(getattr(provider, "max_tools", 128))
    max_name_length = int(getattr(provider, "max_tool_name_length", 128))
    if len(tools) > max_tools:
        raise ToolBudgetExceeded(
            f"Selected {len(tools)} tools but {model or 'the active model'} limit is {max_tools}. "
            "Narrow the active skills or connection before retrying."
        )

    projected = [provider.normalize_tool_schema(tool) for tool in tools]
    for item in projected:
        name = _projected_tool_name(item)
        if not name or len(name) > max_name_length or not _VALID_TOOL_NAME.fullmatch(name):
            raise ToolCompatibilityError(
                f"Tool name {name!r} is not valid for {model or 'the active model'}"
            )
    return projected


def select_tools_with_budget(
    tools: list[dict],
    *,
    max_tools: int,
    required_names: set[str],
    priority_groups: list[set[str]],
) -> ToolSelection:
    """Keep required tools first and omit lower-priority groups deterministically.

    An explicit/always-on set that cannot fit is left intact so the caller can
    surface a clear configuration error rather than silently dropping a tool
    the user selected.
    """
    ordered_names = [str(tool.get("name", "")) for tool in tools]
    required = [tool for tool in tools if tool.get("name") in required_names]
    if len(required) > max_tools:
        return ToolSelection(list(tools), [], required_overflow=True)

    selected = list(required)
    selected_names = {tool.get("name") for tool in selected}
    omitted: list[str] = []
    considered_names = set(selected_names)
    for group in priority_groups + [set(ordered_names)]:
        for tool in tools:
            name = tool.get("name")
            if name not in group or name in considered_names:
                continue
            considered_names.add(name)
            if len(selected) < max_tools:
                selected.append(tool)
                selected_names.add(name)
            else:
                omitted.append(str(name))
    return ToolSelection(selected, omitted)


_AUTH_CODES = {"not_authed", "invalid_auth", "token_revoked", "token_expired", "invalid_token"}
_PERMISSION_CODES = {"team_access_not_granted", "account_inactive"}
_TRANSIENT_CODES = {"rate_limited", "ratelimited", "timeout", "temporarily_unavailable"}


def _extract_error_code(result: dict) -> str:
    for value in (result.get("code"), result.get("error"), result.get("result")):
        if not isinstance(value, str):
            continue
        stripped = value.strip()
        if stripped in _AUTH_CODES | _PERMISSION_CODES | _TRANSIENT_CODES:
            return stripped
        try:
            parsed = __import__("json").loads(stripped)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            nested = parsed.get("error") or parsed.get("code")
            if isinstance(nested, str):
                return nested
        lowered = stripped.lower()
        for code in _AUTH_CODES | _PERMISSION_CODES | _TRANSIENT_CODES:
            if code in lowered:
                return code
        if "google authentication required" in lowered:
            return "google_authentication_required"
    if result.get("_mcp_auth_error"):
        return "mcp_authentication_required"
    return ""


def classify_tool_failure(result: object, *, tool_name: str = "") -> ToolFailure | None:
    """Translate integration-specific failures into safe execution policy."""
    if not isinstance(result, dict):
        return None
    code = _extract_error_code(result)
    if not code:
        return None
    if code == "google_authentication_required":
        auth_url = result.get("_auth_url") if result.get("_workspace_mcp_auth") else None
        suffix = (
            f" Open this authorization link, then retry: {auth_url}"
            if isinstance(auth_url, str) and auth_url.startswith("https://accounts.google.com/o/oauth2/auth?")
            else " Reconnect Google Workspace, then retry."
        )
        return ToolFailure(
            "authentication", code, False, True,
            f"Google authentication is required.{suffix}",
        )
    if code in _AUTH_CODES or code == "mcp_authentication_required":
        service = "Slack" if tool_name.startswith("slack_") else "This connection"
        return ToolFailure(
            "authentication", code, False, True,
            f"{service} authentication is missing or expired. Reconnect it in Settings, then retry.",
        )
    if code in _PERMISSION_CODES:
        service = "Slack workspace" if code == "team_access_not_granted" or tool_name.startswith("slack_") else "This connection"
        return ToolFailure(
            "permission", code, False, True,
            f"{service} access was not granted. Reconnect it or ask an administrator to grant access.",
        )
    if code in _TRANSIENT_CODES:
        return ToolFailure(
            "transient", code, True, False,
            f"The tool reported {code}; retry after a short delay.",
        )
    return None


def sanitize_tool_failure(result: object, *, tool_name: str = "") -> dict | None:
    """Return a model/telemetry-safe result for a recognized tool failure."""
    failure = classify_tool_failure(result, tool_name=tool_name)
    if failure is None:
        return None
    return {
        "error": failure.code,
        "_tool_outcome": {
            "category": failure.category,
            "code": failure.code,
            "retryable": failure.retryable,
            "terminal": failure.terminal,
            "user_message": failure.user_message,
        },
    }


_GOOGLE_SERVICE_TOOLS = {
    "g-gmail": frozenset({
        "search_gmail_messages", "get_gmail_message_content", "get_gmail_messages_content_batch",
        "send_gmail_message", "get_gmail_attachment_content", "get_gmail_thread_content",
        "modify_gmail_message_labels", "list_gmail_labels", "manage_gmail_label",
        "draft_gmail_message", "list_gmail_filters", "manage_gmail_filter",
        "get_gmail_threads_content_batch", "batch_modify_gmail_message_labels",
    }),
    "g-drive": frozenset({
        "search_drive_files", "get_drive_file_content", "get_drive_file_download_url",
        "create_drive_file", "create_drive_folder", "import_to_google_doc",
        "import_to_google_slides", "import_to_google_sheets", "get_drive_shareable_link",
        "list_drive_items", "copy_drive_file", "update_drive_file", "manage_drive_access",
        "set_drive_file_permissions", "get_drive_file_permissions", "check_drive_file_public_access",
    }),
    "g-calendar": frozenset({
        "list_calendars", "get_events", "manage_event", "create_calendar", "query_freebusy",
        "manage_out_of_office", "manage_focus_time",
    }),
    "g-docs": frozenset({
        "get_doc_content", "create_doc", "modify_doc_text", "export_doc_to_pdf", "search_docs",
        "find_and_replace_doc", "list_docs_in_folder", "insert_doc_elements", "update_paragraph_style",
        "get_doc_as_markdown", "list_document_comments", "manage_document_comment", "insert_doc_image",
        "update_doc_headers_footers", "batch_update_doc", "inspect_doc_structure", "create_table_with_data",
        "debug_table_structure", "manage_doc_tab",
    }),
    "g-sheets": frozenset({
        "create_spreadsheet", "read_sheet_values", "modify_sheet_values", "list_spreadsheets",
        "get_spreadsheet_info", "format_sheet_range", "list_sheet_tables", "create_sheet",
        "append_table_rows", "resize_sheet_dimensions", "move_sheet_rows", "list_spreadsheet_comments",
        "manage_spreadsheet_comment", "manage_conditional_formatting",
    }),
    "g-slides": frozenset({
        "create_presentation", "get_presentation", "batch_update_presentation", "get_page",
        "get_page_thumbnail", "list_presentation_comments", "manage_presentation_comment",
    }),
    "g-forms": frozenset({
        "create_form", "get_form", "list_form_responses", "set_publish_settings", "get_form_response",
        "batch_update_form",
    }),
    "g-tasks": frozenset({
        "get_task", "list_tasks", "manage_task", "list_task_lists", "get_task_list", "manage_task_list",
    }),
    "g-contacts": frozenset({
        "search_contacts", "get_contact", "list_contacts", "manage_contact", "list_contact_groups",
        "get_contact_group", "manage_contacts_batch", "manage_contact_group",
    }),
    "g-chat": frozenset({
        "send_message", "get_messages", "search_messages", "create_reaction", "list_spaces",
        "download_chat_attachment",
    }),
    "g-search": frozenset({"search_custom", "get_search_engine_info"}),
    "g-script": frozenset({
        "list_script_projects", "get_script_project", "get_script_content", "create_script_project",
        "update_script_content", "run_script_function", "generate_trigger_code", "manage_deployment",
        "list_deployments", "delete_script_project", "list_versions", "create_version", "get_version",
        "list_script_processes", "get_script_metrics",
    }),
}
_GOOGLE_SHARED_TOOLS = frozenset({"start_google_auth"})
GOOGLE_WORKSPACE_SERVICE_IDS = frozenset(_GOOGLE_SERVICE_TOOLS)


def is_google_workspace_service(skill_id: str) -> bool:
    """True only for backend-defined Google Workspace synthetic service IDs."""
    return skill_id in GOOGLE_WORKSPACE_SERVICE_IDS


def google_workspace_tool_groups(raw_to_alias: dict[str, str]) -> dict[str, set[str]]:
    """Build explicit backend tool groups for the Google service tiles."""
    return {
        skill_id: {
            raw_to_alias[name]
            for name in names | _GOOGLE_SHARED_TOOLS
            if name in raw_to_alias
        }
        for skill_id, names in _GOOGLE_SERVICE_TOOLS.items()
        if any(name in raw_to_alias for name in names)
    }
