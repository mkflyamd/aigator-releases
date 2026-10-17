"""Canonical rich-text model for draft approval cards.

Every draft carries one sanitized-HTML body. Per-service adapters turn it into
the native format (email HTML, Teams HTML with Skype mentions, Slack mrkdwn).
Pure functions, no I/O. A new service registers one Adapter in ADAPTERS.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Callable

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


_SLACK_MENTION_ID = re.compile(r"(?:[UW][A-Z0-9]+|!(?:here|channel|everyone)|#C[A-Z0-9]+)")


def _neutralize_slack_href(href: str) -> str:
    return re.sub(
        r"\s",
        "%20",
        href.replace("&", "&amp;").replace("<", "%3C").replace(">", "%3E").replace("|", "%7C"),
    )


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
        if tag == "span" and _SLACK_MENTION_ID.fullmatch(attrs.get("data-mention-id") or ""):
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
            href = _neutralize_slack_href(href)
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
