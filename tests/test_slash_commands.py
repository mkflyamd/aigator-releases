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


# ── Increment 2, item 4: minimal plugin commands (decision #11) ────────────
# try_expand_command() is wired into routes.chat's chat() handler BEFORE
# parse_slash_command(). These tests exercise the same two-step flow the
# handler runs, using the real registry (marketplace.commands.COMMAND_REGISTRY)
# to prove the two slash surfaces don't collide.

def test_bare_registered_command_message_gets_expanded_before_slash_parsing():
    from marketplace.commands import COMMAND_REGISTRY, try_expand_command
    from routes.chat import parse_slash_command

    COMMAND_REGISTRY["standup"] = {
        "body": "Write a standup update for $ARGUMENTS.",
        "description": "",
        "plugin_id": "test-plugin",
    }
    try:
        raw_message = "/standup yesterday's work"
        expanded = try_expand_command(raw_message)
        assert expanded == "Write a standup update for yesterday's work."
        # Simulates the handler: expansion happens, then parse_slash_command
        # runs on the (already-expanded) message and correctly finds no
        # /plugin:capability syntax in it.
        assert parse_slash_command(expanded) is None
    finally:
        COMMAND_REGISTRY.pop("standup", None)


def test_plugin_capability_message_is_untouched_by_command_expansion():
    """/plugin:capability messages must reach parse_slash_command exactly as
    typed — try_expand_command must return None for them even when a command
    happens to be registered under a colliding leading name."""
    from marketplace.commands import COMMAND_REGISTRY, try_expand_command
    from routes.chat import parse_slash_command

    COMMAND_REGISTRY["rocm-toolkit"] = {"body": "should never fire", "description": "", "plugin_id": "p"}
    try:
        raw_message = "/rocm-toolkit:gpu-doctor diagnose device 0"
        assert try_expand_command(raw_message) is None
        slash_cmd = parse_slash_command(raw_message)
        assert slash_cmd == {"plugin": "rocm-toolkit", "capability": "gpu-doctor", "message": "diagnose device 0"}
    finally:
        COMMAND_REGISTRY.pop("rocm-toolkit", None)


def test_unregistered_bare_slash_message_falls_through_unchanged():
    from marketplace.commands import try_expand_command
    assert try_expand_command("/not-a-real-command with args") is None
