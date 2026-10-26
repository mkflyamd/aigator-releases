"""The saved GitHub token and host, read in-process.

Never exported as GITHUB_TOKEN: that variable is inherited by every child (terminals, MCP
servers) and outranks the user's own `gh auth login`. An env var the user set themselves is
only a fallback.
"""
import os


def _saved() -> dict:
    try:
        from config import load_config
        return load_config()
    except Exception:
        return {}


def get_token() -> str:
    return _saved().get("github_token") or os.environ.get("GITHUB_TOKEN", "")


def get_base_url() -> str:
    return (_saved().get("github_base_url") or os.environ.get("GITHUB_BASE_URL", "")).rstrip("/")


def is_enterprise() -> bool:
    base = get_base_url()
    return bool(base) and "github.com" not in base
