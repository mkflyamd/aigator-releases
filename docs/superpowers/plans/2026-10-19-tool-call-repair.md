# Tool-Call Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A rejected tool call (missing/blank required argument, schema violation) gets exactly one repair turn in both agent loops; if the repair also fails the user sees a banner naming the tool and fields, and Continue resubmits the original request plus a failure note.

**Architecture:** A new pure module `web/tool_repair.py` builds structured rejection summaries and the `stalled` SSE event. `web/agent_loop.py` drops the pre-emptive stall, counts schema rejections, and emits the structured event from the real breakers and the provider-failure exits. `execute_tool` returns the required fields with a corrected hint. `web/static/app.js` carries the event's `retry_note` into the Continue button.

**Tech Stack:** Python 3 / pytest (asyncio_mode auto), FastAPI SSE loop in `web/`, vanilla JS tested with `node --test`.

## Global Constraints

- Commit messages are conventional (`feat:` / `fix:` / `test:`) and contain NO `Co-Authored-By` line (CLAUDE.md).
- The product is "AI Gator"; never call it a POC.
- The only fake credential in tests/docs is `aigator-fake-api-key` (SP1 needs none).
- LLM calls go through `llm.gateway` (SP1 adds none).
- SP1 adds no POST/PUT/PATCH/DELETE routes, so no `verify_csrf` work.
- The `stalled` SSE JSON must keep `stalled` as its first key: `web/routes/chat.py` holds loop-emitted stalls by the prefix `data: {"stalled"`.
- Do the least needed; no new settings, no server-side resume state, the Retry/Stop path and the doom-loop detector (`_DOOM_LOOP_THRESHOLD = 3`) stay as they are.
- Run commands from the repo root. Python: `uv run pytest ...`. JS: `node --test tests/<file>.test.js`.

---

## File Structure

- Create `web/tool_repair.py` — `REJECTED_ERRORS`, `rejection_summaries`, `rejection_summary_text`, `stalled_chunk`.
- Modify `web/agent_loop.py` — import, `_NON_RETRYABLE_TOOL_ERRORS`, `_generic_tool_summary`, remove pre-emptive breaker, `_last_rejections`, structured breakers, provider-failure stalls (single loop and executor).
- Modify `web/app.py` — `execute_tool` `missing_required_params` payload.
- Modify `web/static/app.js` — `_continueRetryNote`, `_lastUserRequestText`, `_continueRequestText`, Continue handler, `_showBrowserConfirmCard` refactor.
- Create `tests/test_tool_repair.py` — all Python coverage (built up task by task).
- Create `tests/stalled_continue.test.js` — Continue behavior.
- Modify `tests/test_streaming_stall_recovery.py` — remove the pre-emptive test, fix docstring.

---

### Task 1: `tool_repair` helpers

**Files:**

- Create: `web/tool_repair.py`
- Create: `tests/test_tool_repair.py`

**Interfaces:**

- Consumes: nothing.
- Produces:
  - `REJECTED_ERRORS: tuple[str, str]`
  - `rejection_summaries(tool_calls: list, results: list) -> list[dict]` — `[{"tool": str, "fields": list[str]}]`
  - `rejection_summary_text(result: dict) -> str | None`
  - `stalled_chunk(summaries: list[dict]) -> str` — `data: {...}\n\n` with keys `stalled`, `message`, `failed_calls`, `retry_note` in that order.
  - Test-file harness reused by Tasks 2–5: `_tc`, `_tool_turn`, `_text_turn`, `_Provider`, `_fake_tool`, `_run_single`, `_run_three`, `_events`, `_stalled`.

- [ ] **Step 1: Write the failing test (with the shared harness)**

Create `tests/test_tool_repair.py`:

```python
"""A rejected tool call (missing/blank args, schema violation) gets exactly one
repair turn; the Continue banner appears only when the repair also fails."""

import asyncio
import json
import sys
import pathlib
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest

from agent_loop import _single_agent_loop, run_three_agent_loop
from tool_repair import rejection_summaries, rejection_summary_text, stalled_chunk


def _tc(name="run_python", inputs=None, call_id="t1"):
    return SimpleNamespace(name=name, inputs={} if inputs is None else inputs, id=call_id)


def _tool_turn(*calls):
    return [{"type": "done", "stop_reason": "tool_use", "tool_calls": list(calls),
             "raw_content": [], "usage": {}}]


def _text_turn(text):
    return [{"type": "text_delta", "text": text},
            {"type": "done", "stop_reason": "end_turn", "tool_calls": [],
             "raw_content": [{"type": "text", "text": text}], "usage": {}}]


class _Provider:
    context_window = 200_000

    def __init__(self, turns):
        self._turns = turns
        self.calls = 0
        self.seen = []

    def normalize_tool_schema(self, t):
        return t

    def build_assistant_message(self, raw):
        return {"role": "assistant", "content": raw}

    def build_tool_result_message(self, tool_calls, results):
        return {"role": "user", "content": json.dumps(results)}

    async def stream_turn(self, model, system, msgs, tools):
        self.seen.append(list(msgs))
        turn = self._turns[self.calls]
        self.calls += 1
        if isinstance(turn, Exception):
            raise turn
        for event in turn:
            yield event


def _fake_tool():
    """execute_tool stand-in: run_python needs `code`; records only real executions."""
    executed = []

    async def execute_tool(name, inputs, **kw):
        if not str(inputs.get("code", "")).strip():
            return {"error": "missing_required_params", "tool": name, "missing": ["code"],
                    "required": ["code"], "hint": "Call again with every required argument: code."}
        executed.append(inputs)
        return {"stdout": "ok"}

    return execute_tool, executed


def _run_single(provider, execute_tool):
    async def go():
        return [c async for c in _single_agent_loop(
            provider=provider, model="m", system="s",
            msgs=[{"role": "user", "content": "go"}],
            normalized_tools=[{"name": "run_python", "input_schema": {"type": "object"}}],
            execute_tool=execute_tool, COM_BOUND_TOOLS=set(), TOOL_STATUS={},
            _tool_toast=lambda *a, **k: None, _SLACK_SAFE_MSG="__safe__",
        )]
    return asyncio.run(go())


def _run_three(provider, execute_tool):
    async def go():
        return [c async for c in run_three_agent_loop(
            provider, "m", "s", [{"role": "user", "content": "go"}],
            [{"name": "run_python", "input_schema": {"type": "object"}}],
            execute_tool, set(), {}, lambda *a, **k: None, "__safe__", token_budget=0,
        )]
    return asyncio.run(go())


def _events(chunks):
    return [json.loads(c[6:]) for c in chunks
            if c.startswith("data: ") and not c.startswith("data: [DONE]")]


def _stalled(chunks):
    return [e for e in _events(chunks) if e.get("stalled")]


# ── tool_repair helpers ──────────────────────────────────────────────────────

def test_rejection_summaries_name_tool_and_fields():
    calls = [_tc("run_python"), _tc("write_file", call_id="t2")]
    results = [
        {"error": "missing_required_params", "tool": "run_python", "missing": ["code"]},
        {"error": "invalid_tool_input", "tool": "write_file", "field": "path", "reason": "bad"},
    ]
    assert rejection_summaries(calls, results) == [
        {"tool": "run_python", "fields": ["code"]},
        {"tool": "write_file", "fields": ["path"]},
    ]


def test_rejection_summaries_fall_back_to_call_name_without_structure():
    assert rejection_summaries([_tc("x")], [{"error": "json decode failure"}]) == [
        {"tool": "x", "fields": []},
    ]


def test_stalled_chunk_names_tool_fields_and_carries_retry_note():
    chunk = stalled_chunk([{"tool": "run_python", "fields": ["code"]}])
    assert chunk.startswith('data: {"stalled"')  # routes/chat.py holds stalled chunks by this prefix
    evt = json.loads(chunk[6:])
    assert evt["stalled"] is True
    assert "run_python" in evt["message"] and "code" in evt["message"]
    assert "run_python" in evt["retry_note"] and "code" in evt["retry_note"]
    assert evt["failed_calls"] == [{"tool": "run_python", "fields": ["code"]}]


def test_rejection_summary_text():
    assert rejection_summary_text(
        {"error": "missing_required_params", "tool": "run_python", "missing": ["code"]}
    ) == "Rejected run_python: missing code"
    assert rejection_summary_text(
        {"error": "invalid_tool_input", "tool": "write_file", "field": "path"}
    ) == "Rejected write_file: invalid path"
    assert rejection_summary_text({"error": "boom"}) is None
    assert rejection_summary_text("text") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tool_repair.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'tool_repair'`.

- [ ] **Step 3: Write minimal implementation**

Create `web/tool_repair.py`:

```python
"""Structured description of rejected tool calls, shared by both agent loops."""
from __future__ import annotations

import json

REJECTED_ERRORS = ("missing_required_params", "invalid_tool_input")


def _fields(result: dict) -> list[str]:
    if result.get("error") == "missing_required_params":
        return [str(f) for f in result.get("missing") or []]
    field = result.get("field")
    return [str(field)] if field else []


def rejection_summaries(tool_calls: list, results: list) -> list[dict]:
    """One {"tool", "fields"} entry per failed call in a round (names from the tool's own result)."""
    out = []
    for tc, result in zip(tool_calls, results):
        if not (isinstance(result, dict) and result.get("error")):
            continue
        out.append({"tool": str(result.get("tool") or tc.name), "fields": _fields(result)})
    return out


def rejection_summary_text(result: dict) -> str | None:
    """One-line tool_result summary for a rejected call, or None for any other result."""
    if not (isinstance(result, dict) and result.get("error") in REJECTED_ERRORS):
        return None
    fields = ", ".join(_fields(result))
    label = "missing" if result["error"] == "missing_required_params" else "invalid"
    return f"Rejected {result.get('tool', 'tool')}: {label} {fields}".strip()


def stalled_chunk(summaries: list[dict]) -> str:
    """SSE `stalled` event naming the failed tool(s) and fields; `retry_note` feeds Continue."""
    parts = [
        f"{s['tool']} ({', '.join(s['fields'])})" if s["fields"] else s["tool"]
        for s in summaries
    ]
    names = "; ".join(parts) or "tool"
    payload = {
        "stalled": True,
        "message": f"Gator could not form a valid call to {names} after one repair attempt "
                   "— click Continue to retry.",
        "failed_calls": summaries,
        "retry_note": f"Note: the previous attempt failed because the call to {names} had "
                      "missing or invalid arguments. Supply every required argument this time.",
    }
    return f"data: {json.dumps(payload)}\n\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tool_repair.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add web/tool_repair.py tests/test_tool_repair.py
git commit -m "feat: add tool_repair helpers describing rejected tool calls"
```

---

### Task 2: Accurate rejection payload from `execute_tool`

**Files:**

- Modify: `web/app.py` (the `missing_required_params` return in `execute_tool`, ~lines 521-531)
- Test: `tests/test_tool_repair.py`

**Interfaces:**

- Consumes: nothing from Task 1.
- Produces: `execute_tool` result `{"error": "missing_required_params", "tool": str, "missing": list[str], "required": list[str], "hint": str}`; the hint contains every required field name.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tool_repair.py`:

```python
# ── real execute_tool: a rejected call never runs the tool ───────────────────

async def test_rejected_call_never_executes_and_reports_required_fields(monkeypatch):
    import shared
    from app import execute_tool

    ran = []

    def probe(code: str):
        ran.append(code)
        return {"stdout": code}

    monkeypatch.setitem(shared.TOOL_DISPATCH, "repair_probe", probe)
    for inputs in ({}, {"code": ""}, {"code": "   "}):
        result = await execute_tool("repair_probe", inputs)
        assert result["error"] == "missing_required_params"
        assert result["tool"] == "repair_probe"
        assert result["missing"] == ["code"]
        assert result["required"] == ["code"]
        assert "code" in result["hint"]
    assert ran == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tool_repair.py::test_rejected_call_never_executes_and_reports_required_fields -v`
Expected: FAIL with `KeyError: 'required'`.

- [ ] **Step 3: Write minimal implementation**

In `web/app.py`, replace the payload:

```python
                return {
                    "error": "missing_required_params",
                    "tool": name,
                    "missing": missing,
                    "hint": (
                        "Required arguments are missing — they were likely truncated "
                        "because the payload exceeded the output budget. Reduce the "
                        "payload size or split it into smaller chunked calls."
                    ),
                }
```

with:

```python
                return {
                    "error": "missing_required_params",
                    "tool": name,
                    "missing": missing,
                    "required": required,
                    "hint": (
                        f"Call {name} again with every required argument: {', '.join(required)}. "
                        "If a large payload was cut off, split it into smaller calls."
                    ),
                }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tool_repair.py::test_rejected_call_never_executes_and_reports_required_fields -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/app.py tests/test_tool_repair.py
git commit -m "fix: tell the model which required arguments it omitted"
```

---

### Task 3: Single-loop repair turn and structured breaker

**Files:**

- Modify: `web/agent_loop.py` (import after the `tool_pipeline` import block; `_NON_RETRYABLE_TOOL_ERRORS` ~232-262; pre-emptive breaker ~850-872; `_bad_tool_streak` init; breaker ~1265-1286; two "circuit breaker + narration cap" comments)
- Modify: `tests/test_streaming_stall_recovery.py` (delete `test_circuit_breaker_fires_on_streak_1_before_second_llm_call`, lines ~51-106 including its section-header comment; fix docstring item 2)
- Test: `tests/test_tool_repair.py`

**Interfaces:**

- Consumes: `rejection_summaries`, `stalled_chunk` from Task 1.
- Produces: `_last_rejections: list[dict]`, a local variable of `_single_agent_loop`, set on every all-bad round; the real breaker yields `stalled_chunk(_last_rejections)`. Task 4 reads `_last_rejections` and `_bad_tool_streak`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tool_repair.py`:

```python
# ── single-agent loop ────────────────────────────────────────────────────────

def test_missing_field_gets_exactly_one_repair_call_and_task_resumes():
    execute, executed = _fake_tool()
    provider = _Provider([
        _tool_turn(_tc(inputs={})),
        _tool_turn(_tc(inputs={"code": "print(1)"})),
        _text_turn("The script ran and printed 1, so the task is complete."),
    ])
    chunks = _run_single(provider, execute)
    assert provider.calls == 3
    assert executed == [{"code": "print(1)"}]
    assert not _stalled(chunks)
    # the repair call saw the structured rejection
    repair_ctx = provider.seen[1][-1]["content"]
    assert '"missing": ["code"]' in repair_ctx and '"tool": "run_python"' in repair_ctx
    assert chunks[-1] == "data: [DONE]\n\n"


def test_repair_that_fails_again_stalls_naming_tool_and_fields():
    execute, executed = _fake_tool()
    provider = _Provider([
        _tool_turn(_tc(inputs={})),
        _tool_turn(_tc(inputs={})),
        _text_turn("unexpected third call"),
    ])
    chunks = _run_single(provider, execute)
    assert provider.calls == 2
    assert executed == []
    stalled = _stalled(chunks)
    assert len(stalled) == 1
    assert "run_python" in stalled[0]["message"] and "code" in stalled[0]["message"]
    assert stalled[0]["failed_calls"] == [{"tool": "run_python", "fields": ["code"]}]
    assert not any("could not form valid tool calls" in c for c in chunks)
    assert chunks[-1] == "data: [DONE]\n\n"


def test_successful_repair_resets_the_repair_budget():
    execute, executed = _fake_tool()
    provider = _Provider([
        _tool_turn(_tc(inputs={})),
        _tool_turn(_tc(inputs={"code": "1"})),
        _tool_turn(_tc(inputs={})),
        _tool_turn(_tc(inputs={"code": "2"})),
        _text_turn("Both scripts ran successfully and the task is complete."),
    ])
    chunks = _run_single(provider, execute)
    assert provider.calls == 5
    assert executed == [{"code": "1"}, {"code": "2"}]
    assert not _stalled(chunks)


def test_schema_violation_counts_as_a_rejected_call():
    async def execute(name, inputs, **kw):
        return {"error": "invalid_tool_input", "tool": name, "field": "code",
                "reason": "123 is not of type 'string'", "hint": "Fix 'code'."}

    provider = _Provider([
        _tool_turn(_tc(inputs={"code": 123})),
        _tool_turn(_tc(inputs={"code": 456})),
        _text_turn("unexpected third call"),
    ])
    chunks = _run_single(provider, execute)
    assert provider.calls == 2
    assert _stalled(chunks)[0]["failed_calls"] == [{"tool": "run_python", "fields": ["code"]}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tool_repair.py -k "repair_call or fails_again or resets_the or schema_violation" -v`
Expected: FAIL — `provider.calls == 1` instead of 3/2 (the pre-emptive stall), and `KeyError: 'failed_calls'`.

- [ ] **Step 3: Write minimal implementation**

All edits in `web/agent_loop.py` (match on text, not line numbers).

1. Import — after the `tool_pipeline` import block that ends `    select_tools_with_budget,\n)`, add:

```python
from tool_repair import rejection_summaries, stalled_chunk
```

2. `_NON_RETRYABLE_TOOL_ERRORS` — add the new entry directly after `"missing_required_params",`:

```python
_NON_RETRYABLE_TOOL_ERRORS = (
    "missing_required_params",
    "invalid_tool_input",
```

3. Delete the whole pre-emptive breaker at the top of `for _ in range(MAX_ITERATIONS):` — from the comment line `# Circuit breaker: if the previous round had a bad-tool streak and we are` through its final `return`. The loop body must then start directly with `turn = None`:

```python
    for _ in range(MAX_ITERATIONS):
        turn = None
        _overflow_prunes = 0
        _failover_used = False
        _any_text_streamed = False
```

4. After the single loop's `_bad_tool_streak = 0  # consecutive rounds where ALL tool calls were non-retryable errors` line, add:

```python
    _last_rejections: list[dict] = []  # {tool, fields} per failed call in the latest all-bad round
```

5. Update the two comments: `(for circuit breaker + narration cap)` → `(for telemetry + narration cap)` and `# update for next iteration's circuit breaker + narration cap` → `# update for next iteration's telemetry + narration cap`.

6. Replace the single-loop breaker. Old:

```python
        if all_non_retryable:
            _bad_tool_streak += 1
            if _bad_tool_streak >= _MAX_BAD_TOOL_RETRIES:
                _names = ", ".join(tc.name for tc in tool_calls)
                yield f"data: {json.dumps({'text': f'The model could not form valid tool calls for {_names} after {_bad_tool_streak} attempts. Try rephrasing your request or switching to a more capable model.'})}\n\n"
```

New (the lines after the yield — `_log_turn_end_safe(... "circuit_breaker" ...)`, `[DONE]`, `return` — stay as they are):

```python
        if all_non_retryable:
            _bad_tool_streak += 1
            _last_rejections = rejection_summaries(tool_calls, results)
            if _bad_tool_streak >= _MAX_BAD_TOOL_RETRIES:
                yield stalled_chunk(_last_rejections)
```

7. In `tests/test_streaming_stall_recovery.py`: delete the section comment `# ── P0-1/Gap2: circuit breaker pre-empts next LLM call when bad_tool_streak >= 1 ──` and the whole `test_circuit_breaker_fires_on_streak_1_before_second_llm_call` function (it asserts `llm_call_count == 1`, the removed behavior). Change docstring item 2 to `2. a rejected tool call gets one repair turn before the circuit breaker stalls (tests/test_tool_repair.py)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tool_repair.py tests/test_streaming_stall_recovery.py tests/test_agent_loop_stall.py tests/test_agent_loop_indicator.py tests/test_mcp_tool_pipeline.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/agent_loop.py tests/test_tool_repair.py tests/test_streaming_stall_recovery.py
git commit -m "fix: give rejected tool calls one repair turn before stalling"
```

---

### Task 4: Provider failure after a rejection, and field-naming summaries

**Files:**

- Modify: `web/agent_loop.py` (import line; `_generic_tool_summary`; single-loop exits)
- Test: `tests/test_tool_repair.py`

**Interfaces:**

- Consumes: `rejection_summary_text`, `stalled_chunk` (Task 1); `_bad_tool_streak`, `_last_rejections` (Task 3).
- Produces: `_generic_tool_summary(result)` returns `"Rejected <tool>: missing <fields>"` for rejected calls (feeds the `tool_result` event summary and the watchdog's `_last_tool_error`); the single-loop failure exits emit `stalled_chunk(_last_rejections)` when `_bad_tool_streak > 0`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tool_repair.py`:

```python
def test_provider_failure_during_repair_stalls_with_the_failed_tool():
    execute, _ = _fake_tool()
    provider = _Provider([_tool_turn(_tc(inputs={})), ValueError("provider exploded")])
    chunks = _run_single(provider, execute)
    stalled = _stalled(chunks)
    assert len(stalled) == 1
    assert stalled[0]["failed_calls"] == [{"tool": "run_python", "fields": ["code"]}]
    assert chunks[-1] == "data: [DONE]\n\n"


def test_rejected_call_tool_result_names_missing_fields_for_the_watchdog_banner():
    # routes/chat.py's idle watchdog quotes the last error tool_result summary
    execute, _ = _fake_tool()
    provider = _Provider([_tool_turn(_tc(inputs={})), _tool_turn(_tc(inputs={}))])
    results = [e["tool_result"] for e in _events(_run_single(provider, execute)) if "tool_result" in e]
    assert results[0]["status"] == "error"
    assert "code" in results[0]["summary"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tool_repair.py -k "provider_failure_during_repair or watchdog_banner" -v`
Expected: FAIL — `IndexError`/`assert 1 == len(...)` for the missing stalled event, and `assert 'code' in 'Error: missing_required_params'`.

- [ ] **Step 3: Write minimal implementation**

In `web/agent_loop.py`:

1. Widen the import: `from tool_repair import rejection_summaries, rejection_summary_text, stalled_chunk`.

2. `_generic_tool_summary` — directly after its docstring `"""Fallback one-line summary when _tool_toast returns None."""`, before `if isinstance(result, dict):`:

```python
    rejected = rejection_summary_text(result)
    if rejected:
        return rejected
```

3. Failover-declined exit — old:

```python
                            yield f"data: {json.dumps({'text': 'LLM stream stalled — failover declined.'})}\n\n"
```

new:

```python
                            yield f"data: {json.dumps({'text': 'LLM stream stalled — failover declined.'})}\n\n"
                            if _bad_tool_streak:
                                yield stalled_chunk(_last_rejections)
```

4. LLM error exit — old:

```python
                    yield f"data: {json.dumps({'text': f'LLM error: {exc}'})}\n\n"
```

new (the added `if` is one level shallower than the yield, i.e. at the `except` block's body indent):

```python
                    yield f"data: {json.dumps({'text': f'LLM error: {exc}'})}\n\n"
                if _bad_tool_streak:
                    yield stalled_chunk(_last_rejections)
```

5. No-response exit — old:

```python
            yield f"data: {json.dumps({'text': 'No response from model.'})}\n\n"
```

new:

```python
            yield f"data: {json.dumps({'text': 'No response from model.'})}\n\n"
            if _bad_tool_streak:
                yield stalled_chunk(_last_rejections)
```

(Each of the three existing statements that follow — `_log_turn_end_safe`, `[DONE]`, `return` — is unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tool_repair.py tests/test_agent_loop_stall.py tests/test_streaming_stall_recovery.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/agent_loop.py tests/test_tool_repair.py
git commit -m "fix: stall with the failed tool when the provider errors after a rejected call"
```

---

### Task 5: Executor loop

**Files:**

- Modify: `web/agent_loop.py` (`run_three_agent_loop` executor: `_bad_tool_streak` init, breaker, "Executor error" exit)
- Test: `tests/test_tool_repair.py`

**Interfaces:**

- Consumes: `rejection_summaries`, `stalled_chunk` (Task 1); `invalid_tool_input` already counted (Task 3).
- Produces: executor `_last_rejections`; breaker and executor-error exit emit `stalled_chunk(_last_rejections)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tool_repair.py`:

```python
# ── executor loop ────────────────────────────────────────────────────────────

def _planner_turn():
    return _text_turn("1. Run the script.")


def test_executor_repair_that_fails_again_stalls_with_structured_event():
    execute, executed = _fake_tool()
    provider = _Provider([
        _planner_turn(),
        _tool_turn(_tc(inputs={})),
        _tool_turn(_tc(inputs={})),
        _text_turn("unexpected"),
    ])
    chunks = _run_three(provider, execute)
    assert provider.calls == 3  # planner + original + one repair
    assert executed == []
    stalled = _stalled(chunks)
    assert len(stalled) == 1
    assert stalled[0]["failed_calls"] == [{"tool": "run_python", "fields": ["code"]}]
    assert not any("could not form valid tool calls" in c for c in chunks)
    assert chunks[-1] == "data: [DONE]\n\n"


def test_executor_successful_repair_resumes_the_task():
    execute, executed = _fake_tool()
    provider = _Provider([
        _planner_turn(),
        _tool_turn(_tc(inputs={})),
        _tool_turn(_tc(inputs={"code": "print(1)"})),
        _text_turn("The script ran and printed 1, so the task is complete."),
        _text_turn("The script ran and printed 1, so the task is complete."),
    ])
    chunks = _run_three(provider, execute)
    assert executed == [{"code": "print(1)"}]
    assert not _stalled(chunks)


def test_executor_provider_failure_after_rejection_stalls():
    execute, _ = _fake_tool()
    provider = _Provider([_planner_turn(), _tool_turn(_tc(inputs={})), ValueError("provider exploded")])
    chunks = _run_three(provider, execute)
    assert _stalled(chunks)[0]["failed_calls"] == [{"tool": "run_python", "fields": ["code"]}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tool_repair.py -k executor -v`
Expected: `repair_that_fails_again` and `provider_failure_after_rejection` FAIL (`IndexError`: no stalled event; plain "Executor: model could not form valid tool calls" text instead). `successful_repair_resumes` already PASSES — it is the regression guard that the executor loop must keep its one repair turn.

- [ ] **Step 3: Write minimal implementation**

In `web/agent_loop.py`, inside `run_three_agent_loop`'s executor section:

1. After `    _bad_tool_streak = 0  # consecutive all-bad-tool rounds in executor` add:

```python
    _last_rejections: list[dict] = []
```

2. Replace the executor breaker. Old:

```python
            _bad_tool_streak += 1
            if _bad_tool_streak >= _MAX_BAD_TOOL_RETRIES:
                _names = ", ".join(tc.name for tc in tool_calls)
                yield f"data: {json.dumps({'text': f'Executor: model could not form valid tool calls for {_names} after {_bad_tool_streak} attempts. Try rephrasing or switching model.'})}\n\n"
```

New (following lines unchanged):

```python
            _bad_tool_streak += 1
            _last_rejections = rejection_summaries(tool_calls, results)
            if _bad_tool_streak >= _MAX_BAD_TOOL_RETRIES:
                yield stalled_chunk(_last_rejections)
```

3. Executor error exit — old:

```python
                yield f"data: {json.dumps({'text': f'Executor error: {exc}'})}\n\n"
```

new:

```python
                yield f"data: {json.dumps({'text': f'Executor error: {exc}'})}\n\n"
                if _bad_tool_streak:
                    yield stalled_chunk(_last_rejections)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tool_repair.py tests/test_mcp_tool_pipeline.py tests/test_agent_loop_stall.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/agent_loop.py tests/test_tool_repair.py
git commit -m "fix: executor loop stalls with the failed tool and fields after one repair"
```

---

### Task 6: Continue resubmits the original request plus the failure note

**Files:**

- Modify: `web/static/app.js` (`_exhaustedMessage` declaration; `msg.stalled` branch ~13727; banner block ~13873-13896; new helpers above `_pinConfirmCardInView`; `_showBrowserConfirmCard`)
- Create: `tests/stalled_continue.test.js`

**Interfaces:**

- Consumes: the `stalled` event's `retry_note` string (Task 1).
- Produces: `_lastUserRequestText(tabId) -> string`; `_continueRequestText(lastUserText, retryNote) -> string`; stream-scoped `_continueRetryNote`.

- [ ] **Step 1: Write the failing test**

Create `tests/stalled_continue.test.js`:

```js
// A stall caused by a rejected tool call must make Continue resubmit the original
// request plus the failure note; every other stall keeps the plain Continue prompt.
// The real handler code is cut out of app.js and run against fake state.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function braceBlock(startMarker) {
  const start = source.indexOf(startMarker);
  assert(start > 0, `${startMarker} not found in app.js`);
  const open = source.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < source.length; i++) {
    if (source[i] === '{') depth++;
    if (source[i] === '}' && --depth === 0) return source.slice(open + 1, i);
  }
  throw new Error(`${startMarker} block not closed`);
}

function fn(name) {
  const match = source.match(new RegExp(`function ${name}\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}`));
  assert(match, `${name} not found in app.js`);
  return match[0];
}

const stalledBranch = braceBlock('} else if (msg.stalled) {');
const bannerBlock = braceBlock('if (_streamExhausted) {');
const helpers = `${fn('_lastUserRequestText')}\n${fn('_continueRequestText')}`;

const RETRY =
  'Note: the previous attempt failed because the call to run_python (code) had missing or invalid arguments.';

function onStalled(msg) {
  const ctx = { msg, _streamExhausted: false, _exhaustedMessage: '', _continueRetryNote: '' };
  vm.runInNewContext(stalledBranch, ctx);
  return ctx;
}

// stalled event: banner text and retry note are captured
let ctx = onStalled({
  stalled: true,
  message: 'Gator could not form a valid call to run_python (code)',
  retry_note: RETRY,
});
assert.strictEqual(ctx._streamExhausted, true);
assert.strictEqual(ctx._exhaustedMessage, 'Gator could not form a valid call to run_python (code)');
assert.strictEqual(ctx._continueRetryNote, RETRY);

// stalled event without a note (watchdog, end-of-turn failure) leaves the note empty
ctx = onStalled({ stalled: true, message: 'Gator stopped after going silent' });
assert.strictEqual(ctx._continueRetryNote, '');

function clickContinue({ retryNote, history, requestTabId = 'tab-1', activeTabId = 'tab-1' }) {
  const created = [];
  const input = { textContent: '', dispatchEvent() {} };
  const form = {
    submits: 0,
    requestSubmit() {
      this.submits++;
    },
  };
  const el = () => {
    const e = { className: '', textContent: '', children: [], listeners: {}, removed: false };
    e.appendChild = (c) => e.children.push(c);
    e.addEventListener = (type, cb) => {
      e.listeners[type] = cb;
    };
    e.remove = () => {
      e.removed = true;
    };
    created.push(e);
    return e;
  };
  const prose = { parentElement: { appendChild() {} } };
  const state = {
    document: {
      createElement: el,
      getElementById: (id) => (id === 'chat-input' ? input : id === 'chat-form' ? form : null),
    },
    Event: function Event() {},
    prose,
    msgDiv: {},
    requestTabId,
    _activeTabId: activeTabId,
    _exhaustedMessage: 'banner text',
    _continueRetryNote: retryNote,
    _loadTabHistory: () => history,
  };
  vm.runInNewContext(`${helpers}\n${bannerBlock}`, state);
  const btn = created.find((e) => e.className === 'exhausted-continue-btn');
  assert(btn, 'Continue button created');
  btn.listeners.click();
  return { input, form, banner: created[0] };
}

const history = [
  { role: 'user', content: 'record my demo' },
  { role: 'assistant', content: 'working' },
];

// rejected-call stall: original request + note, resubmitted once
let r = clickContinue({ retryNote: RETRY, history });
assert.strictEqual(r.input.textContent, `record my demo\n\n${RETRY}`);
assert.strictEqual(r.form.submits, 1);

// no note: the plain Continue prompt, as before
r = clickContinue({ retryNote: '', history });
assert.strictEqual(r.input.textContent, 'Continue where you left off.');
assert.strictEqual(r.form.submits, 1);

// note but no recorded user request: plain Continue
r = clickContinue({ retryNote: RETRY, history: [] });
assert.strictEqual(r.input.textContent, 'Continue where you left off.');

// note-carrying Continue must not resubmit a request into a different tab
r = clickContinue({ retryNote: RETRY, history, requestTabId: 'tab-1', activeTabId: 'tab-2' });
assert.strictEqual(r.form.submits, 0);
assert.strictEqual(r.banner.removed, false);

console.log('stalled_continue: all assertions passed');
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test tests/stalled_continue.test.js`
Expected: FAIL with `AssertionError: _lastUserRequestText not found in app.js`.

- [ ] **Step 3: Write minimal implementation**

In `web/static/app.js` (match text exactly; the file may use CRLF line endings — keep them):

1. Declaration — old `  let _exhaustedMessage = '';\n  let _abortCtrl = new AbortController();` → add a line between:

```js
let _exhaustedMessage = '';
let _continueRetryNote = '';
let _abortCtrl = new AbortController();
```

2. `msg.stalled` branch — after the `_exhaustedMessage = msg.message || '...';` statement add:

```js
_continueRetryNote = typeof msg.retry_note === 'string' ? msg.retry_note : '';
```

3. Banner block — old:

```js
        btn.textContent = 'Continue';
        btn.addEventListener('click', () => {
          banner.remove();
          const chatInput = document.getElementById('chat-input');
          const chatForm = document.getElementById('chat-form');
          if (chatInput && chatForm) {
            chatInput.textContent = 'Continue where you left off.';
```

new:

```js
        btn.textContent = 'Continue';
        const _continueTabId = requestTabId;
        const _continueText = _continueRequestText(
          _lastUserRequestText(_continueTabId),
          _continueRetryNote,
        );
        btn.addEventListener('click', () => {
          if (_continueRetryNote && _continueTabId !== _activeTabId) return;
          banner.remove();
          const chatInput = document.getElementById('chat-input');
          const chatForm = document.getElementById('chat-form');
          if (chatInput && chatForm) {
            chatInput.textContent = _continueText;
```

4. Helpers — directly above `function _pinConfirmCardInView(card) {` add:

```js
function _lastUserRequestText(tabId) {
  const last = [...(_loadTabHistory(tabId) || [])].reverse().find((e) => e?.role === 'user');
  return typeof last?.content === 'string' ? last.content : '';
}

// A stall caused by a rejected tool call resubmits the original request plus the
// failure note; any other stall keeps the plain "Continue" prompt.
function _continueRequestText(lastUserText, retryNote) {
  if (!retryNote || !lastUserText) return 'Continue where you left off.';
  return `${lastUserText}\n\n${retryNote}`;
}
```

5. `_showBrowserConfirmCard` — replace

```js
const _lastUserText = (() => {
  const last = [..._loadTabHistory(_tabId)].reverse().find((e) => e?.role === 'user');
  return typeof last?.content === 'string' ? last.content : '';
})();
```

with:

```js
const _lastUserText = _lastUserRequestText(_tabId);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test tests/stalled_continue.test.js`
Expected: PASS (`stalled_continue: all assertions passed`).

- [ ] **Step 5: Full verification and commit**

Run:

```bash
uv run coverage run --source=web,packaging --omit='*/tests/*' -m pytest tests -q
npm --prefix shell test
```

Expected: both pass.

```bash
git add web/static/app.js tests/stalled_continue.test.js
git commit -m "feat: Continue resubmits the original request with the tool-failure note"
```

---

## Self-Review

**Spec coverage**

| Spec item                                           | Task                                                                                |
| --------------------------------------------------- | ----------------------------------------------------------------------------------- |
| 1 no repair turn (single loop)                      | 3                                                                                   |
| 2 `invalid_tool_input` not counted                  | 3 (`_NON_RETRYABLE_TOOL_ERRORS`, `test_schema_violation_counts_as_a_rejected_call`) |
| 3 banner names tool/fields; breakers emit `stalled` | 1 (`stalled_chunk`), 3 (single), 5 (executor)                                       |
| 4 provider-failure exits                            | 4 (single), 5 (executor)                                                            |
| 5 payload `required` + hint                         | 2                                                                                   |
| 6 watchdog summary                                  | 4 (`_generic_tool_summary`)                                                         |
| 7 Continue resubmits request + note, tab guard      | 6                                                                                   |
| 8 executor one repair turn                          | 5 (regression guard test)                                                           |
| delete pre-emptive test / docstring                 | 3                                                                                   |
| Retry/Stop, doom-loop untouched                     | no task touches them                                                                |

**Placeholder scan:** every step carries concrete code or exact edit text; no TBD/"similar to" entries.

**Type consistency:** `rejection_summaries(tool_calls, results) -> list[dict]` (Task 1) is used with `tool_calls, results` in Tasks 3 and 5; `stalled_chunk(summaries)` takes that list in Tasks 3–5; `failed_calls` is `[{"tool", "fields"}]` in the helper, loops and every test; `retry_note` (Task 1) is read as `msg.retry_note` into `_continueRetryNote` (Task 6); `_lastUserRequestText` / `_continueRequestText` are defined once (Task 6) and used by the banner and `_showBrowserConfirmCard`; `rejection_summary_text` is defined in Task 1 and first imported in Task 4 (Task 3 imports only the two names it uses).
