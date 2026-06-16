"""GitHub API client — routes to REST API (github.com) or Enterprise MCP server.

Routing logic:
  - GITHUB_BASE_URL not set or github.com → REST API directly
  - GITHUB_BASE_URL is a GitHub Enterprise URL → MCP server at GITHUB_MCP_URL

Set GITHUB_MCP_URL env var to point at your GitHub MCP server endpoint.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request


def _is_enterprise() -> bool:
    base = os.environ.get("GITHUB_BASE_URL", "")
    return bool(base) and "github.com" not in base


def _rest_base() -> str:
    base = os.environ.get("GITHUB_BASE_URL", "").rstrip("/")
    if base and "github.com" not in base:
        return f"{base}/api/v3"
    return "https://api.github.com"


def _token() -> str:
    t = os.environ.get("GITHUB_TOKEN", "")
    if not t:
        raise RuntimeError("GitHub credentials not configured — add them in Settings.")
    return t


# ── REST implementation ────────────────────────────────────────────────────────

def _rest(path: str, method: str = "GET", body: dict | None = None) -> dict:
    """Make a single GitHub REST API call."""
    url = f"{_rest_base()}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="ignore")[:500]
        return {"error": f"GitHub API {e.code}: {body_text}"}
    except Exception as e:
        return {"error": f"GitHub API call failed: {e}"}


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
        return {"items": items, "pull_requests": items, "total_count": data.get("total_count", len(items))}

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
            data = _rest(f"/repos/{owner}/{repo}/pulls/{num}/reviews")
            return {"reviews": data if isinstance(data, list) else []}
        elif method == "get_check_runs":
            # Need the head SHA first, then fetch check runs for that commit
            pr = _rest(f"/repos/{owner}/{repo}/pulls/{num}")
            if "error" in pr:
                return pr
            sha = pr.get("head", {}).get("sha", "")
            if not sha:
                return {"check_runs": []}
            data = _rest(f"/repos/{owner}/{repo}/commits/{sha}/check-runs")
            return {"check_runs": data.get("check_runs", [])}
        elif method == "get_comments":
            data = _rest(f"/repos/{owner}/{repo}/pulls/{num}/comments")
            return {"comments": data if isinstance(data, list) else []}
        elif method == "get_files":
            data = _rest(f"/repos/{owner}/{repo}/pulls/{num}/files")
            return {"files": data if isinstance(data, list) else []}

    elif tool_name == "search_repositories":
        q = urllib.parse.quote(inputs.get("query", ""))
        per = inputs.get("perPage", 20)
        data = _rest(f"/search/repositories?q={q}&per_page={per}")
        items = data.get("items", [])
        return {"items": items, "repositories": items, "total_count": data.get("total_count", len(items))}

    elif tool_name == "search_code":
        q = urllib.parse.quote(inputs.get("query", ""))
        per = inputs.get("perPage", 10)
        data = _rest(f"/search/code?q={q}&per_page={per}")
        items = data.get("items", [])
        return {"items": items, "total_count": data.get("total_count", len(items))}

    elif tool_name == "list_my_repos":
        per = inputs.get("perPage", 30)
        data = _rest(f"/user/repos?sort=updated&per_page={per}&affiliation=owner,collaborator")
        repos = data if isinstance(data, list) else []
        return {"items": repos, "repositories": repos}

    return {"error": f"Unknown tool: {tool_name}"}


# ── MCP implementation (Enterprise) ───────────────────────────────────────────

def _mcp_tool(tool_name: str, inputs: dict) -> dict:
    """Forward a tool call to a hosted GitHub MCP server."""
    mcp_url = os.environ.get("GITHUB_MCP_URL", "")
    if not mcp_url:
        return {"error": "GITHUB_MCP_URL not configured"}
    payload = json.dumps({"tool": tool_name, "input": inputs}).encode()
    req = urllib.request.Request(mcp_url, data=payload, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_token()}",
    })
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
