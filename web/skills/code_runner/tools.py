"""Sandboxed Python code execution — produces real output files."""

import ast
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import shared
from config import OUTPUTS_DIR, INSTALLED_SKILLS_DIR, USER_SKILL_DIRS, PLUGINS_DIR
from marketplace.installer import skill_id_for_cache_path as _skill_id_for_cache_path
from proc_utils import (
    no_window_kwargs,
    watched_output_dirs,
    snapshot_outputs,
    diff_outputs,
)

SKILL_ID = "code_runner"
SKILL_ALIASES = ["code-runner", "python-runner"]
# Foundational capability: general-purpose code execution must be visible on
# every turn, not gated behind skill selection/inference.
ALWAYS_ON = True

_BUILTIN_SKILLS_DIR = Path(__file__).parent.parent  # web/skills/


def _python_command(script_path: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--run-python", str(script_path)]
    return [sys.executable, "-X", "utf8", str(script_path)]


def _missing_packages(packages: list[str]) -> list[str]:
    from importlib.metadata import PackageNotFoundError, version
    from packaging.requirements import InvalidRequirement, Requirement

    missing = []
    for package in packages:
        try:
            requirement = Requirement(package)
            installed = version(requirement.name)
            if requirement.specifier and installed not in requirement.specifier:
                missing.append(package)
        except (InvalidRequirement, PackageNotFoundError):
            missing.append(package)
    return missing


def _find_skill_dir(skill_id: str) -> Path | None:
    """Locate a skill's directory across the known install/search locations.

    Flat roots (built-in skills, "mine" folder, USER_SKILL_DIRS) resolve by
    a simple root/skill_id join. Marketplace plugin bundles don't fit that
    shape — a bundled skill lives at
    PLUGINS_DIR/cache/{source}/{plugin_id}/{version}/[...]/{skill_dir} and
    registers under a namespaced id ("{plugin_id}__{relpath}", see
    marketplace.installer.namespaced_skill_id) — so when none of the flat
    candidates match, fall back to scanning the plugin cache for the
    SKILL.md whose namespaced id equals skill_id (finding #4, 2026-08-07
    milestone adversarial review).
    """
    if not skill_id:
        return None
    candidates = [
        _BUILTIN_SKILLS_DIR / skill_id,
        INSTALLED_SKILLS_DIR / "mine" / skill_id,
        *[root / skill_id for root in USER_SKILL_DIRS],
    ]
    found = next((p for p in candidates if p.is_dir()), None)
    if found is not None:
        return found

    cache_root = PLUGINS_DIR / "cache"
    if cache_root.is_dir():
        for skill_md in cache_root.rglob("SKILL.md"):
            if _skill_id_for_cache_path(cache_root, skill_md) == skill_id:
                return skill_md.parent
    return None


# --- AST: file deletion is hard-blocked — no HITL, no override ---
# Only qualified-call patterns are blocked. The previous bare-name check
# (._FUNCS) false-positived on list.remove(), lxml Element.remove(),
# python-pptx _p.remove(_r), and any other in-memory .remove()/.unlink()
# call (issue #76). Receiver type is unknowable from AST alone, so we
# require an explicit module-qualified call instead.
_DELETE_CALLS = {
    ("os", "remove"),
    ("os", "unlink"),
    ("os", "rmdir"),
    ("shutil", "rmtree"),
    ("shutil", "rmdir"),
}

# Path(...).unlink() / Path(...).rmdir() — receiver is a literal Path(...)
# call, so we can be sure this is filesystem-touching.
_PATH_DELETE_METHODS = {"unlink", "rmdir"}

# --- AST: other destructive ops that require HITL confirmation ---
_DESTRUCTIVE_CALLS = {
    ("os", "system"),
}

# Forensic logs written per run so the exact executed code + full stdout/stderr
# survive on disk after a timeout, crash, or server restart. Excluded from the
# `files` array returned to the model (they're for the user/dev, not outputs).
# Cleaned up with the run dir by cleanup_old_outputs() (24h retention).
_FORENSIC_FILES = {"code.py", "stdout.log", "stderr.log"}


def _write_forensic(path: Path, content: str) -> None:
    """Best-effort write of a forensic log file. Never raises — a logging
    failure must not mask the real tool result."""
    try:
        path.write_text(content, encoding="utf-8")
    except OSError:
        pass


def _forensic_paths(run_id: str, run_dir: Path) -> dict:
    """Absolute on-disk paths + download URLs for the per-run forensic logs.

    Included in every failure return so the model (and the user/dev) can read
    the FULL code + stderr, not just the stderr[:500] truncation carried in the
    error string. The model can read code.py / stderr.log from disk to
    self-correct instead of guessing from a truncated traceback.
    """
    return {
        "run_id": run_id,
        "code_path": str(run_dir / "code.py"),
        "stdout_path": str(run_dir / "stdout.log"),
        "stderr_path": str(run_dir / "stderr.log"),
        "code_url": f"/api/files/{run_id}/code.py",
        "stderr_url": f"/api/files/{run_id}/stderr.log",
    }


def _ast_scan(code: str) -> tuple[list, list]:
    """Return (blocked, flagged) lists. blocked = hard errors, flagged = HITL candidates."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return [], []

    blocked = []
    flagged = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                # Module-qualified: os.remove(), shutil.rmtree(), etc.
                if isinstance(func.value, ast.Name):
                    pair = (func.value.id, func.attr)
                    if pair in _DELETE_CALLS:
                        blocked.append(
                            f"Line {node.lineno}: {func.value.id}.{func.attr}()"
                        )
                    elif pair in _DESTRUCTIVE_CALLS:
                        flagged.append(
                            f"Line {node.lineno}: {func.value.id}.{func.attr}()"
                        )
                # Path(literal-or-expr).unlink() / .rmdir() — receiver is a
                # Path(...) Call, so this is genuinely filesystem-touching.
                if (
                    func.attr in _PATH_DELETE_METHODS
                    and isinstance(func.value, ast.Call)
                    and isinstance(func.value.func, ast.Name)
                    and func.value.func.id == "Path"
                ):
                    blocked.append(f"Line {node.lineno}: Path(...).{func.attr}()")
            # open(path, 'w') with a hardcoded path outside OUTPUT_DIR
            if isinstance(func, ast.Name) and func.id == "open":
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                    mode = str(node.args[1].value)
                    if any(m in mode for m in ("w", "a", "x")):
                        if len(node.args) >= 1 and isinstance(
                            node.args[0], ast.Constant
                        ):
                            path_val = str(node.args[0].value)
                            if "OUTPUT_DIR" not in path_val:
                                flagged.append(
                                    f"Line {node.lineno}: open('{path_val}', '{mode}')"
                                )
            # subprocess calls with shell=True
            if isinstance(func, ast.Attribute) and func.attr in (
                "run",
                "call",
                "Popen",
            ):
                for kw in node.keywords:
                    if (
                        kw.arg == "shell"
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value
                    ):
                        flagged.append(
                            f"Line {node.lineno}: subprocess.{func.attr}(shell=True)"
                        )
    return blocked, flagged


def _tool_run_python(
    code: str,
    skill_id: str = "",
    timeout: int = None,
    confirmed: bool = False,
    packages: list = None,
    _install_timeout: int = 120,
) -> dict:
    """Execute Python code in a sandboxed subprocess and return stdout and output files.

    Args:
        code: Python source to execute. OUTPUT_DIR variable is injected automatically.
        skill_id: The marketplace skill this runs under — used for tier lookup.
        timeout: Override timeout in seconds. Defaults to config value based on tier.
        confirmed: Set True to skip AST destructive-op check (user has approved).

    Returns:
        On success: {"stdout": str, "stderr": str, "files": [...], "runtime_ms": int, "error": null}
        On HITL required: {"hitl_required": True, "flagged_operations": [...], "message": str}
        On error: {"error": str, "stdout": str, "files": []}
    """
    from config import load_config

    cfg = load_config()

    tier = shared.TOOL_TIER_MAP.get(skill_id, "Verified")
    if timeout is None:
        key = (
            "code_runner_timeout_community"
            if tier == "Community"
            else "code_runner_timeout_verified"
        )
        timeout = int(cfg.get(key, 30 if tier == "Community" else 60))

    # On-the-fly pip install
    missing_packages = _missing_packages(packages or [])
    if missing_packages:
        if getattr(sys, "frozen", False):
            return {
                "error": (
                    "Package installation is not available in the packaged app. "
                    f"Missing packages: {missing_packages}."
                )
            }
        try:
            pip_result = subprocess.run(
                [sys.executable, "-m", "pip", "install"] + missing_packages,
                capture_output=True,
                timeout=_install_timeout,
                text=True,
                encoding="utf-8",
                **no_window_kwargs(),
            )
            if pip_result.returncode != 0:
                return {
                    "error": f"Failed to install {missing_packages}: {pip_result.stderr[:500]}"
                }
        except subprocess.TimeoutExpired:
            return {"error": f"Package install timed out after {_install_timeout}s."}

    # AST scan — blocked ops are always rejected; flagged ops require HITL (skipped if confirmed=True)
    blocked, flagged = _ast_scan(code)
    if blocked:
        return {
            "error": (
                "File deletion is not supported. The code contains delete operations: "
                + ", ".join(blocked)
                + ". Please ask the user to delete files manually."
            ),
        }
    if not confirmed and flagged:
        return {
            "hitl_required": True,
            "flagged_operations": flagged,
            "message": (
                "This code contains operations that could modify files outside the output folder. "
                "Review the flagged lines and re-call run_python with confirmed=True if you want to proceed. "
                "Always explain to the user what was flagged before re-calling."
            ),
        }

    # Create per-run output directory
    run_id = uuid4().hex[:12]
    run_dir = OUTPUTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    skill_dir = _find_skill_dir(skill_id)
    skill_dir_line = ""
    if skill_dir is not None:
        skill_dir_line = (
            f"SKILL_DIR = {str(skill_dir)!r}\n"
            f"import sys as _sys; _sys.path.insert(0, SKILL_DIR)\n"
        )
    preamble = (
        f"OUTPUT_DIR = {str(run_dir)!r}\n{skill_dir_line}from pathlib import Path\n"
    )
    full_code = preamble + code

    # Snapshot ~/Downloads so we can report files the code writes OUTSIDE its
    # OUTPUT_DIR (run_dir files are already returned via `files` below). This
    # surfaces e.g. a deck the code saved to Downloads instead of OUTPUT_DIR,
    # from disk rather than the model's memory (issue #87).
    _home = Path.home()
    _watch_dirs = [d for d in (_home / "Downloads",) if d.is_dir()]
    _before = snapshot_outputs(_watch_dirs)

    # Persist the exact executed code (preamble + user code) so the full script
    # is recoverable on disk after a timeout/crash/restart. Best-effort.
    _write_forensic(run_dir / "code.py", full_code)

    # Build the subprocess env. The sandbox cwd (run_dir) has no node_modules,
    # so node scripts run via run_python can't resolve globally-installed
    # packages (e.g. pptxgenjs, which the pptx skill's SKILL.md treats as
    # preinstalled). Set NODE_PATH to the global npm root so `require('pptxgenjs')`
    # works regardless of cwd. Best-effort: if the root can't be resolved, fall
    # back to the parent env unchanged.
    _subproc_env = os.environ.copy()
    _npm_root = None
    # Prefer `npm root -g` (authoritative), but on Windows npm is a .cmd shim
    # so subprocess.run needs shell=True to find it. Fall back to the well-known
    # %APPDATA%\npm\node_modules path if npm isn't invocable.
    try:
        import subprocess as _sp

        _npm_root = _sp.run(
            "npm root -g",
            capture_output=True,
            text=True,
            timeout=5,
            shell=True,
            **no_window_kwargs(),
        ).stdout.strip()
        if not _npm_root or not Path(_npm_root).is_dir():
            _npm_root = None
    except Exception:
        _npm_root = None
    if not _npm_root:
        _fallback = Path.home() / "AppData" / "Roaming" / "npm" / "node_modules"
        if _fallback.is_dir():
            _npm_root = str(_fallback)
    if _npm_root:
        _subproc_env["NODE_PATH"] = _npm_root

    start = time.monotonic()
    try:
        proc = subprocess.run(
            _python_command(run_dir / "code.py"),
            cwd=str(run_dir),
            capture_output=True,
            timeout=timeout,
            text=True,
            encoding="utf-8",
            env=_subproc_env,
            **no_window_kwargs(),
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""

        # Full stdout/stderr to disk (the tool result only carries stderr[:500]
        # back to the model; these logs keep the complete trace for forensics).
        _write_forensic(run_dir / "stdout.log", stdout)
        _write_forensic(run_dir / "stderr.log", stderr)

        import mimetypes as _mimetypes

        files = []
        for f in sorted(run_dir.iterdir()):
            if f.is_file() and f.name not in _FORENSIC_FILES:
                mime, _ = _mimetypes.guess_type(str(f))
                files.append(
                    {
                        "name": f.name,
                        "download_url": f"/api/files/{run_id}/{f.name}",
                        "size_bytes": f.stat().st_size,
                        "mime_type": mime or "application/octet-stream",
                    }
                )

        external_files = diff_outputs(_before, _watch_dirs)

        if proc.returncode != 0:
            result = {
                "error": f"Code exited with code {proc.returncode}. stderr: {stderr[:500]}",
                "stdout": stdout,
                "files": files,
                "runtime_ms": elapsed_ms,
                "forensic": _forensic_paths(run_id, run_dir),
            }
            if external_files:
                result["output_files"] = external_files
            return result

        result = {
            "stdout": stdout,
            "stderr": stderr,
            "files": files,
            "runtime_ms": elapsed_ms,
            "error": None,
        }
        if external_files:
            result["output_files"] = external_files
        return result

    except subprocess.TimeoutExpired as te:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        # On timeout the subprocess is killed; partial stdout/stderr (if any)
        # are captured on the exception object. Persist them so the partial
        # output is recoverable — the returned error string carries no output.
        _stdout = te.stdout if isinstance(te.stdout, str) else ""
        _stderr = te.stderr if isinstance(te.stderr, str) else ""
        _write_forensic(run_dir / "stdout.log", _stdout)
        _write_forensic(run_dir / "stderr.log", _stderr)
        return {
            "error": f"Code execution timed out after {timeout}s.",
            "stdout": "",
            "files": [],
            "runtime_ms": elapsed_ms,
            "forensic": _forensic_paths(run_id, run_dir),
        }
    except Exception as exc:
        _write_forensic(run_dir / "stderr.log", f"runner exception: {exc}")
        return {
            "error": str(exc),
            "stdout": "",
            "files": [],
            "forensic": _forensic_paths(run_id, run_dir),
        }


TOOL_DEFS = [
    {
        "name": "run_python",
        "description": (
            "Execute Python code in a sandboxed subprocess. "
            "OUTPUT_DIR is injected automatically — write all output files there. "
            "Returns stdout and a list of output files with download URLs. "
            "If the code contains destructive operations outside OUTPUT_DIR, returns hitl_required=True "
            "with flagged_operations — show these to the user and re-call with confirmed=True if they approve."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute. Use OUTPUT_DIR variable for all file writes.",
                },
                "skill_id": {
                    "type": "string",
                    "description": "Skill context for sandbox tier (optional, e.g. 'slack-gif-creator')",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Override execution timeout in seconds (optional)",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "Set True to skip AST destructive-op check after user has approved flagged operations",
                },
                "packages": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "pip package names to install before running (optional, e.g. ['pandas', 'requests']). Already-installed packages are a no-op.",
                },
            },
            "required": ["code"],
        },
    }
]

TOOL_STATUS = {
    "run_python": "Running code...",
}

TOOL_HANDLERS = {
    "run_python": _tool_run_python,
}
