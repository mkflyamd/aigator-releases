"""Runs a marketplace skill's tools.py inside the OS sandbox, one process per call."""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from marketplace import skill_audit, state
from marketplace.permissions import Permissions
from marketplace.sandbox_launch import new_run_dir, run_in_sandbox
from marketplace.tool_runner_source import ARGS_NAME, RESULT_NAME, RUNNER_NAME, RUNNER_SOURCE

logger = logging.getLogger(__name__)

DESCRIBE_TIMEOUT = 30
MAX_RESULT_BYTES = 10_000_000
_SHARED_HINT = (
    "This skill's tools import the app's internal modules, which a sandboxed skill cannot reach. "
    "Its tools are unavailable."
)


def _could_not_run(exc: Exception) -> dict:
    logger.warning("sandboxed skill tool run failed", exc_info=True)
    return {"ok": False, "error": f"The skill's tool could not be run in the sandbox ({type(exc).__name__})."}


def _timeout_for(tier: str) -> int:
    from config import load_config

    community = tier == "Community"
    key = "code_runner_timeout_community" if community else "code_runner_timeout_verified"
    return int(load_config().get(key, 30 if community else 60))


def _friendly(message: str) -> str:
    return _SHARED_HINT if "No module named 'shared'" in message else message


def _stopped(stderr: str, returncode: int) -> str:
    lines = [line for line in stderr.strip().splitlines() if line.strip()]
    tail = lines[-1][:300] if lines else ""
    return _friendly(f"The skill's tool stopped without a result (exit {returncode}). {tail}".strip())


def _run(skill_id: str, skill_dir: Path, mode: str, perms: Permissions, timeout: int,
         tool_name: str = "", args: dict | None = None) -> dict:
    # Fail closed: any error before or during the launch is an error result. tools.py is never
    # imported or run in this process as a fallback.
    try:
        from skills.code_runner import tools as cr

        run_dir = new_run_dir()
    except Exception as exc:
        return _could_not_run(exc)
    try:
        runner = run_dir / RUNNER_NAME
        runner.write_text(RUNNER_SOURCE, encoding="utf-8")
        argv = cr._python_command(runner) + [mode, str(skill_dir)]
        if tool_name:
            argv.append(tool_name)
            (run_dir / ARGS_NAME).write_text(json.dumps(args or {}, default=str), encoding="utf-8")
        run = run_in_sandbox(skill_id, "tool", argv, Path(skill_dir), run_dir, perms, timeout)
        if not run.ok:
            return {"ok": False, "error": run.error}
        destinations, stderr = skill_audit.extract_outbound(run.stderr)
        skill_audit.log_outbound(skill_id, destinations)
        if run.timed_out:
            return {"ok": False, "error": f"The skill's tool timed out after {timeout} seconds."}
        result_file = run_dir / RESULT_NAME
        try:
            if result_file.stat().st_size > MAX_RESULT_BYTES:
                return {"ok": False, "error": "The skill's tool returned more than 10 MB."}
            data = json.loads(result_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"ok": False, "error": _stopped(stderr, run.returncode)}
        if not isinstance(data, dict):
            return {"ok": False, "error": _stopped(stderr, run.returncode)}
        if not data.get("ok"):
            data["error"] = _friendly(str(data.get("error") or "the skill's tool failed"))
        return data
    except Exception as exc:
        return _could_not_run(exc)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def describe_skill_tools(skill_id: str, skill_dir: Path, perms: Permissions) -> dict:
    try:
        data = _run(skill_id, skill_dir, "describe", perms, DESCRIBE_TIMEOUT)
    except Exception as exc:
        return _could_not_run(exc)
    if data.get("ok") and not isinstance(data.get("defs"), list):
        return {"ok": False, "error": "The skill's tool list could not be read."}
    return data


def call_skill_tool(skill_id: str, skill_dir: Path, name: str, args: dict, tier: str) -> dict:
    try:
        if state.is_disabled(skill_id):
            return {"error": "skill is disabled"}
        data = _run(skill_id, skill_dir, "call", state.approved_permissions(skill_id),
                    _timeout_for(tier), name, args)
    except Exception as exc:
        return {"error": _could_not_run(exc)["error"]}
    if not data.get("ok"):
        return {"error": data.get("error") or "the skill's tool failed"}
    result = data.get("result")
    return result if isinstance(result, dict) else {"error": "the skill's tool returned an unreadable result"}


def make_stub(skill_id: str, skill_dir: Path, name: str, tier: str):
    def stub(args: dict) -> dict:
        return call_skill_tool(skill_id, skill_dir, name, args, tier)

    stub.__name__ = f"{skill_id}__{name}"
    return stub
