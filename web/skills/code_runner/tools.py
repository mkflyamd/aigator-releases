"""Sandboxed Python code execution — produces real output files."""

import ast
import os
import re
import shutil
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
import sandbox
from sandbox import approvals as sandbox_approvals
from sandbox import task_grants
from sandbox.paths import HOME_DENY, PathNotGrantable, is_within, normalize_grant_paths, normalize_hosts
from sandbox.policy import load_policy

SKILL_ID = "code_runner"
SKILL_ALIASES = ["code-runner", "python-runner"]
# Foundational capability: general-purpose code execution must be visible on
# every turn, not gated behind skill selection/inference.
ALWAYS_ON = True

_BUILTIN_SKILLS_DIR = Path(__file__).parent.parent  # web/skills/
_PACKAGE_IMPORT_ALIASES = {
    "beautifulsoup4": ("bs4",),
    "pillow": ("PIL",),
    "python-docx": ("docx",),
    "python-pptx": ("pptx",),
    "pyyaml": ("yaml",),
    "scikit-learn": ("sklearn",),
    "opencv-python": ("cv2",),
}


def _python_command(script_path: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--run-python", str(script_path)]
    return [sys.executable, "-X", "utf8", str(script_path)]


def _missing_packages(packages: list[str]) -> list[str]:
    from importlib import util
    from importlib.metadata import PackageNotFoundError, version
    from packaging.requirements import InvalidRequirement, Requirement

    missing = []
    for package in packages:
        try:
            requirement = Requirement(package)
        except InvalidRequirement:
            missing.append(package)
            continue
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            installed = version(requirement.name)
        except PackageNotFoundError:
            normalized_name = re.sub(r"[-.]", "_", requirement.name.lower())
            import_names = _PACKAGE_IMPORT_ALIASES.get(
                requirement.name.lower(), (normalized_name,)
            )
            try:
                importable = any(util.find_spec(name) is not None for name in import_names)
            except (ImportError, AttributeError, ValueError):
                importable = False
            if not importable:
                missing.append(package)
            continue
        if requirement.specifier and installed not in requirement.specifier:
            missing.append(package)
    return missing


# No trailing "." (Windows strips it, so "skill." would name the "skill" folder); no spaces.
_SKILL_ID_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9_-])?")


def _valid_skill_id(skill_id) -> bool:
    """A plain skill name: no path separators, drive colon, NUL or traversal."""
    return isinstance(skill_id, str) and bool(_SKILL_ID_RE.fullmatch(skill_id)) and ".." not in skill_id


def _in_skill_roots(path: Path) -> bool:
    roots = [_BUILTIN_SKILLS_DIR, INSTALLED_SKILLS_DIR / "mine", *USER_SKILL_DIRS, PLUGINS_DIR / "cache"]
    try:
        resolved = Path(path).resolve()
        return any(is_within(resolved, Path(root).resolve()) for root in roots)
    except (OSError, RuntimeError, ValueError):
        return False


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
    if not skill_id or not _valid_skill_id(skill_id):
        return None
    candidates = [
        _BUILTIN_SKILLS_DIR / skill_id,
        INSTALLED_SKILLS_DIR / "mine" / skill_id,
        *[root / skill_id for root in USER_SKILL_DIRS],
    ]
    found = next((p for p in candidates if p.is_dir()), None)
    if found is None:
        cache_root = PLUGINS_DIR / "cache"
        if cache_root.is_dir():
            for skill_md in cache_root.rglob("SKILL.md"):
                if _skill_id_for_cache_path(cache_root, skill_md) == skill_id:
                    found = skill_md.parent
                    break
    # The folder is handed to the sandbox as readable, so it must really live in a skill root
    # (symlinks resolved), never wherever a crafted id or a symlink points.
    if found is not None and _in_skill_roots(found):
        return found
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


# --- OS sandbox (docs/superpowers/specs/2026-10-05-code-runner-sandbox-design.md) ---

_SANDBOX_HINT = (
    "[sandbox] This code can only use its own OUTPUT_DIR and has no network. If the task really "
    "needs more, re-call run_python with extra_read_paths, extra_write_paths or network_hosts; "
    "the user will be asked to approve."
)
_PERMISSION_PATTERNS = re.compile(
    r"PermissionError|Permission denied|Access is denied|EACCES|EPERM|Operation not permitted|"
    r"WinError 5\b|WinError 10013|Network is unreachable|ENETUNREACH|getaddrinfo failed|"
    r"Temporary failure in name resolution|Name or service not known|nodename nor servname",
    re.IGNORECASE,
)
_DISABLED_MSG = "Code execution is disabled on this computer by the administrator's AI Gator policy."
_NETWORK_REFUSED_MSG = (
    "Network access for code is blocked by the administrator's AI Gator policy. "
    "Do not retry with network_hosts."
)
_FS_REFUSED_MSG = (
    "Access to folders outside OUTPUT_DIR is blocked by the administrator's AI Gator policy. "
    "Do not retry with extra paths; work only inside OUTPUT_DIR."
)
_DENIED_MSG = (
    "The user denied this access request. Do not retry it; continue without that access "
    "or ask the user what to do."
)
_EXPIRED_MSG = (
    "This access approval expired (approvals last 10 minutes). Do not retry automatically; "
    "ask the user whether to request the access again."
)
_APPROVAL_MSG = (
    "The user must approve this access first; an approval card is now shown in the chat. Tell the "
    "user briefly what access you asked for and why, then stop and wait. When the user says they "
    "approved, call run_python again with exactly the same code, extra_read_paths, "
    "extra_write_paths and network_hosts. If they deny, do not retry."
)
_RUN_ERROR_MSG = (
    "The code sandbox failed while the code may have been running, and AI Gator did not run it "
    "again. Tell the user; do not retry automatically."
)


def _unavailable_message(reason: str | None) -> str:
    return (
        "Code cannot run because the code sandbox is unavailable on this computer. "
        f"{reason or ''} Tell the user; details are in Settings under Code sandbox."
    ).replace("  ", " ")


def _sandbox_mode(cfg: dict, policy) -> tuple[str, str | None]:
    """('enforced', None), ('off', None) or ('unavailable', reason).

    The opt-out applies only when the sandbox cannot run and the policy does
    not require it; a working sandbox is always used."""
    if sandbox.sandbox_level() == "enforced":
        return "enforced", None
    reason = sandbox.sandbox_unavailable_reason() or "The sandbox is unavailable."
    if cfg.get("code_runner_sandbox") == "off" and not policy.require_sandbox:
        return "off", None
    return "unavailable", reason


def _with_sandbox_hint(stderr: str) -> str:
    if stderr and _PERMISSION_PATTERNS.search(stderr):
        return stderr.rstrip("\n") + "\n" + _SANDBOX_HINT + "\n"
    return stderr


def _runtime_paths(skill_dir: Path | None, npm_root: str | None) -> list[Path]:
    """Read+execute paths the sandboxed process needs (interpreter, libraries, skill folder, Node)."""
    import site

    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent)
    else:
        candidates += [Path(sys.base_prefix), Path(sys.prefix), Path(sys.executable).resolve().parent]
        try:
            candidates += [Path(p) for p in site.getsitepackages()]
        except AttributeError:
            pass
        if site.ENABLE_USER_SITE:
            candidates.append(Path(site.getusersitepackages()))
    node = shutil.which("node")
    if node:
        candidates.append(Path(node).resolve().parent)
    if npm_root:
        candidates.append(Path(npm_root))
    if skill_dir is not None:
        candidates.append(Path(skill_dir))
    kept: list[Path] = []
    for path in sorted({p.resolve() for p in candidates if p.exists()}, key=lambda p: len(str(p))):
        if not any(is_within(path, k) for k in kept):
            kept.append(path)
    return kept


def _check_requested_access(extra_read_paths, extra_write_paths, network_hosts, policy):
    """Normalize the model's requested access and apply the admin policy and the
    never-grantable list. Runs in every mode, so an opt-out cannot dodge them.

    Returns a refusal result dict, or (read_paths, write_paths, hosts)."""
    try:
        read_paths = normalize_grant_paths(extra_read_paths)
        write_paths = normalize_grant_paths(extra_write_paths)
        hosts = normalize_hosts(network_hosts)
    except (PathNotGrantable, ValueError) as exc:
        return {"error": f"{exc} Do not retry with this value."}
    if hosts and policy.network == "deny":
        return {"error": _NETWORK_REFUSED_MSG}
    if (read_paths or write_paths) and policy.filesystem == "strict":
        return {"error": _FS_REFUSED_MSG}
    return read_paths, write_paths, hosts


def _approval_gate(read_paths, write_paths, hosts, context_id: str, skill_id: str):
    """Return a result dict to send back (approval_required or a decision error), or
    (read_paths, write_paths, hosts, approval) to run with.

    An approval exists only if the user decided it through the CSRF-guarded
    route (sandbox/approvals.py); nothing the model passes can create one."""
    if not (read_paths or write_paths or hosts):
        return read_paths, write_paths, hosts, None

    read_s, write_s = [str(p) for p in read_paths], [str(p) for p in write_paths]

    def telemetry(decision: str) -> dict:
        return sandbox.telemetry_record("", skill_id, "enforced", bool(hosts), len(read_paths), len(write_paths), decision)

    context_id = context_id or "default"
    status, req = sandbox_approvals.lookup(context_id, read_s, write_s, hosts, tool="run_python")
    if status == "approved":
        return read_paths, write_paths, hosts, "task_approved" if req.scope == "task" else "approved"
    if status == "denied":
        return {"error": _DENIED_MSG, "_sandbox_telemetry": telemetry("denied")}
    if status == "expired":
        return {"error": _EXPIRED_MSG, "_sandbox_telemetry": telemetry("expired")}
    if task_grants.covers(context_id, read_s, write_s, hosts):
        return read_paths, write_paths, hosts, "task_approved"
    if req is None:
        req = sandbox_approvals.create(context_id, read_s, write_s, hosts)
    card = {
        "request_id": req.id,
        "read_paths": list(req.read_paths),
        "write_paths": list(req.write_paths),
        "network_hosts": list(req.network_hosts),
        "context_id": req.context_id,
    }
    return {
        "approval_required": True,
        "request_id": req.id,
        "read_paths": card["read_paths"],
        "write_paths": card["write_paths"],
        "network_hosts": card["network_hosts"],
        "message": _APPROVAL_MSG,
        "_sandbox_approval": card,
        "_sandbox_telemetry": telemetry("requested"),
    }


_PKG_SPEC = r"(?:===|==|~=|!=|>=|<=|>|<)[A-Za-z0-9.*+!_-]+"
_PLAIN_REQUIREMENT_RE = re.compile(
    rf"[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9._,-]+\])?(?:{_PKG_SPEC}(?:,{_PKG_SPEC})*)?"
)


_ARCHIVE_SUFFIXES = (".whl", ".zip", ".tar.gz", ".tgz", ".tar.bz2")


def _packages_are_plain(packages) -> bool:
    """Only `name[extras]specifiers` strings: no URLs, paths, options or markers.

    pip runs in the server process with the full environment, so a model-chosen
    string must never be able to become a pip option or a non-index source
    (a name ending in .whl/.zip/.tar.gz/... is read by pip as a local file)."""
    return isinstance(packages, list) and all(
        isinstance(p, str)
        and _PLAIN_REQUIREMENT_RE.fullmatch(p)
        and not p.lower().endswith(_ARCHIVE_SUFFIXES)
        for p in packages
    )


def _runtime_path_refused(path: Path | None) -> bool:
    """Backstop for the folders added to the sandbox's read+execute set (skill folder, npm root):
    never a drive root, the home folder or an ancestor of it, or a protected home location.
    Subfolders of ~/.gator (installed skills) are fine; ~/.gator itself is not."""
    if path is None:
        return False
    try:
        path = Path(path).resolve()
        home = Path.home().resolve()
        if path.parent == path or is_within(home, path):
            return True
        protected = [home / ".gator", *(home / d for d in HOME_DENY)]
        for entry in protected:
            for form in {entry, entry.resolve()}:
                if is_within(form, path) or (entry.name != ".gator" and is_within(path, form)):
                    return True
    except (OSError, RuntimeError, ValueError):
        return True
    return False


def _install_packages(packages: list, install_timeout: int) -> dict | None:
    """pip-install missing packages; an error result, or None when all is installed.

    Runs unsandboxed in the server process (known gap, tracked separately)."""
    missing_packages = _missing_packages(packages or [])
    if not missing_packages:
        return None
    # "--" and --no-input: a requirement string can never be read as a pip option or prompt.
    pip_cmd = [sys.executable, "-m", "pip", "install", "--no-input", "--"] + missing_packages
    try:
        pip_result = subprocess.run(
            pip_cmd,
            capture_output=True,
            timeout=install_timeout,
            text=True,
            encoding="utf-8",
            **no_window_kwargs(),
        )
        if pip_result.returncode != 0 and "No module named pip" in pip_result.stderr:
            # Some interpreters (e.g. uv-managed venvs, which omit pip by
            # default for faster installs) have no pip at all. Bootstrap
            # it from the stdlib bundle rather than failing every install.
            subprocess.run(
                [sys.executable, "-m", "ensurepip", "--default-pip"],
                capture_output=True, timeout=install_timeout, text=True,
                encoding="utf-8", **no_window_kwargs(),
            )
            pip_result = subprocess.run(
                pip_cmd,
                capture_output=True,
                timeout=install_timeout,
                text=True,
                encoding="utf-8",
                **no_window_kwargs(),
            )
        if pip_result.returncode != 0:
            return {"error": f"Failed to install {missing_packages}: {pip_result.stderr[:500]}"}
    except subprocess.TimeoutExpired:
        return {"error": f"Package install timed out after {install_timeout}s."}
    return None


def _tool_run_python(
    code: str,
    skill_id: str = "",
    timeout: int = None,
    confirmed: bool = False,
    packages: list = None,
    extra_read_paths: list = None,
    extra_write_paths: list = None,
    network_hosts: list = None,
    _install_timeout: int = 120,
    _context_id: str = "",
) -> dict:
    """Execute Python code in an OS sandbox and return stdout and output files.

    Args:
        code: Python source to execute. OUTPUT_DIR variable is injected automatically.
        skill_id: The marketplace skill this runs under — used for tier lookup and SKILL_DIR.
        timeout: Override timeout in seconds. Defaults to config value based on tier.
        confirmed: Set True to skip AST destructive-op check (user has approved).
            Has no effect on sandbox access: only a user decision made in the UI does.
        extra_read_paths / extra_write_paths / network_hosts: access beyond the run
            folder; needs a user approval for this tab and exactly this set.
        _context_id: server-injected tab id (never supplied by the model).

    Returns:
        On success: {"stdout", "stderr", "files", "runtime_ms", "error": None, "sandbox"}
        On approval needed: {"approval_required": True, "request_id", ..., "message"}
        On HITL required: {"hitl_required": True, "flagged_operations": [...], "message": str}
        On error: {"error": str, "stdout": str, "files": []}
    """
    from config import load_config

    cfg = load_config()
    policy = load_policy()
    if policy.code_runner == "disabled":
        return {"error": _DISABLED_MSG}
    # skill_id becomes a folder the sandbox may read, and goes into telemetry: plain names only.
    # Any non-empty value is checked, so a falsy non-string ({} or []) is refused rather than crashing later.
    if skill_id is not None and skill_id != "" and not _valid_skill_id(skill_id):
        return {"error": "Invalid skill_id: use only the skill's own id (letters, digits, dots, hyphens, underscores)."}
    # Admin policy and the never-grantable list apply in every mode, including the opt-out.
    requested = _check_requested_access(extra_read_paths, extra_write_paths, network_hosts, policy)
    if isinstance(requested, dict):
        return requested
    mode, reason = _sandbox_mode(cfg, policy)
    if mode == "unavailable":
        return {"error": _unavailable_message(reason)}

    # A frozen desktop sidecar cannot modify its bundled environment. Reject
    # any package-install request up front, even if that package happens to be
    # importable in the build environment today.
    if packages and getattr(sys, "frozen", False):
        return {
            "error": "Package installation is not available in the packaged app."
        }

    if mode == "enforced" and packages and not _packages_are_plain(packages):
        return {
            "error": (
                "Invalid packages: use plain names with optional extras and version specifiers "
                "such as 'requests', 'numpy>=1.2' or 'pkg[extra]==1.0'. URLs, paths and pip options are not allowed."
            )
        }

    # AST scan — blocked ops are always rejected; flagged ops require HITL (skipped if confirmed=True).
    # Runs before the approval gate so a rejected run never consumes a user approval.
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

    read_paths: list[Path] = []
    write_paths: list[Path] = []
    hosts: list[str] = []
    approval = None
    if mode == "enforced":
        gate = _approval_gate(*requested, _context_id, skill_id)
        if isinstance(gate, dict):
            return gate
        read_paths, write_paths, hosts, approval = gate

    tier = shared.TOOL_TIER_MAP.get(skill_id, "Verified")
    if timeout is None:
        key = (
            "code_runner_timeout_community"
            if tier == "Community"
            else "code_runner_timeout_verified"
        )
        timeout = int(cfg.get(key, 30 if tier == "Community" else 60))

    install_error = _install_packages(packages, _install_timeout)
    if install_error:
        return install_error

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

    # The run folder has no node_modules, so node scripts started by the code
    # can't resolve globally-installed packages (e.g. pptxgenjs). NODE_PATH
    # points at the global npm root. Prefer `npm root -g` (authoritative); on
    # Windows npm is a .cmd shim so it needs shell=True. Fall back to the
    # well-known %APPDATA%\npm\node_modules path if npm isn't invocable.
    _npm_root = None
    try:
        _npm_root = subprocess.run(
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

    telemetry = sandbox.telemetry_record(
        run_id, skill_id, mode, bool(hosts), len(read_paths), len(write_paths), approval
    )
    tags = {"sandbox": mode, "_sandbox_telemetry": telemetry}

    def fail(message: str, log: str, **extra) -> dict:
        _write_forensic(run_dir / "stderr.log", log)
        return {
            "error": message,
            "stdout": "",
            "files": [],
            "forensic": _forensic_paths(run_id, run_dir),
            **extra,
            **tags,
        }

    start = time.monotonic()
    try:
        if mode == "enforced":
            # Runtime paths become persistent read+execute grants on Windows: every one
            # (interpreter, site-packages, Node, npm root, skill folder) goes through the backstop.
            runtime_paths = _runtime_paths(skill_dir, _npm_root)
            if (
                _runtime_path_refused(skill_dir)
                or _runtime_path_refused(Path(_npm_root) if _npm_root else None)
                or any(_runtime_path_refused(p) for p in runtime_paths)
            ):
                return fail(
                    "The code sandbox refused to start because a runtime folder is not allowed. "
                    "Nothing was run. Tell the user; do not retry automatically.",
                    "sandbox refused: protected runtime path",
                )
            request = sandbox.SandboxRequest(
                argv=_python_command(run_dir / "code.py"),
                cwd=run_dir,
                env=sandbox.build_env(os.environ, run_dir, _npm_root),
                runtime_paths=runtime_paths,
                read_paths=read_paths,
                write_paths=write_paths,
                network=bool(hosts),
                timeout=timeout,
            )
            # Every failure here ends the call: never fall back to running the code unsandboxed.
            try:
                res = sandbox.launch_sandboxed(request)
            except sandbox.SandboxUnavailable as exc:  # raised before anything ran
                return fail(_unavailable_message(str(exc)), f"sandbox unavailable: {exc}")
            except sandbox.SandboxRunError as exc:  # the process may already have run
                return fail(_RUN_ERROR_MSG, f"sandbox run error: {exc}")
            except OSError as exc:  # e.g. grant ledger or launch-time sweep
                return fail(
                    f"The code sandbox could not start ({type(exc).__name__}) and nothing was run. "
                    "Tell the user; do not retry automatically.",
                    f"sandbox launch OSError: {exc}",
                )
            returncode, timed_out = res.returncode, res.timed_out
            stdout, stderr = res.stdout or "", _with_sandbox_hint(res.stderr or "")
        else:
            # Opted out (sandbox unavailable, policy allows it): the old unsandboxed path.
            _subproc_env = os.environ.copy()
            if _npm_root:
                _subproc_env["NODE_PATH"] = _npm_root
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
                returncode, timed_out = proc.returncode, False
                stdout, stderr = proc.stdout or "", proc.stderr or ""
            except subprocess.TimeoutExpired as te:
                # Partial stdout/stderr (if any) are on the exception object.
                returncode, timed_out = -1, True
                stdout = te.stdout if isinstance(te.stdout, str) else ""
                stderr = te.stderr if isinstance(te.stderr, str) else ""
        elapsed_ms = int((time.monotonic() - start) * 1000)

        # Full stdout/stderr to disk (the tool result only carries stderr[:500]
        # back to the model; these logs keep the complete trace for forensics).
        _write_forensic(run_dir / "stdout.log", stdout)
        _write_forensic(run_dir / "stderr.log", stderr)

        if timed_out:
            return {
                "error": f"Code execution timed out after {timeout}s.",
                "stdout": "",
                "files": [],
                "runtime_ms": elapsed_ms,
                "forensic": _forensic_paths(run_id, run_dir),
                **tags,
            }

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

        if returncode != 0:
            error = f"Code exited with code {returncode}. stderr: {stderr[:500]}"
            if _SANDBOX_HINT in stderr and _SANDBOX_HINT not in stderr[:500]:
                error += f"\n{_SANDBOX_HINT}"  # the 500-char cut must not drop the hint
            result = {
                "error": error,
                "stdout": stdout,
                "files": files,
                "runtime_ms": elapsed_ms,
                "forensic": _forensic_paths(run_id, run_dir),
                **tags,
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
            **tags,
        }
        if external_files:
            result["output_files"] = external_files
        return result

    except Exception as exc:
        return fail(str(exc), f"runner exception: {exc}")


TOOL_DEFS = [
    {
        "name": "run_python",
        "description": (
            "Execute Python code in an OS sandbox. By default the code can read and write only its "
            "own OUTPUT_DIR (injected automatically — write all output files there) and read the "
            "Python/Node runtime and SKILL_DIR; it has no network and no access to the rest of the "
            "user's files. If the task needs to read or write other local paths or reach the network, "
            "pass extra_read_paths, extra_write_paths or network_hosts: the call returns "
            "approval_required and the user approves or denies in the chat; call again with exactly "
            "the same values only after the user says they approved. Returns stdout and a list of "
            "output files with download URLs. If the code contains destructive operations outside "
            "OUTPUT_DIR, returns hitl_required=True with flagged_operations — show these to the user "
            "and re-call with confirmed=True if they approve."
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
                    "description": "Skill context for sandbox tier and SKILL_DIR (optional, e.g. 'slack-gif-creator')",
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
                "extra_read_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Absolute paths of existing files or folders outside OUTPUT_DIR the code must read. Needs the user's approval; request only what the task needs.",
                },
                "extra_write_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Absolute paths of existing folders or files outside OUTPUT_DIR the code must write. Needs the user's approval.",
                },
                "network_hosts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "host:port destinations the code must connect to, e.g. 'api.example.com:443'. Needs the user's approval; approval turns on outbound network for the runs it covers.",
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
