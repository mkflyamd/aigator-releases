"""Agentic loop -- single-agent (original) and three-agent (primary) orchestration."""
import asyncio
import json
import logging
import re
import uuid
from typing import AsyncIterator

MAX_ITERATIONS = 25
_COMPACT_THRESHOLD = 0.85  # compact when input_tokens exceed 85% of context window
_log = logging.getLogger(__name__)

# Substrings in provider error messages that indicate context-window overflow.
# When we see one of these, we prune the largest tool result from msgs and retry.
_OVERFLOW_MARKERS = (
    "prompt is too long",
    "context_length_exceeded",
    "maximum context length",
    "too many tokens",
    "exceeds the maximum",
)

# Max consecutive overflow prune-and-retry attempts per turn. Each iteration
# evicts the next-largest tool result, so multiple large results (transcript +
# OneDrive + Confluence all in one turn) are handled progressively.
_MAX_OVERFLOW_RETRIES = 5

# ── Error taxonomy ────────────────────────────────────────────────────────────
# Non-retryable: model generated a bad tool call (bad params, truncated JSON).
# Retrying the same call against the same bad output never helps — feed an
# error message back to the model once so it can self-correct, then move on.
_NON_RETRYABLE_TOOL_ERRORS = (
    "missing_required_params",
    "missing required",
    "required field",
    "field required",           # pydantic v2 field-level error
    "none is not allowed",      # pydantic v2 null-in-non-optional
    "value is not a valid",     # pydantic v1 validation error
    "invalid param",
    "invalid argument",
    "unexpected keyword",
    "type error",               # python TypeError from tool dispatch
    "json decode",
    "json parse",
    "unterminated string",
    "extra inputs",
    "validation error",
)

# Max consecutive non-retryable failures for a single tool before aborting the
# turn. Keeps on-prem models that can't form valid tool calls from looping forever.
_MAX_BAD_TOOL_RETRIES = 2


def _is_overflow_error(exc: Exception) -> bool:
    s = str(exc).lower()
    if any(m in s for m in _OVERFLOW_MARKERS):
        return True
    # Gateway-agnostic: any error reporting input_tokens > context_limit as bare
    # numbers (e.g. "input (716626 tokens) is longer than context length (262144)").
    # Matches regardless of provider wording — Azure, AWS, vLLM, custom gateways.
    numbers = [int(n) for n in re.findall(r'\b(\d{5,})\b', s)]
    return len(numbers) >= 2 and numbers[0] > numbers[1]


def _is_non_retryable_tool_error(result: dict) -> bool:
    """True if a tool result represents a permanent (non-retryable) failure."""
    err = result.get("error", "") if isinstance(result, dict) else ""
    if not err:
        return False
    err_lower = str(err).lower()
    return any(marker in err_lower for marker in _NON_RETRYABLE_TOOL_ERRORS)


def _failed_tool_results(results: list) -> list[str]:
    """Return short error strings for any failed tool results in `results`.

    A failure is a dict carrying an "error" key (the convention across tools —
    code_runner timeouts, run_shell non-zero exits, generic exceptions). Used to
    detect when a turn ends right after a tool failed, so the UI can offer a
    "Continue?" affordance instead of a silent dead stop (#4)."""
    errs = []
    for r in results:
        if isinstance(r, dict):
            e = r.get("error")
            if e:
                errs.append(str(e))
    return errs


def _prune_largest_tool_result(msgs: list[dict]) -> int:
    """Find the largest tool_result block in msgs and replace its content with a
    stub. Returns the number of bytes reclaimed, or 0 if nothing to prune.

    Operates on Anthropic-format messages (content is a list of blocks). For
    OpenAI-format (role='tool' with string content) it replaces the whole content.
    """
    largest_idx = -1
    largest_block_idx = -1
    largest_size = 0
    largest_kind = None  # "anthropic" or "openai"

    for i, m in enumerate(msgs):
        if m.get("role") == "tool" and isinstance(m.get("content"), str):
            sz = len(m["content"])
            if sz > largest_size:
                largest_size = sz
                largest_idx = i
                largest_kind = "openai"
        elif m.get("role") == "user" and isinstance(m.get("content"), list):
            for j, block in enumerate(m["content"]):
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                # Anthropic tool_result.content can be a string or list of blocks
                content = block.get("content", "")
                if isinstance(content, str):
                    sz = len(content)
                elif isinstance(content, list):
                    sz = sum(len(b.get("text", "")) for b in content if isinstance(b, dict))
                else:
                    sz = 0
                if sz > largest_size:
                    largest_size = sz
                    largest_idx = i
                    largest_block_idx = j
                    largest_kind = "anthropic"

    if largest_idx < 0 or largest_size < 1000:
        return 0  # nothing worth pruning

    stub = (
        f"[Tool result evicted to recover from context overflow "
        f"(was {largest_size} chars). Re-call this tool with a narrower query "
        f"if you still need the data — add filters or lower limit/maxResults.]"
    )
    if largest_kind == "openai":
        msgs[largest_idx]["content"] = stub
    else:
        msgs[largest_idx]["content"][largest_block_idx]["content"] = stub
    _log.warning("[overflow] pruned %d-char tool result at msg[%d]", largest_size, largest_idx)
    return largest_size


def _make_tool_runner(execute_tool, COM_BOUND_TOOLS, TOOL_STATUS, _tool_toast, _SLACK_SAFE_MSG):
    """Returns (_run_tool_block, _run_all_into_queue, _SENTINEL) closures."""
    _SENTINEL = object()

    _BROWSER_TOOLS = {"browser_task", "browser_navigate", "browser_search"}

    async def _request_browser_confirm(action: str, event_queue) -> bool:
        """Suspend execution, ask user to allow/cancel browser use. Returns True if allowed."""
        from browser_agent import _pending_confirms, resolve_browser_confirm
        confirm_id = str(uuid.uuid4())
        event = asyncio.Event()
        result: list[bool] = []
        _pending_confirms[confirm_id] = (event, result)
        try:
            await event_queue.put({"kind": "browser_confirm", "confirm_id": confirm_id, "action": action})
            try:
                await asyncio.wait_for(event.wait(), timeout=60.0)
            except asyncio.TimeoutError:
                result.append(False)
            return result[0] if result else False
        finally:
            _pending_confirms.pop(confirm_id, None)

    async def _run_tool_block(tc, event_queue):
        is_browser = tc.name in _BROWSER_TOOLS
        if is_browser:
            if tc.name == "browser_navigate":
                action = f"Navigate to {tc.inputs.get('url', 'a website')}"
            elif tc.name == "browser_search":
                action = f"Search the web for \"{tc.inputs.get('query', '')}\""
            else:
                action = tc.inputs.get("task", "Perform a browser task")[:120]
            confirmed = await _request_browser_confirm(action, event_queue)
            if not confirmed:
                return {"error": "Browser use cancelled by user."}
            await event_queue.put({"kind": "browser_hitl", "state": "active"})
        result = await execute_tool(tc.name, tc.inputs)
        if is_browser:
            await event_queue.put({"kind": "browser_hitl", "state": "done"})
        _slack_silent = False
        if tc.name.startswith("slack_") and isinstance(result, dict):
            r = result.get("result", "")
            if isinstance(r, str) and r == _SLACK_SAFE_MSG:
                result = {"result": ""}
                _slack_silent = True
        # A call rejected for missing/truncated required args never ran — don't
        # emit the "Running ..." indicator for it, so the UI shows at most one
        # indicator per real execution even when the model retries (#25).
        _rejected = isinstance(result, dict) and result.get("error") == "missing_required_params"
        if not _slack_silent and not _rejected:
            status = TOOL_STATUS.get(tc.name, f"⚙️ Running {tc.name}...")
            await event_queue.put({"kind": "status", "status": status})
        toast = _tool_toast(tc.name, result)
        if toast:
            await event_queue.put({"kind": "toast", "level": toast["level"], "message": toast["message"]})
        if isinstance(result, dict) and "_pane" in result:
            print(f"[pane-signal] tool {tc.name} emitted pane signal: {result['_pane']}", flush=True)
            await event_queue.put({"kind": "pane", "pane": result["_pane"], "data": result.get("data", {})})
        if isinstance(result, dict) and "_draft" in result:
            await event_queue.put({"kind": "draft", "draft": result["_draft"], "data": result.get("data", {})})
        if isinstance(result, dict) and result.get("files"):
            await event_queue.put({"kind": "files", "files": result["files"]})
        # Cross-skill nudge: a tool may return `suggested_next` — a list of
        # {skill, tool, why} dicts pointing at a better next step (typically on
        # failure). The dict is already serialized into the tool_result the model
        # sees, so the model is nudged automatically; here we also surface a toast
        # so the user sees the suggestion. Shape:
        #   {"suggested_next": [{"skill": "confluence", "tool": "confluence_open_edit_form", "why": "..."}]}
        if isinstance(result, dict) and result.get("suggested_next"):
            _sugg = result["suggested_next"]
            if isinstance(_sugg, list):
                _names = ", ".join(
                    s.get("tool") or s.get("skill") or ""
                    for s in _sugg if isinstance(s, dict)
                ).strip(", ")
                if _names:
                    await event_queue.put({"kind": "toast", "level": "info",
                                           "message": f"Suggested next: {_names}"})
        return result

    async def _run_all_into_queue(tool_calls, event_queue):
        try:
            has_com = any(tc.name in COM_BOUND_TOOLS for tc in tool_calls)
            if has_com or len(tool_calls) == 1:
                results = []
                for tc in tool_calls:
                    try:
                        results.append(await _run_tool_block(tc, event_queue))
                    except Exception as exc:
                        results.append({"error": str(exc)})
            else:
                results = list(await asyncio.gather(
                    *[_run_tool_block(tc, event_queue) for tc in tool_calls],
                    return_exceptions=True,
                ))
                results = [r if not isinstance(r, Exception) else {"error": str(r)} for r in results]
        finally:
            await event_queue.put(_SENTINEL)
        return results

    return _run_tool_block, _run_all_into_queue, _SENTINEL


async def _single_agent_loop(
    provider, model, system, msgs, normalized_tools,
    execute_tool, COM_BOUND_TOOLS, TOOL_STATUS, _tool_toast, _SLACK_SAFE_MSG,
    context_id: str | None = None,
) -> AsyncIterator[str]:
    """Original single-agent loop. Kept as fallback reference."""
    _, _run_all_into_queue, _SENTINEL = _make_tool_runner(
        execute_tool, COM_BOUND_TOOLS, TOOL_STATUS, _tool_toast, _SLACK_SAFE_MSG
    )
    _total_input = 0
    _total_output = 0
    _last_round_errors: list[str] = []  # failures from the most recent tool round
    _bad_tool_streak = 0  # consecutive rounds where ALL tool calls were non-retryable errors

    for _ in range(MAX_ITERATIONS):
        turn = None
        _overflow_prunes = 0
        while True:
            try:
                async for event in provider.stream_turn(model, system, msgs, normalized_tools):
                    if event["type"] == "text_delta":
                        yield f"data: {json.dumps({'token': event['text']})}\n\n"
                    elif event["type"] == "thinking_delta":
                        yield f"data: {json.dumps({'thinking': event['text'], 'agent': event.get('agent')})}\n\n"
                    elif event["type"] == "done":
                        turn = event
                break
            except Exception as exc:
                # Context-overflow recovery: progressively prune the largest tool
                # results until the prompt fits or there is nothing left to prune.
                # Loop allows multiple large results (transcript + files + pages)
                # to be evicted one-by-one rather than failing after the first prune.
                if _overflow_prunes < _MAX_OVERFLOW_RETRIES and _is_overflow_error(exc):
                    reclaimed = _prune_largest_tool_result(msgs)
                    if reclaimed > 0:
                        _overflow_prunes += 1
                        yield f"data: {json.dumps({'status': f'⚠️ Context overflow — pruned a {reclaimed//1024}KB tool result and retrying...'})}\n\n"
                        continue
                import logging as _logging
                _logging.getLogger(__name__).exception("[agent] LLM error during stream_turn: %s", exc)
                print(f"[agent] LLM error during stream_turn: {exc}", flush=True)
                yield f"data: {json.dumps({'text': f'LLM error: {exc}'})}\n\n"
                yield "data: [DONE]\n\n"
                return

        if turn is None:
            yield f"data: {json.dumps({'text': 'No response from model.'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        _u = turn.get("usage", {})
        _total_input += _u.get("input_tokens", 0)
        _total_output += _u.get("output_tokens", 0)
        _ctx_limit = getattr(provider, "context_window", 200_000) or 200_000
        if context_id and _u.get("input_tokens", 0) > _ctx_limit * _COMPACT_THRESHOLD:
            import shared as _shared
            yield f"data: {json.dumps({'status': '🗜️ Compacting conversation history...'})}\n\n"
            msgs = await _shared.conversation_store.compact(context_id, provider, model)
        asst_msg = provider.build_assistant_message(turn["raw_content"])
        if isinstance(asst_msg, list):
            msgs.extend(asst_msg)
        else:
            msgs.append(asst_msg)

        if turn["stop_reason"] != "tool_use":
            yield f"data: {json.dumps({'usage': {'input_tokens': _total_input, 'output_tokens': _total_output}})}\n\n"
            # If the model stops on the heels of a failed tool, surface a
            # Continue affordance — otherwise the turn dies silently after a
            # timeout/error and the user is left wondering (#4).
            if _last_round_errors:
                _detail = _last_round_errors[0]
                if len(_detail) > 160:
                    _detail = _detail[:160] + "…"
                yield f"data: {json.dumps({'stalled': True, 'message': f'Gator stopped after a step failed: {_detail} — click Continue to pick up where it left off.'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        tool_calls = turn["tool_calls"]
        if not tool_calls:
            yield f"data: {json.dumps({'text': 'Model requested tool use with no tool calls.'})}\n\n"
            yield "data: [DONE]\n\n"
            return
        event_queue = asyncio.Queue()
        gather_task = asyncio.create_task(_run_all_into_queue(tool_calls, event_queue))
        try:
            while True:
                evt = await event_queue.get()
                if evt is _SENTINEL:
                    break
                kind = evt["kind"]
                if kind == "status":
                    yield f"data: {json.dumps({'status': evt['status']})}\n\n"
                elif kind == "pane":
                    yield f"data: {json.dumps({'pane': evt['pane'], 'paneData': evt.get('data', {})})}\n\n"
                elif kind == "draft":
                    yield f"data: {json.dumps({'draft': evt['draft'], 'draftData': evt.get('data', {})})}\n\n"
                elif kind == "toast":
                    yield f"data: {json.dumps({'toast': {'level': evt.get('level', 'info'), 'message': evt.get('message', '')}})}\n\n"
                elif kind == "browser_hitl":
                    yield f"data: {json.dumps({'browser_hitl': evt['state']})}\n\n"
                elif kind == "browser_confirm":
                    yield f"data: {json.dumps({'browser_confirm': {'confirm_id': evt['confirm_id'], 'action': evt['action']}})}\n\n"
                elif kind == "files":
                    yield f"data: {json.dumps({'files': evt['files']})}\n\n"
            results = await gather_task
        finally:
            if not gather_task.done():
                gather_task.cancel()
        _last_round_errors = _failed_tool_results(results)

        # If any tool result is marked _terminal, stop the loop immediately
        # without a second LLM turn — lets a tool handler skip an unnecessary
        # acknowledgment round trip when it has nothing useful to add.
        if any(isinstance(r, dict) and r.get("_terminal") for r in results):
            yield f"data: {json.dumps({'usage': {'input_tokens': _total_input, 'output_tokens': _total_output}})}\n\n"
            yield "data: [DONE]\n\n"
            return

        tool_msg = provider.build_tool_result_message(tool_calls, results)
        if isinstance(tool_msg, list):
            msgs.extend(tool_msg)
        else:
            msgs.append(tool_msg)

        # Circuit breaker: if every tool call in this round was a non-retryable
        # error (bad params, malformed JSON from on-prem model), increment the
        # streak counter. After _MAX_BAD_TOOL_RETRIES consecutive all-bad rounds
        # abort — the model can't form valid calls and will loop forever otherwise.
        all_non_retryable = results and all(_is_non_retryable_tool_error(r) for r in results)
        if all_non_retryable:
            _bad_tool_streak += 1
            if _bad_tool_streak >= _MAX_BAD_TOOL_RETRIES:
                _names = ", ".join(tc.name for tc in tool_calls)
                yield f"data: {json.dumps({'text': f'The model could not form valid tool calls for {_names} after {_bad_tool_streak} attempts. Try rephrasing your request or switching to a more capable model.'})}\n\n"
                yield "data: [DONE]\n\n"
                return
        else:
            _bad_tool_streak = 0

        # A tool round just completed; any assistant text streamed before this is
        # narration/tool-data, not the final answer. Signal consumers (task_queue)
        # to discard prior accumulated text so only the post-last-tool answer is kept.
        yield f"data: {json.dumps({'phase': 'tool_round'})}\n\n"

    yield f"data: {json.dumps({'exhausted': True, 'iterations': MAX_ITERATIONS, 'message': f'Gator hit its {MAX_ITERATIONS}-step limit before finishing. Click Continue to pick up where it left off.'})}\n\n"
    yield "data: [DONE]\n\n"


_PLANNER_SUFFIX = """

You are the PLANNING agent. Decompose the user's request into an ordered numbered list of steps.
For each step, note which tool(s) should be called. Do NOT call tools. Reply with ONLY the plan. No preamble, no commentary.

Quality check before outputting: (1) Are these the ONLY channels/platforms the user asked for? (2) Is there a simpler path with fewer steps? (3) Are all steps actually needed, or are any speculative? Apply corrections silently — do not narrate this check.

IMPORTANT: Only use the channels/platforms the user explicitly asked for. If the user says "post in Teams", do NOT also post in Slack (or vice versa). Never expand the scope of a request to additional platforms unless the user specifically asks.
"""

_EXECUTOR_SUFFIX = """

You are the EXECUTION agent. You receive a plan and must execute it using the available tools.

Tool discipline:
- Only call tools when they are necessary. NEVER make redundant or speculative tool calls.
- Call independent tools in parallel; call dependent tools in sequence.
- Before each tool call, confirm you have the required inputs from prior steps — do not guess parameter values.

Execution:
- Execute steps in plan order. If a step fails, report the exact error and stop — do not silently skip or substitute a different action.
- When the user's request involves web research followed by communication (email, Teams, Slack), complete all browser/search tools first to gather findings, then use the appropriate compose tool (email_open_compose, teams_open_compose) to draft the message with those findings. Do not ask the user to manually copy results between steps. Include the key findings in the draft body.

After all steps, write a draft response summarising what you found.
"""

_VERIFIER_SUFFIX = """

You are the VERIFICATION agent. Check: does the draft fully address the original request?

Before deciding, verify from the draft text alone:
1. Does the draft answer the original question — not just describe what steps were taken?
2. Does the draft explicitly report any failures, errors, or partial results? If so, the draft is incomplete.
3. Does the draft make any confident success claims without showing actual results (data, counts, confirmations)?

If the draft passes all three checks: output the final response verbatim. No meta-commentary.
If NOT: output "RETRY:" followed by specifically what is missing or wrong. Do not fix it yourself. Max 2 retries.
"""


def _chunk_text(text: str, size: int = 4) -> list:
    return [text[i:i + size] for i in range(0, len(text), size)]


async def run_three_agent_loop(
    provider, model, system, msgs, normalized_tools,
    execute_tool, COM_BOUND_TOOLS, TOOL_STATUS, _tool_toast, _SLACK_SAFE_MSG,
    token_budget: int = 0,
    context_id: str | None = None,
) -> AsyncIterator[str]:
    """Planner -> Executor -> Verifier. Emits msg.agent on thinking events."""
    _total_input = 0
    _total_output = 0
    _, _run_all_into_queue, _SENTINEL = _make_tool_runner(
        execute_tool, COM_BOUND_TOOLS, TOOL_STATUS, _tool_toast, _SLACK_SAFE_MSG
    )

    def _budget_ok():
        return token_budget <= 0 or (_total_input + _total_output) < token_budget

    # ── Diagnostics ────────────────────────────────────────────────
    import logging as _log
    _log.info("[tokens] system_prompt=%d chars, tools=%d, msgs=%d",
              len(system), len(normalized_tools), len(msgs))

    # ── Planner ───────────────────────────────────────────────────
    plan_text = ""
    try:
        async for event in provider.stream_turn(model, system + _PLANNER_SUFFIX, list(msgs), []):
            if event["type"] == "text_delta":
                plan_text += event["text"]
                yield f"data: {json.dumps({'token': event['text']})}\n\n"
            elif event["type"] == "thinking_delta":
                yield f"data: {json.dumps({'thinking': event['text'], 'agent': 'planner'})}\n\n"
            elif event["type"] == "done":
                _u = event.get("usage", {})
                _total_input += _u.get("input_tokens", 0)
                _total_output += _u.get("output_tokens", 0)
                _log.info("[tokens] PLANNER: in=%d out=%d",
                          _u.get("input_tokens", 0), _u.get("output_tokens", 0))
    except Exception as exc:
        yield f"data: {json.dumps({'text': f'Planner error: {exc}'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    if not _budget_ok():
        yield f"data: {json.dumps({'text': 'Task too complex for current token budget. Try a narrower scope.'})}\n\n"
        yield f"data: {json.dumps({'usage': {'input_tokens': _total_input, 'output_tokens': _total_output}})}\n\n"
        yield "data: [DONE]\n\n"
        return

    yield f"data: {json.dumps({'status': '\U0001f4cb Planning done'})}\n\n"

    # ── Executor ──────────────────────────────────────────────────
    executor_msgs = list(msgs) + [
        {"role": "assistant", "content": plan_text},
        {"role": "user", "content": "Execute the plan above using the available tools."},
    ]
    draft_text = ""
    _bad_tool_streak = 0  # consecutive all-bad-tool rounds in executor

    for _iter in range(MAX_ITERATIONS):  # executor tool iterations
        exec_turn = None
        draft_text = ""  # only keep the final (non-tool-use) turn's text
        _overflow_prunes = 0
        while True:
            try:
                async for event in provider.stream_turn(model, system + _EXECUTOR_SUFFIX, executor_msgs, normalized_tools):
                    if event["type"] == "text_delta":
                        draft_text += event["text"]
                        yield f"data: {json.dumps({'token': event['text']})}\n\n"
                    elif event["type"] == "thinking_delta":
                        yield f"data: {json.dumps({'thinking': event['text'], 'agent': 'executor'})}\n\n"
                    elif event["type"] == "done":
                        exec_turn = event
                        _u = event.get("usage", {})
                        _total_input += _u.get("input_tokens", 0)
                        _total_output += _u.get("output_tokens", 0)
                        _log.info("[tokens] EXECUTOR iter: in=%d out=%d total_so_far=%d",
                                  _u.get("input_tokens", 0), _u.get("output_tokens", 0),
                                  _total_input + _total_output)
                        _ctx_limit = getattr(provider, "context_window", 200_000) or 200_000
                        if context_id and _u.get("input_tokens", 0) > _ctx_limit * _COMPACT_THRESHOLD:
                            import shared as _shared
                            yield f"data: {json.dumps({'status': '🗜️ Compacting conversation history...'})}\n\n"
                            msgs = await _shared.conversation_store.compact(context_id, provider, model)
                break
            except Exception as exc:
                if _overflow_prunes < _MAX_OVERFLOW_RETRIES and _is_overflow_error(exc):
                    reclaimed = _prune_largest_tool_result(executor_msgs)
                    if reclaimed > 0:
                        _overflow_prunes += 1
                        draft_text = ""  # reset partial output before retry
                        yield f"data: {json.dumps({'status': f'⚠️ Context overflow — pruned a {reclaimed//1024}KB tool result and retrying...'})}\n\n"
                        continue
                yield f"data: {json.dumps({'text': f'Executor error: {exc}'})}\n\n"
                yield "data: [DONE]\n\n"
                return

        if exec_turn is None:
            break
        exec_asst = provider.build_assistant_message(exec_turn["raw_content"])
        if isinstance(exec_asst, list):
            executor_msgs.extend(exec_asst)
        else:
            executor_msgs.append(exec_asst)
        if exec_turn["stop_reason"] != "tool_use":
            break
        if not _budget_ok():
            yield f"data: {json.dumps({'status': '\u26a0\ufe0f Token budget reached -- partial result'})}\n\n"
            break

        tool_calls = exec_turn["tool_calls"]
        event_queue = asyncio.Queue()
        gather_task = asyncio.create_task(_run_all_into_queue(tool_calls, event_queue))
        results = []
        try:
            while True:
                evt = await event_queue.get()
                if evt is _SENTINEL:
                    break
                kind = evt["kind"]
                if kind == "status":
                    yield f"data: {json.dumps({'status': evt['status']})}\n\n"
                elif kind == "pane":
                    yield f"data: {json.dumps({'pane': evt['pane'], 'paneData': evt.get('data', {})})}\n\n"
                elif kind == "draft":
                    yield f"data: {json.dumps({'draft': evt['draft'], 'draftData': evt.get('data', {})})}\n\n"
                elif kind == "toast":
                    yield f"data: {json.dumps({'toast': {'level': evt.get('level', 'info'), 'message': evt.get('message', '')}})}\n\n"
                elif kind == "browser_hitl":
                    yield f"data: {json.dumps({'browser_hitl': evt['state']})}\n\n"
                elif kind == "browser_confirm":
                    yield f"data: {json.dumps({'browser_confirm': {'confirm_id': evt['confirm_id'], 'action': evt['action']}})}\n\n"
                elif kind == "files":
                    yield f"data: {json.dumps({'files': evt['files']})}\n\n"
            results = await gather_task
        finally:
            if not gather_task.done():
                gather_task.cancel()
        exec_tool_msg = provider.build_tool_result_message(tool_calls, results)
        if isinstance(exec_tool_msg, list):
            executor_msgs.extend(exec_tool_msg)
        else:
            executor_msgs.append(exec_tool_msg)

        # Circuit breaker: abort if the model keeps producing non-retryable tool errors
        all_non_retryable = results and all(_is_non_retryable_tool_error(r) for r in results)
        if all_non_retryable:
            _bad_tool_streak += 1
            if _bad_tool_streak >= _MAX_BAD_TOOL_RETRIES:
                _names = ", ".join(tc.name for tc in tool_calls)
                yield f"data: {json.dumps({'text': f'Executor: model could not form valid tool calls for {_names} after {_bad_tool_streak} attempts. Try rephrasing or switching model.'})}\n\n"
                yield f"data: {json.dumps({'usage': {'input_tokens': _total_input, 'output_tokens': _total_output}})}\n\n"
                yield "data: [DONE]\n\n"
                return
        else:
            _bad_tool_streak = 0
    else:
        # for-loop completed without break — executor exhausted its iterations
        yield f"data: {json.dumps({'exhausted': True, 'iterations': MAX_ITERATIONS, 'message': f'Gator hit its {MAX_ITERATIONS}-step limit before finishing. Click Continue to pick up where it left off.'})}\n\n"
        yield f"data: {json.dumps({'usage': {'input_tokens': _total_input, 'output_tokens': _total_output}})}\n\n"
        yield "data: [DONE]\n\n"
        return

    if not _budget_ok():
        yield f"data: {json.dumps({'usage': {'input_tokens': _total_input, 'output_tokens': _total_output}})}\n\n"
        yield "data: [DONE]\n\n"
        return

    # ── Verifier ──────────────────────────────────────────────────
    yield f"data: {json.dumps({'status': '\u2713 Checking...'})}\n\n"
    original = msgs[-1]["content"] if msgs else ""
    verifier_msgs = [{"role": "user", "content": f"Original: {original}\n\nDraft:\n{draft_text}\n\nVerify and finalise."}]

    for _retry in range(3):  # 0,1,2 -- max 2 retries
        verif_text = ""
        try:
            async for event in provider.stream_turn(model, system + _VERIFIER_SUFFIX, verifier_msgs, []):
                if event["type"] == "text_delta":
                    verif_text += event["text"]
                elif event["type"] == "thinking_delta":
                    yield f"data: {json.dumps({'thinking': event['text'], 'agent': 'verifier'})}\n\n"
                elif event["type"] == "done":
                    _u = event.get("usage", {})
                    _total_input += _u.get("input_tokens", 0)
                    _total_output += _u.get("output_tokens", 0)
                    _log.info("[tokens] VERIFIER: in=%d out=%d TOTAL=%d",
                              _u.get("input_tokens", 0), _u.get("output_tokens", 0),
                              _total_input + _total_output)
        except Exception as _verif_exc:
            import logging as _log
            _log.warning("[verifier] streaming failed: %s — falling back to draft_text", _verif_exc)

        if verif_text.startswith("RETRY:") and _retry < 2:
            note = verif_text[len("RETRY:"):].strip()
            improved = ""
            try:
                async for event in provider.stream_turn(
                    model, system + _EXECUTOR_SUFFIX,
                    executor_msgs + [{"role": "user", "content": f"Improve answer. Missing: {note}"}], [],
                ):
                    if event["type"] == "text_delta":
                        improved += event["text"]
                    elif event["type"] == "done":
                        _u = event.get("usage", {})
                        _total_input += _u.get("input_tokens", 0)
                        _total_output += _u.get("output_tokens", 0)
            except Exception as _imp_exc:
                import logging as _log
                _log.warning("[verifier] improve call failed: %s", _imp_exc)
            if improved:
                draft_text = improved
            verifier_msgs = [{"role": "user", "content": f"Original: {original}\n\nImproved draft:\n{draft_text}\n\nVerify again."}]
        else:
            final = (verif_text if verif_text and not verif_text.startswith("RETRY:") else draft_text)
            yield f"data: {json.dumps({'phase': 'final'})}\n\n"
            for ch in _chunk_text(final):
                yield f"data: {json.dumps({'token': ch})}\n\n"
            break

    yield f"data: {json.dumps({'usage': {'input_tokens': _total_input, 'output_tokens': _total_output}})}\n\n"
    yield "data: [DONE]\n\n"
