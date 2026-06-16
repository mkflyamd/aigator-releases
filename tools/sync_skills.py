#!/usr/bin/env python3
"""Skill sync tool — install and update skills from any git repo.

Usage:
    python sync_skills.py --check --repo <git-url>
    python sync_skills.py --sync --repo <git-url>
    python sync_skills.py --sync <skill> [<skill>...] --repo <git-url>
    python sync_skills.py --sync <skill> --upstream-dir /path/to/repo
"""

import argparse
import filecmp
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent
SKILLS_DIR = ROOT / "web" / "skills"

# Skills that exist only locally — never touched during sync
LOCAL_ONLY_SKILLS = frozenset({
    "aigator",
    "atlassian",
    "excel_skill",
    "ppt_skill",
    "slack",
})

# Files that must never be overwritten by upstream
PROTECTED_FILES = frozenset({
    "web/skills/m365-email/graph_client.py",
    "web/skills/m365-email/auth.py",
    "web/skills/m365-email/scripts/graph_client.py",
    "web/skills/m365-calendar/scripts/graph_client.py",
    "web/skills/m365-contacts/scripts/graph_client.py",
    "web/skills/m365-onedrive/scripts/graph_client.py",
    "web/skills/m365-onenote/scripts/graph_client.py",
    "web/skills/m365-people/scripts/graph_client.py",
    "web/skills/m365-planner/scripts/graph_client.py",
    "web/skills/m365-sharepoint/scripts/graph_client.py",
    "web/skills/m365-teams/scripts/graph_client.py",
})

SKIP_PATTERNS = {"__pycache__", ".pyc", ".pyo", ".git"}

# Stored hash of last-synced upstream graph_client.py
GC_HASH_FILE = SKILLS_DIR / ".upstream_gc_hash"

WRAPPER_SELF = '''\
"""Thin wrapper -- delegates to the canonical GraphClient in skills/m365-email/."""
import importlib.util
from pathlib import Path

_canonical = Path(__file__).parent.parent / "graph_client.py"
_spec = importlib.util.spec_from_file_location("_gc_canonical", str(_canonical))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

GraphClient = _mod.GraphClient
GRAPH_BASE = _mod.GRAPH_BASE
DEFAULT_CLIENT_ID = _mod.DEFAULT_CLIENT_ID
DEFAULT_SCOPES = _mod.DEFAULT_SCOPES
TOKEN_FILE = _mod.TOKEN_FILE
'''

WRAPPER_SIBLING = '''\
"""Thin wrapper -- delegates to the canonical GraphClient in skills/m365-email/."""
import importlib.util
from pathlib import Path

_canonical = Path(__file__).parent.parent.parent / "m365-email" / "graph_client.py"
_spec = importlib.util.spec_from_file_location("_gc_canonical", str(_canonical))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

GraphClient = _mod.GraphClient
GRAPH_BASE = _mod.GRAPH_BASE
DEFAULT_CLIENT_ID = _mod.DEFAULT_CLIENT_ID
DEFAULT_SCOPES = _mod.DEFAULT_SCOPES
TOKEN_FILE = _mod.TOKEN_FILE
'''


# ── Helpers ─────────────────────────────────────────────────

def parse_version(skill_md: Path) -> str:
    """Extract version from SKILL.md YAML frontmatter."""
    if not skill_md.exists():
        return ""
    text = skill_md.read_text(errors="replace")
    m = re.search(r'version:\s*["\']?(\d[\d.]*)["\']?', text)
    return m.group(1) if m else ""


def version_tuple(ver: str) -> tuple:
    """Convert version string to comparable tuple."""
    if not ver:
        return (0,)
    try:
        return tuple(int(x) for x in ver.split("."))
    except ValueError:
        return (0,)


def discover_skills(skills_dir: Path) -> set:
    """Find subdirectories that contain a SKILL.md."""
    if not skills_dir.exists():
        return set()
    return {
        d.name for d in skills_dir.iterdir()
        if d.is_dir() and (d / "SKILL.md").exists()
    }


def clone_upstream(repo_url: str, tmp_dir: Path) -> Path:
    """Shallow-clone a git repo, return path to its skills/ directory."""
    print(f"Cloning {repo_url} ...")
    result = subprocess.run(
        ["git", "clone", "--depth", "1", "--single-branch", str(repo_url), str(tmp_dir)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: git clone failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    # Find the skills directory — could be at root/skills/ or root/ itself
    candidate = tmp_dir / "skills"
    if candidate.exists():
        return candidate
    # Maybe the repo IS the skills directory
    if any((tmp_dir / d / "SKILL.md").exists() for d in tmp_dir.iterdir() if d.is_dir()):
        return tmp_dir
    print("ERROR: Could not find skills/ directory in the repo.", file=sys.stderr)
    sys.exit(1)


def _is_protected(skill_name: str, rel_path: str) -> bool:
    """Check if a file path is in the protected set."""
    full_rel = f"web/skills/{skill_name}/{rel_path}"
    return full_rel.replace("\\", "/") in PROTECTED_FILES


def _should_skip(path: Path) -> bool:
    """Check if a path component matches skip patterns."""
    return any(part in SKIP_PATTERNS for part in path.parts)


def restore_wrappers(skill_name: str):
    """Re-write thin wrapper graph_client.py for m365-* skills."""
    if not skill_name.startswith("m365-"):
        return
    gc_path = SKILLS_DIR / skill_name / "scripts" / "graph_client.py"
    if not gc_path.parent.exists():
        return
    if skill_name == "m365-email":
        gc_path.write_text(WRAPPER_SELF)
    else:
        gc_path.write_text(WRAPPER_SIBLING)


def check_upstream_graph_client(upstream_dir: Path, update_hash: bool = False) -> bool:
    """Check if upstream graph_client.py changed since last sync. Returns True if changed."""
    # Find any upstream m365-* graph_client.py (they're all identical in Trung's repo)
    upstream_gc = None
    for d in sorted(upstream_dir.iterdir()):
        candidate = d / "scripts" / "graph_client.py"
        if d.name.startswith("m365-") and candidate.exists():
            upstream_gc = candidate
            break
    if not upstream_gc:
        return False

    current_hash = hashlib.sha256(upstream_gc.read_bytes()).hexdigest()
    stored_hash = GC_HASH_FILE.read_text().strip() if GC_HASH_FILE.exists() else ""

    changed = current_hash != stored_hash
    if update_hash:
        GC_HASH_FILE.write_text(current_hash)
    return changed


# ── Compare ─────────────────────────────────────────────────

def compare_skills(upstream_dir: Path) -> dict:
    """Compare local vs upstream skills."""
    local_skills = discover_skills(SKILLS_DIR)
    upstream_skills = discover_skills(upstream_dir)

    shared = local_skills & upstream_skills
    new_upstream = upstream_skills - local_skills
    local_only = local_skills - upstream_skills

    outdated = []
    up_to_date = []
    no_version = []

    for name in sorted(shared):
        if name in LOCAL_ONLY_SKILLS:
            continue
        local_ver = parse_version(SKILLS_DIR / name / "SKILL.md")
        upstream_ver = parse_version(upstream_dir / name / "SKILL.md")
        if not local_ver and not upstream_ver:
            no_version.append(name)
        elif version_tuple(upstream_ver) > version_tuple(local_ver):
            outdated.append({"name": name, "local": local_ver or "?", "upstream": upstream_ver})
        else:
            up_to_date.append(name)

    return {
        "outdated": outdated,
        "new_upstream": sorted(new_upstream),
        "up_to_date": up_to_date,
        "local_only": sorted(n for n in local_only if n not in LOCAL_ONLY_SKILLS),
        "no_version": no_version,
    }


# ── Sync ────────────────────────────────────────────────────

def sync_skill(skill_name: str, upstream_dir: Path) -> dict:
    """Sync a single skill from upstream. Returns action log."""
    src = upstream_dir / skill_name
    dst = SKILLS_DIR / skill_name

    if not src.exists():
        return {"error": f"Skill '{skill_name}' not found in upstream"}

    if skill_name in LOCAL_ONLY_SKILLS:
        return {"error": f"Skill '{skill_name}' is local-only and cannot be synced"}

    local_ver = parse_version(SKILLS_DIR / skill_name / "SKILL.md") if dst.exists() else "(new)"
    upstream_ver = parse_version(src / "SKILL.md")

    updated = []
    added = []
    skipped = []

    for src_file in sorted(src.rglob("*")):
        if not src_file.is_file():
            continue
        rel = src_file.relative_to(src)
        if _should_skip(rel):
            continue
        rel_str = str(rel).replace("\\", "/")

        if _is_protected(skill_name, rel_str):
            skipped.append(rel_str)
            continue

        dst_file = dst / rel
        dst_file.parent.mkdir(parents=True, exist_ok=True)

        if dst_file.exists():
            if filecmp.cmp(str(src_file), str(dst_file), shallow=False):
                continue  # identical
            shutil.copy2(str(src_file), str(dst_file))
            updated.append(rel_str)
        else:
            shutil.copy2(str(src_file), str(dst_file))
            added.append(rel_str)

    # Safety net: restore wrappers for m365 skills
    restore_wrappers(skill_name)

    return {
        "name": skill_name,
        "local_ver": local_ver,
        "upstream_ver": upstream_ver,
        "updated": updated,
        "added": added,
        "skipped": skipped,
    }


# ── Output ──────────────────────────────────────────────────

def print_check_report(report: dict):
    """Pretty-print the comparison report."""
    outdated = report["outdated"]
    new = report["new_upstream"]
    up = report["up_to_date"]

    if outdated:
        print(f"\nOUTDATED ({len(outdated)} skills need update):")
        print(f"  {'Skill':<30} {'Local':<10} {'Upstream':<10}")
        print(f"  {'-'*30} {'-'*10} {'-'*10}")
        for s in outdated:
            print(f"  {s['name']:<30} {s['local']:<10} {s['upstream']:<10}")
    else:
        print("\nAll shared skills are up to date.")

    if new:
        print(f"\nNEW (available to install):")
        for n in new:
            ver = ""
            print(f"  {n}")

    if up:
        print(f"\nUP TO DATE: {len(up)} skills")

    if report["local_only"]:
        print(f"\nLOCAL-ONLY (not in upstream): {', '.join(report['local_only'])}")

    print()


def print_sync_result(result: dict):
    """Print sync result for a single skill."""
    if "error" in result:
        print(f"  ERROR: {result['error']}")
        return

    name = result["name"]
    lv = result["local_ver"]
    uv = result["upstream_ver"]
    label = f"[{name}] {lv} -> {uv}" if lv != "(new)" else f"[{name}] (new install) v{uv}"
    print(f"\n{label}")

    for f in result["updated"]:
        print(f"  Updated: {f}")
    for f in result["added"]:
        print(f"  Added:   {f}")
    for f in result["skipped"]:
        print(f"  Protected (kept local): {f}")

    total = len(result["updated"]) + len(result["added"])
    if total == 0 and not result["skipped"]:
        print("  (no changes)")


# ── Main ────────────────────────────────────────────────────

def _rm_readonly(func, path, _exc_info):
    """Handle read-only files on Windows during rmtree."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def main():
    parser = argparse.ArgumentParser(
        description="Install and update skills from any git repo.",
        epilog="Examples:\n"
               "  python sync_skills.py --check --repo https://gitenterprise.xilinx.com/trungt/embeddedsw-skills\n"
               "  python sync_skills.py --sync --repo https://gitenterprise.xilinx.com/trungt/embeddedsw-skills\n"
               "  python sync_skills.py --sync zephyr --repo https://gitenterprise.xilinx.com/trungt/embeddedsw-skills\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="Show what's outdated or new (dry run)")
    group.add_argument("--sync", action="store_true", help="Install or update skills")
    parser.add_argument("skills", nargs="*", help="Specific skill names to sync (omit for all outdated)")
    parser.add_argument("--repo", help="Git repo URL containing a skills/ directory")
    parser.add_argument("--upstream-dir", help="Path to a local repo (skips git clone)")

    args = parser.parse_args()

    if not args.repo and not args.upstream_dir:
        parser.error("Provide --repo <git-url> or --upstream-dir <path>")

    tmp_dir = None
    try:
        # Resolve upstream skills directory
        if args.upstream_dir:
            upstream_base = Path(args.upstream_dir)
            upstream_dir = upstream_base / "skills" if (upstream_base / "skills").exists() else upstream_base
        else:
            tmp_dir = Path(tempfile.mkdtemp(prefix="skill_sync_"))
            upstream_dir = clone_upstream(args.repo, tmp_dir)

        if args.check:
            report = compare_skills(upstream_dir)
            print(f"\nSkill Sync Check")
            print(f"{'='*50}")
            if args.repo:
                print(f"Source: {args.repo}")
            else:
                print(f"Source: {args.upstream_dir}")
            print_check_report(report)

            if check_upstream_graph_client(upstream_dir):
                print("  *** WARNING: upstream graph_client.py has changed! ***")
                print("  Our copy has local enhancements (thin wrappers, extra_headers, put_binary).")
                print("  Ask Claude to merge upstream changes into skills/m365-email/graph_client.py")
                print()

        elif args.sync:
            if args.skills:
                # Sync specific skills
                skill_names = args.skills
            else:
                # Sync all outdated
                report = compare_skills(upstream_dir)
                skill_names = [s["name"] for s in report["outdated"]]
                if not skill_names:
                    print("Everything is up to date. Nothing to sync.")
                    return

            print(f"Syncing {len(skill_names)} skill(s)...")
            total_updated = 0
            total_added = 0
            total_skipped = 0

            for name in skill_names:
                result = sync_skill(name, upstream_dir)
                print_sync_result(result)
                if "error" not in result:
                    total_updated += len(result["updated"])
                    total_added += len(result["added"])
                    total_skipped += len(result["skipped"])

            print(f"\nDone: {total_updated} updated, {total_added} added, {total_skipped} protected")

            # Check if upstream graph_client.py changed and warn
            gc_changed = check_upstream_graph_client(upstream_dir, update_hash=True)
            if gc_changed:
                print()
                print("  *** WARNING: upstream graph_client.py has changed! ***")
                print("  Our copy has local enhancements (thin wrappers, extra_headers, put_binary).")
                print("  Ask Claude to merge upstream changes into skills/m365-email/graph_client.py")
                print()

    finally:
        if tmp_dir and tmp_dir.exists():
            shutil.rmtree(str(tmp_dir), onerror=_rm_readonly)


if __name__ == "__main__":
    main()
