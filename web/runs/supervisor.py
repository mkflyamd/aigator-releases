"""Run Supervisor: the one place a run's lifecycle, budgets, Stop and record live.

A run is an approval (awaiting_approval) followed by an execution on a worker thread owned by the
supervisor. Process handles live here in memory; the sqlite store is a durable mirror only. No
sqlite I/O happens under the lock: state changes are made in memory, then the snapshot is written.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from pathlib import Path

from proc_utils import kill_process_tree
from runs.facts import TreeWatcher, collect as collect_facts
from runs.records import ACTIVE_STATES, OUTPUT_TAIL_CHARS, RunRecord, RunStore, exit_info, tail_of
from timeouts import Budgets

_log = logging.getLogger(__name__)

MAX_RUNNING_PER_CONTEXT = 3
_MEMORY_KEEP_SECONDS = 1800
_RETENTION_SECONDS = 7 * 24 * 3600


class RunError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code


class _PidProc:
    """A process known only by pid (the sandbox launchers report one), enough for kill_process_tree."""

    def __init__(self, pid: int):
        self.pid = pid

    def kill(self) -> None:
        try:
            import psutil

            psutil.Process(self.pid).kill()
        except Exception:
            pass


class RunHandle:
    """What a runner gets: its run budget, whether Stop was requested, and a place to hand over its process."""

    def __init__(self, supervisor: "RunSupervisor", run_id: str, timeout_s: float, teardown_ms: int):
        self._supervisor = supervisor
        self.run_id = run_id
        self.timeout_s = timeout_s
        self.teardown_ms = teardown_ms
        self._cancelled = threading.Event()
        self.proc = None
        self.watcher = None
        self.thread: threading.Thread | None = None
        self.inline = False  # runs on the calling tool thread, so it may still be queued with nothing started
        self.done = threading.Event()  # set when the runner has returned: nothing of the run is left to wind down

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def attach(self, proc) -> None:
        """Remember the running process so Stop and app quit can kill its tree; kill it now if Stop already came."""
        self.proc = proc
        self._supervisor._process_started(self.run_id, proc)
        if self.cancelled:
            kill_process_tree(proc)

    def started(self, pid: int) -> None:
        """The sandbox launchers report a pid instead of a Popen."""
        self.attach(_PidProc(int(pid)))


class RunSupervisor:
    def __init__(self, store: RunStore, clock=time.time, max_running_per_context: int = MAX_RUNNING_PER_CONTEXT):
        self._store = store
        self._clock = clock
        self._cap = max_running_per_context
        self._lock = threading.Lock()
        self._records: dict[str, RunRecord] = {}
        self._handles: dict[str, RunHandle] = {}

    # -- internals ----------------------------------------------------------

    def _snapshot_locked(self, rec: RunRecord) -> dict:
        rec.rev += 1
        return rec.to_dict()

    def _write(self, snapshot: dict) -> None:
        self._store.upsert(snapshot)

    def _load_locked(self, run_id: str) -> RunRecord | None:
        return self._records.get(run_id)

    def _load(self, run_id: str) -> RunRecord | None:
        with self._lock:
            rec = self._records.get(run_id)
        if rec is not None:
            return rec
        data = self._store.get(run_id)
        if data is None:
            return None
        rec = RunRecord.from_dict(data)
        with self._lock:
            return self._records.setdefault(run_id, rec)

    def _owned(self, run_id: str, context_id: str) -> RunRecord:
        rec = self._load(run_id)
        if rec is None:
            raise RunError(404, "This run was not found or has expired.")
        if rec.context_id != (context_id or ""):
            raise RunError(409, "This run belongs to a different tab.")
        return rec

    def _terminal(self, run_id: str, state: str, **changes) -> dict:
        """Move an active record to a terminal state. A record that is already terminal is left alone."""
        with self._lock:
            rec = self._records[run_id]
            if rec.state not in ACTIVE_STATES:
                return rec.to_dict()
            rec.state = state
            rec.finished_at = self._clock()
            for key, value in changes.items():
                if key == "facts":
                    rec.facts.update(value)
                else:
                    setattr(rec, key, value)
            self._handles.pop(run_id, None)
            snapshot = self._snapshot_locked(rec)
        self._write(snapshot)
        return snapshot

    def _process_started(self, run_id: str, proc) -> None:
        pid, created = int(getattr(proc, "pid", 0) or 0), 0.0
        try:
            import psutil

            created = psutil.Process(pid).create_time()
        except Exception:
            pass
        with self._lock:
            rec = self._records.get(run_id)
            if rec is None:
                return
            rec.owner_pid, rec.owner_create_time = pid, created
            if rec.state == "preparing":
                rec.state, rec.run_started_at = "running", self._clock()
            handle = self._handles.get(run_id)
            snapshot = self._snapshot_locked(rec)
        if handle is not None and pid:
            try:
                handle.watcher = TreeWatcher(pid).start()
            except Exception:
                _log.warning("run %s: process tree watcher did not start", run_id[:8])
        self._write(snapshot)

    def _forget_old_locked(self, now: float) -> None:
        stale = [rid for rid, r in self._records.items()
                 if r.state not in ACTIVE_STATES and now - (r.finished_at or r.created_at) > _MEMORY_KEEP_SECONDS]
        for rid in stale:
            del self._records[rid]

    # -- approval -----------------------------------------------------------

    def open_approval(self, *, run_id: str, context_id: str, path: str, kind: str, scope: str,
                      expires_at: float, turn_id: str = "") -> dict:
        now = self._clock()
        rec = RunRecord(id=run_id, context_id=context_id or "", path=path, kind=kind, scope=scope,
                        state="awaiting_approval", turn_id=turn_id or "", created_at=now, expires_at=expires_at)
        with self._lock:
            self._forget_old_locked(now)
            self._records[run_id] = rec
            snapshot = self._snapshot_locked(rec)
        self._write(snapshot)
        return snapshot

    def deny(self, run_id: str, context_id: str) -> dict:
        self._owned(run_id, context_id)
        return self._terminal(run_id, "denied")

    def policy_block(self, run_id: str, context_id: str, reason: str) -> dict:
        self._owned(run_id, context_id)
        return self._terminal(run_id, "policy_blocked", reason=reason)

    def mark_expired(self, run_id: str) -> dict | None:
        """The approval registry's expiry event: one clock decides, the record follows."""
        rec = self._load(run_id)
        if rec is None:
            return None
        with self._lock:
            awaiting = rec.state == "awaiting_approval"
        return self._terminal(run_id, "expired") if awaiting else rec.to_dict()

    # -- execution ----------------------------------------------------------

    def start(self, run_id: str, context_id: str, runner, budgets: Budgets, on_done=None) -> dict:
        """awaiting_approval -> preparing, atomically, then run on a worker thread. Idempotent while active."""
        rec = self._owned(run_id, context_id)
        with self._lock:
            if rec.state in ("preparing", "running"):
                return rec.to_dict()
            if rec.state == "expired":
                raise RunError(410, "This command request expired. Ask AI Gator to propose it again.")
            if rec.state != "awaiting_approval":
                raise RunError(409, f"This command request was already {rec.state}.")
            running = sum(1 for r in self._records.values()
                          if r.context_id == rec.context_id and r.state in ("preparing", "running"))
            over_cap = running >= self._cap
            if not over_cap:
                rec.state = "preparing"
                rec.setup_started_at = self._clock()
                handle = RunHandle(self, run_id, budgets.run_ms / 1000, budgets.teardown_ms)
                self._handles[run_id] = handle
                snapshot = self._snapshot_locked(rec)
        if over_cap:
            return self._terminal(run_id, "failed_to_start", reason="concurrency_cap")
        self._write(snapshot)
        thread = threading.Thread(target=self._execute, args=(run_id, handle, runner, budgets, on_done),
                                  name=f"run-{run_id[:8]}", daemon=True)
        handle.thread = thread
        thread.start()
        return snapshot

    def _execute(self, run_id: str, handle: RunHandle, runner, budgets: Budgets, on_done) -> None:
        with self._lock:
            rec = self._records[run_id]
            if rec.state == "preparing":
                rec.state, rec.run_started_at = "running", self._clock()
                snapshot = self._snapshot_locked(rec)
            else:
                snapshot = None
        if snapshot is not None:
            self._write(snapshot)
        self._run_and_conclude(run_id, handle, runner, on_done)

    def _run_and_conclude(self, run_id: str, handle: RunHandle, runner, on_done) -> tuple[dict, dict]:
        """Call the runner, then record how the run ended. Returns the final record and the runner's result."""
        failure: Exception | None = None
        result: dict = {}
        try:
            result = runner(handle) or {}
        except Exception as exc:
            failure = exc
        finally:
            handle.done.set()
        if failure is not None:
            _log.warning("run %s could not start (%s)", run_id[:8], type(failure).__name__)
            if handle.watcher is not None:
                handle.watcher.finish()
            message = f"The command could not be started ({type(failure).__name__})."
            result = {"error": message, "stdout": "", "stderr": "", "exit_code": -1}
            record = self._terminal(run_id, "cancelled" if handle.cancelled else "failed_to_start", error=message)
            self._notify(run_id, on_done, result)
            return record, result
        self._notify(run_id, on_done, result)
        output = f"{result.get('stdout') or ''}{result.get('stderr') or ''}"
        tail, truncated = tail_of(output, OUTPUT_TAIL_CHARS)
        try:
            found = collect_facts(output, handle.watcher)
        except Exception:
            _log.warning("run %s: facts could not be collected", run_id[:8])
            found = {}
        if result.get("teardown_failed"):
            found["teardown_failed"] = True
        common = {"exit": exit_info(result.get("exit_code")), "output_tail": tail, "output_truncated": truncated,
                  "error": str(result.get("error") or ""), "facts": found}
        if handle.cancelled:
            state = "cancelled"
        elif result.get("timed_out"):
            state = "timed_out"
        elif handle.proc is None and result.get("error"):
            state = "failed_to_start"
        else:
            state = "finished"
        return self._terminal(run_id, state, **common), result

    @staticmethod
    def _notify(run_id: str, on_done, result: dict) -> None:
        if on_done is None:
            return
        try:
            on_done(result)
        except Exception:
            _log.exception("run %s on_done failed", run_id[:8])

    def run_inline(self, *, context_id: str, turn_id: str, path: str, kind: str, budgets: Budgets,
                   runner) -> tuple[dict, dict]:
        """A model-called command that needs no approval card: it runs on the calling tool thread, owned by
        the turn, so the turn's Stop reaches it. Returns the final record and the runner's result."""
        now = self._clock()
        run_id = uuid.uuid4().hex
        rec = RunRecord(id=run_id, context_id=context_id or "", path=path, kind=kind, scope="turn",
                        state="preparing", turn_id=turn_id or "", created_at=now, setup_started_at=now)
        with self._lock:
            self._forget_old_locked(now)
            running = sum(1 for r in self._records.values()
                          if r.context_id == rec.context_id and r.state in ("preparing", "running"))
            over_cap = running >= self._cap
            if over_cap:
                rec.state, rec.reason, rec.finished_at = "failed_to_start", "concurrency_cap", now
                handle = None
            else:
                handle = RunHandle(self, run_id, budgets.run_ms / 1000, budgets.teardown_ms)
                handle.thread = threading.current_thread()
                handle.inline = True
                self._handles[run_id] = handle
            self._records[run_id] = rec
            snapshot = self._snapshot_locked(rec)
        self._write(snapshot)
        if handle is None:
            return snapshot, {"error": f"Too many commands are already running in this tab (limit {self._cap}). "
                                       "Wait for one to finish; do not retry automatically."}
        return self._run_and_conclude(run_id, handle, runner, None)

    def wait(self, run_id: str, timeout: float) -> None:
        """Block until the run has ended (tests and shutdown)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                rec = self._records.get(run_id)
                if rec is None or rec.state not in ("preparing", "running"):
                    return
            time.sleep(0.01)

    # -- Stop ---------------------------------------------------------------

    def cancel(self, run_id: str, context_id: str) -> dict:
        """Stop a run: tree-kill, then wait up to the teardown budget for its worker to wind down."""
        rec = self._owned(run_id, context_id)
        with self._lock:
            state = rec.state
        if state == "awaiting_approval":
            return self._terminal(run_id, "denied")
        if state not in ("preparing", "running"):
            return rec.to_dict()
        return self._stop(run_id)

    def _stop(self, run_id: str) -> dict:
        with self._lock:
            handle = self._handles.get(run_id)
            rec = self._records[run_id]
            if rec.teardown_started_at == 0.0:
                rec.teardown_started_at = self._clock()
        if handle is None:
            return rec.to_dict()
        handle._cancelled.set()
        if handle.proc is not None:
            kill_process_tree(handle.proc)
        wound_down = handle.done.wait(handle.teardown_ms / 1000)
        if wound_down:
            with self._lock:
                state = rec.state
            if state in ACTIVE_STATES:
                self.wait(run_id, 1)
            return rec.to_dict()
        # An inline command still queued behind another launch has no process and nothing to tear down: its own
        # thread sees Stop and ends. Anything else that outlived its teardown budget is reported.
        facts = {} if handle.inline and handle.proc is None else {"teardown_failed": True}
        return self._terminal(run_id, "cancelled", facts=facts)

    def cancel_turn(self, turn_id: str) -> list[str]:
        """The turn's Stop: cancel its turn-scoped runs. Tab-scoped runs (host cards) are never touched."""
        if not turn_id:
            return []
        with self._lock:
            ids = [r.id for r in self._records.values()
                   if r.scope == "turn" and r.turn_id == turn_id and r.state in ("preparing", "running")]
        for run_id in ids:
            self._stop(run_id)
        return ids

    def active_for_turn(self, turn_id: str) -> list[dict]:
        """The turn's runs that are still preparing or running, oldest first."""
        if not turn_id:
            return []
        with self._lock:
            recs = [r.to_dict() for r in self._records.values()
                    if r.scope == "turn" and r.turn_id == turn_id and r.state in ("preparing", "running")]
        return sorted(recs, key=lambda r: r["created_at"])

    def stop_all(self) -> None:
        """App quit: kill every running command."""
        with self._lock:
            ids = [r.id for r in self._records.values() if r.state in ("preparing", "running")]
        for run_id in ids:
            self._stop(run_id)

    # -- reads --------------------------------------------------------------

    def get(self, run_id: str, context_id: str) -> dict | None:
        rec = self._load(run_id)
        if rec is None or rec.context_id != (context_id or ""):
            return None
        with self._lock:
            return rec.to_dict()

    def begin_probe(self, run_id: str, context_id: str, url: str, max_probes: int) -> list[str]:
        """Count a probe against the run's cap and log it on the record. Returns the URLs the run printed."""
        rec = self._owned(run_id, context_id)
        with self._lock:
            if len(rec.probe_log) >= max_probes:
                raise RunError(429, f"This run has already used its {max_probes} probes.")
            rec.probe_log.append({"url": url, "at": self._clock()})
            urls_seen = list(rec.facts.get("urls_seen") or [])
            snapshot = self._snapshot_locked(rec)
        self._write(snapshot)
        return urls_seen

    def finish_probe(self, run_id: str, outcome: dict) -> None:
        with self._lock:
            rec = self._records.get(run_id)
            if rec is None or not rec.probe_log:
                return
            rec.probe_log[-1].update(outcome)
            snapshot = self._snapshot_locked(rec)
        self._write(snapshot)

    def list(self, context_id: str) -> list[dict]:
        merged = {r["id"]: r for r in self._store.list(context_id)}
        with self._lock:
            for rec in self._records.values():
                if rec.context_id == (context_id or ""):
                    merged[rec.id] = rec.to_dict()
        return sorted(merged.values(), key=lambda r: r["created_at"], reverse=True)

    # -- startup ------------------------------------------------------------

    def reconcile(self) -> list[str]:
        """Startup: records still active when the backend stopped become interrupted, and any process they
        left behind is swept, but only if the pid still belongs to the same process (pid and creation time)."""
        now = self._clock()
        interrupted = self._store.interrupt_active(now)
        for data in interrupted:
            self._sweep_process(data.get("owner_pid") or 0, data.get("owner_create_time") or 0.0)
        self._store.purge(now - _RETENTION_SECONDS)
        return [d["id"] for d in interrupted]

    @staticmethod
    def _sweep_process(pid: int, created: float) -> None:
        if not pid or not created:
            return
        try:
            import psutil

            proc = psutil.Process(pid)
            if abs(proc.create_time() - created) > 1.0:
                return
            for child in proc.children(recursive=True):
                try:
                    child.kill()
                except psutil.Error:
                    pass
            proc.kill()
        except Exception:
            return


_default: RunSupervisor | None = None
_default_lock = threading.Lock()


def get_supervisor() -> RunSupervisor:
    global _default
    with _default_lock:
        if _default is None:
            from config import GATOR_DIR

            _default = RunSupervisor(RunStore(Path(GATOR_DIR) / "runs.db"))
        return _default


def reset_supervisor(supervisor: RunSupervisor | None = None) -> None:
    """Tests: swap the process-wide supervisor."""
    global _default
    with _default_lock:
        _default = supervisor
