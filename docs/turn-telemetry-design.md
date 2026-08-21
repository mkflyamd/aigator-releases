# Turn Telemetry — Design Specification

## Problem

There is no structured telemetry tying a turn's end to its conversation context. Today:

- `perf.py` records request latency (endpoint name + ms) — no turn IDs, no context linking, in-memory only, resets on restart.
- `usage_log` (SQLite) records `source`, `prompt_preview` (100 chars), `input_tokens`, `output_tokens`, `created_at` — but **no `context_id`, no `task_id`, no turn index, no stop reason, no error**.
- `chat_task_store` holds `task_id` -> `context_id` in memory but logs nothing on turn end.
- Scattered `print()` statements (`[chat] req.model=...`, `[agent] LLM error during stream_turn`) are unstructured with no correlation ID.

You cannot triage "turn 3 of context X ended after a tool failure and the user never sent another message" because **turn-end is never logged with `context_id`**.

## Goal

Structured turn-event logging at every turn boundary, with enough context to:

1. Reconstruct the full lifecycle of any conversation (turn sequence, outcomes, costs).
2. Triage stuck/stalled/errored turns — what tool failed, what the model did next, whether the user continued.
3. Attribute token costs to conversations, not just global totals.

## Turn Lifecycle (current code)

```
chat.py POST /api/chat
  |
  +-- creates task_id (uuid), registers in chat_task_store with context_id
  +-- _run_and_buffer() background task (holds per-context lock)
        |
        +-- stream() generator
              |
              +-- _single_agent_loop OR run_three_agent_loop  (agent_loop.py)
                    |
                    for _ in range(MAX_ITERATIONS):  # turn index
                      |
                      +-- provider.stream_turn()  # one LLM call
                      |     yields: text_delta, thinking_delta, tool_call, done
                      |
                      +-- turn["stop_reason"] == "end_turn"  --> EXIT 1 (normal)
                      +-- stop_reason == "end_turn" + _last_round_errors  --> EXIT 2 (stalled)
                      +-- stop_reason == "tool_use" but tool_calls == []  --> EXIT 3 (empty)
                      +-- any tool result has _terminal flag  --> EXIT 4 (terminal)
                      +-- _bad_tool_streak >= _MAX_BAD_TOOL_RETRIES  --> EXIT 5 (circuit breaker)
                      +-- for-loop completes without break  --> EXIT 6 (max iterations)
                      +-- LLM exception after retries+failover  --> EXIT 7 (LLM error)
                      +-- three-agent: budget exceeded  --> EXIT 8 (budget)
                      +-- three-agent: planner error  --> EXIT 8 (planner error)
                    |
                    verifier: stream_turn + retry loop --> EXIT (verifier fallback)
              |
              +-- finally: persist turns to conversation_store, log_usage()
        |
        +-- finally: chat_task_store.mark_done(), notify_all("chat_done")
        +-- except: cancel or 300s timeout  --> EXIT 9 (cancel/timeout)
```

### All 9 turn-end paths

| #   | Path                       | Location                | `stop_reason`    | Has tool errors?           | User can continue?    |
| --- | -------------------------- | ----------------------- | ---------------- | -------------------------- | --------------------- |
| 1   | Normal end                 | `agent_loop.py:545-556` | `end_turn`       | No                         | Yes (new message)     |
| 2   | Stalled after tool failure | `agent_loop.py:550-554` | `end_turn`       | Yes (`_last_round_errors`) | Yes (Continue button) |
| 3   | Empty tool_calls           | `agent_loop.py:559-562` | `tool_use`       | No                         | Yes                   |
| 4   | Terminal tool result       | `agent_loop.py:598-601` | `tool_use`       | Maybe                      | Yes                   |
| 5   | Circuit breaker            | `agent_loop.py:616-620` | `tool_use`       | Yes (all non-retryable)    | Yes (rephrase)        |
| 6   | Max iterations             | `agent_loop.py:629`     | last turn's      | Maybe                      | Yes (Continue)        |
| 7   | LLM error                  | `agent_loop.py:514-522` | None (exception) | Maybe                      | Yes                   |
| 8   | Budget / planner error     | `agent_loop.py:797-804` | None             | No                         | Yes                   |
| 9   | Cancel / timeout           | `chat.py:1692-1735`     | None             | Maybe                      | Yes (new message)     |

## Design

### 1. New table: `turn_log`

SQLite table alongside the existing `usage_log` (same DB file in `GATOR_DIR/state.db`):

```sql
CREATE TABLE IF NOT EXISTS turn_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id         TEXT NOT NULL,          -- uuid4, unique per turn
    context_id      TEXT NOT NULL,          -- tab/conversation ID
    task_id         TEXT NOT NULL,          -- chat task ID (from chat_task_store)
    turn_index      INTEGER NOT NULL,       -- 0-based iteration within the agent loop
    agent           TEXT NOT NULL,          -- 'single' | 'planner' | 'executor' | 'verifier'
    model           TEXT NOT NULL,          -- resolved model name
    provider        TEXT NOT NULL,          -- 'AnthropicProvider' | 'OpenAIProvider' | ...

    -- Outcome
    outcome         TEXT NOT NULL,          -- see outcome enum below
    stop_reason     TEXT,                   -- 'end_turn' | 'tool_use' | 'max_tokens' | NULL (error)
    tool_calls      TEXT NOT NULL DEFAULT '[]',  -- JSON: [{name, success, error?}, ...]
    tool_error      TEXT,                   -- first tool error message (if any), truncated to 500 chars
    llm_error       TEXT,                   -- LLM exception message (if outcome=llm_error), truncated to 500 chars

    -- Token cost (cumulative for this turn's LLM calls)
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,

    -- Diagnostics
    overflow_prunes  INTEGER NOT NULL DEFAULT 0,  -- context-overflow recovery count
    retry_count      INTEGER NOT NULL DEFAULT 0,  -- transient-retry count
    failover_used    INTEGER NOT NULL DEFAULT 0,  -- 1 if fell over to backup provider
    bad_tool_streak  INTEGER NOT NULL DEFAULT 0,  -- circuit-breaker counter at exit time
    duration_ms      INTEGER NOT NULL DEFAULT 0,  -- wall-clock from turn start to turn end

    -- Conversation context at turn end (for triage without joining other tables)
    history_turns    INTEGER NOT NULL DEFAULT 0,  -- message count in conversation at turn start
    active_skills    TEXT NOT NULL DEFAULT '[]',  -- JSON: ["email", "jira", ...]

    -- User follow-up tracking (filled by the NEXT turn's start, or NULL if no follow-up)
    next_turn_id     TEXT,                   -- turn_id of the next turn in this context, or NULL
    next_turn_delay_s REAL,                  -- seconds between this turn's end and next turn's start

    created_at      TEXT NOT NULL            -- ISO 8601 UTC
);

CREATE INDEX IF NOT EXISTS idx_turn_log_context ON turn_log(context_id, created_at);
CREATE INDEX IF NOT EXISTS idx_turn_log_task ON turn_log(task_id);
CREATE INDEX IF NOT EXISTS idx_turn_log_outcome ON turn_log(outcome);
```

### 2. `outcome` enum

Every turn-end path maps to exactly one outcome:

| outcome             | Exit # | Description                                                     |
| ------------------- | ------ | --------------------------------------------------------------- |
| `end_turn`          | 1      | Normal completion — model stopped on its own                    |
| `stalled`           | 2      | Model stopped after a tool failure — user shown Continue button |
| `empty_tool_use`    | 3      | Model requested tool_use but produced no tool calls             |
| `terminal_tool`     | 4      | A tool returned `_terminal` — loop stopped early                |
| `circuit_breaker`   | 5      | Too many consecutive non-retryable tool errors                  |
| `max_iterations`    | 6      | Hit `MAX_ITERATIONS` (25) without finishing                     |
| `llm_error`         | 7      | LLM exception after retries + failover exhausted                |
| `budget_exceeded`   | 8      | Three-agent: token budget exceeded                              |
| `planner_error`     | 8      | Three-agent: planner LLM call failed                            |
| `cancelled`         | 9      | User cancelled or 300s timeout                                  |
| `verifier_fallback` | —      | Verifier failed, fell back to draft text                        |

### 3. New module: `web/turn_telemetry.py`

```python
"""Structured turn-event logging for triage.

Every LLM turn — start and end — is logged to the turn_log SQLite table with
enough context to reconstruct the full conversation lifecycle and triage
stuck/stalled/errored turns.

Design constraints (matching perf.py's philosophy):
  - SQLite-persisted (survives restart, unlike perf.py's in-memory buffers).
  - Records ONLY metadata: turn IDs, outcome, token counts, error messages
    (truncated), tool names. NEVER message content, tool inputs, or tool
    outputs — those live in conversation_store.
  - Thread-safe: the agent loop runs on the asyncio event loop, but
    task_queue's background worker also calls log_usage from a worker thread.
    Uses aiosqlite for async callers and a sync fallback for the background
    path.
"""
```

#### API

```python
async def log_turn_start(
    turn_id: str,
    context_id: str,
    task_id: str,
    turn_index: int,
    agent: str,           # 'single' | 'planner' | 'executor' | 'verifier'
    model: str,
    provider: str,
    history_turns: int,
    active_skills: list[str],
) -> None:
    """Record the start of a turn. Called at the top of each loop iteration,
    before provider.stream_turn()."""

async def log_turn_end(
    turn_id: str,
    context_id: str,
    task_id: str,
    turn_index: int,
    agent: str,
    outcome: str,         # from the enum above
    stop_reason: str | None,
    tool_calls: list[dict],  # [{name, success, error?}, ...]
    tool_error: str | None,
    llm_error: str | None,
    input_tokens: int,
    output_tokens: int,
    overflow_prunes: int,
    retry_count: int,
    failover_used: bool,
    bad_tool_streak: int,
    duration_ms: int,
) -> None:
    """Record the end of a turn. Called at EVERY exit path in the agent loop."""

async def link_next_turn(context_id: str, prev_turn_id: str, next_turn_id: str) -> None:
    """When a new turn starts, link it to the previous turn in the same context.
    Fills next_turn_id + next_turn_delay_s on the previous turn's row."""

async def get_conversation_timeline(context_id: str, limit: int = 100) -> list[dict]:
    """Return all turns for a conversation, ordered by time, with next-turn
    linking. The primary triage query."""

async def get_turns_by_outcome(outcome: str, limit: int = 50) -> list[dict]:
    """Find all turns with a given outcome (e.g. all 'stalled' turns)."""

async def get_stuck_conversations() -> list[dict]:
    """Find conversations where the last turn was 'stalled' or 'llm_error' AND
    no follow-up turn was logged within 5 minutes — i.e. the user likely gave
    up. The highest-value triage query."""
```

### 4. Instrumentation points

#### 4a. `agent_loop.py` — `_single_agent_loop`

**Turn start** (top of `for _ in range(MAX_ITERATIONS):` loop, line 431):

```python
import turn_telemetry
_turn_id = str(uuid.uuid4())
_turn_start = time.monotonic()
await turn_telemetry.log_turn_start(
    turn_id=_turn_id, context_id=context_id, task_id=task_id,
    turn_index=_, agent="single", model=model, provider=type(provider).__name__,
    history_turns=len(msgs), active_skills=active_skills,
)
```

**Turn end** — at every exit path, before `yield "data: [DONE]\n\n"`:

```python
await turn_telemetry.log_turn_end(
    turn_id=_turn_id, context_id=context_id, task_id=task_id,
    turn_index=_, agent="single",
    outcome="end_turn",  # or "stalled", "circuit_breaker", etc.
    stop_reason=turn["stop_reason"] if turn else None,
    tool_calls=[{"name": tc.name, "success": ...} for tc in tool_calls],
    tool_error=_last_round_errors[0] if _last_round_errors else None,
    llm_error=None,
    input_tokens=_total_input, output_tokens=_total_output,
    overflow_prunes=_overflow_prunes, retry_count=_retry_count,
    failover_used=_failover_used, bad_tool_streak=_bad_tool_streak,
    duration_ms=int((time.monotonic() - _turn_start) * 1000),
)
```

The `task_id` needs to be threaded through from `chat.py` (currently `_single_agent_loop` doesn't receive it). Add `task_id: str` to the function signature.

#### 4b. `agent_loop.py` — `run_three_agent_loop`

Same pattern, but `agent` is `"planner"`, `"executor"`, or `"verifier"` depending on which phase the turn is in. The executor's internal `for _iter in range(MAX_ITERATIONS):` loop each gets its own turn_id.

#### 4c. `chat.py` — cancel/timeout path

In `_run_and_buffer`'s `except` and `finally` blocks (lines 1692-1735), log the cancel/timeout outcome:

```python
await turn_telemetry.log_turn_end(
    turn_id=_current_turn_id, context_id=context_id, task_id=task_id,
    turn_index=0, agent="single",
    outcome="cancelled",
    stop_reason=None, tool_calls=[], tool_error=None, llm_error=None,
    input_tokens=_in_tok, output_tokens=_out_tok,
    overflow_prunes=0, retry_count=0, failover_used=False, bad_tool_streak=0,
    duration_ms=int((time.monotonic() - _turn_start) * 1000),
)
```

#### 4d. `chat.py` — link consecutive turns

At the top of `stream()`, before starting the agent loop, link to the previous turn in this context:

```python
if _previous_turn_id_for_context:
    await turn_telemetry.link_next_turn(context_id, _previous_turn_id_for_context, _turn_id)
```

This requires tracking the last turn_id per context_id (a simple in-memory dict in `turn_telemetry` or `chat_task_store`).

### 5. Triage query surface

A new read-only endpoint for debugging:

```
GET /api/debug/turns/{context_id}       — full turn timeline for a conversation
GET /api/debug/turns?outcome=stalled    — all turns with a given outcome
GET /api/debug/stuck                    — conversations where the user likely gave up
```

These are behind the existing CSRF guard and intended for the developer/debugging UI (not exposed to end users). Output is JSON, ready for a future debug panel.

**Example triage query: "What happened in conversation X?"**

```
GET /api/debug/turns/ctx-abc123

[
  {turn_index: 0, outcome: "end_turn", stop_reason: "tool_use",
   tool_calls: [{name: "read_email", success: true}], input: 1200, output: 450,
   duration_ms: 3200, next_turn_delay_s: 5.2},

  {turn_index: 1, outcome: "stalled", stop_reason: "end_turn",
   tool_calls: [{name: "send_email", success: false, error: "Auth token expired"}],
   tool_error: "Auth token expired", input: 2400, output: 300,
   duration_ms: 1800, next_turn_id: null, next_turn_delay_s: null},
]
```

**Reading this:** Turn 0 called `read_email` successfully, user waited 5.2s, then sent a follow-up. Turn 1 called `send_email`, which failed with "Auth token expired". The model stopped (stalled). No follow-up turn was ever logged (`next_turn_id: null`) — the user gave up.

### 6. Privacy

- `turn_log` records **only metadata**: IDs, outcome, token counts, error messages (truncated to 500 chars), tool names.
- It **never** records: message content, tool inputs, tool outputs, email subjects, user PII.
- `tool_error` and `llm_error` are truncated to 500 chars — enough to diagnose, not enough to leak full payloads.
- The debug endpoints are CSRF-guarded and intended for the developer, not end users.

### 7. Performance

- SQLite writes are async (aiosqlite), non-blocking on the event loop.
- One INSERT per turn start + one INSERT per turn end = 2 writes per turn. At ~1 turn per 3-30 seconds, this is negligible.
- Indexed on `(context_id, created_at)` for fast timeline queries.
- The `next_turn_id` / `next_turn_delay_s` columns are UPDATE'd (not INSERT'd) when the next turn starts — one UPDATE per turn.
- Table grows unbounded; a future cleanup job can prune rows older than 30 days (same TTL as `chat_task_store`'s `TASK_TTL_SECONDS`).

### 8. Migration

- `CREATE TABLE IF NOT EXISTS` in `task_queue.py`'s `init_db()` (which already creates `usage_log`).
- No data migration — the table starts empty and fills as new turns run.
- Existing `usage_log` is untouched (backward compat); `turn_log` supplements it with the conversation context that `usage_log` lacks.

### 9. What this does NOT cover (out of scope)

- **Distributed tracing** (OpenTelemetry, Jaeger) — overkill for a single-process desktop app.
- **Message content logging** — by design, for privacy. Content lives in `conversation_store` (in-memory).
- **Real-time streaming metrics** — `perf.py` already covers request latency. This design covers turn-level outcomes, not intra-turn token latency.
- **Frontend debug UI** — the endpoints exist; a visual triage panel is a follow-up.
