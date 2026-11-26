"""Commands the model starts without an approval card (run_shell, run_python), run under the supervisor.

The run belongs to the chat turn that called the tool, so that turn's Stop kills it and cleans up.
"""
from __future__ import annotations

import dataclasses

import timeouts
from runs.model_result import model_result
from runs.supervisor import get_supervisor
from runs.turn import current_turn


class RunRefused(Exception):
    """The supervisor did not start the run (for example the tab already has its limit running)."""


def run_inline(path: str, kind: str, context_id: str, run_seconds: float, runner) -> tuple[dict, dict]:
    """(final record, the runner's result). The runner takes the RunHandle."""
    budgets = timeouts.budgets_for(path, run_ms=int(run_seconds * 1000))
    return get_supervisor().run_inline(context_id=context_id or "", turn_id=current_turn.get(), path=path,
                                       kind=kind, budgets=budgets, runner=runner)


def with_run_fields(result: dict, record: dict) -> dict:
    """The tool's own result plus the run's id, state, exit and observed facts."""
    fields = model_result(record, {})
    fields.pop("stdout", None)
    return {**fields, **result}


def launch_supervised(request, *, context_id: str, kind: str):
    """Launch a SandboxRequest as a turn-owned run. Returns (SandboxResult, record).

    A launcher refusal is re-raised unchanged, so callers keep their own error messages."""
    import sandbox

    refusal: list[Exception] = []
    outcome: list = []

    def runner(handle):
        supervised = dataclasses.replace(
            request, cancel=handle._cancelled, on_start=handle.started,
            setup_seconds=budgets.setup_ms / 1000, teardown_seconds=budgets.teardown_ms / 1000)
        try:
            res = sandbox.launch_sandboxed(supervised)
        except Exception as exc:
            refusal.append(exc)
            raise
        outcome.append(res)
        return {"stdout": res.stdout, "stderr": res.stderr, "exit_code": res.returncode,
                "timed_out": res.timed_out, "teardown_failed": res.teardown_failed}

    budgets = timeouts.budgets_for("sandbox", run_ms=int(request.timeout * 1000))
    record, result = get_supervisor().run_inline(context_id=context_id or "", turn_id=current_turn.get(),
                                                 path="sandbox", kind=kind, budgets=budgets, runner=runner)
    if refusal:
        raise refusal[0]
    if not outcome:
        raise RunRefused(result.get("error") or "The command could not be started.")
    return outcome[0], record
