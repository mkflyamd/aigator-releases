"""Fail-closed target resolution and verification for Jira mutations.

The built-in Jira client historically reads one process-global configuration.
That is safe only when exactly one Jira site is connected.  This module is the
boundary for any new state-changing Jira operation: a mutation must carry the
resolved target that was used while drafting it, and success is reported only
after a read from that same target confirms the requested state.

MCP-backed Jira sites are deliberately not silently mapped to the built-in
credentials.  An MCP resource needs an explicit adapter before it is allowed
to mutate anything; this prevents a request for amd.atlassian.net from being
sent to a configured amd-hub.atlassian.net account.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import RLock
from urllib.parse import urlparse
import secrets
import hashlib
from pathlib import Path
import tempfile
import json
import time

from config import load_config
from . import api


class JiraTargetResolutionError(ValueError):
    """Raised when a Jira target is ambiguous, unconfigured, or unsafe."""


_target_selection_lock = RLock()
_target_selection_by_context: dict[str, str] = {}
_target_selection_handles: dict[str, tuple[str, str, float]] = {}
_TARGET_SELECTION_TTL_SECONDS = 5 * 60
_staged_attachments: dict[str, dict] = {}
_attachment_lock = RLock()
_probe_cache: dict[tuple, tuple[bool, float]] = {}
_probe_cache_lock = RLock()
_PROBE_CACHE_TTL = 60.0


def _canonical_base_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise JiraTargetResolutionError("Jira target must be an https URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise JiraTargetResolutionError("Jira target URL must not include credentials, a query, or a fragment.")
    path = parsed.path.rstrip("/")
    # A target is a site root (optionally a Server/DC context path), never a
    # Jira view URL. Accepting /browse would later generate /browse/browse/KEY
    # and, worse, makes URL matching ambiguous.
    if path.lower().endswith(("/browse", "/secure", "/projects")):
        raise JiraTargetResolutionError("Jira target URL must be a site base URL, not a Jira page URL.")
    return f"https://{parsed.netloc.lower()}{path}"


@dataclass(frozen=True)
class JiraTarget:
    """Immutable Jira site identity captured at draft time.

    ``adapter`` is intentionally explicit.  No code may substitute the
    process-global Jira credentials for an MCP target just because both are
    Atlassian Cloud sites.
    """

    id: str
    base_url: str
    adapter: str
    is_cloud: bool
    connection_id: str = ""
    resource_id: str = ""
    display_name: str = ""
    capabilities: tuple[str, ...] = ()

    def issue_url(self, issue_key: str) -> str:
        return f"{self.base_url}/browse/{issue_key}"

    def to_dict(self) -> dict:
        return asdict(self)

    def public_dict(self) -> dict:
        """The site identity safe to send to a renderer or model.

        Target, connection, and resource IDs are routing implementation
        details.  In particular, they must never become model-controlled tool
        arguments just because a tool result was echoed into the conversation.
        """
        return {
            "display_name": self.display_name or self.base_url,
            "base_url": self.base_url,
            "adapter": self.adapter,
            "is_cloud": self.is_cloud,
            "capabilities": list(self.capabilities),
        }


def configured_builtin_target() -> JiraTarget:
    """Return the sole built-in target, normalized from trusted config.

    This is not a fallback resolver.  It only represents the legacy direct
    Jira configuration and must exactly match a supplied Jira URL.
    """

    base_url = _canonical_base_url(api.jira_browse_url())
    return JiraTarget(
        id=f"builtin:{base_url}",
        base_url=base_url,
        adapter="builtin-rest",
        is_cloud=api.jira_is_cloud(),
        display_name="Jira",
        # Advertise only operations that currently have a target-bound,
        # HITL-gated, read-back-verified direct REST implementation.
        capabilities=("read", "create", "update", "watcher", "attachment"),
    )


def _registered_targets() -> list[JiraTarget]:
    """Load validated non-legacy Jira targets registered by a connector.

    A registry entry is data discovered from a trusted connector, never an LLM
    tool argument. This module intentionally does not obtain credentials from
    it; credentials remain owned by the selected connector.
    """

    try:
        from mcp.manager import _load_connections
        connection_ids = {str(c.get("id", "")) for c in _load_connections()}
    except Exception:
        connection_ids = set()
    targets: list[JiraTarget] = []
    seen_ids: set[str] = set()
    for raw in load_config().get("jira_targets", []):
        if not isinstance(raw, dict):
            continue
        try:
            target = JiraTarget(**raw)
            if (target.adapter != "rovo-mcp" or not target.connection_id
                    or not target.resource_id or target.connection_id not in connection_ids
                    or target.id in seen_ids):
                continue
            if _canonical_base_url(target.base_url) != target.base_url:
                continue
            if not target.display_name:
                target = JiraTarget(**{**target.to_dict(), "display_name": target.base_url})
            targets.append(target)
            seen_ids.add(target.id)
        except (TypeError, JiraTargetResolutionError):
            continue
    return targets


def available_targets() -> list[JiraTarget]:
    """Return all configured targets without treating any one as a fallback.

    When builtin-rest and a rovo-mcp target share the same base_url, the
    builtin-rest target takes precedence and the Rovo duplicate is suppressed.
    This prevents bare-key resolution from becoming ambiguous when the user
    configures direct credentials for a site that Rovo also exposes.
    """

    targets = _registered_targets()
    try:
        builtin = configured_builtin_target()
    except Exception:
        builtin = None
    if builtin:
        targets = [t for t in targets if t.base_url != builtin.base_url]
        targets.insert(0, builtin)
    return targets


def target_selection_event(context_id: str, detail: str = "") -> dict:
    """UI-only site-picker payload; IDs are never writable tool parameters."""
    context = (context_id or "").strip()
    choices = []
    with _target_selection_lock:
        now = time.monotonic()
        for handle, stored in list(_target_selection_handles.items()):
            if stored[2] <= now:
                del _target_selection_handles[handle]
        for target in available_targets():
            handle = secrets.token_urlsafe(24)
            _target_selection_handles[handle] = (
                context, target.id, now + _TARGET_SELECTION_TTL_SECONDS,
            )
            choices.append({"handle": handle, **target.public_dict()})
    return {
        "context_id": context_id,
        "detail": detail,
        "targets": choices,
    }


def _url_matches_target(url: str, target: JiraTarget) -> bool:
    parsed = urlparse(url)
    configured = urlparse(target.base_url)
    same_origin = (
        parsed.scheme.lower() == configured.scheme.lower()
        and parsed.netloc.lower() == configured.netloc.lower()
    )
    configured_path = configured.path.rstrip("/")
    path_matches = not configured_path or (
        parsed.path == configured_path
        or parsed.path.startswith(f"{configured_path}/")
    )
    return same_origin and path_matches


def resolve_jira_target(issue_or_url: str = "", target_id: str = "", for_write: bool = False, _context_id: str = "") -> JiraTarget:
    """Resolve a Jira target or fail closed when an issue key is ambiguous.

    for_write=True tightens resolution for mutations: when the waterfall finds
    the issue on more than one site the call is refused rather than silently
    picking the first hit, preventing writes to the wrong site.
    """

    targets = available_targets()
    if not targets:
        raise JiraTargetResolutionError("No Jira site is connected. Connect Jira in Apps first.")
    if target_id:
        target = next((item for item in targets if item.id == target_id), None)
        if target is None:
            raise JiraTargetResolutionError(
                "The selected Jira site is no longer connected. Reconnect it and re-draft the action."
            )
        if issue_or_url.startswith(("http://", "https://")) and not _url_matches_target(issue_or_url, target):
            raise JiraTargetResolutionError(
                "The provided Jira URL does not belong to the selected Jira site. "
                "AI Gator will not redirect the mutation."
            )
        return target
    if issue_or_url.startswith(("http://", "https://")):
        matches = [target for target in targets if _url_matches_target(issue_or_url, target)]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise JiraTargetResolutionError(
                "The Jira URL does not belong to a connected Jira site. Connect that site before drafting a mutation."
            )
        raise JiraTargetResolutionError("More than one connected Jira site matches this URL. Select a Jira site explicitly.")
    if len(targets) == 1:
        return targets[0]

    # Multiple targets, bare key — waterfall probes each site.
    # For reads: return the first site that has the issue (silent, best-effort).
    # For writes: if more than one site has the issue, refuse and ask the user
    #             to supply the full URL so the target is unambiguous.
    return _waterfall_resolve(issue_or_url, targets, for_write=for_write, context_id=_context_id)


def _probe_target(issue_key: str, target: "JiraTarget", context_id: str = "") -> bool:
    """Return True if issue_key exists on target. Never raises.

    Results are cached for 60 s per (context_id, key, target.id) to avoid
    repeated network round-trips within a single conversation turn.
    context_id is included so one user's probe result never leaks to another.
    """
    cache_key = (context_id or "", issue_key, target.id)
    with _probe_cache_lock:
        cached = _probe_cache.get(cache_key)
        if cached is not None:
            found, ts = cached
            if time.monotonic() - ts < _PROBE_CACHE_TTL:
                return found
    try:
        if target.adapter == "rovo-mcp":
            raw = rovo_jira_call(target, "get_issue", {"issueIdOrKey": issue_key})
            data = raw.get("data", raw) if isinstance(raw, dict) else {}
            found = bool(data.get("key") or data.get("id"))
        else:
            result_data = api.jira_api_for_target(target, "GET", f"issue/{issue_key}?fields=summary")
            found = bool(result_data.get("key") or result_data.get("id"))
    except Exception:
        found = False
    with _probe_cache_lock:
        _probe_cache[cache_key] = (found, time.monotonic())
    return found


def flush_probe_cache_for_target(target_id: str) -> None:
    """Remove all cached probe results for a target — call when a site is disconnected."""
    with _probe_cache_lock:
        stale = [k for k in _probe_cache if k[2] == target_id]
        for k in stale:
            del _probe_cache[k]


def _waterfall_resolve(issue_key: str, targets: "list[JiraTarget]", for_write: bool = False, context_id: str = "") -> "JiraTarget":
    """Try each target in order and return the first one that has the issue.

    builtin-rest targets are tried before rovo-mcp so direct credentials
    (which support full write capabilities) are preferred when available.

    for_write=True: if the issue is found on more than one site, refuse with
    an error asking the user to supply the full URL — silently picking a site
    for a mutation risks writing to the wrong project.
    """
    ordered = sorted(targets, key=lambda t: 0 if t.adapter == "builtin-rest" else 1)
    hits = [target for target in ordered if _probe_target(issue_key, target, context_id)]
    if not hits:
        raise JiraTargetResolutionError(
            f"Issue {issue_key!r} was not found on any of the {len(ordered)} connected Jira site(s). "
            "Check the issue key or connect the site that hosts it in Apps → Settings."
        )
    if for_write and len(hits) > 1:
        raise JiraTargetResolutionError(
            f"Issue {issue_key!r} exists on {len(hits)} connected Jira sites. "
            "Provide the full issue URL so AI Gator knows which site to write to."
        )
    return hits[0]


def select_target_for_context(context_id: str, target_id: str) -> JiraTarget:
    """Persist a user-selected target for one chat tab.

    This function is called only by the CSRF-protected UI endpoint. Tool calls
    receive the context ID server-side; they never receive a model-controlled
    target identifier.
    """
    context = (context_id or "").strip()
    if not context:
        raise JiraTargetResolutionError("A tab context is required to select a Jira site.")
    target = resolve_jira_target(target_id=target_id)
    with _target_selection_lock:
        _target_selection_by_context[context] = target.id
    return target


def select_target_handle(context_id: str, handle: str) -> JiraTarget:
    """Consume a UI-only, tab-bound target selection handle."""
    context = (context_id or "").strip()
    with _target_selection_lock:
        stored = _target_selection_handles.pop((handle or "").strip(), None)
    if not stored or stored[0] != context or stored[2] <= time.monotonic():
        raise JiraTargetResolutionError("That Jira site choice expired or belongs to another tab. Choose a site again.")
    return select_target_for_context(context, stored[1])


def stage_attachment(filename: str, content: bytes, content_type: str = "") -> dict:
    """Create an immutable, private attachment snapshot and return its opaque ID."""
    safe_name = Path(filename or "attachment").name
    if not safe_name or safe_name in {".", ".."}:
        raise JiraTargetResolutionError("Attachment filename is invalid.")
    upload_id = secrets.token_urlsafe(24)
    root = Path(tempfile.gettempdir()) / "aigator-jira-uploads"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = root / upload_id
    # The service writes this new file itself; later checks reject any swapped
    # symlink or changed snapshot before an approval can upload it.
    with open(path, "xb") as handle:
        handle.write(content)
    snapshot = {
        "upload_id": upload_id, "path": path, "filename": safe_name,
        "content_type": content_type or "application/octet-stream",
        "size": len(content), "sha256": hashlib.sha256(content).hexdigest(),
    }
    with _attachment_lock:
        _staged_attachments[upload_id] = snapshot
    return {key: snapshot[key] for key in ("upload_id", "filename", "content_type", "size", "sha256")}


def staged_attachment(upload_id: str) -> dict:
    """Return a verified staged snapshot or reject path swaps and symlinks."""
    with _attachment_lock:
        snapshot = _staged_attachments.get((upload_id or "").strip())
    if not snapshot:
        raise JiraTargetResolutionError("Attachment upload ID is unknown or expired. Upload it again.")
    path = Path(snapshot["path"])
    if path.is_symlink() or not path.is_file():
        raise JiraTargetResolutionError("Attachment snapshot is no longer a regular file. Upload it again.")
    content = path.read_bytes()
    if len(content) != snapshot["size"] or hashlib.sha256(content).hexdigest() != snapshot["sha256"]:
        raise JiraTargetResolutionError("Attachment changed after staging. Upload it again before approval.")
    verified = dict(snapshot)
    # Keep the bytes in memory only for the immediate approval call. Uploading
    # these bytes (rather than reopening ``path``) closes the check/use window.
    verified["_content"] = content
    return verified


def discover_rovo_targets() -> list[JiraTarget]:
    """Discover Jira resources from authenticated Rovo MCP connections.

    Per-connection semantics:
    - A connection that responds successfully: its targets fully replace any
      previously stored targets for that connection_id.
    - A connection that fails (expired OAuth, timeout, network error): its
      existing stored targets are left untouched. The failure is not treated
      as proof the resources are gone.
    - A connection that has been removed from mcp_connections entirely: its
      stored targets ARE removed, since the owning connection no longer exists.

    This means a temporary OAuth expiry never silently erases Rovo targets.
    Only a successful re-discovery of that connection (returning a different
    resource set) or an explicit connection removal can change its targets.
    """
    from config import update_config
    from mcp.manager import _client_for, _load_connections

    all_connections = _load_connections()
    enabled_connection_ids = {str(c.get("id", "")) for c in all_connections}

    # Track which connection_ids were successfully contacted this run.
    contacted: set[str] = set()
    discovered: list[JiraTarget] = []

    for connection in all_connections:
        conn_id = str(connection.get("id", ""))
        cached = connection.get("cached_tools", []) or []
        resource_tool = next(
            (tool.get("name", "") for tool in cached if isinstance(tool, dict)
             and tool.get("name", "").lower() == "getaccessibleatlassianresources"),
            "",
        )
        if not resource_tool:
            continue
        client = None
        try:
            client = _client_for(connection, pooled=False)
            raw = client.call(resource_tool, {})
            payload = json.loads(raw) if isinstance(raw, str) else raw
            resources = payload.get("resources", payload) if isinstance(payload, dict) else payload
            if not isinstance(resources, list):
                continue
            # Mark this connection as successfully contacted. Its stored targets
            # will be replaced with what discovery returned (even if empty —
            # that means the user has genuinely lost access to all resources).
            contacted.add(conn_id)
            tool_names = {str(tool.get("name", "")).lower() for tool in cached if isinstance(tool, dict)}
            capabilities = ["read"]
            for capability, marker in (("create", "createjiraissue"), ("update", "updatejiraissue"), ("watcher", "watch")):
                if any(marker in name for name in tool_names):
                    capabilities.append(capability)
            for resource in resources:
                if not isinstance(resource, dict):
                    continue
                resource_id, url = str(resource.get("id", "")), str(resource.get("url", ""))
                if not resource_id:
                    continue
                try:
                    base_url = _canonical_base_url(url)
                except JiraTargetResolutionError:
                    continue
                discovered.append(JiraTarget(
                    id=f"rovo:{conn_id}:{resource_id}",
                    base_url=base_url, adapter="rovo-mcp", is_cloud=True,
                    connection_id=conn_id, resource_id=resource_id,
                    display_name=str(resource.get("name") or resource.get("title") or base_url),
                    capabilities=tuple(capabilities),
                ))
        except Exception:
            # Connection failed (expired OAuth, timeout, etc.).
            # Do NOT mark as contacted — existing stored targets survive.
            continue
        finally:
            if client is not None and hasattr(client, "close"):
                try:
                    client.close()
                except Exception:
                    pass

    def _commit_targets(cfg: dict):
        existing = cfg.get("jira_targets", [])
        seen_ids: set[str] = set()
        kept: list[dict] = []
        for entry in existing:
            if not isinstance(entry, dict) or entry.get("adapter") != "rovo-mcp":
                # Non-Rovo entries (builtin-rest, etc.) are never touched here.
                entry_id = entry.get("id", "") if isinstance(entry, dict) else ""
                if entry_id not in seen_ids:
                    seen_ids.add(entry_id)
                    kept.append(entry)
                continue
            entry_id = entry.get("id", "")
            entry_conn = entry.get("connection_id", "")
            if entry_conn not in enabled_connection_ids:
                # Connection was removed from mcp_connections entirely — drop target
                # and flush any cached probe results for it.
                if entry_id:
                    flush_probe_cache_for_target(entry_id)
                continue
            if entry_conn in contacted:
                # Successfully re-discovered this connection; its fresh targets
                # will be added below. Skip the stale record.
                continue
            # Connection exists but failed this run — preserve existing target,
            # but deduplicate by stable ID so repeated failures cannot stack records.
            if entry_id not in seen_ids:
                seen_ids.add(entry_id)
                kept.append(entry)

        # Deduplicate newly discovered targets by stable ID before appending.
        unique_discovered: list[JiraTarget] = []
        for target in discovered:
            if target.id not in seen_ids:
                seen_ids.add(target.id)
                unique_discovered.append(target)

        cfg["jira_targets"] = kept + [target.to_dict() for target in unique_discovered]
        return cfg

    # Build unique_discovered outside _commit_targets so we can return it.
    # This mirrors the dedup logic inside _commit_targets but without the
    # seen_ids context from retained entries — we want the caller to receive
    # the same deduplicated list that was actually persisted.
    unique_discovered: list[JiraTarget] = []
    _seen: set[str] = set()
    for target in discovered:
        if target.id not in _seen:
            _seen.add(target.id)
            unique_discovered.append(target)

    update_config(_commit_targets)
    return unique_discovered


def selected_target_for_context(context_id: str) -> JiraTarget | None:
    with _target_selection_lock:
        target_id = _target_selection_by_context.get((context_id or "").strip())
    if not target_id:
        return None
    try:
        return resolve_jira_target(target_id=target_id)
    except JiraTargetResolutionError:
        return None


def resolve_target_for_context(issue_or_url: str = "", context_id: str = "", for_write: bool = False) -> JiraTarget:
    """Resolve a target using a UI-owned tab selection when one exists."""
    selected = selected_target_for_context(context_id)
    if selected is not None:
        return resolve_jira_target(issue_or_url, target_id=selected.id, for_write=for_write)
    return resolve_jira_target(issue_or_url, for_write=for_write, _context_id=context_id)


def resolve_builtin_target(issue_or_url: str = "", context_id: str = "") -> JiraTarget:
    """Resolve an issue reference against the configured direct Jira site.

    A full URL is accepted only if it names the configured site.  A key alone
    is inherently site-ambiguous once multiple sites are connected, so callers
    must pass an already-selected target for key-only operations in that case.
    Current direct tools have one selected built-in target, so the key remains
    compatible while URL mismatches fail closed.
    """

    target = resolve_target_for_context(issue_or_url, context_id)
    if target.adapter != "builtin-rest":
        raise JiraTargetResolutionError(
            f"{target.base_url} is connected through Rovo. This direct Jira action cannot use it yet; "
            "use the Rovo-backed action after selecting that Jira site."
        )
    return target


def target_from_draft(raw: dict, context_id: str = "") -> JiraTarget:
    """Rehydrate and validate the target captured in a pending HITL draft."""

    if not isinstance(raw, dict):
        raise JiraTargetResolutionError("Jira draft has no resolved target. Re-draft the action.")
    try:
        target = JiraTarget(**raw)
    except TypeError as exc:
        raise JiraTargetResolutionError("Jira draft target is malformed. Re-draft the action.") from exc
    canonical = _canonical_base_url(target.base_url)
    if canonical != target.base_url or target.adapter not in {"builtin-rest", "rovo-mcp"}:
        raise JiraTargetResolutionError(
            "Jira draft target is not a supported verified-mutation adapter. Re-draft after selecting a connected Jira site."
        )
    current = next((item for item in available_targets() if item.id == target.id), None)
    # Presentation/capability metadata may evolve independently of a draft.
    # The approval fingerprint is the routing identity and adapter binding.
    current_identity = (
        current.id, current.base_url, current.adapter, current.is_cloud,
        current.connection_id, current.resource_id,
    ) if current else None
    draft_identity = (
        target.id, target.base_url, target.adapter, target.is_cloud,
        target.connection_id, target.resource_id,
    )
    if current_identity != draft_identity:
        raise JiraTargetResolutionError(
            "The Jira connection changed after this draft was prepared. Re-draft so the action can be reviewed against the current site."
        )
    if context_id and selected_target_for_context(context_id) != target:
        raise JiraTargetResolutionError(
            "The Jira site selected for this tab changed after the draft was prepared. Re-draft the action."
        )
    return target


_ROVO_OPERATION_TO_TOOL = {
    "get_issue": "getJiraIssue",
    "create_issue": "createJiraIssue",
    "update_issue": "editJiraIssue",
    "add_comment": "addCommentToJiraIssue",
    "transition_issue": "transitionJiraIssue",
    "create_link": "createIssueLink",
    "lookup_account": "lookupJiraAccountId",
    "get_projects": "getVisibleJiraProjects",
    "get_issue_types": "getJiraProjectIssueTypesMetadata",
    "get_create_meta": "getJiraIssueTypeMetaWithFields",
}


def rovo_jira_call(target: JiraTarget, operation: str, arguments: dict) -> object:
    """Call one allowlisted Rovo Jira operation for its captured resource.

    The connection and accessible-resource list are read again at execution
    time. This picks up refreshed OAuth while refusing a disconnected or
    reauthorized connection whose resource no longer belongs to the draft.
    No operation is inferred from a model-provided tool name.
    """
    if target.adapter != "rovo-mcp":
        raise JiraTargetResolutionError("This operation requires a Rovo-backed Jira target.")
    tool_name = _ROVO_OPERATION_TO_TOOL.get(operation)
    if not tool_name:
        raise JiraTargetResolutionError(f"Rovo does not have a verified adapter for {operation!r}.")
    from mcp.manager import _client_for, _load_connections
    connection = next((c for c in _load_connections() if c.get("id") == target.connection_id and c.get("enabled", True)), None)
    if connection is None:
        raise JiraTargetResolutionError("The selected Rovo connection is no longer available. Reconnect it and re-draft the action.")
    cached = connection.get("cached_tools", []) or []
    names = {str(tool.get("name", "")) for tool in cached if isinstance(tool, dict)}
    if tool_name not in names or "getAccessibleAtlassianResources" not in names:
        raise JiraTargetResolutionError(f"The selected Rovo connection does not support {operation.replace('_', ' ')}.")
    client = None
    try:
        client = _client_for(connection, pooled=False)
        raw_resources = client.call("getAccessibleAtlassianResources", {})
        parsed = json.loads(raw_resources) if isinstance(raw_resources, str) else raw_resources
        resources = parsed.get("resources", parsed) if isinstance(parsed, dict) else parsed
        if not isinstance(resources, list) or not any(
            isinstance(item, dict) and str(item.get("id", "")) == target.resource_id
            and _canonical_base_url(str(item.get("url", ""))) == target.base_url
            for item in resources
        ):
            raise JiraTargetResolutionError("The selected Jira site is no longer accessible through this Rovo connection. Reconnect and re-draft.")
        payload = dict(arguments or {})
        payload["cloudId"] = target.resource_id
        raw = client.call(tool_name, payload)
        try:
            return json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, json.JSONDecodeError):
            return raw
    finally:
        if client is not None and hasattr(client, "close"):
            try:
                client.close()
            except Exception:
                pass


def verified_result(target: JiraTarget, requested: dict, applied: dict, verified: dict) -> dict:
    """Standard success payload. Call only after a target-scoped re-read."""

    issue_key = str(applied.get("issue_key") or requested.get("issue_key") or "")
    result = {
        "ok": True,
        "target": target.public_dict(),
        "requested": requested,
        "applied": applied,
        "verified": verified,
    }
    if issue_key:
        result["canonical_issue_url"] = target.issue_url(issue_key)
    return result


def compare_jira_fields(requested: dict, actual: dict) -> tuple[dict, dict]:
    """Return exact, evidence-backed field matches and mismatches.

    Jira expands entity objects returned from GET (for example, a component
    gets a description in addition to the requested ``id``).  A requested
    mapping is therefore compared as a recursive subset of the read-back
    value. Scalars remain exact and a requested list must be represented by
    matching values on the server. This deliberately returns a mismatch when
    a value cannot be established; callers must not infer success from a 2xx.
    """

    def _matches(expected, observed) -> bool:
        if isinstance(expected, dict):
            return isinstance(observed, dict) and all(
                key in observed and _matches(value, observed[key])
                for key, value in expected.items()
            )
        if isinstance(expected, list):
            if not isinstance(observed, list) or len(expected) != len(observed):
                return False
            unmatched = list(observed)
            for value in expected:
                for index, candidate in enumerate(unmatched):
                    if _matches(value, candidate):
                        unmatched.pop(index)
                        break
                else:
                    return False
            return True
        return expected == observed

    confirmed: dict = {}
    rejected: dict = {}
    for field, expected in requested.items():
        observed = actual.get(field)
        if _matches(expected, observed):
            confirmed[field] = observed
        else:
            rejected[field] = {"requested": expected, "actual": observed}
    return confirmed, rejected
