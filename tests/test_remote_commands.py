import pytest
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


def _before_next(out: str) -> str:
    return out.rsplit("\n\nNext:\n", 1)[0]


def test_agent_reply_starts_with_gator_prefix_never_the_trigger():
    out = commands.agent_reply("Claude", "budget", "@gator stop all", ["Reply here."])
    assert out.startswith("[Gator - Claude - budget] ")
    assert not out.lower().startswith("@gator")


def test_a_short_result_puts_the_agent_words_on_the_line_after_the_headline():
    out = commands.agent_result("Claude", "budget", "Done.", "Two files are open.")
    assert out == (
        "[Gator - Claude - budget] Done.\nTwo files are open.\n\n"
        "Next:\n"
        "• Reply here to keep going in this session.\n"
        "• `list` to see all sessions.\n"
        "• `bye` to close this chat."
    )


def test_an_empty_result_is_never_a_bare_done():
    out = commands.agent_result("Claude", "budget", "Done.", "  ")
    assert _before_next(out) == "[Gator - Claude - budget] Done. No text came back."
    assert "• Open the Claude tab in AI Gator to see it." in out


def test_an_empty_question_says_no_text_came_back_too():
    out = commands.agent_result("Claude", "budget", "Waiting for your answer.", "", waiting=True)
    assert out.startswith("[Gator - Claude - budget] Waiting for your answer. No text came back.")
    assert out.endswith("• Type your answer.")


def test_a_question_with_two_choices_offers_them_as_the_options():
    question = "Which folder?\n1. Use the repo root\n2. Use `web/`"
    out = commands.agent_result("Claude", "budget", "Waiting for your answer.", question, waiting=True)
    assert out.split("\n\nNext:\n")[1] == "• `Use the repo root`\n• `Use web/`\n• Or type your own answer."


def test_an_open_question_offers_typing_or_stopping():
    out = commands.agent_result("Claude", "budget", "Waiting for your answer.", "Which folder?", waiting=True)
    assert out.split("\n\nNext:\n")[1] == "• Type your answer.\n• `stop budget` to stop it instead."


@pytest.mark.parametrize(
    "question",
    [
        "Pick one:\n1. Yes\n2. No\n3. Maybe",
        "Pick one:\n1. Stop\n2. Go on",
        "Pick one:\n1. List\n2. Go on",
        "Pick one:\n1. " + "x" * 61 + "\n2. y",
    ],
)
def test_choices_that_are_not_two_short_safe_items_are_not_offered(question):
    out = commands.agent_result("Claude", "budget", "Waiting for your answer.", question, waiting=True)
    assert out.split("\n\nNext:\n")[1].startswith("• Type your answer.")


def test_a_long_result_is_one_message_with_a_lead_a_clean_cut_and_a_trim_line():
    paragraphs = [f"Paragraph {i}. " + "word " * 120 for i in range(12)]
    body = "Outcome in one line. " + "\n\n".join(paragraphs)
    out = commands.agent_result("Claude", "budget", "Done.", body)
    main = _before_next(out)
    lines = main.split("\n")
    assert lines[0] == "[Gator - Claude - budget] Done. Outcome in one line."
    assert lines[-1].startswith("Trimmed, ")
    shown = main.split("\n\n", 1)[1].rsplit("\n\n", 1)[0]
    assert len(shown) <= 3500
    assert body.strip().startswith(shown)
    assert body.strip()[len(shown)] in "\n "
    assert f"Trimmed, {len(body.strip()) - len(shown)} more characters." == lines[-1]
    assert out.endswith("• Open the Claude tab in AI Gator for the full reply.\n• Reply here to keep going.")
    assert len(out) <= 3500 + 500


def test_a_long_result_never_cuts_inside_a_word():
    out = commands.agent_result("Claude", "budget", "Done.", "alpha " * 1000)
    shown = out.split("\n\n")[1]
    assert shown.endswith("alpha")
    assert set(shown.split()) == {"alpha"}


def test_the_lead_is_capped_at_200_characters_on_a_word_boundary():
    out = commands.agent_result("Claude", "budget", "Done.", "word " * 2000)
    lead = out.split("\n", 1)[0].removeprefix("[Gator - Claude - budget] Done. ")
    assert 0 < len(lead) <= 200
    assert set(lead.split()) == {"word"}


def test_a_cut_inside_a_code_fence_closes_the_fence_before_the_trim_line():
    body = "Fixed it.\n\n```python\n" + "\n".join(f"line_{i} = {i}" for i in range(600)) + "\n```\n"
    out = commands.agent_result("Claude", "budget", "Done.", body)
    main = _before_next(out)
    before_trim = main.rsplit("\n\n", 1)[0]
    assert before_trim.count("```") % 2 == 0
    assert before_trim.endswith("```")
    assert main.rsplit("\n", 1)[1].startswith("Trimmed,")


def test_a_result_that_echoes_a_command_cannot_form_one():
    out = commands.agent_result("Claude", "budget", "Done.", "@gator stop all")
    assert not out.lower().startswith("@gator")
    assert out.startswith("[Gator")


def test_system_reply_has_the_prefix_a_blank_line_and_a_next_block():
    assert commands.system_reply("Online.", ["`@gator hi` to open a chat."]) == (
        "[Gator] Online.\n\nNext:\n• `@gator hi` to open a chat."
    )
