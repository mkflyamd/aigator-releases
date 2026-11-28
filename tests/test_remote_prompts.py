"""What an agent is asking, as chat copy, and the exact keys each reply types. Payloads are the shapes
Claude Code's PermissionRequest hook wrote when captured live (ids and paths made up)."""

import json

import pytest

from remote import commands, prompts

CWD = "C:\\Users\\someone\\code\\repo"

# A real AskUserQuestion capture: one single-select question, the same shape Claude Code sends.
ASK_USER_QUESTION = json.loads(
    '{"session_id":"00000000-0000-4000-8000-000000000001",'
    '"transcript_path":"C:\\\\Users\\\\someone\\\\.claude\\\\projects\\\\repo\\\\00000000-0000-4000-8000-000000000001.jsonl",'
    '"cwd":"C:\\\\Users\\\\someone\\\\code\\\\repo","prompt_id":"00000000-0000-4000-8000-000000000002",'
    '"permission_mode":"auto","effort":{"level":"high"},"hook_event_name":"PermissionRequest",'
    '"tool_name":"AskUserQuestion","tool_input":{"questions":[{"question":"Which color do you prefer?",'
    '"header":"Color","options":[{"label":"Red","description":"Choose red"},'
    '{"label":"Blue","description":"Choose blue"}],"multiSelect":false}]}}'
)

# A real Bash permission capture, including the "always allow" suggestion that must never reach chat.
BASH_PERMISSION = {
    "session_id": "00000000-0000-4000-8000-000000000001",
    "cwd": CWD,
    "permission_mode": "default",
    "hook_event_name": "PermissionRequest",
    "tool_name": "Bash",
    "tool_input": {"command": "echo hi > out.txt", "description": "Write hi to a file"},
    "permission_suggestions": [{"type": "addRules", "rules": [{"toolName": "Bash", "ruleContent": "echo hi:*"}]}],
}


def parsed(payload, at=1000.0, redact=str):
    prompt = prompts.parse(payload, at, redact)
    assert prompt is not None
    return prompt


def ask(*questions):
    return {"tool_name": "AskUserQuestion", "tool_input": {"questions": list(questions)}}


def question(text="Which?", labels=("A", "B"), multi=False, descriptions=None):
    options = [{"label": lab, "description": (descriptions or {}).get(lab, "")} for lab in labels]
    return {"question": text, "header": "H", "options": options, "multiSelect": multi}


def test_the_captured_ask_user_question_is_a_numbered_question():
    prompt = parsed(ASK_USER_QUESTION)
    assert prompt.kind == prompts.QUESTION and prompt.answerable
    assert prompt.question == "Which color do you prefer?"
    assert [(c.label, c.description) for c in prompt.choices] == [("Red", "Choose red"), ("Blue", "Choose blue")]
    assert prompts.waiting_message("budget", "Budget", prompt) == (
        "[Gator - budget - Budget] Needs you: a question.\n"
        "Which color do you prefer?\n\n"
        "Next:\n• `1` Red: Choose red\n• `2` Blue: Choose blue"
    )


def test_a_bash_permission_shows_the_tool_and_command_and_offers_allow_once_and_deny():
    prompt = parsed(BASH_PERMISSION)
    assert prompt.kind == prompts.PERMISSION
    assert prompts.waiting_message("budget", "Budget", prompt) == (
        "[Gator - budget - Budget] Needs you: permission.\n"
        "Tool: Bash\nCommand: echo hi > out.txt\n\n"
        "Next:\n• `allow` to allow once.\n• `deny` to deny."
    )


@pytest.mark.parametrize("payload", [ASK_USER_QUESTION, BASH_PERMISSION])
def test_always_allow_and_dont_ask_again_never_appear_and_cannot_be_typed(payload):
    prompt = parsed(payload)
    shown = prompts.waiting_message("budget", "Budget", prompt).lower()
    assert "always" not in shown and "don't ask" not in shown and "addrules" not in shown
    for reply in ("always allow", "allow always", "don't ask again", "yes, and don't ask again", "allow all"):
        out = prompts.resolve(prompt, reply)
        if prompt.kind == prompts.PERMISSION:
            assert isinstance(out, prompts.Refused)
        else:
            assert out.keys[-2] == reply  # typed as the user's own words, never picked as a menu row


def test_a_file_tool_shows_its_path_relative_to_the_project():
    prompt = parsed({"tool_name": "Edit", "cwd": CWD, "tool_input": {"file_path": CWD + "\\web\\app.py"}})
    assert prompts.waiting_message("a", "p", prompt).startswith(
        "[Gator - a - p] Needs you: permission.\nTool: Edit\nPath: web/app.py\n"
    )


def test_a_fetch_shows_its_url():
    prompt = parsed({"tool_name": "WebFetch", "tool_input": {"url": "https://example.com/docs"}})
    assert "URL: https://example.com/docs" in prompts.waiting_message("a", "p", prompt)


def test_a_long_command_is_cut_with_an_ellipsis_and_only_deny_is_offered():
    prompt = parsed({"tool_name": "Bash", "tool_input": {"command": "echo " + "x" * 400}})
    message = prompts.waiting_message("a", "p", prompt)
    assert prompt.cut and prompt.command.endswith("…") and len(prompt.command) <= prompts.COMMAND_MAX_CHARS + 1
    assert "• `deny` to deny." in message and "`allow`" not in message
    assert prompts.OPEN_APP_COMMAND in message
    assert isinstance(prompts.resolve(prompt, "allow"), prompts.Refused)
    assert prompts.resolve(prompt, "deny").keys == (prompts.ESCAPE,)


def test_a_command_of_exactly_the_cap_is_not_cut():
    prompt = parsed({"tool_name": "Bash", "tool_input": {"command": "x" * prompts.COMMAND_MAX_CHARS}})
    assert not prompt.cut


def test_a_multi_line_command_cannot_be_allowed_from_chat():
    prompt = parsed({"tool_name": "Bash", "tool_input": {"command": "echo a\nrm -rf /tmp/x"}})
    assert prompt.cut
    assert isinstance(prompts.resolve(prompt, "allow"), prompts.Refused)


def test_the_command_is_redacted_before_it_is_shown():
    prompt = parsed(
        {"tool_name": "Bash", "tool_input": {"command": "curl -H 'Authorization: aigator-fake-api-key' x"}},
        redact=lambda text: text.replace("aigator-fake-api-key", "[REDACTED]"),
    )
    assert "aigator-fake-api-key" not in prompts.waiting_message("a", "p", prompt)
    assert "[REDACTED]" in prompt.command


def test_a_draft_tool_is_not_answerable_and_points_to_the_app():
    for tool in (
        "mcp__outlook__send_email",
        "mcp__slack__post_message",
        "mcp__teams__replyToMessage",
        "mcp__x__create_draft",
    ):
        prompt = parsed({"tool_name": tool, "tool_input": {"body": "hello"}})
        assert prompt.kind == prompts.DRAFT and not prompt.answerable
        assert prompts.waiting_message("a", "p", prompt) == (
            "[Gator - a - p] Needs you: a draft to review.\nOpen AI Gator to review it and send."
        )
        assert isinstance(prompts.resolve(prompt, "allow"), prompts.Refused)
        assert isinstance(prompts.resolve(prompt, "1"), prompts.Refused)


def test_a_tool_that_only_reads_is_not_mistaken_for_a_draft():
    assert parsed({"tool_name": "mcp__outlook__list_emails", "tool_input": {}}).kind == prompts.PERMISSION
    assert parsed({"tool_name": "mcp__x__postgres_query", "tool_input": {}}).kind == prompts.PERMISSION


def test_a_multi_select_question_is_refused_to_the_app():
    prompt = parsed(ask(question(multi=True)))
    assert prompt.kind == prompts.APP_ONLY
    message = prompts.waiting_message("a", "p", prompt)
    assert "it takes several answers" in message and prompts.OPEN_APP_QUESTION in message
    assert isinstance(prompts.resolve(prompt, "1"), prompts.Refused)


def test_a_multi_question_menu_is_refused_to_the_app():
    prompt = parsed(ask(question("One?"), question("Two?")))
    assert prompt.kind == prompts.APP_ONLY
    assert "it has several questions" in prompts.waiting_message("a", "p", prompt)
    assert isinstance(prompts.resolve(prompt, "1"), prompts.Refused)


@pytest.mark.parametrize("bad", [{}, {"questions": []}, {"questions": ["x"]}, {"questions": [question(labels=())]}])
def test_an_unreadable_menu_is_refused_to_the_app(bad):
    assert parsed({"tool_name": "AskUserQuestion", "tool_input": bad}).kind == prompts.APP_ONLY


def test_more_options_than_one_digit_is_refused_to_the_app():
    assert parsed(ask(question(labels=tuple("ABCDEFGHIJ")))).kind == prompts.APP_ONLY


def test_a_payload_without_a_tool_is_nothing():
    assert prompts.parse({"tool_input": {}}, 1.0) is None
    assert prompts.parse({"tool_name": 3}, 1.0) is None


def test_an_option_description_is_cut_and_one_that_repeats_the_label_is_dropped():
    prompt = parsed(ask(question(labels=("A", "B"), descriptions={"A": "d" * 200, "B": "b"})))
    assert prompt.choices[0].description.endswith("…") and len(prompt.choices[0].description) <= 81
    assert prompt.choices[1].description == ""


def test_the_id_changes_when_the_same_prompt_is_shown_again_and_is_stable_for_one_prompt():
    assert parsed(BASH_PERMISSION, 1.0).id == parsed(BASH_PERMISSION, 1.0).id
    assert parsed(BASH_PERMISSION, 1.0).id != parsed(BASH_PERMISSION, 2.0).id
    other = dict(BASH_PERMISSION, tool_input={"command": "ls"})
    assert parsed(BASH_PERMISSION, 1.0).id != parsed(other, 1.0).id


# ---------------------------------------------------------------- replies to keystrokes


def test_a_number_is_down_arrows_then_enter():
    prompt = parsed(ASK_USER_QUESTION)
    assert prompts.resolve(prompt, "1") == prompts.Answer((prompts.ENTER,), "Got it: Red.")
    assert prompts.resolve(prompt, "2") == prompts.Answer((prompts.DOWN, prompts.ENTER), "Got it: Blue.")
    assert prompts.resolve(prompt, " 2. ").keys == (prompts.DOWN, prompts.ENTER)


def test_the_third_option_of_three_is_two_downs():
    prompt = parsed(ask(question(labels=("A", "B", "C"))))
    assert prompts.resolve(prompt, "3").keys == (prompts.DOWN, prompts.DOWN, prompts.ENTER)


def test_a_label_typed_exactly_picks_that_option():
    assert prompts.resolve(parsed(ASK_USER_QUESTION), "blue").keys == (prompts.DOWN, prompts.ENTER)


def test_a_number_out_of_range_types_nothing_and_says_what_to_pick():
    out = prompts.resolve(parsed(ASK_USER_QUESTION), "3")
    assert out == prompts.Refused("pick 1 or 2, or type your answer.")
    assert prompts.resolve(parsed(ASK_USER_QUESTION), "0") == out


def test_other_text_is_typed_into_the_type_something_row():
    out = prompts.resolve(parsed(ASK_USER_QUESTION), "green, please")
    assert out.keys == (prompts.DOWN, prompts.DOWN, "green, please", prompts.ENTER)
    assert out.done == "Got it: green, please."


def test_typed_text_carries_no_control_characters():
    out = prompts.resolve(parsed(ASK_USER_QUESTION), "hi\x1b[B\x03there")
    assert out.keys[2] == "hi[Bthere"


def test_typed_text_is_capped():
    assert isinstance(prompts.resolve(parsed(ASK_USER_QUESTION), "x" * 600), prompts.Refused)


def test_allow_is_enter_and_deny_is_escape_and_ends_the_turn():
    prompt = parsed(BASH_PERMISSION)
    assert prompts.resolve(prompt, "allow") == prompts.Answer((prompts.ENTER,), "Allowed once.")
    assert prompts.resolve(prompt, "Allow.") == prompts.Answer((prompts.ENTER,), "Allowed once.")
    assert prompts.resolve(prompt, "deny") == prompts.Answer((prompts.ESCAPE,), "Denied.", ends_turn=True)


@pytest.mark.parametrize("reply", ["2", "yes", "ok go ahead", "allow it and always", ""])
def test_anything_else_at_a_permission_is_refused_not_typed(reply):
    assert isinstance(prompts.resolve(parsed(BASH_PERMISSION), reply), prompts.Refused)


def test_a_refused_message_names_what_is_being_asked_and_offers_the_options():
    prompt = parsed(BASH_PERMISSION)
    out = prompts.waiting_message("budget", "Budget", prompt, refused="this session is waiting on a permission.")
    assert out.startswith("[Gator - budget - Budget] Not sent: this session is waiting on a permission.\nTool: Bash\n")
    assert out.endswith("Next:\n• `allow` to allow once.\n• `deny` to deny.")


def test_every_message_carries_the_session_name_and_the_shared_prefix():
    for prompt in (parsed(ASK_USER_QUESTION), parsed(BASH_PERMISSION), parsed({"tool_name": "mcp__a__send_x"})):
        text = prompts.waiting_message("budget", "Budget", prompt)
        assert text.startswith(commands.SYSTEM_PREFIX + " - budget - Budget]")
        assert text.count(commands.SYSTEM_PREFIX) == 1
        assert "!" not in text and "**" not in text


def test_answer_word_is_what_list_suggests():
    assert prompts.answer_word(parsed(BASH_PERMISSION)) == "allow"
    assert prompts.answer_word(parsed(ASK_USER_QUESTION)) == "your answer"
    assert prompts.answer_word(None) == "your answer"
