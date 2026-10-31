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
            {"displayName": "James Smith", "email": "James.Smith2@amd.com"},
            {"displayName": "Sherry Yang", "email": "sherry.yang@amd.com"},
            {"displayName": "No Mail"},
        ]
    )
    assert result["chats"][0]["participants"] == [
        {"name": "James Smith", "email": "james.smith2@amd.com"},
        {"name": "Sherry Yang", "email": "sherry.yang@amd.com"},
    ]


def test_chat_read_still_works_when_members_cannot_be_fetched():
    result = _read_chat(None)
    assert result["chats"][0]["participants"] == []
    assert result["chats"][0]["messages"]
