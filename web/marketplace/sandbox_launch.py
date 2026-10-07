"""The one place that turns a hook or tools.py run into a SandboxRequest."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from marketplace import skill_audit
from marketplace.permissions import Permissions, readable_paths

_REFUSED_MSG = ("The skill sandbox refused to start because a runtime folder is not allowed. "
                "Nothing was run.")


@dataclass(frozen=True)
class SkillRun:
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    error: str = ""


def _failed(message: str) -> SkillRun:
    return SkillRun(False, -1, "", "", False, message)


def new_run_dir() -> Path:
    import config

    run_dir = Path(config.OUTPUTS_DIR) / uuid4().hex[:12]
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def run_in_sandbox(skill_id: str, kind: str, argv: list[str], skill_dir: Path, run_dir: Path,
                   perms: Permissions, timeout: int) -> SkillRun:
    """Run argv in the OS sandbox. Never falls back to running unsandboxed."""
    import sandbox
    from skills.code_runner import tools as cr

    runtime_paths = cr._runtime_paths(skill_dir, None)
    if cr._runtime_path_refused(skill_dir) or any(cr._runtime_path_refused(p) for p in runtime_paths):
        return _failed(_REFUSED_MSG)
    request = sandbox.SandboxRequest(
        argv=argv,
        cwd=run_dir,
        env=sandbox.build_env(os.environ, run_dir, None),
        runtime_paths=runtime_paths,
        read_paths=readable_paths(perms),
        write_paths=[],
        network=perms.wants_network,
        timeout=timeout,
    )
    skill_audit.log_launch(skill_id, kind, perms.wants_network, perms.network)
    try:
        res = sandbox.launch_sandboxed(request)
    except sandbox.SandboxUnavailable as exc:
        return _failed(cr._unavailable_message(str(exc)))
    except sandbox.SandboxRunError:
        return _failed(cr._RUN_ERROR_MSG)
    except OSError as exc:
        return _failed(f"The skill sandbox could not start ({type(exc).__name__}) and nothing was run.")
    return SkillRun(True, res.returncode, res.stdout or "", res.stderr or "", bool(res.timed_out))
