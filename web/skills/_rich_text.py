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
