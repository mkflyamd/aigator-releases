"""Tests for chat link rendering — Issue #49.

When the LLM emits a raw <a href="...">text</a> tag (instead of markdown link
syntax), the chat renderer escaped it to visible text and the bare-URL pass
re-linked a fragment, leaking attribute soup like:

    ...DefaultItemOpen=1" target="_blank" rel="noopener">ROCm CLI - Test Learnings.docx

into the visible message. The fix: renderMarkdown must neutralise raw anchors by
converting <a href="URL">TEXT</a> to markdown [TEXT](URL) BEFORE escaping, so the
existing markdown-link pass renders a single clean, clickable anchor.

The Python helpers below mirror the link-handling logic in web/static/app.js
(escapeHtml, applyInline link passes, and the renderMarkdown raw-anchor
pre-process). A source-inspection test guards that app.js carries the fix.
"""

import pathlib
import re

APP_JS = (pathlib.Path(__file__).parent.parent / "static" / "app.js").read_text(encoding="utf-8")

SHAREPOINT_URL = (
    "https://amd.sharepoint.com/personal/x/_layouts/15/Doc.aspx?"
    "sourcedoc=%7B12345678-FF3F-4208-B335-3B73AEA335F7%7D"
    "&file=ROCm%20CLI%20-%20Test%20Learnings.docx"
    "&action=default&mobileredirect=true&DefaultItemOpen=1"
)


# ── Python port of app.js link handling ──────────────────────────────────────

def _escape_html(t: str) -> str:
    # mirrors escapeHtml() in app.js (escapes & < > only)
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _apply_inline_links(html: str) -> str:
    # mirrors the markdown-link + bare-URL passes in applyInline()
    def _md(m):
        text, href = m.group(1), m.group(2)
        ext = ' target="_blank" rel="noopener"' if re.match(r"https?://", href) else ""
        return f'<a href="{href}"{ext}>{text}</a>'
    html = re.sub(r'\[(.*?)\]\(((?:https?://|mailto:|/|#)[^)"]*)\)', _md, html)
    html = re.sub(
        r'(?<![="\'>])(https?://[^\s<>"\')\]]+)',
        r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>',
        html,
    )
    return html


def _render_links(raw: str, *, neutralise_raw_anchors: bool) -> str:
    # mirrors renderMarkdown(): optional raw-anchor pre-process, then escape + inline
    s = raw
    if neutralise_raw_anchors:
        def _to_md(m):
            href, inner = m.group(1), m.group(2)
            text = re.sub(r"<[^>]+>", "", inner).strip() or href
            # ')' in the href would terminate the markdown-link pass early and
            # truncate the URL; percent-encode it so the link survives intact.
            href = href.replace(")", "%29")
            return f"[{text}]({href})"
        s = re.sub(
            r'<a\b[^>]*\bhref=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            _to_md, s, flags=re.IGNORECASE | re.DOTALL,
        )
    return _apply_inline_links(_escape_html(s))


# ── Behavioural tests ────────────────────────────────────────────────────────

class TestRawAnchorRendering:
    def test_raw_anchor_renders_single_clean_link(self):
        raw = f'<a href="{SHAREPOINT_URL}" target="_blank" rel="noopener">ROCm CLI - Test Learnings.docx</a>'
        out = _render_links(raw, neutralise_raw_anchors=True)
        # Exactly one anchor, label preserved, href intact (& becomes &amp; which is valid HTML)
        assert out.count("<a ") == 1, f"expected one clean anchor, got: {out}"
        assert "ROCm CLI - Test Learnings.docx</a>" in out
        assert "DefaultItemOpen=1" in out

    def test_raw_anchor_does_not_leak_attribute_text(self):
        raw = f'<a href="{SHAREPOINT_URL}" target="_blank" rel="noopener">ROCm CLI - Test Learnings.docx</a>'
        out = _render_links(raw, neutralise_raw_anchors=True)
        # The reported leak: escaped tag shown as visible text, and dangling
        # attribute soup AFTER the closing </a> rendered as plain text.
        assert "&lt;a" not in out, f"raw <a tag leaked as escaped text: {out}"
        tail = out.split("</a>")[-1]
        assert "target=" not in tail and "rel=" not in tail, f"attribute soup leaked after </a>: {out}"

    def test_current_pipeline_without_fix_is_broken(self):
        """Documents the bug: without the raw-anchor pre-process, the tag leaks."""
        raw = f'<a href="{SHAREPOINT_URL}" target="_blank" rel="noopener">ROCm CLI - Test Learnings.docx</a>'
        out = _render_links(raw, neutralise_raw_anchors=False)
        assert "&lt;a" in out  # escaped raw tag is visible — the regression we fixed

    def test_markdown_link_with_special_chars_unaffected(self):
        raw = f"[ROCm CLI - Test Learnings.docx]({SHAREPOINT_URL})"
        out = _render_links(raw, neutralise_raw_anchors=True)
        assert out.count("<a ") == 1
        assert "ROCm CLI - Test Learnings.docx</a>" in out

    def test_anchor_url_with_paren_not_truncated(self):
        """SharePoint/OneDrive URLs often contain ')' in query strings; the
        markdown-link pass stops at the first unescaped ')', truncating the href
        and leaking the tail as visible text. The href must survive intact."""
        url = "https://amd.sharepoint.com/file.docx?id=abc(123)def&open=1"
        raw = f'<a href="{url}">Doc</a>'
        out = _render_links(raw, neutralise_raw_anchors=True)
        assert out.count("<a ") == 1, f"expected one clean anchor, got: {out}"
        # The tail after the URL must not leak as plain text.
        tail = out.split("</a>")[-1]
        assert "def" not in tail and "open=1" not in tail, f"href truncated, tail leaked: {out}"

    def test_anchor_label_with_bracket_not_dropped(self):
        """A ']' in the link text terminates the markdown-link text capture early,
        dropping the link. The label's bracket must be neutralised so the anchor
        still renders with its full text."""
        raw = '<a href="https://example.com/doc">Some [draft] file.docx</a>'
        out = _render_links(raw, neutralise_raw_anchors=True)
        assert out.count("<a ") == 1, f"expected one clean anchor, got: {out}"
        assert "file.docx</a>" in out, f"label dropped/mangled: {out}"
        assert "&lt;a" not in out


# ── Source-inspection guard on the production renderer ────────────────────────

class TestAppJsCarriesFix:
    def test_render_markdown_neutralises_raw_anchors(self):
        """app.js renderMarkdown must convert raw <a href=...> tags before escaping."""
        start = APP_JS.find("function renderMarkdown(")
        assert start != -1, "renderMarkdown not found in app.js"
        body = APP_JS[start:start + 4000]
        assert "<a\\b" in body and "href=" in body, (
            "renderMarkdown must pre-process raw <a href=...> tags into markdown "
            "links so they don't leak as escaped text (issue #49)."
        )
