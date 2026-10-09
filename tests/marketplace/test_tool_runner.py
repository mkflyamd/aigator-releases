import json
import subprocess
import sys

from marketplace import skill_audit
from marketplace.tool_runner_source import ARGS_NAME, RESULT_NAME, RUNNER_NAME, RUNNER_SOURCE

HEADER = (
    'TOOL_DEFS = [{"name": "t", "description": "d", "input_schema": {"type": "object", "properties": {}}}]\n'
    'TOOL_STATUS = {"t": "Working"}\n'
)


def _run(tmp_path, tools_py, mode, name="", args=None, extra_files=None):
    skill = tmp_path / "skill"
    skill.mkdir(exist_ok=True)
    (skill / "tools.py").write_text(tools_py, encoding="utf-8")
    for rel, content in (extra_files or {}).items():
        (skill / rel).write_text(content, encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir(exist_ok=True)
    (run_dir / RUNNER_NAME).write_text(RUNNER_SOURCE, encoding="utf-8")
    argv = [sys.executable, "-X", "utf8", str(run_dir / RUNNER_NAME), mode, str(skill)]
    if name:
        argv.append(name)
        (run_dir / ARGS_NAME).write_text(json.dumps(args or {}), encoding="utf-8")
    proc = subprocess.run(argv, cwd=run_dir, capture_output=True, text=True, encoding="utf-8", timeout=60)
    result_file = run_dir / RESULT_NAME
    data = json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else None
    return proc, data


def test_describe_returns_defs_and_status(tmp_path):
    _, data = _run(tmp_path, HEADER + "def t(): return {}\nTOOL_HANDLERS = {'t': t}\n", "describe")
    assert data["ok"] is True
    assert data["defs"][0]["name"] == "t"
    assert data["status"] == {"t": "Working"}


def test_describe_flags_a_contract_mismatch(tmp_path):
    _, data = _run(tmp_path, HEADER + "TOOL_HANDLERS = {}\n", "describe")
    assert data["ok"] is False
    assert "tool contract mismatch" in data["error"]


def test_describe_reports_an_import_time_failure(tmp_path):
    _, data = _run(tmp_path, "raise RuntimeError('boom at import')\n", "describe")
    assert data["ok"] is False
    assert "boom at import" in data["error"]


def test_describe_reports_a_syntax_error(tmp_path):
    _, data = _run(tmp_path, "this is not python !!!\n", "describe")
    assert data["ok"] is False


def test_call_passes_keyword_arguments(tmp_path):
    src = HEADER + "def t(a, b=2): return {'sum': a + b}\nTOOL_HANDLERS = {'t': t}\n"
    _, data = _run(tmp_path, src, "call", "t", {"a": 5})
    assert data == {"ok": True, "result": {"sum": 7}}


def test_call_drops_unknown_arguments_and_context_id(tmp_path):
    src = HEADER + "def t(a): return {'a': a}\nTOOL_HANDLERS = {'t': t}\n"
    _, data = _run(tmp_path, src, "call", "t", {"a": 1, "extra": 2, "_context_id": "tab-1"})
    assert data["result"] == {"a": 1}


def test_call_gives_a_var_keyword_handler_everything_except_context_id(tmp_path):
    src = HEADER + "def t(**kw): return {'kw': sorted(kw)}\nTOOL_HANDLERS = {'t': t}\n"
    _, data = _run(tmp_path, src, "call", "t", {"a": 1, "b": 2, "_context_id": "x"})
    assert data["result"] == {"kw": ["a", "b"]}


def test_call_passes_the_whole_dict_to_a_single_dict_handler(tmp_path):
    src = HEADER + "def t(args: dict): return {'got': args}\nTOOL_HANDLERS = {'t': t}\n"
    _, data = _run(tmp_path, src, "call", "t", {"x": 1})
    assert data["result"] == {"got": {"x": 1}}


def test_call_awaits_an_async_handler(tmp_path):
    src = HEADER + "async def t(a): return {'a': a}\nTOOL_HANDLERS = {'t': t}\n"
    _, data = _run(tmp_path, src, "call", "t", {"a": 3})
    assert data["result"] == {"a": 3}


def test_call_reports_a_handler_exception(tmp_path):
    src = HEADER + "def t(): raise ValueError('bad input')\nTOOL_HANDLERS = {'t': t}\n"
    _, data = _run(tmp_path, src, "call", "t")
    assert data["ok"] is False and "bad input" in data["error"]


def test_call_reports_a_missing_required_argument(tmp_path):
    src = HEADER + "def t(a): return {}\nTOOL_HANDLERS = {'t': t}\n"
    _, data = _run(tmp_path, src, "call", "t", {})
    assert data["ok"] is False


def test_call_rejects_a_non_dict_result(tmp_path):
    src = HEADER + "def t(): return 'text'\nTOOL_HANDLERS = {'t': t}\n"
    _, data = _run(tmp_path, src, "call", "t")
    assert data["ok"] is False


def test_call_unknown_tool(tmp_path):
    src = HEADER + "def t(): return {}\nTOOL_HANDLERS = {'t': t}\n"
    _, data = _run(tmp_path, src, "call", "nope")
    assert data["ok"] is False and "nope" in data["error"]


def test_printing_does_not_corrupt_the_answer(tmp_path):
    src = HEADER + "def t():\n    print('noise on stdout')\n    return {'ok': True}\nTOOL_HANDLERS = {'t': t}\n"
    _, data = _run(tmp_path, src, "call", "t")
    assert data["result"] == {"ok": True}


def test_a_helper_module_next_to_tools_py_imports(tmp_path):
    src = HEADER + "import helper\ndef t(): return {'v': helper.VALUE}\nTOOL_HANDLERS = {'t': t}\n"
    _, data = _run(tmp_path, src, "call", "t", extra_files={"helper.py": "VALUE = 41\n"})
    assert data["result"] == {"v": 41}


def test_outbound_lookups_and_connections_are_reported_on_stderr(tmp_path):
    src = HEADER + (
        "import socket\n"
        "def t():\n"
        "    try:\n"
        "        socket.getaddrinfo('example.invalid', 443)\n"
        "    except OSError:\n"
        "        pass\n"
        "    return {}\n"
        "TOOL_HANDLERS = {'t': t}\n"
    )
    proc, data = _run(tmp_path, src, "call", "t")
    assert data["ok"] is True
    dests, _ = skill_audit.extract_outbound(proc.stderr)
    assert "example.invalid:443" in dests
