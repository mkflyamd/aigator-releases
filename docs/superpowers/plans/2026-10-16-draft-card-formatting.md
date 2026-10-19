# Draft Card Formatting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Draft approval cards carry, edit, and send formatted text for email, Teams, and Slack, and a future service needs one adapter and no card changes.

**Architecture:** One canonical sanitized-HTML body per draft, stored as `body_html` in the draft params and echoed in the card payload with `format_capabilities`. A new pure module `web/skills/_rich_text.py` sanitizes, normalizes, and renders that HTML through per-service adapters (email HTML fragment, Teams HTML with Skype mentions, Slack mrkdwn). The card uses one contenteditable rich editor with a capability-filtered toolbar and posts `edited_html`; the approve and open-in-Outlook routes fold the edit into the draft params and render through the adapter. The draft lifecycle (`claim_for_sending`, `claim_for_handoff`, `abort_handoff`, `complete_handoff`, `release_claim_for_retry`) is unchanged.

**Tech Stack:** Python 3.12 (stdlib `html.parser` only, no new dependencies), FastAPI, pytest (`pythonpath = web .`, `--import-mode=importlib`), vanilla JS in `web/static/app.js`, Node `vm` scripts for JS unit tests.

## Global Constraints

- Canonical body is HTML limited to `p br b strong i em u s a ul ol li code pre blockquote h1 h2 h3 table thead tbody tr th td` plus mention spans (`<span data-mention-id data-mention-name data-mention-service>`).
- Only `color`, `background-color`, `font-weight`, `font-style`, `text-decoration`, and `text-align` survive in `style`. Anything else is stripped.
- `href` is limited to `http`, `https`, `mailto`. Scripts, styles, and event attributes are dropped.
- No new dependencies. Use the stdlib `html.parser.HTMLParser`.
- Slack has no underline: the Slack adapter drops underline and its capabilities omit `underline`. The toolbar is built from `format_capabilities`.
- Headings and tables exist so LLM-authored `body_html` is not flattened. The card toolbar does not create them.
- Existing tool schemas stay valid. `edited_message` stays accepted and means plain text.
- No new routes. The existing CSRF dependencies stay (`dependencies=[Depends(verify_csrf)]` from `web/security.py`; every new POST/PUT/PATCH/DELETE route would need it, and `tests/csrf_route_baseline.txt` must not change).
- Human-in-the-loop is unchanged: email, Teams, and Slack messages NEVER auto-send. Draft-only; nothing sends without the user clicking Send or Open.
- All LLM calls go through `llm.gateway`. This plan adds none.
- The project is called **AI Gator**. Never refer to it as a POC.
- `aigator-fake-api-key` is the only fake credential in tests, examples, fixtures, and docs.
- Git commits must not contain `Co-Authored-By` lines. Stage files by explicit path.

---

## File Structure

| File                                                              | Responsibility                                                                                                                                                                             |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `web/skills/_rich_text.py` (create)                               | Pure functions: `sanitize`, `normalize`, `slack_to_html`, `teams_to_html`, `mention_span`, adapter registry (`ADAPTERS`, `service_for`, `capabilities`, `render`, `rich_payload`). No I/O. |
| `tests/test_rich_text.py` (create)                                | Unit tests for `sanitize` and `normalize`.                                                                                                                                                 |
| `tests/test_rich_text_adapters.py` (create)                       | Unit tests for the registry, the three adapters, `slack_to_html`, `teams_to_html`.                                                                                                         |
| `web/routes/drafts.py` (modify)                                   | `_fold_rich_edits`, `_email_fragment`, `_slack_text`; approve and open-in-Outlook paths render through adapters.                                                                           |
| `tests/test_draft_rich_email.py` (create)                         | Route tests for email approve and open-in-Outlook.                                                                                                                                         |
| `tests/test_draft_rich_chat.py` (create)                          | Route tests for Slack and Teams approve.                                                                                                                                                   |
| `web/skills/email/tools.py` (modify)                              | Reply, forward, and open-compose seed `body_html` and `format_capabilities`.                                                                                                               |
| `web/skills/slack/tools.py` (modify)                              | `_handle_slack_send_message` seeds `body_html` and `format_capabilities`.                                                                                                                  |
| `web/skills/teams/tools.py` (modify)                              | `_tool_teams_open_compose` seeds `body_html` and `format_capabilities`.                                                                                                                    |
| `tests/test_draft_rich_tools.py` (create)                         | Tool tests for the three seeding paths.                                                                                                                                                    |
| `web/static/app.js` (modify)                                      | Rich editor helpers, toolbar, card markup, approve and open-in-Outlook bodies.                                                                                                             |
| `web/static/style.css` (modify)                                   | Rich editor, toolbar, and link row styles.                                                                                                                                                 |
| `tests/draft_rich_editor.test.js` (create)                        | Node `vm` tests for the pure client helpers.                                                                                                                                               |
| `tests/test_hitl_draft_unification.py` (modify, lines ~1142-1143) | Source-string assertions follow the helper rename.                                                                                                                                         |

Plan order is bottom-up: module (Tasks 1-2), server (Tasks 3-4), tools (Task 5), client (Task 6), manual verification (Task 7). Every task leaves the existing suite green.

### Task 1: `_rich_text` sanitize and normalize

**Files:**

- Create: `web/skills/_rich_text.py`
- Test: `tests/test_rich_text.py`

**Interfaces:**

- Consumes: nothing.
- Produces (later tasks rely on these exact names):
  - `ALLOWED_TAGS: set[str]`
  - `sanitize(markup: str) -> str` — allow-list sanitizer; returns an HTML fragment.
  - `normalize(body: str = "", body_html: str = "") -> str` — canonical HTML. Sanitizes `body_html` if it is non-blank; otherwise converts HTML-looking text (sanitized), markdown, or plain text.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rich_text.py` with exactly this content:

````python
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
````

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_rich_text.py -q`
Expected: FAIL at collection with `ImportError: cannot import name '_rich_text' from 'skills'`.

- [ ] **Step 3: Write the implementation**

Create `web/skills/_rich_text.py` with exactly this content:

````python
"""Canonical rich-text model for draft approval cards.

Every draft carries one sanitized-HTML body. Per-service adapters turn it into
the native format (email HTML, Teams HTML with Skype mentions, Slack mrkdwn).
Pure functions, no I/O. A new service registers one Adapter in ADAPTERS.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

ALLOWED_TAGS = {
    "p", "br", "b", "strong", "i", "em", "u", "s", "a", "ul", "ol", "li",
    "code", "pre", "blockquote", "span", "h1", "h2", "h3",
    "table", "thead", "tbody", "tr", "th", "td",
}
_DROP_WITH_CONTENT = {"script", "style", "iframe", "object", "embed", "head", "title"}
_SAFE_SCHEMES = ("http://", "https://", "mailto:")
_STYLE_PROPS = {
    "color", "background-color", "font-weight", "font-style",
    "text-decoration", "text-align",
}
_STYLE_VALUE = re.compile(r"^[#\w\s%.,()-]+$")
_MENTION_ATTRS = ("data-mention-id", "data-mention-name", "data-mention-service")


def _safe_style(value: str) -> str:
    kept = []
    for decl in value.split(";"):
        prop, _, val = decl.partition(":")
        prop, val = prop.strip().lower(), val.strip()
        lowered = val.lower()
        if (
            prop in _STYLE_PROPS
            and _STYLE_VALUE.match(val)
            and "url(" not in lowered
            and "expression" not in lowered
        ):
            kept.append(f"{prop}: {val}")
    return "; ".join(kept)


def _attr(name: str, value: str) -> str:
    return f' {name}="{html.escape(value, quote=True)}"'


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[tuple[str, bool]] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _DROP_WITH_CONTENT:
            self.skip += 1
            return
        if self.skip:
            return
        tag = "p" if tag == "div" else tag
        if tag not in ALLOWED_TAGS:
            return
        attrs = dict(attrs)
        if tag == "br":
            self.out.append("<br>")
            return
        rendered = ""
        style = _safe_style(attrs.get("style") or "")
        if tag == "a":
            href = re.sub(r"[\x00-\x20]+", "", attrs.get("href") or "")
            if href.lower().startswith(_SAFE_SCHEMES):
                rendered += _attr("href", href)
        elif tag == "span":
            if attrs.get("data-mention-id"):
                for name in _MENTION_ATTRS:
                    if attrs.get(name):
                        rendered += _attr(name, attrs[name])
        elif tag in ("td", "th"):
            for name in ("colspan", "rowspan"):
                if (attrs.get(name) or "").isdigit():
                    rendered += _attr(name, attrs[name])
        if style:
            rendered += _attr("style", style)
        keep = not (tag == "span" and not rendered)
        if keep:
            self.out.append(f"<{tag}{rendered}>")
        self.stack.append((tag, keep))

    def handle_endtag(self, tag):
        if tag in _DROP_WITH_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        tag = "p" if tag == "div" else tag
        if tag not in [t for t, _ in self.stack]:
            return
        while self.stack:
            top, keep = self.stack.pop()
            if keep:
                self.out.append(f"</{top}>")
            if top == tag:
                break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html.escape(data, quote=False))

    def finish(self) -> str:
        self.close()
        while self.stack:
            top, keep = self.stack.pop()
            if keep:
                self.out.append(f"</{top}>")
        return "".join(self.out)


def sanitize(markup: str) -> str:
    """Allow-list HTML: known tags, safe hrefs, mention data attributes, safe styles."""
    parser = _Sanitizer()
    parser.feed(markup or "")
    return parser.finish()


# ── plain text / markdown -> canonical HTML ────────────────────────────────────

_LOOKS_LIKE_HTML = re.compile(
    r"</?(?:p|br|div|span|b|strong|i|em|u|s|a|ul|ol|li|table|tr|td|th|"
    r"h[1-6]|pre|code|blockquote|html|body)\b",
    re.IGNORECASE,
)


def _inline(text: str, mrkdwn: bool = False) -> str:
    s = html.escape(text, quote=False)
    codes: list[str] = []

    def stash(m):
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    s = re.sub(r"`([^`\n]+)`", stash, s)
    s = re.sub(
        r"\[([^\]\n]+)\]\(((?:https?://|mailto:)[^\s)]+)\)", r'<a href="\2">\1</a>', s
    )
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    if mrkdwn:
        s = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<![\w~])~(?!\s)([^~\n]+?)(?<!\s)~(?![\w~])", r"<s>\1</s>", s)
    else:
        s = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"(?<!\w)_(?!\s)([^_\n]+?)(?<!\s)_(?!\w)", r"<em>\1</em>", s)
    s = re.sub(r"~~(.+?)~~", r"<s>\1</s>", s)
    return re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{codes[int(m.group(1))]}</code>", s)


_UL = re.compile(r"^\s*[-*+]\s+(.*)$")
_OL = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")


def _markdown_to_html(text: str, mrkdwn: bool = False) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            out.append("<p>" + "<br>".join(_inline(l, mrkdwn) for l in para) + "</p>")
            para.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            flush()
            i += 1
            code: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            out.append("<pre>" + html.escape("\n".join(code), quote=False) + "</pre>")
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2), mrkdwn)}</h{level}>")
            i += 1
            continue
        for pattern, tag in ((_UL, "ul"), (_OL, "ol")):
            if pattern.match(line):
                flush()
                items = []
                while i < len(lines) and pattern.match(lines[i]):
                    items.append(pattern.match(lines[i]).group(1))
                    i += 1
                out.append(
                    f"<{tag}>" + "".join(f"<li>{_inline(x, mrkdwn)}</li>" for x in items) + f"</{tag}>"
                )
                break
        else:
            if _QUOTE.match(line):
                flush()
                quoted = []
                while i < len(lines) and _QUOTE.match(lines[i]):
                    quoted.append(_QUOTE.match(lines[i]).group(1))
                    i += 1
                out.append(
                    "<blockquote>" + "<br>".join(_inline(x, mrkdwn) for x in quoted) + "</blockquote>"
                )
            elif not line.strip():
                flush()
                i += 1
            else:
                para.append(line)
                i += 1
            continue
    flush()
    return "".join(out)


def normalize(body: str = "", body_html: str = "") -> str:
    """Canonical HTML from body_html, else HTML-looking text, else markdown/plain text."""
    if body_html and body_html.strip():
        return sanitize(body_html)
    text = (body or "").replace("\x00", "").replace("\x01", "")
    outside_code = re.sub(r"```.*?```|`[^`\n]*`", "", text, flags=re.DOTALL)
    if _LOOKS_LIKE_HTML.search(outside_code):
        return sanitize(text)
    return sanitize(_markdown_to_html(text))
````

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_rich_text.py -q`
Expected: `16 passed`.

- [ ] **Step 5: Commit**

```bash
git add web/skills/_rich_text.py tests/test_rich_text.py
git commit -m "feat: add canonical rich-text sanitizer and normalizer for draft cards"
```

---

### Task 2: `_rich_text` mentions, adapters, and registry

**Files:**

- Modify: `web/skills/_rich_text.py` (imports at the top, then append to the end of the file)
- Test: `tests/test_rich_text_adapters.py`

**Interfaces:**

- Consumes (from Task 1): `sanitize`, `_LOOKS_LIKE_HTML`, `_markdown_to_html` are defined in the same module and used by the appended code.
- Produces:
  - `mention_span(mention_id: str, name: str, service: str) -> str`
  - `slack_to_html(message: str, names: dict[str, str] | None = None) -> str` — lifts Slack mrkdwn (`<@U1>`, `<!here>`, `<url|label>`, `*b*`, `_i_`, `~s~`) into canonical HTML.
  - `teams_to_html(message: str, mentions: list[dict] | None = None) -> str` — lifts a Teams message (plain text or HTML with Skype mention spans) into canonical HTML.
  - `@dataclass Rendered(content: str, mentions: list[dict])`
  - `@dataclass Adapter(capabilities: tuple[str, ...], render: Callable[[str], Rendered])`
  - `ADAPTERS: dict[str, Adapter]` keyed `"email"`, `"teams"`, `"slack"`
  - `DRAFT_SERVICES: dict[str, str]` mapping draft type to service
  - `service_for(draft_type: str) -> str` (`""` for unsupported types)
  - `capabilities(service: str) -> list[str]` (`[]` for unknown services)
  - `render(service: str, markup: str) -> Rendered`
  - `rich_payload(service: str, body_html: str) -> dict` returning `{"body_html": ..., "format_capabilities": [...]}`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rich_text_adapters.py` with exactly this content:

````python
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
````

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_rich_text_adapters.py -q`
Expected: FAIL with `AttributeError: module 'skills._rich_text' has no attribute 'service_for'` (and similar for the other new names).

- [ ] **Step 3: Restore the imports used by the appended code**

In `web/skills/_rich_text.py`, replace the import block

```python
import html
import re
from html.parser import HTMLParser
```

with

```python
import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Callable
```

- [ ] **Step 4: Append the adapters**

Append this to the end of `web/skills/_rich_text.py` (keep one blank line between the existing last line and the new `# ── mentions` header):

````python
# ── mentions ───────────────────────────────────────────────────────────────────


def mention_span(mention_id: str, name: str, service: str) -> str:
    prefix = "#" if mention_id.startswith("#") else "@"
    return (
        f'<span data-mention-id="{html.escape(mention_id, quote=True)}"'
        f' data-mention-name="{html.escape(name, quote=True)}"'
        f' data-mention-service="{html.escape(service, quote=True)}">'
        f"{prefix}{html.escape(name, quote=False)}</span>"
    )


_SLACK_TOKEN = re.compile(
    r"<(@[UW][A-Z0-9]+|!(?:here|channel|everyone)|#C[A-Z0-9]+)(?:\|([^>]*))?>"
)
_SLACK_LINK = re.compile(r"<((?:https?://|mailto:)[^|>\s]+)(?:\|([^>]+))?>")


def slack_to_html(message: str, names: dict[str, str] | None = None) -> str:
    """Canonical HTML for a Slack mrkdwn message (keeps <@U..>, <!here>, <#C..>, <url|label>)."""
    names = names or {}
    text = (message or "").replace("\x00", "").replace("\x01", "")
    text = _SLACK_LINK.sub(lambda m: f"[{m.group(2) or m.group(1)}]({m.group(1)})", text)
    text = _SLACK_TOKEN.sub(
        lambda m: f"\x01{m.group(1)}|{m.group(2) or ''}\x01", text
    )
    markup = _markdown_to_html(text, mrkdwn=True)

    def restore(m):
        token, label = m.group(1), m.group(2)
        if token.startswith("@"):
            uid = token[1:]
            return mention_span(uid, label or names.get(uid, uid), "slack")
        if token.startswith("!"):
            return mention_span(token, token[1:], "slack")
        return mention_span(token, label or token[1:], "slack")

    markup = re.sub(r"\x01([^|\x01]+)\|([^\x01]*)\x01", restore, markup)
    return sanitize(markup)


_SKYPE_SPAN = re.compile(
    r'<span[^>]*itemtype="http://schema\.skype\.com/Mention"[^>]*itemid="(\d+)"[^>]*>(.*?)</span>',
    re.IGNORECASE | re.DOTALL,
)


def teams_to_html(message: str, mentions: list[dict] | None = None) -> str:
    """Canonical HTML for a Teams message whose mentions are Skype spans plus a mentions list."""
    by_id = {str(m.get("id")): m for m in (mentions or [])}
    spans: list[str] = []

    def swap(m):
        mention = by_id.get(m.group(1))
        if not mention:
            spans.append(html.escape(html.unescape(re.sub(r"<[^>]+>", "", m.group(2)))))
        else:
            user = (mention.get("mentioned") or {}).get("user") or {}
            name = mention.get("mentionText") or user.get("displayName") or ""
            spans.append(mention_span(user.get("id", ""), name, "teams"))
        return f"\x01{len(spans) - 1}\x01"

    text = _SKYPE_SPAN.sub(swap, (message or "").replace("\x01", "").replace("\x00", ""))
    if _LOOKS_LIKE_HTML.search(text):
        markup = text
    else:
        paragraphs = [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
        markup = "".join("<p>" + html.escape(p).replace("\n", "<br>") + "</p>" for p in paragraphs)
    return sanitize(re.sub(r"\x01(\d+)\x01", lambda m: spans[int(m.group(1))], markup))


# ── adapters ───────────────────────────────────────────────────────────────────


@dataclass
class Rendered:
    content: str
    mentions: list[dict] = field(default_factory=list)


@dataclass
class Adapter:
    capabilities: tuple[str, ...]
    render: Callable[[str], Rendered]


_MENTION_SPAN = re.compile(
    r"<span[^>]*data-mention-id=\"([^\"]*)\"[^>]*data-mention-name=\"([^\"]*)\"[^>]*>.*?</span>",
    re.DOTALL,
)


def _mention_parts(match) -> tuple[str, str]:
    return html.unescape(match.group(1)), html.unescape(match.group(2))


def _render_email(markup: str) -> Rendered:
    def plain(m):
        _, name = _mention_parts(m)
        return html.escape(("#" if m.group(1).startswith("#") else "@") + name, quote=False)

    return Rendered(_MENTION_SPAN.sub(plain, markup))


def _render_teams(markup: str) -> Rendered:
    mentions: list[dict] = []

    def skype(m):
        user_id, name = _mention_parts(m)
        if not user_id or user_id[0] in "!#":
            return _render_email(m.group(0)).content
        itemid = len(mentions)
        mentions.append(
            {
                "id": itemid,
                "mentionText": name,
                "mentioned": {"user": {"id": user_id, "displayName": name, "userIdentityType": "aadUser"}},
            }
        )
        return (
            f'<span itemscope itemtype="http://schema.skype.com/Mention" '
            f'itemid="{itemid}">{html.escape(name, quote=False)}</span>'
        )

    content = _MENTION_SPAN.sub(skype, markup)
    content = re.sub(r"<p(\s[^>]*)?>", lambda m: f"<div{m.group(1) or ''}>", content)
    content = content.replace("</p>", "</div>")
    return Rendered(content, mentions)


class _Mrkdwn(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.nl = 2
        self.lists: list[list] = []
        self.links: list[tuple[str, int]] = []
        self.quote = 0
        self.pre = 0
        self.skip = 0
        self.cell = 0

    def _w(self, text: str) -> None:
        if not text:
            return
        body = text.rstrip("\n")
        if body and self.nl and self.quote:
            self.out.append("> ")
        self.out.append(text)
        self.nl = self.nl + len(text) if not body else len(text) - len(body)

    def _break(self, n: int) -> None:
        if self.nl < n:
            self.out.append("\n" * (n - self.nl))
            self.nl = n

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.skip:
            self.skip += 1
            return
        if tag == "span" and attrs.get("data-mention-id"):
            mention_id = attrs["data-mention-id"]
            self._w(f"<@{mention_id}>" if mention_id[0] in "UW" else f"<{mention_id}>")
            self.skip = 1
        elif tag in ("p", "div", "h1", "h2", "h3"):
            self._break(2)
            if tag.startswith("h"):
                self._w("*")
        elif tag == "br":
            self._w("\n")
        elif tag in ("b", "strong"):
            self._w("*")
        elif tag in ("i", "em"):
            self._w("_")
        elif tag in ("s", "strike", "del"):
            self._w("~")
        elif tag == "code" and not self.pre:
            self._w("`")
        elif tag == "pre":
            self._break(2)
            self._w("```\n")
            self.pre += 1
        elif tag == "a":
            self.links.append((attrs.get("href") or "", len(self.out)))
        elif tag in ("ul", "ol"):
            self._break(1 if self.lists else 2)
            self.lists.append([tag, 0])
        elif tag == "li" and self.lists:
            self._break(1)
            kind = self.lists[-1]
            kind[1] += 1
            self._w("  " * (len(self.lists) - 1) + ("• " if kind[0] == "ul" else f"{kind[1]}. "))
        elif tag == "blockquote":
            self._break(2)
            self.quote += 1
        elif tag == "tr":
            self._break(1)
            self.cell = 0
        elif tag in ("td", "th"):
            if self.cell:
                self._w(" | ")
            self.cell += 1

    def handle_endtag(self, tag):
        if self.skip:
            self.skip -= 1
            return
        if tag in ("p", "div"):
            self._break(2)
        elif tag in ("h1", "h2", "h3"):
            self._w("*")
            self._break(2)
        elif tag in ("b", "strong"):
            self._w("*")
        elif tag in ("i", "em"):
            self._w("_")
        elif tag in ("s", "strike", "del"):
            self._w("~")
        elif tag == "code" and not self.pre:
            self._w("`")
        elif tag == "pre" and self.pre:
            self._break(1)
            self._w("```")
            self.pre -= 1
            self._break(2)
        elif tag == "a" and self.links:
            href, start = self.links.pop()
            label = "".join(self.out[start:])
            del self.out[start:]
            if href and label.strip() and label != href:
                self.out.append(f"<{href}|{label}>")
            elif href:
                self.out.append(f"<{href}>")
            else:
                self.out.append(label)
        elif tag in ("ul", "ol") and self.lists:
            self.lists.pop()
            self._break(1 if self.lists else 2)
        elif tag == "blockquote":
            self.quote = max(0, self.quote - 1)
            self._break(2)

    def handle_data(self, data):
        if self.skip:
            return
        text = data if self.pre else re.sub(r"\s*\n\s*", " ", data)
        self._w(text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    def result(self) -> str:
        self.close()
        return "".join(self.out).strip("\n")


def _render_slack(markup: str) -> Rendered:
    parser = _Mrkdwn()
    parser.feed(markup)
    return Rendered(parser.result())


_ALL = ("bold", "italic", "underline", "ul", "ol", "link", "code")

ADAPTERS: dict[str, Adapter] = {
    "email": Adapter(_ALL, _render_email),
    "teams": Adapter(_ALL, _render_teams),
    "slack": Adapter(tuple(c for c in _ALL if c != "underline"), _render_slack),
}

DRAFT_SERVICES: dict[str, str] = {
    "email-send": "email",
    "email-reply": "email",
    "email-forward": "email",
    "teams-message": "teams",
    "slack-post": "slack",
    "slack-dm": "slack",
}


def service_for(draft_type: str) -> str:
    return DRAFT_SERVICES.get(draft_type, "")


def capabilities(service: str) -> list[str]:
    adapter = ADAPTERS.get(service)
    return list(adapter.capabilities) if adapter else []


def render(service: str, markup: str) -> Rendered:
    return ADAPTERS[service].render(markup)


def rich_payload(service: str, body_html: str) -> dict:
    """Fields every draft tool adds to both the stored params and the card data."""
    return {"body_html": body_html, "format_capabilities": capabilities(service)}
````

- [ ] **Step 5: Run all rich-text tests to verify they pass**

Run: `python -m pytest tests/test_rich_text.py tests/test_rich_text_adapters.py -q`
Expected: `30 passed`.

- [ ] **Step 6: Commit**

```bash
git add web/skills/_rich_text.py tests/test_rich_text_adapters.py
git commit -m "feat: add Slack, Teams, and email adapters for the rich-text draft model"
```

---

### Task 3: Email approve and open-in-Outlook render through the adapter

**Files:**

- Modify: `web/routes/drafts.py` (helpers after `_run_sync` at line 34; `approve_draft` lines ~215-316; `open_draft_in_outlook` lines ~929-1025)
- Test: `tests/test_draft_rich_email.py`

**Interfaces:**

- Consumes (Tasks 1-2): `skills._rich_text.sanitize(markup) -> str`, `normalize(body="", body_html="") -> str`, `service_for(draft_type) -> str`, `render(service, markup) -> Rendered` (`.content`).
- Produces (Task 4 reuses the first):
  - `_fold_rich_edits(draft_type: str, params: dict, body: dict | None) -> None` — no-op unless `service_for(draft_type)` is non-empty and `body` is truthy. If `body["edited_html"]` is a string: sets `params["body_html"] = sanitize(edited_html)` and blanks any of `body`/`message`/`comment` present in `params`. Else if `"edited_message"` is in `body`: drops `params["body_html"]` so the plain edit wins.
  - `_email_fragment(params: dict, plain_key: str) -> str` — the email HTML fragment for `params`: `render("email", normalize(body=params.get(plain_key) or "", body_html=params.get("body_html") or "")).content`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_draft_rich_email.py`:

```python
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import app
from skills import _drafts


def setup_function(function):
    _drafts._pending_drafts.clear()


def _post(client, draft_id, action, body=None):
    from security import get_csrf_token

    return client.post(
        f"/api/drafts/{draft_id}/{action}",
        headers={"X-CSRF-Token": get_csrf_token("testserver")},
        json=body,
    )


def _gc():
    gc = MagicMock()
    gc.post.return_value = {"id": "NEWID"}
    gc.get.return_value = {"body": {"content": "<p>quoted</p>"}}
    return gc


def _sent_content(gc):
    call = next(c for c in gc.post.call_args_list if c.args[0] == "/me/sendMail")
    return call.args[1]["message"]["body"]["content"]


def _email_send(**extra):
    params = {"to": "bob@amd.com", "subject": "S", "body": "stale", "body_html": "<p>stale</p>"}
    params.update(extra)
    return _drafts.create_draft("email-send", params, {})


def test_send_with_edited_html_keeps_formatting():
    gc = _gc()
    did = _email_send()
    with patch("skills._m365.helpers.get_graph_client", return_value=gc):
        r = _post(TestClient(app), did, "approve", {"edited_html": "<p><b>Bold</b> text</p>"})
    assert r.status_code == 200, r.text
    content = _sent_content(gc)
    assert content.startswith("<!DOCTYPE html>")
    assert "<p><b>Bold</b> text</p>" in content
    assert "stale" not in content


def test_send_sanitizes_edited_html():
    gc = _gc()
    did = _email_send()
    edited = '<p onclick="x()">Hi</p><script>alert(1)</script>'
    with patch("skills._m365.helpers.get_graph_client", return_value=gc):
        r = _post(TestClient(app), did, "approve", {"edited_html": edited})
    assert r.status_code == 200, r.text
    content = _sent_content(gc)
    assert "<p>Hi</p>" in content
    assert "onclick" not in content and "script" not in content


def test_send_plain_edited_message_keeps_line_breaks():
    gc = _gc()
    did = _email_send()
    with patch("skills._m365.helpers.get_graph_client", return_value=gc):
        r = _post(TestClient(app), did, "approve", {"edited_message": "Line one\nLine two"})
    assert r.status_code == 200, r.text
    content = _sent_content(gc)
    assert "<p>Line one<br>Line two</p>" in content
    assert "stale" not in content


def test_send_without_edit_uses_stored_body_html():
    gc = _gc()
    did = _email_send(body="plain", body_html="<p><i>kept</i></p>")
    with patch("skills._m365.helpers.get_graph_client", return_value=gc):
        r = _post(TestClient(app), did, "approve")
    assert r.status_code == 200, r.text
    assert "<p><i>kept</i></p>" in _sent_content(gc)


def test_send_cleared_editor_does_not_resurrect_stale_text():
    gc = _gc()
    did = _email_send()
    with patch("skills._m365.helpers.get_graph_client", return_value=gc):
        r = _post(TestClient(app), did, "approve", {"edited_html": ""})
    assert r.status_code == 200, r.text
    content = _sent_content(gc)
    assert "<body></body>" in content
    assert "stale" not in content


def test_reply_approve_uses_edited_html():
    gc = _gc()
    did = _drafts.create_draft(
        "email-reply",
        {"message_id": "AAMk1", "body": "old", "body_html": "<p>old</p>", "reply_all": False},
        {},
    )
    with patch("skills._m365.helpers.get_graph_client", return_value=gc):
        r = _post(TestClient(app), did, "approve", {"edited_html": "<p><b>Hi</b></p>"})
    assert r.status_code == 200, r.text
    assert gc.patch.call_args.args[1]["body"]["content"] == "<p><b>Hi</b></p><p>quoted</p>"


def test_forward_approve_uses_edited_html():
    gc = _gc()
    did = _drafts.create_draft(
        "email-forward",
        {"message_id": "AAMk1", "to": "bob@amd.com", "comment": "old", "body_html": "<p>old</p>"},
        {},
    )
    with patch("skills._m365.helpers.get_graph_client", return_value=gc):
        r = _post(TestClient(app), did, "approve", {"edited_html": "<p><u>FYI</u></p>"})
    assert r.status_code == 200, r.text
    assert gc.patch.call_args.args[1]["body"]["content"] == "<p><u>FYI</u></p><p>quoted</p>"


def test_open_in_outlook_email_send_posts_bare_fragment():
    gc = _gc()
    did = _email_send()
    with patch("skills._m365.helpers.get_graph_client", return_value=gc):
        r = _post(TestClient(app), did, "open-in-outlook", {"edited_html": "<p><b>Bold</b> text</p>"})
    assert r.status_code == 200, r.text
    created = next(c for c in gc.post.call_args_list if c.args[0] == "/me/messages")
    assert created.args[1]["body"]["content"] == "<p><b>Bold</b> text</p>"


def test_open_in_outlook_reply_uses_edited_html():
    gc = _gc()
    did = _drafts.create_draft(
        "email-reply",
        {"message_id": "AAMk1", "body": "old", "body_html": "<p>old</p>", "reply_all": False},
        {},
    )
    with patch("skills._m365.helpers.get_graph_client", return_value=gc):
        r = _post(TestClient(app), did, "open-in-outlook", {"edited_html": "<p><b>Hi</b></p>"})
    assert r.status_code == 200, r.text
    assert gc.patch.call_args.args[1]["body"]["content"] == "<p><b>Hi</b></p><p>quoted</p>"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_draft_rich_email.py -q`
Expected: FAIL. `edited_html` is ignored today, so assertions such as `"<p><b>Bold</b> text</p>" in content` fail.

- [ ] **Step 3: Add the two helpers to `web/routes/drafts.py`**

Insert directly after the last line of `_run_sync` (`    return await asyncio.to_thread(partial(fn, *args, **kwargs))`, line 34), leaving two blank lines before the next section:

```python


def _fold_rich_edits(draft_type: str, params: dict, body: dict | None) -> None:
    from skills import _rich_text as rich

    if not body or not rich.service_for(draft_type):
        return
    edited_html = body.get("edited_html")
    if isinstance(edited_html, str):
        params["body_html"] = rich.sanitize(edited_html)
        for key in ("body", "message", "comment"):
            if key in params:
                params[key] = ""
    elif "edited_message" in body:
        params.pop("body_html", None)


def _email_fragment(params: dict, plain_key: str) -> str:
    from skills import _rich_text as rich

    markup = rich.normalize(
        body=params.get(plain_key) or "", body_html=params.get("body_html") or ""
    )
    return rich.render("email", markup).content
```

- [ ] **Step 4: Rewire `approve_draft` (email branches)**

4a. After the `mentions` assignment, insert the fold call. Before:

```python
    if body and isinstance(body.get("mentions"), list):
        draft["params"]["mentions"] = body["mentions"]

    delivery_result: dict | None = None
```

After:

```python
    if body and isinstance(body.get("mentions"), list):
        draft["params"]["mentions"] = body["mentions"]
    _fold_rich_edits(draft["type"], draft["params"], body)

    delivery_result: dict | None = None
```

Do not touch the `edited_message` mapping above it: `web/tests/test_teams_pane_config.py` requires `draft["params"]["message"] = body["edited_message"]` to appear before `dtype = draft["type"]`.

4b. `email-reply` branch: delete the line `            import html as _html` (line 227, between `from skills._m365.helpers import get_graph_client` and `gc = get_graph_client()`), then replace

```python
            body_html = p["body"]
            if "<" not in body_html:
                body_html = _html.escape(body_html).replace("\n", "<br>")
            quoted = (
```

with

```python
            body_html = _email_fragment(p, "body")
            quoted = (
```

4c. `email-forward` branch: delete the line `            import html as _html` (line 259, the one directly above `gc = get_graph_client()` in that branch), then replace

```python
            if p.get("comment"):
                comment_html = p["comment"]
                if "<" not in comment_html:
                    comment_html = _html.escape(comment_html).replace("\n", "<br>")
                forwarded = (
```

with

```python
            comment_html = _email_fragment(p, "comment")
            if comment_html:
                forwarded = (
```

4d. `email-send` branch: replace

```python
            edited = p.get("message")
            body_content = edited if edited is not None else (p.get("body_html") or p.get("body") or "")
            to_addrs = [a.strip() for a in p.get("to", "").split(",") if a.strip()]
            if not to_addrs:
                raise HTTPException(status_code=400, detail="No recipients specified")
            if "<html" not in body_content.lower():
                body_content = (
                    "<!DOCTYPE html><html><head>"
                    '<meta http-equiv="Content-Type" content="text/html; charset=utf-8">'
                    "</head><body>" + body_content + "</body></html>"
                )
```

with

```python
            body_content = _email_fragment(p, "message" if "message" in p else "body")
            to_addrs = [a.strip() for a in p.get("to", "").split(",") if a.strip()]
            if not to_addrs:
                raise HTTPException(status_code=400, detail="No recipients specified")
            body_content = (
                "<!DOCTYPE html><html><head>"
                '<meta http-equiv="Content-Type" content="text/html; charset=utf-8">'
                "</head><body>" + body_content + "</body></html>"
            )
```

- [ ] **Step 5: Rewire `open_draft_in_outlook`**

5a. Delete the line `    import html as _html` (line 929, directly above `from skills._drafts import get_draft, claim_for_handoff, abort_handoff, complete_handoff`).

5b. After the `edited_message` mapping on `p`, insert the fold call. Before:

```python
        else:
            p["message"] = body["edited_message"]

    try:
        from skills._m365.helpers import get_graph_client

        gc = get_graph_client()

        if dtype == "email-send":
```

After:

```python
        else:
            p["message"] = body["edited_message"]
    _fold_rich_edits(dtype, p, body)

    try:
        from skills._m365.helpers import get_graph_client

        gc = get_graph_client()

        if dtype == "email-send":
```

5c. `email-send` in `open_draft_in_outlook`: replace

```python
            edited = p.get("message")
            body_content = edited if edited is not None else (p.get("body_html") or p.get("body") or "")
            if "<" not in body_content:
                body_content = _html.escape(body_content).replace("\n", "<br>")
            msg: dict = {
```

with

```python
            body_content = _email_fragment(p, "message" if "message" in p else "body")
            msg: dict = {
```

5d. Reply in `open_draft_in_outlook`: replace

```python
            body_html = p.get("body", "")
            if "<" not in body_html:
                body_html = _html.escape(body_html).replace("\n", "<br>")
            quoted = (gc.get(
```

with

```python
            body_html = _email_fragment(p, "body")
            quoted = (gc.get(
```

(the `quoted = (gc.get(...` line continues unchanged; only replace the three lines above it).

5e. Forward in `open_draft_in_outlook`: replace

```python
            if p.get("comment"):
                comment_html = p["comment"]
                if "<" not in comment_html:
                    comment_html = _html.escape(comment_html).replace("\n", "<br>")
                forwarded = (gc.get(
```

with

```python
            comment_html = _email_fragment(p, "comment")
            if comment_html:
                forwarded = (gc.get(
```

(again the rest of that line and the `update["body"] = ...` line stay as they are).

5f. Confirm nothing references `_html` any more: `grep -n "_html\b" web/routes/drafts.py` should show only `body_html`, `comment_html`, `edited_html` style names, never `_html.escape`.

- [ ] **Step 6: Run the new tests and the baseline**

Run: `python -m pytest tests/test_draft_rich_email.py -q`
Expected: `9 passed`.

Run: `python -m pytest tests/test_hitl_draft_unification.py tests/test_drafts_pr10.py web/tests/test_teams_pane_config.py web/tests/test_outlook_native_hitl.py web/tests/test_teams_message_approve_send.py web/tests/test_slack_pinned_draft_context.py -q`
Expected: all pass (126 before this plan). If a legacy test expects the old `<html` passthrough or the old unwrapped-text behavior, fix the implementation, not the test, unless the old behavior was the stale-text/lost-newline bug this task removes; in that case report which assertion and why before editing it.

- [ ] **Step 7: Commit**

```bash
git add web/routes/drafts.py tests/test_draft_rich_email.py
git commit -m "feat: send and open email drafts with the formatting the user edited"
```

---

### Task 4: Slack and Teams approve render through the adapter

**Files:**

- Modify: `web/routes/drafts.py` (new `_slack_text` helper next to `_email_fragment`; `slack-post` at ~line 341; `slack-dm` at ~line 363; `teams-message` at ~lines 369-380 in `approve_draft`)
- Test: `tests/test_draft_rich_chat.py`

**Interfaces:**

- Consumes (Tasks 1-3): `skills._rich_text.render(service, markup) -> Rendered` with `.content: str` and `.mentions: list[dict]`; `_fold_rich_edits` is already called in `approve_draft` (Task 3, step 4a), so `params["body_html"]` is already the sanitized edit by the time a branch runs.
- Produces:
  - `_slack_text(params: dict) -> str` — mrkdwn from `params["body_html"]` if present, else `params.get("message", "")`.
  - Teams sends `TeamsSendMessageRequest(message=<adapter HTML>, html=True, mentions=<adapter mentions>)` when `params["body_html"]` is present; otherwise the legacy fields are used unchanged.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_draft_rich_chat.py`:

```python
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from unittest.mock import patch

from fastapi.testclient import TestClient

from app import app
from skills import _drafts

MENTION = (
    '<span data-mention-id="{id}" data-mention-name="{name}" '
    'data-mention-service="{svc}">@{name}</span>'
)


def setup_function(function):
    _drafts._pending_drafts.clear()


def _approve(client, draft_id, body=None):
    from security import get_csrf_token

    return client.post(
        f"/api/drafts/{draft_id}/approve",
        headers={"X-CSRF-Token": get_csrf_token("testserver")},
        json=body,
    )


def _slack_api(posted):
    def api(api_method, params, method="GET"):
        if api_method == "conversations.info":
            return {"ok": True, "channel": {"id": "C1"}}
        if api_method == "conversations.open":
            return {"ok": True, "channel": {"id": "D1"}}
        if api_method == "chat.postMessage":
            posted.append(params)
            return {"ok": True, "ts": "1.2"}
        raise AssertionError(api_method)

    return api


def _send_slack(draft_type, params, body):
    posted: list[dict] = []
    did = _drafts.create_draft(draft_type, params, {})
    with patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T1"}), patch(
        "routes.slack._slack_web_api", side_effect=_slack_api(posted)
    ):
        r = _approve(TestClient(app), did, body)
    assert r.status_code == 200, r.text
    return posted[0]["text"]


POST = {"channel_id": "C1", "team_id": "T1", "message": "old", "body_html": "<p>old</p>"}
DM = {"user_id": "U9", "team_id": "T1", "message": "old", "body_html": "<p>old</p>"}
EDIT = (
    "<p><strong>Ship</strong> it "
    + MENTION.format(id="U1", name="Alex", svc="slack")
    + "</p>"
)


def test_slack_post_sends_mrkdwn_from_edited_html():
    assert _send_slack("slack-post", dict(POST), {"edited_html": EDIT}) == "*Ship* it <@U1>"


def test_slack_dm_sends_mrkdwn_from_edited_html():
    assert _send_slack("slack-dm", dict(DM), {"edited_html": EDIT}) == "*Ship* it <@U1>"


def test_slack_stored_body_html_is_rendered_without_edit():
    params = dict(POST, body_html="<p><strong>hi</strong></p>")
    assert _send_slack("slack-post", params, None) == "*hi*"


def test_slack_plain_edited_message_wins_over_stale_body_html():
    params = dict(POST, body_html="<p><strong>stale</strong></p>")
    assert _send_slack("slack-post", params, {"edited_message": "plain edit"}) == "plain edit"


def test_slack_legacy_draft_without_body_html_still_sends_message():
    assert _send_slack("slack-post", {"channel_id": "C1", "team_id": "T1", "message": "hi"}, None) == "hi"


def _send_teams(params, body):
    did = _drafts.create_draft("teams-message", params, {})
    with patch("routes.teams.tp_teams_send_message", return_value={"ok": True}) as send:
        r = _approve(TestClient(app), did, body)
    assert r.status_code == 200, r.text
    return send.call_args.args[0]


TEAMS = {
    "to": "bob@amd.com",
    "message": "old",
    "chat_id": "19:abc@thread.v2",
    "recipients": [],
    "mentions": [],
    "body_html": "<p>old</p>",
}
TEAMS_EDIT = (
    "<p><b>Hi</b> "
    + MENTION.format(id="AAD1", name="Alex", svc="teams")
    + '</p><script>alert(1)</script>'
)


def test_teams_edited_html_sends_html_with_skype_mentions():
    req = _send_teams(dict(TEAMS), {"edited_html": TEAMS_EDIT})
    assert req.html is True
    assert 'itemtype="http://schema.skype.com/Mention"' in req.message
    assert "<b>Hi</b>" in req.message
    assert "<script" not in req.message
    assert req.mentions[0]["mentioned"]["user"]["id"] == "AAD1"


def test_teams_stored_body_html_renders_without_edit():
    params = dict(TEAMS, body_html="<p>Hi " + MENTION.format(id="AAD1", name="Alex", svc="teams") + "</p>")
    req = _send_teams(params, None)
    assert req.html is True
    assert req.mentions[0]["mentioned"]["user"]["id"] == "AAD1"


def test_teams_legacy_draft_without_body_html_is_unchanged():
    legacy = {k: v for k, v in TEAMS.items() if k != "body_html"}
    req = _send_teams(legacy, None)
    assert req.message == "old"
    assert req.html is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_draft_rich_chat.py -q`
Expected: FAIL. Slack posts `"old"` instead of mrkdwn, and Teams sends `req.html is False`.

- [ ] **Step 3: Add `_slack_text` to `web/routes/drafts.py`**

Insert directly after `_email_fragment` (added in Task 3):

```python


def _slack_text(params: dict) -> str:
    from skills import _rich_text as rich

    if params.get("body_html"):
        return rich.render("slack", params["body_html"]).content
    return params.get("message", "")
```

- [ ] **Step 4: Use it in the Slack and Teams branches of `approve_draft`**

4a. `slack-post`: replace

```python
            payload = {"channel": p["channel_id"], "text": p["message"]}
```

with

```python
            payload = {"channel": p["channel_id"], "text": _slack_text(p)}
```

4b. `slack-dm`: replace

```python
            data = _slack_web_api("chat.postMessage", {"channel": dm_channel_id, "text": p["message"]}, method="POST")
```

with

```python
            data = _slack_web_api("chat.postMessage", {"channel": dm_channel_id, "text": _slack_text(p)}, method="POST")
```

4c. `teams-message`: replace

```python
            send_req = TeamsSendMessageRequest(
                to=p.get("to", ""),
                message=p.get("message", ""),
                html=p.get("html", False),
                chat_id=p.get("chat_id", ""),
                recipients=p.get("recipients", []),
                mentions=p.get("mentions", []),
            )
```

with

```python
            if p.get("body_html"):
                from skills import _rich_text as rich

                rendered = rich.render("teams", p["body_html"])
                message, html_flag, mentions = rendered.content, True, rendered.mentions
            else:
                message, html_flag, mentions = p.get("message", ""), p.get("html", False), p.get("mentions", [])
            send_req = TeamsSendMessageRequest(
                to=p.get("to", ""),
                message=message,
                html=html_flag,
                chat_id=p.get("chat_id", ""),
                recipients=p.get("recipients", []),
                mentions=mentions,
            )
```

Leave the following `delivery_result = await tp_teams_send_message(send_req)` line as is.

- [ ] **Step 5: Run the new tests and the baseline**

Run: `python -m pytest tests/test_draft_rich_chat.py tests/test_draft_rich_email.py -q`
Expected: `17 passed` (9 email + 8 chat).

Run: `python -m pytest tests/test_hitl_draft_unification.py tests/test_drafts_pr10.py web/tests/test_teams_pane_config.py web/tests/test_outlook_native_hitl.py web/tests/test_teams_message_approve_send.py web/tests/test_slack_pinned_draft_context.py -q`
Expected: all pass. `web/tests/test_teams_message_approve_send.py` drafts have no `body_html`, so they take the legacy branch and must still see `sent_req.message == "Fireworks update text"`.

- [ ] **Step 6: Commit**

```bash
git add web/routes/drafts.py tests/test_draft_rich_chat.py
git commit -m "feat: send Slack and Teams drafts in each service's native format"
```

---

### Task 5: Tools seed `body_html` and `format_capabilities`

**Files:**

- Modify: `web/skills/email/tools.py` (`_tool_reply_email` line 324, `_tool_forward_email` line 355, `_tool_email_open_compose` line 627)
- Modify: `web/skills/slack/tools.py` (`_handle_slack_send_message` line ~599)
- Modify: `web/skills/teams/tools.py` (`_tool_teams_open_compose`, the block that ends with `create_draft("teams-message", ...)` around lines 840-888)
- Test: `tests/test_draft_rich_tools.py`

**Interfaces:**

- Consumes (Tasks 1-2): `skills._rich_text` — `normalize(body="", body_html="")`, `slack_to_html(message, names=None)`, `teams_to_html(message, mentions=None)`, `rich_payload(service, body_html) -> {"body_html": str, "format_capabilities": list[str]}`, `capabilities(service)`, `mention_span(mention_id, name, service)`.
- Produces: every email, Slack, and Teams draft has `params["body_html"]` (canonical HTML) and its card `data` carries `body_html` and `format_capabilities`. Existing fields (`body`, `message`, `mentions`, `body_snippet`) are unchanged, so the legacy approve path and existing tests keep working. Task 6 reads `data.body_html` and `data.format_capabilities`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_draft_rich_tools.py`:

```python
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from unittest.mock import patch

from skills import _drafts
from skills import _rich_text as rt

ORIG = {
    "subject": "Plan",
    "from_addr": "amy@amd.com",
    "from_name": "Amy",
    "to_recipients": [],
    "cc_recipients": [],
}


def setup_function(function):
    _drafts._pending_drafts.clear()


def _params(result):
    return _drafts.get_draft(result["data"]["draft_id"])["params"]


def test_email_compose_converts_markdown_body():
    from skills.email.tools import _tool_email_open_compose

    res = _tool_email_open_compose(to="bob@amd.com", subject="S", body="Hi **Bob**")
    assert _params(res)["body_html"] == "<p>Hi <strong>Bob</strong></p>"
    assert res["data"]["body_html"] == "<p>Hi <strong>Bob</strong></p>"
    assert res["data"]["format_capabilities"] == rt.capabilities("email")


def test_email_compose_sanitizes_llm_body_html():
    from skills.email.tools import _tool_email_open_compose

    res = _tool_email_open_compose(
        to="bob@amd.com", subject="S", body="x", body_html="<p>x</p><script>alert(1)</script>"
    )
    assert _params(res)["body_html"] == "<p>x</p>"
    assert res["data"]["body_html"] == "<p>x</p>"


def test_email_reply_seeds_body_html():
    from skills.email.tools import _tool_reply_email

    with patch("skills.email.tools._fetch_original_email_context", return_value=ORIG):
        res = _tool_reply_email("AAMk1", "Thanks, **done**")
    params = _params(res)
    assert params["body"] == "Thanks, **done**"
    assert params["body_html"] == "<p>Thanks, <strong>done</strong></p>"
    assert res["data"]["body_html"] == params["body_html"]
    assert res["data"]["format_capabilities"] == rt.capabilities("email")


def test_email_forward_seeds_body_html():
    from skills.email.tools import _tool_forward_email

    with patch("skills.email.tools._fetch_original_email_context", return_value=ORIG):
        res = _tool_forward_email("AAMk1", "bob@amd.com", "FYI")
    params = _params(res)
    assert params["comment"] == "FYI"
    assert params["body_html"] == "<p>FYI</p>"
    assert res["data"]["format_capabilities"] == rt.capabilities("email")


def test_slack_dm_seeds_body_html_with_mention_and_format():
    from skills.slack.tools import _handle_slack_send_message

    with patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T1", "team": "AMD"}), patch(
        "skills.slack.tools._resolve_user", return_value="Alex"
    ):
        res = _handle_slack_send_message(
            user_id="U1",
            team_id="T1",
            message="Hi @Alex *now*",
            mentions=[{"user_id": "U1", "name": "Alex"}],
        )
    params = _params(res)
    assert params["message"] == "Hi <@U1> *now*"
    assert 'data-mention-id="U1"' in params["body_html"]
    assert "<strong>now</strong>" in params["body_html"]
    assert res["data"]["body_html"] == params["body_html"]
    assert res["data"]["format_capabilities"] == rt.capabilities("slack")
    assert "underline" not in res["data"]["format_capabilities"]


def test_slack_post_seeds_body_html():
    from skills.slack.tools import _handle_slack_send_message

    with patch("skills.slack.mcp_client._load_token", return_value={"team_id": "T1", "team": "AMD"}), patch(
        "skills.slack.tools._api", return_value={"ok": False}
    ):
        res = _handle_slack_send_message(channel_id="C1", team_id="T1", message="ship _it_")
    params = _params(res)
    assert params["message"] == "ship _it_"
    assert params["body_html"] == "<p>ship <em>it</em></p>"
    assert res["data"]["format_capabilities"] == rt.capabilities("slack")


def test_teams_compose_seeds_body_html_with_mention_chip():
    from skills.teams.tools import _tool_teams_open_compose

    res = _tool_teams_open_compose(
        to="peer@amd.com",
        message="Hi @Alex McKinney,\n\nplease review.",
        mentions=[
            {
                "id": 9,
                "mentionText": "Alex McKinney",
                "mentioned": {"user": {"id": "AAD1", "displayName": "Alex McKinney"}},
            }
        ],
    )
    params = _params(res)
    expected = "<p>Hi " + rt.mention_span("AAD1", "Alex McKinney", "teams") + ",</p><p>please review.</p>"
    assert params["body_html"] == expected
    assert 'itemtype="http://schema.skype.com/Mention"' in params["message"]
    assert res["data"]["body_html"] == expected
    assert res["data"]["format_capabilities"] == rt.capabilities("teams")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_draft_rich_tools.py -q`
Expected: FAIL with `KeyError: 'body_html'` (or an assertion on `format_capabilities`) in every test.

- [ ] **Step 3: Email tools**

3a. Replace the whole `_tool_reply_email` (line 324 through its `return {...}`) with:

```python
def _tool_reply_email(message_id: str, body: str, reply_all: bool = False) -> dict:
    from .._drafts import create_draft
    from skills import _rich_text as rich

    action = "replyAll" if reply_all else "reply"
    orig = _fetch_original_email_context(message_id)
    subject = f"Re: {orig['subject']}" if orig["subject"] else ""
    body_html = rich.normalize(body)
    draft_id = create_draft(
        draft_type="email-reply",
        params={"message_id": message_id, "body": body, "body_html": body_html, "reply_all": reply_all},
        preview={
            "action": action,
            "subject": subject,
            "from": orig["from_name"] or orig["from_addr"],
        },
    )
    return {
        "_draft": "email-reply",
        "data": {
            "draft_id": draft_id,
            "action": action,
            "message_id": message_id,
            "subject": subject,
            "to": orig["from_addr"],
            "to_names": orig["from_name"],
            "body": body,
            "body_snippet": body[:200],
            **rich.rich_payload("email", body_html),
        },
        "_user_message": f"Draft {action} ready for your approval. Click 'I approve to send' or edit in /outlook.",
    }
```

3b. Replace the whole `_tool_forward_email` (line 355 through its `return {...}`) with:

```python
def _tool_forward_email(message_id: str, to: str, comment: str = "") -> dict:
    from .._drafts import create_draft
    from skills import _rich_text as rich

    to_addrs = [a.strip() for a in to.split(",") if a.strip()]
    orig = _fetch_original_email_context(message_id)
    subject = f"Fw: {orig['subject']}" if orig["subject"] else ""
    body_html = rich.normalize(comment)
    draft_id = create_draft(
        draft_type="email-forward",
        params={"message_id": message_id, "to": to, "comment": comment, "body_html": body_html},
        preview={
            "to": to_addrs,
            "subject": subject,
            "from": orig["from_name"] or orig["from_addr"],
        },
    )
    return {
        "_draft": "email-forward",
        "data": {
            "draft_id": draft_id,
            "subject": subject,
            "to": ", ".join(to_addrs),
            "message_id": message_id,
            "body": comment,
            "body_snippet": (comment or "")[:200],
            **rich.rich_payload("email", body_html),
        },
        "_user_message": f"Draft forward to {', '.join(to_addrs)} ready for your approval. Click 'I approve to send' or edit in /outlook.",
    }
```

3c. In `_tool_email_open_compose`, replace the block from `from .._drafts import create_draft` (the first line after the docstring) through `data["body_html"] = body_html` with:

```python
    from .._drafts import create_draft
    from skills import _rich_text as rich

    canonical = rich.normalize(body=body, body_html=body_html)
    draft_id = create_draft(
        draft_type="email-send",
        params={
            "to": to,
            "subject": subject,
            "body": body,
            "cc": cc,
            "bcc": bcc,
            "body_html": canonical,
        },
        preview={
            "to": [a.strip() for a in to.split(",") if a.strip()],
            "subject": subject,
        },
    )
    data = {
        "to": to,
        "to_names": to_names,
        "subject": subject,
        "body": body,
        "cc": cc,
        "bcc": bcc,
        "context": context,
        "draft_id": draft_id,
    }
    data.update(rich.rich_payload("email", canonical))
```

The `return {"_draft": "email-send", "data": data, ...}` that follows stays unchanged.

- [ ] **Step 4: Slack tool**

In `_handle_slack_send_message`:

4a. Replace the two lines

```python
    from .._drafts import create_draft
    from skills.slack.mcp_client import _load_token

    if not message:
        return {"error": "A Slack draft needs a message."}
```

with

```python
    from .._drafts import create_draft
    from skills import _rich_text as rich
    from skills.slack.mcp_client import _load_token

    if not message:
        return {"error": "A Slack draft needs a message."}
```

4b. Replace

```python
        message = pattern.sub(f"<@{user_id_for_mention}>", message)

    params = {
        "channel_id": channel_id,
        "user_id": user_id,
        "team_id": team_id or active_team_id,
        "workspace_name": active_workspace.get("team", "Slack"),
        "message": message,
    }
```

with

```python
        message = pattern.sub(f"<@{user_id_for_mention}>", message)

    names = {
        str(m["user_id"]): str(m.get("name", "")).lstrip("@")
        for m in (mentions or [])
        if m.get("user_id")
    }
    body_html = rich.slack_to_html(message, names)
    params = {
        "channel_id": channel_id,
        "user_id": user_id,
        "team_id": team_id or active_team_id,
        "workspace_name": active_workspace.get("team", "Slack"),
        "message": message,
        "body_html": body_html,
    }
```

4c. In the DM card data, replace

```python
                "workspace_name": params["workspace_name"],
                "message": message,
                "message_snippet": message[:200],
            },
            "_user_message": "Slack DM draft ready for your approval. The DM is opened only after you send.",
```

with

```python
                "workspace_name": params["workspace_name"],
                "message": message,
                "message_snippet": message[:200],
                **rich.rich_payload("slack", body_html),
            },
            "_user_message": "Slack DM draft ready for your approval. The DM is opened only after you send.",
```

4d. In the channel card data, replace

```python
            "thread_ts": thread_ts or "",
            "message": message,
            "message_snippet": message[:200],
        },
        "_user_message": "Slack draft ready for your approval. Review it in AI Gator, then click Post.",
```

with

```python
            "thread_ts": thread_ts or "",
            "message": message,
            "message_snippet": message[:200],
            **rich.rich_payload("slack", body_html),
        },
        "_user_message": "Slack draft ready for your approval. Review it in AI Gator, then click Post.",
```

- [ ] **Step 5: Teams tool**

In `_tool_teams_open_compose`, the module already imports `html`, so import the rich module under the alias `rich`.

5a. Replace

```python
        message = pattern.sub(_replace, message)
    draft_id = create_draft(
        "teams-message",
        {
            "to": to,
            "to_names": to_names,
            "message": message,
            "chat_id": chat_id,
            "chat_topic": chat_topic,
            "mentions": compiled_mentions,
        },
```

with

```python
        message = pattern.sub(_replace, message)
    from skills import _rich_text as rich

    body_html = rich.teams_to_html(message, compiled_mentions)
    draft_id = create_draft(
        "teams-message",
        {
            "to": to,
            "to_names": to_names,
            "message": message,
            "chat_id": chat_id,
            "chat_topic": chat_topic,
            "mentions": compiled_mentions,
            "body_html": body_html,
        },
```

5b. Replace

```python
            "mentions": compiled_mentions,
            "draft_id": draft_id,
            "body": message,
        },
```

with

```python
            "mentions": compiled_mentions,
            "draft_id": draft_id,
            "body": message,
            **rich.rich_payload("teams", body_html),
        },
```

- [ ] **Step 6: Run the new tests and the baseline**

Run: `python -m pytest tests/test_draft_rich_tools.py -q`
Expected: `7 passed`.

Run: `python -m pytest tests/test_draft_rich_email.py tests/test_draft_rich_chat.py tests/test_rich_text.py tests/test_rich_text_adapters.py tests/test_hitl_draft_unification.py tests/test_drafts_pr10.py web/tests/test_teams_pane_config.py web/tests/test_outlook_native_hitl.py web/tests/test_teams_message_approve_send.py web/tests/test_slack_pinned_draft_context.py -q`
Expected: all pass. `test_teams_tool_compiles_selected_main_mention` in `tests/test_hitl_draft_unification.py` still sees the skype itemtype in `params["message"]` because `message` is unchanged.

- [ ] **Step 7: Commit**

```bash
git add web/skills/email/tools.py web/skills/slack/tools.py web/skills/teams/tools.py tests/test_draft_rich_tools.py
git commit -m "feat: seed canonical body_html and format capabilities when Gator drafts a message"
```

---

### Task 6: Card rich editor, toolbar, and request bodies

**Files:**

- Modify: `web/static/app.js` (replace `_serializeInlineDraftEditor` at lines ~10182-10214; card markup at ~10461-10469; wiring at ~10508-10510; approve handler at ~10525-10542; open-in-Outlook handler at ~10665-10672)
- Modify: `web/static/style.css` (after the `.gcc-mention-editor` rule at ~5801-5804)
- Modify: `tests/test_hitl_draft_unification.py` (lines ~1142-1143)
- Test: `tests/draft_rich_editor.test.js`

**Interfaces:**

- Consumes (Task 5): draft card `data.body_html: string` (canonical sanitized HTML) and `data.format_capabilities: string[]` (subset of `bold italic underline ul ol link code`). Existing app.js helpers: `escapeHtml(t)`, `_draftMentionChip(service, person)`, `_wireInlineDraftMentions(editor, service, data)`, `_replaceDraftEditorTrigger`, `_teamsDraftEditorSeed`.
- Consumes (Tasks 3-4): `/api/drafts/{id}/approve` and `/open-in-outlook` accept `{"edited_html": str}` for email, Slack, and Teams drafts, and `{"edited_message": str}` for everything else.
- Produces (new app.js functions, all top-level declarations):
  - `_draftEditorSeedHtml(data, fallbackText) -> string`
  - `_upgradeDraftMentions(editor) -> void`
  - `_normalizeDraftLinkUrl(raw) -> string` (`''` means rejected)
  - `_draftFormatButtons(capabilities) -> Array<{cap, label, title, command}>`
  - `_initDraftRichEditor(editor, capabilities) -> void`
- Removes: `_serializeInlineDraftEditor` (the server now derives mentions and native formats from `edited_html`).

- [ ] **Step 1: Confirm the serializer has no other callers**

Run: `grep -rn "_serializeInlineDraftEditor" web/ --include=*.js --include=*.html --include=*.py`
Expected: only the definition and its single call in the approve handler of `web/static/app.js`. If anything else references it, stop and report.

- [ ] **Step 2: Write the failing JS test**

Create `tests/draft_rich_editor.test.js`:

```js
// Pure helpers behind the draft card rich editor. Each function is cut out of app.js and run in a vm.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function load(name, stubs = {}) {
  const match = source.match(new RegExp('function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}'));
  assert(match, name + ' found in app.js');
  return vm.runInNewContext(match[0] + '; ' + name + ';', stubs);
}

const escapeHtml = load('escapeHtml');

// _normalizeDraftLinkUrl
const normalize = load('_normalizeDraftLinkUrl');
assert.strictEqual(normalize(''), '');
assert.strictEqual(normalize('  '), '');
assert.strictEqual(normalize('https://a.com/x'), 'https://a.com/x');
assert.strictEqual(normalize('HTTP://A.COM'), 'HTTP://A.COM');
assert.strictEqual(normalize('example.com'), 'https://example.com');
assert.strictEqual(normalize('a@b.com'), 'mailto:a@b.com');
assert.strictEqual(normalize('javascript:alert(1)'), '');
assert.strictEqual(normalize('data:text/html,x'), '');
assert.strictEqual(normalize('a b.com'), '');
assert.strictEqual(normalize('localhost:8080/x'), 'https://localhost:8080/x');

// _draftEditorSeedHtml
const seed = load('_draftEditorSeedHtml', { escapeHtml });
assert.strictEqual(seed({ body_html: '  <p>x</p> ' }, 'fallback'), '<p>x</p>');
assert.strictEqual(seed({ body_html: '   ' }, 'a < b\nc'), 'a &lt; b<br>c');
assert.strictEqual(seed({}, 'a < b\nc'), 'a &lt; b<br>c');
assert.strictEqual(seed({}, undefined), '');

// _draftFormatButtons
const buttons = load('_draftFormatButtons');
const caps = (list) => JSON.stringify(buttons(list).map((b) => b.cap));
assert.strictEqual(
  caps(['bold', 'italic', 'ul', 'ol', 'link', 'code']),
  '["bold","italic","ul","ol","link","code"]',
);
assert.strictEqual(caps(['link', 'bold']), '["bold","link"]');
assert.strictEqual(caps([]), '[]');
assert.strictEqual(caps(undefined), '[]');
assert.strictEqual(buttons(['underline'])[0].command, 'underline');

// _upgradeDraftMentions
const chips = [];
const upgrade = load('_upgradeDraftMentions', {
  _draftMentionChip: (service, person) => {
    const chip = { service, person, textContent: '' };
    chips.push(chip);
    return chip;
  },
});
const fakeSpan = ({ id, service, name, text, upgraded = false }) => ({
  dataset: { mentionId: id, mentionService: service, mentionName: name },
  classList: { contains: (c) => upgraded && c === 'gcc-inline-mention' },
  textContent: text,
  replacedWith: null,
  replaceWith(node) {
    this.replacedWith = node;
  },
});
const spans = [
  fakeSpan({ id: 'U1', service: 'slack', name: 'Alex', text: '@Alex' }),
  fakeSpan({ id: 'AAD1', service: 'teams', name: '', text: '@Sam' }),
  fakeSpan({ id: 'U2', service: 'slack', name: 'Z', text: '@Z', upgraded: true }),
];
upgrade({ querySelectorAll: () => spans });
assert.strictEqual(chips.length, 2);
assert.deepStrictEqual(JSON.parse(JSON.stringify(chips[0])), {
  service: 'slack',
  person: { name: 'Alex', id: 'U1' },
  textContent: '@Alex',
});
assert.deepStrictEqual(JSON.parse(JSON.stringify(chips[1])), {
  service: 'teams',
  person: { name: 'Sam', id: 'AAD1' },
  textContent: '@Sam',
});
assert.strictEqual(spans[0].replacedWith, chips[0]);
assert.strictEqual(spans[1].replacedWith, chips[1]);
assert.strictEqual(spans[2].replacedWith, null);

console.log('ok');
```

- [ ] **Step 3: Run it to verify it fails**

Run: `node tests/draft_rich_editor.test.js`
Expected: FAIL with `AssertionError: _normalizeDraftLinkUrl found in app.js`.

- [ ] **Step 4: Replace the serializer with the new helpers in `web/static/app.js`**

Delete the whole `function _serializeInlineDraftEditor(editor, service) { ... }` (lines ~10182-10214, from its `function` line through the closing `}` at column 0, plus one of the two surrounding blank lines) and put this in its place. Keep every inner `}` indented: `tests/draft_rich_editor.test.js` cuts each function out of the file up to the first `}` at column 0.

```js
function _draftEditorSeedHtml(data, fallbackText) {
  const html = data && typeof data.body_html === 'string' ? data.body_html.trim() : '';
  if (html) return html;
  return escapeHtml(String(fallbackText || '')).replace(/\n/g, '<br>');
}

function _upgradeDraftMentions(editor) {
  editor.querySelectorAll('span[data-mention-id]').forEach((span) => {
    if (span.classList.contains('gcc-inline-mention')) return;
    const service = span.dataset.mentionService === 'slack' ? 'slack' : 'teams';
    const label = span.textContent || '';
    const name = span.dataset.mentionName || label.replace(/^[@#]/, '');
    const chip = _draftMentionChip(service, { name, id: span.dataset.mentionId || '' });
    chip.textContent = label;
    span.replaceWith(chip);
  });
}

function _normalizeDraftLinkUrl(raw) {
  const url = String(raw || '').trim();
  if (!url || /[\s"<>]/.test(url)) return '';
  if (/^(https?:\/\/|mailto:)/i.test(url)) return url;
  if (/^[a-z][a-z0-9+.-]*:(?!\d)/i.test(url)) return '';
  if (/^[^@/]+@[^@/]+\.[^@/]+$/.test(url)) return 'mailto:' + url;
  return 'https://' + url;
}

function _draftFormatButtons(capabilities) {
  const allowed = new Set(capabilities || []);
  return [
    { cap: 'bold', label: 'B', title: 'Bold', command: 'bold' },
    { cap: 'italic', label: 'I', title: 'Italic', command: 'italic' },
    { cap: 'underline', label: 'U', title: 'Underline', command: 'underline' },
    { cap: 'ul', label: '•', title: 'Bulleted list', command: 'insertUnorderedList' },
    { cap: 'ol', label: '1.', title: 'Numbered list', command: 'insertOrderedList' },
    { cap: 'link', label: 'Link', title: 'Link', command: 'link' },
    { cap: 'code', label: '</>', title: 'Code', command: 'code' },
  ].filter((button) => allowed.has(button.cap));
}

function _initDraftRichEditor(editor, capabilities) {
  _upgradeDraftMentions(editor);
  editor.addEventListener('focus', () => {
    try {
      document.execCommand('defaultParagraphSeparator', false, 'p');
      document.execCommand('styleWithCSS', false, false);
    } catch (_) {
      // execCommand options are best effort; the editor still works without them.
    }
  });
  editor.addEventListener('paste', (event) => {
    const text = event.clipboardData?.getData('text/plain');
    if (text === undefined) return;
    event.preventDefault();
    document.execCommand('insertHTML', false, escapeHtml(text).replace(/\r?\n/g, '<br>'));
  });

  const buttons = _draftFormatButtons(capabilities);
  if (!buttons.length) return;

  const toolbar = document.createElement('div');
  toolbar.className = 'gcc-toolbar';
  toolbar.setAttribute('role', 'toolbar');
  toolbar.setAttribute('aria-label', 'Formatting');

  const linkRow = document.createElement('div');
  linkRow.className = 'gcc-link-row hidden';
  const linkInput = document.createElement('input');
  linkInput.type = 'text';
  linkInput.className = 'gcc-link-input';
  linkInput.placeholder = 'https://example.com';
  linkInput.setAttribute('aria-label', 'Link address');
  const linkAdd = document.createElement('button');
  linkAdd.type = 'button';
  linkAdd.className = 'gcc-tool-btn';
  linkAdd.textContent = 'Add';
  linkRow.append(linkInput, linkAdd);

  let savedRange = null;
  const applyLink = () => {
    const url = _normalizeDraftLinkUrl(linkInput.value);
    if (!url) {
      linkInput.setAttribute('aria-invalid', 'true');
      return;
    }
    linkInput.removeAttribute('aria-invalid');
    editor.focus();
    const sel = window.getSelection();
    if (savedRange) {
      sel.removeAllRanges();
      sel.addRange(savedRange);
    }
    if (!sel.rangeCount || sel.isCollapsed) {
      document.execCommand(
        'insertHTML',
        false,
        `<a href="${escapeHtml(url)}">${escapeHtml(url)}</a>`,
      );
    } else {
      document.execCommand('createLink', false, url);
    }
    linkInput.value = '';
    linkRow.classList.add('hidden');
  };
  linkInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      applyLink();
    } else if (event.key === 'Escape') {
      linkRow.classList.add('hidden');
      editor.focus();
    }
  });
  linkAdd.addEventListener('click', applyLink);

  buttons.forEach((button) => {
    const el = document.createElement('button');
    el.type = 'button';
    el.className = 'gcc-tool-btn';
    el.textContent = button.label;
    el.title = button.title;
    el.setAttribute('aria-label', button.title);
    el.addEventListener('mousedown', (event) => event.preventDefault());
    el.addEventListener('click', () => {
      const sel = window.getSelection();
      const inEditor = !!sel && sel.rangeCount > 0 && editor.contains(sel.anchorNode);
      if (button.command === 'link') {
        savedRange = inEditor ? sel.getRangeAt(0).cloneRange() : null;
        linkRow.classList.toggle('hidden');
        if (!linkRow.classList.contains('hidden')) linkInput.focus();
        return;
      }
      editor.focus();
      if (button.command === 'code') {
        const selected = inEditor ? sel.toString() : '';
        document.execCommand('insertHTML', false, `<code>${escapeHtml(selected || 'code')}</code>`);
        return;
      }
      document.execCommand(button.command, false, null);
    });
    toolbar.appendChild(el);
  });
  editor.before(toolbar, linkRow);
}
```

- [ ] **Step 5: Use the rich editor in the card markup**

In `_injectDraftApprovalCard`, replace

```js
                : config.service === 'slack' || config.service === 'teams'
                  ? `<div class="gcc-edit-area gcc-mention-editor" contenteditable="true" role="textbox" aria-multiline="true" aria-label="Draft message">${escapeHtml(_editableBody)}</div>`
                  : `<textarea class="gcc-edit-area" rows="${Math.min(10, Math.max(3, _editableBody.split('\n').length))}">${escapeHtml(_editableBody)}</textarea>`
```

with

```js
                : ['email', 'slack', 'teams'].includes(config.service)
                  ? `<div class="gcc-edit-area gcc-rich-editor${config.service === 'email' ? '' : ' gcc-mention-editor'}" contenteditable="true" role="textbox" aria-multiline="true" aria-label="Draft message">${_draftEditorSeedHtml(data, _editableBody)}</div>`
                  : `<textarea class="gcc-edit-area" rows="${Math.min(10, Math.max(3, _editableBody.split('\n').length))}">${escapeHtml(_editableBody)}</textarea>`
```

The `gcc-mention-editor` class stays on the Slack and Teams editors, so the existing mention lookup wiring and `tests/test_hitl_draft_unification.py` still match.

- [ ] **Step 6: Initialize the editor after the mention wiring**

Replace

```js
if (inlineMentionEditor && (config.service === 'slack' || config.service === 'teams')) {
  _wireInlineDraftMentions(editArea, config.service, data);
}
```

with

```js
if (inlineMentionEditor && (config.service === 'slack' || config.service === 'teams')) {
  _wireInlineDraftMentions(editArea, config.service, data);
}
if (editArea?.classList.contains('gcc-rich-editor')) {
  _initDraftRichEditor(editArea, data.format_capabilities || []);
}
```

- [ ] **Step 7: Post `edited_html` from Approve**

Replace this block in the approve click handler

```js
const inlineMentionPayload =
  inlineMentionEditor && editArea ? _serializeInlineDraftEditor(editArea, config.service) : null;
const editedText = editArea
  ? inlineMentionPayload
    ? inlineMentionPayload.text
    : editArea.value || editArea.textContent || ''
  : null;
const _approveBody = JSON.stringify({
  context_id: ownerTabId || _activeTabId || 'default',
  ...(editedText !== null ? { edited_message: editedText } : {}),
  ...(Object.keys(editedFields).length ? { edited_fields: editedFields } : {}),
  ...(inlineMentionPayload?.mentions?.length ? { mentions: inlineMentionPayload.mentions } : {}),
});
```

with

```js
const richEditor = !!editArea?.classList.contains('gcc-rich-editor');
const editedText = editArea && !richEditor ? editArea.value || editArea.textContent || '' : null;
const _approveBody = JSON.stringify({
  context_id: ownerTabId || _activeTabId || 'default',
  ...(richEditor ? { edited_html: editArea.innerHTML } : {}),
  ...(editedText !== null ? { edited_message: editedText } : {}),
  ...(Object.keys(editedFields).length ? { edited_fields: editedFields } : {}),
});
```

- [ ] **Step 8: Post `edited_html` from Open in Outlook**

In the `config.service === 'email'` branch of the open-in-Outlook handler, replace

```js
const editedText = editArea ? editArea.value || editArea.textContent || '' : null;
```

with

```js
const outlookEdit = editArea?.classList.contains('gcc-rich-editor')
  ? { edited_html: editArea.innerHTML }
  : editArea
    ? { edited_message: editArea.value || editArea.textContent || '' }
    : null;
```

and replace

```js
            body: editedText !== null ? JSON.stringify({ edited_message: editedText }) : undefined,
```

with

```js
            body: outlookEdit ? JSON.stringify(outlookEdit) : undefined,
```

- [ ] **Step 9: Styles**

In `web/static/style.css`, insert directly after the `.gcc-mention-editor { ... }` rule (it must come after, so `white-space: normal` wins):

```css
.gcc-rich-editor {
  white-space: normal;
  overflow-wrap: anywhere;
}
.gcc-rich-editor p {
  margin: 0 0 0.6em;
}
.gcc-rich-editor p:last-child {
  margin-bottom: 0;
}
.gcc-rich-editor h1,
.gcc-rich-editor h2,
.gcc-rich-editor h3 {
  margin: 0 0 0.4em;
  line-height: 1.3;
}
.gcc-rich-editor h1 {
  font-size: 1.2em;
}
.gcc-rich-editor h2 {
  font-size: 1.1em;
}
.gcc-rich-editor h3 {
  font-size: 1em;
}
.gcc-rich-editor ul,
.gcc-rich-editor ol {
  margin: 0 0 0.6em;
  padding-left: 1.4em;
}
.gcc-rich-editor a {
  color: var(--accent);
  text-decoration: underline;
}
.gcc-rich-editor code,
.gcc-rich-editor pre {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 0.92em;
  background: var(--bg, rgba(127, 127, 127, 0.15));
  border-radius: 4px;
}
.gcc-rich-editor code {
  padding: 0 4px;
}
.gcc-rich-editor pre {
  margin: 0 0 0.6em;
  padding: 6px 8px;
  white-space: pre-wrap;
}
.gcc-rich-editor blockquote {
  margin: 0 0 0.6em;
  padding-left: 10px;
  border-left: 3px solid var(--border);
}
.gcc-rich-editor table {
  border-collapse: collapse;
  margin: 0 0 0.6em;
}
.gcc-rich-editor th,
.gcc-rich-editor td {
  border: 1px solid var(--border);
  padding: 3px 6px;
}
.gcc-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}
.gcc-tool-btn {
  min-width: 28px;
  padding: 3px 8px;
  font: inherit;
  font-size: 0.78rem;
  color: var(--text);
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 5px;
  cursor: pointer;
}
.gcc-tool-btn:hover {
  border-color: var(--accent);
}
.gcc-tool-btn:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}
.gcc-link-row {
  display: flex;
  gap: 4px;
  margin-top: 6px;
}
.gcc-link-row.hidden {
  display: none;
}
.gcc-link-input {
  flex: 1;
  min-width: 0;
  padding: 3px 8px;
  font: inherit;
  font-size: 0.8rem;
  color: var(--text);
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 5px;
}
.gcc-link-input[aria-invalid='true'] {
  border-color: #d33;
}
```

- [ ] **Step 10: Update the source-string test that named the removed serializer**

In `tests/test_hitl_draft_unification.py`, in `test_slack_draft_card_has_scoped_mention_lookup`, replace

```python
        assert "function _serializeInlineDraftEditor" in source
        assert "<@${id}>" in source
```

with

```python
        assert "function _upgradeDraftMentions" in source
        assert "function _normalizeDraftLinkUrl" in source
```

Leave `assert "gcc-mention-editor" in source` and the Teams test (`'itemtype="http://schema.skype.com/Mention"'`, which still appears in the compose-pane code near line 10021) as they are.

- [ ] **Step 11: Run the JS and Python tests**

Run: `node tests/draft_rich_editor.test.js`
Expected: prints `ok`.

Run: `python -m pytest tests/test_hitl_draft_unification.py tests/test_drafts_pr10.py web/tests/test_teams_pane_config.py web/tests/test_outlook_native_hitl.py web/tests/test_teams_message_approve_send.py web/tests/test_slack_pinned_draft_context.py tests/test_draft_rich_email.py tests/test_draft_rich_chat.py tests/test_draft_rich_tools.py tests/test_rich_text.py tests/test_rich_text_adapters.py -q`
Expected: all pass. `test_no_unsupported_compose_injection` requires `insertText` and `teams-pane:open-draft` to be absent from `app.js`; the paste handler uses `insertHTML` for that reason. If `web/tests/test_slack_pinned_draft_context.py` fails, it slices `app.js` between `'slack-dm':` and `'slack-announce':`; do not add either string in the new code.

Run: `node --check web/static/app.js`
Expected: no output.

- [ ] **Step 12: Commit**

```bash
git add web/static/app.js web/static/style.css tests/draft_rich_editor.test.js tests/test_hitl_draft_unification.py
git commit -m "feat: edit and format drafts in the approval card with a rich editor and toolbar"
```

---

### Task 7: End-to-end verification in the running app

**Files:** none modified. This task is a checklist; fix any defect it finds in the task that owns the code, with a test, and commit that fix separately.

**Interfaces:**

- Consumes: everything from Tasks 1-6.
- Produces: nothing.

- [ ] **Step 1: Run the full automated set**

Run: `python -m pytest tests/test_rich_text.py tests/test_rich_text_adapters.py tests/test_draft_rich_email.py tests/test_draft_rich_chat.py tests/test_draft_rich_tools.py tests/test_hitl_draft_unification.py tests/test_drafts_pr10.py tests/test_csrf_route_inventory.py web/tests/test_teams_pane_config.py web/tests/test_outlook_native_hitl.py web/tests/test_teams_message_approve_send.py web/tests/test_slack_pinned_draft_context.py -q`
Expected: all pass (no new routes were added, so the CSRF inventory test is unchanged).

Run: `node tests/draft_rich_editor.test.js`
Expected: prints `ok`.

- [ ] **Step 2: Start the app**

Run: `./dev.ps1` from the repo root and open the app.

- [ ] **Step 3: Email card**

Ask Gator: "Draft an email to myself with a short bulleted list, one bold word, and a link to https://example.com".
Check each of these:

- The draft card shows the bullets, the bold word, and the link as formatted text, not as raw tags or asterisks.
- The toolbar shows B, I, U, bullet, 1., Link, and `</>` buttons.
- Select a word, click B: it becomes bold. Click the Link button, type `example.org`, press Enter: the selection becomes a link to `https://example.org`. Type `javascript:alert(1)` in the link box: it is rejected and the box is marked invalid.
- Paste text copied from a web page: it lands as plain text with no foreign styling.
- Click "Open in Outlook": the Outlook compose window shows the formatting you edited, not the original draft.
- In a second draft, click Approve and confirm it is sent as formatted HTML. Use a draft addressed only to yourself.

- [ ] **Step 4: Slack card**

Ask Gator: "Draft a Slack DM to <a colleague> saying _build is green_ with a bullet list of two items". Check:

- The card shows bold text and bullets; the toolbar omits Underline if the capability list leaves it out.
- Type `@` and two letters: the people lookup still appears, and choosing a person inserts a chip.
- Approve to a test channel or DM to yourself: Slack shows `*bold*`-style formatting as bold and the mention as a real mention.

- [ ] **Step 5: Teams card**

Ask Gator for a Teams message with a mention and a bold word. Check:

- The mention is a chip, and a chip added by typing `@` works as before.
- Approve to a chat with yourself: Teams shows the bold text and a real mention.

- [ ] **Step 6: Other draft types**

Create any non-email, non-Slack, non-Teams draft (for example a calendar event or a GitHub comment). Confirm its card still shows the plain textarea and that Approve still sends the edited text.

- [ ] **Step 7: Browser console**

Open DevTools in the app. Confirm no errors during steps 3-6.

- [ ] **Step 8: Report**

Write the results of steps 3-7 in your task report: pass or fail per step. If any step fails, fix it in the owning task and add a test before finishing.
