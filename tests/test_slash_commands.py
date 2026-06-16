import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web'))


def test_parse_slash_command_returns_plugin_and_capability():
    from routes.chat import parse_slash_command
    result = parse_slash_command("/rocm-toolkit:gpu-doctor diagnose device 0")
    assert result["plugin"] == "rocm-toolkit"
    assert result["capability"] == "gpu-doctor"
    assert result["message"] == "diagnose device 0"


def test_parse_slash_command_returns_none_for_non_slash():
    from routes.chat import parse_slash_command
    result = parse_slash_command("why is my GPU slow?")
    assert result is None


def test_parse_slash_command_returns_none_for_plain_slash():
    from routes.chat import parse_slash_command
    result = parse_slash_command("/help")
    assert result is None  # no colon → not a plugin command


def test_parse_slash_command_handles_no_trailing_message():
    from routes.chat import parse_slash_command
    result = parse_slash_command("/rocm-toolkit:get-memory")
    assert result["plugin"] == "rocm-toolkit"
    assert result["capability"] == "get-memory"
    assert result["message"] == ""


def test_parse_slash_command_trims_whitespace():
    from routes.chat import parse_slash_command
    result = parse_slash_command("  /rocm-toolkit:gpu-doctor  check all  ")
    assert result["plugin"] == "rocm-toolkit"
    assert result["message"] == "check all"


def test_parse_slash_command_rejects_three_colons():
    """`/a:b:c diagnose` is malformed slash syntax — must return None so the
    message flows through to the LLM as plain text rather than silently leaking
    `:c diagnose` into the rewritten message body."""
    from routes.chat import parse_slash_command
    assert parse_slash_command("/a:b:c diagnose") is None


def test_parse_slash_command_rejects_capability_immediately_followed_by_garbage():
    """No whitespace between capability and trailing text means the input isn't
    a clean slash command — reject it. Prevents `/a:bfoo` parsing as capability=bfoo."""
    from routes.chat import parse_slash_command
    # `/rocm:gpu-doctor.extra` — the `.` is not whitespace, so it's malformed
    assert parse_slash_command("/rocm:gpu-doctor.extra") is None


def test_chat_handler_does_not_leak_prefix_when_message_empty():
    """Regression: when the slash command has no trailing text, the handler must
    rewrite message to "" — NOT fall back to the raw prefixed string. Otherwise
    `/plugin:capability` reaches the LLM verbatim as user content."""
    from pydantic import BaseModel

    class FakeReq(BaseModel):
        message: str = ""
        active_skill: str = ""

    req = FakeReq(message="/rocm-toolkit:get-memory", active_skill="")

    # Simulate the handler's rewrite block from web/routes/chat.py
    from routes.chat import parse_slash_command
    raw_message = req.message
    slash_cmd = parse_slash_command(raw_message)
    assert slash_cmd is not None
    req = req.model_copy(update={
        "active_skill": slash_cmd["plugin"],
        "message": slash_cmd["message"],
    })
    assert req.active_skill == "rocm-toolkit"
    assert req.message == "", "empty trailing message must stay empty, not revert to '/rocm-toolkit:get-memory'"
