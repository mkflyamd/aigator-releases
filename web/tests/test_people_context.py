"""A bare name resolves to the person in the chat or thread already read, not to a directory guess."""

import asyncio
from types import SimpleNamespace

import people_context
from agent_loop import _make_tool_runner

JAMES_IN_CHAT = {"name": "James Smith", "email": "James.Smith2@example.com"}
OTHER_JAMES = {"name": "James Smith", "email": "james.smith@example.com"}
DIRECTORY = {"total": 2, "people": [OTHER_JAMES, {"name": "James Smithers", "email": "jsmithers@example.com"}]}


def test_collect_finds_participants_at_any_depth_and_dedupes():
    known = {}
    people_context.collect({"chats": [{"participants": [JAMES_IN_CHAT, {"name": "x", "email": ""}]}]}, known)
    people_context.collect({"participants": [JAMES_IN_CHAT]}, known)
    assert list(known) == ["james.smith2@example.com"]


def test_one_match_in_context_wins_and_says_so():
    known = {}
    people_context.collect({"participants": [JAMES_IN_CHAT, {"name": "Sherry Yang", "email": "sherry.yang@example.com"}]}, known)
    out = people_context.apply("James Smith", DIRECTORY, known)
    assert out["people"][0]["email"] == "James.Smith2@example.com".lower()
    assert out["people"][0]["in_context"] is True
    assert out["resolved_from_context"] == "james.smith2@example.com"
    assert "do not ask" in out["hint"]
    assert "James" not in out["hint"]
    assert [p["email"] for p in out["people"][1:]] == ["james.smith@example.com", "jsmithers@example.com"]


def test_two_matches_in_context_are_not_resolved():
    known = {}
    people_context.collect({"participants": [JAMES_IN_CHAT, {"name": "James Smith", "email": "other@example.com"}]}, known)
    out = people_context.apply("James", DIRECTORY, known)
    assert "resolved_from_context" not in out
    assert all(p["in_context"] for p in out["people"][:2])


def test_nothing_in_context_leaves_the_result_alone():
    assert people_context.apply("James", DIRECTORY, {}) is DIRECTORY
    known = {}
    people_context.collect({"participants": [{"name": "Sherry Yang", "email": "sherry.yang@example.com"}]}, known)
    assert people_context.apply("James", DIRECTORY, known) is DIRECTORY


def test_search_waits_for_the_chat_read_in_the_same_batch():
    async def fake_execute(name, inputs, **kw):
        if name == "read_teams_chats":
            await asyncio.sleep(0.05)
            return {"chats": [{"participants": [JAMES_IN_CHAT]}]}
        return DIRECTORY

    run_tool_block, run_all, sentinel = _make_tool_runner(fake_execute, set(), {}, lambda n, r: None, "__slack_safe__")
    calls = [
        SimpleNamespace(name="search_people", inputs={"query": "James Smith"}, id="c1"),
        SimpleNamespace(name="read_teams_chats", inputs={}, id="c2"),
    ]

    async def go():
        q = asyncio.Queue()
        return await run_all(calls, q)

    loop = asyncio.new_event_loop()
    try:
        results = loop.run_until_complete(go())
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())
    assert results[0]["resolved_from_context"] == "james.smith2@example.com"
    assert "chats" in results[1]


def test_a_name_matches_whole_words_not_fragments():
    ann = {"name": "Ann Park", "email": "ann.park@example.com"}
    joanne = {"name": "Joanne Lee", "email": "joanne.lee@example.com"}
    known = {}
    people_context.collect({"participants": [joanne]}, known)
    assert people_context.apply("Ann", DIRECTORY, known) is DIRECTORY
    people_context.collect({"participants": [ann]}, known)
    out = people_context.apply("Ann", DIRECTORY, known)
    assert out["resolved_from_context"] == "ann.park@example.com"
    assert people_context.apply("park", DIRECTORY, known)["resolved_from_context"] == "ann.park@example.com"
    assert people_context.apply("ann.park@example.com", DIRECTORY, known)["resolved_from_context"] == "ann.park@example.com"


def test_a_mail_header_name_is_not_resolved_unless_the_directory_returns_that_email():
    attacker = {"name": "Alice Lee", "email": "attacker@example.net", "unverified": True}
    real = {"name": "Alice Lee", "email": "alice.lee@example.com"}
    directory = {"total": 1, "people": [real]}
    known = {}
    people_context.collect({"participants": [attacker]}, known)
    assert people_context.apply("Alice", directory, known) is directory

    colleague = {"name": "Alice Lee", "email": "alice.lee@example.com", "unverified": True}
    known = {}
    people_context.collect({"participants": [colleague]}, known)
    out = people_context.apply("Alice", directory, known)
    assert out["resolved_from_context"] == "alice.lee@example.com"


def test_mail_participants_are_marked_unverified():
    from skills.email.tools import _mail_participants

    people = _mail_participants([{"from": {"emailAddress": {"name": "Alice Lee", "address": "A@Example.net"}}}])
    assert people == [{"name": "Alice Lee", "email": "a@example.net", "unverified": True}]
