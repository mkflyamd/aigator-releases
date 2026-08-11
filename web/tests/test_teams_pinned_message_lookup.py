"""A pinned Teams message must be found even when it is older than the first
page of history, and a message_id with no chat_id must fail loudly.

Root causes fixed:
  1. _tool_read_teams_chats fetched only the newest 50 messages (limit=50) with
     NO backward pagination, so an older pinned message id never appeared and the
     read silently returned nothing. Fix: page backward via
     read_messages(..., backward_link=...) until the id is found.
  2. A message_id without a chat_id silently fell through to the "list all chats"
     branch (returning unrelated messages). Fix: reject it with a clear error.
"""
import importlib.util as _ilu
import types
from unittest.mock import patch


def _fake_rc(pages):
    """Build a fake read_chats module. `pages` is a list of (messages, backward)
    tuples returned in order across successive read_messages calls."""
    calls = {"n": 0}

    def read_messages(chat_id, skype_token, messaging_service, limit=20, backward_link=""):
        i = calls["n"]
        calls["n"] += 1
        return pages[i] if i < len(pages) else ([], "")

    mod = types.ModuleType("_teams_read_chats_fake")
    mod.get_auth = lambda: ("SKYPE_TOKEN", "https://msgsvc.example")
    mod.read_messages = read_messages
    mod.list_chats = lambda *a, **k: ([], "")
    return mod, calls


def _run(pages, chat_id="19:71880fe368394488b0ba77ef34ac1967@thread.v2",
         message_id="1785869566130"):
    from skills.teams import tools
    fake, calls = _fake_rc(pages)

    # The tool loads read_chats.py via importlib.util.spec_from_file_location +
    # module_from_spec + spec.loader.exec_module. Patch those to hand back our
    # fake module with a no-op loader so nothing touches the real Skype API.
    fake_loader = types.SimpleNamespace(exec_module=lambda m: None)
    fake_spec = types.SimpleNamespace(loader=fake_loader)
    with patch.object(_ilu, "spec_from_file_location", return_value=fake_spec), \
         patch.object(_ilu, "module_from_spec", return_value=fake):
        result = tools._tool_read_teams_chats(chat_id=chat_id, message_id=message_id)
    return result, calls


def test_pinned_message_found_on_later_page():
    target = "1785869566130"
    pages = [
        ([{"id": "9999999999999", "time": "2026-08-04T10:00:00Z",
           "from": "x", "content": "recent"}], "BACKLINK_1"),
        ([{"id": target, "time": "2026-08-04T08:39:00Z", "from": "Chaojun Hou",
           "content": "For ROCm Docker Image send to dl.rocm-dh-council@amd.com"}], "BACKLINK_2"),
    ]
    result, calls = _run(pages, message_id=target)
    msgs = result["chats"][0]["messages"]
    assert len(msgs) == 1, result
    assert "ROCm Docker Image" in msgs[0]["body"]
    assert calls["n"] == 2  # proves it paged backward


def test_message_not_found_reports_clearly():
    pages = [
        ([{"id": "1", "time": "2026-08-04T10:00:00Z", "from": "x", "content": "a"}], "B1"),
        ([{"id": "2", "time": "2026-08-04T09:00:00Z", "from": "x", "content": "b"}], ""),
    ]
    result, calls = _run(pages, message_id="1785869566130")
    assert result.get("message_not_found") is True
    assert "not found" in result["error"].lower()
    assert result["chats"][0]["messages"] == []


def test_found_on_first_page_does_not_paginate():
    target = "1785869566130"
    pages = [
        ([{"id": target, "time": "2026-08-04T08:39:00Z", "from": "x", "content": "hit"}], "B1"),
    ]
    result, calls = _run(pages, message_id=target)
    assert len(result["chats"][0]["messages"]) == 1
    assert calls["n"] == 1  # no needless backward paging


def test_message_id_without_chat_id_fails_loudly():
    """The core failure: a pin that lost its chat_id must not silently list all chats."""
    from skills.teams import tools
    # No importlib patching needed — the guard returns before any module load,
    # but auth runs first, so stub get_auth via the module loader path anyway.
    fake, _ = _fake_rc([])
    fake_loader = types.SimpleNamespace(exec_module=lambda m: None)
    fake_spec = types.SimpleNamespace(loader=fake_loader)
    with patch.object(_ilu, "spec_from_file_location", return_value=fake_spec), \
         patch.object(_ilu, "module_from_spec", return_value=fake):
        result = tools._tool_read_teams_chats(chat_id="", message_id="1785877076884")
    assert result.get("message_not_found") is True
    assert "chat_id" in result["error"].lower()
    assert result["chats"] == []
