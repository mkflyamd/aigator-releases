"""Regression tests for execute_tool's required-param guard.

When a large tool-call argument (e.g. a ~44KB Confluence body) blows the model's
output-token budget, the tool-use JSON is truncated and required params arrive
missing. execute_tool must return a structured `missing_required_params` error —
never let Python raise a raw `TypeError: missing 1 required positional argument`.
"""
import asyncio

import app
import shared


def _run(coro):
    return asyncio.run(coro)


def _with_tool(name, fn):
    shared.TOOL_DISPATCH[name] = fn
    return name


def teardown_function():
    for n in ("_test_edit_form", "_test_ctx_tool", "_test_req"):
        shared.TOOL_DISPATCH.pop(n, None)


def test_missing_required_param_returns_structured_error():
    def _test_edit_form(page_id: str, body: str, version: int, title: str = ""):
        return {"ok": True}

    _with_tool("_test_edit_form", _test_edit_form)
    # body + version omitted (simulating truncated args)
    res = _run(app.execute_tool("_test_edit_form", {"page_id": "123"}))
    assert res.get("error") == "missing_required_params"
    assert res["tool"] == "_test_edit_form"
    assert set(res["missing"]) == {"body", "version"}
    assert "chunk" in res["hint"].lower() or "smaller" in res["hint"].lower()


def test_all_required_present_invokes_handler():
    def _test_edit_form(page_id: str, body: str, version: int, title: str = ""):
        return {"ok": True, "len": len(body)}

    _with_tool("_test_edit_form", _test_edit_form)
    res = _run(app.execute_tool("_test_edit_form", {"page_id": "1", "body": "x" * 10, "version": 2}))
    assert res == {"ok": True, "len": 10}


def test_empty_string_required_arg_treated_as_missing():
    # A truncated tool call can arrive with a present-but-empty required arg.
    # Treat "" (and whitespace-only) as missing, same as absent (#25).
    def _test_req(code: str):
        return {"ran": True}

    _with_tool("_test_req", _test_req)
    res = _run(app.execute_tool("_test_req", {"code": ""}))
    assert res.get("error") == "missing_required_params"
    assert res["missing"] == ["code"]


def test_whitespace_only_required_arg_treated_as_missing():
    def _test_req(code: str):
        return {"ran": True}

    _with_tool("_test_req", _test_req)
    res = _run(app.execute_tool("_test_req", {"code": "   \n  "}))
    assert res.get("error") == "missing_required_params"


def test_rejection_warn_log_includes_payload_size(caplog):
    import logging
    def _test_req(code: str):
        return {"ran": True}

    _with_tool("_test_req", _test_req)
    with caplog.at_level(logging.WARNING):
        _run(app.execute_tool("_test_req", {}))
    warns = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("missing required" in m.lower() and "_test_req" in m for m in warns)
    assert any("bytes" in m.lower() for m in warns)


def test_empty_string_allowed_for_exempt_required_arg():
    # write_file content="" (empty file) and edit_file new_str="" (deletion) are
    # legitimate empty required args and must NOT be rejected as missing (#25).
    def _test_write(path: str, content: str):
        return {"wrote": path, "len": len(content)}

    shared.TOOL_DISPATCH["write_file"] = _test_write
    try:
        res = _run(app.execute_tool("write_file", {"path": "a.txt", "content": ""}))
        assert res == {"wrote": "a.txt", "len": 0}
    finally:
        shared.TOOL_DISPATCH.pop("write_file", None)


def test_context_id_not_treated_as_required():
    def _test_ctx_tool(page_id: str, _context_id: str = "default"):
        return {"ctx": _context_id}

    _with_tool("_test_ctx_tool", _test_ctx_tool)
    res = _run(app.execute_tool("_test_ctx_tool", {"page_id": "1"}, context_id="tab-9"))
    assert res == {"ctx": "tab-9"}
