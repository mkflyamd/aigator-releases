"""Fetch and merge skill catalogs from configured registry sources."""

import json
import logging
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Catalog cache file ────────────────────────────────────────────────────────
# Written by the background sync job at startup and every 6 hours.
# The API endpoint always reads from this file — no live GitHub dependency.
try:
    _CATALOG_CACHE_FILE  # noqa: F821
except NameError:
    from config import CATALOG_CACHE as _CATALOG_CACHE_FILE
_CATALOG_REFRESH_HOURS = 6

_ANTHROPIC_API_URL = (
    "https://api.github.com/repos/anthropics/skills/contents/skills"
)
_ANTHROPIC_RAW_BASE = (
    "https://raw.githubusercontent.com/anthropics/skills/main/skills"
)


def normalize_entry(entry: dict) -> dict:
    """Fill in default fields so the UI always has what it needs."""
    result = {**entry}
    result.setdefault("id", "")
    result.setdefault("name", result.get("id", ""))
    result.setdefault("description", "")
    result.setdefault("version", "")
    result.setdefault("tier", "Community")
    result.setdefault("install_url", "")
    result.setdefault("install_count", 0)
    result.setdefault("category", "")
    result.setdefault("license", "")
    result.setdefault("has_tools", False)
    result.setdefault("source", "")
    return result


def merge_catalogs(sources: list[list[dict]]) -> list[dict]:
    """Merge multiple catalog lists; first source wins on duplicate id."""
    seen: dict[str, dict] = {}
    for source in sources:
        for entry in source:
            eid = entry.get("id", "")
            if eid and eid not in seen:
                seen[eid] = normalize_entry(entry)
    return list(seen.values())


def _fetch_json_url(url: str) -> list[dict]:
    """Fetch a JSON array from a URL. Returns [] on any error."""
    if not url:
        return []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AIGator/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read(4 * 1024 * 1024))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "skills" in data:
            return data["skills"]
        return []
    except Exception as exc:
        logger.warning("Registry fetch failed for %s: %s", url, exc)
        return []


def fetch_verified_json(url: str) -> list[dict]:
    return [dict(e, tier="Verified", source="verified") for e in _fetch_json_url(url)]


def _parse_skill_md_frontmatter(text: str) -> dict:
    """Extract key: value pairs from YAML frontmatter block (--- ... ---)."""
    result = {}
    if not text.startswith("---"):
        return result
    end = text.find("---", 3)
    if end == -1:
        return result
    for line in text[3:end].splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            result[key.strip()] = val.strip().strip('"')
    return result


def _fetch_skill_md(skill_id: str) -> dict | None:
    """Fetch and parse a single SKILL.md. Returns None on failure."""
    raw_url = f"{_ANTHROPIC_RAW_BASE}/{skill_id}/SKILL.md"
    try:
        md_req = urllib.request.Request(raw_url, headers={"User-Agent": "AIGator/1.0"})
        with urllib.request.urlopen(md_req, timeout=8) as md_resp:
            md_text = md_resp.read(256 * 1024).decode("utf-8", errors="replace")
        fm = _parse_skill_md_frontmatter(md_text)
        return {
            "id": skill_id,
            "name": fm.get("name", skill_id),
            "description": fm.get("description", ""),
            "version": fm.get("version", "1.0"),
            "tier": "Community",
            "source": "anthropic",
            "install_url": f"{_ANTHROPIC_RAW_BASE}/{skill_id}/SKILL.md",
            "has_tools": False,
            "install_count": 0,
            "category": "",
            "license": fm.get("license", ""),
        }
    except Exception as exc:
        logger.debug("Skipping anthropic skill %s: %s", skill_id, exc)
        return None


def fetch_anthropic_skills() -> list[dict]:
    """Fetch skill list from github.com/anthropics/skills.

    1 request to list directories, then all SKILL.md files fetched in parallel.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    try:
        req = urllib.request.Request(
            _ANTHROPIC_API_URL,
            headers={"User-Agent": "AIGator/1.0", "Accept": "application/vnd.github.v3+json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            entries = json.loads(resp.read(4 * 1024 * 1024))
        if not isinstance(entries, list):
            return []
        skill_ids = [item["name"] for item in entries if item.get("type") == "dir"]
        skills = []
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {pool.submit(_fetch_skill_md, sid): sid for sid in skill_ids}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    skills.append(result)
        return skills
    except Exception as exc:
        logger.warning("Anthropic skills fetch failed: %s", exc)
        return []


def fetch_clawhub(url: str) -> list[dict]:
    if not url:
        return []
    api_url = url.rstrip("/") + "/skills"
    return [
        dict(e, tier=e.get("tier", "Community"), source="clawhub")
        for e in _fetch_json_url(api_url)
    ]


def fetch_enterprise(url: str) -> list[dict]:
    if not url:
        return []
    if url.startswith(("http://", "https://")):
        raw = _fetch_json_url(url)
    else:
        try:
            import pathlib
            # Resolve to absolute path to prevent path traversal.
            # Only files under the user's home directory are permitted.
            resolved = pathlib.Path(url).resolve()
            allowed_root = pathlib.Path.home().resolve()
            if not str(resolved).startswith(str(allowed_root)):
                logger.warning("Enterprise registry path outside allowed root: %s", resolved)
                return []
            raw = json.loads(resolved.read_text(encoding="utf-8")) if resolved.exists() else []
        except Exception as exc:
            logger.warning("Enterprise registry read failed: %s", exc)
            return []
    # Normalise: accept list or {"skills": [...]} envelope
    if isinstance(raw, list):
        entries = raw
    elif isinstance(raw, dict) and "skills" in raw:
        entries = raw["skills"]
    else:
        entries = []
    return [dict(e, source="enterprise") for e in entries if isinstance(e, dict)]


def fetch_catalog(cfg: dict) -> list[dict]:
    """Return catalog from local cache file. Never fetches GitHub at request time."""
    if _CATALOG_CACHE_FILE.exists():
        try:
            data = json.loads(_CATALOG_CACHE_FILE.read_text(encoding="utf-8"))
            return data.get("skills", [])
        except Exception as exc:
            logger.warning("Could not read catalog cache: %s", exc)
    return []


def refresh_catalog(cfg: dict) -> None:
    """Fetch fresh catalog from all sources and write to local cache file.

    Called at startup and every _CATALOG_REFRESH_HOURS hours by a background job.
    Never called during a user request.
    """
    sources = []
    if cfg.get("marketplace_verified_url"):
        sources.append(fetch_verified_json(cfg["marketplace_verified_url"]))
    if cfg.get("marketplace_clawhub_url"):
        sources.append(fetch_clawhub(cfg["marketplace_clawhub_url"]))
    if cfg.get("marketplace_anthropic_enabled", True):
        sources.append(fetch_anthropic_skills())
    if cfg.get("marketplace_enterprise_url"):
        sources.append(fetch_enterprise(cfg["marketplace_enterprise_url"]))
    skills = merge_catalogs(sources)
    if not skills:
        logger.warning("Catalog refresh returned 0 skills — keeping existing cache")
        return
    _CATALOG_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CATALOG_CACHE_FILE.write_text(
        json.dumps({"skills": skills, "count": len(skills)}, indent=2),
        encoding="utf-8",
    )
    logger.info("Catalog cache refreshed: %d skills written to %s", len(skills), _CATALOG_CACHE_FILE)
