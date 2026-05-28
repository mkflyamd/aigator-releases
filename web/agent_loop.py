"""Agentic loop -- single-agent (original) and three-agent (primary) orchestration."""
import asyncio
import json
import uuid
from typing import AsyncIterator

MAX_ITERATIONS = 25


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
        if not _slack_silent:
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
) -> AsyncIterator[str]:
    """Original single-agent loop. Kept as fallback reference."""
    _, _run_all_into_queue, _SENTINEL = _make_tool_runner(
        execute_tool, COM_BOUND_TOOLS, TOOL_STATUS, _tool_toast, _SLACK_SAFE_MSG
    )
    _total_input = 0
    _total_output = 0

    for _ in range(MAX_ITERATIONS):
        turn = None
        try:
            async for event in provider.stream_turn(model, system, msgs, normalized_tools):
                if event["type"] == "text_delta":
                    yield f"data: {json.dumps({'token': event['text']})}\n\n"
                elif event["type"] == "thinking_delta":
                    yield f"data: {json.dumps({'thinking': event['text'], 'agent': event.get('agent')})}\n\n"
                elif event["type"] == "done":
                    turn = event
        except Exception as exc:
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
        if _u.get("input_tokens", 0) > 160_000:
            yield f"data: {json.dumps({'context_warning': True, 'context_tokens': _u['input_tokens']})}\n\n"
        asst_msg = provider.build_assistant_message(turn["raw_content"])
        if isinstance(asst_msg, list):
            msgs.extend(asst_msg)
        else:
            msgs.append(asst_msg)

        if turn["stop_reason"] != "tool_use":
            yield f"data: {json.dumps({'usage': {'input_tokens': _total_input, 'output_tokens': _total_output}})}\n\n"
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
        tool_msg = provider.build_tool_result_message(tool_calls, results)
        if isinstance(tool_msg, list):
            msgs.extend(tool_msg)
        else:
            msgs.append(tool_msg)

    yield f"data: {json.dumps({'exhausted': True, 'iterations': MAX_ITERATIONS, 'message': f'Gator hit its {MAX_ITERATIONS}-step limit before finishing. Click Continue to pick up where it left off.'})}\n\n"
    yield "data: [DONE]\n\n"


_PLANNER_SUFFIX = """

You are the PLANNING agent. Decompose the user's request into an ordered numbered list of steps.
For each step, note which tool(s) should be called. Do NOT call tools. Reply with ONLY the plan. No preamble.

IMPORTANT: Only use the channels/platforms the user explicitly asked for. If the user says "post in Teams", do NOT also post in Slack (or vice versa). Never expand the scope of a request to additional platforms unless the user specifically asks.
"""

_EXECUTOR_SUFFIX = """

You are the EXECUTION agent. You receive a plan and must execute it using the available tools.
Call tools in the order specified; call independent tools in parallel.
After all steps, write a draft response summarising what you found.

When the user's request involves web research followed by communication (email, Teams, Slack), complete all browser tools first to gather findings, then use the appropriate compose tool (email_open_compose, teams_open_compose) to draft the message with those findings. Do not ask the user to manually copy results between steps. Include the key findings in the draft body.
"""

_VERIFIER_SUFFIX = """

You are the VERIFICATION agent. Check: does the draft fully address the original request?
If YES: output the final response verbatim. No meta-commentary.
If NO: output "RETRY:" followed by what is missing. Do not fix it yourself. Max 2 retries.
"""


def _chunk_text(text: str, size: int = 4) -> list:
    return [text[i:i + size] for i in range(0, len(text), size)]


async def run_three_agent_loop(
    provider, model, system, msgs, normalized_tools,
    execute_tool, COM_BOUND_TOOLS, TOOL_STATUS, _tool_toast, _SLACK_SAFE_MSG,
    token_budget: int = 0,
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

    for _iter in range(MAX_ITERATIONS):  # executor tool iterations
        exec_turn = None
        draft_text = ""  # only keep the final (non-tool-use) turn's text
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
        except Exception as exc:
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
