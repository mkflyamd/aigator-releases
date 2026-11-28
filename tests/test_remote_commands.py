import pytest
from remote import commands


def test_plain_note_is_not_a_command():
    assert commands.parse("buy milk") is None
    assert commands.parse("") is None


def test_the_agent_prefix_has_two_slots_alone_and_three_while_several_sessions_are_live():
    assert commands.agent_prefix("budget", "Budget") == "[Ranger - Budget] \U0001F40A"
    assert commands.agent_prefix("budget", "Budget", several=True) == "[Ranger - budget - Budget] \U0001F40A"
    assert commands.agent_prefix("budget") == "[Ranger - budget] \U0001F40A"


def test_the_loop_guard_ignores_the_ranger_prefix_and_not_a_plain_bracket_note():
    assert commands.is_own_message("[Ranger - proj] \U0001F40A Done.")
    assert commands.is_own_message("[Ranger - one - proj] \U0001F40A Done.")
    assert not commands.is_own_message("[todo] x")


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
    out = commands.agent_reply("budget", "@gator stop all", ["Reply here."])
    assert out.startswith("[Ranger - budget] \U0001F40A ")
    assert not out.lower().startswith("@gator")


def test_a_short_result_puts_the_agent_words_on_the_line_after_the_headline():
    out = commands.agent_result("Claude", "budget", "Done.", "Two files are open.")
    assert out == "[Ranger - budget] \U0001F40A Done.\nTwo files are open."


def test_a_quick_answer_is_the_prefix_and_the_words_only():
    out = commands.agent_result("Claude", "budget", "", "Two files are open.")
    assert out == "[Ranger - budget] \U0001F40A Two files are open."


def test_an_empty_result_is_never_a_bare_done():
    out = commands.agent_result("Claude", "budget", "Done.", "  ")
    assert _before_next(out) == "[Ranger - budget] \U0001F40A Done. No text came back."
    assert "• Open the Claude tab in AI Gator to see it." in out


def test_an_empty_question_says_no_text_came_back_too():
    out = commands.agent_result("Claude", "budget", "Waiting for your answer.", "", waiting=True)
    assert out.startswith("[Ranger - budget] \U0001F40A Waiting for your answer. No text came back.")
    assert out.endswith("• Type your answer.")


def test_a_question_with_two_choices_offers_them_as_the_options():
    question = "Which folder?\n1. Use the repo root\n2. Use `web/`"
    out = commands.agent_result("Claude", "budget", "Waiting for your answer.", question, waiting=True)
    assert out.split("\n\nNext:\n")[1] == "• `Use the repo root`\n• `Use web/`"


def test_with_several_sessions_each_choice_names_its_session():
    question = "Which folder?\n1. Use the repo root\n2. Use `web/`"
    out = commands.agent_result("Claude", "budget", "Waiting for your answer.", question, waiting=True, several=True)
    assert out.split("\n\nNext:\n")[1] == "• `budget: Use the repo root`\n• `budget: Use web/`"


def test_an_open_question_has_no_next_block():
    out = commands.agent_result("Claude", "budget", "Waiting for your answer.", "Which folder?", waiting=True)
    assert out == "[Ranger - budget] \U0001F40A Waiting for your answer.\nWhich folder?"


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
    assert "Next:" not in out


def test_a_long_result_is_one_message_with_a_lead_a_clean_cut_and_a_trim_line():
    paragraphs = [f"Paragraph {i}. " + "word " * 120 for i in range(12)]
    body = "Outcome in one line. " + "\n\n".join(paragraphs)
    out = commands.agent_result("Claude", "budget", "Done.", body)
    main = _before_next(out)
    lines = main.split("\n")
    assert lines[0] == "[Ranger - budget] \U0001F40A Done. Outcome in one line."
    assert lines[-1].startswith("Trimmed, ")
    shown = main.split("\n\n", 1)[1].rsplit("\n\n", 1)[0]
    assert len(shown) <= 3500
    tidy = "\n".join(line.rstrip() for line in body.strip().split("\n"))
    assert tidy.startswith(shown)
    assert tidy[len(shown)] in "\n "
    assert f"Trimmed, {len(tidy) - len(shown)} more characters." == lines[-1]
    assert out.endswith("• Open the Claude tab in AI Gator for the full reply.\n• Reply here to keep going.")
    assert len(out) <= 3500 + 500


def test_a_long_result_never_cuts_inside_a_word():
    out = commands.agent_result("Claude", "budget", "Done.", "alpha " * 1000)
    shown = out.split("\n\n")[1]
    assert shown.endswith("alpha")
    assert set(shown.split()) == {"alpha"}


def test_the_lead_is_capped_at_200_characters_on_a_word_boundary():
    out = commands.agent_result("Claude", "budget", "Done.", "word " * 2000)
    lead = out.split("\n", 1)[0].removeprefix("[Ranger - budget] \U0001F40A Done. ")
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
    assert commands.is_own_message(out)


def test_system_reply_has_the_prefix_a_blank_line_and_a_next_block():
    assert commands.system_reply("Online.", ["`@gator hi` to open a chat."]) == (
        "[Gator] Online.\n\nNext:\n• `@gator hi` to open a chat."
    )


def test_replies_have_no_trailing_spaces_and_no_double_blank_lines():
    out = commands.agent_result("Claude", "budget", "Done.", "one  \n\n\n\ntwo \n")
    assert out == "[Ranger - budget] \U0001F40A Done.\none\n\ntwo"


def test_done_says_the_elapsed_time_only_past_a_minute():
    assert commands.done_headline(None) == "Done."
    assert commands.done_headline(60) == "Done."
    assert commands.done_headline(61) == "Done in 1 min."
    assert commands.done_headline(12 * 60 + 5) == "Done in 12 min."
    assert commands.done_headline(3600 + 5 * 60) == "Done in 1 h 5 min."
    assert commands.done_headline(7200) == "Done in 2 h."


def test_working_names_the_branch_and_offers_stop():
    assert commands.working("budget", "main", False) == (
        "[Ranger - budget] \U0001F40A Working on it.\nBranch: main\n\nNext:\n• `stop` to stop it."
    )
    assert commands.working("budget", None, True, project="Budget") == (
        "[Ranger - budget - Budget] \U0001F40A Working on it.\n\nNext:\n• `stop budget` to stop it."
    )


def test_still_working_has_no_options():
    assert commands.progress("budget", 130) == "[Ranger - budget] \U0001F40A Still working, 2 min."


def test_an_unknown_name_lists_at_most_three_sessions():
    out = commands.unknown_mention("ghost", ["a", "b", "c", "d"])
    assert out == (
        "[Gator] I don't know ghost. Start with `@gator` to send it to Ranger.\n\n"
        "Next:\n• `a: your message`\n• `b: your message`\n• `c: your message`"
    )
    assert commands.unknown_mention("ghost", []) == (
        "[Gator] I don't know ghost. Start with `@gator` to send it to Ranger."
    )


@pytest.mark.parametrize(
    "question, asks",
    [
        ("Which folder?", True),
        ("Done. Want me to push?", True),
        ("Which one?\n1. Yes\n2. No", True),
        ("All done.", False),
        ("Is it fixed? Yes, it is.", False),
    ],
)
def test_a_trailing_question_is_detected(question, asks):
    assert commands.asks_a_question(question) is asks


@pytest.mark.parametrize(
    "text, own",
    [
        ("[Gator] \U0001F40A x", True),
        ("[Claude - proj] \U0001F40A x", True),
        ("[Ranger - proj - sess] \U0001F40A x", True),
        ("[Ranger - proj] \U0001F40A Done.", True),
        ("  [Gator] x", True),
        ("[todo] fix it", False),
        ("[todo] \U0001F40A fix it", True),
        ("[" + "x" * 81 + "] \U0001F40A y", False),
        ("[a\nb] \U0001F40A y", False),
        ("fix it [Gator] \U0001F40A", False),
    ],
)
def test_own_messages_are_matched_by_shape(text, own):
    assert commands.is_own_message(text) is own
