import pytest
from remote import commands


def test_plain_note_is_not_a_command():
    assert commands.parse("buy milk") is None
    assert commands.parse("") is None


def test_the_agent_prefix_has_two_slots_alone_and_three_while_several_sessions_are_live():
    assert commands.agent_prefix("budget", "Budget") == "[\U0001F40A Gator - Budget]"
    assert commands.agent_prefix("budget", "Budget", several=True) == "[\U0001F40A Gator - budget - Budget]"
    assert commands.agent_prefix("budget") == "[\U0001F40A Gator - budget]"


def test_the_not_armed_reply_is_app_voice_and_ignored_by_the_loop_guard():
    reply = commands.not_armed()
    assert reply.startswith("[\U0001F40A Gator]")
    assert commands.is_own_message(reply)


def test_the_app_voice_and_the_agent_voice_differ_only_by_the_project_slot():
    assert commands.app_prefix() == "[\U0001F40A Gator]"
    assert commands.agent_prefix("budget", "Budget") == "[\U0001F40A Gator - Budget]"
    assert commands.agent_prefix("budget", "Budget", several=True) != commands.app_prefix()


def test_the_agent_name_defaults_to_gator_and_follows_the_setting(monkeypatch):
    from remote import settings

    monkeypatch.setattr(settings, "load_config", lambda: {})
    assert commands.app_prefix() == "[\U0001F40A Gator]"
    monkeypatch.setattr(settings, "load_config", lambda: {"remote_agent_name": "Skipper"})
    assert commands.app_prefix() == "[\U0001F40A Skipper]"
    assert commands.agent_prefix("budget", "Budget") == "[\U0001F40A Skipper - Budget]"
    assert commands.online().startswith("[\U0001F40A Skipper] Online.")


@pytest.mark.parametrize("bad", ["", "   ", "a]b", "[a", "a\nb", "x" * 21, 7, None, True])
def test_an_invalid_agent_name_falls_back_to_gator(monkeypatch, bad):
    from remote import settings

    monkeypatch.setattr(settings, "load_config", lambda: {"remote_agent_name": bad})
    assert commands.app_prefix() == "[\U0001F40A Gator]"


def test_a_custom_name_is_still_ignored_by_the_loop_guard(monkeypatch):
    from remote import settings

    monkeypatch.setattr(settings, "load_config", lambda: {"remote_agent_name": "Skipper"})
    assert commands.is_own_message(commands.app_prefix() + " Online.")
    assert commands.is_own_message(commands.agent_prefix("budget", "Budget") + " Done.")


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
    assert out.startswith("[\U0001F40A Gator - budget] ")
    assert not out.lower().startswith("@gator")


def test_a_short_result_puts_the_agent_words_on_the_line_after_the_headline():
    out = commands.agent_result("Claude", "budget", "Done.", "Two files are open.")[0]
    assert out == "[\U0001F40A Gator - budget] Done.\nTwo files are open."


def test_a_quick_answer_is_the_prefix_and_the_words_only():
    out = commands.agent_result("Claude", "budget", "", "Two files are open.")[0]
    assert out == "[\U0001F40A Gator - budget] Two files are open."


def test_an_empty_result_is_never_a_bare_done():
    out = commands.agent_result("Claude", "budget", "Done.", "  ")[0]
    assert _before_next(out) == "[\U0001F40A Gator - budget] Done. No text came back."
    assert "• Open the Claude tab in AI Gator to see it." in out


def test_an_empty_question_says_no_text_came_back_too():
    out = commands.agent_result("Claude", "budget", "Waiting for your answer.", "", waiting=True)[0]
    assert out.startswith("[\U0001F40A Gator - budget] Waiting for your answer. No text came back.")
    assert out.endswith("• Type your answer.")


def test_a_question_with_two_choices_offers_them_as_the_options():
    question = "Which folder?\n1. Use the repo root\n2. Use `web/`"
    out = commands.agent_result("Claude", "budget", "Waiting for your answer.", question, waiting=True)[0]
    assert out.split("\n\nNext:\n")[1] == "• `Use the repo root`\n• `Use web/`"


def test_with_several_sessions_each_choice_names_its_session():
    question = "Which folder?\n1. Use the repo root\n2. Use `web/`"
    out = commands.agent_result("Claude", "budget", "Waiting for your answer.", question, waiting=True, several=True)[0]
    assert out.split("\n\nNext:\n")[1] == "• `budget: Use the repo root`\n• `budget: Use web/`"


def test_an_open_question_has_no_next_block():
    out = commands.agent_result("Claude", "budget", "Waiting for your answer.", "Which folder?", waiting=True)[0]
    assert out == "[\U0001F40A Gator - budget] Waiting for your answer.\nWhich folder?"


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
    out = commands.agent_result("Claude", "budget", "Waiting for your answer.", question, waiting=True)[0]
    assert "Next:" not in out


def _body_of(part):
    """The agent's words in one posted part: after the first line, before any Next block."""
    return _before_next(part).split("\n", 1)[1]


def test_a_long_result_goes_out_in_numbered_parts_cut_at_paragraphs():
    paragraphs = [f"Paragraph {i}. " + "word " * 120 for i in range(12)]
    body = "\n\n".join(paragraphs)
    parts = commands.agent_result("Claude", "budget", "Done.", body)
    assert len(parts) == 3
    for number, part in enumerate(parts, 1):
        assert part.startswith(f"[\U0001F40A Gator - budget] Done. ({number}/3)\n")
        assert len(_body_of(part)) <= 3500
    pieces = [_body_of(part) for part in parts]
    assert all(piece.startswith("Paragraph ") for piece in pieces)
    assert "\n\n".join(pieces) == "\n".join(line.rstrip() for line in body.split("\n"))


def test_a_long_result_never_cuts_inside_a_word():
    parts = commands.agent_result("Claude", "budget", "Done.", "alpha " * 1000)
    assert len(parts) == 2
    for part in parts:
        assert set(_body_of(part).split()) == {"alpha"}


def test_a_quick_answer_in_parts_keeps_the_prefix_and_marks_each_part():
    parts = commands.agent_result("Claude", "budget", "", "word " * 2000)
    assert [p.split("\n", 1)[0] for p in parts] == [
        "[\U0001F40A Gator - budget] (1/3)",
        "[\U0001F40A Gator - budget] (2/3)",
        "[\U0001F40A Gator - budget] (3/3)",
    ]


def test_a_short_result_is_one_message_with_no_part_marker():
    (only,) = commands.agent_result("Claude", "budget", "Done.", "Two files are open.")
    assert only == "[\U0001F40A Gator - budget] Done.\nTwo files are open."


def test_a_cut_inside_a_code_fence_closes_it_and_opens_it_again():
    body = "Fixed it.\n\n```python\n" + "\n".join(f"line_{i} = {i}" for i in range(600)) + "\n```\n"
    parts = commands.agent_result("Claude", "budget", "Done.", body)
    assert len(parts) > 1
    for part in parts:
        assert _body_of(part).count("```") % 2 == 0
    assert _body_of(parts[0]).endswith("```")
    assert _body_of(parts[1]).startswith("```")


def test_choices_go_on_the_last_part_only():
    body = "word " * 1000 + "\n\nPick one:\n1. Yes\n2. No"
    parts = commands.agent_result("Claude", "budget", "Waiting for your answer.", body, waiting=True)
    assert len(parts) == 2
    assert "Next:" not in parts[0]
    assert parts[1].endswith("Next:\n• `Yes`\n• `No`")


def test_a_reply_past_the_ceiling_says_plainly_that_the_rest_was_not_sent():
    parts = commands.agent_result("Claude", "budget", "Done.", "word " * 30000)
    assert "so the rest was not sent" in parts[-1]
    assert "Open the Claude tab in AI Gator for all of it." in parts[-1]
    assert all("so the rest was not sent" not in p for p in parts[:-1])
    assert all(len(p) < 4000 for p in parts)


def test_a_result_that_echoes_a_command_cannot_form_one():
    out = commands.agent_result("Claude", "budget", "Done.", "@gator stop all")[0]
    assert not out.lower().startswith("@gator")
    assert commands.is_own_message(out)


def test_system_reply_has_the_prefix_a_blank_line_and_a_next_block():
    assert commands.system_reply("Online.", ["`@gator hi` to open a chat."]) == (
        "[\U0001F40A Gator] Online.\n\nNext:\n• `@gator hi` to open a chat."
    )


def test_replies_have_no_trailing_spaces_and_no_double_blank_lines():
    out = commands.agent_result("Claude", "budget", "Done.", "one  \n\n\n\ntwo \n")[0]
    assert out == "[\U0001F40A Gator - budget] Done.\none\n\ntwo"


def test_done_says_the_elapsed_time_only_past_a_minute():
    assert commands.done_headline(None) == "Done."
    assert commands.done_headline(60) == "Done."
    assert commands.done_headline(61) == "Done in 1 min."
    assert commands.done_headline(12 * 60 + 5) == "Done in 12 min."
    assert commands.done_headline(3600 + 5 * 60) == "Done in 1 h 5 min."
    assert commands.done_headline(7200) == "Done in 2 h."


def test_working_names_the_branch_and_offers_stop():
    assert commands.working("budget", "main", False) == (
        "[\U0001F40A Gator - budget] Working on it.\nBranch: main\n\nNext:\n• `stop` to stop it."
    )
    assert commands.working("budget", None, True, project="Budget") == (
        "[\U0001F40A Gator - budget - Budget] Working on it.\n\nNext:\n• `stop budget` to stop it."
    )


def test_still_working_has_no_options():
    assert commands.progress("budget", 130) == "[\U0001F40A Gator - budget] Still working, 2 min."


def test_an_unknown_name_lists_at_most_three_sessions():
    out = commands.unknown_mention("ghost", ["a", "b", "c", "d"])
    assert out == (
        "[\U0001F40A Gator] I don't know ghost. Start with `@gator` to send it to the agent.\n\n"
        "Next:\n• `a: your message`\n• `b: your message`\n• `c: your message`"
    )
    assert commands.unknown_mention("ghost", []) == (
        "[\U0001F40A Gator] I don't know ghost. Start with `@gator` to send it to the agent."
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
        ("[\U0001F40A Gator] x", True),
        ("[\U0001F40A Skipper - proj] x", True),
        ("[\U0001F40A Gator - proj - sess] x", True),
        ("  [\U0001F40A Gator] x", True),
        ("[:crocodile: Gator] x", True),
        ("[:crocodile: Gator - proj] x", True),
        ("  [:crocodile: Skipper] x", True),
        ("[Gator] x", True),
        ("[Gator - proj] \U0001F40A x", True),
        ("[Claude - proj] \U0001F40A x", True),
        ("[todo] \U0001F40A fix it", True),
        ("[todo] fix it", False),
        ("[" + "x" * 81 + "] \U0001F40A y", False),
        ("[a\nb] \U0001F40A y", False),
        ("fix it [\U0001F40A Gator]", False),
        ("fix it [:crocodile: Gator]", False),
        ("plain text", False),
    ],
)
def test_own_messages_are_matched_by_shape(text, own):
    assert commands.is_own_message(text) is own
