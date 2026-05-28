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
    """Install a SKILL.md-only skill. If install_url given and skill_md empty,
    downloads the .gator ZIP and extracts SKILL.md only (tools.py is ignored in Phase 1)."""
    try:
        skill_dir = _safe_skill_dir(INSTALLED_SKILLS_DIR, skill_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    if install_url and not skill_md:
        if not install_url.startswith(("https://", "http://")):
            return {"ok": False, "error": "install_url must be an http:// or https:// URL"}
        try:
            req = urllib.request.Request(install_url, headers={"User-Agent": "AIGator/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read(20 * 1024 * 1024)  # 20 MB limit
            # Detect format from content: ZIP magic bytes are PK\x03\x04
            if data[:4] == b"PK\x03\x04":
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    names = [n for n in zf.namelist() if n.endswith("SKILL.md")]
                    if not names:
                        return {"ok": False, "error": "No SKILL.md found in package"}
                    skill_md = zf.read(names[0]).decode("utf-8")
            else:
                # Plain text SKILL.md (raw URL, no ZIP wrapper)
                skill_md = data.decode("utf-8")
        except Exception as exc:
            return {"ok": False, "error": f"Download failed: {exc}"}

    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

    entries = [e for e in load_installed() if e.get("id") != skill_id]
    entries.append({
        "id": skill_id,
        "version": version,
        "tier": tier,
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "has_tools": False,
    })
    save_installed(entries)
    return {"ok": True, "skill_id": skill_id}


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
