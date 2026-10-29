"""GitHub skill — REST/gh tools. Uses REST API for github.com, MCP server for Enterprise."""

from .api import github_api
from .gh_cli import run_gh

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
        "input_schema": {
            "type": "object",
            "properties": {
                "state": {
                    "type": "string",
                    "description": "Filter by state: open (default), closed, all",
                    "default": "open",
                },
                "per_page": {
                    "type": "integer",
                    "description": "Max results to return. Default 20.",
                    "default": 20,
                },
            },
            "required": [],
        },
    },
    {
        "name": "github_list_review_requests",
        "description": "List pull requests where the current user has been requested as a reviewer. Use when user asks 'what PRs need my review' or 'review requests'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "per_page": {
                    "type": "integer",
                    "description": "Max results. Default 20.",
                    "default": 20,
                },
            },
            "required": [],
        },
    },
    {
        "name": "github_list_my_prs",
        "description": "List pull requests authored by the current user. Use when user asks 'show my PRs' or 'my pull requests'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "state": {
                    "type": "string",
                    "description": "Filter: open (default), closed, merged, all",
                    "default": "open",
                },
                "per_page": {
                    "type": "integer",
                    "description": "Max results. Default 20.",
                    "default": 20,
                },
            },
            "required": [],
        },
    },
    {
        "name": "github_get_issue",
        "description": "Get full details of a GitHub issue including body, labels, assignees, milestone, and comments. Use when user asks about a specific issue by number or URL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Repository owner or org e.g. rocm",
                },
                "repo": {"type": "string", "description": "Repository name e.g. rocm"},
                "issue_number": {"type": "integer", "description": "Issue number"},
            },
            "required": ["owner", "repo", "issue_number"],
        },
    },
    {
        "name": "github_get_pr",
        "description": "Get details of a pull request: state, merged/merged_at, labels, CI check status, reviews, the latest conversation comments, inline review comments, and changed files (names and line counts, no diffs). Long text is truncated; github_get_issue with the PR number returns the full conversation. Use when user asks about a specific PR by number or URL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string", "description": "Repository owner or org"},
                "repo": {"type": "string", "description": "Repository name"},
                "pr_number": {"type": "integer", "description": "Pull request number"},
            },
            "required": ["owner", "repo", "pr_number"],
        },
    },
    {
        "name": "github_search_repos",
        "description": "Search GitHub repositories. Use when user asks to find or list repositories.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query e.g. 'org:rocm language:cpp'",
                },
                "per_page": {
                    "type": "integer",
                    "description": "Max results. Default 20.",
                    "default": 20,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "github_search_code",
        "description": "Search code across GitHub repositories. Use when user asks to find code, functions, or patterns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Code search query e.g. 'hip_malloc repo:rocm/rocm'",
                },
                "per_page": {
                    "type": "integer",
                    "description": "Max results. Default 10.",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "github_list_issues",
        "description": "List open issues in a specific GitHub repository. Use when user asks to see issues in a repo, or says 'show me issues in owner/repo'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string", "description": "Repository owner or org"},
                "repo": {"type": "string", "description": "Repository name"},
                "state": {
                    "type": "string",
                    "description": "Filter by state: open (default), closed, all",
                    "default": "open",
                },
                "per_page": {
                    "type": "integer",
                    "description": "Max results. Default 30.",
                    "default": 30,
                },
            },
            "required": ["owner", "repo"],
        },
    },
    {
        "name": "github_create_issue",
        "description": "Create a new GitHub issue in a repository. Use when user asks to file, create, open, or raise an issue or bug report.",
        "input_schema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string", "description": "Repository owner or org"},
                "repo": {"type": "string", "description": "Repository name"},
                "title": {"type": "string", "description": "Issue title"},
                "body": {
                    "type": "string",
                    "description": "Issue body (markdown supported)",
                    "default": "",
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Label names to apply (optional)",
                    "default": [],
                },
                "assignees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "GitHub usernames to assign (optional)",
                    "default": [],
                },
            },
            "required": ["owner", "repo", "title"],
        },
    },
    {
        "name": "github_add_issue_comment",
        "description": "Add a comment to an existing GitHub issue. Use when user asks to comment on, reply to, or update an issue.",
        "input_schema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string", "description": "Repository owner or org"},
                "repo": {"type": "string", "description": "Repository name"},
                "issue_number": {"type": "integer", "description": "Issue number"},
                "body": {
                    "type": "string",
                    "description": "Comment body (markdown supported)",
                },
            },
            "required": ["owner", "repo", "issue_number", "body"],
        },
    },
    {
        "name": "github_list_my_repos",
        "description": "List repositories the authenticated user owns or collaborates on, sorted by recently updated.",
        "input_schema": {
            "type": "object",
            "properties": {
                "per_page": {
                    "type": "integer",
                    "description": "Max results. Default 30.",
                    "default": 30,
                },
            },
            "required": [],
        },
    },
    {
        "name": "github_gh",
        "description": "Run the GitHub CLI (gh) on the user's machine with their own gh login. Use it for anything the other github_* tools do not cover: labels, workflow runs and checks, creating or editing PRs and issues, repo views. Pass args as a list without the leading 'gh', e.g. [\"label\", \"list\", \"-R\", \"owner/repo\"] or [\"pr\", \"checks\", \"92\"]. Use this instead of run_shell for gh, which cannot sign in inside the command sandbox. Allowed: issue, pr (no merge), label, run, workflow, release, repo view/list, search, status, and read-only api. Pass text with --body, not a file or template. cwd (optional) is a local repo folder for commands like pr create; a folder other than the AI Gator working folder needs the user's approval in the chat.",
        "input_schema": {
            "type": "object",
            "properties": {
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "gh arguments, without the leading 'gh'",
                },
                "cwd": {
                    "type": "string",
                    "description": "Local folder to run in (optional)",
                },
            },
            "required": ["args"],
        },
    },
]

TOOL_STATUS = {
    "github_gh": "🐙 Running gh…",
    "github_list_my_repos": "📁 Loading your repositories…",
    "github_whoami": "🐙 Checking GitHub connection…",
    "github_list_my_issues": "🔴 Loading your GitHub issues…",
    "github_list_review_requests": "👀 Fetching review requests…",
    "github_list_my_prs": "✅ Loading your pull requests…",
    "github_get_issue": "🔎 Fetching issue details…",
    "github_get_pr": "🔎 Fetching pull request details…",
    "github_search_repos": "🔍 Searching repositories…",
    "github_search_code": "💻 Searching code…",
    "github_list_issues": "🔍 Listing issues…",
    "github_create_issue": "📝 Creating issue…",
    "github_add_issue_comment": "💬 Adding comment…",
}


# ── Handlers ───────────────────────────────────────────────────────────────────


def _github_whoami(**_) -> dict:
    return github_api("get_me", {})


def _github_list_my_issues(state: str = "open", per_page: int = 20) -> dict:
    return github_api(
        "search_issues",
        {
            "query": f"is:issue is:{state} assignee:@me",
            "perPage": per_page,
        },
    )


def _github_list_review_requests(per_page: int = 20) -> dict:
    return github_api(
        "search_pull_requests",
        {
            "query": "is:pr is:open review-requested:@me",
            "perPage": per_page,
        },
    )


def _github_list_my_prs(state: str = "open", per_page: int = 20) -> dict:
    q = "is:pr author:@me"
    if state != "all":
        q += f" is:{state}"
    return github_api("search_pull_requests", {"query": q, "perPage": per_page})


def _github_get_issue(owner: str, repo: str, issue_number: int) -> dict:
    result = github_api(
        "issue_read",
        {"method": "get", "owner": owner, "repo": repo, "issueNumber": issue_number},
    )
    comments = github_api(
        "issue_read",
        {
            "method": "get_comments",
            "owner": owner,
            "repo": repo,
            "issueNumber": issue_number,
        },
    )
    if "error" not in result:
        result["comments"] = comments.get("comments", [])
    return result


_PR_BODY_CHARS = 2000
_PR_COMMENT_CHARS = 1500
_PR_MAX_COMMENTS = 30
_PR_MAX_FILES = 100
_PR_MAX_CHECKS = 30
_PR_OK_CONCLUSIONS = ("success", "skipped", "neutral")


def _cap(text, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}… [truncated, {len(text)} chars total]"


def _person(user) -> dict:
    return {"login": user.get("login")} if isinstance(user, dict) else {}


def _slim_pr(pr: dict, reviews: list, checks: list, comments: list, review_comments: list, files: list) -> dict:
    """Keep what the model and the GitHub pane read; drop patches, API links and repo objects.

    Status fields come first so they survive in the inline preview if the result still overflows.
    """
    out: dict = {}
    for key in ("number", "title", "state", "merged", "merged_at", "closed_at", "draft"):
        if key in pr:
            out[key] = pr[key]
    out["labels"] = [
        {"name": l.get("name"), "color": l.get("color")} if isinstance(l, dict) else l
        for l in pr.get("labels") or []
    ]
    for key in ("mergeable_state", "html_url", "created_at", "updated_at", "commits",
                "additions", "deletions", "changed_files"):
        if key in pr:
            out[key] = pr[key]
    for key in ("user", "author", "merged_by"):
        if key in pr:
            out[key] = _person(pr[key])
    for key in ("base", "head"):
        if isinstance(pr.get(key), dict):
            out[key] = {"ref": pr[key].get("ref")}
    out["body"] = _cap(pr.get("body"), _PR_BODY_CHARS)

    out["reviews"] = [
        {
            "user": _person(r.get("user")),
            "state": r.get("state"),
            "submitted_at": r.get("submitted_at"),
            "body": _cap(r.get("body"), _PR_COMMENT_CHARS),
        }
        for r in reviews
    ]

    summary: dict = {}
    for c in checks:
        label = c.get("conclusion") or c.get("status") or "unknown"
        summary[label] = summary.get(label, 0) + 1
    shown = checks
    if len(checks) > _PR_MAX_CHECKS:
        shown = [c for c in checks if c.get("conclusion") not in _PR_OK_CONCLUSIONS]
    out["checks_summary"] = summary
    out["checks"] = [
        {"name": c.get("name"), "status": c.get("status"), "conclusion": c.get("conclusion")}
        for c in shown
    ]

    out["comments_total"] = len(comments)
    out["comments"] = [
        {"user": _person(c.get("user")), "created_at": c.get("created_at"),
         "body": _cap(c.get("body"), _PR_COMMENT_CHARS)}
        for c in comments[-_PR_MAX_COMMENTS:]
    ]
    out["review_comments_total"] = len(review_comments)
    out["review_comments"] = [
        {"user": _person(c.get("user")), "path": c.get("path"), "created_at": c.get("created_at"),
         "body": _cap(c.get("body"), _PR_COMMENT_CHARS)}
        for c in review_comments[-_PR_MAX_COMMENTS:]
    ]
    out["files_total"] = len(files)
    out["files"] = [
        {"filename": f.get("filename"), "status": f.get("status"),
         "additions": f.get("additions"), "deletions": f.get("deletions")}
        for f in files[:_PR_MAX_FILES]
    ]
    if "additions" not in out and files:
        out["additions"] = sum(f.get("additions", 0) for f in files)
        out["deletions"] = sum(f.get("deletions", 0) for f in files)
        out["changed_files"] = len(files)
    return out


def _github_get_pr(owner: str, repo: str, pr_number: int) -> dict:
    result = github_api(
        "pull_request_read",
        {"method": "get", "owner": owner, "repo": repo, "pullNumber": pr_number},
    )
    if "error" in result:
        return result
    reviews = github_api(
        "pull_request_read",
        {
            "method": "get_reviews",
            "owner": owner,
            "repo": repo,
            "pullNumber": pr_number,
        },
    )
    checks = github_api(
        "pull_request_read",
        {
            "method": "get_check_runs",
            "owner": owner,
            "repo": repo,
            "pullNumber": pr_number,
        },
    )
    comments = github_api(
        "pull_request_read",
        {
            "method": "get_comments",
            "owner": owner,
            "repo": repo,
            "pullNumber": pr_number,
        },
    )
    files = github_api(
        "pull_request_read",
        {"method": "get_files", "owner": owner, "repo": repo, "pullNumber": pr_number},
    )
    review_comments = github_api(
        "pull_request_read",
        {
            "method": "get_review_comments",
            "owner": owner,
            "repo": repo,
            "pullNumber": pr_number,
        },
    )
    return _slim_pr(
        result,
        reviews.get("reviews", []),
        checks.get("check_runs", []),
        comments.get("comments", []),
        review_comments.get("comments", []),
        files.get("files", []),
    )


def _github_search_repos(query: str, per_page: int = 20) -> dict:
    return github_api("search_repositories", {"query": query, "perPage": per_page})


def _github_search_code(query: str, per_page: int = 10) -> dict:
    return github_api("search_code", {"query": query, "perPage": per_page})


def _github_list_my_repos(per_page: int = 30) -> dict:
    return github_api("list_my_repos", {"perPage": per_page})


def _github_list_issues(
    owner: str, repo: str, state: str = "open", per_page: int = 30
) -> dict:
    return github_api(
        "list_repo_issues",
        {"owner": owner, "repo": repo, "state": state, "perPage": per_page},
    )


def _github_create_issue(
    owner: str,
    repo: str,
    title: str,
    body: str = "",
    labels: list = None,
    assignees: list = None,
) -> dict:
    return github_api(
        "create_issue",
        {
            "owner": owner,
            "repo": repo,
            "title": title,
            "body": body,
            "labels": labels or [],
            "assignees": assignees or [],
        },
    )


def _github_add_issue_comment(
    owner: str, repo: str, issue_number: int, body: str
) -> dict:
    return github_api(
        "add_issue_comment",
        {"owner": owner, "repo": repo, "issueNumber": issue_number, "body": body},
    )


def _github_gh(args: list, cwd: str = None, _context_id: str = "") -> dict:
    return run_gh(args, cwd, _context_id)


TOOL_HANDLERS = {
    "github_gh": _github_gh,
    "github_whoami": _github_whoami,
    "github_list_my_issues": _github_list_my_issues,
    "github_list_review_requests": _github_list_review_requests,
    "github_list_my_prs": _github_list_my_prs,
    "github_get_issue": _github_get_issue,
    "github_get_pr": _github_get_pr,
    "github_search_repos": _github_search_repos,
    "github_search_code": _github_search_code,
    "github_list_my_repos": _github_list_my_repos,
    "github_list_issues": _github_list_issues,
    "github_create_issue": _github_create_issue,
    "github_add_issue_comment": _github_add_issue_comment,
}
