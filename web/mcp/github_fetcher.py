# web/mcp/github_fetcher.py
"""Fetch a GitHub repo's README and extract MCP configs from JSON code fences."""
from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx

from mcp.normalizer import NormalizeResult, _try_json, GITHUB_API_BASE


def _parse_github_url(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url.strip())
    if parsed.hostname not in ("github.com", "www.github.com"):
        return None
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) >= 2:
        return parts[0], parts[1].removesuffix(".git")
    return None


def github_fetcher(url: str) -> NormalizeResult | None:
    """Fetch README for a public GitHub repo and extract MCP configs from code fences.

    Returns None on any network error so the normalizer pipeline can fall through.
    """
    parsed = _parse_github_url(url)
    if not parsed:
        return None
    owner, repo = parsed

    try:
        meta = httpx.get(f"{GITHUB_API_BASE}/repos/{owner}/{repo}", timeout=10).json()
        branch = meta.get("default_branch", "main")
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/README.md"
        readme = httpx.get(raw_url, timeout=10).text
    except Exception:
        return None

    # Extract all fenced code blocks (```json or plain ```)
    fences = re.findall(r"```(?:json)?\s*\n(.*?)\n```", readme, re.DOTALL)
    results: list[NormalizeResult] = []
    for fence in fences:
        r = _try_json(fence.strip())
        results.extend(r)

    if not results:
        return None

    for r in results:
        r.source = "github_readme"

    if len(results) == 1:
        return results[0]

    first = results[0]
    all_results_copy = list(results)   # copy before mutating first
    first.confidence = "medium"
    first.all_results = all_results_copy
    return first
