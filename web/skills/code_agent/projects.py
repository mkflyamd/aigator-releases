"""Project storage and active-project management for the Coding Agent.

Projects are stored under ~/.gator/projects/<name>/.
Active project pointer lives in ~/.gator/config.json.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from proc_utils import no_window_kwargs

GATOR_HOME = Path.home() / ".gator"
PROJECTS_DIR = GATOR_HOME / "projects"
# Separate config file — NEVER share ~/.gator/config.json (that's Gator's main
# config with llm_profiles, personas, etc.). Co-mingling caused full-file
# overwrites that wiped the LLM config.
CONFIG_FILE = GATOR_HOME / "code_agent_projects.json"

# Project name: alphanumeric, dash, underscore, max 64 chars. No path separators.
_NAME_RE = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')


def _ensure_dirs() -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def _load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"active_project": None, "projects": {}}


def _save_config(cfg: dict) -> None:
    GATOR_HOME.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


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
    """Return list of project dicts for all saved projects."""
    cfg = _load_config()
    return [
        {"name": name, **meta}
        for name, meta in cfg.get("projects", {}).items()
    ]


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
    cfg = _load_config()
    cfg["active_project"] = name
    _save_config(cfg)


def add_project(name: str, repo_path: str, source: str = "local") -> dict:
    """Add a new project.

    source = "local": validates repo_path is an absolute, existing git repo.
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
            capture_output=True, text=True,
            **no_window_kwargs(),
        )
        if result.returncode != 0:
            raise ValueError("This folder is not a git project")
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
        if parsed.hostname not in allowed_hosts and not (parsed.hostname or "").endswith(".github.com"):
            raise ValueError(
                f"Only GitHub URLs are supported (got: {parsed.hostname!r}). "
                f"Use https://github.com/org/repo"
            )
        # Clone into ~/.gator/projects/<name>/
        clone_dir = PROJECTS_DIR / safe_name
        if clone_dir.exists():
            raise ValueError(f"Project '{safe_name}' already exists")
        # Run git clone via args list (not shell=True)
        result = subprocess.run(
            ["git", "clone", repo_path, str(clone_dir)],
            capture_output=True, text=True,
            **no_window_kwargs(),
        )
        if result.returncode != 0:
            raise ValueError(f"Could not clone repository: {result.stderr.splitlines()[-1] if result.stderr else 'unknown error'}")
        resolved_path = str(clone_dir)

    else:
        raise ValueError(f"Unknown source: {source!r}. Use 'local' or 'github'.")

    # Create project directory
    project_dir = PROJECTS_DIR / safe_name
    project_dir.mkdir(parents=True, exist_ok=True)

    # Save to config
    cfg = _load_config()
    project_meta = {"repo_path": resolved_path, "source": source}
    cfg.setdefault("projects", {})[safe_name] = project_meta
    # Set as active if first project
    if not cfg.get("active_project"):
        cfg["active_project"] = safe_name
    _save_config(cfg)

    return {"name": safe_name, **project_meta}


def project_dir(name: str) -> Path:
    """Return ~/.gator/projects/<name>/."""
    safe_name = _sanitize_name(name)
    return PROJECTS_DIR / safe_name
