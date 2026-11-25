"""A model that writes its native tool-call markup as text must get one repair turn, then stall."""

import asyncio
import json

import app  # noqa: F401 — populates registries
import agent_loop
import tool_repair

LEAKED = '<｜DSML｜ calls> <｜DSML｜ invoke name="schedule_task"> </｜DSML｜ invoke> </｜DSML｜ calls>'


class _ScriptedProvider:
    def __init__(self, texts):
        self.texts = list(texts)
        self.seen_msgs = []

    async def stream_turn(self, model, system, msgs, tools):
        self.seen_msgs.append(list(msgs))
        text = self.texts.pop(0)
        yield {"type": "text_delta", "text": text}
        yield {
            "type": "done",
            "stop_reason": "end_turn",
            "text": text,
            "usage": {"input_tokens": 5, "output_tokens": 5},
            "tool_calls": [],
            "raw_content": [{"type": "text", "text": text}],
        }

    def build_assistant_message(self, raw_content):
        return {"role": "assistant", "content": raw_content}


def _run(provider):
    async def go():
        out = []
        async for chunk in agent_loop._single_agent_loop(
            provider, "claude-sonnet-5", "sys", [{"role": "user", "content": "hi"}], [],
            lambda *a, **k: {}, set(), {}, lambda *a, **k: None, "safe",
        ):
            if chunk.startswith("data: {"):
                out.append(json.loads(chunk[6:]))
        return out

    return asyncio.run(go())


def test_leaked_call_gets_one_repair_turn_then_answers():
    provider = _ScriptedProvider([LEAKED, "Scheduled."])
    events = _run(provider)
    assert len(provider.seen_msgs) == 2
    assert provider.seen_msgs[1][-1] == {"role": "user", "content": tool_repair.LEAKED_CALL_NOTE}
    assert {"phase": "tool_round"} in events
    assert not any(e.get("stalled") for e in events)
    assert [e["token"] for e in events if "token" in e][-1] == "Scheduled."


def test_leaked_call_twice_stalls_instead_of_looping():
    provider = _ScriptedProvider([LEAKED, LEAKED])
    events = _run(provider)
    assert len(provider.seen_msgs) == 2
    stalled = [e for e in events if e.get("stalled")]
    assert len(stalled) == 1 and stalled[0]["retry_note"] == tool_repair.LEAKED_CALL_NOTE


def test_plain_text_is_not_treated_as_a_leak():
    assert not tool_repair.leaked_tool_call("I'll schedule that for Friday at noon.")
    assert tool_repair.leaked_tool_call(LEAKED)


def _run_with_task(provider):
    import shared

    task_id = "t-leaked-repair"
    shared.chat_task_store.create_task(task_id, "ctx-leaked-repair")

    async def go():
        async for _ in agent_loop._single_agent_loop(
            provider, "claude-sonnet-5", "sys", [{"role": "user", "content": "hi"}], [],
            lambda *a, **k: {}, set(), {}, lambda *a, **k: None, "safe",
            context_id="ctx-leaked-repair", task_id=task_id,
        ):
            pass

    asyncio.run(go())
    return shared.chat_task_store.had_error(task_id)


def test_a_repaired_leaked_call_does_not_flag_the_turn_as_failed():
    assert _run_with_task(_ScriptedProvider([LEAKED, "Scheduled."])) is False


def test_a_leaked_call_that_stalls_flags_the_turn_as_failed():
    assert _run_with_task(_ScriptedProvider([LEAKED, LEAKED])) is True


def test_an_error_outcome_is_only_logged_where_the_turn_really_ends():
    """The queue pauses on any outcome in _ERROR_OUTCOMES, so none may be logged for a step the loop recovers from."""
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path(agent_loop.__file__).read_text(encoding="utf-8"))
    offenders = []
    for parent in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            stmts = getattr(parent, field, None)
            if not isinstance(stmts, list):
                continue
            for i, stmt in enumerate(stmts):
                call = stmt.value.value if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Await) else None
                if not isinstance(call, ast.Call) or getattr(call.func, "id", "") != "_log_turn_end_safe" or len(call.args) < 8:
                    continue
                outcome = call.args[7]
                on_continue_path = outcome.body if isinstance(outcome, ast.IfExp) else outcome  # "x if repairing else y"
                literals = {n.value for n in ast.walk(on_continue_path) if isinstance(n, ast.Constant)}
                bad = literals & agent_loop._ERROR_OUTCOMES
                for later in stmts[i + 1:]:
                    if isinstance(later, (ast.Return, ast.Raise)):
                        break
                    if any(isinstance(n, ast.Continue) for n in ast.walk(later)):
                        if bad:
                            offenders.append((call.lineno, sorted(bad)))
                        break
    assert not offenders, f"error outcome logged on a path that continues the loop: {offenders}"
