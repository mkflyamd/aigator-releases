import pathlib
import sys
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from agent_loop import _summarize_tool_calls


def test_sandbox_telemetry_is_attached_to_the_tool_call_entry():
    rec = {"run_id": "r1", "skill_id": "", "level": "enforced", "network": False,
           "extra_read": 0, "extra_write": 0, "approval": None}
    tc = SimpleNamespace(name="run_python")
    (entry,) = _summarize_tool_calls([tc], [{"error": None, "stdout": "secret output", "_sandbox_telemetry": rec}])
    assert entry == {"name": "run_python", "success": True, "sandbox": rec}
    (failed,) = _summarize_tool_calls([tc], [{"error": "boom", "_sandbox_telemetry": rec}])
    assert failed["sandbox"] == rec and failed["success"] is False


def test_other_tools_unchanged():
    (entry,) = _summarize_tool_calls([SimpleNamespace(name="x")], [{"result": "ok"}])
    assert entry == {"name": "x", "success": True}


import asyncio

from agent_loop import _make_tool_runner


def test_runner_emits_sandbox_approval_event():
    card = {"request_id": "abc", "read_paths": ["C:/data"], "write_paths": [], "network_hosts": [], "context_id": "tab-1"}

    async def fake_execute(name, inputs, **kw):
        return {"approval_required": True, "request_id": "abc", "_sandbox_approval": card}

    run_tool_block, _, _ = _make_tool_runner(fake_execute, set(), {}, lambda n, r: None, "__slack_safe__")

    async def go():
        q = asyncio.Queue()
        await run_tool_block(SimpleNamespace(name="run_python", inputs={"code": "1"}, id="c1"), q)
        return [q.get_nowait() for _ in range(q.qsize())]

    loop = asyncio.new_event_loop()
    try:
        events = loop.run_until_complete(go())
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())
    assert {"kind": "sandbox_approval", "data": card} in events


def test_both_stream_loops_forward_sandbox_approval():
    src = (pathlib.Path(__file__).parent.parent / "web" / "agent_loop.py").read_text(encoding="utf-8")
    assert src.count("yield f\"data: {json.dumps({'sandbox_approval': evt.get('data', {})})}\\n\\n\"") == 2


def _capture_run_python(monkeypatch):
    import shared

    seen = {}

    def fake_run_python(code: str = "", _context_id: str = ""):
        seen["inputs"] = {"code": code, "_context_id": _context_id}
        return {"ok": True}

    monkeypatch.setitem(shared.TOOL_DISPATCH, "run_python", fake_run_python)
    return seen


def test_model_supplied_context_id_never_reaches_tool_without_server_value(monkeypatch):
    import app

    seen = _capture_run_python(monkeypatch)
    asyncio.run(app.execute_tool("run_python", {"code": "1", "_context_id": "victim-tab"}))
    assert seen["inputs"]["_context_id"] == ""


def test_model_supplied_context_id_is_stripped_for_var_keyword_tool_without_server_value(monkeypatch):
    import app
    import shared

    seen = {}

    def tool(**kwargs):
        seen["kwargs"] = kwargs
        return {"ok": True}

    monkeypatch.setitem(shared.TOOL_DISPATCH, "kw_tool", tool)
    asyncio.run(app.execute_tool("kw_tool", {"x": 1, "_context_id": "victim-tab"}))
    assert seen["kwargs"] == {"x": 1}


def test_server_context_id_overwrites_model_supplied_one(monkeypatch):
    import app

    seen = _capture_run_python(monkeypatch)
    asyncio.run(app.execute_tool("run_python", {"code": "1", "_context_id": "victim-tab"}, context_id="tab-1"))
    assert seen["inputs"]["_context_id"] == "tab-1"
