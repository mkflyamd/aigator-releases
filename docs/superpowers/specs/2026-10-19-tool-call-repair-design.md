# Tool-Call Repair — Design (SP1)

Covers issue #55 plan A items 1–5 and the `run_python` "Gator could not form valid arguments" failure from #12. Line references are to `web/agent_loop.py` unless a file is named.

## Problem

A tool call that the dispatcher rejects (missing or blank required argument, schema violation) never runs the tool. The model should see the rejection, fix the call, and carry on. Today the user gets a dead-end banner after a single bad call.

1. **No repair turn in the single-agent loop.** The pre-emptive breaker at `:850-872` fires at the start of the next iteration on `_ > 0 and _bad_tool_streak >= 1`. After the first rejected round the loop stalls without making another LLM call, so the model never sees the structured rejection. The real breaker at `:1265-1286` (`>= _MAX_BAD_TOOL_RETRIES`, which is 2, `:232-262`) is unreachable in this loop.
2. **Schema rejections are not counted.** `_NON_RETRYABLE_TOOL_ERRORS` (`:232-262`) omits `invalid_tool_input` (returned by `web/tool_validation.py:33-62`), so `_is_non_retryable_tool_error` / `_failed_tool_results` (`:277-299`) ignore it and the streak never grows.
3. **The banner names neither tool nor fields.** The pre-emptive stall says "could not form valid arguments for {names}" using the *previous* turn's tool names. The real breakers (`:1265-1286` single, `:1774-1793` executor) emit plain `text`, not a `stalled` event, so there is no Continue button and no field names.
4. **Provider failure after a rejection loses the context.** The exits "failover declined", "LLM error", "No response from model." (single loop) and "Executor error: {exc}" (executor) print plain text with no recovery affordance, even though the real cause was the rejected call.
5. **The rejection payload misleads the model.** `execute_tool` (`web/app.py:490-542`) tells the model its arguments "were likely truncated because the payload exceeded the output budget". A model that simply omitted `code` is told to shrink its payload. The payload also does not list the tool's required fields.
6. **The watchdog banner is uninformative.** `web/routes/chat.py:2290-2420` quotes `_last_tool_error`, the last error `tool_result` summary. For a rejected call the summary is `Error: missing_required_params`.
7. **Continue loses the task.** `web/static/app.js` (stalled handler ~13727, banner ~13873-13896) sends the literal "Continue where you left off." The server keeps no resume state, so the model has no idea what to resume.
8. **The executor loop** already allows one repair turn (no pre-emptive twin) but its breaker output is plain `text` (finding 3).

### Why the pre-emptive breaker exists

Issue #42 (`tests/test_streaming_stall_recovery.py`): the idle watchdog in `routes/chat.py` kills an LLM call that stays silent (first token 180 s, between chunks 60 s). An on-prem model that receives a conversation ending in a rejection can go silent; the watchdog cancels the generator externally, bypassing the loop's own streak check. The breaker was added to stop *before* making that call. It does so unconditionally at `streak >= 1`, which also prevents every legitimate repair.

That case does not need a loop-level pre-empt: the watchdog is independent of the loop and already emits its own `stalled` event, so a silent repair call is bounded by the watchdog banner (finding 6 makes it name the fields). A repair call that errors (rather than hangs) is covered by finding 4's fix.

## Design

### Component: `web/tool_repair.py` (new)

Pure helpers shared by both loops; no I/O.

- `REJECTED_ERRORS = ("missing_required_params", "invalid_tool_input")`
- `rejection_summaries(tool_calls, results) -> list[dict]` — one `{"tool": str, "fields": list[str]}` per failed call in a round. Tool name comes from the result's own `tool` key, falling back to `tc.name`; fields come from `missing` (missing params) or `field` (schema).
- `rejection_summary_text(result) -> str | None` — `"Rejected run_python: missing code"`; `None` for any non-rejection.
- `stalled_chunk(summaries) -> str` — the SSE line. JSON key order is `stalled`, `message`, `failed_calls`, `retry_note`, because `routes/chat.py:2114` holds loop-emitted stalls by the prefix `data: {"stalled"`.

### Component: `agent_loop.py`

- Import the helpers; add `invalid_tool_input` to `_NON_RETRYABLE_TOOL_ERRORS`.
- Delete the pre-emptive breaker. The existing `all_non_retryable` branch now does the work: streak 1 → loop continues and the model gets the rejection (the repair turn); streak 2 → breaker.
- Track `_last_rejections` (single loop and executor). On a bad round set it from `rejection_summaries`. The breaker yields `stalled_chunk(_last_rejections)` instead of plain text, then keeps its existing `_log_turn_end_safe(... "circuit_breaker" ...)` and `[DONE]`.
- On the provider-failure exits listed in finding 4, after the existing text, `if _bad_tool_streak: yield stalled_chunk(_last_rejections)`.
- `_generic_tool_summary` returns `rejection_summary_text(result)` first, so the `tool_result` event and the watchdog banner name the fields.

### Component: `web/app.py` `execute_tool`

Rejection payload gains `"required": required` and a hint that tells the model to call the tool again with every required argument, naming them, and keeps the truncation advice as a secondary sentence.

### Component: `web/static/app.js`

- `_continueRetryNote` is set from `msg.retry_note` in the stalled branch.
- `_lastUserRequestText(tabId)` (extracted from the inline code in `_showBrowserConfirmCard`) and `_continueRequestText(lastUserText, retryNote)` build the Continue text: original request + blank line + note, or "Continue where you left off." when either is missing.
- The Continue click handler uses that text, reusing the Ask-again mechanism (set `#chat-input`, `form.requestSubmit()`). A note-carrying Continue clicked from a different tab than the one that streamed does nothing, so a request is never resubmitted into the wrong conversation.

### Data flow

1. Model emits a call with a missing/blank/invalid argument → `execute_tool` returns the structured rejection, tool does not run.
2. Round is all-bad → `_bad_tool_streak = 1`, `_last_rejections` set, loop calls the model again with the rejection in context.
3. Repair succeeds → streak resets (existing behavior), task continues, no banner.
4. Repair also rejected (streak 2), or the provider errors with streak ≥ 1 → one `stalled` event with `message` (tool and fields), `failed_calls`, `retry_note`, then `[DONE]`.
5. Frontend renders the banner with `message`; Continue resubmits the original request plus `retry_note`.

## Decisions

- **Remove the pre-emptive stall instead of tuning its threshold.** Any threshold ≤ 1 denies repair; the real `>= 2` breaker already expresses "one repair, then stop".
- **Count `invalid_tool_input`.** Same failure class (call rejected, tool never ran); one counter keeps behavior uniform.
- **Breaker emits a structured `stalled` event, not text.** Gives a Continue button and carries names; `stalled` stays the first JSON key for the `chat.py` hold.
- **Also stall on provider failure after a rejection.** The user otherwise sees "LLM error" with no hint that a rejected call preceded it and no Continue.
- **Add `required` and a corrected hint to the payload.** Fixes the misleading advice at its source, for every tool, with no per-tool code.
- **Generic `tool_result` summary names the fields.** One change improves the UI row and the watchdog banner.
- **Continue resubmits the original request plus a note (user decision).** Reuses Ask-again, so no server-side resume state; the note names the failed tool and fields (user decision).
- **Tab guard on note-carrying Continue.** The banner belongs to the request's tab; resubmitting elsewhere would send the wrong conversation.
- **Keep the watchdog case in `routes/chat.py`.** It is independent of the loop and unchanged.
- **Keep Retry/Stop (user decision) and the doom-loop detector** (`_DOOM_LOOP_THRESHOLD = 3`) untouched.
- **Cover both loops (user decision).**
- **Delete `test_circuit_breaker_fires_on_streak_1_before_second_llm_call`.** It asserts exactly the removed behavior; new tests cover the replacement.

## Error handling

- A repair call that raises, is declined by failover, or returns nothing, after a rejected round, ends with the structured `stalled` event, never plain text alone.
- A rejected call whose result has no `tool`/`missing`/`field` (e.g. a generic error) is summarized from the call name with empty `fields`; the message then names only the tool.
- No rejection and no streak: the exits behave exactly as before (plain text only).
- Continue with no recorded user message or no note falls back to the plain "Continue where you left off." prompt.

## Testing

All Python in `tests/test_tool_repair.py`; JS in `tests/stalled_continue.test.js`.

| Defect | Test |
|---|---|
| 1 no repair turn | `test_missing_field_gets_exactly_one_repair_call_and_task_resumes` (3 LLM calls, only the valid call executes, repair context contains `"missing": ["code"]`); `test_successful_repair_resets_the_repair_budget` |
| 2 schema not counted | `test_schema_violation_counts_as_a_rejected_call` |
| 3 banner content | `test_repair_that_fails_again_stalls_naming_tool_and_fields`; `test_stalled_chunk_names_tool_fields_and_carries_retry_note` (incl. `data: {"stalled"` prefix); helper tests |
| 4 provider failure | `test_provider_failure_during_repair_stalls_with_the_failed_tool`; `test_executor_provider_failure_after_rejection_stalls` |
| 5 payload | `test_rejected_call_never_executes_and_reports_required_fields` (real `execute_tool`, inputs `{}`, `""`, `"   "`; handler never runs) |
| 6 watchdog summary | `test_rejected_call_tool_result_names_missing_fields_for_the_watchdog_banner`; `test_rejection_summary_text` |
| 7 Continue | `stalled_continue.test.js`: note captured, plain Continue unchanged, original request + note resubmitted once, no-history fallback, wrong-tab guard |
| 8 executor | `test_executor_repair_that_fails_again_stalls_with_structured_event`; `test_executor_successful_repair_resumes_the_task` (regression guard) |
| pre-emptive stall removed | old test deleted from `tests/test_streaming_stall_recovery.py`; the loop tests above assert the call counts |
