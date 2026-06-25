"""Sandboxed Python code execution — produces real output files."""

import ast
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import shared
from config import OUTPUTS_DIR, INSTALLED_SKILLS_DIR, AGENTS_SKILLS_DIR
from proc_utils import no_window_kwargs, watched_output_dirs, snapshot_outputs, diff_outputs

SKILL_ID = "code_runner"
SKILL_ALIASES = ["code-runner", "python-runner"]
# Foundational capability: general-purpose code execution must be visible on
# every turn, not gated behind skill selection/inference.
ALWAYS_ON = True

_BUILTIN_SKILLS_DIR = Path(__file__).parent.parent  # web/skills/


def _find_skill_dir(skill_id: str) -> Path | None:
    """Locate a skill's directory across the known install/search locations."""
    if not skill_id:
        return None
    candidates = [
        _BUILTIN_SKILLS_DIR / skill_id,
        INSTALLED_SKILLS_DIR / "mine" / skill_id,
        INSTALLED_SKILLS_DIR / skill_id,
        AGENTS_SKILLS_DIR / skill_id,
    ]
    return next((p for p in candidates if p.is_dir()), None)

# --- AST: file deletion is hard-blocked — no HITL, no override ---
# Only qualified-call patterns are blocked. The previous bare-name check
# (._FUNCS) false-positived on list.remove(), lxml Element.remove(),
# python-pptx _p.remove(_r), and any other in-memory .remove()/.unlink()
# call (issue #76). Receiver type is unknowable from AST alone, so we
# require an explicit module-qualified call instead.
_DELETE_CALLS = {
    ("os", "remove"), ("os", "unlink"), ("os", "rmdir"),
    ("shutil", "rmtree"), ("shutil", "rmdir"),
}

# Path(...).unlink() / Path(...).rmdir() — receiver is a literal Path(...)
# call, so we can be sure this is filesystem-touching.
_PATH_DELETE_METHODS = {"unlink", "rmdir"}

# --- AST: other destructive ops that require HITL confirmation ---
_DESTRUCTIVE_CALLS = {
    ("os", "system"),
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
                        blocked.append(f"Line {node.lineno}: {func.value.id}.{func.attr}()")
                    elif pair in _DESTRUCTIVE_CALLS:
                        flagged.append(f"Line {node.lineno}: {func.value.id}.{func.attr}()")
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
                        if len(node.args) >= 1 and isinstance(node.args[0], ast.Constant):
                            path_val = str(node.args[0].value)
                            if "OUTPUT_DIR" not in path_val:
                                flagged.append(f"Line {node.lineno}: open('{path_val}', '{mode}')")
            # subprocess calls with shell=True
            if isinstance(func, ast.Attribute) and func.attr in ("run", "call", "Popen"):
                for kw in node.keywords:
                    if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value:
                        flagged.append(f"Line {node.lineno}: subprocess.{func.attr}(shell=True)")
    return blocked, flagged


def _tool_run_python(code: str, skill_id: str = "", timeout: int = None, confirmed: bool = False,
                     packages: list = None, _install_timeout: int = 120) -> dict:
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
        key = "code_runner_timeout_community" if tier == "Community" else "code_runner_timeout_verified"
        timeout = int(cfg.get(key, 30 if tier == "Community" else 60))

    # On-the-fly pip install
    if packages:
        try:
            pip_result = subprocess.run(
                [sys.executable, "-m", "pip", "install"] + packages,
                capture_output=True,
                timeout=_install_timeout,
                text=True,
                encoding="utf-8",
                **no_window_kwargs(),
            )
            if pip_result.returncode != 0:
                return {"error": f"Failed to install {packages}: {pip_result.stderr[:500]}"}
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
        f"OUTPUT_DIR = {str(run_dir)!r}\n"
        f"{skill_dir_line}"
        "from pathlib import Path\n"
    )
    full_code = preamble + code

    # Snapshot ~/Downloads so we can report files the code writes OUTSIDE its
    # OUTPUT_DIR (run_dir files are already returned via `files` below). This
    # surfaces e.g. a deck the code saved to Downloads instead of OUTPUT_DIR,
    # from disk rather than the model's memory (issue #87).
    _home = Path.home()
    _watch_dirs = [d for d in (_home / "Downloads",) if d.is_dir()]
    _before = snapshot_outputs(_watch_dirs)

    start = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", "-c", full_code],
            cwd=str(run_dir),
            capture_output=True,
            timeout=timeout,
            text=True,
            encoding="utf-8",
            **no_window_kwargs(),
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""

        import mimetypes as _mimetypes
        files = []
        for f in sorted(run_dir.iterdir()):
            if f.is_file():
                mime, _ = _mimetypes.guess_type(str(f))
                files.append({
                    "name": f.name,
                    "download_url": f"/api/files/{run_id}/{f.name}",
                    "size_bytes": f.stat().st_size,
                    "mime_type": mime or "application/octet-stream",
                })

        external_files = diff_outputs(_before, _watch_dirs)

        if proc.returncode != 0:
            result = {
                "error": f"Code exited with code {proc.returncode}. stderr: {stderr[:500]}",
                "stdout": stdout,
                "files": files,
                "runtime_ms": elapsed_ms,
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

    except subprocess.TimeoutExpired:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {
            "error": f"Code execution timed out after {timeout}s.",
            "stdout": "",
            "files": [],
            "runtime_ms": elapsed_ms,
        }
    except Exception as exc:
        return {"error": str(exc), "stdout": "", "files": []}


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
