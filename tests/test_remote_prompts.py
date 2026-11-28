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
        "[\U0001F40A Gator - budget - Budget] Needs you: a question.\n"
        "Which color do you prefer?\n\n"
        "Next:\n• `1` Red: Choose red\n• `2` Blue: Choose blue"
    )


def test_a_bash_permission_shows_the_tool_and_command_and_offers_allow_once_and_deny():
    prompt = parsed(BASH_PERMISSION)
    assert prompt.kind == prompts.PERMISSION
    assert prompts.waiting_message("budget", "Budget", prompt) == (
        "[\U0001F40A Gator - budget - Budget] Needs you: permission.\n"
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
        assert isinstance(out, prompts.Refused)  # never typed as words and never picked as a menu row


def test_a_file_tool_shows_its_path_relative_to_the_project():
    prompt = parsed({"tool_name": "Edit", "cwd": CWD, "tool_input": {"file_path": CWD + "\\web\\app.py"}})
    assert prompts.waiting_message("a", "p", prompt).startswith(
        "[\U0001F40A Gator - a - p] Needs you: permission.\nTool: Edit\nPath: web/app.py\n"
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
            "[\U0001F40A Gator - a - p] Needs you: a draft to review.\nOpen AI Gator to review it and send."
        )
        assert isinstance(prompts.resolve(prompt, "allow"), prompts.Refused)
        assert isinstance(prompts.resolve(prompt, "1"), prompts.Refused)


@pytest.mark.parametrize("tool", ["Bash", "Edit", "Write"])
def test_enter_allows_only_the_tools_whose_dialog_was_seen_to_make_option_one_a_plain_yes(tool):
    prompt = parsed({"tool_name": tool, "tool_input": {"command": "ls", "file_path": CWD + "\\a.py"}, "cwd": CWD})
    assert prompt.kind == prompts.PERMISSION
    assert prompts.resolve(prompt, "allow").keys == (prompts.ENTER,)


@pytest.mark.parametrize(
    "payload",
    [
        {"tool_name": "ExitPlanMode", "tool_input": {"plan": "1. rewrite everything"}},
        {"tool_name": "mcp__outlook__list_emails", "tool_input": {}},
        {"tool_name": "mcp__x__postgres_query", "tool_input": {"sql": "drop table t"}},
        {"tool_name": "mcp__x__sendmail", "tool_input": {}},
        {"tool_name": "mcp__x__respond", "tool_input": {}},
        {"tool_name": "PowerShell", "tool_input": {"command": "Get-Date"}},
        {"tool_name": "WebFetch", "tool_input": {"url": "https://example.com"}},
        {"tool_name": "Read", "tool_input": {"file_path": "C:/elsewhere/secret.txt"}},
        {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "a.ipynb"}},
        {"tool_name": "SomethingNew", "tool_input": {}},
    ],
)
def test_any_other_tool_is_app_only_so_a_chat_allow_cannot_pick_an_unseen_option(payload):
    prompt = parsed(payload)
    assert prompt.kind in (prompts.PERMISSION_APP, prompts.DRAFT) and not prompt.answerable
    assert isinstance(prompts.resolve(prompt, "allow"), prompts.Refused)
    assert isinstance(prompts.resolve(prompt, "deny"), prompts.Refused)
    assert isinstance(prompts.resolve(prompt, "1"), prompts.Refused)
    message = prompts.waiting_message("a", "p", prompt)
    assert "`allow`" not in message and "`deny`" not in message


def test_an_app_only_permission_still_shows_what_it_is_and_points_to_the_app():
    prompt = parsed({"tool_name": "WebFetch", "tool_input": {"url": "https://example.com/docs"}})
    assert prompts.waiting_message("a", "p", prompt) == (
        "[\U0001F40A Gator - a - p] Needs you: permission.\n"
        "Tool: WebFetch\nURL: https://example.com/docs\n\n"
        "Next:\n• Open AI Gator to review and answer this permission."
    )


@pytest.mark.parametrize("payload", [{"tool_name": "Bash", "tool_input": {}}, {"tool_name": "Edit", "tool_input": {}}])
def test_a_permission_that_shows_nothing_to_approve_is_app_only(payload):
    assert parsed(payload).kind == prompts.PERMISSION_APP


def test_a_command_with_runs_of_spaces_is_not_allowed_from_chat_because_the_shown_text_differs():
    prompt = parsed({"tool_name": "Bash", "tool_input": {"command": 'rm "a  b"'}})
    assert prompt.command == 'rm "a b"' and prompt.cut
    assert isinstance(prompts.resolve(prompt, "allow"), prompts.Refused)


def test_a_command_whose_secret_was_redacted_is_not_allowed_from_chat():
    prompt = parsed(
        {"tool_name": "Bash", "tool_input": {"command": "curl -H aigator-fake-api-key x"}},
        redact=lambda text: text.replace("aigator-fake-api-key", "[REDACTED]"),
    )
    assert prompt.cut
    assert isinstance(prompts.resolve(prompt, "allow"), prompts.Refused)


def test_an_unchanged_command_is_not_cut_even_with_surrounding_whitespace():
    assert not parsed({"tool_name": "Bash", "tool_input": {"command": "  ls -la\n"}}).cut




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
    assert out == prompts.Refused("pick 1 or 2, or answer it in AI Gator.")
    assert prompts.resolve(parsed(ASK_USER_QUESTION), "0") == out


@pytest.mark.parametrize("reply", ["green, please", "hi\x1b[B\x03there", "x" * 600])
def test_free_text_is_not_typed_into_a_question_because_its_other_row_was_not_seen_live(reply):
    out = prompts.resolve(parsed(ASK_USER_QUESTION), reply)
    assert out == prompts.Refused("pick 1 or 2, or answer it in AI Gator.")




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
    assert out.startswith("[\U0001F40A Gator - budget - Budget] Not sent: this session is waiting on a permission.\nTool: Bash\n")
    assert out.endswith("Next:\n• `allow` to allow once.\n• `deny` to deny.")


def test_every_message_carries_the_session_name_and_the_shared_prefix():
    for prompt in (parsed(ASK_USER_QUESTION), parsed(BASH_PERMISSION), parsed({"tool_name": "mcp__a__send_x"})):
        text = prompts.waiting_message("budget", "Budget", prompt)
        assert text.startswith(commands.agent_prefix("budget", "Budget", several=True))
        assert text.count(commands.CROC) == 1
        assert "!" not in text and "**" not in text


def test_answer_word_is_what_list_suggests():
    assert prompts.answer_word(parsed(BASH_PERMISSION)) == "allow"
    assert prompts.answer_word(parsed(ASK_USER_QUESTION)) == "a number"
    assert prompts.answer_word(None) == "your answer"


DIALOG = "Doyouwanttoproceed?\n❯1.Yes\n2.Yes,andalwaysallow\n3.No\n\nEsctocancel"


@pytest.mark.parametrize(
    "tail, showing",
    [
        ("noise\n" + DIALOG + "·Tabtoamend", True),
        ("Do you want to proceed?\n ❯ 1. Yes\n 3. No\n Esc to cancel · ctrl+e to explain", True),
        (DIALOG + "·Tabtoamend\n✢Marinating…", False),
        (DIALOG + "·Tabtoamend\n● Interrupted · What should Claude do instead?", False),
        (DIALOG + "\n❯", False),
        ("Doyouwanttoproceed?\n❯1.Yes\n3.No", False),
        ("Doyouwanttoproceed?\n❯1.Yes\n3.No\nEsctocancel\nDoyouwanttocreate?\n2.No", False),
        ("Doyouwanttoproceed?\nEsctocancel", False),
        ("", False),
    ],
)
def test_the_permission_dialog_must_be_the_last_thing_on_screen(tail, showing):
    assert prompts.permission_dialog_showing(tail) is showing
