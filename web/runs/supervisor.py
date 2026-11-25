"""Run Supervisor: the one place a run's lifecycle, budgets, Stop and record live.

A run is an approval (awaiting_approval) followed by an execution on a worker thread owned by the
supervisor. Process handles live here in memory; the sqlite store is a durable mirror only. No
sqlite I/O happens under the lock: state changes are made in memory, then the snapshot is written.
"""
from __future__ import annotations

import contextvars
import itertools
import logging
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from proc_utils import kill_process_tree
from runs.facts import TreeWatcher, collect as collect_facts, urls_in
from runs.records import ACTIVE_STATES, OUTPUT_TAIL_CHARS, RunRecord, RunStore, exit_info, tail_of
from timeouts import Budgets

_log = logging.getLogger(__name__)

MAX_RUNNING_PER_CONTEXT = 3
MAX_ABANDONED_PER_SERVER = 3
_MCP_POLL_SECONDS = 0.02
# Refused probes do not use up a run's probe allowance, but the record that logs them stays bounded.
_MAX_PROBE_LOG = 50
_MEMORY_KEEP_SECONDS = 1800
_RETENTION_SECONDS = 7 * 24 * 3600


class RunError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code


class McpAbandoned(Exception):
    """An MCP call was left running on its worker thread: it outlived its budget or its turn's Stop."""

    def __init__(self, reason: str, record: dict, at_cap: bool):
        super().__init__(reason)
        self.reason, self.record, self.at_cap = reason, record, at_cap


class McpDispatchRefused(Exception):
    """The server already has its limit of abandoned calls still running, so nothing more is sent to it."""

    def __init__(self, abandoned: int):
        super().__init__(f"{abandoned} earlier calls are still running")
        self.abandoned = abandoned


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
    def __init__(self, store: RunStore, clock=time.time, max_running_per_context: int = MAX_RUNNING_PER_CONTEXT,
                 max_abandoned_per_server: int = MAX_ABANDONED_PER_SERVER):
        self._store = store
        self._clock = clock
        self._cap = max_running_per_context
        self._max_abandoned = max_abandoned_per_server
        self._abandoned: dict[str, int] = {}
        self._lock = threading.Lock()
        self._records: dict[str, RunRecord] = {}
        self._handles: dict[str, RunHandle] = {}
        self._workers: dict[str, threading.Thread] = {}
        self._probes: dict[int, tuple[str, str, object]] = {}
        self._probe_ids = itertools.count(1)

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
                          if r.context_id == rec.context_id and r.state in ("preparing", "running")
                          and r.kind != "mcp_call")
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
        with self._lock:
            self._workers[run_id] = thread
        try:
            thread.start()
        except RuntimeError as exc:
            with self._lock:
                self._workers.pop(run_id, None)
            self._terminal(run_id, "failed_to_start", reason="worker_unavailable")
            raise RunError(500, "The command could not be started.") from exc
        return snapshot

    @staticmethod
    def _notify(run_id: str, on_done, result: dict) -> None:
        if on_done is None:
            return
        try:
            on_done(result)
        except Exception:
            _log.exception("run %s on_done failed", run_id[:8])

    def _execute(self, run_id: str, handle: RunHandle, runner, budgets: Budgets, on_done) -> None:
        try:
            self._execute_inner(run_id, handle, runner, on_done)
        finally:
            with self._lock:
                self._workers.pop(run_id, None)

    def _execute_inner(self, run_id: str, handle: RunHandle, runner, on_done) -> None:
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
            lingering = {"teardown_failed": True} if getattr(failure, "teardown_failed", False) else {}
            result.update(lingering)
            record = self._terminal(run_id, "cancelled" if handle.cancelled else "failed_to_start",
                                    error=message, facts=lingering)
            self._notify(run_id, on_done, result)
            return record, result
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
        record = self._terminal(run_id, state, **common)
        self._notify(run_id, on_done, result)
        return record, result

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
                          if r.context_id == rec.context_id and r.state in ("preparing", "running")
                          and r.kind != "mcp_call")
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

    def run_mcp_call(self, *, context_id: str, turn_id: str, server_id: str, server_name: str, tool: str,
                     budgets: Budgets, call, on_abandon=None) -> tuple[dict, object]:
        """Run one MCP tool call on a worker thread that the budget and the turn's Stop can walk away from.

        Returns (final record, the call's value) and re-raises the call's own error. A call that outlives its
        budget or Stop is abandoned, not cancelled: the thread cannot be killed and the server may still finish
        it. The record keeps server, tool and timing only, never arguments or results."""
        now = self._clock()
        run_id = uuid.uuid4().hex
        rec = RunRecord(id=run_id, context_id=context_id or "", path="mcp", kind="mcp_call", scope="turn",
                        state="running", turn_id=turn_id or "", created_at=now, run_started_at=now,
                        facts={"server": server_name, "tool": tool, "timeout_ms": budgets.run_ms})
        state = {"ended": False, "abandoned": False}
        handle = None
        with self._lock:
            self._forget_old_locked(now)
            stuck = self._abandoned.get(server_id, 0)
            if stuck >= self._max_abandoned:
                rec.state, rec.reason, rec.finished_at = "failed_to_start", "server_unresponsive", now
            else:
                handle = RunHandle(self, run_id, budgets.run_ms / 1000, budgets.teardown_ms)
                handle.inline = True
                self._handles[run_id] = handle
            self._records[run_id] = rec
            snapshot = self._snapshot_locked(rec)
        self._write(snapshot)
        if handle is None:
            raise McpDispatchRefused(stuck)

        box: dict = {}
        finished = threading.Event()

        def work() -> None:
            try:
                box["value"] = call()
            except BaseException as exc:  # noqa: BLE001 - handed back to the caller unchanged
                box["error"] = exc
            finally:
                with self._lock:
                    state["ended"] = True
                    if state["abandoned"]:
                        self._abandoned[server_id] = max(0, self._abandoned.get(server_id, 1) - 1)
                finished.set()

        # The worker keeps the caller's context (turn id, telemetry suppression) the way asyncio.to_thread does.
        context = contextvars.copy_context()
        threading.Thread(target=context.run, args=(work,), name=f"mcp-{run_id[:8]}", daemon=True).start()
        deadline = time.monotonic() + budgets.run_ms / 1000
        while not finished.wait(_MCP_POLL_SECONDS):
            if handle.cancelled or time.monotonic() >= deadline:
                break
        with self._lock:
            walked_away = not state["ended"]
            if walked_away:
                state["abandoned"] = True
                count = self._abandoned.get(server_id, 0) + 1
                self._abandoned[server_id] = count
        if walked_away:
            reason = "stopped" if handle.cancelled else "timeout"
            record = self._terminal(run_id, "abandoned", reason=reason)
            handle.done.set()
            if on_abandon is not None:
                try:
                    on_abandon(reason)
                except Exception:
                    _log.warning("run %s: the MCP cancel notice was not delivered", run_id[:8])
            raise McpAbandoned(reason, record, at_cap=count >= self._max_abandoned)
        handle.done.set()
        error = box.get("error")
        if error is None:
            return self._terminal(run_id, "finished"), box.get("value")
        self._terminal(run_id, "timed_out" if isinstance(error, TimeoutError) else "finished",
                       error=type(error).__name__)
        raise error

    def abandoned_count(self, server_id: str) -> int:
        with self._lock:
            return self._abandoned.get(server_id, 0)

    def wait(self, run_id: str, timeout: float) -> None:
        """Block until the run has ended and its worker, including on_done, has finished (tests and shutdown)."""
        with self._lock:
            thread = self._workers.get(run_id)
        if thread is not None:
            thread.join(timeout)
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
        self._cancel_probes(run_id=run_id)
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
        self._cancel_probes(turn_id=turn_id)
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
                    if r.scope == "turn" and r.turn_id == turn_id and r.state in ("preparing", "running")
                    and r.kind != "mcp_call"]
        return sorted(recs, key=lambda r: r["created_at"])

    def stop_all(self) -> None:
        """App quit: kill every running command."""
        self._cancel_probes()
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
            data = rec.to_dict()
        if data["state"] in ACTIVE_STATES and not (data.get("facts") or {}).get("urls_seen"):
            live = self._live_urls(run_id)
            if live:
                data["facts"] = {**(data.get("facts") or {}), "urls_seen": live}
        return data

    def _live_urls(self, run_id: str) -> list[str]:
        """URLs printed so far by a run that is still going, read from its live output."""
        with self._lock:
            handle = self._handles.get(run_id)
            read = getattr(getattr(handle, "proc", None), "live_output", None)
        if read is None:
            return []
        try:
            return urls_in(read())
        except Exception:
            return []

    def begin_probe(self, run_id: str, context_id: str, url: str, max_probes: int) -> list[str]:
        """Log a probe on the record, counting it against the run's cap. Returns the URLs the run printed so far."""
        rec = self._owned(run_id, context_id)
        live = self._live_urls(run_id)
        with self._lock:
            made = [p for p in rec.probe_log if "refused" not in p]
            if len(made) >= max_probes or len(rec.probe_log) >= _MAX_PROBE_LOG:
                raise RunError(429, f"This run has already used its {max_probes} probes.")
            rec.probe_log.append({"url": url, "at": self._clock()})
            urls_seen = list(rec.facts.get("urls_seen") or []) or live
            snapshot = self._snapshot_locked(rec)
        self._write(snapshot)
        return urls_seen

    @contextmanager
    def probing(self, run_id: str, turn_id: str, cancel):
        """While a probe is in flight, a Stop of its run or of its turn calls cancel.cancel()."""
        token = next(self._probe_ids)
        with self._lock:
            self._probes[token] = (run_id, turn_id or "", cancel)
        try:
            yield
        finally:
            with self._lock:
                self._probes.pop(token, None)

    def _cancel_probes(self, *, run_id: str = "", turn_id: str = "") -> None:
        with self._lock:
            hits = [c for r, t, c in self._probes.values()
                    if (not run_id and not turn_id) or (run_id and r == run_id) or (turn_id and t == turn_id)]
        for cancel in hits:
            cancel.cancel("stopped")

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
        interrupted = self._store.interrupt_active(now, skip=self._is_mine)
        for data in interrupted:
            self._sweep_process(data.get("owner_pid") or 0, data.get("owner_create_time") or 0.0)
        self._store.purge(now - _RETENTION_SECONDS)
        return [d["id"] for d in interrupted]

    def _is_mine(self, run_id: str) -> bool:
        """A record this process opened is live, whatever the database says: reconcile only owns older rows."""
        with self._lock:
            return run_id in self._records

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
