import inspect
import json
import logging
import time
from pathlib import Path

import pytest

import config
import sandbox
from marketplace import installer, state
from marketplace import tool_sandbox as T
from marketplace.permissions import Permissions

NOOP = (
    'TOOL_DEFS = [{"name": "noop", "description": "d", "input_schema": {"type": "object", "properties": {}}}]\n'
    'TOOL_STATUS = {"noop": "Working"}\n'
    "def noop():\n"
    "    return {'ok': True}\n"
    "TOOL_HANDLERS = {'noop': noop}\n"
)

needs_sandbox = pytest.mark.skipif(
    sandbox.sandbox_level() != "enforced", reason="OS sandbox is not enforced on this machine"
)


@pytest.fixture(autouse=True)
def _index():
    installer.save_installed([{"id": "demo", "version": "1.0", "tier": "community"}])
    yield
    installer.save_installed([])


def _outputs():
    root = Path(config.OUTPUTS_DIR)
    return set(root.iterdir()) if root.exists() else set()


def test_describe_returns_the_tool_list(passthrough_sandbox, make_skill_dir):
    skill = make_skill_dir({"tools.py": NOOP})
    data = T.describe_skill_tools("demo", skill, Permissions())
    assert data["ok"] is True
    assert [d["name"] for d in data["defs"]] == ["noop"]
    assert data["status"] == {"noop": "Working"}


def test_call_returns_the_tools_result(passthrough_sandbox, make_skill_dir):
    skill = make_skill_dir({"tools.py": NOOP})
    assert T.call_skill_tool("demo", skill, "noop", {}, "Community") == {"ok": True}


def test_a_tool_that_raises_becomes_a_tool_error(passthrough_sandbox, make_skill_dir):
    src = NOOP.replace("return {'ok': True}", "raise ValueError('bad input')")
    skill = make_skill_dir({"tools.py": src})
    result = T.call_skill_tool("demo", skill, "noop", {}, "Community")
    assert "bad input" in result["error"]


def test_a_broken_tools_py_is_a_describe_failure(passthrough_sandbox, make_skill_dir):
    skill = make_skill_dir({"tools.py": "this is not python !!!\n"})
    data = T.describe_skill_tools("demo", skill, Permissions())
    assert data["ok"] is False and data["error"]


def test_a_tools_py_that_imports_the_apps_modules_gets_a_clear_message(passthrough_sandbox, make_skill_dir):
    skill = make_skill_dir({"tools.py": "import shared\n" + NOOP})
    data = T.describe_skill_tools("demo", skill, Permissions())
    assert data["ok"] is False
    assert "cannot reach" in data["error"]


def test_sandbox_unavailable_means_no_tool_result_and_nothing_runs(fake_sandbox, make_skill_dir):
    skill = make_skill_dir({"tools.py": NOOP})
    fake_sandbox.raises = sandbox.SandboxUnavailable("no sandbox")
    result = T.call_skill_tool("demo", skill, "noop", {}, "Community")
    assert result["error"]
    assert T.describe_skill_tools("demo", skill, Permissions())["ok"] is False


def test_a_timeout_is_a_tool_error(passthrough_sandbox, make_skill_dir, monkeypatch):
    monkeypatch.setattr(T, "_timeout_for", lambda tier: 1)
    src = "import time\n" + NOOP.replace("return {'ok': True}", "time.sleep(5)\n    return {}")
    skill = make_skill_dir({"tools.py": src})
    result = T.call_skill_tool("demo", skill, "noop", {}, "Community")
    assert "timed out after 1 seconds" in result["error"]


def test_timeouts_come_from_config_by_tier(monkeypatch):
    monkeypatch.setattr(config, "load_config", lambda: {"code_runner_timeout_community": 7})
    assert T._timeout_for("Community") == 7
    assert T._timeout_for("Verified") == 60


def test_the_run_folder_is_removed_after_every_call(passthrough_sandbox, make_skill_dir):
    skill = make_skill_dir({"tools.py": NOOP})
    before = _outputs()
    T.call_skill_tool("demo", skill, "noop", {}, "Community")
    T.describe_skill_tools("demo", skill, Permissions())
    passthrough_sandbox.raises = sandbox.SandboxRunError("boom")
    T.call_skill_tool("demo", skill, "noop", {}, "Community")
    assert _outputs() == before


def test_the_approved_permissions_decide_network(passthrough_sandbox, make_skill_dir):
    skill = make_skill_dir({"tools.py": NOOP})
    T.call_skill_tool("demo", skill, "noop", {}, "Community")
    state.record_approval("demo", Permissions(network=("api.example.com",)).to_dict())
    T.call_skill_tool("demo", skill, "noop", {}, "Community")
    assert [r.network for r in passthrough_sandbox.requests] == [False, True]


def test_describe_uses_the_permissions_it_is_given(passthrough_sandbox, make_skill_dir):
    skill = make_skill_dir({"tools.py": NOOP})
    T.describe_skill_tools("demo", skill, Permissions(network=("a.example.com",)))
    assert passthrough_sandbox.requests[0].network is True


def test_a_disabled_skill_is_refused_without_launching(fake_sandbox, make_skill_dir):
    skill = make_skill_dir({"tools.py": NOOP})
    state.set_disabled("demo", True)
    assert T.call_skill_tool("demo", skill, "noop", {}, "Community") == {"error": "skill is disabled"}
    assert fake_sandbox.requests == []


def test_outbound_destinations_are_logged(passthrough_sandbox, make_skill_dir, caplog):
    src = (
        "import socket\n"
        + NOOP.replace(
            "return {'ok': True}",
            "try:\n        socket.getaddrinfo('example.invalid', 443)\n    except OSError:\n        pass\n    return {'ok': True}",
        )
    )
    skill = make_skill_dir({"tools.py": src})
    with caplog.at_level(logging.INFO, logger="aigator.skill_audit"):
        result = T.call_skill_tool("demo", skill, "noop", {}, "Community")
    assert result == {"ok": True}
    assert "skill-outbound skill=demo dest=example.invalid:443" in caplog.text


def test_every_run_is_logged_as_a_launch(passthrough_sandbox, make_skill_dir, caplog):
    skill = make_skill_dir({"tools.py": NOOP})
    with caplog.at_level(logging.INFO, logger="aigator.skill_audit"):
        T.call_skill_tool("demo", skill, "noop", {}, "Community")
    assert "skill-launch skill=demo kind=tool" in caplog.text


def test_a_failure_before_the_launch_is_an_error_and_nothing_runs(fake_sandbox, make_skill_dir, monkeypatch):
    skill = make_skill_dir({"tools.py": "open(__file__ + '.ran', 'w').write('x')\n" + NOOP})

    def boom():
        raise OSError("disk full")

    monkeypatch.setattr(T, "new_run_dir", boom)
    assert T.call_skill_tool("demo", skill, "noop", {}, "Community")["error"]
    data = T.describe_skill_tools("demo", skill, Permissions())
    assert data["ok"] is False and data["error"]
    assert fake_sandbox.requests == []
    assert not (skill / "tools.py.ran").exists()


def test_an_unexpected_error_from_the_launch_is_an_error_not_an_exception(fake_sandbox, make_skill_dir):
    skill = make_skill_dir({"tools.py": NOOP})
    fake_sandbox.raises = RuntimeError("unexpected")
    assert T.call_skill_tool("demo", skill, "noop", {}, "Community")["error"]
    assert T.describe_skill_tools("demo", skill, Permissions())["ok"] is False


def test_the_stub_is_a_single_dict_argument_function(make_skill_dir):
    stub = T.make_stub("demo", make_skill_dir({"tools.py": NOOP}), "noop", "Community")
    params = list(inspect.signature(stub).parameters.values())
    assert len(params) == 1 and params[0].annotation in (dict, "dict")
    assert not inspect.iscoroutinefunction(stub)


def test_the_stub_calls_the_tool(passthrough_sandbox, make_skill_dir):
    stub = T.make_stub("demo", make_skill_dir({"tools.py": NOOP}), "noop", "Community")
    assert stub({}) == {"ok": True}


@needs_sandbox
def test_real_sandbox_noop_call_stays_under_two_seconds(make_skill_dir):
    skill = make_skill_dir({"tools.py": NOOP})
    # The first sandbox launch on a machine grants the interpreter folders to the sandbox profile
    # (one-time icacls work, ~20 s here with a fresh ledger); the latency that matters is a warm call.
    assert T.call_skill_tool("demo", skill, "noop", {}, "Community") == {"ok": True}
    started = time.monotonic()
    result = T.call_skill_tool("demo", skill, "noop", {}, "Community")
    elapsed = time.monotonic() - started
    assert result == {"ok": True}
    assert elapsed < 2.0, f"a no-op sandboxed tool call took {elapsed:.2f}s"


@needs_sandbox
def test_real_sandbox_tool_cannot_read_a_file_it_was_not_granted(make_skill_dir, tmp_path):
    secret = tmp_path / "outside.txt"
    secret.write_text("secret-content", encoding="utf-8")
    src = NOOP.replace("return {'ok': True}", f"return {{'text': open({str(secret)!r}).read()}}")
    skill = make_skill_dir({"tools.py": src})
    result = T.call_skill_tool("demo", skill, "noop", {}, "Community")
    assert "secret-content" not in json.dumps(result)
    # Windows and macOS deny with PermissionError; Linux (bwrap) does not mount the path at all.
    assert result.get("error", "").startswith(("PermissionError", "FileNotFoundError", "OSError")), result


@needs_sandbox
def test_real_sandbox_tool_cannot_write_into_its_own_folder(make_skill_dir):
    src = NOOP.replace("return {'ok': True}", "open(__file__ + '.pwned', 'w').write('x')\n    return {'ok': True}")
    skill = make_skill_dir({"tools.py": src})
    result = T.call_skill_tool("demo", skill, "noop", {}, "Community")
    # Linux (bwrap) mounts the skill folder read-only, which raises a plain OSError (EROFS).
    assert result.get("error", "").startswith(("PermissionError", "OSError")), result
    assert not (skill / "tools.py.pwned").exists()


@needs_sandbox
def test_real_sandbox_tool_without_approved_network_cannot_connect(make_skill_dir):
    # An IP address, so a failed name lookup is not what stops it. No approval is recorded for "demo".
    src = (
        "import socket\n"
        + NOOP.replace(
            "return {'ok': True}",
            "socket.create_connection(('1.1.1.1', 443), timeout=3)\n    return {'ok': True}",
        )
    )
    skill = make_skill_dir({"tools.py": src})
    result = T.call_skill_tool("demo", skill, "noop", {}, "Community")
    error = result.get("error", "")
    # The runner reports type(exc).__name__: a refused or blocked connect is an OSError (often PermissionError).
    assert error.startswith(("PermissionError", "OSError", "Connection", "TimeoutError")), result
    assert result.get("ok") is not True

    # The sandbox itself works: a no-op tool in the same kind of skill runs fine.
    ok_skill = make_skill_dir({"tools.py": NOOP}, name="demo-ok")
    assert T.call_skill_tool("demo", ok_skill, "noop", {}, "Community") == {"ok": True}
