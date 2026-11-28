"""Messaging another agent from a chat: who is reachable, how a typed name picks one, the hourly
limit, the permission-mode checks, and the runner's routing and replies."""

import pytest

import agent_wake
from remote import commands, peers as peers_mod
from remote.peers import Peer, PeerDirectory, PeerLimiter, PeerRefused, WakeGateway, addressable, resolve
from remote.runner import RemoteRunner
from remote.service import RemoteService
from tests.test_remote_runner import BUDGET, World, baselined

RESERVED = frozenset((*commands.RESERVED, "all", "gator", "claude"))


def entry(title, session_id=None, state="live", pty="p", project="budget"):
    session_id = session_id or f"{title.replace(' ', '')}-0000-aaaa-bbbb".lower()
    return {
        "state": state,
        "pty_id": f"{pty}-{session_id[:4]}",
        "agent": "claude",
        "project_id": project,
        "session_id": session_id,
        "title": title,
    }


def peers_of(*titles):
    return [Peer(entry(t)) for t in titles]


# ---------------------------------------------------------------- resolving a typed name

def test_a_name_picks_the_peer_and_leaves_the_message():
    found = resolve(peers_of("MergeBrain"), "MergeBrain please rebase", RESERVED)
    assert found.peer.name == "MergeBrain"
    assert found.text == "please rebase"


def test_names_match_exactly_apart_from_case_and_a_leading_at():
    assert resolve(peers_of("MergeBrain"), "@mergebrain hi", RESERVED).text == "hi"
    assert resolve(peers_of("MergeBrain"), "merge hi", RESERVED) is None
    assert resolve(peers_of("MergeBrain"), "MergeBrainy hi", RESERVED) is None


def test_a_colon_or_the_end_of_the_text_ends_the_name():
    assert resolve(peers_of("MergeBrain"), "MergeBrain: hi", RESERVED).text == "hi"
    assert resolve(peers_of("MergeBrain"), "MergeBrain", RESERVED).text == ""


def test_a_name_of_several_words_and_the_longest_name_wins():
    both = peers_of("Design", "Design Head")
    found = resolve(both, "Design Head tighten the dock", RESERVED)
    assert found.peer.name == "Design Head"
    assert found.text == "tighten the dock"
    assert resolve(both, "Design tighten the dock", RESERVED).peer.name == "Design"


def test_the_session_id_and_its_first_eight_characters_pick_the_peer():
    peer = Peer(entry("MergeBrain", session_id="0123456789abcdef"))
    assert resolve([peer], "01234567 hi", RESERVED).peer is peer
    assert resolve([peer], "0123456789abcdef hi", RESERVED).peer is peer
    assert resolve([peer], "0123456 hi", RESERVED) is None


def test_two_peers_with_one_name_are_ambiguous_but_ids_still_work():
    a = Peer(entry("Memory", session_id="aaaaaaaa-1"))
    b = Peer(entry("Memory", session_id="bbbbbbbb-2"))
    found = resolve([a, b], "Memory hi", RESERVED)
    assert found.peer is None
    assert {c.session_id for c in found.candidates} == {a.session_id, b.session_id}
    assert resolve([a, b], "bbbbbbbb hi", RESERVED).peer is b


@pytest.mark.parametrize("title", ["list", "Stop the build", "gator", "All hands", "claude helper"])
def test_a_name_that_starts_with_a_reserved_word_is_reached_only_by_id(title):
    peer = Peer(entry(title, session_id="cafe0000-1"))
    assert not addressable(peer, RESERVED)
    assert resolve([peer], f"{title} hi", RESERVED) is None
    assert resolve([peer], "cafe0000 hi", RESERVED).peer is peer


def test_a_name_that_collides_with_a_remote_session_is_reached_only_by_id():
    peer = Peer(entry("budget", session_id="cafe0000-1"))
    assert resolve([peer], "budget hi", RESERVED | {"budget"}) is None
    assert resolve([peer], "budget hi", RESERVED).peer is peer


def test_an_untitled_session_has_only_its_id():
    peer = Peer(entry("", session_id="cafe0000-1"))
    assert peer.name == "cafe0000-1"
    assert not addressable(peer, RESERVED)


def test_a_name_is_one_line():
    assert Peer(entry("Merge\n  Brain")).name == "Merge Brain"


# ---------------------------------------------------------------- the limit

class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


def test_the_limit_counts_messages_to_one_peer_in_the_last_hour():
    clock, cap = Clock(), [2]
    limiter = PeerLimiter(lambda: cap[0], clock)
    assert limiter.wait_seconds("a") == 0
    limiter.record("a")
    limiter.record("a")
    assert limiter.wait_seconds("a") == pytest.approx(3600)
    assert limiter.wait_seconds("b") == 0
    clock.now += 1800
    assert limiter.wait_seconds("a") == pytest.approx(1800)
    clock.now += 1800
    assert limiter.wait_seconds("a") == 0


def test_zero_means_no_limit_and_a_new_value_applies_at_once():
    cap = [0]
    limiter = PeerLimiter(lambda: cap[0], Clock())
    for _ in range(100):
        limiter.record("a")
    assert limiter.wait_seconds("a") == 0
    cap[0] = 5
    assert limiter.wait_seconds("a") > 0
    assert limiter.limit == 5


class FakeGateway:
    def __init__(self, *entries):
        self.listed = list(entries)
        self.calls = 0
        self.sent = []
        self.refuse = None
        self.woke = False

    def entries(self):
        self.calls += 1
        return list(self.listed)

    async def deliver(self, peer, text, sender_name):
        if self.refuse:
            raise PeerRefused(self.refuse, "unsafe_mode")
        self.sent.append((peer.name, text, sender_name))
        return self.woke


async def test_the_directory_keeps_to_the_project_and_leaves_out_remote_sessions():
    gateway = FakeGateway(
        entry("Mine", project="budget"),
        entry("Elsewhere", project="other"),
        entry("Remote one", pty="remote"),
    )
    directory = PeerDirectory(gateway, lambda: 30, Clock())
    found = await directory.peers("budget", {"remote-remo"})
    assert [p.name for p in found] == ["Mine"]


async def test_live_peers_come_before_suspended_ones_each_by_name():
    gateway = FakeGateway(
        entry("Zed", state="live"), entry("Alpha", state="suspended"), entry("Beta", state="live")
    )
    found = await PeerDirectory(gateway, lambda: 30, Clock()).peers("budget", set())
    assert [p.name for p in found] == ["Beta", "Zed", "Alpha"]


async def test_the_listing_is_reused_until_it_is_old_or_a_fresh_one_is_asked_for():
    clock, gateway = Clock(), FakeGateway(entry("Mine"))
    directory = PeerDirectory(gateway, lambda: 30, clock, cache_seconds=15)
    await directory.peers("budget", set())
    await directory.peers("budget", set())
    assert gateway.calls == 1
    await directory.peers("budget", set(), refresh=True)
    assert gateway.calls == 2
    clock.now += 16
    await directory.peers("budget", set())
    assert gateway.calls == 3


async def test_only_a_delivered_message_counts_against_the_limit():
    gateway = FakeGateway(entry("Mine"))
    directory = PeerDirectory(gateway, lambda: 1, Clock())
    peer = (await directory.peers("budget", set()))[0]
    gateway.refuse = "no"
    with pytest.raises(PeerRefused):
        await directory.deliver(peer, "hi", "Teams chat")
    assert directory.limiter.wait_seconds(peer.session_id) == 0
    gateway.refuse = None
    await directory.deliver(peer, "hi", "Teams chat")
    assert directory.limiter.wait_seconds(peer.session_id) > 0


# ---------------------------------------------------------------- the real gateway

def test_the_gateway_leaves_out_remote_sessions_and_relay_opt_outs(monkeypatch):
    from relay import settings as relay_settings

    listed = [
        {**entry("Open"), "remote_pinned": False},
        {**entry("Mine", pty="remote"), "remote_pinned": True},
        entry("Closed", pty="closed"),
    ]
    monkeypatch.setattr(agent_wake, "list_entries", lambda: listed)
    monkeypatch.setattr(relay_settings, "opted_out", lambda key: key == "pty:closed-clos")
    assert [e["title"] for e in WakeGateway().entries()] == ["Open"]


async def test_the_gateway_delivers_as_a_person_without_spending_an_agent_slot(monkeypatch):
    seen = {}

    async def deliver_entry(sender, e, message, **kw):
        seen.update(sender=sender, entry=e, message=message, **kw)
        return {"woke": True}

    monkeypatch.setattr(agent_wake, "deliver_entry", deliver_entry)
    gateway = WakeGateway()
    assert await gateway.deliver(Peer(entry("Mine")), "hi", "Teams chat") is True
    assert seen["sender"] == {"name": "Teams chat"}
    assert seen["spend_slot"] is False
    assert seen["origin"] == "user"
    assert seen["live_wait"] == peers_mod.READY_SECONDS
    assert seen["before_type"] == gateway._check_permission_mode


async def test_a_refusal_from_the_wake_path_is_audited_and_surfaced(monkeypatch):
    audited = []

    async def deliver_entry(*a, **kw):
        raise agent_wake.WakeRefused("typing", "Its user is typing.")

    monkeypatch.setattr(agent_wake, "deliver_entry", deliver_entry)
    monkeypatch.setattr(agent_wake, "audit_refusal", lambda *a: audited.append(a))
    with pytest.raises(PeerRefused) as raised:
        await WakeGateway().deliver(Peer(entry("Mine")), "hi", "Teams chat")
    assert raised.value.reason == "Its user is typing."
    assert audited and audited[0][2] == "typing"


@pytest.mark.parametrize("mode", ["default", "plan"])
async def test_a_session_that_asks_before_acting_may_be_typed_into(monkeypatch, mode):
    monkeypatch.setattr(peers_mod, "_read_mode", lambda pty: mode)
    monkeypatch.setattr(peers_mod, "_screen_skips_prompts", lambda pty: False)
    await WakeGateway()._check_permission_mode("p1")


@pytest.mark.parametrize("mode", ["bypassPermissions", "acceptEdits", "auto", "dontAsk", None])
async def test_any_other_or_unknown_mode_is_refused(monkeypatch, mode):
    monkeypatch.setattr(peers_mod, "_read_mode", lambda pty: mode)
    monkeypatch.setattr(peers_mod, "_screen_skips_prompts", lambda pty: False)
    with pytest.raises(agent_wake.WakeRefused):
        await WakeGateway()._check_permission_mode("p1")


async def test_a_footer_showing_bypass_wins_over_a_stale_default_mode(monkeypatch):
    monkeypatch.setattr(peers_mod, "_read_mode", lambda pty: "default")
    monkeypatch.setattr(peers_mod, "_screen_skips_prompts", lambda pty: True)
    with pytest.raises(agent_wake.WakeRefused) as raised:
        await WakeGateway()._check_permission_mode("p1")
    assert raised.value.code == "unsafe_mode"


@pytest.mark.parametrize(
    "footer, skips",
    [
        ("\x1b[1m>> bypass permissions on\x1b[0m (shift+tab to cycle)", True),
        (">> accept edits on", True),
        ("auto-accept edits", True),
        ("? for shortcuts", False),
    ],
)
def test_the_screen_check_reads_the_footer_without_colour_codes(monkeypatch, footer, skips):
    from routes import terminal

    class Pty:
        def read_from(self, since):
            return (footer, len(footer)) if since < len(footer) else ("", len(footer))

    monkeypatch.setattr(terminal, "get_pty_session", lambda pty: Pty())
    assert peers_mod._screen_skips_prompts("p1") is skips


# ---------------------------------------------------------------- the runner

class PeerWorld(World):
    def __init__(self, tmp_path, *entries, limit=30):
        self.gateway = FakeGateway(*entries)
        self.limit = [limit]
        super().__init__(tmp_path)
        self.service = RemoteService(self.host, default_project=lambda: BUDGET, clock=self.clock)
        self.runner = RemoteRunner(
            self.channel,
            self.service,
            self.guard,
            self.state,
            clock=self.clock,
            stale_seconds=900,
            branch_of=lambda path: "main",
            peers=PeerDirectory(self.gateway, lambda: self.limit[0], self.clock),
        )
        self.runner.sync_enabled(True)

    async def say(self, text):
        self.seq = getattr(self, "seq", 100) + 1
        await self.feed(self.msg(self.seq, text))


@pytest.fixture
def pw(tmp_path):
    return PeerWorld(tmp_path, entry("MergeBrain"), entry("Design Head", state="suspended"))


async def test_a_tagged_name_sends_the_text_to_that_agent_only(pw):
    await baselined(pw)
    await pw.say("@gator MergeBrain please rebase")
    assert pw.gateway.sent == [("MergeBrain", "please rebase", "Teams chat")]
    assert pw.host.delivered == [] and pw.host.n == 0
    assert pw.channel.posted == [commands.peer_sent("MergeBrain", False)]


async def test_a_woken_agent_is_said_to_be_woken(pw):
    await baselined(pw)
    pw.gateway.woke = True
    await pw.say("@gator Design Head tighten the dock")
    assert pw.channel.posted == [commands.peer_sent("Design Head", True)]
    assert "Woke Design Head" in pw.channel.posted[0]


async def test_a_mention_form_reaches_the_agent_too(pw):
    await baselined(pw)
    await pw.say("@gator @mergebrain hi")
    assert [s[:2] for s in pw.gateway.sent] == [("MergeBrain", "hi")]


async def test_an_open_chat_window_never_routes_to_an_agent(pw):
    await baselined(pw)
    await pw.say("@gator hi")
    await pw.say("MergeBrain please rebase")
    assert pw.gateway.sent == []
    assert pw.host.n == 1  # it became a request to a new Remote session instead


async def test_a_name_alone_asks_for_the_message(pw):
    await baselined(pw)
    await pw.say("@gator MergeBrain")
    assert pw.gateway.sent == []
    assert pw.channel.posted == [commands.mention_needs_text("MergeBrain")]


async def test_a_name_that_matches_nobody_goes_on_as_a_request(pw):
    await baselined(pw)
    await pw.say("@gator Merge the branches")
    assert pw.gateway.sent == []
    assert pw.host.n == 1


async def test_a_remote_session_wins_over_an_agent_with_the_same_name(tmp_path):
    w = PeerWorld(tmp_path, entry("budget", session_id="cafe0000-1"))
    await baselined(w)
    await w.say("@gator start it")
    assert w.host.n == 1
    await w.say("@gator budget status please")
    assert w.gateway.sent == []
    assert w.host.delivered[-1][1] == "status please"


async def test_two_agents_with_one_name_get_an_ambiguity_reply(tmp_path):
    w = PeerWorld(tmp_path, entry("Memory", session_id="aaaaaaaa-1"), entry("Memory", session_id="bbbbbbbb-2"))
    await baselined(w)
    await w.say("@gator Memory hi")
    assert w.gateway.sent == []
    assert w.channel.posted == [commands.peer_ambiguous("Memory", [("aaaaaaaa", "live"), ("bbbbbbbb", "live")])]
    await w.say("@gator bbbbbbbb hi")
    assert [s[:2] for s in w.gateway.sent] == [("Memory", "hi")]


async def test_a_refusal_is_said_and_does_not_count(pw):
    await baselined(pw)
    pw.gateway.refuse = "It is set to run without asking for permission, so I will not message it."
    await pw.say("@gator MergeBrain hi")
    assert pw.channel.posted == [commands.peer_refused("MergeBrain", pw.gateway.refuse)]
    pw.gateway.refuse = None
    await pw.say("@gator MergeBrain hi")
    assert len(pw.gateway.sent) == 1


async def test_the_hourly_limit_stops_the_next_message_and_zero_lifts_it(tmp_path):
    w = PeerWorld(tmp_path, entry("MergeBrain"), limit=2)
    await baselined(w)
    for _ in range(3):
        await w.say("@gator MergeBrain hi")
    assert len(w.gateway.sent) == 2
    assert w.channel.posted[-1] == commands.peer_limit("MergeBrain", 2, 3600)
    w.limit[0] = 0
    await w.say("@gator MergeBrain hi")
    assert len(w.gateway.sent) == 3


async def test_list_shows_the_other_agents_with_how_to_reach_them(pw):
    await baselined(pw)
    await pw.say("@gator list")
    reply = pw.channel.posted[-1]
    assert "Other agents in this project:" in reply
    assert "- Design Head" in reply and "- MergeBrain" in reply
    assert "`@gator Design Head your message`" in reply or "`@gator MergeBrain your message`" in reply


async def test_list_caps_the_agents_and_counts_the_rest(tmp_path):
    w = PeerWorld(tmp_path, *[entry(f"Agent{i:02}", session_id=f"id{i:02}0000-x") for i in range(11)])
    await baselined(w)
    await w.say("@gator list")
    reply = w.channel.posted[-1]
    assert reply.count("\n- Agent") == commands.PEERS_SHOWN
    assert "- 3 more." in reply


async def test_list_gives_the_id_for_a_name_that_cannot_be_typed(tmp_path):
    w = PeerWorld(tmp_path, entry("stop the line", session_id="cafe0000-1"))
    await baselined(w)
    await w.say("@gator list")
    assert "- stop the line (cafe0000)" in w.channel.posted[-1]
    assert "`@gator cafe0000 your message`" in w.channel.posted[-1]


async def test_list_without_agents_is_unchanged(tmp_path):
    w = PeerWorld(tmp_path)
    await baselined(w)
    await w.say("@gator list")
    assert w.channel.posted == [commands.no_sessions()]


async def test_a_failing_directory_does_not_break_other_commands(tmp_path):
    w = PeerWorld(tmp_path)

    def boom():
        raise OSError("disk")

    w.gateway.entries = boom
    await baselined(w)
    await w.say("@gator do something")
    assert w.host.n == 1


def test_the_list_text_is_unchanged_when_there_are_only_remote_sessions():
    assert "Other agents" not in commands.session_list([("budget", "Budget", commands.IDLE)])


def test_the_list_text_with_only_agents_says_no_remote_sessions_are_running():
    text = commands.session_list([], [("MergeBrain", "live")], 0, "MergeBrain")
    assert "No remote sessions are running." in text
    assert "Send a request and it starts a new session." in text


async def test_an_answer_that_starts_with_an_agents_name_goes_to_the_waiting_session(pw):
    await baselined(pw)
    await pw.say("@gator start something")
    pw.service.list()[0].waiting = True
    pw.host.delivered.clear()
    await pw.say("@gator MergeBrain is done")
    assert pw.gateway.sent == []
    assert pw.host.delivered == [("pty-1", "MergeBrain is done")]


async def test_a_colon_still_reaches_the_agent_while_a_session_waits(pw):
    await baselined(pw)
    await pw.say("@gator start something")
    pw.service.list()[0].waiting = True
    pw.host.delivered.clear()
    await pw.say("@gator MergeBrain: rebase please")
    assert pw.gateway.sent == [("MergeBrain", "rebase please", "Teams chat")]
    assert pw.host.delivered == []


def test_colon_only_ignores_a_name_followed_by_a_space():
    assert resolve(peers_of("MergeBrain"), "MergeBrain hi", RESERVED, colon_only=True) is None
    assert resolve(peers_of("MergeBrain"), "MergeBrain: hi", RESERVED, colon_only=True).text == "hi"
