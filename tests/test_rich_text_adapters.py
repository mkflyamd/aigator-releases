from skills import _rich_text as rt

MENTION = (
    '<span data-mention-id="{id}" data-mention-name="{name}" '
    'data-mention-service="{svc}">@{name}</span>'
)


# ── registry ──────────────────────────────────────────────────────────────────


def test_service_for_and_capabilities():
    assert rt.service_for("email-reply") == "email"
    assert rt.service_for("slack-dm") == "slack"
    assert rt.service_for("teams-message") == "teams"
    assert rt.service_for("jira-create") == ""
    assert "underline" in rt.capabilities("email")
    assert "underline" not in rt.capabilities("slack")
    assert rt.capabilities("nope") == []


def test_rich_payload_shape():
    assert rt.rich_payload("slack", "<p>x</p>") == {
        "body_html": "<p>x</p>",
        "format_capabilities": rt.capabilities("slack"),
    }


# ── email ─────────────────────────────────────────────────────────────────────


def test_email_passes_formatting_through_and_flattens_mentions():
    src = "<p><b>Hi</b> " + MENTION.format(id="U1", name="Alex", svc="slack") + "</p><ul><li>a</li></ul>"
    out = rt.render("email", src).content
    assert out == "<p><b>Hi</b> @Alex</p><ul><li>a</li></ul>"


# ── teams ─────────────────────────────────────────────────────────────────────


def test_teams_builds_skype_mentions_and_divs():
    src = "<p>Hi " + MENTION.format(id="AAD1", name="Alex", svc="teams") + "</p><p><b>x</b></p>"
    out = rt.render("teams", src)
    assert out.content == (
        '<div>Hi <span itemscope itemtype="http://schema.skype.com/Mention" itemid="0">Alex</span></div>'
        "<div><b>x</b></div>"
    )
    assert out.mentions == [
        {
            "id": 0,
            "mentionText": "Alex",
            "mentioned": {"user": {"id": "AAD1", "displayName": "Alex", "userIdentityType": "aadUser"}},
        }
    ]


def test_teams_non_user_mentions_become_plain_text():
    src = "<p>" + MENTION.format(id="!here", name="here", svc="slack") + "</p>"
    out = rt.render("teams", src)
    assert out.content == "<div>@here</div>"
    assert out.mentions == []


def test_teams_to_html_round_trips_skype_spans():
    message = (
        '<div>Hi <span itemscope itemtype="http://schema.skype.com/Mention" itemid="0">Alex</span></div>'
    )
    mentions = [
        {"id": 0, "mentionText": "Alex", "mentioned": {"user": {"id": "AAD1", "displayName": "Alex"}}}
    ]
    html = rt.teams_to_html(message, mentions)
    assert html == "<p>Hi " + MENTION.format(id="AAD1", name="Alex", svc="teams") + "</p>"
    assert rt.render("teams", html).mentions[0]["mentioned"]["user"]["id"] == "AAD1"


def test_teams_to_html_plain_text_keeps_paragraphs_and_escapes():
    message = (
        'Hi <span itemscope itemtype="http://schema.skype.com/Mention" itemid="0">Alex</span>,'
        "\n\nReview a < b & ship.\nThanks"
    )
    mentions = [
        {"id": 0, "mentionText": "Alex", "mentioned": {"user": {"id": "AAD1", "displayName": "Alex"}}}
    ]
    assert rt.teams_to_html(message, mentions) == (
        "<p>Hi " + MENTION.format(id="AAD1", name="Alex", svc="teams") + ",</p>"
        "<p>Review a &lt; b &amp; ship.<br>Thanks</p>"
    )


# ── slack ─────────────────────────────────────────────────────────────────────


def test_slack_inline_formatting():
    src = (
        '<p><strong>b</strong> <i>i</i> <s>s</s> <u>u</u> <code>c</code> '
        '<a href="https://x.com">site</a> <a href="https://y.com">https://y.com</a></p>'
    )
    assert rt.render("slack", src).content == (
        "*b* _i_ ~s~ u `c` <https://x.com|site> <https://y.com>"
    )


def test_slack_blocks_and_newlines():
    src = (
        "<p>one<br>two</p><p>para</p><ul><li>a</li><li>b</li></ul>"
        "<ol><li>x</li><li>y</li></ol><blockquote>q</blockquote><pre>a &lt; b</pre>"
    )
    assert rt.render("slack", src).content == (
        "one\ntwo\n\npara\n\n• a\n• b\n\n1. x\n2. y\n\n> q\n\n```\na &lt; b\n```"
    )


def test_slack_nested_list_indents():
    src = "<ul><li>a<ul><li>b</li></ul></li></ul>"
    assert rt.render("slack", src).content == "• a\n  • b"


def test_slack_escapes_special_characters_in_text():
    assert rt.render("slack", "<p>a &lt;b&gt; &amp; c</p>").content == "a &lt;b&gt; &amp; c"


def test_slack_mentions_and_specials():
    src = (
        "<p>Hi "
        + MENTION.format(id="U1", name="Alex", svc="slack")
        + " "
        + MENTION.format(id="!here", name="here", svc="slack")
        + "</p>"
    )
    assert rt.render("slack", src).content == "Hi <@U1> <!here>"


def test_slack_to_html_round_trip_preserves_native_tokens():
    message = "Hi <@U1> <!here> see <https://x.com|site> *bold* _it_ ~s~\n\n• not a list marker"
    html = rt.slack_to_html(message, {"U1": "Alex"})
    assert MENTION.format(id="U1", name="Alex", svc="slack") in html
    assert "<strong>bold</strong>" in html and "<em>it</em>" in html and "<s>s</s>" in html
    assert rt.render("slack", html).content.startswith(
        "Hi <@U1> <!here> see <https://x.com|site> *bold* _it_ ~s~"
    )


def test_slack_heading_and_table_flatten():
    assert rt.render("slack", "<h2>Title</h2><p>x</p>").content == "*Title*\n\nx"
    assert (
        rt.render("slack", "<table><tr><th>a</th><td>b</td></tr></table>").content == "a | b"
    )


def test_slack_mention_id_with_injected_markup_renders_as_text():
    src = "<p>Hi " + MENTION.format(id="U1&gt; &lt;!channel", name="Alex", svc="slack") + "</p>"
    out = rt.render("slack", src).content
    assert out == "Hi @Alex"
    assert "<!channel>" not in out


def test_slack_valid_user_mention_still_renders_token():
    src = "<p>Hi " + MENTION.format(id="U123ABC", name="Alex", svc="slack") + "</p>"
    assert rt.render("slack", src).content == "Hi <@U123ABC>"


def test_slack_special_and_channel_mentions_still_render_tokens():
    src = "<p>" + MENTION.format(id="!channel", name="channel", svc="slack") + "</p>"
    assert rt.render("slack", src).content == "<!channel>"
    src = "<p>" + MENTION.format(id="#C123", name="chan", svc="slack") + "</p>"
    assert rt.render("slack", src).content == "<#C123>"


def test_slack_link_href_is_neutralized():
    src = '<p><a href="https://a.com/&gt; &lt;!channel|x">link</a></p>'
    assert rt.render("slack", src).content == "<https://a.com/%3E%20%3C!channel%7Cx|link>"


def test_slack_normal_link_unchanged():
    src = "<p><a href=\"https://x.com\">site</a></p>"
    assert rt.render("slack", src).content == "<https://x.com|site>"
