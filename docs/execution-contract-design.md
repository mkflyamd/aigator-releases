# Execution Contract — Design

Status: draft for review. Date: 2026-11-24. Reviewed by Opus (sections 1-4).

## Problem

Every path that runs a command or code (sandboxed `run_shell`, unsandboxed `run_shell`, `run_on_host`, `run_python`, MCP calls) has its own approval, budgets, Stop behavior, status events and result shape. Fixes have landed one symptom at a time, and the same class of failure keeps returning:

- Unbounded external calls: icacls hang on an over-broad folder (#114), Graph blocking the event loop (#112), stdio MCP stalls, hung CI tests.
- The model misreading a tool result: `_exit_note` (`web/skills/shell_runner/tools.py:742`) tells the model that a non-zero exit with a localhost URL means "the server it started is probably not running". `motlab edit` prints the URL of an already-running viewer and then crashes at exit (Node 24 libuv assertion, exit 0xC0000409), so the agent told the user a working viewer had crashed.
- Stop that does not stop: only host commands have a real kill. A running sandboxed command, `run_python` or MCP call cannot be stopped.
- No visible lifecycle: the only progress text is "Still working... (Ns)".
- Host card state is an in-memory dict, lost on restart, and Run returns 409 on reload or retry.

This is a missing contract, not a set of edge cases.

## Relationship to Agent Runtime Hardening

The Agent Runtime Hardening design (2026-11-19, WS0-WS9) stands, and the loop stays hand-rolled (G1 closed 2026-11-24: no Agent SDK or CLI as main loop). This contract is the command-execution layer beneath it. Seams:

- **WS1 (killable worker, per-tool timeouts):** the supervisor owns anything that is an OS process. WS1 owns loop-level execution for in-process and MCP tools and calls `start_run` for subprocess tools. This is the same seam as `kind=mcp_call` (`abandoned`).
- **WS3 (pending-interactions registry):** the single approvals store. `awaiting_approval` on a RunRecord references a registry entry; it does not duplicate approval state. The host card registers there like the other card kinds. The entry carries `expires_at` (300 s default, 600 s for host) and the registry emits the expired event; the supervisor moves the RunRecord to `expired` from that event, so there is one clock. The run's setup and run budgets do not tick while awaiting approval.
- **Turn id and per-context turn lock:** hardening PR 1 makes `chat()` return 409 `turn_in_progress` for a conversation with a live task (live means the asyncio task is not done, and the new task is registered in the same step as the check), and WS4 needs a stable turn id for durable sessions. The contract uses that definition and does not build a second one; PR1a depends on hardening PR 1. The turn id is an opaque in-memory id with a 30-minute TTL: RunRecord treats it as opaque and reconciliation never depends on the task still existing.
- **Message queue:** WS3's first slice adds the "queued" chip while a card is pending. Hardening PR 11 is split: 11a is the queue (based on hardening PR 1, this contract's PR3) and 11b is steer (stays on PR 6). The queue section below is the requirement set for 11a; it is not a separate implementation.
- **WS4 (durable sessions):** RunRecord shares its sqlite store and secret-scrubbing rules. Until WS4 lands, an `awaiting_approval` record becomes `interrupted` at startup. After WS4 lands, an `awaiting_approval` record whose registry entry is still live stays awaiting.
- **WS2 (typed events):** run state changes are typed events in the same schema, marked must-deliver for terminal states.

## Goals

1. Every run, on every path, goes through one supervisor and has one persisted record with defined states.
2. Every step is time-bounded, and Stop cancels it.
3. The model receives facts, never verdicts.
4. A user can queue the next message while a turn runs.
5. A conformance suite enforces all of the above.

## Non-goals

- MCP server process lifecycle (session-long and shared). Individual MCP tool calls are covered by a thin record (see MCP calls).
- A detach mode for long-running servers. For a real server, "run it in your terminal" stays correct.
- Loosening `_check_fetch_target`; `fetch_webpage` keeps blocking loopback.
- Verifying the Node/motlab crash itself. It is a motlab/Node 24 Windows bug, reproduced with file, pipe and console stdout.

## Architecture: Run Supervisor

A loop-agnostic service module (not inside `agent_loop.py`). Every path calls `start_run(spec)`; no path spawns a process itself. Any agent loop (including a Claude Agent SDK loop) must expose command execution through the runner tools, with native Bash disabled.

### RunRecord

Persisted in sqlite as a durable mirror. Process handles live in an in-memory map; liveness comes from the map and process checks, not from the database. No sqlite I/O under the global lock.

Fields: id, context_id/tab, turn id, path, kind, owner scope, state, phase timestamps (setup, run, teardown), exit info (code, hex, is_crash_value), facts, grant ids (links to the grants ledger), probe log, error.

Facts: `urls_seen`, `ports_opened`, `owner_pid`, `owner_in_run_tree` (informational, gates nothing), `children_left`, output size and truncated flag, `teardown_failed`.

Persistence hygiene: metadata plus a capped output tail, with a retention purge. No full output, no args or results for MCP calls.

### States

`awaiting_approval` (expires after 300 s by default, 600 s for host cards, set per registry entry), `preparing`, `running`, `finished`, `timed_out`, `cancelled`, `denied`, `policy_blocked`, `expired`, `failed_to_start`, `interrupted`, plus `abandoned` for MCP calls. These replace the host states `pending/running/done/denied`; a state-mapping shim keeps `app.js` and existing tests working until migrated.

- One atomic transition into `preparing` inside `start_run`; `claim()` is the approval flavor of it and stays the only way a host run starts.
- `policy_blocked` (route policy gate) is distinct from `denied` (user clicked No).
- Run on an already-running record returns the current record (200), not 409.

### Budgets

One injectable budget table: setup, run, teardown, each with its own reserved time. The #114 icacls budgets become the sandboxed setup and teardown entries. Cancel during teardown skips to forced kill but never skips the revoke. A failed revoke sets `teardown_failed`, visible on the record and in the UI.

### Owner scope and Stop

- Turn-scoped runs: runs started inside a live turn (sandboxed `run_shell`, `run_python`, unsandboxed `run_shell`). Cancelled by that turn's Stop.
- Tab-scoped runs: host-card runs and background-agent runs. A host-card run starts after the turn's task has ended, so it is scoped to the card and tab and has its own Stop on the card; turn Stop never touches it.
- There is no "service" scope. A command that is still running with a port open when its run budget fires ends `timed_out`, with the port facts kept and the tree killed.
- `cancel(run_id)` tree-kills and runs teardown. Tree kill only on Stop, timeout or quit. Survivors of a finished command are reported in `children_left`, never silently killed or leaked.
- `ChatTaskStore.cancel` calls `asyncio_task.cancel()`, which raises `CancelledError` at the turn's await. Teardown (revoke) must run outside the cancelled task: shielded, or in the supervisor's own thread or task. Conformance case: Stop during a run, then assert the grants ledger is clean.
- A turn id must exist and Stop needs a handle that maps to it; both come from hardening PR 1.

### Startup reconciliation

At startup, records in `awaiting_approval`, `preparing` or `running` become `interrupted`. Processes are tracked by pid and creation time (or a Windows job object with KILL_ON_JOB_CLOSE) so they can be swept. Startup repair walks both the run records and the grants ledger (`~/.gator/sandbox/grants.json`); grant ids on the record prevent a crash between `preparing` and revoke from leaking an ACL silently.

### Safety limits

Output cap with a truncation marker. Per-tab concurrency cap: reject at the cap (no run queueing) as `failed_to_start` with reason `concurrency_cap`; the model-facing result shows the reason.

### UI

State changes are events. One status row replaces "Still working... (Ns)" ("Preparing the sandbox · 32s", "Taking longer than usual" beside Stop at 30 s). `GET /api/runs?context_id` plus a tab-level event channel serve reloads and runs that change state after the turn's stream has closed; polling is the fallback. The host Run route returns immediately and the card follows the record.

## What the model sees

One result shape on every path: `run_id`, `state`, `exit` (code, hex, class), `facts`, stdout and stderr (capped). `_exit_note` is removed. When the exit is abnormal and facts exist, one neutral line: a crash code can come from a program's exit after it already did its work, so check what it started before saying it is down. Whether a code is a crash value (NTSTATUS-style, >= 0xC0000000) is a fact only.

Command class is observed (exited cleanly, exited with children left, still running with a port open), never declared by the model.

A lint test on the result formatter forbids verdict vocabulary ("probably", "crashed", "not running", "succeeded").

### probe_local_url

Read-only, no approval card. `urls_seen` is the allow-list, but it is attacker-influenceable (any command can print any URL), so the gate lives in the probe:

- http only; host is literally `127.0.0.1`, `[::1]` or `localhost`, resolved once and pinned to loopback; no userinfo.
- Deny the Gator backend ports (read from the running config at call time) and control-plane ports (Docker 2375/2376).
- GET only, no cookies or auth headers, no redirect following (a 3xx is returned as a fact), short timeout, response size cap, per-run probe count cap.
- The response body is untrusted. Each probe is logged on the RunRecord.

### Untrusted output

`run_shell`, `run_python`, `host_command_result` and the probe response are all added to `_HOST_TOOLS` in `web/data_sources.py`; marking is keyed by tool name and silently does not apply otherwise. URLs in output can be probed, never fetched or followed.

## MCP calls

Thin: each MCP tool call gets a `kind=mcp_call` record with server, tool, duration, timeout and state only. A timed-out or cancelled call becomes `abandoned`, not `cancelled`: the worker thread cannot be killed and the server may still finish the side effect. Send MCP `notifications/cancelled` best effort. Cap abandoned workers per server; at the cap mark the server unhealthy and stop dispatching. Own small PR after the sandboxed-path migration.

## Message queue

- Enter while a turn runs queues the message as a chip under the composer (edit, remove, "Send now" = Stop then send).
- The queue is server-side, per tab/context, so reloads and a second window agree. Persist in the same sqlite store as RunRecord if cheap; otherwise a restart loses it.
- One message is popped at a time under the per-context turn lock (atomic, so two windows cannot double-send). Drain only while a UI is attached; otherwise the message stays "queued, will send when you return".
- Sends on `end_turn` or when the turn is parked on an unresolved approval card. A user Stop and an error turn pause the queue ("Queue paused · Resume · Clear").
- A queued message is never approval for a pending card. Card expiry is unchanged (300 s default, 600 s for host cards, per registry entry).
- Snapshot the full composer payload at enqueue (attachments, pasted images, model, skill pin, scoped skill), with a stored-size cap. Queue plain messages only: slash commands, card approvals and failover consent are not queueable.
- Client-generated id per message makes double-Enter idempotent; once popped, a chip is not editable. Small fixed queue cap with a clear message.
- Every queue POST/PUT/PATCH/DELETE route uses `dependencies=[Depends(verify_csrf)]`.
- Prerequisite: a turn id and a single turn-lock owner per context (a turn parked on a card and a new turn on the same context must not both own it).

## Conformance suite

Fake programs written in Python so they behave identically across paths: slow, crash-after-success, spawns a detached child, floods output, ignores Stop, prints a URL, setup hang, teardown hang. Each must end in a defined state within budget with correct facts. Additional cases: `teardown_failed` (injected icacls failure), backend killed mid-run then startup reconciliation, Stop during `preparing` and `awaiting_approval`, double Stop, reload mid-run, concurrency cap.

Budgets are injectable with millisecond values so tests do not sleep for real seconds. Sandboxed-path cases need a Windows runner with AppContainer and icacls; if CI lacks one, tag them and run as a required local or nightly job instead of claiming a CI gate.

## Rollout

Critical path: #172 (exit codes) -> #115 (run-on-host card) -> #114 (sandbox hardening) -> PR1a. #172 and #115 both rewrite `shell_runner/tools.py`, and PR1a's host-path shim must sit on top of #115's `run_on_host` and #172's `_exit_note`, so PR1a is built after both merge. The turn id and per-context turn lock go in `chat.py`, the same region as #171 and #173, so PR1a also builds on those.

- Spec: its own docs-only PR off main (`docs/execution-contract-spec`), so the design is approved before code.
- PR0: replace the verdict text in `_exit_note` with neutral facts (exit code, hex, URLs seen). `_exit_note` exists only on #172's branch (`fix/agent-tool-limits`, commit 034b2041), so PR0 is a follow-up commit on #172, or "PR0 - Stacked on PR172" if split; never branched off main. Existing tests that assert `_exit_note` strings change.
- PR1a: supervisor core, RunRecord, sqlite, startup reconciliation, host path via the shim, conformance harness with host cases. Depends on hardening PR 1 (turn id, per-context turn lock). Base main after #172, #115, #171, #173 merge.
- PR1b: result facts, uniform untrusted marking, `probe_local_url`. Stacked on PR1a.
- PR2: migrate sandboxed `run_shell` and `run_python` (budgets, real Stop, status row). Stacked on PR1b; #114 merges first.
- PR3: message queue (hardening PR 11a). Based on hardening PR 1, not on PR1a; parallel to PR1b/PR2.
- PR4: `mcp_call` records. Stacked on PR1a.

Conflict notes: keep `app.js` edits in one contiguous block or small module, no reformatting; `app.js` has a BOM and LF line endings, so normalize to LF and keep the BOM. Every new POST/PUT/PATCH/DELETE route (Stop, queue) uses `dependencies=[Depends(verify_csrf)]`; do not add to `tests/csrf_route_baseline.txt`.

Each PR grows the conformance suite. `docs/shell-automation-workflows-design.md` covers the Electron shell and workflow runner, a different layer; no conflict. `docs/permissions-matrix.md` rule 2 applies: a run that would need an ask-every-time approval inside a background run ends `policy_blocked`, because nobody is there to approve it.

## Out of scope for this contract (separate fixes)

Tool-routing bugs (shell_runner not offered under a locked skill, the thinking-last 400), unevidenced claims ("fictional data" with no leak check), platform shell mismatch (cmd.exe multi-line input), and the folder-grant size preflight (already guarded by df428715).
