"""Branch and worktree operations for the Code view.

Every call passes arguments to git as a list (never a shell string), validates names with
git's own ref-name rules, and never forces: git's refusals (uncommitted changes, unmerged
branch, branch checked out elsewhere) are reported to the user as 409.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from proc_utils import no_window_kwargs

GIT_TIMEOUT_SECONDS = 15
MAX_REF_LENGTH = 200


class GitOpError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _git(repo: str, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_SECONDS,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            **no_window_kwargs(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitOpError(500, "git_failed", f"git could not run: {type(exc).__name__}") from exc


def _reason(proc: subprocess.CompletedProcess) -> str:
    lines = [ln.strip() for ln in (proc.stderr or proc.stdout or "").splitlines() if ln.strip()]
    return re.sub(r"^(error|fatal): ", "", lines[0]) if lines else "git refused the operation"


def _valid_ref(repo: str, name: str) -> str:
    if not isinstance(name, str) or not name or len(name) > MAX_REF_LENGTH or name.startswith("-"):
        raise GitOpError(400, "bad_name", "That is not a valid branch name.")
    if _git(repo, "check-ref-format", f"refs/heads/{name}").returncode != 0:
        raise GitOpError(400, "bad_name", "That is not a valid branch name.")
    return name


def _norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _current_branch(repo: str) -> str | None:
    proc = _git(repo, "symbolic-ref", "--short", "-q", "HEAD")
    return proc.stdout.strip() or None if proc.returncode == 0 else None


def _local_exists(repo: str, name: str) -> bool:
    return _git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{name}").returncode == 0


def _default_branch(repo: str) -> str | None:
    proc = _git(repo, "symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD")
    if proc.returncode == 0 and "/" in proc.stdout:
        return proc.stdout.strip().split("/", 1)[1]
    for name in ("main", "master"):
        if _local_exists(repo, name):
            return name
    return None


def list_worktrees(repo: str) -> list[dict]:
    proc = _git(repo, "worktree", "list", "--porcelain")
    if proc.returncode != 0:
        raise GitOpError(500, "git_failed", _reason(proc))
    out: list[dict] = []
    for block in proc.stdout.split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.strip().splitlines():
            key, _, value = line.partition(" ")
            fields[key] = value
        if "worktree" not in fields or "bare" in fields:
            continue
        branch = fields.get("branch", "")
        out.append(
            {
                "path": fields["worktree"],
                "branch": branch[len("refs/heads/"):] if branch.startswith("refs/heads/") else None,
                "head": fields.get("HEAD", "")[:7],
                "is_main": not out,
                "prunable": "prunable" in fields,
            }
        )
    return out


def list_branches(repo: str) -> dict:
    checked_out = {w["branch"]: w["path"] for w in list_worktrees(repo) if w["branch"]}
    current = _current_branch(repo)
    local = _git(repo, "for-each-ref", "--format=%(refname)", "refs/heads").stdout.splitlines()
    remote = _git(repo, "for-each-ref", "--format=%(refname)", "refs/remotes").stdout.splitlines()
    names = sorted(r[len("refs/heads/"):] for r in local)
    return {
        "current": current,
        "default": _default_branch(repo),
        "local": [{"name": n, "current": n == current, "worktree": checked_out.get(n)} for n in names],
        "remote": sorted(
            r[len("refs/remotes/"):] for r in remote if r.startswith("refs/remotes/") and not r.endswith("/HEAD")
        ),
    }


def resolve_worktree(repo: str, path: str) -> str:
    """The project folder, or one of its listed worktrees; anything else is rejected."""
    if not path:
        return repo
    wanted = _norm(path)
    for w in list_worktrees(repo):
        if _norm(w["path"]) == wanted:
            return w["path"]
    raise GitOpError(400, "unknown_worktree", "That folder is not a worktree of this project.")


def checkout(repo: str, name: str, confirm_dirty: bool = False) -> None:
    _valid_ref(repo, name)
    if _local_exists(repo, name):
        switch = ["switch", name]
    elif _git(repo, "show-ref", "--verify", "--quiet", f"refs/remotes/{name}").returncode == 0:
        switch = ["switch", "--track", name]
    else:
        raise GitOpError(404, "no_branch", f"There is no branch named {name}.")
    dirty = _git(repo, "status", "--porcelain", "--untracked-files=no").stdout.strip()
    if dirty and not confirm_dirty:
        raise GitOpError(409, "dirty", "You have uncommitted changes. Switching branches will carry them along.")
    proc = _git(repo, *switch)
    if proc.returncode != 0:
        raise GitOpError(409, "checkout_refused", _reason(proc))


def create_branch(repo: str, name: str) -> None:
    _valid_ref(repo, name)
    if _local_exists(repo, name):
        raise GitOpError(409, "exists", f"A branch named {name} already exists.")
    proc = _git(repo, "switch", "-c", name)
    if proc.returncode != 0:
        raise GitOpError(409, "create_refused", _reason(proc))


def delete_branch(repo: str, name: str) -> None:
    _valid_ref(repo, name)
    if not _local_exists(repo, name):
        raise GitOpError(404, "no_branch", f"There is no branch named {name}.")
    if name == _current_branch(repo):
        raise GitOpError(409, "current_branch", "You cannot delete the branch you are on.")
    if name == _default_branch(repo):
        raise GitOpError(409, "default_branch", "You cannot delete the default branch.")
    proc = _git(repo, "branch", "-d", name)
    if proc.returncode != 0:
        raise GitOpError(409, "delete_refused", _reason(proc))


def _folder_slug(branch: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip("-.") or "worktree"


def add_worktree(repo: str, branch: str) -> dict:
    """A worktree for a branch (created from HEAD if new) in a sibling folder of the main one."""
    _valid_ref(repo, branch)
    main = Path(list_worktrees(repo)[0]["path"])
    target = main.parent / f"{main.name}-worktrees" / _folder_slug(branch)
    if target.exists():
        raise GitOpError(409, "folder_exists", f"The folder {target} already exists.")
    if _local_exists(repo, branch):
        proc = _git(repo, "worktree", "add", str(target), branch)
    else:
        proc = _git(repo, "worktree", "add", "-b", branch, str(target))
    if proc.returncode != 0:
        raise GitOpError(409, "worktree_refused", _reason(proc))
    return {"path": str(target)}


def remove_worktree(repo: str, path: str) -> None:
    wanted = _norm(path)
    listed = list_worktrees(repo)
    match = next((w for w in listed if _norm(w["path"]) == wanted), None)
    if match is None:
        raise GitOpError(400, "unknown_worktree", "That folder is not a worktree of this project.")
    if match["is_main"]:
        raise GitOpError(409, "main_worktree", "You cannot remove the project's main folder.")
    proc = _git(listed[0]["path"], "worktree", "remove", match["path"])
    if proc.returncode != 0:
        if _git(match["path"], "status", "--porcelain").stdout.strip():
            raise GitOpError(
                409, "remove_refused", "This worktree has uncommitted changes. Commit or discard them first."
            )
        raise GitOpError(409, "remove_refused", _reason(proc))
