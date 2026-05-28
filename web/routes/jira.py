"""Jira route group — issues, transitions, comments, projects, user search."""

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import shared

router = APIRouter()


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


# ── Jira REST endpoints ───────────────────────────────────────────────

@router.get("/api/jira/my-issues")
def jira_my_issues():
    """Return open issues assigned to the current user."""
    try:
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
def jira_my_work():
    """Return sectioned issue views for the JIRA left pane (assigned, reported, watched, recent, saved filters)."""
    from skills.jira.tools import _jira_search_post
    from skills.jira.api import jira_api, jira_browse_url

    def _fmt(issues):
        return [{"key": i["key"],
                 "summary": i["fields"].get("summary", ""),
                 "status": i["fields"].get("status", {}).get("name", ""),
                 "priority": (i["fields"].get("priority") or {}).get("name", ""),
                 "url": f"{jira_browse_url()}/browse/{i['key']}"}
                for i in issues]

    def _fetch_assigned():
        return ("assigned", _fmt(_jira_search_post(
            "assignee = currentUser() AND status NOT IN (Done,Closed,Resolved) ORDER BY updated DESC", 15
        ).get("issues", [])))

    def _fetch_reported():
        return ("reported", _fmt(_jira_search_post(
            "reporter = currentUser() AND status NOT IN (Done,Closed,Resolved) ORDER BY updated DESC", 15
        ).get("issues", [])))

    def _fetch_watched():
        try:
            return ("watched", _fmt(_jira_search_post(
                "watcher = currentUser() AND status NOT IN (Done,Closed,Resolved) ORDER BY updated DESC", 15
            ).get("issues", [])))
        except Exception:
            return ("watched", [])  # watcher JQL not supported on all instances

    def _fetch_recent():
        return ("recent", _fmt(_jira_search_post(
            "updated >= -7d AND (assignee = currentUser() OR reporter = currentUser()) ORDER BY updated DESC", 15
        ).get("issues", [])))

    def _fetch_filters():
        try:
            data = jira_api("GET", "filter/favourite")
            return ("filters", [{"id": f["id"], "name": f["name"], "jql": f.get("jql", "")}
                                for f in (data if isinstance(data, list) else [])])
        except Exception:
            return ("filters", [])

    try:
        sections = {}
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(fn) for fn in [_fetch_assigned, _fetch_reported, _fetch_watched, _fetch_recent, _fetch_filters]]
            for future in as_completed(futures):
                key, data = future.result()
                sections[key] = data
        return sections
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/jira/filter-issues")
def jira_filter_issues(jql: str):
    """Run a saved filter's JQL and return matching issues."""
    from skills.jira.tools import _jira_search_post
    from skills.jira.api import jira_browse_url
    try:
        data = _jira_search_post(jql, max_results=20)
        issues = [{"key": i["key"],
                   "summary": i["fields"].get("summary", ""),
                   "status": i["fields"].get("status", {}).get("name", ""),
                   "priority": (i["fields"].get("priority") or {}).get("name", ""),
                   "url": f"{jira_browse_url()}/browse/{i['key']}"}
                  for i in data.get("issues", [])]
        return {"issues": issues}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/jira/projects")
def jira_projects():
    """Return all Jira projects the user can see."""
    try:
        from skills.jira.api import jira_api
        data = jira_api("GET", "project")
        projects = sorted(
            [{"key": p["key"], "name": p.get("name", p["key"])} for p in (data if isinstance(data, list) else [])],
            key=lambda p: p["name"]
        )
        return {"projects": projects}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/jira/priorities")
def jira_priorities():
    """Return all priorities configured in this Jira instance."""
    try:
        from skills.jira.api import jira_api
        data = jira_api("GET", "priority")
        priorities = [{"id": p.get("id", ""), "name": p.get("name", "")} for p in (data if isinstance(data, list) else [])]
        return {"priorities": priorities}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/jira/project-meta")
def jira_project_meta(project: str):
    """Return issue types and required fields for a project."""
    try:
        from skills.jira.tools import _tool_jira_get_project_meta
        return _tool_jira_get_project_meta(project)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/jira/issue/{issue_key}")
def jira_get_issue_endpoint(issue_key: str):
    """Return full details of a Jira issue for the third pane."""
    try:
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
def jira_issue_transitions(issue_key: str):
    """Return available status transitions for an issue."""
    try:
        from skills.jira.api import jira_api
        data = jira_api("GET", f"issue/{issue_key}/transitions")
        return {"transitions": [{"id": t["id"], "name": t["name"]} for t in data.get("transitions", [])]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/jira/issue/{issue_key}/transition")
def jira_issue_transition(issue_key: str, req: JiraTransitionRequest):
    """Execute a status transition on an issue."""
    try:
        from skills.jira.tools import _tool_jira_transition
        result = _tool_jira_transition(issue_key, req.transition, req.comment)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/jira/issue/{issue_key}/comment")
def jira_issue_comment(issue_key: str, req: JiraCommentRequest):
    """Add a comment to an issue."""
    try:
        from skills.jira.tools import _tool_jira_add_comment
        if not req.comment.strip():
            raise HTTPException(status_code=400, detail="Comment cannot be empty")
        result = _tool_jira_add_comment(issue_key, req.comment.strip())
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/jira/issue/{issue_key}/assign")
def jira_issue_assign(issue_key: str, req: JiraAssignRequest):
    """Update issue fields (assignee, priority, summary, description)."""
    try:
        from skills.jira.tools import _tool_jira_update_issue
        result = _tool_jira_update_issue(
            issue_key,
            assignee=req.assignee,
            priority=req.priority,
            summary=req.summary,
            description=req.description,
        )
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/jira/myself")
def jira_myself():
    """Return the current JIRA user (for pre-filling reporter)."""
    try:
        from skills.jira.tools import jira_api, jira_is_cloud
        if jira_is_cloud():
            data = jira_api("GET", "myself", api_version="3")
            return {"accountId": data.get("accountId", ""), "displayName": data.get("displayName", ""),
                    "email": data.get("emailAddress", ""), "name": data.get("displayName", "")}
        else:
            data = jira_api("GET", "myself")
            return {"name": data.get("name", ""), "displayName": data.get("displayName", ""),
                    "email": data.get("emailAddress", "")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/jira/user-search")
def jira_user_search(q: str):
    """Search JIRA users by name/email."""
    try:
        from skills.jira.tools import _tool_jira_search_user
        return _tool_jira_search_user(q)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/jira/create-issue")
def jira_create_issue_endpoint(body: dict):
    """Create a Jira issue from the third-pane form (human already reviewed -- bypass AI guard)."""
    try:
        from skills.jira.tools import jira_api, jira_browse_url
        import json as _json
        project = body.get("project", "")
        summary = body.get("summary", "")
        issue_type = body.get("issue_type", "")
        if not project or not summary or not issue_type:
            raise HTTPException(status_code=400, detail="project, summary, issue_type are required")
        fields: dict = {
            "project": {"key": project},
            "summary": summary,
            "issuetype": {"name": issue_type},
        }
        description = body.get("description", "")
        if description:
            fields["description"] = description
        priority = body.get("priority", "")
        if priority:
            # Use id if numeric, name otherwise
            fields["priority"] = {"id": priority} if priority.isdigit() else {"name": priority}
        extra_fields = body.get("extra_fields", "")
        if extra_fields:
            try:
                parsed = _json.loads(extra_fields) if isinstance(extra_fields, str) else extra_fields
                fields.update(parsed)
            except _json.JSONDecodeError as je:
                print(f"[jira-create] extra_fields JSON parse error: {je} | raw: {extra_fields[:200]}", flush=True)
                raise HTTPException(status_code=400, detail=f"Invalid extra_fields JSON: {je}")
        print(f"[jira-create] Submitting fields: {_json.dumps({k: str(v)[:60] for k, v in fields.items()})}", flush=True)
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
                brace_start = err_str.find('{')
                if brace_start >= 0:
                    err_data = _json.loads(err_str[brace_start:])
                    field_errors = err_data.get("errors", {})
                    error_messages = err_data.get("errorMessages", [])
                    all_errors = {**field_errors}
                    for i, msg in enumerate(error_messages):
                        if msg:
                            all_errors[f"_msg_{i}"] = msg
                    if all_errors:
                        raise HTTPException(status_code=400, detail={
                            "message": "Required fields are missing",
                            "field_errors": all_errors,
                        })
            except (ValueError, HTTPException) as ex:
                if isinstance(ex, HTTPException):
                    raise
        raise HTTPException(status_code=500, detail=err_str[:300])
