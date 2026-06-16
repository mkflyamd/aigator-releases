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
        dest_resolved = skill_dir.resolve()
        for rel, data in files.items():
            if rel.startswith(("/", "\\")) or (len(rel) > 1 and rel[1] == ":"):
                raise ValueError(f"absolute path not allowed: {rel}")
            target = (skill_dir / rel).resolve()
            if not target.is_relative_to(dest_resolved):
                raise ValueError(f"path traversal not allowed: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            part = target.with_suffix(target.suffix + ".part")
            part.write_bytes(data)
            os.replace(part, target)
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


def uninstall_skill(skill_id: str) -> dict:
    try:
        skill_dir = _safe_skill_dir(INSTALLED_SKILLS_DIR, skill_id)
        mine_dir = _safe_skill_dir(INSTALLED_SKILLS_DIR, "mine", skill_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    removed = False
    for d in [skill_dir, mine_dir]:
        if d.exists():
            shutil.rmtree(d)
            removed = True
    entries = load_installed()
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
) -> None:
    with _INSTALL_INDEX_LOCK:
        entries = [e for e in load_installed() if e.get("id") != plugin_id]
        entries.append({
            "id": plugin_id,
            "version": version,
            "tier": tier,
            "installed_at": datetime.now(timezone.utc).isoformat(),
            "has_tools": has_tools,
            "source": source,
            "marketplace_url": marketplace_url,
        })
        save_installed(entries)
