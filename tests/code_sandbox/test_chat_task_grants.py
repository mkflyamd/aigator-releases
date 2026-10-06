import inspect

from routes import chat as chat_routes
from routes.chat import ChatRequest
from sandbox import task_grants


def test_flag_defaults_to_false():
    assert ChatRequest(message="hi").sandbox_followup is False
    assert ChatRequest(message="hi", sandbox_followup=True).sandbox_followup is True


def test_new_user_message_ends_the_tabs_grants_only():
    task_grants._reset()
    task_grants.add("tab-a", [], ["/proj"], [])
    task_grants.add("tab-b", [], ["/proj"], [])
    chat_routes._end_task_grants_for_new_message(ChatRequest(message="next", context_id="tab-a"))
    assert not task_grants.covers("tab-a", [], ["/proj"], [])
    assert task_grants.covers("tab-b", [], ["/proj"], [])
    task_grants._reset()


def test_automatic_followup_keeps_the_grants():
    task_grants._reset()
    task_grants.add("tab-a", [], ["/proj"], [])
    chat_routes._end_task_grants_for_new_message(
        ChatRequest(message="I approved ...", context_id="tab-a", sandbox_followup=True))
    assert task_grants.covers("tab-a", [], ["/proj"], [])
    task_grants._reset()


def test_empty_context_id_means_default_tab():
    task_grants._reset()
    task_grants.add("default", [], ["/proj"], [])
    chat_routes._end_task_grants_for_new_message(ChatRequest(message="x", context_id=""))
    assert not task_grants.covers("default", [], ["/proj"], [])
    task_grants._reset()


def test_chat_ends_grants_before_any_early_return():
    src = inspect.getsource(chat_routes.chat)
    call = src.index("_end_task_grants_for_new_message(req)")
    assert call < src.index("return "), "must run before the first return in chat()"
