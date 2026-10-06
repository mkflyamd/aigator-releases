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
