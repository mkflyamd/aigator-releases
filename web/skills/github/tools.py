"""GitHub skill — 8 tools. Uses REST API for github.com, MCP server for Enterprise."""
from .api import github_api

SKILL_ID = "github"
ALWAYS_ON = False

TOOL_DEFS = [
    {
        "name": "github_whoami",
        "description": "Get the authenticated GitHub user. Use to test the GitHub connection or when user asks who they are on GitHub.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "github_list_my_issues",
        "description": "List GitHub issues assigned to the current user across all repos. Use when user asks about tasks, tickets, bugs, or 'my GitHub issues'.",
        "input_schema": {"type": "object", "properties": {
            "state": {"type": "string", "description": "Filter by state: open (default), closed, all", "default": "open"},
            "per_page": {"type": "integer", "description": "Max results to return. Default 20.", "default": 20},
        }, "required": []},
    },
    {
        "name": "github_list_review_requests",
        "description": "List pull requests where the current user has been requested as a reviewer. Use when user asks 'what PRs need my review' or 'review requests'.",
        "input_schema": {"type": "object", "properties": {
            "per_page": {"type": "integer", "description": "Max results. Default 20.", "default": 20},
        }, "required": []},
    },
    {
        "name": "github_list_my_prs",
        "description": "List pull requests authored by the current user. Use when user asks 'show my PRs' or 'my pull requests'.",
        "input_schema": {"type": "object", "properties": {
            "state": {"type": "string", "description": "Filter: open (default), closed, merged, all", "default": "open"},
            "per_page": {"type": "integer", "description": "Max results. Default 20.", "default": 20},
        }, "required": []},
    },
    {
        "name": "github_get_issue",
        "description": "Get full details of a GitHub issue including body, labels, assignees, milestone, and comments. Use when user asks about a specific issue by number or URL.",
        "input_schema": {"type": "object", "properties": {
            "owner": {"type": "string", "description": "Repository owner or org e.g. rocm"},
            "repo":  {"type": "string", "description": "Repository name e.g. rocm"},
            "issue_number": {"type": "integer", "description": "Issue number"},
        }, "required": ["owner", "repo", "issue_number"]},
    },
    {
        "name": "github_get_pr",
        "description": "Get full details of a pull request including CI check status, reviewer state, file changes, and comments. Use when user asks about a specific PR by number or URL.",
        "input_schema": {"type": "object", "properties": {
            "owner": {"type": "string", "description": "Repository owner or org"},
            "repo":  {"type": "string", "description": "Repository name"},
            "pr_number": {"type": "integer", "description": "Pull request number"},
        }, "required": ["owner", "repo", "pr_number"]},
    },
    {
        "name": "github_search_repos",
        "description": "Search GitHub repositories. Use when user asks to find or list repositories.",
        "input_schema": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Search query e.g. 'org:rocm language:cpp'"},
            "per_page": {"type": "integer", "description": "Max results. Default 20.", "default": 20},
        }, "required": ["query"]},
    },
    {
        "name": "github_search_code",
        "description": "Search code across GitHub repositories. Use when user asks to find code, functions, or patterns.",
        "input_schema": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Code search query e.g. 'hip_malloc repo:rocm/rocm'"},
            "per_page": {"type": "integer", "description": "Max results. Default 10.", "default": 10},
        }, "required": ["query"]},
    },
    {
        "name": "github_list_my_repos",
        "description": "List repositories the authenticated user owns or collaborates on, sorted by recently updated.",
        "input_schema": {"type": "object", "properties": {
            "per_page": {"type": "integer", "description": "Max results. Default 30.", "default": 30},
        }, "required": []},
    },
]

TOOL_STATUS = {
    "github_list_my_repos":       "📁 Loading your repositories…",
    "github_whoami":              "🐙 Checking GitHub connection…",
    "github_list_my_issues":      "🔴 Loading your GitHub issues…",
    "github_list_review_requests": "👀 Fetching review requests…",
    "github_list_my_prs":         "✅ Loading your pull requests…",
    "github_get_issue":           "🔎 Fetching issue details…",
    "github_get_pr":              "🔎 Fetching pull request details…",
    "github_search_repos":        "🔍 Searching repositories…",
    "github_search_code":         "💻 Searching code…",
}


# ── Handlers ───────────────────────────────────────────────────────────────────

def _github_whoami(**_) -> dict:
    return github_api("get_me", {})


def _github_list_my_issues(state: str = "open", per_page: int = 20) -> dict:
    return github_api("search_issues", {
        "query": f"is:issue is:{state} assignee:@me",
        "perPage": per_page,
    })


def _github_list_review_requests(per_page: int = 20) -> dict:
    return github_api("search_pull_requests", {
        "query": "is:pr is:open review-requested:@me",
        "perPage": per_page,
    })


def _github_list_my_prs(state: str = "open", per_page: int = 20) -> dict:
    q = "is:pr author:@me"
    if state != "all":
        q += f" is:{state}"
    return github_api("search_pull_requests", {"query": q, "perPage": per_page})


def _github_get_issue(owner: str, repo: str, issue_number: int) -> dict:
    result = github_api("issue_read", {"method": "get", "owner": owner, "repo": repo, "issueNumber": issue_number})
    comments = github_api("issue_read", {"method": "get_comments", "owner": owner, "repo": repo, "issueNumber": issue_number})
    if "error" not in result:
        result["comments"] = comments.get("comments", [])
    return result


def _github_get_pr(owner: str, repo: str, pr_number: int) -> dict:
    result   = github_api("pull_request_read", {"method": "get",           "owner": owner, "repo": repo, "pullNumber": pr_number})
    reviews  = github_api("pull_request_read", {"method": "get_reviews",   "owner": owner, "repo": repo, "pullNumber": pr_number})
    checks   = github_api("pull_request_read", {"method": "get_check_runs","owner": owner, "repo": repo, "pullNumber": pr_number})
    comments = github_api("pull_request_read", {"method": "get_comments",  "owner": owner, "repo": repo, "pullNumber": pr_number})
    files    = github_api("pull_request_read", {"method": "get_files",     "owner": owner, "repo": repo, "pullNumber": pr_number})
    if "error" not in result:
        result["reviews"]  = reviews.get("reviews", [])
        result["checks"]   = checks.get("check_runs", [])
        result["comments"] = comments.get("comments", [])
        result["files"]    = files.get("files", [])
        # Sum additions/deletions from files if not present in the PR object
        if "additions" not in result and result.get("files"):
            result["additions"]    = sum(f.get("additions", 0) for f in result["files"])
            result["deletions"]    = sum(f.get("deletions", 0) for f in result["files"])
            result["changed_files"] = len(result["files"])
    return result


def _github_search_repos(query: str, per_page: int = 20) -> dict:
    return github_api("search_repositories", {"query": query, "perPage": per_page})


def _github_search_code(query: str, per_page: int = 10) -> dict:
    return github_api("search_code", {"query": query, "perPage": per_page})


def _github_list_my_repos(per_page: int = 30) -> dict:
    return github_api("list_my_repos", {"perPage": per_page})


TOOL_HANDLERS = {
    "github_whoami":               _github_whoami,
    "github_list_my_issues":       _github_list_my_issues,
    "github_list_review_requests": _github_list_review_requests,
    "github_list_my_prs":          _github_list_my_prs,
    "github_get_issue":            _github_get_issue,
    "github_get_pr":               _github_get_pr,
    "github_search_repos":         _github_search_repos,
    "github_search_code":          _github_search_code,
    "github_list_my_repos":        _github_list_my_repos,
}
