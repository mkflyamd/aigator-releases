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

_ANTHROPIC_API_URL = "https://api.github.com/repos/anthropics/skills/contents/skills"
_ANTHROPIC_RAW_BASE = "https://raw.githubusercontent.com/anthropics/skills/main/skills"

# Cache for the anthropics/skills directory listing. The api.github.com call to
# list skill directories is unauthenticated (60 req/hour limit) and runs at every
# catalog refresh + every server restart, so it easily 403s. The directory list
# changes rarely, so cache it for 24h: within the window we skip the API call
# and fetch SKILL.md files for the cached IDs (those go to raw.githubusercontent.com,
# a different host with no per-hour limit). On a 403 we fall back to the stale
# cache rather than failing the whole refresh.
try:
    _ANTHROPIC_DIR_CACHE_FILE  # noqa: F821
except NameError:
    from config import GATOR_DIR as _GATOR_DIR

    _ANTHROPIC_DIR_CACHE_FILE = _GATOR_DIR / "anthropic_skills_dir_cache.json"
_ANTHROPIC_DIR_CACHE_TTL = 24 * 3600  # seconds

_CLAUDE_PLUGINS_OFFICIAL_URL = (
    "https://raw.githubusercontent.com/anthropics/claude-plugins-official/"
    "main/.claude-plugin/marketplace.json"
)

# Advisory-only heuristic (decision #8, 2026-08-07 milestone) for repo-acting
# coding plugins. False positives are acceptable — the UI shows an advisory
# banner, not a block. Deliberately does NOT key off category=="development":
# that signal is too broad and would wrongly bounce amd-skills (category is
# "development" but it belongs in chat, not the Coding Agent).
_CODING_SOFT_KEYWORDS = (
    "code-review",
    "pr-review",
    "code-modernization",
    "refactor",
    "lint",
    "codegen",
    "feature-dev",
    "commit",
    "debugger",
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


def classify_coding(entry: dict) -> str:
    """Classify a marketplace entry as 'coding_hard', 'coding_soft', or 'none'.

    'coding_hard' — LSP plugins (name ends with '-lsp', or the entry declares
    lspServers/lsp_servers). These can't run in a chat surface at all, so the
    caller must set installable=False and point the user at the Coding Agent.

    'coding_soft' — repo-acting coding plugins (code review, refactor, commit
    helpers, ...). These stay installable; the UI shows an advisory banner.

    'none' — everything else, installs normally.

    This is advisory only, never category-blocking — see module docstring
    on _CODING_SOFT_KEYWORDS for why category=="development" is not used.
    """
    name = str(entry.get("name") or entry.get("id") or "").lower()
    description = str(entry.get("description") or "").lower()
    if name.endswith("-lsp") or entry.get("lspServers") or entry.get("lsp_servers"):
        return "coding_hard"
    haystack = f"{name} {description}"
    if any(keyword in haystack for keyword in _CODING_SOFT_KEYWORDS):
        return "coding_soft"
    return "none"


def _normalize_plugin_source(raw_source) -> dict:
    """Normalize a claude-plugins-official 'source' field to one consistent shape.

    Most entries (227/280 as measured 2026-08-07) use the git-subdir dict form
    ({"source": "git-subdir", "url", "path", "ref", "sha"}) pointing at an
    external repo. The rest — mostly plugins that ship inside the
    claude-plugins-official repo itself (e.g. the LSP plugins) — use a bare
    relative-path string instead (e.g. "./plugins/clangd-lsp"). Normalizing
    both to the same shape means installers only ever handle one form.

    A third shape (e.g. fullstory, jfrog) has no "url" at all:
    {"source": "github", "repo": "owner/name", "commit": ..., "sha": ...}.
    That shape is detected by source=="github" or the presence of "repo"
    without "url", and a url is synthesized from repo so it's just as
    installable as the git-subdir form. "commit" is treated as a ref when
    "sha" isn't present (a full commit sha and a "ref" are both valid inputs
    to download_skill_tarball's `branch` parameter).
    """
    if isinstance(raw_source, dict):
        if raw_source.get("source") == "github" or (
            raw_source.get("repo") and not raw_source.get("url")
        ):
            repo = raw_source.get("repo", "")
            return {
                "kind": "github",
                "url": f"https://github.com/{repo}.git" if repo else "",
                "path": raw_source.get("path", ""),
                "ref": raw_source.get("ref", ""),
                "sha": raw_source.get("sha") or raw_source.get("commit", ""),
            }
        return {
            "kind": raw_source.get("source", "git-subdir"),
            "url": raw_source.get("url", ""),
            "path": raw_source.get("path", ""),
            "ref": raw_source.get("ref", ""),
            "sha": raw_source.get("sha", ""),
        }
    if isinstance(raw_source, str):
        path = raw_source[2:] if raw_source.startswith("./") else raw_source
        return {
            "kind": "local",
            "url": "https://github.com/anthropics/claude-plugins-official.git",
            "path": path,
            "ref": "main",
            "sha": "",
        }
    return {"kind": "unknown", "url": "", "path": "", "ref": "", "sha": ""}


def _normalize_claude_plugins_official_entry(raw: dict) -> dict:
    """Build a normalize_entry()-shaped catalog entry from a raw
    claude-plugins-official marketplace.json plugin object, plus the extra
    fields this milestone needs (tier, source, installable, coding_class,
    plugin_source). Raises if raw has no usable name — caller skips those."""
    coding_class = classify_coding(raw)
    plugin_source = _normalize_plugin_source(raw.get("source"))
    entry = normalize_entry(
        {
            "id": raw["name"],
            "name": raw.get("name"),
            "description": raw.get("description", ""),
            "version": raw.get("version", ""),
            "category": raw.get("category", ""),
            "license": raw.get("license", ""),
        }
    )
    entry["tier"] = "Verified"
    entry["source"] = "claude-plugins-official"
    entry["install_url"] = plugin_source.get("url", "")
    entry["installable"] = coding_class != "coding_hard"
    entry["coding_class"] = coding_class
    entry["plugin_source"] = plugin_source
    return entry


def fetch_claude_plugins_official() -> list[dict]:
    """Fetch Anthropic's curated claude-plugins-official marketplace (Verified
    tier, decision #2 of the 2026-08-07 milestone).

    Single GET of marketplace.json. Fails soft on any network/parse error —
    logs a warning and returns [] so refresh_catalog's other sources are
    unaffected (mirrors fetch_anthropic_skills below). Malformed individual
    entries (missing name) are skipped so one bad entry doesn't drop the
    whole catalog.
    """
    try:
        req = urllib.request.Request(
            _CLAUDE_PLUGINS_OFFICIAL_URL, headers={"User-Agent": "AIGator/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read(8 * 1024 * 1024))
    except Exception as exc:
        logger.warning("claude-plugins-official fetch failed: %s", exc)
        return []

    if not isinstance(data, dict):
        logger.warning("claude-plugins-official marketplace.json is not a JSON object")
        return []
    raw_plugins = data.get("plugins", [])
    if not isinstance(raw_plugins, list):
        return []

    entries = []
    for raw in raw_plugins:
        if not isinstance(raw, dict) or not raw.get("name"):
            logger.debug("Skipping malformed claude-plugins-official entry: %r", raw)
            continue
        try:
            entries.append(_normalize_claude_plugins_official_entry(raw))
        except Exception as exc:
            logger.debug(
                "Skipping claude-plugins-official entry %s: %s", raw.get("name"), exc
            )
            continue
    return entries


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


def _load_anthropic_dir_cache() -> list[str] | None:
    """Return cached skill IDs if the cache is fresh, else None."""
    import time

    try:
        if not _ANTHROPIC_DIR_CACHE_FILE.exists():
            return None
        data = json.loads(_ANTHROPIC_DIR_CACHE_FILE.read_text(encoding="utf-8"))
        if time.time() - data.get("fetched_at", 0) > _ANTHROPIC_DIR_CACHE_TTL:
            return None
        ids = data.get("skill_ids", [])
        return ids if isinstance(ids, list) else None
    except Exception:
        return None


def _save_anthropic_dir_cache(skill_ids: list[str]) -> None:
    """Persist the directory listing (best-effort)."""
    import time

    try:
        _ANTHROPIC_DIR_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _ANTHROPIC_DIR_CACHE_FILE.write_text(
            json.dumps({"fetched_at": time.time(), "skill_ids": skill_ids}),
            encoding="utf-8",
        )
    except Exception:
        pass


def _fetch_anthropic_skill_ids() -> tuple[list[str], bool]:
    """Fetch the list of skill directory names from api.github.com.

    Returns (skill_ids, from_cache). Uses the 24h directory-listing cache to
    avoid the unauthenticated GitHub API rate limit (60 req/hour). On a fetch
    failure, falls back to a stale cache rather than returning empty so the
    catalog refresh degrades gracefully instead of dropping Anthropic skills.
    """
    # Fresh cache — skip the API call entirely.
    cached = _load_anthropic_dir_cache()
    if cached is not None:
        return cached, True

    # Try the live API call.
    try:
        req = urllib.request.Request(
            _ANTHROPIC_API_URL,
            headers={
                "User-Agent": "AIGator/1.0",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            entries = json.loads(resp.read(4 * 1024 * 1024))
        if not isinstance(entries, list):
            return [], False
        skill_ids = [item["name"] for item in entries if item.get("type") == "dir"]
        _save_anthropic_dir_cache(skill_ids)
        return skill_ids, False
    except Exception as exc:
        logger.warning("Anthropic skills dir listing failed: %s", exc)
        # Fall back to a stale cache if one exists (better than dropping the
        # whole Anthropic source on a transient 403).
        try:
            if _ANTHROPIC_DIR_CACHE_FILE.exists():
                data = json.loads(_ANTHROPIC_DIR_CACHE_FILE.read_text(encoding="utf-8"))
                stale = data.get("skill_ids", [])
                if isinstance(stale, list) and stale:
                    logger.info(
                        "Anthropic skills: using stale dir cache (%d ids) after fetch failure",
                        len(stale),
                    )
                    return stale, True
        except Exception:
            pass
        return [], False


def fetch_anthropic_skills() -> list[dict]:
    """Fetch skill list from github.com/anthropics/skills.

    1 request to list directories (cached 24h), then all SKILL.md files fetched
    in parallel from raw.githubusercontent.com (no per-hour rate limit).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    skill_ids, from_cache = _fetch_anthropic_skill_ids()
    if not skill_ids:
        return []
    if from_cache:
        logger.info(
            "Anthropic skills: using cached dir listing (%d ids)", len(skill_ids)
        )
    skills = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_fetch_skill_md, sid): sid for sid in skill_ids}
        for future in as_completed(futures):
            result = future.result()
            if result:
                skills.append(result)
    return skills


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
                logger.warning(
                    "Enterprise registry path outside allowed root: %s", resolved
                )
                return []
            raw = (
                json.loads(resolved.read_text(encoding="utf-8"))
                if resolved.exists()
                else []
            )
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
    # claude-plugins-official (Verified tier) is fetched BEFORE
    # fetch_anthropic_skills() (Community tier) below: merge_catalogs keeps
    # the FIRST source's entry on a colliding id, so ordering here is what
    # makes the Verified plugin win over a same-id Community skill (e.g.
    # "frontend-design", "skill-creator" exist in both sources).
    # Defaults to True as of the 2026-08-07 milestone's final increment (4b):
    # the full path is now built and adversarially reviewed end to end —
    # install routing (Increment 2), consent gate + coding-redirect UI
    # (Increment 2/4a), plugin-bundled MCP servers (Increment 3), and
    # secret-collection UI + command discovery (Increment 4b). Kept False
    # through every increment up to this one specifically so these ~280
    # entries never surfaced before the install path could handle them
    # correctly — see docs/pluginArchitecture.md's Implementation log for
    # the full history (including why this was False for a while).
    if cfg.get("marketplace_claude_plugins_official_enabled", True):
        try:
            sources.append(fetch_claude_plugins_official())
        except Exception as exc:
            # fetch_claude_plugins_official() already fails soft internally;
            # this belt-and-suspenders guard ensures a bug there still can't
            # take down catalog refresh for every other source.
            logger.warning("claude-plugins-official source failed: %s", exc)
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
    logger.info(
        "Catalog cache refreshed: %d skills written to %s",
        len(skills),
        _CATALOG_CACHE_FILE,
    )
