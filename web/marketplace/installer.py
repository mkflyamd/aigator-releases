"""Install, uninstall, and create SKILL.md-only marketplace skills."""

import io
import json
import logging
import os
import re
import shutil
import threading
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# INSTALLED_SKILLS_DIR is imported from config unless already set (e.g., by
# a test monkeypatch before importlib.reload). This pattern lets tests inject
# a tmp_path by setting the module attribute before reloading.
try:
    INSTALLED_SKILLS_DIR  # noqa: F821 — may be set by monkeypatch before reload
except NameError:
    from config import INSTALLED_SKILLS_DIR

try:
    PLUGINS_DIR  # noqa: F821 — may be set by monkeypatch before reload
except NameError:
    from config import PLUGINS_DIR

from marketplace import github_fetcher
from marketplace.registry import _parse_skill_md_frontmatter

logger = logging.getLogger(__name__)


# Note: installed-skills.json path is computed inside each function (not at module level)
# so that tests can monkeypatch INSTALLED_SKILLS_DIR and have it take effect immediately.

# Guards concurrent read-modify-write of installed-skills.json within this process.
# Cross-process safety would require a file lock; in-process parallel installs
# (e.g., during marketplace bulk-install) are the realistic concurrency case.
_INSTALL_INDEX_LOCK = threading.Lock()


def _safe_skill_dir(base: Path, *parts: str) -> Path:
    """Resolve path and assert it stays under base. Raises ValueError if not."""
    candidate = (base / Path(*parts)).resolve()
    if not str(candidate).startswith(str(base.resolve())):
        raise ValueError(f"Skill ID escapes skills directory: {parts}")
    return candidate


def _write_files_atomically(dest_dir: Path, files: dict[str, bytes]) -> None:
    """Write `files` (relative-path -> bytes, as returned by
    github_fetcher.download_skill_tarball) into dest_dir.

    Shared by both codeload-tarball install paths (_install_github_folder and
    install_claude_plugins_official_plugin) so the zip-slip guard and atomic
    per-file write (.part + os.replace) live in exactly one place instead of
    two copies drifting apart (finding #7, 2026-08-07 milestone review).

    Raises ValueError on any absolute-path or path-traversal entry. Callers
    are responsible for creating dest_dir first and for cleanup-on-failure
    (rmtree if they created the dir themselves) — that policy differs
    slightly between callers, so it stays with them rather than here.
    """
    dest_resolved = dest_dir.resolve()
    for rel, data in files.items():
        if rel.startswith(("/", "\\")) or (len(rel) > 1 and rel[1] == ":"):
            raise ValueError(f"absolute path not allowed: {rel}")
        target = (dest_dir / rel).resolve()
        if not target.is_relative_to(dest_resolved):
            raise ValueError(f"path traversal not allowed: {rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_suffix(target.suffix + ".part")
        part.write_bytes(data)
        os.replace(part, target)


def load_installed() -> list[dict]:
    """Return list of installed skill entries from installed-skills.json."""
    installed_json = INSTALLED_SKILLS_DIR / "installed-skills.json"
    if not installed_json.exists():
        return []
    try:
        return json.loads(installed_json.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("installed-skills.json is corrupt or unreadable; returning empty list")
        return []


def save_installed(entries: list[dict]) -> None:
    """Persist installed skill list to disk atomically (write tmp + os.replace)."""
    INSTALLED_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    installed_json = INSTALLED_SKILLS_DIR / "installed-skills.json"
    tmp = installed_json.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    os.replace(tmp, installed_json)


def install_skill_md(
    skill_id: str,
    skill_md: str,
    version: str,
    tier: str,
    install_url: str = "",
) -> dict:
    """Install a skill from inline SKILL.md or a URL. If install_url is given and
    skill_md is empty, downloads from the URL: a ZIP is extracted in full (SKILL.md,
    tools.py, scripts/, reference docs) subject to size caps and path-traversal
    guards; a plain SKILL.md URL is written as the single file."""
    try:
        skill_dir = _safe_skill_dir(INSTALLED_SKILLS_DIR, skill_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    _zip_already_written = False
    if install_url and not skill_md:
        if not install_url.startswith(("https://", "http://")):
            return {"ok": False, "error": "install_url must be an http:// or https:// URL"}
        # Track whether the skill directory existed before this install so that
        # cleanup on failure only removes directories we created (mirrors the
        # pattern used by _install_github_folder).
        created_now = not skill_dir.exists()
        try:
            req = urllib.request.Request(install_url, headers={"User-Agent": "AIGator/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read(20 * 1024 * 1024)  # 20 MB limit
            # Detect format from content: ZIP magic bytes are PK\x03\x04
            if data[:4] == b"PK\x03\x04":
                # ZIP — extract whole folder (SKILL.md + tools.py + scripts/ + reference docs).
                from marketplace.github_fetcher import MAX_FILES, MAX_TOTAL_BYTES
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    names = [n for n in zf.namelist() if n.endswith("SKILL.md")]
                    if not names:
                        return {"ok": False, "error": "No SKILL.md found in package"}
                    # Reject any ZIP entry with traversal/absolute paths BEFORE
                    # picking a root — a malicious archive shouldn't be trusted
                    # just because the bad entry is outside our chosen subtree.
                    all_files = [n for n in zf.namelist() if not n.endswith("/")]
                    for n in all_files:
                        if (n.startswith(("/", "\\"))
                                or (len(n) > 1 and n[1] == ":")
                                or ".." in n.replace("\\", "/").split("/")):
                            return {"ok": False,
                                    "error": f"path traversal not allowed: {n}"}
                    # Pick the shallowest SKILL.md as the skill root.
                    skill_md_name = min(names, key=lambda n: n.count("/"))
                    root_prefix = skill_md_name[: -len("SKILL.md")]
                    members = [n for n in all_files if n.startswith(root_prefix)]
                    if len(members) > MAX_FILES:
                        return {"ok": False,
                                "error": f"Skill has too many files (> {MAX_FILES})"}
                    total = sum(zf.getinfo(n).file_size for n in members)
                    if total > MAX_TOTAL_BYTES:
                        return {"ok": False,
                                "error": f"Skill too large (> {MAX_TOTAL_BYTES // (1024 * 1024)} MB)"}
                    skill_dir.mkdir(parents=True, exist_ok=True)
                    dest_resolved = skill_dir.resolve()
                    for name in members:
                        rel = name[len(root_prefix):]
                        target = (skill_dir / rel).resolve()
                        # Defense in depth — resolve() should catch anything the
                        # textual check above missed (e.g., symlink-style entries).
                        if not target.is_relative_to(dest_resolved):
                            if created_now:
                                shutil.rmtree(skill_dir, ignore_errors=True)
                            return {"ok": False,
                                    "error": f"path traversal not allowed: {rel}"}
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(zf.read(name))
                    skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
                    _zip_already_written = True
            else:
                # Plain text SKILL.md (raw URL, no ZIP wrapper)
                skill_md = data.decode("utf-8")
        except Exception as exc:
            return {"ok": False, "error": f"Download failed: {exc}"}

    skill_dir.mkdir(parents=True, exist_ok=True)
    if not _zip_already_written:
        (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

    entries = [e for e in load_installed() if e.get("id") != skill_id]
    entries.append({
        "id": skill_id,
        "version": version,
        "tier": tier,
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "has_tools": (skill_dir / "tools.py").exists(),
    })
    save_installed(entries)
    return {"ok": True, "skill_id": skill_id}


def _install_github_folder(
    install_url: str,
    skill_id: str,
    version: str = "1.0",
    orphan_resolution: str | None = None,
) -> dict:
    """Install a skill from a GitHub tree/blob URL via codeload tarball.

    orphan_resolution: "keep" or "delete" — required when a pre-existing
    install has files absent from the new version. None on first install or
    when the new version is a superset of the old.

    Always installs at tier='Community' — URL imports are unverified by
    definition; runtime sandbox bears the trust burden."""
    try:
        skill_dir = _safe_skill_dir(INSTALLED_SKILLS_DIR, skill_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    try:
        parsed = github_fetcher.parse_github_url(install_url)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if parsed["kind"] == "raw_file":
        return {"ok": False, "error": "Use install_skill_md for raw SKILL.md URLs"}

    try:
        files = github_fetcher.download_skill_tarball(
            parsed["owner"], parsed["repo"], parsed["branch"], parsed["path"]
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.warning("Codeload download failed: %s", exc)
        return {"ok": False, "error": f"Download failed: {exc}"}

    if "SKILL.md" not in files:
        return {"ok": False, "error": "No SKILL.md found at this URL"}

    existing_files = list_existing_skill_files(skill_dir)
    orphans = sorted(set(existing_files) - set(files.keys()))
    if orphans and orphan_resolution is None:
        return {
            "ok": False,
            "error": "orphan_resolution_required",
            "orphans": orphans,
        }

    created_now = not skill_dir.exists()
    try:
        skill_dir.mkdir(parents=True, exist_ok=True)
        _write_files_atomically(skill_dir, files)
    except ValueError as exc:
        if created_now:
            shutil.rmtree(skill_dir, ignore_errors=True)
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        if created_now:
            shutil.rmtree(skill_dir, ignore_errors=True)
        logger.warning("Codeload install write failed: %s", exc)
        return {"ok": False, "error": f"Install failed: {exc}"}

    if orphans and orphan_resolution == "delete":
        delete_orphans(skill_dir, orphans)

    has_tools = "tools.py" in files
    _upsert_installed_entry(
        skill_id, version, "Community", "url", install_url, has_tools
    )
    return {"ok": True, "skill_id": skill_id}


def list_existing_skill_files(skill_dir: Path) -> list[str]:
    """Forward-slash relative paths of real files under skill_dir.

    Skips dotfiles and __pycache__ so callers building orphan diffs don't
    surface system cruft (.DS_Store, .part sidecars, .pyc) as user choices."""
    out: list[str] = []
    if not skill_dir.exists():
        return out
    for p in skill_dir.rglob("*"):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(skill_dir).parts
        if any(part.startswith(".") or part == "__pycache__" for part in rel_parts):
            continue
        out.append("/".join(rel_parts))
    return out


def delete_orphans(skill_dir: Path, orphans: list[str]) -> None:
    """Per-file os.unlink for each orphan, then prune empty subdirs (bottom-up).

    Path-traversal guard on every entry. Never removes skill_dir itself."""
    skill_root = skill_dir.resolve()
    for rel in orphans:
        target = (skill_dir / rel).resolve()
        if not target.is_relative_to(skill_root) or target == skill_root:
            continue
        if target.is_file():
            target.unlink()
    # Prune empty subdirs, deepest first; never prune skill_dir itself.
    for d in sorted(
        (p for p in skill_dir.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        try:
            d.rmdir()
        except OSError:
            pass


def _teardown_plugin_mcp(plugin_id: str) -> None:
    """Tear down every mcp_connections entry a plugin owns (Phase E, decision
    #9): stops any pooled stdio process, deregisters the connection's
    namespaced tools from shared.TOOLS/TOOL_DISPATCH, removes the record
    from config.json:mcp_connections, and wipes any stored OAuth credential
    — by delegating to mcp.manager.remove_plugin_mcp_servers(), which itself
    calls the exact same mcp.manager.remove() a user-initiated single-
    connection delete uses per connection, rather than a second
    reimplementation of that teardown.

    Called unconditionally from uninstall_skill's plugin-bundle branch below
    (added in Increment 2 as a no-op seam); test_uninstall_calls_mcp_
    teardown_hook patches this function and asserts it's invoked, so an
    accidental removal of the call site in a future refactor is caught by an
    existing test rather than silently regressing. Never raises — an MCP
    teardown failure must not block the rest of uninstall (cache-dir removal,
    command deregistration) from completing.
    """
    try:
        from mcp.manager import remove_plugin_mcp_servers
    except ImportError:
        logger.debug("mcp.manager.remove_plugin_mcp_servers unavailable — skipping MCP teardown for %s", plugin_id)
        return None
    try:
        removed = remove_plugin_mcp_servers(plugin_id)
        if removed:
            logger.info("Tore down %d MCP connection(s) for plugin %s: %s", len(removed), plugin_id, removed)
    except Exception as exc:
        logger.warning("MCP teardown failed for plugin %s: %s", plugin_id, exc)
    return None


def uninstall_skill(skill_id: str) -> dict:
    """Uninstall a skill or a plugin bundle by id.

    For a plugin bundle install (has a "skill_ids" field — see
    _upsert_plugin_bundle_entry / decision #3), this also removes the whole
    PLUGINS_DIR/cache/{source}/{plugin_id}/ tree (decision #9), taking every
    skill the plugin registered down with it, deregisters any commands it
    registered (decision #11), and calls the (currently no-op) MCP teardown
    hook (decision #9 / Phase E) — uninstall must not leave a plugin
    half-removed.
    """
    try:
        skill_dir = _safe_skill_dir(INSTALLED_SKILLS_DIR, skill_id)
        mine_dir = _safe_skill_dir(INSTALLED_SKILLS_DIR, "mine", skill_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    entries = load_installed()
    entry = next((e for e in entries if e.get("id") == skill_id), None)

    removed = False
    for d in [skill_dir, mine_dir]:
        if d.exists():
            shutil.rmtree(d)
            removed = True

    # Plugin-bundle install (decision #3): also remove the versioned cache
    # tree covering all its registered skills. Keyed on "skill_ids" presence
    # rather than tier/source alone, since that's the field unique to bundle
    # installs (a single-skill install via install_plugin() has no such key).
    if entry is not None and entry.get("skill_ids") is not None and entry.get("source"):
        _teardown_plugin_mcp(skill_id)

        from marketplace import commands as _commands
        _commands.deregister_plugin_commands(entry.get("command_ids") or [])

        try:
            plugin_cache_dir = _safe_skill_dir(PLUGINS_DIR / "cache", entry["source"], skill_id)
        except ValueError:
            plugin_cache_dir = None
        if plugin_cache_dir is not None and plugin_cache_dir.exists():
            shutil.rmtree(plugin_cache_dir)
            removed = True

    new_entries = [e for e in entries if e.get("id") != skill_id]
    if not removed and len(new_entries) == len(entries):
        return {"ok": False, "error": f"Skill '{skill_id}' not found"}
    save_installed(new_entries)
    return {"ok": True, "skill_id": skill_id}


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-") or "my-skill"


def create_user_skill(name: str, description: str, instructions: str) -> dict:
    skill_id = _slugify(name)
    skill_dir = INSTALLED_SKILLS_DIR / "mine" / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    safe_name = name.replace("\n", " ").replace("\r", " ")
    safe_desc = description.replace("\n", " ").replace("\r", " ")
    safe_instructions = instructions.replace("\r\n", "\n")
    # Prevent premature frontmatter close
    safe_instructions = "\n".join(
        line if line.strip() != "---" else "\\---"
        for line in safe_instructions.split("\n")
    )
    skill_md = (
        f"---\nname: {safe_name}\ndescription: {safe_desc}\n"
        f"metadata:\n  author: user\n  version: \"1.0\"\n  format: agentskills-1.0\n---\n\n"
        f"# {safe_name}\n\n{safe_instructions}\n"
    )
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
    entries = [e for e in load_installed() if e.get("id") != skill_id]
    entries.append({
        "id": skill_id,
        "version": "1.0",
        "tier": "Mine",
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "has_tools": False,
        "display_name": name,
    })
    save_installed(entries)
    return {"ok": True, "skill_id": skill_id}


def install_plugin(
    plugin_id: str,
    version: str,
    marketplace: str,
    skill_md: str,
    tier: str,
    marketplace_url: str = "",
    has_tools: bool = False,
) -> dict:
    """Install a full plugin to the versioned cache directory.

    Path: PLUGINS_DIR/cache/{marketplace}/{plugin_id}/{version}/
    Never overwrites an already-present version (SKILL.md present == installed).
    """
    # Resolve target path and assert it stays under PLUGINS_DIR/cache (path traversal guard).
    try:
        plugin_dir = _safe_skill_dir(PLUGINS_DIR / "cache", marketplace, plugin_id, version)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    # Idempotency check uses SKILL.md presence, not just the directory — a prior
    # crash between mkdir() and write_text() would otherwise leave the install
    # permanently broken with no way to recover via reinstall.
    if (plugin_dir / "SKILL.md").exists():
        _upsert_installed_entry(plugin_id, version, tier, marketplace, marketplace_url, has_tools)
        return {"ok": True, "plugin_id": plugin_id, "path": str(plugin_dir)}

    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

    _upsert_installed_entry(plugin_id, version, tier, marketplace, marketplace_url, has_tools)
    return {"ok": True, "plugin_id": plugin_id, "path": str(plugin_dir)}


def _upsert_installed_entry(
    plugin_id: str,
    version: str,
    tier: str,
    source: str,
    marketplace_url: str,
    has_tools: bool = False,
    *,
    sha: str | None = None,
    skill_ids: list[str] | None = None,
    consented: bool | None = None,
    command_ids: list[str] | None = None,
    mcp_connection_ids: list[str] | None = None,
) -> None:
    """Insert-or-replace the installed-skills.json record for `plugin_id`.

    sha/skill_ids/consented/command_ids/mcp_connection_ids are plugin-bundle-
    only fields (decision #3/#11/#5-Phase-E) — keyword-only and omitted from
    the record entirely when None (not just left at a default placeholder),
    so a plain single-skill install's record keeps its original shape.
    _upsert_plugin_bundle_entry below is a thin wrapper that always supplies
    them; this dedup avoids two near-identical read-modify-write
    implementations drifting apart (finding #7, 2026-08-07 milestone review).
    """
    with _INSTALL_INDEX_LOCK:
        entries = [e for e in load_installed() if e.get("id") != plugin_id]
        record = {
            "id": plugin_id,
            "version": version,
            "tier": tier,
            "installed_at": datetime.now(timezone.utc).isoformat(),
            "has_tools": has_tools,
            "source": source,
            "marketplace_url": marketplace_url,
        }
        if sha is not None:
            record["sha"] = sha
        if skill_ids is not None:
            record["skill_ids"] = skill_ids
        if consented is not None:
            record["consented"] = consented
        if command_ids is not None:
            record["command_ids"] = command_ids
        if mcp_connection_ids is not None:
            record["mcp_connection_ids"] = mcp_connection_ids
        entries.append(record)
        save_installed(entries)


# ── claude-plugins-official install (Phase A+B, 2026-08-07 milestone) ───────
# Decisions #3/#4: install = HTTPS-tarball fetch @ pinned sha, no git; a
# plugin is a bundle — recurse skills/*/SKILL.md, one install record covers
# every skill it registers.

def _upsert_plugin_bundle_entry(
    plugin_id: str,
    version: str,
    tier: str,
    source: str,
    marketplace_url: str,
    sha: str,
    skill_ids: list[str],
    has_tools: bool = False,
    consented: bool = False,
    command_ids: list[str] | None = None,
    mcp_connection_ids: list[str] | None = None,
) -> None:
    """Write ONE install record for a whole plugin bundle (decision #3): one
    plugin = one record, with skill_ids listing every skill it registered,
    command_ids (decision #11, Increment 2) listing every commands/*.md it
    registered, and mcp_connection_ids (Phase E, Increment 3) listing every
    mcp_connections entry it registered — so uninstall can tear down exactly
    what this plugin created without re-deriving it from the id-prefix
    convention alone.

    `consented` is threaded through from the route's server-side consent
    gate (decision #7, Increment 2) — install_claude_plugins_official_plugin
    only reaches this with consented=True once the caller has enforced it;
    this function itself performs no enforcement.
    """
    _upsert_installed_entry(
        plugin_id, version, tier, source, marketplace_url, has_tools,
        sha=sha, skill_ids=skill_ids, consented=consented, command_ids=command_ids,
        mcp_connection_ids=mcp_connection_ids,
    )


def _extract_plugin_version(files: dict[str, bytes]) -> str:
    """Best-effort version lookup from a freshly-fetched plugin tree: prefer
    .claude-plugin/plugin.json's "version" field (mirrors
    loader.load_plugin_manifest's precedence), then fall back to the first
    (alphabetically) bundled SKILL.md's frontmatter version. Returns "" if
    neither is present — caller falls back to the literal string "unknown",
    never an empty version-directory segment."""
    manifest_bytes = files.get(".claude-plugin/plugin.json")
    if manifest_bytes:
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            if isinstance(manifest, dict) and manifest.get("version"):
                return str(manifest["version"])
        except Exception:
            pass
    for rel in sorted(files):
        if rel.endswith("SKILL.md"):
            try:
                fm = _parse_skill_md_frontmatter(files[rel].decode("utf-8", errors="replace"))
            except Exception:
                continue
            if fm.get("version"):
                return str(fm["version"])
    return ""


def _discover_bundled_skill_dirs(plugin_dir: Path) -> list[Path]:
    """Recursively find every SKILL.md under an installed plugin (decision #3
    — a plugin bundles N skills; e.g. amd-skills ships 7 as <name>/SKILL.md
    rather than a single top-level SKILL.md; other plugins ship exactly one
    top-level SKILL.md). Returns each SKILL.md's parent dir, sorted for
    deterministic skill_ids ordering."""
    return sorted(
        {p.parent for p in plugin_dir.rglob("SKILL.md")},
        key=lambda p: p.relative_to(plugin_dir).as_posix(),
    )


# ── Plugin MCP servers (Phase E, 2026-08-07 milestone, decision #5) ─────────
# A plugin's .mcp.json declares mcpServers the same way Claude Code itself
# reads them; we reuse mcp.normalizer's parser (the same one the manual
# "Connect an MCP server" add-modal uses) and mcp.manager's connection model
# — no new schema, no new auth subsystem.

_SERVER_SHAPE_KEYS = ("type", "command", "url", "args", "env")


def _looks_like_bare_mcp_servers_map(config: dict) -> bool:
    """Heuristic for gap #3 (2026-08-07 milestone): some real .mcp.json files
    skip the "mcpServers" wrapper key entirely and put server definitions
    directly at the top level — confirmed real: Airtable's .mcp.json is
    `{"airtable": {"type": "http", "url": "..."}}`, no "mcpServers" key
    anywhere.

    Require EVERY top-level value to be a dict containing at least one
    recognizable server-shape key (type/command/url/args/env) — a narrower
    bar than "any dict of dicts", so a genuinely unrelated JSON file isn't
    misinterpreted as an MCP manifest just because it happens to be a dict
    of dicts (e.g. a settings file with nested objects). An empty dict is
    not bare-format (nothing to recognize as a server)."""
    if not config:
        return False
    return all(
        isinstance(v, dict) and any(k in v for k in _SERVER_SHAPE_KEYS)
        for v in config.values()
    )


def _mcp_manifest_from_dict(config: object) -> dict[str, dict]:
    """Return the mcpServers dict from a parsed .mcp.json-shaped object, or
    {} if it isn't recognizable as one.

    Two shapes are recognized (gap #3, 2026-08-07 milestone fix): the
    canonical wrapped form (`{"mcpServers": {...}}`) and a bare top-level
    form some real plugins ship instead — see
    _looks_like_bare_mcp_servers_map. The wrapped form always wins when a
    "mcpServers" key is present at all (even if it's not an object — e.g.
    the plugin.json string-pointer case handled elsewhere), so a bare-format
    misparse can only ever happen when "mcpServers" is entirely absent."""
    if not isinstance(config, dict):
        return {}
    declared = config.get("mcpServers")
    if isinstance(declared, dict):
        return declared
    if "mcpServers" not in config and _looks_like_bare_mcp_servers_map(config):
        return config
    return {}


def _resolve_plugin_relative_path(base_dir: str, rel: str) -> str | None:
    """Resolve `rel` (a relative path declared inside a plugin.json that
    itself lives at `base_dir`/.claude-plugin/plugin.json — "" for the
    plugin root, or a bundled skill dir's forward-slash relpath) against the
    plugin's own tree, returning a normalized forward-slash relpath rooted
    at the plugin root (matching the {relpath: bytes} key convention used
    elsewhere in this module).

    Returns None if `rel` is absolute, or normalizes to a path that escapes
    the plugin tree (path-traversal guard — same posture as
    _write_files_atomically's own guard, applied here to a string used as a
    dict-key/relative-Path lookup rather than a filesystem write target)."""
    if rel.startswith(("/", "\\")) or (len(rel) > 1 and rel[1] == ":"):
        return None
    import posixpath
    combined = posixpath.normpath(posixpath.join(base_dir or ".", rel.replace("\\", "/")))
    if combined == ".." or combined.startswith("../") or combined == ".":
        return None
    return combined


def _mcp_servers_declared_via_plugin_json(plugin_json_dir: Path) -> dict[str, dict]:
    """Read `plugin_json_dir`/.claude-plugin/plugin.json and return the
    mcpServers dict it declares — gap #1, 2026-08-07 milestone fix.

    Claude Code's plugin.json convention allows `mcpServers` to be either an
    inline OBJECT of server definitions (same shape a `.mcp.json` file's own
    "mcpServers" value has) or a STRING relative path — resolved relative to
    `plugin_json_dir` itself (the plugin's own root, NOT the .claude-plugin/
    subdirectory the manifest file lives in) — pointing at another JSON file
    that declares the real mcpServers object. Confirmed real: datadog's
    plugin.json has `"mcpServers": "./.dd_claude-code_mcp.json"`, a
    non-canonical filename our .mcp.json glob alone never finds.

    A pointed-to file whose own "mcpServers" is ALSO a string (a pointer
    chain) is not a real case worth supporting — treated as "no servers
    found" (returns {}) rather than recursing or raising, per this gap's
    explicit scope. The pointed-to file's servers dict is still run through
    _mcp_manifest_from_dict so gap #3's bare-format detection applies to it
    too.

    Returns {} on any missing/malformed input or a pointer that escapes the
    plugin tree."""
    plugin_json_path = plugin_json_dir / ".claude-plugin" / "plugin.json"
    if not plugin_json_path.exists():
        return {}
    try:
        manifest = json.loads(plugin_json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Malformed plugin.json in %s: %s", plugin_json_dir, exc)
        return {}
    if not isinstance(manifest, dict):
        return {}
    declared = manifest.get("mcpServers")
    if isinstance(declared, dict):
        return declared
    if not isinstance(declared, str):
        return {}

    pointer_rel = _resolve_plugin_relative_path("", declared)
    if pointer_rel is None:
        logger.warning("plugin.json mcpServers pointer escapes plugin dir in %s: %r",
                        plugin_json_dir, declared)
        return {}
    pointer_path = (plugin_json_dir / pointer_rel).resolve()
    try:
        base_resolved = plugin_json_dir.resolve()
    except Exception:
        return {}
    if not pointer_path.is_relative_to(base_resolved) or not pointer_path.exists():
        logger.warning("plugin.json mcpServers pointer not found or escapes plugin dir: %s (from %s)",
                        pointer_path, plugin_json_dir)
        return {}
    try:
        pointed = json.loads(pointer_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Malformed MCP manifest at plugin.json pointer %s: %s", pointer_path, exc)
        return {}
    if isinstance(pointed, dict) and isinstance(pointed.get("mcpServers"), str):
        logger.warning("plugin.json mcpServers pointer at %s itself points at another "
                        "string pointer — not supported, skipping", pointer_path)
        return {}
    return _mcp_manifest_from_dict(pointed)


def _discover_plugin_mcp_manifest(plugin_dir: Path) -> dict[str, dict]:
    """Merge mcpServers declarations from every .mcp.json under an installed
    plugin: the plugin root (the canonical Claude Code plugin location,
    alongside .claude-plugin/plugin.json) and any bundled skill dir's own
    .mcp.json (the per-skill convention marketplace.loader.load_plugin_mcp
    already uses for the separate single-skill install path). Also reads
    each of those dirs' own .claude-plugin/plugin.json for an mcpServers
    declaration (gap #1, 2026-08-07 milestone fix — a plugin's mcpServers
    may point at a non-canonically-named MCP config file instead of
    shipping a `.mcp.json`) — merged in BEFORE that dir's own .mcp.json, so
    a standalone .mcp.json still wins a same-named collision within one
    dir (the more direct/canonical declaration). The root dir is merged in
    last overall so it wins on a same-named server collision against any
    per-skill duplicate — it's merged in last so dict.update() overwrites
    any earlier per-skill duplicate.

    Reads from disk — called after install_claude_plugins_official_plugin
    has already written the plugin's files. See
    _discover_plugin_mcp_manifest_from_files for the in-memory equivalent
    used by the read-only consent-preview call.
    """
    servers: dict[str, dict] = {}
    skill_dirs = [d for d in _discover_bundled_skill_dirs(plugin_dir) if d != plugin_dir]
    for d in skill_dirs + [plugin_dir]:
        servers.update(_mcp_servers_declared_via_plugin_json(d))
        mcp_json = d / ".mcp.json"
        if not mcp_json.exists():
            continue
        try:
            config = json.loads(mcp_json.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Malformed .mcp.json in %s: %s", d, exc)
            continue
        servers.update(_mcp_manifest_from_dict(config))
    return servers


def _discover_bundled_skill_dirs_from_files(files: dict[str, bytes]) -> set[str]:
    """In-memory equivalent of _discover_bundled_skill_dirs: return the set
    of relative directory paths (the plugin root itself as "") that contain
    a SKILL.md, derived from an in-memory {relpath: bytes} tree rather than
    walking an on-disk plugin_dir with rglob. Used by
    _discover_plugin_mcp_manifest_from_files (fix #3, 2026-08-07 milestone
    adversarial review) to scope the consent-preview's .mcp.json discovery
    to exactly the same directories the real, on-disk install-time
    registration scans — see that function's docstring for the full
    rationale."""
    dirs: set[str] = {""}
    for rel in files:
        if rel == "SKILL.md":
            dirs.add("")
        elif rel.endswith("/SKILL.md"):
            dirs.add(rel[: -len("/SKILL.md")])
    return dirs


def _mcp_servers_declared_via_plugin_json_from_files(
    files: dict[str, bytes], dir_rel: str
) -> dict[str, dict]:
    """In-memory equivalent of _mcp_servers_declared_via_plugin_json: read
    `{dir_rel}/.claude-plugin/plugin.json` (dir_rel="" for the plugin root)
    from an in-memory {relpath: bytes} tree and return the mcpServers dict
    it declares, following a STRING pointer to another in-tree file exactly
    like the on-disk variant — see that function's docstring for the full
    gap #1 rationale. Used by _discover_plugin_mcp_manifest_from_files so
    the read-only consent-preview sees the identical servers the real,
    on-disk install-time registration would find."""
    plugin_json_rel = f"{dir_rel}/.claude-plugin/plugin.json" if dir_rel else ".claude-plugin/plugin.json"
    manifest_bytes = files.get(plugin_json_rel)
    if manifest_bytes is None:
        return {}
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except Exception as exc:
        logger.warning("Malformed plugin.json in %s: %s", dir_rel or "<plugin root>", exc)
        return {}
    if not isinstance(manifest, dict):
        return {}
    declared = manifest.get("mcpServers")
    if isinstance(declared, dict):
        return declared
    if not isinstance(declared, str):
        return {}

    # Fix (adversarial review of this milestone's own gap-1 fix): resolve
    # `declared` against base_dir="" FIRST — exactly like the on-disk sibling
    # _mcp_servers_declared_via_plugin_json does — before joining onto this
    # dir's own relpath. Resolving straight against `dir_rel` (the calling
    # skill dir's own relpath) as the base let a ".." in `declared` walk OUT
    # of that skill dir's subtree into a sibling dir or the plugin root, as
    # long as the final result stayed somewhere inside the overall tarball
    # tree — e.g. `_resolve_plugin_relative_path('skills/foo',
    # '../bar/../../secret_outside')` normalizes to 'secret_outside', a
    # valid in-tree path entirely outside skills/foo's own subtree, which
    # the on-disk function would reject outright. Resolving against ""
    # first rejects any ".." in `declared` unconditionally (same as
    # on-disk), then the already-".."-free pointer_rel is joined onto
    # dir_rel for the real in-tree lookup — the on-disk equivalent of
    # `(plugin_json_dir / pointer_rel).resolve()`.
    pointer_rel = _resolve_plugin_relative_path("", declared)
    if pointer_rel is None:
        logger.warning("plugin.json mcpServers pointer escapes plugin tree in %s: %r",
                        dir_rel or "<plugin root>", declared)
        return {}
    combined_rel = _resolve_plugin_relative_path(dir_rel, pointer_rel)
    if combined_rel is None:
        logger.warning("plugin.json mcpServers pointer escapes plugin tree in %s: %r",
                        dir_rel or "<plugin root>", declared)
        return {}
    pointed_bytes = files.get(combined_rel)
    if pointed_bytes is None:
        logger.warning("plugin.json mcpServers pointer not found: %s (from %s)",
                        combined_rel, dir_rel or "<plugin root>")
        return {}
    try:
        pointed = json.loads(pointed_bytes.decode("utf-8"))
    except Exception as exc:
        logger.warning("Malformed MCP manifest at plugin.json pointer %s: %s", pointer_rel, exc)
        return {}
    if isinstance(pointed, dict) and isinstance(pointed.get("mcpServers"), str):
        logger.warning("plugin.json mcpServers pointer at %s itself points at another "
                        "string pointer — not supported, skipping", pointer_rel)
        return {}
    return _mcp_manifest_from_dict(pointed)


def _discover_plugin_mcp_manifest_from_files(files: dict[str, bytes]) -> dict[str, dict]:
    """Same merge semantics as _discover_plugin_mcp_manifest, but over an
    in-memory {relpath: bytes} tree (as returned by the tarball fetcher)
    rather than files already written to disk — used by
    get_claude_plugins_official_capabilities, which must stay read-only /
    zero-disk-writes for the consent-preview call (decision #7). Deepest
    dir first, root (fewest "/") last, so dict.update() lets the root
    manifest win a same-named collision, same tie-break as the on-disk
    variant above; within one dir, its plugin.json-declared servers (gap #1)
    are merged in BEFORE its own .mcp.json, so a standalone .mcp.json still
    wins a same-named collision within that dir.

    Fix #3 (2026-08-07 milestone adversarial review): scoped to the plugin
    root plus bundled-skill-dir .mcp.json/plugin.json files only — matching
    _discover_plugin_mcp_manifest's on-disk scope (plugin_dir +
    _discover_bundled_skill_dirs(plugin_dir)) exactly. Previously this scanned
    EVERY .mcp.json anywhere in the tarball tree, so a server declared in
    some unrelated directory (e.g. docs/example/.mcp.json, with no adjacent
    SKILL.md) would show up in the consent-preview as "will run" but never
    actually get registered at real install time — the same class of "what
    you consented to isn't what happens" bug this milestone already fixed
    once for the pinned_ref TOCTOU (see _fetch_plugin_source_tree).

    Ordering (fix, adversarial review of this fix): root ("") is separated
    out and appended LAST unconditionally rather than sorted in by "/"-count
    — a bundled skill dir living directly under the plugin root (dir="",
    dir="myskill", 0 slashes each) previously TIED with root under a
    slash-count sort, so root could merge first and the skill dir last,
    letting the skill dir win a same-named-server collision — the opposite
    of the on-disk sibling _discover_plugin_mcp_manifest, which never sorts
    by slash-count at all and instead appends plugin_dir last via plain list
    concatenation (`skill_dirs + [plugin_dir]`). Non-root dirs are sorted
    alphabetically here to match _discover_bundled_skill_dirs' own sort key
    (relpath.as_posix()) — on-disk, skill-dir-vs-skill-dir precedence is
    whatever that alphabetical order produces, so mirroring it keeps the two
    functions' precedence semantics identical.
    """
    allowed_dirs = _discover_bundled_skill_dirs_from_files(files)
    ordered_dirs = sorted(d for d in allowed_dirs if d)
    if "" in allowed_dirs:
        ordered_dirs.append("")
    servers: dict[str, dict] = {}
    for d in ordered_dirs:
        servers.update(_mcp_servers_declared_via_plugin_json_from_files(files, d))
        mcp_rel = f"{d}/.mcp.json" if d else ".mcp.json"
        config_bytes = files.get(mcp_rel)
        if config_bytes is None:
            continue
        try:
            config = json.loads(config_bytes.decode("utf-8"))
        except Exception:
            continue
        servers.update(_mcp_manifest_from_dict(config))
    return servers


def _missing_secrets_for_server(parsed) -> list[str]:
    """Return the names of declared config values in a normalized MCP server
    config (an mcp.normalizer.NormalizeResult) that have no resolved value
    yet — i.e. still need a secret collected before the server can safely be
    live-spawned. Two independent conventions are detected:

    1. {PLACEHOLDER}-style template syntax, or bash-parameter-expansion
       syntax ("${VAR}" / "${VAR:-default}" — 2026-08-07 milestone gap #2
       fix: mcp.normalizer._find_placeholders runs a second regex
       specifically for this shape, since the ":-default" portion isn't a
       "{VAR}" substring the bare-brace regex can match) — still literally
       present in a declared env/header/url/arg/command string.
    2. Fix #2 (2026-08-07 milestone adversarial review): an env var or header
       value that is the empty string — a common "user must fill this in"
       convention distinct from the template-placeholder one, which
       _find_placeholders' regex never matches (no "{...}" substring to find).
       Checked here at the installer level, not inside the shared
       _find_placeholders helper — that helper's "no {VAR} substring means
       nothing to report" semantics may be exactly right for its other
       caller (the manual add-modal's own {placeholder}-in-headers
       detection), so the empty-string check is layered on as an addition
       here rather than changing its shared meaning.

    Fix #1 (2026-08-07 milestone adversarial review): a stdio server can also
    declare a secret as a CLI flag instead of (or as well as) an env var —
    e.g. {"command": "npx", "args": [..., "--api-key", "{FOO_API_KEY}"]}.
    _find_placeholders takes a field-name -> value dict and only cares about
    the string values, so args are indexed positionally into such a dict to
    reuse the same regex rather than duplicating it.

    Decision #5: env-var secrets map onto the existing add-modal
    {placeholder}-field flow; actually collecting the value from the user is
    Increment 4's job (a consent dialog). At install time we can only detect
    that a declared value is still unresolved, not fill it in.
    """
    from mcp.normalizer import _find_placeholders

    def _add_unique(names: list[str], more: list[str]) -> None:
        for n in more:
            if n not in names:
                names.append(n)

    if parsed.transport == "stdio":
        missing = _find_placeholders(parsed.env)
        arg_fields = {f"_arg{i}": a for i, a in enumerate(parsed.args)}
        if parsed.command:
            arg_fields["_command"] = parsed.command
        _add_unique(missing, _find_placeholders(arg_fields))
        for key, val in parsed.env.items():
            if val == "" and key not in missing:
                missing.append(key)
        return missing

    fields = dict(parsed.headers)
    if parsed.url:
        fields["_url"] = parsed.url
    if parsed.auth_value:
        fields["_auth_value"] = parsed.auth_value
    missing = _find_placeholders(fields)
    for key, val in parsed.headers.items():
        if val == "" and key not in missing:
            missing.append(key)
    return missing


def _register_plugin_mcp_servers(plugin_id: str, plugin_dir: Path) -> list[str]:
    """Register every MCP server an installed plugin declares (Phase E,
    decision #5) into mcp.manager's connection model. Called from
    install_claude_plugins_official_plugin right after skill/command
    registration, once the plugin's files are actually on disk.

    Parses each mcpServers entry with mcp.normalizer._parse_server_entry —
    the SAME parser the manual "Connect an MCP server" add-modal uses — so a
    plugin's .mcp.json is interpreted with exactly the schema Claude Code
    itself uses, not a bespoke one. An entry that fails to parse (malformed,
    or contains a shell-metacharacter-bearing command — see the normalizer's
    guard) is skipped with a warning; one bad server declaration must not
    fail the whole plugin install.

    Returns the list of mcp_connections ids registered (enabled or left
    pending on a missing secret) — persisted on the install record as
    mcp_connection_ids so uninstall doesn't need to re-derive them.
    """
    servers = _discover_plugin_mcp_manifest(plugin_dir)
    if not servers:
        return []

    from mcp.normalizer import _parse_server_entry
    from mcp import manager as _mcp_manager
    import dataclasses as _dataclasses

    connection_ids: list[str] = []
    for name, raw_cfg in servers.items():
        parsed = _parse_server_entry(name, raw_cfg)
        if parsed is None:
            logger.warning("Plugin %s: could not parse MCP server %r (%r) — skipping",
                            plugin_id, name, raw_cfg)
            continue
        missing = _missing_secrets_for_server(parsed)
        provisional = _dataclasses.asdict(parsed)
        result = _mcp_manager.register_plugin_mcp_server(plugin_id, name, provisional, missing)
        connection_ids.append(result["id"])
    return connection_ids


def namespaced_skill_id(plugin_id: str, plugin_version_dir: Path, skill_dir: Path) -> str:
    """Compute the plugin-namespaced skill id for a bundled skill (finding #2,
    2026-08-07 milestone adversarial review).

    Without namespacing, a bundled skill's id was derived from its SKILL.md's
    parent folder name alone: a plugin whose SKILL.md sits at the version
    root registered under the version string itself (e.g. "1.0.0"), and two
    plugins bundling a same-named skill folder (e.g. "getting-started")
    silently collided — first-found wins, the other vanishes from
    SKILL_PROMPTS.

    Returns "{plugin_id}__{relpath}" where relpath is skill_dir's path
    relative to the plugin's version dir with "/" normalized to "-", or bare
    plugin_id (never the version string) when skill_dir IS the version dir —
    i.e. a single top-level SKILL.md plugin.

    Used both here (building install_claude_plugins_official_plugin's
    skill_ids) and by shared.load_installed_skill_prompts() so the two never
    drift apart and produce different ids for the same on-disk skill.
    """
    try:
        rel = skill_dir.resolve().relative_to(plugin_version_dir.resolve())
    except ValueError:
        return plugin_id
    rel_str = rel.as_posix()
    if rel_str in ("", "."):
        return plugin_id
    return f"{plugin_id}__{rel_str.replace('/', '-')}"


def skill_id_for_cache_path(cache_root: Path, skill_md_path: Path) -> str | None:
    """Compute the namespaced skill id for a SKILL.md discovered under a
    PLUGINS_DIR/cache-shaped root (cache/{source}/{plugin_id}/{version}/...).

    Returns None if skill_md_path doesn't have enough path segments under
    cache_root to resolve a plugin_id + version dir (i.e. isn't actually a
    plugin-bundle path) — callers should fall back to their own default.

    Shared by shared.load_installed_skill_prompts() (registering discovered
    skills) and code_runner's _find_skill_dir() (resolving a namespaced id
    back to its on-disk dir, finding #4) so both sides of the round-trip use
    one definition.
    """
    try:
        rel_parts = skill_md_path.relative_to(cache_root).parts
    except ValueError:
        return None
    if len(rel_parts) < 4:  # source, plugin_id, version, SKILL.md (or deeper)
        return None
    plugin_id = rel_parts[1]
    version_dir = cache_root.joinpath(*rel_parts[:3])
    return namespaced_skill_id(plugin_id, version_dir, skill_md_path.parent)


def _fetch_plugin_source_tree(
    entry: dict, pinned_ref: str | None = None
) -> tuple[str, dict[str, bytes], str] | dict:
    """Resolve entry's `plugin_source` and fetch its tree via the existing
    HTTPS-tarball fetcher at the pinned sha (falling back to ref, then
    "main", when no sha is recorded) — unless `pinned_ref` is given, in
    which case it is used verbatim INSTEAD of re-resolving from the entry.

    `pinned_ref` (fix #1, 2026-08-07 milestone adversarial review of
    Increment 2 — TOCTOU): the consent-preview call
    (get_claude_plugins_official_capabilities) and the real install call
    (install_claude_plugins_official_plugin) used to each independently
    re-resolve `ref` from `entry.plugin_source` and fetch separately. For
    the ~53/280 catalog entries with no pinned sha, those two fetches could
    resolve to different content if the entry's plugin_source (e.g. the
    server's own catalog cache) changed between the two calls — the user
    would consent to capabilities from fetch #1 while fetch #2's (possibly
    different) content is what actually gets installed. Passing the exact
    ref string the preview call resolved back into the install call closes
    that gap: the install fetch is pinned to what was actually shown to the
    user, not to whatever the entry currently says.

    Returns (plugin_id, files, resolved_ref) on success — resolved_ref is
    the concrete ref string actually used for the fetch, which callers
    should surface back to their own caller (e.g. the consent-preview route
    response) so a later install call can pass it back in as `pinned_ref`.
    Returns an {"ok": False, "error": ...} dict on failure. Shared by
    install_claude_plugins_official_plugin and
    get_claude_plugins_official_capabilities (Increment 2, decision #7) so
    the source-resolution/fetch/error-message logic lives in exactly one
    place instead of drifting between an install path and a preview path.
    """
    plugin_id = entry.get("id") or entry.get("name") or ""
    if not plugin_id:
        return {"ok": False, "error": "entry is missing id/name"}

    plugin_source = entry.get("plugin_source") or {}
    url = plugin_source.get("url", "")
    owner_repo = github_fetcher.parse_git_clone_url(url)
    if owner_repo is None:
        return {"ok": False, "error": f"Could not parse plugin source url: {url!r}"}
    owner, repo = owner_repo
    subpath = plugin_source.get("path", "")
    ref = pinned_ref or plugin_source.get("sha") or plugin_source.get("ref") or "main"

    try:
        files = github_fetcher.download_skill_tarball(owner, repo, ref, subpath)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.warning("Codeload download failed for plugin %s: %s", plugin_id, exc)
        return {"ok": False, "error": f"Download failed: {exc}"}

    if not files:
        return {"ok": False, "error": "No files found at pinned plugin source"}

    return plugin_id, files, ref


def get_claude_plugins_official_capabilities(entry: dict) -> dict:
    """Fetch (read-only, never writes to disk) a claude-plugins-official
    plugin's tree and summarize what installing it would do, for the
    server-side consent gate (decision #7 — "dialog names what will
    execute... lists declared capabilities").

    Returns {"ok": True, "plugin_id", "skill_count", "has_mcp",
    "has_local_code", "mcp_servers", "resolved_ref"} or {"ok": False,
    "error"}. `has_mcp` = the bundle declares at least one MCP server
    ("runs a local server") — derived from the real discovery result
    (_discover_plugin_mcp_manifest_from_files), NOT a bare `.mcp.json`
    filename sniff (gap #1, 2026-08-07 milestone fix: a plugin's manifest
    may live at a non-canonical filename pointed to from plugin.json's own
    "mcpServers" string field — a filename check would silently gate the
    fixed discovery call out of ever running); `has_local_code` = any
    bundled skill ships a `tools.py` ("runs code locally"). Because this
    only fetches and inspects the tarball in memory — it never calls
    _write_files_atomically nor _upsert_plugin_bundle_entry — calling it
    before consent is granted cannot itself install or execute anything.

    `mcp_servers` (Phase E, Increment 3, decision #7): when `has_mcp` is
    true, a list of `{"name", "needs_secrets"}` — one entry per declared
    mcpServers entry, `needs_secrets` listing any {PLACEHOLDER}-style env
    var / header / url value with no resolved value yet (see
    _missing_secrets_for_server). This is exactly the data a future consent
    dialog (Increment 4) needs to say "this needs a Datadog API key" instead
    of just "runs a local server" — computed here, read-only, so Increment 4
    doesn't need another backend round-trip to get it.

    `resolved_ref` (fix #1, 2026-08-07 milestone adversarial review) is the
    concrete ref string this preview actually fetched at — the caller
    (routes/marketplace.py) must echo it back to the client so a subsequent
    consent=True install call can pass it through as `pinned_ref`, pinning
    the real install to the exact content that was previewed here rather
    than letting the install re-resolve `ref` from a possibly-since-changed
    entry (see _fetch_plugin_source_tree's docstring for the full TOCTOU
    rationale).
    """
    fetched = _fetch_plugin_source_tree(entry)
    if isinstance(fetched, dict):
        return fetched
    plugin_id, files, resolved_ref = fetched

    skill_count = sum(1 for rel in files if rel.endswith("SKILL.md"))
    has_local_code = any(rel.endswith("tools.py") for rel in files)

    # has_mcp keeps its original "ships a canonical .mcp.json file" signal
    # (even one that happens to declare zero servers today — a plugin
    # author's stated intent to run something is still worth surfacing) OR'd
    # with whether the real, gap-1-aware discovery below actually found a
    # server. The OR is required, not a stylistic choice: a bare filename
    # check ALONE would gate discovery on a convention some real plugins
    # don't follow — confirmed: datadog's real MCP config lives at
    # ".dd_claude-code_mcp.json" (pointed to from plugin.json's own
    # "mcpServers" string field), which does NOT end in literal ".mcp.json",
    # so relying on the filename check alone would silently reproduce this
    # milestone's original bug (consent dialog shows no MCP info at all)
    # even after fixing _discover_plugin_mcp_manifest_from_files itself.
    discovered_servers = _discover_plugin_mcp_manifest_from_files(files)
    has_mcp = any(rel.endswith(".mcp.json") for rel in files) or bool(discovered_servers)

    mcp_servers: list[dict] = []
    if has_mcp:
        from mcp.normalizer import _parse_server_entry
        for name, raw_cfg in discovered_servers.items():
            parsed = _parse_server_entry(name, raw_cfg)
            needs_secrets = _missing_secrets_for_server(parsed) if parsed is not None else []
            mcp_servers.append({"name": name, "needs_secrets": needs_secrets})

    return {
        "ok": True,
        "plugin_id": plugin_id,
        "skill_count": skill_count,
        "has_mcp": has_mcp,
        "has_local_code": has_local_code,
        "mcp_servers": mcp_servers,
        "resolved_ref": resolved_ref,
    }


def install_claude_plugins_official_plugin(
    entry: dict, consented: bool = False, pinned_ref: str | None = None
) -> dict:
    """Install a claude-plugins-official plugin (decisions #2-#4).

    `entry` is a normalized catalog entry from
    marketplace.registry.fetch_claude_plugins_official — it must carry a
    `plugin_source` dict with url/path/ref/sha (see
    registry._normalize_plugin_source).

    `consented` (decision #7): must be True to reach this function per the
    server-side consent gate enforced by the route handler
    (routes/marketplace.py) — threaded through here purely so the install
    record reflects what the user actually agreed to; this function itself
    does NOT re-check it (the route is the single enforcement point).

    `pinned_ref` (fix #1, 2026-08-07 milestone adversarial review — TOCTOU):
    when given, used verbatim as the fetch ref INSTEAD of re-resolving from
    `entry.plugin_source`. The route handler passes through whatever
    `resolved_ref` the preceding consent-preview call
    (get_claude_plugins_official_capabilities) reported, so the real install
    fetches the exact content the user was shown, even if the entry's own
    plugin_source has since changed (e.g. a catalog refresh landed between
    the two calls). When None — e.g. a legacy/simplified caller that never
    captured a preview's resolved_ref — falls back to today's behavior:
    resolve `ref` from the entry, best effort. See
    _fetch_plugin_source_tree's docstring for the full rationale.

    Fetches the plugin's tree via the existing HTTPS-tarball fetcher at the
    pinned sha (falling back to ref, then "main", when no sha is recorded),
    writes it to PLUGINS_DIR/cache/claude-plugins-official/{plugin_id}/{version}/
    (never overwriting an existing version dir), and recursively registers
    every bundled skills/*/SKILL.md under one install record. Also discovers
    and registers any bundled commands/*.md (decision #11) — command_ids are
    stored on the install record so uninstall can clean them up too.

    Registered skills become visible to shared.load_installed_skill_prompts()
    because PLUGINS_DIR/cache is a USER_SKILL_DIRS root (see config.py) — no
    separate registration call is needed here; the caller (route handler)
    refreshes SKILL_PROMPTS the same way it does for any other install.
    """
    fetched = _fetch_plugin_source_tree(entry, pinned_ref=pinned_ref)
    if isinstance(fetched, dict):
        return fetched
    plugin_id, files, _resolved_ref = fetched

    version = _extract_plugin_version(files) or "unknown"
    tier = entry.get("tier", "Verified")
    sha = (entry.get("plugin_source") or {}).get("sha", "")

    try:
        plugin_dir = _safe_skill_dir(
            PLUGINS_DIR / "cache", "claude-plugins-official", plugin_id, version
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    # Idempotency: never overwrite an already-installed version (decision #4).
    # A non-empty dir means a prior install completed (or is at least further
    # along than "just mkdir'd") — re-registering from what's already on disk
    # is safe and cheap; re-fetching would only waste bandwidth.
    already_installed = plugin_dir.exists() and any(plugin_dir.iterdir())
    # Default: record this call's freshly-resolved sha (the normal, fresh-
    # install case). The "version dir exists, no matching record" fallback
    # branch below overrides this to "" — see its comment (fix #5).
    sha_for_record = sha
    if already_installed:
        # Finding #6: if an install record for this plugin_id already exists,
        # it was written the first time this version dir was populated (with
        # whatever sha was pinned back then). The `sha` resolved above comes
        # from *this* call's catalog entry and may have since diverged (e.g.
        # the catalog's pinned sha moved but the version string didn't) —
        # blindly re-upserting would make installed-skills.json claim a sha
        # that doesn't match what's actually on disk. So: re-install of an
        # already-installed version is a no-op success that reuses the
        # existing record verbatim, never re-upserting a divergent sha.
        existing = next((e for e in load_installed() if e.get("id") == plugin_id), None)
        if existing is not None:
            # Re-register commands from disk even on this fast path: COMMAND_REGISTRY
            # is in-memory only (decision #11), so a second install() call in the
            # same process (or a future explicit "refresh" action) must still be
            # able to repopulate it without re-fetching/re-writing anything.
            from marketplace import commands as _commands
            _commands.register_plugin_commands(plugin_id, plugin_dir)

            # Fix #6 (2026-08-07 milestone adversarial review): a plugin
            # installed by Increment 1/2's code — before Phase E existed —
            # has no "mcp_connection_ids" key on its record at all. That's
            # distinguishable from a plugin Phase E code already handled
            # correctly (which always sets the key, even to an empty list
            # when it genuinely has no MCP servers). Backfill now — the
            # files are already on disk from the prior install — rather than
            # leaving it stuck with no remediation short of a full
            # uninstall+reinstall.
            mcp_connection_ids = existing.get("mcp_connection_ids")
            if mcp_connection_ids is None:
                mcp_connection_ids = _register_plugin_mcp_servers(plugin_id, plugin_dir)
                _upsert_plugin_bundle_entry(
                    plugin_id,
                    existing.get("version", version),
                    existing.get("tier", tier),
                    existing.get("source", "claude-plugins-official"),
                    existing.get("marketplace_url", ""),
                    existing.get("sha", ""),
                    existing.get("skill_ids", []),
                    existing.get("has_tools", False),
                    consented=existing.get("consented", False),
                    command_ids=existing.get("command_ids", []),
                    mcp_connection_ids=mcp_connection_ids,
                )
            return {
                "ok": True,
                "plugin_id": plugin_id,
                "path": str(plugin_dir),
                "skill_ids": existing.get("skill_ids", []),
                "command_ids": existing.get("command_ids", []),
                "mcp_connection_ids": mcp_connection_ids,
            }
        # Version dir exists but no matching record (e.g. a prior run crashed
        # after writing files but before the upsert) — fall through and
        # register from what's already on disk, same as a fresh install.
        # Fix #5 (2026-08-07 milestone adversarial review): this is the same
        # bug class Increment 1 already fixed for the sibling branch above —
        # `sha` was resolved from *this* call's entry, which is NOT
        # necessarily the sha that produced the bytes already sitting on
        # disk from the earlier (crashed) attempt. We have no way to verify
        # they match, so record sha="" (unknown) rather than an unverifiable
        # value, same rationale as the "existing record found" branch above.
        sha_for_record = ""
    else:
        created_now = not plugin_dir.exists()
        try:
            plugin_dir.mkdir(parents=True, exist_ok=True)
            _write_files_atomically(plugin_dir, files)
        except ValueError as exc:
            if created_now:
                shutil.rmtree(plugin_dir, ignore_errors=True)
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            if created_now:
                shutil.rmtree(plugin_dir, ignore_errors=True)
            logger.warning("Plugin install write failed for %s: %s", plugin_id, exc)
            return {"ok": False, "error": f"Install failed: {exc}"}

    skill_dirs = _discover_bundled_skill_dirs(plugin_dir)
    skill_ids = [namespaced_skill_id(plugin_id, plugin_dir, d) for d in skill_dirs]
    has_tools = any((d / "tools.py").exists() for d in skill_dirs)

    # Commands (decision #11) — own registry, discovered/registered here so
    # they're available immediately without a separate route call, mirroring
    # how skills become visible via PLUGINS_DIR/cache being a USER_SKILL_DIRS
    # root. command_ids is persisted on the install record so uninstall can
    # deregister them (see uninstall_skill's plugin-bundle branch).
    from marketplace import commands as _commands
    command_ids = _commands.register_plugin_commands(plugin_id, plugin_dir)

    # MCP servers (Phase E, Increment 3, decision #5) — registered here, once
    # the plugin's files are actually on disk, same reasoning as commands
    # above: available immediately without a separate route call. Unlike
    # commands (in-memory-only COMMAND_REGISTRY), mcp_connections persists to
    # config.json, so this is skipped on the "already installed, reuse
    # existing record" fast path above — nothing to redo there.
    mcp_connection_ids = _register_plugin_mcp_servers(plugin_id, plugin_dir)

    _upsert_plugin_bundle_entry(
        plugin_id, version, tier, "claude-plugins-official",
        entry.get("install_url", ""), sha_for_record, skill_ids, has_tools,
        consented=consented, command_ids=command_ids,
        mcp_connection_ids=mcp_connection_ids,
    )
    return {
        "ok": True,
        "plugin_id": plugin_id,
        "path": str(plugin_dir),
        "skill_ids": skill_ids,
        "command_ids": command_ids,
        "mcp_connection_ids": mcp_connection_ids,
    }
