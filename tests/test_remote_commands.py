from remote import commands


def test_plain_note_is_not_a_command():
    assert commands.parse("buy milk") is None
    assert commands.parse("") is None


def test_trigger_needs_whitespace_after_it():
    assert commands.parse("@gatorx hello") is None
    assert commands.parse("hey @gator hello") is None


def test_trigger_is_case_insensitive_and_text_is_trimmed():
    cmd = commands.parse("  @GATOR   what is open?  ")
    assert (cmd.kind, cmd.text) == ("send", "what is open?")


def test_bare_trigger_is_help():
    assert commands.parse("@gator").kind == "help"


def test_reserved_words():
    assert commands.parse("@gator list").kind == "list"
    assert commands.parse("@gator help").kind == "help"
    status = commands.parse("@gator status budget")
    assert (status.kind, status.name) == ("status", "budget")
    assert commands.parse("@gator status").name is None
    stop = commands.parse("@gator STOP budget-2")
    assert (stop.kind, stop.name) == ("stop", "budget-2")
    assert commands.parse("@gator stop").name is None


def test_stop_all_is_its_own_kind():
    assert commands.parse("@gator stop all").kind == "stop_all"
    assert commands.parse("@gator Stop   ALL").kind == "stop_all"


def test_anything_else_is_a_send_with_the_whole_text():
    cmd = commands.parse("@gator budget run the tests")
    assert (cmd.kind, cmd.text) == ("send", "budget run the tests")


def test_text_is_capped_at_4096_bytes():
    cmd = commands.parse("@gator " + "é" * 5000)
    assert len(cmd.text.encode()) <= 4096


def test_agent_reply_starts_with_gator_prefix_never_the_trigger():
    out = commands.agent_reply("Claude", "budget", "@gator stop all")
    assert out.startswith("[Gator - Claude - budget] ")
    assert not out.lower().startswith("@gator")


def test_long_reply_is_truncated_with_a_count():
    out = commands.agent_reply("Claude", "budget", "x" * 4000)
    body = out.split("] ", 1)[1]
    assert body.startswith("x" * 3500)
    assert body.endswith("(truncated, 500 more characters)")


def test_system_reply_starts_with_gator_prefix():
    assert commands.system_reply("Online") == "[Gator] Online"
