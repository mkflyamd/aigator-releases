import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "web"))

import pytest

from runs.model_result import model_result
from runs.records import STATES, exit_info

_VERDICT_WORDS = re.compile(r"probably|crashed|not running|succeeded|\bdied\b", re.IGNORECASE)
_FACTS = {"urls_seen": ["http://127.0.0.1:4173/p/demo/"], "ports_opened": [4173], "children_left": []}


def _record(state, code=None, facts=None, **extra):
    return {"id": "r1", "state": state, "exit": exit_info(code), "facts": facts or {}, **extra}


def test_the_result_has_one_shape_with_run_id_state_exit_facts_and_output():
    out = model_result(_record("finished", 0, _FACTS), {"stdout": "hi", "stderr": ""})
    assert out["run_id"] == "r1" and out["state"] == "finished"
    assert out["exit"] == {"code": 0, "hex": "0x00000000", "class": "zero"}
    assert out["facts"]["urls_seen"] == ["http://127.0.0.1:4173/p/demo/"]
    assert out["stdout"] == "hi" and "message" not in out


def test_an_exit_in_the_status_code_range_is_a_class_not_a_verdict():
    out = model_result(_record("finished", -1073741510), {})
    assert out["exit"]["class"] == "ntstatus_range"
    assert out["exit"]["hex"] == "0xC000013A"


def test_an_abnormal_exit_with_facts_gets_one_neutral_line_pointing_at_the_facts():
    out = model_result(_record("finished", 3, _FACTS), {"stdout": "Viewer at http://127.0.0.1:4173/p/demo/"})
    assert "urls_seen" in out["message"] and "ports_opened" in out["message"]
    assert out["message"].count("\n") == 0


def test_an_abnormal_exit_with_no_facts_gets_no_line():
    assert "message" not in model_result(_record("finished", 3), {"stdout": "boom"})


def test_a_clean_exit_with_facts_gets_no_line():
    assert "message" not in model_result(_record("finished", 0, _FACTS), {})


def test_a_refused_start_shows_its_reason():
    out = model_result(_record("failed_to_start", reason="concurrency_cap"), {})
    assert "concurrency_cap" in out["message"]


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("code", [None, 0, 3, -1073741510])
def test_no_result_for_any_state_or_exit_uses_verdict_words(state, code):
    out = model_result(_record(state, code, _FACTS, reason="concurrency_cap"), {"stdout": "", "stderr": ""})
    assert not _VERDICT_WORDS.search(json.dumps(out)), out


def _messages_in(path):
    import ast

    tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) in (
                "_shell_error", "ProbeRefused"):
            found += [n.value for arg in node.args for n in ast.walk(arg)
                      if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "").endswith("_MSG") for t in node.targets):
            found += [n.value for n in ast.walk(node.value) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    return found


@pytest.mark.parametrize("path", ["web/skills/shell_runner/tools.py", "web/runs/probe.py"])
def test_no_error_or_refusal_message_the_model_can_read_uses_verdict_words(path):
    root = pathlib.Path(__file__).parent.parent.parent
    messages = _messages_in(root / path)
    assert messages, "the scan found no messages, so it checks nothing"
    assert not [m for m in messages if _VERDICT_WORDS.search(m)]


def test_a_run_with_no_exit_code_gets_no_abnormal_exit_note():
    out = model_result(_record("timed_out", None, _FACTS), {})
    assert "ports_opened" not in out.get("message", "")
