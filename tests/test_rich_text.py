from skills import _rich_text as rt


# ── sanitize ──────────────────────────────────────────────────────────────────


def test_sanitize_keeps_allowed_subset():
    src = "<p>Hi <b>there</b> <i>x</i> <u>y</u> <s>z</s> <code>c</code></p><ul><li>a</li></ul>"
    assert rt.sanitize(src) == src


def test_sanitize_drops_scripts_styles_and_event_attributes():
    out = rt.sanitize(
        '<p onclick="x()">Hi</p><script>alert(1)</script><style>p{}</style><iframe src="x"></iframe>'
    )
    assert out == "<p>Hi</p>"


def test_sanitize_unterminated_script_drops_the_rest():
    assert rt.sanitize("<p>ok</p><script>alert(1)<p>boom</p>") == "<p>ok</p>"


def test_sanitize_links_only_http_https_mailto():
    assert rt.sanitize('<a href="https://a.com">x</a>') == '<a href="https://a.com">x</a>'
    assert rt.sanitize('<a href="mailto:a@b.com">x</a>') == '<a href="mailto:a@b.com">x</a>'
    assert rt.sanitize('<a href="javascript:alert(1)">x</a>') == "<a>x</a>"
    assert rt.sanitize('<a href=" jav&#x61;script:alert(1)">x</a>') == "<a>x</a>"


def test_sanitize_div_becomes_paragraph_and_unknown_tags_unwrap():
    assert rt.sanitize("<div>a<font>b</font></div>") == "<p>ab</p>"


def test_sanitize_keeps_tables_and_headings():
    src = "<h2>T</h2><table><tr><th>a</th><td colspan=\"2\">b</td></tr></table>"
    assert rt.sanitize(src) == '<h2>T</h2><table><tr><th>a</th><td colspan="2">b</td></tr></table>'


def test_sanitize_style_allow_list():
    out = rt.sanitize('<p style="color: red; position: fixed; background-color: url(x)">x</p>')
    assert out == '<p style="color: red">x</p>'


def test_sanitize_mention_span_keeps_only_mention_attributes():
    out = rt.sanitize(
        '<span class="inline-chip" contenteditable="false" data-mention-id="U1" '
        'data-mention-name="Alex" data-mention-service="slack">@Alex</span>'
    )
    assert out == (
        '<span data-mention-id="U1" data-mention-name="Alex" data-mention-service="slack">@Alex</span>'
    )
    assert rt.sanitize('<span class="x">plain</span>') == "plain"


def test_sanitize_closes_open_tags_and_escapes_text():
    assert rt.sanitize("<p><b>a &amp; <c") == "<p><b>a &amp; &lt;c</b></p>"


# ── normalize ─────────────────────────────────────────────────────────────────


def test_normalize_prefers_body_html():
    assert rt.normalize(body="ignored", body_html="<p>kept</p>") == "<p>kept</p>"


def test_normalize_plain_text_keeps_paragraphs_and_line_breaks():
    assert rt.normalize("Hi Bob,\nthanks\n\nBye") == "<p>Hi Bob,<br>thanks</p><p>Bye</p>"


def test_normalize_escapes_plain_text():
    assert rt.normalize("a < b & c") == "<p>a &lt; b &amp; c</p>"


def test_normalize_markdown_inline():
    out = rt.normalize("**b** *i* `c` [l](https://x.com) ~~s~~")
    assert out == (
        '<p><strong>b</strong> <em>i</em> <code>c</code> <a href="https://x.com">l</a> <s>s</s></p>'
    )


def test_normalize_markdown_blocks():
    out = rt.normalize("# T\n\n- a\n- b\n\n1. x\n2. y\n\n> q\n\n```\n<b>\n```")
    assert out == (
        "<h1>T</h1><ul><li>a</li><li>b</li></ul><ol><li>x</li><li>y</li></ol>"
        "<blockquote>q</blockquote><pre>&lt;b&gt;</pre>"
    )


def test_normalize_html_looking_text_is_sanitized_not_escaped():
    assert rt.normalize("<div>hi<script>x</script></div>") == "<p>hi</p>"


def test_normalize_empty():
    assert rt.normalize("") == ""
    assert rt.normalize(None) == ""
