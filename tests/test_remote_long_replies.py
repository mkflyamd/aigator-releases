"""A reply in several parts goes out from a task of its own: the polling loop does not wait for it, a part that
fails is tried again, and one that still fails is said so."""

import asyncio

import pytest

from remote import commands, runner
from remote.channel import PostUncertain
from tests.test_remote_chat_window import opened, say
from tests.test_remote_runner import World, _finish

LONG = "word " * 2000


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


async def settle(w):
    await asyncio.gather(*list(w.runner._wakes))


async def test_the_parts_of_a_long_reply_arrive_in_order(w):
    await opened(w)
    await say(w, "go")
    w.channel.posted.clear()
    await _finish(w, LONG)
    await settle(w)
    assert [m.splitlines()[0].rsplit(" ", 1)[1] for m in w.channel.posted] == ["(1/3)", "(2/3)", "(3/3)"]


async def test_the_loop_does_not_wait_for_a_slow_channel_while_parts_go_out(w):
    await opened(w)
    await say(w, "go")
    w.channel.posted.clear()
    release = asyncio.Event()
    real = w.channel.post
    loop = asyncio.get_running_loop()

    def slow(text, reply_to=None):
        asyncio.run_coroutine_threadsafe(release.wait(), loop).result(5)
        return real(text, reply_to)

    w.channel.post = slow
    await asyncio.wait_for(_finish(w, LONG), 2)
    assert w.channel.posted == []
    await asyncio.wait_for(w.runner.tick(), 2)
    release.set()
    await settle(w)
    assert len(w.channel.posted) == 3


async def test_a_part_that_fails_is_tried_again_and_the_rest_follow(w):
    await opened(w)
    await say(w, "go")
    w.channel.posted.clear()
    real, calls = w.channel.post, []

    def flaky(text, reply_to=None):
        calls.append(text)
        if len(calls) == 2:
            raise OSError("429")
        return real(text, reply_to)

    w.channel.post = flaky
    await _finish(w, LONG)
    await settle(w)
    assert [m.splitlines()[0].rsplit(" ", 1)[1] for m in w.channel.posted] == ["(1/3)", "(2/3)", "(3/3)"]
    assert all("did not send" not in m for m in w.channel.posted)


async def test_a_part_that_fails_twice_is_said_so_and_the_rest_still_follow(w):
    await opened(w)
    await say(w, "go")
    w.channel.posted.clear()
    real = w.channel.post

    def refusing(text, reply_to=None):
        if "(2/3)" in text.splitlines()[0]:
            raise OSError("429")
        return real(text, reply_to)

    w.channel.post = refusing
    await _finish(w, LONG)
    await settle(w)
    posted = w.channel.posted
    assert len(posted) == 3
    assert posted[0].splitlines()[0].endswith("(1/3)")
    assert posted[1] == commands.part_not_sent(2, 3)
    assert posted[2].splitlines()[0].endswith("(3/3)")


async def test_two_long_replies_never_interleave(w):
    await opened(w)
    await say(w, "go")
    w.channel.posted.clear()
    first = [f"[x] (1/2)\none", f"[x] (2/2)\ntwo"]
    second = [f"[y] (1/2)\none", f"[y] (2/2)\ntwo"]
    await w.runner._post_all(first)
    await w.runner._post_all(second)
    await settle(w)
    assert [m.split("\n")[0] for m in w.channel.posted] == ["[x] (1/2)", "[x] (2/2)", "[y] (1/2)", "[y] (2/2)"]


async def test_no_other_post_lands_between_the_parts_of_a_reply(w):
    await opened(w)
    await say(w, "go")
    w.channel.posted.clear()
    release = asyncio.Event()
    real = w.channel.post
    loop = asyncio.get_running_loop()

    def gated(text, reply_to=None):
        if "(2/2)" in text.splitlines()[0]:
            asyncio.run_coroutine_threadsafe(release.wait(), loop).result(5)
        return real(text, reply_to)

    w.channel.post = gated
    await w.runner._post_all(["[x] (1/2)\none", "[x] (2/2)\ntwo"])
    note = asyncio.create_task(w.runner._post("[note]"))
    await asyncio.sleep(0.05)
    release.set()
    await settle(w)
    await note
    assert [m.split("\n")[0] for m in w.channel.posted] == ["[x] (1/2)", "[x] (2/2)", "[note]"]


async def test_a_part_whose_post_got_no_answer_is_not_sent_again(w):
    await opened(w)
    await say(w, "go")
    w.channel.posted.clear()
    real, calls = w.channel.post, []

    def silent(text, reply_to=None):
        calls.append(text)
        if "(2/3)" in text.splitlines()[0]:
            raise PostUncertain("timed out")
        return real(text, reply_to)

    w.channel.post = silent
    await _finish(w, LONG)
    await settle(w)
    assert sum("(2/3)" in c.splitlines()[0] for c in calls) == 1
    posted = w.channel.posted
    assert len(posted) == 3
    assert posted[1] == commands.part_unsure(2, 3)
    assert posted[2].splitlines()[0].endswith("(3/3)")


def test_the_pause_between_parts_is_a_real_second_outside_tests():
    import importlib

    source = importlib.util.find_spec("remote.runner").origin
    assert "PART_PAUSE_SECONDS = 1.0" in open(source, encoding="utf-8").read()
    assert runner.PART_PAUSE_SECONDS == 0.0
