# web/mcp/github_fetcher.py
"""Backwards-compatibility shim — functionality moved to url_fetcher.py."""
from mcp.url_fetcher import url_fetcher as github_fetcher, _fetch_github, _parse_github_url

__all__ = ["github_fetcher", "_fetch_github", "_parse_github_url"]
