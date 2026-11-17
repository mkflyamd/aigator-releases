"""Project storage and active-project management for the Coding Agent.

Projects are stored under ~/.gator/projects/<name>/.
Active project pointer lives in ~/.gator/config.json.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from proc_utils import no_window_kwargs

GATOR_HOME = Path.home() / ".gator"
PROJECTS_DIR = GATOR_HOME / "projects"
# Separate config file — NEVER share ~/.gator/config.json (that's Gator's main
# config with llm_profiles, personas, etc.). Co-mingling caused full-file
# overwrites that wiped the LLM config.
CONFIG_FILE = GATOR_HOME / "code_agent_projects.json"

# Project name: alphanumeric, dash, underscore, max 64 chars. No path separators.
_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class NotGitRepoError(ValueError):
    """Raised when a local folder isn't a git repo and init_git wasn't requested.

    Kept distinct from plain ValueError so the route can surface a code the
    frontend recognizes and offers to fix (git init + retry), instead of just
    a dead-end alert.
    """


def _ensure_dirs() -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


# One lock for every read and read-modify-write: route handlers run on worker
# threads and the event loop at once, and Windows refuses os.replace while a
# reader has the file open.
_CONFIG_LOCK = threading.RLock()


def _load_config() -> dict:
    with _CONFIG_LOCK:
        if CONFIG_FILE.exists():
            try:
                return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"active_project": None, "projects": {}}


def _save_config(cfg: dict) -> None:
    with _CONFIG_LOCK:
        GATOR_HOME.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=GATOR_HOME, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            os.replace(tmp, CONFIG_FILE)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


@contextmanager
def _config_txn():
    """Load the config, let the caller change it, and save it, all under the lock."""
    with _CONFIG_LOCK:
        cfg = _load_config()
        yield cfg
        _save_config(cfg)


def _sanitize_name(name: str) -> str:
    """Return a safe project name or raise ValueError.

    Rejects names that contain path separators or other invalid characters.
    Does NOT silently rename — if the input contains /\\ it is rejected outright.
    """
    if "/" in name or "\\" in name:
        raise ValueError(
            f"Invalid project name {name!r}. Project names must not contain path separators."
        )
    if not _NAME_RE.match(name):
        raise ValueError(
            f"Invalid project name {name!r}. Use letters, numbers, dash, underscore only (max 64 chars)."
        )
    return name


# ── Public API ────────────────────────────────────────────────────────────────


def list_projects() -> list[dict]:
    """Return saved projects, most recently opened first; never-opened ones keep saved order."""
    cfg = _load_config()
    items = [{"name": name, **meta} for name, meta in cfg.get("projects", {}).items()]
    return sorted(items, key=lambda p: p.get("last_opened", 0), reverse=True)


def get_project(name: str) -> dict | None:
    """Return project dict or None if not found."""
    cfg = _load_config()
    meta = cfg.get("projects", {}).get(name)
    if meta is None:
        return None
    return {"name": name, **meta}


def get_active_project() -> str | None:
    """Return active project name or None."""
    return _load_config().get("active_project")


def set_active_project(name: str) -> None:
    """Set active project in config.json. Persists across server restarts."""
    with _config_txn() as cfg:
        cfg["active_project"] = name
        meta = cfg.get("projects", {}).get(name)
        if meta is not None:
            meta["last_opened"] = time.time()


def remove_project(name: str) -> None:
    """Forget a project. Never deletes the project's folder or a clone with content;
    only Gator's own empty metadata folder is removed."""
    safe_name = _sanitize_name(name)
    with _config_txn() as cfg:
        projects = cfg.get("projects", {})
        if safe_name not in projects:
            raise ValueError(f"Project not found: {safe_name}")
        del projects[safe_name]
        if cfg.get("active_project") == safe_name:
            remaining = sorted(
                projects, key=lambda n: projects[n].get("last_opened", 0), reverse=True
            )
            cfg["active_project"] = remaining[0] if remaining else None
    try:
        (PROJECTS_DIR / safe_name).rmdir()
    except OSError:
        pass


def set_project_agent(name: str, agent: str) -> None:
    """Set which coding agent a project uses ("opencode" is the default and
    always implicit for any project without this key - existing projects are
    completely unaffected by this field's existence). See web/generic_agent.py
    for the other supported values."""
    with _config_txn() as cfg:
        projects = cfg.setdefault("projects", {})
        if name not in projects:
            raise ValueError(f"Project not found: {name}")
        projects[name]["agent"] = agent


def get_active_pty_session() -> str | None:
    """Return the pty_session_id most recently activated in any browser tab.

    Used by the Teams remote-control relay (see teams_remote_control.py) to
    pick a target for injected input when no browser tab is open to ask.
    """
    return _load_config().get("active_pty_session")


def set_active_pty_session(pty_session_id: str) -> None:
    """Record the most recently activated pty_session_id. Best-effort, fire-
    and-forget from the frontend on every session activation - stale values
    are harmless (write_pty_session just fails closed on a dead/unknown id)."""
    with _config_txn() as cfg:
        cfg["active_pty_session"] = pty_session_id


def _is_clone_of(clone_dir: Path, url: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(clone_dir), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        **no_window_kwargs(),
    )
    return result.returncode == 0 and result.stdout.strip() == url


def add_project(
    name: str, repo_path: str, source: str = "local", init_git: bool = False
) -> dict:
    """Add a new project.

    source = "local": validates repo_path is an absolute, existing git repo.
        If it isn't a git repo yet: raises NotGitRepoError unless init_git=True,
        in which case a plain `git init` is run in-place and the folder is
        added as a fresh repo.
    source = "github": validates repo_path is a github URL, clones into ~/.gator/projects/<name>/.

    Returns the project dict.
    Raises ValueError for invalid inputs.
    """
    safe_name = _sanitize_name(name)
    _ensure_dirs()

    if source == "local":
        # Check is_absolute BEFORE resolve() — on Windows, resolve() makes relative paths absolute
        raw = Path(repo_path)
        if not raw.is_absolute():
            raise ValueError("repo_path must be an absolute path")
        p = raw.resolve()
        if not p.exists():
            raise ValueError(f"Folder not found: {repo_path}")
        if not p.is_dir():
            raise ValueError(f"Not a directory: {repo_path}")
        # Validate it is a git repo
        result = subprocess.run(
            ["git", "-C", str(p), "status", "--porcelain"],
            capture_output=True,
            text=True,
            **no_window_kwargs(),
        )
        if result.returncode != 0:
            if not init_git:
                raise NotGitRepoError("This folder is not a git project yet.")
            init_result = subprocess.run(
                ["git", "init"],
                cwd=str(p),
                capture_output=True,
                text=True,
                **no_window_kwargs(),
            )
            if init_result.returncode != 0:
                raise ValueError(
                    f"Could not initialize git: {init_result.stderr.strip()}"
                )
        resolved_path = str(p)

    elif source == "github":
        import urllib.parse

        parsed = urllib.parse.urlparse(repo_path)
        if parsed.scheme not in ("https", "http"):
            raise ValueError("GitHub URL must start with https://")
        # Reject ext:: protocol (git RCE vector) and option-like arguments
        if repo_path.startswith("ext::") or repo_path.startswith("--"):
            raise ValueError("Invalid GitHub URL")
        # Reject shell metacharacters and git protocol injection characters
        _BLOCKED = [";", "&", "|", "`", "$", "(", ")", "\n", "\r", "ext::", "::", "\\"]
        if any(c in repo_path for c in _BLOCKED):
            raise ValueError("Invalid characters in GitHub URL")
        # Restrict to known-safe GitHub domains
        allowed_hosts = {"github.com", "github.enterprise.com"}
        if parsed.hostname not in allowed_hosts and not (
            parsed.hostname or ""
        ).endswith(".github.com"):
            raise ValueError(
                f"Only GitHub URLs are supported (got: {parsed.hostname!r}). "
                f"Use https://github.com/org/repo"
            )
        # Clone into ~/.gator/projects/<name>/
        clone_dir = PROJECTS_DIR / safe_name
        if safe_name in _load_config().get("projects", {}):
            raise ValueError(f"Project '{safe_name}' already exists")
        if clone_dir.exists():
            # A clone kept when the project was removed is reused, never re-cloned.
            if not _is_clone_of(clone_dir, repo_path):
                raise ValueError(
                    f"'{clone_dir}' exists and is not a clone of this repository"
                )
        else:
            # Run git clone via args list (not shell=True)
            result = subprocess.run(
                ["git", "clone", repo_path, str(clone_dir)],
                capture_output=True,
                text=True,
                **no_window_kwargs(),
            )
            if result.returncode != 0:
                raise ValueError(
                    f"Could not clone repository: {result.stderr.splitlines()[-1] if result.stderr else 'unknown error'}"
                )
        resolved_path = str(clone_dir)

    else:
        raise ValueError(f"Unknown source: {source!r}. Use 'local' or 'github'.")

    # Create project directory
    project_dir = PROJECTS_DIR / safe_name
    project_dir.mkdir(parents=True, exist_ok=True)

    # Save to config
    project_meta = {"repo_path": resolved_path, "source": source}
    with _config_txn() as cfg:
        cfg.setdefault("projects", {})[safe_name] = project_meta
        # Set as active if first project
        if not cfg.get("active_project"):
            cfg["active_project"] = safe_name

    return {"name": safe_name, **project_meta}


def project_dir(name: str) -> Path:
    """Return ~/.gator/projects/<name>/."""
    safe_name = _sanitize_name(name)
    return PROJECTS_DIR / safe_name
