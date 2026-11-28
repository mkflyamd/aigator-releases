import pytest

from remote import teams_channel
from remote.channel import ChannelRefused
from remote.state import State
from remote.teams_channel import TeamsSelfChat


@pytest.fixture
def sent(monkeypatch, autosend_gate):
    calls = []

    def fake_send(chat_id, html):
        calls.append((chat_id, html))
        return "777"

    monkeypatch.setattr(teams_channel, "send_message", fake_send)
    return calls


def test_post_to_the_own_self_chat_sends_and_records_the_id(tmp_path, sent):
    state = State(tmp_path / "s.json")
    chat = TeamsSelfChat(state=state)
    assert chat.post("[\U0001F40A Gator] Online") == "777"
    assert sent == [("48:notes", "<div>[\U0001F40A Gator] Online</div>")]
    assert state.is_own_post("teams", "777")


def test_post_to_any_other_chat_is_refused_and_logged(tmp_path, sent, caplog):
    chat = TeamsSelfChat(chat_id="19:someone@thread.v2", state=State(tmp_path / "s.json"))
    assert chat.is_own_self_chat() is False
    with caplog.at_level("WARNING"):
        with pytest.raises(ChannelRefused):
            chat.post("[\U0001F40A Gator] hello")
    assert sent == []
    assert "19:someone@thread.v2" in caplog.text
    assert "not the own self-chat" in caplog.text


def test_post_that_could_form_a_command_is_refused(tmp_path, sent):
    chat = TeamsSelfChat(state=State(tmp_path / "s.json"))
    for text in ("@gator stop all", "hello", "  @GATOR x", "[todo] x"):
        with pytest.raises(ChannelRefused):
            chat.post(text)
    assert sent == []


def test_an_agent_reply_is_posted(tmp_path, sent):
    chat = TeamsSelfChat(state=State(tmp_path / "s.json"))
    chat.post("[\U0001F40A Gator - Budget] Done.")
    chat.post("[\U0001F40A Gator - budget - Budget] Done.")
    assert len(sent) == 2


def test_post_escapes_markup_so_agent_text_is_not_rendered_as_html(tmp_path, sent):
    chat = TeamsSelfChat(state=State(tmp_path / "s.json"))
    chat.post("[\U0001F40A Gator - x] <b>hi</b> & bye\nline two")
    html = sent[0][1]
    assert "<b>" not in html
    assert "&lt;b&gt;hi&lt;/b&gt; &amp; bye<br>line two" in html


def test_post_converts_markdown_to_teams_html(tmp_path, sent):
    chat = TeamsSelfChat(state=State(tmp_path / "s.json"))
    chat.post("[\U0001F40A Gator - x] **Done** with `ls`\n> a note\n- one\n- two")
    html = sent[0][1]
    assert "**" not in html
    assert "&gt; a note" not in html
    assert html == (
        "<div>[\U0001F40A Gator - x] <strong>Done</strong> with <code>ls</code></div>"
        "<blockquote>a note</blockquote><ul><li>one</li><li>two</li></ul>"
    )


def test_a_failed_send_posts_nothing_and_raises_refused(tmp_path, monkeypatch, autosend_gate):
    def boom(chat_id, html):
        raise RuntimeError("token expired")

    monkeypatch.setattr(teams_channel, "send_message", boom)
    chat = TeamsSelfChat(state=State(tmp_path / "s.json"))
    with pytest.raises(ChannelRefused, match="token expired"):
        chat.post("[\U0001F40A Gator] hi")


def test_poll_returns_inbound_messages_newest_first(monkeypatch):
    raw = [
        {"id": "2", "message_type": "message", "body": "@gator two", "body_html": "", "created_at": "2026-11-26T10:00:05.000Z"},
        {"id": "1", "message_type": "systemEvent", "body": "", "body_html": "", "created_at": ""},
        {"id": "0", "message_type": "message", "body": "", "body_html": "<div>@gator <b>one</b></div>", "created_at": "2026-11-26T10:00:00Z"},
    ]
    monkeypatch.setattr(teams_channel, "fetch_messages", lambda chat_id: raw)
    msgs = TeamsSelfChat().poll()
    assert [m.id for m in msgs] == ["2", "0"]
    assert msgs[0].text == "@gator two"
    assert msgs[1].text == "@gator one"
    assert msgs[0].created_at - msgs[1].created_at == 5


def test_a_missing_or_unparseable_timestamp_has_no_time(monkeypatch):
    raw = [
        {"id": "3", "message_type": "message", "body": "@gator a", "body_html": "", "created_at": ""},
        {"id": "2", "message_type": "message", "body": "@gator b", "body_html": "", "created_at": "garbage"},
        {"id": "1", "message_type": "message", "body": "@gator c", "body_html": ""},
    ]
    monkeypatch.setattr(teams_channel, "fetch_messages", lambda chat_id: raw)
    messages = TeamsSelfChat().poll()
    assert [m.created_at for m in messages] == [0.0, 0.0, 0.0]


def test_a_quote_in_a_link_cannot_add_an_attribute(tmp_path, sent):
    chat = TeamsSelfChat(state=State(tmp_path / "s.json"))
    chat.post('[\U0001F40A Gator - x] [a](https://a.com/"onmouseover="alert(1))')
    assert "<a " not in sent[0][1]


QUOTE_REPLY_HTML = (
    '<blockquote itemscope="" itemtype="http://schema.skype.com/Reply" itemid="1764237600123">'
    '<strong itemprop="mri" itemid="8:orgid:00000000-0000-0000-0000-000000000000">Test User</strong>'
    '<span itemprop="time" itemid="1764237600123"></span>'
    '<p itemprop="preview">[Gator - budget - Budget] Needs you: permission. Tool: Bash Command: echo hi</p>'
    "</blockquote><p>@gator allow</p>"
)


def _poll_one(monkeypatch, html, body=""):
    raw = [{"id": "5", "message_type": "message", "body": body, "body_html": html, "created_at": "2026-11-26T10:00:00Z"}]
    monkeypatch.setattr(teams_channel, "fetch_messages", lambda chat_id: raw)
    return TeamsSelfChat().poll()[0]


def test_a_quote_reply_keeps_only_the_typed_text_and_exposes_the_quoted_message_id(monkeypatch):
    msg = _poll_one(monkeypatch, QUOTE_REPLY_HTML, body="Test User [Gator - budget] Needs you @gator allow")
    assert msg.text == "@gator allow"
    assert msg.reply_to == "1764237600123"


def test_a_plain_message_has_no_reply_to(monkeypatch):
    msg = _poll_one(monkeypatch, "<p>@gator allow</p>")
    assert msg.text == "@gator allow" and msg.reply_to is None


def test_a_quote_with_nothing_typed_is_empty_not_the_quoted_text(monkeypatch):
    html = QUOTE_REPLY_HTML.split("</blockquote>")[0] + "</blockquote>"
    msg = _poll_one(monkeypatch, html, body="Test User [Gator - budget] Needs you @gator allow")
    assert msg.text == "" and msg.reply_to == "1764237600123"
