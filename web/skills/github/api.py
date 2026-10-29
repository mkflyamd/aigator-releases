"""GitHub API client — routes to REST API (github.com) or Enterprise MCP server.

Routing logic:
  - saved GitHub URL not set or github.com → REST API directly
  - saved GitHub URL is a GitHub Enterprise URL → MCP server at GITHUB_MCP_URL

Set GITHUB_MCP_URL env var to point at your GitHub MCP server endpoint.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from . import credentials, gh_cli


def _is_enterprise() -> bool:
    return credentials.is_enterprise()


def _rest_base() -> str:
    if credentials.is_enterprise():
        return f"{credentials.get_base_url()}/api/v3"
    return "https://api.github.com"


def _token() -> str:
    t = credentials.get_token()
    if not t:
        raise RuntimeError("GitHub credentials not configured — add them in Settings.")
    return t


# ── REST implementation ────────────────────────────────────────────────────────


def _rest(path: str, method: str = "GET", body: dict | None = None) -> dict:
    """Make a single GitHub REST API call."""
    url = f"{_rest_base()}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="ignore")[:500]
        failure = {"error": f"GitHub API {e.code}: {body_text}"}
        if e.code in _ORG_REFUSAL_CODES and method == "GET":
            return _retry_with_gh_login(path, failure)
        return failure
    except Exception as e:
        return {"error": f"GitHub API call failed: {e}"}


_ORG_REFUSAL_CODES = (401, 403)
_GH_MAX_OUTPUT = 50_000_000


def _retry_with_gh_login(path: str, refused: dict) -> dict:
    """Orgs can reject the saved token (classic PATs banned, SAML SSO not authorized) while the
    user's own `gh auth login` works, so a refused read is retried once as that user."""
    got = gh_cli.run_gh(["api", path.lstrip("/")], max_output=_GH_MAX_OUTPUT, use_saved_token=False)
    if not got.get("error"):
        try:
            return json.loads(got["stdout"])
        except ValueError:
            got = {"error": "gh returned output that is not JSON."}
    owner = path.lstrip("/").split("/")[1:2]
    sso = f"https://github.com/orgs/{owner[0]}/sso" if path.startswith("/repos/") and owner else ""
    hint = f" If the organization enforces SAML SSO, authorize your gh login at {sso}." if sso else ""
    return {"error": f"{refused['error']} | Retry through gh also failed: {got['error']}{hint}"}


_PAGE_SIZE = 100
_MAX_PAGES = 3


def _rest_list(path: str) -> list:
    """Fetch up to _MAX_PAGES pages of a REST list endpoint; errors yield what was fetched so far."""
    items: list = []
    for page in range(1, _MAX_PAGES + 1):
        sep = "&" if "?" in path else "?"
        data = _rest(f"{path}{sep}per_page={_PAGE_SIZE}&page={page}")
        if not isinstance(data, list):
            break
        items.extend(data)
        if len(data) < _PAGE_SIZE:
            break
    return items


def _rest_tool(tool_name: str, inputs: dict) -> dict:
    """Map MCP-style tool names to GitHub REST API calls."""
    if tool_name == "get_me":
        return _rest("/user")

    elif tool_name == "search_issues":
        q = urllib.parse.quote(inputs.get("query", ""))
        per = inputs.get("perPage", 20)
        data = _rest(f"/search/issues?q={q}&per_page={per}")
        items = data.get("items", [])
        return {"items": items, "total_count": data.get("total_count", len(items))}

    elif tool_name == "search_pull_requests":
        # GitHub search API handles both issues and PRs via the same /search/issues endpoint
        q = urllib.parse.quote(inputs.get("query", ""))
        per = inputs.get("perPage", 20)
        data = _rest(f"/search/issues?q={q}&per_page={per}")
        items = data.get("items", [])
        return {
            "items": items,
            "pull_requests": items,
            "total_count": data.get("total_count", len(items)),
        }

    elif tool_name == "issue_read":
        method = inputs.get("method", "get")
        owner, repo, num = inputs["owner"], inputs["repo"], inputs["issueNumber"]
        if method == "get":
            return _rest(f"/repos/{owner}/{repo}/issues/{num}")
        elif method == "get_comments":
            data = _rest(f"/repos/{owner}/{repo}/issues/{num}/comments")
            return {"comments": data if isinstance(data, list) else []}

    elif tool_name == "pull_request_read":
        method = inputs.get("method", "get")
        owner, repo, num = inputs["owner"], inputs["repo"], inputs["pullNumber"]
        if method == "get":
            return _rest(f"/repos/{owner}/{repo}/pulls/{num}")
        elif method == "get_reviews":
            return {"reviews": _rest_list(f"/repos/{owner}/{repo}/pulls/{num}/reviews")}
        elif method == "get_check_runs":
            # Need the head SHA first, then fetch check runs for that commit
            pr = _rest(f"/repos/{owner}/{repo}/pulls/{num}")
            if "error" in pr:
                return pr
            sha = pr.get("head", {}).get("sha", "")
            if not sha:
                return {"check_runs": []}
            data = _rest(f"/repos/{owner}/{repo}/commits/{sha}/check-runs?per_page={_PAGE_SIZE}")
            return {"check_runs": data.get("check_runs", [])}
        elif method == "get_comments":
            # The PR conversation lives on the issue; /pulls/{n}/comments is inline review comments only.
            return {"comments": _rest_list(f"/repos/{owner}/{repo}/issues/{num}/comments")}
        elif method == "get_review_comments":
            return {"comments": _rest_list(f"/repos/{owner}/{repo}/pulls/{num}/comments")}
        elif method == "get_files":
            return {"files": _rest_list(f"/repos/{owner}/{repo}/pulls/{num}/files")}

    elif tool_name == "search_repositories":
        q = urllib.parse.quote(inputs.get("query", ""))
        per = inputs.get("perPage", 20)
        data = _rest(f"/search/repositories?q={q}&per_page={per}")
        items = data.get("items", [])
        return {
            "items": items,
            "repositories": items,
            "total_count": data.get("total_count", len(items)),
        }

    elif tool_name == "search_code":
        q = urllib.parse.quote(inputs.get("query", ""))
        per = inputs.get("perPage", 10)
        data = _rest(f"/search/code?q={q}&per_page={per}")
        items = data.get("items", [])
        return {"items": items, "total_count": data.get("total_count", len(items))}

    elif tool_name == "list_my_repos":
        per = inputs.get("perPage", 30)
        data = _rest(
            f"/user/repos?sort=updated&per_page={per}&affiliation=owner,collaborator"
        )
        repos = data if isinstance(data, list) else []
        return {"items": repos, "repositories": repos}

    elif tool_name == "list_repo_issues":
        owner, repo = inputs["owner"], inputs["repo"]
        state = inputs.get("state", "open")
        per = inputs.get("perPage", 30)
        data = _rest(f"/repos/{owner}/{repo}/issues?state={state}&per_page={per}")
        issues = data if isinstance(data, list) else []
        return {"items": issues, "total_count": len(issues)}

    elif tool_name == "create_issue":
        owner, repo = inputs["owner"], inputs["repo"]
        body: dict = {"title": inputs["title"]}
        if inputs.get("body"):
            body["body"] = inputs["body"]
        if inputs.get("labels"):
            body["labels"] = inputs["labels"]
        if inputs.get("assignees"):
            body["assignees"] = inputs["assignees"]
        return _rest(f"/repos/{owner}/{repo}/issues", method="POST", body=body)

    elif tool_name == "add_issue_comment":
        owner, repo, num = inputs["owner"], inputs["repo"], inputs["issueNumber"]
        return _rest(
            f"/repos/{owner}/{repo}/issues/{num}/comments",
            method="POST",
            body={"body": inputs["body"]},
        )

    return {"error": f"Unknown tool: {tool_name}"}


# ── MCP implementation (Enterprise) ───────────────────────────────────────────


def _mcp_tool(tool_name: str, inputs: dict) -> dict:
    """Forward a tool call to a hosted GitHub MCP server."""
    mcp_url = os.environ.get("GITHUB_MCP_URL", "")
    if not mcp_url:
        return {"error": "GITHUB_MCP_URL not configured"}
    payload = json.dumps({"tool": tool_name, "input": inputs}).encode()
    req = urllib.request.Request(
        mcp_url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_token()}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": f"GitHub MCP call failed: {e}"}


# ── Public entry point ─────────────────────────────────────────────────────────


def github_api(tool_name: str, inputs: dict) -> dict:
    """Route a tool call to REST API (github.com) or Enterprise MCP server."""
    if _is_enterprise():
        return _mcp_tool(tool_name, inputs)
    return _rest_tool(tool_name, inputs)
