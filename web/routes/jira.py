"""Jira route group — issues, transitions, comments, projects, user search."""

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

import shared
from security import verify_csrf

router = APIRouter()

# Align with the compositor upload limit and reject oversized payloads before
# they become unbounded process memory in the immutable staging flow.
_MAX_JIRA_ATTACHMENT_BYTES = 20 * 1024 * 1024


def _require_direct_target(context_id: str = "", reference: str = "") -> None:
    """Reject route-level legacy REST reads without a matching direct target."""
    from skills.jira.mutations import JiraTargetResolutionError, resolve_builtin_target
    try:
        resolve_builtin_target(reference, context_id)
    except JiraTargetResolutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# ── Pydantic Models ───────────────────────────────────────────────────


class JiraTransitionRequest(BaseModel):
    transition: str
    comment: str = ""


class JiraCommentRequest(BaseModel):
    comment: str


class JiraAssignRequest(BaseModel):
    assignee: str = ""
    priority: str = ""
    summary: str = ""
    description: str = ""


class JiraTargetSelectionRequest(BaseModel):
    context_id: str
    target_handle: str


class JiraNavigationRequest(BaseModel):
    context_id: str
    url: str


@router.get("/api/jira/targets")
def jira_targets(context_id: str = ""):
    """List connected Jira sites and the UI-owned selection for one tab."""
    from skills.jira.mutations import available_targets, selected_target_for_context

    selected = selected_target_for_context(context_id)
    return {
        "targets": [target.public_dict() for target in available_targets()],
        # Target IDs are internal routing identities. The renderer only needs
        # the public site identity to show current tab state.
        "selected_site": selected.public_dict() if selected else None,
    }


@router.post("/api/jira/targets/select", dependencies=[Depends(verify_csrf)])
def select_jira_target(req: JiraTargetSelectionRequest):
    """Bind a user-selected Jira site to the current tab, not to the model."""
    from skills.jira.mutations import JiraTargetResolutionError, select_target_handle

    try:
        target = select_target_handle(req.context_id, req.target_handle)
    except JiraTargetResolutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "site": target.public_dict()}


@router.post("/api/jira/targets/bind-navigation", dependencies=[Depends(verify_csrf)])
def bind_jira_navigation(req: JiraNavigationRequest):
    """Bind a connected Jira site when Electron navigates the owning tab.

    The URL is user navigation, not a model argument.  Unknown Jira URLs are
    deliberately not bound: callers receive a normal connect-site outcome and
    no later write may use that URL as an authorization shortcut.
    """
    from skills.jira.mutations import (
        JiraTargetResolutionError,
        resolve_jira_target,
        select_target_for_context,
    )

    try:
        target = resolve_jira_target(req.url)
    except JiraTargetResolutionError as exc:
        return {"ok": False, "connect_required": True, "detail": str(exc)}
    select_target_for_context(req.context_id, target.id)
    return {"ok": True, "site": target.public_dict()}


@router.post("/api/jira/targets/discover", dependencies=[Depends(verify_csrf)])
def discover_jira_targets():
    """Refresh Rovo Jira sites from live, authenticated MCP discovery."""
    from skills.jira.mutations import discover_rovo_targets

    targets = discover_rovo_targets()
    return {"ok": True, "targets": [target.public_dict() for target in targets]}


@router.post("/api/jira/attachments/stage", dependencies=[Depends(verify_csrf)])
async def stage_jira_attachment(file: UploadFile = File(...)):
    """Stage user-provided bytes; models never receive or supply a filesystem path."""
    from skills.jira.mutations import JiraTargetResolutionError, stage_attachment

    try:
        chunks: list[bytes] = []
        size = 0
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > _MAX_JIRA_ATTACHMENT_BYTES:
                raise HTTPException(status_code=413, detail="Jira attachments are limited to 20 MB.")
            chunks.append(chunk)
        return {"ok": True, "attachment": stage_attachment(file.filename or "attachment", b"".join(chunks), file.content_type or "")}
    except JiraTargetResolutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── Jira REST endpoints ───────────────────────────────────────────────


@router.get("/api/jira/my-issues")
def jira_my_issues(context_id: str = ""):
    """Return open issues assigned to the current user."""
    try:
        _require_direct_target(context_id)
        from skills.jira.tools import _tool_list_jira_issues

        result = _tool_list_jira_issues(max_results=20)
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/jira/my-work")
def jira_my_work(context_id: str = ""):
    """Return sectioned issue views for the JIRA left pane (assigned, reported, watched, recent, saved filters)."""
    from skills.jira.tools import _jira_search_post
    from skills.jira.api import jira_api, jira_browse_url

    def _fmt(issues):
        return [
            {
                "key": i["key"],
                "summary": i["fields"].get("summary", ""),
                "status": i["fields"].get("status", {}).get("name", ""),
                "priority": (i["fields"].get("priority") or {}).get("name", ""),
                "url": f"{jira_browse_url()}/browse/{i['key']}",
            }
            for i in issues
        ]

    def _fetch_assigned():
        return (
            "assigned",
            _fmt(
                _jira_search_post(
                    "assignee = currentUser() AND status NOT IN (Done,Closed,Resolved) ORDER BY updated DESC",
                    15,
                ).get("issues", [])
            ),
        )

    def _fetch_reported():
        return (
            "reported",
            _fmt(
                _jira_search_post(
                    "reporter = currentUser() AND status NOT IN (Done,Closed,Resolved) ORDER BY updated DESC",
                    15,
                ).get("issues", [])
            ),
        )

    def _fetch_watched():
        try:
            return (
                "watched",
                _fmt(
                    _jira_search_post(
                        "watcher = currentUser() AND status NOT IN (Done,Closed,Resolved) ORDER BY updated DESC",
                        15,
                    ).get("issues", [])
                ),
            )
        except Exception:
            return ("watched", [])  # watcher JQL not supported on all instances

    def _fetch_recent():
        return (
            "recent",
            _fmt(
                _jira_search_post(
                    "updated >= -7d AND (assignee = currentUser() OR reporter = currentUser()) ORDER BY updated DESC",
                    15,
                ).get("issues", [])
            ),
        )

    def _fetch_filters():
        try:
            data = jira_api("GET", "filter/favourite")
            return (
                "filters",
                [
                    {"id": f["id"], "name": f["name"], "jql": f.get("jql", "")}
                    for f in (data if isinstance(data, list) else [])
                ],
            )
        except Exception:
            return ("filters", [])

    try:
        sections = {}
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [
                pool.submit(fn)
                for fn in [
                    _fetch_assigned,
                    _fetch_reported,
                    _fetch_watched,
                    _fetch_recent,
                    _fetch_filters,
                ]
            ]
            for future in as_completed(futures):
                key, data = future.result()
                sections[key] = data
        return sections
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/jira/filter-issues")
def jira_filter_issues(jql: str, context_id: str = ""):
    """Run a saved filter's JQL and return matching issues."""
    from skills.jira.tools import _jira_search_post
    from skills.jira.api import jira_browse_url

    try:
        _require_direct_target(context_id)
        data = _jira_search_post(jql, max_results=20)
        issues = [
            {
                "key": i["key"],
                "summary": i["fields"].get("summary", ""),
                "status": i["fields"].get("status", {}).get("name", ""),
                "priority": (i["fields"].get("priority") or {}).get("name", ""),
                "url": f"{jira_browse_url()}/browse/{i['key']}",
            }
            for i in data.get("issues", [])
        ]
        return {"issues": issues}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/jira/projects")
def jira_projects(context_id: str = ""):
    """Return all Jira projects the user can see."""
    try:
        _require_direct_target(context_id)
        from skills.jira.api import jira_api

        data = jira_api("GET", "project")
        projects = sorted(
            [
                {"key": p["key"], "name": p.get("name", p["key"])}
                for p in (data if isinstance(data, list) else [])
            ],
            key=lambda p: p["name"],
        )
        return {"projects": projects}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/jira/priorities")
def jira_priorities(context_id: str = ""):
    """Return all priorities configured in this Jira instance."""
    try:
        _require_direct_target(context_id)
        from skills.jira.api import jira_api

        data = jira_api("GET", "priority")
        priorities = [
            {"id": p.get("id", ""), "name": p.get("name", "")}
            for p in (data if isinstance(data, list) else [])
        ]
        return {"priorities": priorities}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/jira/project-meta")
def jira_project_meta(project: str, context_id: str = ""):
    """Return issue types and required fields for a project."""
    try:
        _require_direct_target(context_id, project)
        from skills.jira.tools import _tool_jira_get_project_meta

        return _tool_jira_get_project_meta(project)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/jira/field-options")
def jira_field_options(
    request: Request,
    field: str,
    project: str,
    issueType: str = "",
    issueKey: str = "",
    fieldName: str = "",
    context_id: str = "",
):
    """Return allowed options for a custom field by trying multiple Jira API strategies."""
    from skills.jira.api import jira_api
    import urllib.parse

    # Strategy 1: editmeta on an existing issue of this type — most reliable for context-sensitive fields
    if issueKey:
        try:
            data = jira_api("GET", f"issue/{issueKey}/editmeta")
            fields = data.get("fields", {})
            fdata = fields.get(field, {})
            allowed = fdata.get("allowedValues", [])
            if allowed:
                options = [
                    {
                        "id": str(v.get("id", v.get("value", ""))),
                        "name": v.get("value", v.get("name", "")),
                    }
                    for v in allowed
                ]
                return {"options": options, "source": "editmeta"}
        except Exception:
            pass

    # Strategy 2: paginated createmeta (Jira 8.4+) — returns allowedValues per field per issue type
    if issueType:
        try:
            data = jira_api(
                "GET",
                f"issue/createmeta/{urllib.parse.quote(project)}/issuetypes/{urllib.parse.quote(issueType)}",
            )
            fields_list = data.get("fields", {})
            if isinstance(fields_list, dict):
                fdata = fields_list.get(field, {})
            else:
                # paginated response: fields is a list
                fdata = next(
                    (
                        f
                        for f in (fields_list or [])
                        if f.get("fieldId") == field or f.get("key") == field
                    ),
                    {},
                )
            allowed = fdata.get("allowedValues", [])
            if allowed:
                options = [
                    {
                        "id": str(v.get("id", v.get("value", ""))),
                        "name": v.get("value", v.get("name", "")),
                    }
                    for v in allowed
                ]
                return {"options": options, "source": "createmeta-paginated"}
        except Exception:
            pass

    # Strategy 3: JQL autocomplete — try both the field key and field display name
    # Dynamic Fields (and some other custom fields) only work with the display name here
    for field_ref in (
        [field, fieldName] if fieldName and fieldName != field else [field]
    ):
        if not field_ref:
            continue
        try:
            params = f"fieldName={urllib.parse.quote(field_ref)}"
            data = jira_api("GET", f"jql/autocompletedata/suggestions?{params}")
            results = data if isinstance(data, list) else data.get("results", [])
            if results:
                import re as _re

                def _clean(name):
                    # Strip trailing " [<uuid>]" appended by Dynamic Fields plugin
                    return _re.sub(r"\s+\[[0-9a-f\-]{36}\]\s*$", "", name or "").strip()

                options = [
                    {
                        "id": r.get("value", ""),
                        "name": _clean(r.get("displayName", r.get("value", ""))),
                    }
                    for r in results
                    if r
                ]
                return {"options": options, "source": "jql-autocomplete"}
        except Exception:
            pass

    # Strategy 4: field/{id}/option — Cloud/newer DC endpoint
    try:
        data = jira_api("GET", f"field/{field}/option?maxResults=100")
        values = data.get("values", [])
        if values:
            options = [
                {
                    "id": str(v.get("id", "")),
                    "name": v.get("value", v.get("name", str(v.get("id", "")))),
                }
                for v in values
            ]
            return {"options": options, "source": "field-option"}
    except Exception:
        pass

    return {"options": [], "source": "none"}


@router.get("/api/jira/issue/{issue_key}")
def jira_get_issue_endpoint(issue_key: str, context_id: str = ""):
    """Return full details of a Jira issue for the third pane."""
    try:
        _require_direct_target(context_id, issue_key)
        from skills.jira.tools import _tool_jira_get_issue

        result = _tool_jira_get_issue(issue_key)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/jira/issue/{issue_key}/transitions")
def jira_issue_transitions(issue_key: str, context_id: str = ""):
    """Return available status transitions for an issue."""
    try:
        _require_direct_target(context_id, issue_key)
        from skills.jira.api import jira_api

        data = jira_api("GET", f"issue/{issue_key}/transitions")
        return {
            "transitions": [
                {"id": t["id"], "name": t["name"]} for t in data.get("transitions", [])
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/jira/issue/{issue_key}/transition")
def jira_issue_transition(issue_key: str, req: JiraTransitionRequest, context_id: str = ""):
    """Execute a status transition on an issue."""
    try:
        _require_direct_target(context_id, issue_key)
        from skills.jira.tools import _tool_jira_transition

        result = _tool_jira_transition(issue_key, req.transition, req.comment, _context_id=context_id)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/jira/issue/{issue_key}/comment")
def jira_issue_comment(issue_key: str, req: JiraCommentRequest, context_id: str = ""):
    """Add a comment to an issue."""
    try:
        _require_direct_target(context_id, issue_key)
        from skills.jira.tools import _tool_jira_add_comment

        if not req.comment.strip():
            raise HTTPException(status_code=400, detail="Comment cannot be empty")
        result = _tool_jira_add_comment(issue_key, req.comment.strip(), _context_id=context_id)
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/jira/issue/{issue_key}/assign")
def jira_issue_assign(issue_key: str, req: JiraAssignRequest, context_id: str = ""):
    """Update issue fields (assignee, priority, summary, description)."""
    try:
        _require_direct_target(context_id, issue_key)
        from skills.jira.tools import _tool_jira_update_issue

        result = _tool_jira_update_issue(
            issue_key,
            assignee=req.assignee,
            priority=req.priority,
            summary=req.summary,
            description=req.description,
            _context_id=context_id,
        )
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/jira/myself")
def jira_myself(context_id: str = ""):
    """Return the current JIRA user (for pre-filling reporter)."""
    try:
        _require_direct_target(context_id)
        from skills.jira.tools import jira_api, jira_is_cloud

        if jira_is_cloud():
            data = jira_api("GET", "myself", api_version="3")
            return {
                "accountId": data.get("accountId", ""),
                "displayName": data.get("displayName", ""),
                "email": data.get("emailAddress", ""),
                "name": data.get("displayName", ""),
            }
        else:
            data = jira_api("GET", "myself")
            return {
                "name": data.get("name", ""),
                "displayName": data.get("displayName", ""),
                "email": data.get("emailAddress", ""),
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/jira/user-search")
def jira_user_search(q: str, context_id: str = ""):
    """Search JIRA users by name/email."""
    try:
        _require_direct_target(context_id)
        from skills.jira.tools import _tool_jira_search_user

        return _tool_jira_search_user(q)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/jira/create-issue", dependencies=[Depends(verify_csrf)])
def jira_create_issue_endpoint(body: dict):
    """Retired raw-create endpoint; creation is only available via a Jira draft."""
    raise HTTPException(
        status_code=410,
        detail=(
            "Direct Jira creation is disabled. Use the target-bound Jira draft approval "
            "flow so AI Gator can verify the created issue on the selected site."
        ),
    )
    # Historical implementation deliberately remains below temporarily for
    # migration reference, but is unreachable and must not be re-enabled.
    try:
        from skills.jira.tools import (
            jira_api,
            jira_browse_url,
            jira_is_cloud,
            _build_adf_doc,
        )
        import json as _json

        project = body.get("project", "")
        summary = body.get("summary", "")
        issue_type = body.get("issue_type", "")
        if not project or not summary or not issue_type:
            raise HTTPException(
                status_code=400, detail="project, summary, issue_type are required"
            )
        is_cloud = jira_is_cloud()
        fields: dict = {
            "project": {"key": project},
            "summary": summary,
            "issuetype": {"name": issue_type},
        }
        description = body.get("description", "")
        if description:
            # Cloud (API v3) requires ADF; Server (v2) accepts plain text.
            fields["description"] = (
                _build_adf_doc(description) if is_cloud else description
            )
        priority = body.get("priority", "")
        if priority:
            # Use id if numeric, name otherwise
            fields["priority"] = (
                {"id": priority} if priority.isdigit() else {"name": priority}
            )
        extra_fields = body.get("extra_fields", {})
        # field_schemas: {"customfield_10039": "doc", ...} — sent by the frontend so the
        # backend can apply ADF wrapping for rich-text fields without a second API call.
        field_schemas = body.get("field_schemas", {})
        print(
            f"[jira-create] field_schemas={_json.dumps(field_schemas)} extra_fields_keys={list((extra_fields if isinstance(extra_fields, dict) else {}).keys())}",
            flush=True,
        )
        if extra_fields:
            try:
                parsed = (
                    _json.loads(extra_fields)
                    if isinstance(extra_fields, str)
                    else extra_fields
                )
            except _json.JSONDecodeError as je:
                print(
                    f"[jira-create] extra_fields JSON parse error: {je} | raw: {str(extra_fields)[:200]}",
                    flush=True,
                )
                raise HTTPException(
                    status_code=400, detail=f"Invalid extra_fields JSON: {je}"
                )
            for key, value in parsed.items():
                schema_type = field_schemas.get(key, "")
                if schema_type == "doc" and isinstance(value, str) and value:
                    # Backend owns ADF wrapping — Cloud only, same guard as description field.
                    fields[key] = _build_adf_doc(value) if is_cloud else value
                else:
                    fields[key] = value
        print(
            f"[jira-create] Submitting fields: {_json.dumps({k: str(v)[:60] for k, v in fields.items()})}",
            flush=True,
        )
        data = jira_api("POST", "issue", {"fields": fields})
        key = data.get("key", "")
        return {"created": True, "key": key, "url": f"{jira_browse_url()}/browse/{key}"}
    except HTTPException:
        raise
    except Exception as e:
        err_str = str(e)
        print(f"[jira-create] ERROR: {err_str[:500]}", flush=True)
        # Parse JIRA field validation errors into a structured response
        if "400" in err_str:
            try:
                # Find the JSON body in the error string
                brace_start = err_str.find("{")
                if brace_start >= 0:
                    err_data = _json.loads(err_str[brace_start:])
                    field_errors = err_data.get("errors", {})
                    error_messages = err_data.get("errorMessages", [])
                    all_errors = {**field_errors}
                    for i, msg in enumerate(error_messages):
                        if msg:
                            all_errors[f"_msg_{i}"] = msg
                    if all_errors:
                        raise HTTPException(
                            status_code=400,
                            detail={
                                "message": "Required fields are missing",
                                "field_errors": all_errors,
                            },
                        )
            except (ValueError, HTTPException) as ex:
                if isinstance(ex, HTTPException):
                    raise
        raise HTTPException(status_code=500, detail=err_str[:300])
    _require_direct_target(context_id)
    _require_direct_target(context_id, issueKey or project)
