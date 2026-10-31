"""Slot options show who is free in a fixed-length line, and a read Teams chat says who is in it."""

import importlib.util as _ilu
import types
from unittest.mock import patch

from skills.calendar.tools import _availability_strip


def _slot(organizer, *attendees):
    return {
        "organizerAvailability": organizer,
        "attendeeAvailability": [
            {"attendee": {"emailAddress": {"name": n, "address": f"{n}@x.com"}}, "availability": s}
            for n, s in attendees
        ],
    }


def test_everyone_free_is_one_short_line():
    assert _availability_strip(_slot("free", ("Sherry Yang", "free"), ("James Smith", "free"))) == "\U0001f7e2 All 3 free"


def test_only_people_who_are_not_free_are_named():
    strip = _availability_strip(_slot("free", ("Sherry Yang", "free"), ("Smith, James", "tentative")))
    assert strip == "\U0001f7e2 2 of 3 free · \U0001f7e1 James tentative"


def test_strip_stays_short_with_many_attendees():
    busy = [(f"Person{i} Last", "busy") for i in range(8)]
    strip = _availability_strip(_slot("free", *busy, ("Free Guy", "free")))
    assert strip.startswith("\U0001f7e2 2 of 10 free")
    assert strip.count("busy") == 2
    assert strip.endswith("+6 more")


def test_no_availability_data_gives_no_strip():
    assert _availability_strip({}) == ""


def _read_chat(graph_members):
    import skills._m365.helpers  # noqa: F401  imported before the loader is patched
    from skills.teams import tools

    mod = types.ModuleType("_teams_read_chats_fake")
    mod.get_auth = lambda: ("SKYPE_TOKEN", "https://msgsvc.example")
    mod.read_messages = lambda *a, **k: ([{"id": "1", "time": "2026-10-30T10:00:00Z", "from": "James", "content": "hi"}], "")
    mod.list_chats = lambda *a, **k: ([], "")
    fake_spec = types.SimpleNamespace(loader=types.SimpleNamespace(exec_module=lambda m: None))

    class _Gc:
        def get(self, path, params=None):
            if graph_members is None:
                raise RuntimeError("no access")
            assert path == "/chats/19:abc@thread.v2/members"
            return {"value": graph_members}

    with (
        patch.object(_ilu, "spec_from_file_location", return_value=fake_spec),
        patch.object(_ilu, "module_from_spec", return_value=mod),
        patch("skills._m365.helpers.make_teams_gc", return_value=_Gc()),
    ):
        return tools._tool_read_teams_chats(chat_id="19:abc@thread.v2")


def test_chat_read_lists_participants_with_emails():
    result = _read_chat(
        [
            {"displayName": "James Smith", "email": "James.Smith2@example.com"},
            {"displayName": "Sherry Yang", "email": "sherry.yang@example.com"},
            {"displayName": "No Mail"},
        ]
    )
    assert result["chats"][0]["participants"] == [
        {"name": "James Smith", "email": "james.smith2@example.com"},
        {"name": "Sherry Yang", "email": "sherry.yang@example.com"},
    ]


def test_chat_read_still_works_when_members_cannot_be_fetched():
    result = _read_chat(None)
    assert result["chats"][0]["participants"] == []
    assert result["chats"][0]["messages"]


def test_members_not_readable_falls_back_to_sender_ids_looked_up_in_the_directory():
    import skills._m365.helpers  # noqa: F401
    from skills.teams import tools

    guid = "11111111-2222-3333-4444-555555555555"

    class _Gc:
        def get(self, path, params=None):
            if path.endswith("/members"):
                raise RuntimeError("403")
            assert path == f"/users/{guid}"
            return {"displayName": "James Smith", "mail": "James.Smith2@example.com"}

    with patch("skills._m365.helpers.make_teams_gc", return_value=_Gc()):
        people = tools._participants(
            "19:abc@thread.v2",
            messages=[{"from_mri": f"8:orgid:{guid}"}, {"from_mri": f"8:orgid:{guid}"}, {"from_mri": "8:live:x"}],
            thread_members=[{"id": f"8:orgid:{guid}"}],
        )
    assert people == [{"name": "James Smith", "email": "james.smith2@example.com"}]


def test_single_chat_read_includes_members_who_have_not_posted():
    import skills._m365.helpers  # noqa: F401
    from skills.teams import tools

    sender, quiet = "11111111-2222-3333-4444-555555555555", "99999999-8888-7777-6666-555555555555"
    mod = types.ModuleType("_teams_read_chats_fake")
    mod.get_auth = lambda: ("SKYPE_TOKEN", "https://msgsvc.example")
    mod.read_messages = lambda *a, **k: (
        [{"id": "1", "time": "2026-10-30T10:00:00Z", "from": "Sherry", "from_mri": f"8:orgid:{sender}", "content": "hi"}],
        "",
    )
    mod.list_chats = lambda *a, **k: (
        [{"id": "19:abc@thread.v2", "thread_members": [{"id": f"8:orgid:{sender}"}, {"id": f"8:orgid:{quiet}"}]}],
        "",
    )
    fake_spec = types.SimpleNamespace(loader=types.SimpleNamespace(exec_module=lambda m: None))
    users = {
        sender: {"displayName": "Sherry Yang", "mail": "sherry.yang@example.com"},
        quiet: {"displayName": "James Smith", "mail": "james.smith2@example.com"},
    }

    class _Gc:
        def get(self, path, params=None):
            if path.endswith("/members"):
                raise RuntimeError("403")
            return users[path.rsplit("/", 1)[1]]

    with (
        patch.object(_ilu, "spec_from_file_location", return_value=fake_spec),
        patch.object(_ilu, "module_from_spec", return_value=mod),
        patch("skills._m365.helpers.make_teams_gc", return_value=_Gc()),
    ):
        result = tools._tool_read_teams_chats(chat_id="19:abc@thread.v2")
    assert [p["email"] for p in result["chats"][0]["participants"]] == [
        "sherry.yang@example.com",
        "james.smith2@example.com",
    ]
