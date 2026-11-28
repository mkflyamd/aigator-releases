"""The lane's host side: waking a saved session by its own id, never twice, never over a person."""

import time

import pytest

import agent_sessions
import agent_suspend
import agent_wake
import generic_agent
import pty_client
from remote import session_host
from remote.session_host import HostError, LocalPtyHost, Project
from routes import generic_agent_routes, terminal

PROJECT = Project(id="demo", name="Demo", repo_path="C:/repo/demo")
LABELS = {"remote_channel": "teams", "remote_short": "demo", "remote_created": "1.0"}
RECORD = {"agent": "claude", "project_id": "demo", "session_id": "vendor-1", "title": "t", "at": 1.0}
PROMPT_SCREEN = (
    "\x1b[1mThis session is 3 days old and 142.5k tokens.\x1b[0m\r\n"
    "> 1. Resume from summary (recommended)\r\n  2. Resume full session as-is\r\n  3. Don't ask me again\r\n"
)


class FakePty:
    def __init__(self, text="", last_user_input=0.0, done=False):
        self.text = text
        self.last_user_input = last_user_input
        self.done = done

    def read_from(self, since):
        return self.text, len(self.text)


class Calls:
    def __init__(self):
        self.typed = []
        self.waited = []
        self.resumed = []
        self.forgotten = []
        self.closed = []
        self.unpinned = []
        self.after = None
        self.before_guard = None

    def sleep(self):
        """Nothing runs for the lane now; what a resume brings up is whatever the test set up."""
        self.after = self.ptys.pop("pty-1", None) or FakePty()


@pytest.fixture
def calls(monkeypatch):
    c = Calls()
    ptys = {"pty-1": FakePty()}
    c.ptys = ptys
    c.viewer = False
    c.owner = {"session_id": "vendor-1"}
    c.record = dict(RECORD)
    c.live_labels = {}
    c.other_ptys = []
    c.found = True
    c.resume_result = {"pty_session_id": "pty-1"}

    async def wait_ready(pty_id, timeout):
        c.waited.append((pty_id, timeout))
        if pty_id in ptys and ptys[pty_id].done:
            raise agent_wake.WakeRefused("exited", "The agent exited before it was ready.")

    async def type_message(pty_id, text):
        c.typed.append((pty_id, text))

    async def resume(req, pty_id, woken_by, woken_preview="", labels=None, guard=None):
        if c.before_guard:
            c.before_guard()
        if guard:
            await guard()
        c.resumed.append((pty_id, woken_by, labels, req.resume_id))
        ptys[c.resume_result["pty_session_id"]] = c.after or FakePty()
        return c.resume_result

    monkeypatch.setattr(agent_wake, "_wait_ready", wait_ready)
    monkeypatch.setattr(agent_wake, "_type_message", type_message)
    monkeypatch.setattr(agent_wake, "_project_repo", lambda project_id: "C:/repo/demo")
    monkeypatch.setattr(generic_agent_routes, "resume_suspended", resume)
    monkeypatch.setattr(terminal, "session_owner", lambda sid, strict=False: c.owner)
    monkeypatch.setattr(terminal, "get_pty_session", lambda sid: ptys.get(sid))
    monkeypatch.setattr(terminal, "has_viewer", lambda sid, seconds=0: c.viewer)
    monkeypatch.setattr(terminal, "live_pty_labels", lambda strict=False: c.live_labels)
    monkeypatch.setattr(terminal, "pty_alive_strict", lambda sid: sid in ptys and not ptys[sid].done)
    monkeypatch.setattr(terminal, "is_pty_alive", lambda sid: sid in ptys and not ptys[sid].done)
    monkeypatch.setattr(terminal, "close_pty_session", lambda sid: c.closed.append(sid) or True)
    monkeypatch.setattr(generic_agent, "ptys_for_session", lambda agent, sid: c.other_ptys)
    monkeypatch.setattr(generic_agent, "unpin_session", lambda sid: c.unpinned.append(sid))
    monkeypatch.setattr(agent_sessions, "find_session", lambda repo, agent, sid: object() if c.found else None)
    monkeypatch.setattr(agent_suspend, "suspended_record", lambda pty_id: c.record)
    monkeypatch.setattr(agent_suspend, "forget", lambda pty_id: c.forgotten.append(pty_id))
    monkeypatch.setattr(session_host, "PROMPT_CHECK_SECONDS", 0.01)
    yield c
    agent_wake.release("vendor-1")


async def wake(calls, *args, **kwargs):
    calls.sleep()
    await LocalPtyHost().wake(*args, **kwargs)


async def test_a_message_is_typed_into_a_session_nobody_is_using(calls):
    await LocalPtyHost().deliver("pty-1", "hello")
    assert calls.typed == [("pty-1", "hello")]
    assert agent_wake.claim("vendor-1")


async def test_a_message_is_never_typed_while_someone_has_the_session_open_in_gator(calls):
    calls.viewer = True
    with pytest.raises(HostError, match="using"):
        await LocalPtyHost().deliver("pty-1", "hello")
    assert calls.typed == []
    assert agent_wake.claim("vendor-1")


async def test_a_message_is_never_typed_right_after_local_keystrokes(calls):
    calls.ptys["pty-1"].last_user_input = time.time() - 2
    with pytest.raises(HostError, match="using"):
        await LocalPtyHost().deliver("pty-1", "hello")
    assert calls.typed == []


async def test_a_message_is_typed_once_local_keystrokes_are_old_enough(calls):
    calls.ptys["pty-1"].last_user_input = time.time() - agent_wake.USER_TYPING_SECONDS - 5
    await LocalPtyHost().deliver("pty-1", "hello")
    assert calls.typed == [("pty-1", "hello")]


async def test_a_message_is_not_typed_when_proceed_says_no_after_the_wait(calls):
    with pytest.raises(session_host.Declined):
        await LocalPtyHost().deliver("pty-1", "hello", proceed=lambda: False)
    assert calls.typed == []
    assert agent_wake.claim("vendor-1")


async def test_proceed_is_asked_after_the_wait_for_the_session_not_before(calls, monkeypatch):
    state = {"on": True}

    async def turned_off_while_waiting(pty_id, timeout):
        state["on"] = False

    monkeypatch.setattr(agent_wake, "_wait_ready", turned_off_while_waiting)
    with pytest.raises(session_host.Declined):
        await LocalPtyHost().deliver("pty-1", "hello", proceed=lambda: state["on"])
    assert calls.typed == []


async def test_a_cancel_between_the_paste_and_the_enter_waits_for_the_enter(calls, monkeypatch):
    import asyncio

    steps = []
    pasted = asyncio.Event()

    async def paste_then_enter(pty_id, text):
        steps.append("paste")
        pasted.set()
        await asyncio.sleep(0.05)
        steps.append("enter")

    monkeypatch.setattr(agent_wake, "_type_message", paste_then_enter)
    task = asyncio.create_task(LocalPtyHost().deliver("pty-1", "hello"))
    await pasted.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert steps == ["paste", "enter"]
    assert agent_wake.claim("vendor-1")


async def test_a_message_waits_its_turn_when_the_session_is_being_woken_or_suspended(calls):
    assert agent_wake.claim("vendor-1")
    with pytest.raises(HostError, match="woken or suspended"):
        await LocalPtyHost().deliver("pty-1", "hello")
    assert calls.typed == []


async def test_sleeping_means_the_sweep_left_a_record(calls):
    assert await LocalPtyHost().sleeping("pty-1") is True
    calls.record = None
    assert await LocalPtyHost().sleeping("pty-1") is False


async def test_a_wake_resumes_the_saved_session_under_the_lane_id_with_its_labels(calls):
    await wake(calls, "pty-1", PROJECT, LABELS)
    assert calls.resumed == [("pty-1", session_host.WOKEN_BY, LABELS, "vendor-1")]
    assert calls.waited
    assert calls.forgotten == ["pty-1"]
    assert agent_wake.claim("vendor-1")


async def test_the_saved_record_is_kept_and_the_process_closed_again_when_it_did_not_stay_up(calls):
    calls.ptys["pty-1"].done = True
    with pytest.raises(HostError, match="exited before it was ready"):
        await wake(calls, "pty-1", PROJECT, LABELS)
    assert calls.forgotten == []
    assert calls.closed == ["pty-1"]
    assert calls.unpinned == ["pty-1"]
    assert agent_wake.claim("vendor-1")


async def test_a_wake_without_a_saved_record_fails_for_good(calls):
    calls.record = None
    with pytest.raises(HostError) as err:
        await wake(calls, "pty-1", PROJECT, LABELS)
    assert err.value.permanent
    assert calls.resumed == []


async def test_a_wake_whose_stored_session_is_gone_fails_for_good(calls):
    calls.found = False
    with pytest.raises(HostError) as err:
        await wake(calls, "pty-1", PROJECT, LABELS)
    assert err.value.permanent
    assert calls.resumed == []


async def test_a_wake_whose_project_is_gone_fails_for_good(calls, monkeypatch):
    monkeypatch.setattr(agent_wake, "_project_repo", lambda project_id: None)
    with pytest.raises(HostError) as err:
        await wake(calls, "pty-1", PROJECT, LABELS)
    assert err.value.permanent
    assert calls.resumed == []


async def test_a_session_live_in_another_terminal_is_never_resumed_a_second_time(calls):
    calls.live_labels = {"pty-7": {"agent": "claude", "session_id": "vendor-1"}}
    with pytest.raises(HostError, match="open in another terminal") as err:
        await wake(calls, "pty-1", PROJECT, LABELS)
    assert err.value.permanent
    assert calls.resumed == []
    assert agent_wake.claim("vendor-1")


async def test_a_session_linked_to_a_running_local_terminal_is_never_resumed_a_second_time(calls):
    calls.ptys["pty-7"] = FakePty()
    calls.other_ptys = ["pty-7"]
    with pytest.raises(HostError, match="open in another terminal"):
        await wake(calls, "pty-1", PROJECT, LABELS)
    assert calls.resumed == []


async def test_the_wake_guard_raises_the_open_elsewhere_type_so_the_runner_can_route(calls):
    calls.live_labels = {"pty-7": {"agent": "claude", "session_id": "vendor-1"}}
    with pytest.raises(session_host.OpenElsewhere):
        await wake(calls, "pty-1", PROJECT, LABELS)


async def test_the_holder_of_the_saved_session_is_named_before_any_wake(calls):
    calls.live_labels = {"pty-7": {"agent": "claude", "session_id": "vendor-1"}}
    assert await LocalPtyHost().open_elsewhere("pty-1", PROJECT, "vendor-1") == "pty-7"
    assert calls.resumed == []


async def test_a_local_terminal_linked_to_the_saved_session_is_named_as_its_holder(calls):
    calls.ptys["pty-7"] = FakePty()
    calls.other_ptys = ["pty-7"]
    assert await LocalPtyHost().open_elsewhere("pty-1", PROJECT, "vendor-1") == "pty-7"


async def test_a_session_nobody_else_holds_has_no_holder(calls):
    assert await LocalPtyHost().open_elsewhere("pty-1", PROJECT, "vendor-1") is None
    calls.ptys["pty-7"] = FakePty(done=True)
    calls.other_ptys = ["pty-7"]
    assert await LocalPtyHost().open_elsewhere("pty-1", PROJECT, "vendor-1") is None


async def test_the_lane_is_never_its_own_holder(calls):
    calls.live_labels = {"pty-1": {"agent": "claude", "session_id": "vendor-1"}}
    assert await LocalPtyHost().open_elsewhere("pty-1", PROJECT, "vendor-1") is None


async def test_a_lane_with_no_saved_session_has_no_holder(calls):
    calls.record = None
    assert await LocalPtyHost().open_elsewhere("pty-1", PROJECT, None) is None


async def test_the_lane_id_is_used_when_the_suspend_record_is_gone(calls):
    calls.record = None
    calls.live_labels = {"pty-7": {"agent": "claude", "session_id": "vendor-9"}}
    assert await LocalPtyHost().open_elsewhere("pty-1", PROJECT, "vendor-9") == "pty-7"


async def test_a_terminal_host_that_does_not_answer_is_an_error_never_nobody(calls, monkeypatch):
    def down(strict=False):
        raise pty_client.HostError("down")

    monkeypatch.setattr(terminal, "live_pty_labels", down)
    with pytest.raises(HostError, match="did not answer"):
        await LocalPtyHost().open_elsewhere("pty-1", PROJECT, "vendor-1")


async def test_a_finished_local_terminal_does_not_block_the_wake(calls):
    calls.ptys["pty-7"] = FakePty(done=True)
    calls.other_ptys = ["pty-7"]
    await wake(calls, "pty-1", PROJECT, LABELS)
    assert len(calls.resumed) == 1


async def test_a_resume_that_lands_in_a_different_terminal_is_refused(calls):
    calls.resume_result = {"pty_session_id": "pty-9"}
    with pytest.raises(HostError, match="open in another terminal"):
        await wake(calls, "pty-1", PROJECT, LABELS)


async def test_two_wakes_of_one_session_cannot_overlap(calls):
    assert agent_wake.claim("vendor-1")
    with pytest.raises(HostError, match="woken or suspended") as err:
        await wake(calls, "pty-1", PROJECT, LABELS)
    assert not err.value.permanent
    assert calls.resumed == []


async def test_a_failed_resume_is_reported_and_starts_nothing_else(calls, monkeypatch):
    async def broken(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(generic_agent_routes, "resume_suspended", broken)
    with pytest.raises(HostError, match="could not be woken"):
        await wake(calls, "pty-1", PROJECT, LABELS)
    assert calls.forgotten == []
    assert calls.closed == ["pty-1"]
    assert agent_wake.claim("vendor-1")


def test_the_resume_summary_question_is_recognised_through_terminal_escapes(calls):
    calls.ptys["pty-1"].text = PROMPT_SCREEN
    assert LocalPtyHost._resume_prompt_showing("pty-1") is True


def test_an_ordinary_screen_is_not_taken_for_the_resume_question(calls):
    calls.ptys["pty-1"].text = "Welcome back!\r\n> \r\n"
    assert LocalPtyHost._resume_prompt_showing("pty-1") is False


def test_a_missing_terminal_is_not_a_resume_question(calls):
    calls.ptys.clear()
    assert LocalPtyHost._resume_prompt_showing("pty-1") is False


async def test_the_resume_question_closes_the_terminal_again_keeps_the_save_and_says_why(calls):
    calls.ptys["pty-1"].text = PROMPT_SCREEN
    with pytest.raises(HostError) as err:
        await wake(calls, "pty-1", PROJECT, LABELS)
    assert str(err.value) == session_host.RESUME_PROMPT_MESSAGE
    assert "Code tab" in str(err.value)
    assert not err.value.permanent
    assert calls.closed == ["pty-1"]
    assert calls.unpinned == ["pty-1"]
    assert calls.forgotten == []


async def test_the_resume_question_is_never_answered_for_the_user(calls):
    calls.ptys["pty-1"].text = PROMPT_SCREEN
    with pytest.raises(HostError):
        await wake(calls, "pty-1", PROJECT, LABELS)
    assert calls.typed == []


async def test_a_session_that_never_takes_input_is_reported_after_the_wait(calls, monkeypatch):
    async def never_ready(pty_id, timeout):
        raise agent_wake.WakeRefused("not_ready", "The agent did not become ready.")

    monkeypatch.setattr(agent_wake, "_wait_ready", never_ready)
    monkeypatch.setattr(agent_wake, "WAKE_READY_SECONDS", 0.05)
    with pytest.raises(HostError, match="did not become ready"):
        await wake(calls, "pty-1", PROJECT, LABELS)


async def test_stopping_a_sleeping_lane_closes_no_process_and_drops_what_was_saved(calls):
    calls.ptys.clear()
    await LocalPtyHost().kill("pty-1")
    assert calls.closed == []
    assert calls.forgotten == ["pty-1"]
    assert calls.unpinned == ["pty-1"]


async def test_stopping_a_live_lane_closes_it_and_drops_its_record(calls, monkeypatch):
    monkeypatch.setattr(terminal, "session_owner", lambda sid: {"remote_pinned": "1", "remote_channel": "teams"})
    await LocalPtyHost("teams").kill("pty-1")
    assert calls.closed == ["pty-1"]
    assert calls.forgotten == ["pty-1"]


async def test_a_live_lane_that_will_not_close_is_reported_and_keeps_its_record(calls, monkeypatch):
    monkeypatch.setattr(terminal, "close_pty_session", lambda sid: False)
    monkeypatch.setattr(terminal, "session_owner", lambda sid: {"remote_pinned": "1", "remote_channel": "teams"})
    with pytest.raises(HostError, match="could not be closed"):
        await LocalPtyHost("teams").kill("pty-1")
    assert calls.forgotten == []


async def test_a_host_that_does_not_answer_refuses_the_wake_instead_of_guessing(calls, monkeypatch):
    def silent(sid):
        raise pty_client.HostError("down")

    monkeypatch.setattr(terminal, "pty_alive_strict", silent)
    with pytest.raises(HostError, match="did not answer") as err:
        await LocalPtyHost().wake("pty-1", PROJECT, LABELS)
    assert not err.value.permanent
    assert calls.resumed == []
    assert agent_wake.claim("vendor-1")


async def test_a_host_that_stops_answering_before_the_spawn_refuses_it(calls, monkeypatch):
    def silent(strict=False):
        raise pty_client.HostError("down")

    monkeypatch.setattr(terminal, "live_pty_labels", silent)
    with pytest.raises(HostError, match="did not answer"):
        await wake(calls, "pty-1", PROJECT, LABELS)
    assert calls.resumed == []


async def test_a_wake_of_a_lane_that_is_already_running_does_nothing(calls):
    await LocalPtyHost().wake("pty-1", PROJECT, LABELS)
    assert calls.resumed == []
    assert calls.waited == []
    assert calls.forgotten == []
    assert agent_wake.claim("vendor-1")


async def test_the_open_elsewhere_check_is_made_at_the_moment_of_the_spawn(calls):
    def user_opens_it_in_the_code_tab():
        calls.live_labels = {"pty-7": {"agent": "claude", "session_id": "vendor-1"}}

    calls.before_guard = user_opens_it_in_the_code_tab
    with pytest.raises(HostError, match="open in another terminal"):
        await wake(calls, "pty-1", PROJECT, LABELS)
    assert calls.resumed == []
    assert "pty-1" not in calls.ptys


async def test_a_wake_that_is_cancelled_before_the_spawn_starts_nothing(calls):
    with pytest.raises(HostError, match="called off"):
        await wake(calls, "pty-1", PROJECT, LABELS, "vendor-1", lambda: True)
    assert calls.resumed == []
    assert "pty-1" not in calls.ptys


async def test_a_wake_that_is_cancelled_while_waiting_closes_what_came_up_and_keeps_the_save(calls):
    flips = iter([False, True])
    with pytest.raises(HostError, match="called off"):
        await wake(calls, "pty-1", PROJECT, LABELS, "vendor-1", lambda: next(flips, True))
    assert len(calls.resumed) == 1
    assert calls.closed == ["pty-1"]
    assert calls.forgotten == []


async def test_a_lane_whose_record_is_gone_is_woken_from_what_the_lane_remembers(calls):
    calls.record = None
    await wake(calls, "pty-1", PROJECT, LABELS, "vendor-1")
    assert calls.resumed == [("pty-1", session_host.WOKEN_BY, LABELS, "vendor-1")]
    assert calls.ptys["pty-1"] is not None


PROSE_SCREEN = (
    "I asked Claude what it shows for a big session. It says: This session is 3 days old and 142.5k tokens,\r\n"
    "then offers to Resume from summary (recommended) or Resume full session as-is, and I picked the first.\r\n"
    "A pasted transcript follows: choose 1. Resume from summary or 2. Resume full session as-is.\r\n"
    "> \r\n"
)


def test_the_same_words_in_prose_in_the_last_screenful_are_not_the_resume_question(calls):
    calls.ptys["pty-1"].text = PROSE_SCREEN
    assert len(PROSE_SCREEN) < session_host.PROMPT_TAIL_CHARS
    assert LocalPtyHost._resume_prompt_showing("pty-1") is False


@pytest.mark.parametrize(
    "screen",
    [
        PROMPT_SCREEN,
        "\x1b[36m❯ 1. Resume from summary (recommended)\x1b[0m\r\n  2. Resume full session as-is\r\n",
        "│ 1. Resume from summary (recommended)  │\r\n│\r\n│ 2. Resume full session as-is  │\r\n",
    ],
)
def test_the_dialogs_numbered_choices_are_the_resume_question(calls, screen):
    calls.ptys["pty-1"].text = "earlier output\r\n" + screen
    assert LocalPtyHost._resume_prompt_showing("pty-1") is True


def test_the_resume_question_is_only_looked_for_at_the_end_of_the_screen(calls):
    calls.ptys["pty-1"].text = PROMPT_SCREEN + "x" * session_host.PROMPT_TAIL_CHARS
    assert LocalPtyHost._resume_prompt_showing("pty-1") is False


async def test_someone_opening_the_session_while_the_message_waits_to_be_typed_stops_it(calls, monkeypatch):
    monkeypatch.setattr(session_host, "TYPE_SETTLE_SECONDS", 0.01)
    answers = iter([False, True])
    monkeypatch.setattr(terminal, "has_viewer", lambda sid, seconds=0: next(answers, True))
    with pytest.raises(HostError, match="using"):
        await LocalPtyHost().deliver("pty-1", "hello")
    assert calls.typed == []
    assert agent_wake.claim("vendor-1")


def test_the_strict_alive_check_asks_the_host_and_lets_an_unreachable_host_raise(monkeypatch):
    monkeypatch.setattr(terminal, "_pty_sessions", {})
    monkeypatch.setattr(terminal, "_list_host_sessions", lambda strict=False: [{"id": "a", "done": False}, {"id": "b", "done": True}])
    assert terminal.pty_alive_strict("a") is True
    assert terminal.pty_alive_strict("b") is False
    assert terminal.pty_alive_strict("c") is False

    def silent(strict=False):
        if strict:
            raise pty_client.HostError("down")
        return []

    monkeypatch.setattr(terminal, "_list_host_sessions", silent)
    with pytest.raises(pty_client.HostError):
        terminal.pty_alive_strict("a")
