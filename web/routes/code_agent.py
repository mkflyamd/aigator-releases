"""Code Agent routes — project registry + git plumbing for the Code tab.

Endpoints:
  GET  /api/code_agent/projects        — list saved projects
  POST /api/code_agent/projects        — add a new project
  PUT  /api/code_agent/projects/active — set active project
  GET  /api/code_agent/git/status      — git status for a project
  GET  /api/code_agent/git/log         — recent commits
  GET  /api/code_agent/git/diff        — file diff
  POST /api/code_agent/git/discard     — discard a file's changes (restore to HEAD)
  GET  /api/code_agent/files/tree      — one directory level, for the file explorer
  GET  /api/code_agent/file/content    — read-only file content, for the file explorer

Shared by the source-control panel and the OpenCode dispatch flow
(see web/routes/opencode_routes.py) — the native chat-driven tool-loop
engine that used to live here (start/followup/apply/decline/undo) has been
retired in favor of OpenCode.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from security import verify_csrf

_log = logging.getLogger(__name__)
router = APIRouter()

# ── Pydantic request models ───────────────────────────────────────────────────

class AddProjectRequest(BaseModel):
    name: str
    repo_path: str
    source: str = "local"  # "local" | "github"

class SetActiveRequest(BaseModel):
    name: str

class DiscardFileRequest(BaseModel):
    project_name: str
    file: str


def _resolve_repo_path(repo: str, rel: str) -> Path:
    """Resolve `rel` (a repo-relative path, as returned by git or the file
    explorer) against `repo`, raising ValueError if it would escape the repo
    root (path traversal)."""
    repo_root = Path(repo).resolve()
    full = (repo_root / rel).resolve() if rel else repo_root
    full.relative_to(repo_root)  # raises ValueError if outside
    return full


# ── GET /projects ─────────────────────────────────────────────────────────────

@router.get("/projects")
async def list_projects():
    """List all saved projects and the active project name."""
    from skills.code_agent.projects import list_projects as _list, get_active_project
    return {
        "projects": _list(),
        "active": get_active_project(),
    }


# ── POST /projects ────────────────────────────────────────────────────────────

@router.post("/projects", dependencies=[Depends(verify_csrf)])
async def add_project(req: AddProjectRequest):
    """Add a new project (local folder or GitHub clone)."""
    from skills.code_agent.projects import add_project as _add
    import functools
    try:
        # _add calls subprocess.run (git status / git clone) — run in thread pool
        project = await asyncio.to_thread(
            functools.partial(_add, req.name, req.repo_path, req.source)
        )
        return {"project": project, "status": "created"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _log.error("add_project error: %s", exc)
        raise HTTPException(status_code=500, detail="Could not add the project. Please try again.")


# ── PUT /projects/active ──────────────────────────────────────────────────────

@router.put("/projects/active", dependencies=[Depends(verify_csrf)])
async def set_active_project(req: SetActiveRequest):
    """Set the active project."""
    from skills.code_agent.projects import set_active_project as _set, get_project
    if not get_project(req.name):
        raise HTTPException(status_code=404, detail=f"Project not found: {req.name}")
    _set(req.name)
    return {"active_project": req.name}


# ── GET /git/status ──────────────────────────────────────────────────────────

@router.get("/git/status")
async def git_status(project_name: str):
    """Get local git status for a project: staged, unstaged, untracked files."""
    from skills.code_agent.projects import get_project
    proj = get_project(project_name)
    if not proj:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_name}")
    repo = proj["repo_path"]
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "-C", repo, "status", "--porcelain=v1", "-u"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10
        )
        staged, unstaged, untracked = [], [], []
        for line in result.stdout.splitlines():
            if len(line) < 3:
                continue
            x, y, fname = line[0], line[1], line[3:]
            if x != " " and x != "?":
                staged.append({"file": fname, "status": x})
            if y == "M" or y == "D":
                unstaged.append({"file": fname, "status": y})
            if x == "?" and y == "?":
                untracked.append({"file": fname, "status": "?"})
        return {"staged": staged, "unstaged": unstaged, "untracked": untracked, "repo": repo}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /git/log ─────────────────────────────────────────────────────────────

@router.get("/git/log")
async def git_log(project_name: str, limit: int = 50):
    """Get recent local commits + ref decorations (local branches, remote refs, HEAD)."""
    from skills.code_agent.projects import get_project
    proj = get_project(project_name)
    if not proj:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_name}")
    repo = proj["repo_path"]
    try:
        # ── 1. Commits with decorated refs ───────────────────────────────────
        # %D gives "HEAD -> main, origin/main, origin/HEAD" style decoration per commit.
        # We use a unique separator so message pipes don't confuse the parser.
        log_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "-C", repo, "log", f"--max-count={limit}",
             "--pretty=format:%H\x1f%s\x1f%ar\x1f%an\x1f%D", "--no-merges",
             "--decorate=full"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10
        )

        # ── 2. HEAD commit hash (to mark HEAD indicator) ──────────────────────
        head_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "-C", repo, "rev-parse", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5
        )
        head_hash = head_result.stdout.strip()

        # ── 3. Parse ref decorations ─────────────────────────────────────────
        # Build a map: full_hash → {local_refs: [...], remote_refs: [...], is_head: bool}
        ref_map: dict[str, dict] = {}

        def _parse_decor(full_hash: str, decor_str: str) -> None:
            entry = ref_map.setdefault(full_hash, {
                "local_refs": [], "remote_refs": [], "tags": [], "is_head": False
            })
            if not decor_str.strip():
                return
            for token in decor_str.split(","):
                token = token.strip()
                if not token:
                    continue
                # "HEAD -> refs/heads/main" or just "HEAD"
                if token == "HEAD" or token.startswith("HEAD ->"):
                    entry["is_head"] = True
                    # extract the branch after "HEAD ->"
                    if "->" in token:
                        token = token.split("->", 1)[1].strip()
                    else:
                        continue
                # refs/tags/v1.0  →  tag "v1.0"
                if token.startswith("refs/tags/"):
                    tag_name = token[len("refs/tags/"):]
                    # strip ^{} peeled-tag suffix
                    if tag_name.endswith("^{}"):
                        tag_name = tag_name[:-3]
                    if tag_name not in entry["tags"]:
                        entry["tags"].append(tag_name)
                # refs/heads/foo  →  local branch "foo"
                elif token.startswith("refs/heads/"):
                    entry["local_refs"].append(token[len("refs/heads/"):])
                # refs/remotes/origin/foo  →  remote ref "origin/foo"
                elif token.startswith("refs/remotes/"):
                    remote_name = token[len("refs/remotes/"):]
                    # skip origin/HEAD pointer
                    if not remote_name.endswith("/HEAD"):
                        entry["remote_refs"].append(remote_name)
                # short forms (no-decorate=full fallback): "origin/main", "main"
                elif "/" in token:
                    entry["remote_refs"].append(token)
                else:
                    entry["local_refs"].append(token)

        raw_commits = []
        for line in log_result.stdout.splitlines():
            parts = line.split("\x1f", 4)
            if len(parts) < 4:
                continue
            full_hash = parts[0]
            message   = parts[1]
            when      = parts[2]
            author    = parts[3]
            decor     = parts[4] if len(parts) == 5 else ""
            _parse_decor(full_hash, decor)
            refs = ref_map.get(full_hash, {"local_refs": [], "remote_refs": [], "is_head": False})
            # A commit is "local only" when it has local branch refs but NO remote ref
            is_local_only = bool(refs["local_refs"]) and not refs["remote_refs"]
            raw_commits.append({
                "hash":        full_hash[:7],
                "full_hash":   full_hash,
                "message":     message,
                "when":        when,
                "author":      author,
                "is_head":     full_hash == head_hash,
                "local_refs":  refs["local_refs"],
                "remote_refs": refs["remote_refs"],
                "is_local_only": is_local_only,
            })

        # ── 4. Current branch + ahead/behind ─────────────────────────────────
        branch_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "-C", repo, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5
        )
        branch = branch_result.stdout.strip()

        ahead, behind = 0, 0
        try:
            ab_result = await asyncio.to_thread(
                subprocess.run,
                ["git", "-C", repo, "rev-list", "--left-right", "--count",
                 f"HEAD...origin/{branch}"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5
            )
            ab_parts = ab_result.stdout.strip().split()
            if len(ab_parts) == 2:
                ahead, behind = int(ab_parts[0]), int(ab_parts[1])
        except Exception:
            pass

        return {"branch": branch, "ahead": ahead, "behind": behind, "commits": raw_commits}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /git/diff ─────────────────────────────────────────────────────────────

@router.get("/git/diff")
async def git_diff(project_name: str, file: str, staged: bool = False):
    """Get unified diff for a file (staged or working tree)."""
    from skills.code_agent.projects import get_project
    from pathlib import Path
    proj = get_project(project_name)
    if not proj:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_name}")
    repo = proj["repo_path"]
    # Security: file must be inside repo
    try:
        full = (Path(repo) / file).resolve()
        Path(repo).resolve()
        full.relative_to(Path(repo).resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="File outside repo")
    try:
        cmd = ["git", "-C", repo, "diff"]
        if staged:
            cmd.append("--staged")
        cmd.append("--")
        cmd.append(file)
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15
        )
        return {"diff": result.stdout, "file": file}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /git/discard ─────────────────────────────────────────────────────────

@router.post("/git/discard", dependencies=[Depends(verify_csrf)])
async def git_discard(req: DiscardFileRequest):
    """Discard a file's changes, restoring it to its HEAD state.

    Re-checks the file's live git status right before acting (rather than
    trusting a possibly-stale status from the client) to pick the correct
    strategy:
      - untracked, or staged-add with no HEAD counterpart → remove the file
        (there is nothing to "restore" it to)
      - anything that already exists in HEAD → reset both the index and
        working tree back to the HEAD version
    """
    from skills.code_agent.projects import get_project
    proj = get_project(req.project_name)
    if not proj:
        raise HTTPException(status_code=404, detail=f"Project not found: {req.project_name}")
    repo = proj["repo_path"]
    try:
        _resolve_repo_path(repo, req.file)
    except ValueError:
        raise HTTPException(status_code=400, detail="File outside repo")

    try:
        st = await asyncio.to_thread(
            subprocess.run,
            ["git", "-C", repo, "status", "--porcelain=v1", "--", req.file],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
        )
        line = next((l for l in st.stdout.splitlines() if len(l) > 3), None)
        if not line:
            raise HTTPException(status_code=404, detail="No changes to discard for this file")
        x, y = line[0], line[1]

        if x == "?" or (x == "A" and y != "M"):
            # Untracked, or added-to-index-and-not-committed-anywhere — not in
            # HEAD at all, so there's nothing to restore to. Remove it.
            cmd = ["git", "-C", repo, "clean", "-fd", "--", req.file]
        elif x == "A" and y == "M":
            # Staged as new, then modified further in the working tree — still
            # doesn't exist in HEAD once unstaged, so unstage then remove.
            await asyncio.to_thread(
                subprocess.run,
                ["git", "-C", repo, "restore", "--staged", "--", req.file],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
            )
            cmd = ["git", "-C", repo, "clean", "-fd", "--", req.file]
        else:
            # Tracked file with staged and/or unstaged modifications — reset
            # both the index and working tree content back to HEAD.
            cmd = ["git", "-C", repo, "checkout", "HEAD", "--", req.file]

        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=result.stderr.strip() or "Could not discard changes")
        return {"discarded": req.file}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /files/tree ────────────────────────────────────────────────────────────

@router.get("/files/tree")
async def files_tree(project_name: str, path: str = ""):
    """List one directory level (files + subdirectories) for the file explorer.
    Lazily called per-folder as the user expands the tree, mirroring the
    Confluence page-tree pattern in third-pane.js."""
    from skills.code_agent.projects import get_project
    proj = get_project(project_name)
    if not proj:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_name}")
    repo = proj["repo_path"]
    try:
        target = _resolve_repo_path(repo, path)
    except ValueError:
        raise HTTPException(status_code=400, detail="Path outside repo")
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    def _scan():
        entries = []
        try:
            with os.scandir(target) as it:
                for entry in it:
                    if entry.name == ".git":
                        continue
                    rel = f"{path}/{entry.name}" if path else entry.name
                    entries.append({
                        "name": entry.name,
                        "path": rel,
                        "type": "dir" if entry.is_dir(follow_symlinks=False) else "file",
                    })
        except PermissionError:
            pass
        entries.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))
        return entries

    entries = await asyncio.to_thread(_scan)
    return {"entries": entries, "path": path}


# ── GET /file/content ──────────────────────────────────────────────────────────

@router.get("/file/content")
async def file_content(project_name: str, file: str):
    """Read-only file content for the file explorer (not a diff)."""
    from skills.code_agent.projects import get_project
    proj = get_project(project_name)
    if not proj:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_name}")
    repo = proj["repo_path"]
    try:
        full = _resolve_repo_path(repo, file)
    except ValueError:
        raise HTTPException(status_code=400, detail="File outside repo")
    if not full.exists() or not full.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    max_bytes = 500_000

    def _read():
        raw = full.read_bytes()
        if len(raw) > max_bytes or b"\x00" in raw[:8000]:
            return None, True
        return raw.decode("utf-8", errors="replace"), False

    try:
        content, binary = await asyncio.to_thread(_read)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    if binary:
        return {"binary": True, "file": file}
    return {"content": content, "file": file}
