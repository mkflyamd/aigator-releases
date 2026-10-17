# OneNote Page Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the assistant replace, insert, prepend and append content on an existing OneNote page and rename its title, in personal and SharePoint team notebooks, by extending the existing OneNote tools.

**Architecture:** A new pure module `web/skills/onenote/page_edit.py` holds everything that needs no network: the element outline, single-element HTML extraction, and the Graph PATCH body builder. `web/skills/onenote/tools.py` calls it: `read_onenote_page` gains `include_ids` and `element_id`; `update_onenote_page` gains `site_id`, `action`, `target`, `position` and moves from raw `urllib` to `gc._request`; `pin_onenote_page` gains `site_id`. Defaults reproduce today's append request exactly. No new tools and no new routes.

**Tech Stack:** Python 3.12, BeautifulSoup + lxml (already dependencies), httpx through `GraphClient._request`, pytest (`pythonpath = web .`).

## Global Constraints

- No new tool names and no new routes. The CSRF inventory (`tests/csrf_route_baseline.txt`) must not change.
- No new dependencies: BeautifulSoup (`beautifulsoup4`) and `lxml` are already in `pyproject.toml` and `web/requirements.txt`.
- With default inputs, `update_onenote_page` sends exactly today's request: `[{"target": "body", "action": "append", "content": "<div>…</div>"}]` and returns `{"updated": True, "page_id": page_id}`.
- Graph facts confirmed on real notebooks (personal and SharePoint team, 2026-10-17):
  - `replace` works with the generated id from `GET …/content?includeIDs=true`; `#data-id` targets fail on a created page.
  - `replace` with empty content is rejected (400); `<p></p>` works, so "remove" sends `<p></p>`.
  - `replace` on `body` is accepted by Graph and wipes the page, so the tool must refuse it.
  - `title` only supports `replace`.
  - Two replaces in one call using ids from before the call both apply. Ids are stable after a body append.
- Outline lists only elements Graph can update: `p li h1 h2 h3 h4 h5 h6 ol ul table img object`, and a `div` that is inside another `div`. Nothing inside a table is listed (`tr` and `td` are not targetable). Text cut to 80 characters. Paging: `offset`, `limit` (default 100, max 200), `total`, `next_offset`.
- `element_id` read: HTML with generated `id` attributes removed, cap 100,000 characters (`element_too_large`); unknown id gives `target_not_found`.
- `replace` result carries `previous_html` (cap 20,000 characters). Any non-plain-append result carries a fresh outline (first 100).
- A 404 on an update with no `site_id` adds the hint "If this page is in a SharePoint team notebook, pass its site_id from find_onenote_notebook."
- A team page is reached through its section; `GET …/onenote/notebooks` can 403 on a large site (Graph code 10008), so nothing in this change may rely on listing notebooks.
- Human-in-the-loop rules are unchanged: this change touches OneNote only; email, Teams and Slack never auto-send.
- Fake credential in tests: `aigator-fake-api-key` only.
- The project is called **AI Gator**; never call it a POC.
- Git commits must not contain `Co-Authored-By` lines. Stage files by explicit path.

---

## File Structure

| File                                                                                      | Responsibility                                                                                                                                                                                                         |
| ----------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `web/skills/onenote/page_edit.py` (create)                                                | Pure helpers: `EditError`, `outline`, `element_html`, `build_patch_ops`, and the size constants. No I/O.                                                                                                               |
| `tests/test_onenote_page_edit.py` (create)                                                | Unit tests for the pure helpers.                                                                                                                                                                                       |
| `web/skills/onenote/tools.py` (modify)                                                    | `_fetch_page_html`; `read_onenote_page` (`include_ids`, `element_id`, `offset`, `limit`); `update_onenote_page` (`site_id`, `action`, `target`, `position`); `pin_onenote_page` (`site_id`); schemas and descriptions. |
| `tests/test_onenote_edit_tools.py` (create)                                               | Tool tests with a fake Graph client.                                                                                                                                                                                   |
| `tests/test_graph_id_encoding.py` (modify, `test_update_page_encodes_page_id`, ~line 382) | Follows the move from `urllib` to `gc._request`.                                                                                                                                                                       |
| `web/skills/onenote/state.py` (modify)                                                    | `pin_site_text` helper for the pin prompt text.                                                                                                                                                                        |
| `web/routes/chat.py` (modify, lines ~1325 and ~1501)                                      | Pin prompt lines show `site_id` when set.                                                                                                                                                                              |
| `tests/test_onenote_pin_site.py` (create)                                                 | Pin storage and prompt-text tests.                                                                                                                                                                                     |
| `web/skills/onenote/SKILL.md` (modify)                                                    | Edit workflow text.                                                                                                                                                                                                    |

Order: pure helpers (Tasks 1-2), read (Task 3), update (Task 4), pins (Task 5), skill text and verification (Task 6). Every task leaves the suite green.

Run tests from the repo root `C:\Users\maykulka\pocs\aigator-releases`.

---

### Task 1: Page outline and single-element extraction

**Files:**

- Create: `web/skills/onenote/page_edit.py`
- Test: `tests/test_onenote_page_edit.py`

**Interfaces:**

- Consumes: nothing.
- Produces (later tasks rely on these exact names):
  - `MAX_ELEMENT_HTML = 100_000`, `MAX_PREVIOUS_HTML = 20_000`, `DEFAULT_LIMIT = 100`, `MAX_LIMIT = 200`
  - `outline(page_html: str, offset: int = 0, limit: int = DEFAULT_LIMIT) -> dict` returning `{"elements": [{"id", "tag", "text", "rows"?, "cols"?}], "total": int, "next_offset": int | None}`
  - `element_html(page_html: str, element_id: str) -> str | None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_onenote_page_edit.py`:

```python
"""Pure helpers in web/skills/onenote/page_edit.py."""

from skills.onenote import page_edit

PAGE = """<html><head><title>T</title></head><body>
<div id="div:{a}{1}" style="position:absolute;left:48px;top:120px;width:624px">
<h1 id="h1:{a}{2}">Heading one</h1>
<p id="p:{a}{3}">Paragraph <a href="https://example.test/x">link</a></p>
<ul id="ul:{a}{4}"><li id="li:{a}{5}">item a</li><li id="li:{a}{6}">item b</li></ul>
<table id="table:{a}{7}">
<tr id="tr:{a}{8}"><td id="td:{a}{9}"><p id="p:{a}{10}">r1c1</p></td><td id="td:{a}{11}"><p id="p:{a}{12}">r1c2</p></td></tr>
<tr id="tr:{a}{13}"><td id="td:{a}{14}"><p id="p:{a}{15}">r2c1</p></td><td id="td:{a}{16}"><p id="p:{a}{17}">r2c2</p></td></tr>
</table>
<div id="div:{a}{18}"><p id="p:{a}{19}">nested</p></div>
</div></body></html>"""


def _ids(result):
    return [e["id"] for e in result["elements"]]


def test_outline_lists_only_updatable_elements():
    result = page_edit.outline(PAGE)
    assert _ids(result) == [
        "h1:{a}{2}",
        "p:{a}{3}",
        "ul:{a}{4}",
        "li:{a}{5}",
        "li:{a}{6}",
        "table:{a}{7}",
        "div:{a}{18}",
        "p:{a}{19}",
    ]
    assert result["total"] == 8
    assert result["next_offset"] is None


def test_outline_skips_outer_div_and_table_internals():
    ids = _ids(page_edit.outline(PAGE))
    assert "div:{a}{1}" not in ids
    for inner in ("tr:{a}{8}", "td:{a}{9}", "p:{a}{10}", "p:{a}{17}"):
        assert inner not in ids


def test_outline_table_has_rows_and_cols():
    table = next(e for e in page_edit.outline(PAGE)["elements"] if e["tag"] == "table")
    assert (table["rows"], table["cols"]) == (2, 2)
    heading = next(e for e in page_edit.outline(PAGE)["elements"] if e["tag"] == "h1")
    assert "rows" not in heading


def test_outline_text_is_cut_to_80_characters():
    page = '<html><body><div id="d1"><p id="p1">' + "x" * 200 + "</p></div></body></html>"
    # d1 is an outer div (skipped); p1 is listed
    (item,) = page_edit.outline(page)["elements"]
    assert len(item["text"]) == 80


def test_outline_paging():
    first = page_edit.outline(PAGE, offset=0, limit=3)
    assert len(first["elements"]) == 3
    assert first["total"] == 8
    assert first["next_offset"] == 3
    last = page_edit.outline(PAGE, offset=6, limit=3)
    assert [e["id"] for e in last["elements"]] == ["div:{a}{18}", "p:{a}{19}"]
    assert last["next_offset"] is None


def test_outline_limit_is_clamped():
    assert page_edit.outline(PAGE, limit=10_000)["total"] == 8
    assert len(page_edit.outline(PAGE, limit=0)["elements"]) == 1


def test_element_html_strips_ids_and_keeps_markup():
    out = page_edit.element_html(PAGE, "table:{a}{7}")
    assert out.startswith("<table")
    assert "id=" not in out
    assert "r2c2" in out


def test_element_html_keeps_links_and_styles():
    out = page_edit.element_html(PAGE, "p:{a}{3}")
    assert 'href="https://example.test/x"' in out
    assert "id=" not in out


def test_element_html_unknown_id_is_none():
    assert page_edit.element_html(PAGE, "p:{nope}{1}") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_onenote_page_edit.py -v`
Expected: FAIL with `ImportError: cannot import name 'page_edit'`.

- [ ] **Step 3: Write the implementation**

Create `web/skills/onenote/page_edit.py`:

```python
"""Pure helpers for reading and editing OneNote page content (no network)."""

from bs4 import BeautifulSoup

MAX_ELEMENT_HTML = 100_000
MAX_PREVIOUS_HTML = 20_000
DEFAULT_LIMIT = 100
MAX_LIMIT = 200
_TEXT_LEN = 80
_LISTED_TAGS = {
    "p", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "ol", "ul", "table", "img", "object", "div",
}


def _soup(page_html: str) -> BeautifulSoup:
    return BeautifulSoup(page_html, "lxml")


def _is_listed(el) -> bool:
    if el.name not in _LISTED_TAGS or not el.get("id"):
        return False
    if any(parent.name == "table" for parent in el.parents):
        return False
    if el.name == "div" and not any(parent.name == "div" for parent in el.parents):
        return False
    return True


def _table_shape(table) -> tuple[int, int]:
    rows = [r for r in table.find_all("tr") if r.find_parent("table") is table]
    cols = max(
        (len(r.find_all(["td", "th"], recursive=False)) for r in rows), default=0
    )
    return len(rows), cols


def outline(page_html: str, offset: int = 0, limit: int = DEFAULT_LIMIT) -> dict:
    offset = max(0, int(offset))
    limit = min(max(1, int(limit)), MAX_LIMIT)
    items = []
    for el in _soup(page_html).find_all(True):
        if not _is_listed(el):
            continue
        item = {
            "id": el["id"],
            "tag": el.name,
            "text": el.get_text(" ", strip=True)[:_TEXT_LEN],
        }
        if el.name == "table":
            item["rows"], item["cols"] = _table_shape(el)
        items.append(item)
    end = offset + limit
    return {
        "elements": items[offset:end],
        "total": len(items),
        "next_offset": end if end < len(items) else None,
    }


def element_html(page_html: str, element_id: str) -> str | None:
    el = _soup(page_html).find(attrs={"id": element_id})
    if el is None:
        return None
    for tag in [el, *el.find_all(True)]:
        tag.attrs.pop("id", None)
    return str(el)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_onenote_page_edit.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add web/skills/onenote/page_edit.py tests/test_onenote_page_edit.py
git commit -m "feat: add OneNote page outline and element extraction helpers"
```

---

### Task 2: PATCH body builder

**Files:**

- Modify: `web/skills/onenote/page_edit.py`
- Test: `tests/test_onenote_page_edit.py`

**Interfaces:**

- Consumes: nothing from earlier tasks beyond the module itself.
- Produces:
  - `class EditError(ValueError)` with attributes `code: str` and `message: str`
  - `ACTIONS = ("append", "prepend", "insert", "replace")`
  - `build_patch_ops(content: str, html: bool = False, action: str = "append", target: str = "body", position: str = "") -> list[dict]`; raises `EditError` with these codes: `invalid_action`, `invalid_position`, `title_requires_replace`, `replace_body_not_allowed`, `insert_needs_element`, `content_required`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_onenote_page_edit.py`:

```python
import pytest


def test_default_is_todays_body_append():
    ops = page_edit.build_patch_ops("a < b\nline two")
    assert ops == [
        {"target": "body", "action": "append", "content": "<div>a &lt; b<br/>line two</div>"}
    ]


def test_default_append_with_html_is_passed_through():
    ops = page_edit.build_patch_ops("<b>x</b>", html=True)
    assert ops[0]["content"] == "<div><b>x</b></div>"


def test_body_prepend_wraps_text_in_p():
    ops = page_edit.build_patch_ops("hi", action="prepend")
    assert ops == [{"target": "body", "action": "prepend", "content": "<p>hi</p>"}]


def test_replace_element_with_text_wraps_in_p_and_escapes():
    ops = page_edit.build_patch_ops("a & b", action="replace", target="p:{a}{3}")
    assert ops == [{"target": "p:{a}{3}", "action": "replace", "content": "<p>a &amp; b</p>"}]


def test_replace_element_with_html_is_passed_through():
    ops = page_edit.build_patch_ops("<table></table>", html=True, action="replace", target="t1")
    assert ops[0]["content"] == "<table></table>"


def test_replace_with_empty_content_sends_empty_paragraph():
    ops = page_edit.build_patch_ops("", action="replace", target="p1")
    assert ops[0]["content"] == "<p></p>"


def test_insert_defaults_to_after_and_accepts_before():
    after = page_edit.build_patch_ops("x", action="insert", target="p1")
    assert after[0]["position"] == "after"
    before = page_edit.build_patch_ops("x", action="insert", target="p1", position="before")
    assert before[0]["position"] == "before"


def test_append_to_child_passes_position_through():
    ops = page_edit.build_patch_ops("<li>c</li>", html=True, action="append", target="ul1", position="after")
    assert ops[0]["position"] == "after"
    plain = page_edit.build_patch_ops("<li>c</li>", html=True, action="append", target="ul1")
    assert "position" not in plain[0]


def test_title_replace_is_escaped_single_line():
    ops = page_edit.build_patch_ops("A <b>\nTitle", action="replace", target="title")
    assert ops == [{"target": "title", "action": "replace", "content": "A &lt;b&gt; Title"}]


@pytest.mark.parametrize(
    "kwargs, code",
    [
        ({"action": "replace", "target": "body"}, "replace_body_not_allowed"),
        ({"action": "append", "target": "title"}, "title_requires_replace"),
        ({"action": "insert", "target": "body"}, "insert_needs_element"),
        ({"action": "delete", "target": "p1"}, "invalid_action"),
        ({"action": "insert", "target": "p1", "position": "middle"}, "invalid_position"),
        ({"action": "insert", "target": "p1", "content": ""}, "content_required"),
        ({"action": "prepend", "target": "body", "content": ""}, "content_required"),
    ],
)
def test_build_patch_ops_refusals(kwargs, code):
    kwargs.setdefault("content", "x")
    with pytest.raises(page_edit.EditError) as exc:
        page_edit.build_patch_ops(**kwargs)
    assert exc.value.code == code
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_onenote_page_edit.py -v`
Expected: the new tests FAIL with `AttributeError: module 'skills.onenote.page_edit' has no attribute 'build_patch_ops'`.

- [ ] **Step 3: Write the implementation**

In `web/skills/onenote/page_edit.py`, add `import html as _html` under the module docstring (before the `from bs4` line), then append:

```python
ACTIONS = ("append", "prepend", "insert", "replace")
_POSITIONS = ("before", "after")


class EditError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _escape_text(text: str) -> str:
    return _html.escape(text, quote=False).replace("\n", "<br/>")


def build_patch_ops(
    content: str,
    html: bool = False,
    action: str = "append",
    target: str = "body",
    position: str = "",
) -> list[dict]:
    if action not in ACTIONS:
        raise EditError("invalid_action", f"action must be one of {', '.join(ACTIONS)}.")
    if position and position not in _POSITIONS:
        raise EditError("invalid_position", "position must be 'before' or 'after'.")

    if target == "title":
        if action != "replace":
            raise EditError("title_requires_replace", "The title can only be replaced.")
        title = _html.escape(" ".join(content.split()), quote=False)
        return [{"target": "title", "action": "replace", "content": title}]

    if target == "body":
        if action == "replace":
            raise EditError(
                "replace_body_not_allowed",
                "Replacing the body would erase the whole page. Replace a specific element, or append.",
            )
        if action == "insert":
            raise EditError("insert_needs_element", "insert needs an element id as the target.")
        if action == "append":
            body = content if html else _escape_text(content)
            return [{"target": "body", "action": "append", "content": f"<div>{body}</div>"}]

    if content == "":
        if action != "replace":
            raise EditError("content_required", f"{action} needs non-empty content.")
        markup = "<p></p>"
    else:
        markup = content if html else f"<p>{_escape_text(content)}</p>"
    op = {"target": target, "action": action, "content": markup}
    if action == "insert":
        op["position"] = position or "after"
    elif position:
        op["position"] = position
    return [op]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_onenote_page_edit.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add web/skills/onenote/page_edit.py tests/test_onenote_page_edit.py
git commit -m "feat: add OneNote PATCH body builder for replace, insert, prepend and title"
```

---

### Task 3: `read_onenote_page` with `include_ids` and `element_id`

**Files:**

- Modify: `web/skills/onenote/tools.py` (imports ~line 1-9; schema at 108-126; handler at 482-518)
- Test: `tests/test_onenote_edit_tools.py`

**Interfaces:**

- Consumes: `page_edit.outline`, `page_edit.element_html`, `page_edit.MAX_ELEMENT_HTML`, `page_edit.DEFAULT_LIMIT`.
- Produces:
  - `_fetch_page_html(gc, root: str, page_id: str, include_ids: bool = False) -> str` in `tools.py` (Task 4 reuses it).
  - `_tool_read_onenote_page(page_id, site_id="", include_ids=False, element_id="", offset=0, limit=100)`; the default call is unchanged.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_onenote_edit_tools.py`:

```python
"""update/read OneNote page tools with a fake Graph client."""

import json
from unittest.mock import patch

import pytest

from skills.onenote import page_edit
from skills.onenote import tools as onenote_tools

PAGE = """<html><head><title>T</title></head><body>
<div id="div:{a}{1}" style="position:absolute;left:48px;top:120px">
<h1 id="h1:{a}{2}">Heading one</h1>
<p id="p:{a}{3}">Paragraph one</p>
<table id="table:{a}{7}"><tr id="tr:{a}{8}"><td id="td:{a}{9}"><p id="p:{a}{10}">r1c1</p></td></tr></table>
</div></body></html>"""

SLASH_ID = "AAMkAD/item+Id=xQ=="
SITE = "contoso.sharepoint.com,aaa,bbb"


class FakeResp:
    def __init__(self, text=""):
        self.text = text
        self.status_code = 200


class FakeGC:
    def __init__(self, page_html=PAGE, patch_error=None):
        self.page_html = page_html
        self.patch_error = patch_error
        self.calls = []

    def _headers(self):
        return {"Authorization": "Bearer aigator-fake-api-key"}

    def get_token(self):
        return "aigator-fake-api-key"

    def get(self, path, params=None):
        self.calls.append(("META", path, None))
        return {"title": "My page", "lastModifiedDateTime": "2026-10-17T10:00:00Z"}

    def _request(self, method, url, **kw):
        self.calls.append((method, url, kw.get("content")))
        if method == "PATCH" and self.patch_error:
            raise self.patch_error
        return FakeResp(self.page_html if method == "GET" else "")

    def methods(self):
        return [c[0] for c in self.calls]

    def patch_bodies(self):
        return [json.loads(c[2]) for c in self.calls if c[0] == "PATCH"]


def _run(fn, gc, *args, **kwargs):
    with patch("skills._m365.helpers.get_skill_client", return_value=gc):
        return fn(*args, **kwargs)


# ── read_onenote_page ────────────────────────────────────────────────────────

def test_read_include_ids_returns_outline_for_personal_page():
    gc = FakeGC()
    result = _run(onenote_tools._tool_read_onenote_page, gc, "page1", include_ids=True)
    assert result["title"] == "My page"
    assert [e["tag"] for e in result["elements"]] == ["h1", "p", "table"]
    assert result["total"] == 3
    get_urls = [c[1] for c in gc.calls if c[0] == "GET"]
    assert get_urls == ["https://graph.microsoft.com/v1.0/me/onenote/pages/page1/content?includeIDs=true"]


def test_read_include_ids_routes_to_site_and_encodes_ids():
    gc = FakeGC()
    _run(onenote_tools._tool_read_onenote_page, gc, SLASH_ID, site_id=SITE, include_ids=True)
    url = next(c[1] for c in gc.calls if c[0] == "GET")
    assert "/sites/contoso.sharepoint.com%2Caaa%2Cbbb/onenote/pages/" in url
    assert "%2F" in url and "/item" not in url


def test_read_include_ids_paging():
    gc = FakeGC()
    result = _run(onenote_tools._tool_read_onenote_page, gc, "page1", include_ids=True, offset=1, limit=1)
    assert [e["tag"] for e in result["elements"]] == ["p"]
    assert result["next_offset"] == 2


def test_read_element_id_returns_html_without_ids():
    gc = FakeGC()
    result = _run(onenote_tools._tool_read_onenote_page, gc, "page1", element_id="table:{a}{7}")
    assert result["id"] == "table:{a}{7}"
    assert result["html"].startswith("<table")
    assert "id=" not in result["html"]


def test_read_element_id_unknown_is_target_not_found():
    gc = FakeGC()
    result = _run(onenote_tools._tool_read_onenote_page, gc, "page1", element_id="p:{x}{9}")
    assert result["error"] == "target_not_found"


def test_read_element_id_too_large(monkeypatch):
    monkeypatch.setattr(page_edit, "MAX_ELEMENT_HTML", 10)
    gc = FakeGC()
    result = _run(onenote_tools._tool_read_onenote_page, gc, "page1", element_id="table:{a}{7}")
    assert result["error"] == "element_too_large"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_onenote_edit_tools.py -v`
Expected: FAIL with `TypeError: _tool_read_onenote_page() got an unexpected keyword argument 'include_ids'`.

- [ ] **Step 3: Write the implementation**

In `web/skills/onenote/tools.py`:

3a. Add the import after `from urllib.parse import quote as _url_quote` (line 8):

```python
from . import page_edit as _pe
```

3b. Add the helper directly above `_tool_read_onenote_page` (before line 482):

```python
def _fetch_page_html(gc, root: str, page_id: str, include_ids: bool = False) -> str:
    url = f"https://graph.microsoft.com/v1.0{root}/pages/{_eid(page_id)}/content"
    if include_ids:
        url += "?includeIDs=true"
    resp = gc._request(
        "GET",
        url,
        headers={**gc._headers(), "Accept": "text/html"},
        label=f"onenote/pages/{page_id}/content",
    )
    return resp.text
```

3c. Replace the head of `_tool_read_onenote_page` (signature through the `meta = gc.get(...)` call, lines 482-494) with:

```python
def _tool_read_onenote_page(
    page_id: str,
    site_id: str = "",
    include_ids: bool = False,
    element_id: str = "",
    offset: int = 0,
    limit: int = _pe.DEFAULT_LIMIT,
) -> dict:
    """Read a OneNote page's content as plain text. Pass site_id for pages in
    SharePoint team/shared notebooks (from list_onenote_pages). include_ids
    returns an outline of editable elements; element_id returns one element's HTML."""
    from .._m365.helpers import get_skill_client

    gc = get_skill_client(ONENOTE_SKILLS_DIR)
    token = gc.get_token()
    root = _onenote_root(site_id)

    if element_id:
        element = _pe.element_html(
            _fetch_page_html(gc, root, page_id, include_ids=True), element_id
        )
        if element is None:
            return {
                "error": "target_not_found",
                "hint": "Read the page again; element ids change after an update.",
            }
        if len(element) > _pe.MAX_ELEMENT_HTML:
            return {"error": "element_too_large", "length": len(element)}
        return {"id": element_id, "html": element}

    # Get metadata
    meta = gc.get(
        f"{root}/pages/{_eid(page_id)}", params={"$select": "id,title,lastModifiedDateTime"}
    )

    if include_ids:
        page_html = _fetch_page_html(gc, root, page_id, include_ids=True)
        return {
            "title": meta.get("title", "(untitled)"),
            "id": page_id,
            "modified": meta.get("lastModifiedDateTime", "")[:16],
            **_pe.outline(page_html, offset, limit),
        }
```

The rest of the function (the urllib fetch and `html_to_text`) stays as is.

3d. In `TOOL_DEFS`, replace the `read_onenote_page` entry (lines 108-126) with:

```python
    {
        "name": "read_onenote_page",
        "description": "Read the content of a OneNote page. Returns the page title and body as plain text. Use to read, summarize, or answer questions about a page's content. For pages in SharePoint team notebooks, pass the site_id. Before editing existing content, call with include_ids=true to get an outline of editable elements (id, tag, text; tables also rows and cols); call with element_id to get one element's full HTML (use it to rebuild a table before replacing it).",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {
                    "type": "string",
                    "description": "Page ID from list_onenote_pages or a pinned page",
                },
                "site_id": {
                    "type": "string",
                    "description": "SharePoint site id (same site_id the page came from). Omit or '' for personal notebooks.",
                    "default": "",
                },
                "include_ids": {
                    "type": "boolean",
                    "description": "If true, return an outline of the page's editable elements with their ids instead of the plain text.",
                    "default": False,
                },
                "element_id": {
                    "type": "string",
                    "description": "An element id from the outline. Returns that element's full HTML.",
                    "default": "",
                },
                "offset": {
                    "type": "integer",
                    "description": "Outline paging: index of the first element to return. Default 0.",
                    "default": 0,
                },
                "limit": {
                    "type": "integer",
                    "description": "Outline paging: max elements to return. Default 100, at most 200.",
                    "default": 100,
                },
            },
            "required": ["page_id"],
        },
    },
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_onenote_edit_tools.py tests/test_graph_id_encoding.py -v`
Expected: all PASS (the existing `test_read_page_encodes_page_id` still passes because the default read path is unchanged).

- [ ] **Step 5: Commit**

```bash
git add web/skills/onenote/tools.py tests/test_onenote_edit_tools.py
git commit -m "feat: let read_onenote_page return an element outline and single-element HTML"
```

---

### Task 4: `update_onenote_page` with action, target, position and site

**Files:**

- Modify: `web/skills/onenote/tools.py` (schema at ~127-149 before Task 3 line shifts; handler `_tool_update_onenote_page`)
- Modify: `tests/test_graph_id_encoding.py` (`test_update_page_encodes_page_id`)
- Test: `tests/test_onenote_edit_tools.py`

**Interfaces:**

- Consumes: `page_edit.build_patch_ops`, `page_edit.EditError`, `page_edit.element_html`, `page_edit.outline`, `page_edit.MAX_PREVIOUS_HTML`, `tools._fetch_page_html`, `tools._onenote_root`, `tools._eid`.
- Produces: `_tool_update_onenote_page(page_id, content, html=False, site_id="", action="append", target="body", position="")` returning, for a plain body append, exactly `{"updated": True, "page_id": page_id}`; otherwise also `elements`, `total`, `next_offset`, and for `replace` of an element `previous_html`. Errors are dicts: `{"error": code, ...}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_onenote_edit_tools.py`:

```python
# ── update_onenote_page ──────────────────────────────────────────────────────

def test_update_default_is_todays_request_and_result():
    gc = FakeGC()
    result = _run(onenote_tools._tool_update_onenote_page, gc, "page1", "hello <x>")
    assert result == {"updated": True, "page_id": "page1"}
    assert gc.methods() == ["PATCH"]
    method, url, _ = gc.calls[0]
    assert url == "https://graph.microsoft.com/v1.0/me/onenote/pages/page1/content"
    assert gc.patch_bodies() == [
        [{"target": "body", "action": "append", "content": "<div>hello &lt;x&gt;</div>"}]
    ]


def test_update_encodes_page_id():
    gc = FakeGC()
    _run(onenote_tools._tool_update_onenote_page, gc, SLASH_ID, "hello")
    assert "%2F" in gc.calls[0][1]


def test_update_routes_to_team_site():
    gc = FakeGC()
    _run(onenote_tools._tool_update_onenote_page, gc, "page1", "hello", site_id=SITE)
    assert "/sites/contoso.sharepoint.com%2Caaa%2Cbbb/onenote/pages/page1/content" in gc.calls[0][1]


def test_update_replace_element_returns_previous_html_and_fresh_outline():
    gc = FakeGC()
    result = _run(
        onenote_tools._tool_update_onenote_page,
        gc,
        "page1",
        "<table><tr><td>new</td></tr></table>",
        html=True,
        action="replace",
        target="table:{a}{7}",
    )
    assert gc.methods() == ["GET", "PATCH", "GET"]
    assert gc.patch_bodies() == [
        [{"target": "table:{a}{7}", "action": "replace", "content": "<table><tr><td>new</td></tr></table>"}]
    ]
    assert result["updated"] is True
    assert result["previous_html"].startswith("<table")
    assert "id=" not in result["previous_html"]
    assert [e["tag"] for e in result["elements"]] == ["h1", "p", "table"]


def test_update_previous_html_is_capped(monkeypatch):
    monkeypatch.setattr(page_edit, "MAX_PREVIOUS_HTML", 12)
    gc = FakeGC()
    result = _run(
        onenote_tools._tool_update_onenote_page, gc, "page1", "x", action="replace", target="table:{a}{7}"
    )
    assert len(result["previous_html"]) == 12


def test_update_unknown_target_sends_nothing():
    gc = FakeGC()
    result = _run(
        onenote_tools._tool_update_onenote_page, gc, "page1", "x", action="replace", target="p:{zz}{1}"
    )
    assert result["error"] == "target_not_found"
    assert "PATCH" not in gc.methods()


def test_update_replace_body_is_refused_before_any_call():
    gc = FakeGC()
    result = _run(
        onenote_tools._tool_update_onenote_page, gc, "page1", "x", action="replace", target="body"
    )
    assert result["error"] == "replace_body_not_allowed"
    assert gc.calls == []


def test_update_empty_replace_sends_empty_paragraph():
    gc = FakeGC()
    _run(onenote_tools._tool_update_onenote_page, gc, "page1", "", action="replace", target="p:{a}{3}")
    assert gc.patch_bodies()[0][0]["content"] == "<p></p>"


def test_update_title_needs_no_preread_and_returns_outline():
    gc = FakeGC()
    result = _run(
        onenote_tools._tool_update_onenote_page, gc, "page1", "New title", action="replace", target="title"
    )
    assert gc.methods() == ["PATCH", "GET"]
    assert gc.patch_bodies() == [[{"target": "title", "action": "replace", "content": "New title"}]]
    assert "previous_html" not in result
    assert "elements" in result


def test_update_insert_before_element():
    gc = FakeGC()
    _run(
        onenote_tools._tool_update_onenote_page,
        gc,
        "page1",
        "added",
        action="insert",
        target="p:{a}{3}",
        position="before",
    )
    assert gc.patch_bodies()[0][0] == {
        "target": "p:{a}{3}",
        "action": "insert",
        "content": "<p>added</p>",
        "position": "before",
    }


class _NotFound(RuntimeError):
    status_code = 404


def test_update_404_without_site_adds_team_hint():
    gc = FakeGC(patch_error=_NotFound("Graph API 404: not found"))
    result = _run(onenote_tools._tool_update_onenote_page, gc, "page1", "x")
    assert "404" in result["error"]
    assert "site_id" in result["hint"]


def test_update_404_with_site_has_no_hint():
    gc = FakeGC(patch_error=_NotFound("Graph API 404: not found"))
    result = _run(onenote_tools._tool_update_onenote_page, gc, "page1", "x", site_id=SITE)
    assert "hint" not in result


def test_update_other_graph_error_is_returned_as_error():
    class _Bad(RuntimeError):
        status_code = 400

    gc = FakeGC(patch_error=_Bad("Graph API 400: bad"))
    result = _run(onenote_tools._tool_update_onenote_page, gc, "page1", "x")
    assert result == {"error": "Graph API 400: bad"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_onenote_edit_tools.py -v`
Expected: the new update tests FAIL (`unexpected keyword argument 'site_id'`, and the default test fails because the current handler uses `urllib`).

- [ ] **Step 3: Write the implementation**

3a. Replace `_tool_update_onenote_page` in `web/skills/onenote/tools.py` (the whole function) with:

```python
def _tool_update_onenote_page(
    page_id: str,
    content: str,
    html: bool = False,
    site_id: str = "",
    action: str = "append",
    target: str = "body",
    position: str = "",
) -> dict:
    """Change an existing OneNote page: append (default), prepend, insert or
    replace content, or replace the title. Pass site_id for team notebooks."""
    from .._m365.helpers import get_skill_client

    try:
        ops = _pe.build_patch_ops(content, html, action, target, position)
    except _pe.EditError as e:
        return {"error": e.code, "message": e.message}

    gc = get_skill_client(ONENOTE_SKILLS_DIR)
    root = _onenote_root(site_id)
    result = {"updated": True, "page_id": page_id}
    try:
        if target not in ("body", "title"):
            current = _pe.element_html(
                _fetch_page_html(gc, root, page_id, include_ids=True), target
            )
            if current is None:
                return {
                    "error": "target_not_found",
                    "hint": "Read the page again; element ids change after an update.",
                }
            if action == "replace":
                result["previous_html"] = current[: _pe.MAX_PREVIOUS_HTML]
        gc._request(
            "PATCH",
            f"https://graph.microsoft.com/v1.0{root}/pages/{_eid(page_id)}/content",
            headers={**gc._headers(), "Content-Type": "application/json"},
            content=json.dumps(ops).encode(),
            label=f"onenote/pages/{page_id}/content",
        )
    except Exception as e:
        err = {"error": str(e)}
        if getattr(e, "status_code", 0) == 404 and not site_id:
            err["hint"] = (
                "If this page is in a SharePoint team notebook, pass its site_id "
                "from find_onenote_notebook."
            )
        return err

    if not (action == "append" and target == "body"):
        try:
            result.update(
                _pe.outline(_fetch_page_html(gc, root, page_id, include_ids=True))
            )
        except Exception as e:
            result["outline_error"] = f"Updated, but could not refresh the outline: {e}"
    return result
```

3b. Replace the `update_onenote_page` entry in `TOOL_DEFS` with:

```python
    {
        "name": "update_onenote_page",
        "description": "Change an existing OneNote page without rewriting it or creating a new one. Default: append content to the end. Other actions: prepend (add at the top), insert (before or after one element), replace (swap one element, or the title). To change existing content, first call read_onenote_page with include_ids=true and use an element id from the latest outline or update result as target; ids can change after every update, so never reuse older ids. Tables cannot be edited row by row: read the table with element_id, then replace the whole table with every row included. Replacing the body is refused. replace with empty content clears the element. Replace returns previous_html so the change can be undone. For SharePoint team notebooks pass site_id. Requires page_id from list_onenote_pages or a pinned page.",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {
                    "type": "string",
                    "description": "Page ID from list_onenote_pages or a pinned page",
                },
                "content": {
                    "type": "string",
                    "description": "New content (plain text or HTML). Empty with action=replace clears the element.",
                },
                "html": {
                    "type": "boolean",
                    "description": "If true, content is treated as HTML. Plain text is wrapped in a paragraph.",
                    "default": False,
                },
                "site_id": {
                    "type": "string",
                    "description": "SharePoint site id (same site_id the page came from). Omit or '' for personal notebooks.",
                    "default": "",
                },
                "action": {
                    "type": "string",
                    "enum": ["append", "prepend", "insert", "replace"],
                    "description": "What to do at the target. Default append.",
                    "default": "append",
                },
                "target": {
                    "type": "string",
                    "description": "'body' (default), 'title' (only with replace), or an element id from read_onenote_page(include_ids=true).",
                    "default": "body",
                },
                "position": {
                    "type": "string",
                    "enum": ["before", "after"],
                    "description": "For insert: put the content before or after the target element (default after).",
                },
            },
            "required": ["page_id", "content"],
        },
    },
```

3c. In `tests/test_graph_id_encoding.py`, replace `test_update_page_encodes_page_id` (lines 382-409) with:

```python
    def test_update_page_encodes_page_id(self):
        from skills.onenote import tools as onenote_tools

        gc = MagicMock()
        gc.get_token.return_value = "aigator-fake-api-key"
        gc._headers.return_value = {}
        captured_urls = []

        def fake_request(method, url, **kw):
            captured_urls.append(url)
            return MagicMock()

        gc._request.side_effect = fake_request

        with patch("skills._m365.helpers.get_skill_client", return_value=gc):
            onenote_tools._tool_update_onenote_page(SLASH_ID, "hello")

        assert captured_urls, "No Graph call captured"
        assert "%2F" in captured_urls[0], f"Literal '/' in URL: {captured_urls[0]}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_onenote_edit_tools.py tests/test_graph_id_encoding.py tests/test_onenote_page_edit.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the schema and CSRF checks**

Run: `python -m pytest tests/test_anthropic_tool_schema.py tests/test_csrf_route_inventory.py -q`
Expected: PASS (the new schemas are valid and no route was added).

- [ ] **Step 6: Commit**

```bash
git add web/skills/onenote/tools.py tests/test_onenote_edit_tools.py tests/test_graph_id_encoding.py
git commit -m "feat: let update_onenote_page replace, insert and prepend content, rename titles, and reach team notebooks"
```

---

### Task 5: Pins carry `site_id`

**Files:**

- Modify: `web/skills/onenote/tools.py` (`pin_onenote_page` schema and `_tool_pin_onenote_page`)
- Modify: `web/skills/onenote/state.py`
- Modify: `web/routes/chat.py` (pin line ~1325; legacy pin lines ~1501-1503)
- Test: `tests/test_onenote_pin_site.py`

**Interfaces:**

- Consumes: nothing from earlier tasks.
- Produces:
  - `state.pin_site_text(site_id: str) -> str` returning `", site_id: <id>"` or `""`.
  - `_tool_pin_onenote_page(page_id, page_title, notebook_name="", section_name="", site_id="")` storing `site_id` in the pin dict.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_onenote_pin_site.py`:

```python
"""Pinned OneNote pages carry a site_id so team pages can be edited."""

import pathlib

import pytest

from skills.onenote import state
from skills.onenote import tools as onenote_tools

CHAT_SRC = (pathlib.Path(__file__).parent.parent / "web" / "routes" / "chat.py").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _clean_pins():
    state.pinned_onenote_pages.clear()
    yield
    state.pinned_onenote_pages.clear()


def test_pin_stores_site_id():
    onenote_tools._tool_pin_onenote_page("p1", "Plan", "NB", "Sec", site_id="contoso,aaa,bbb")
    assert state.pinned_onenote_pages["plan"]["site_id"] == "contoso,aaa,bbb"


def test_pin_without_site_id_stores_empty_string():
    onenote_tools._tool_pin_onenote_page("p1", "Plan")
    assert state.pinned_onenote_pages["plan"]["site_id"] == ""


def test_pin_site_text():
    assert state.pin_site_text("contoso,aaa,bbb") == ", site_id: contoso,aaa,bbb"
    assert state.pin_site_text("") == ""
    assert state.pin_site_text(None) == ""


def test_chat_prompt_uses_pin_site_text_in_both_pin_lines():
    assert CHAT_SRC.count("pin_site_text(") == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_onenote_pin_site.py -v`
Expected: FAIL (`unexpected keyword argument 'site_id'`, no `pin_site_text`).

- [ ] **Step 3: Write the implementation**

3a. Replace `web/skills/onenote/state.py` with:

```python
"""Session-scoped OneNote pinned pages."""

pinned_onenote_pages: dict[str, dict] = {}


def pin_site_text(site_id: str | None) -> str:
    return f", site_id: {site_id}" if site_id else ""
```

3b. In `tools.py`, replace `_tool_pin_onenote_page` with:

```python
def _tool_pin_onenote_page(
    page_id: str,
    page_title: str,
    notebook_name: str = "",
    section_name: str = "",
    site_id: str = "",
) -> dict:
    """Pin a OneNote page for quick reference."""
    from .state import pinned_onenote_pages

    pinned_onenote_pages[page_title.lower()] = {
        "page_id": page_id,
        "title": page_title,
        "notebook": notebook_name,
        "section": section_name,
        "site_id": site_id,
    }
    return {
        "pinned": True,
        "title": page_title,
        "page_id": page_id,
        "hint": f"You can now reference this page by name. Currently pinned: {', '.join(p['title'] for p in pinned_onenote_pages.values())}",
    }
```

and in the `pin_onenote_page` schema `properties`, after `section_name`, add:

```python
                "site_id": {
                    "type": "string",
                    "description": "SharePoint site id if the page is in a team notebook (from the page's site_id). Omit or '' for personal notebooks.",
                    "default": "",
                },
```

3c. In `web/routes/chat.py`, add the import where the legacy state is imported and where context pins are built. Replace line 1325 with:

```python
                    from skills.onenote.state import pin_site_text as _pin_site_text
                    _site_txt = _pin_site_text(m.get("site_id"))
                    _pin_lines.append(f"- OneNote: \"{lbl}\" (page_id: {pid}, notebook: {m.get('notebook','?')}, section: {m.get('section','?')}{_site_txt}) \u2192 use update_onenote_page or read with this page_id{' and site_id' if _site_txt else ''}")
```

Replace lines 1499-1503 with:

```python
        from skills.onenote.state import pinned_onenote_pages as _pinned_onenote_pages, pin_site_text as _pin_site_text
        if _pinned_onenote_pages:
            pins = "\n".join(f"- \"{p['title']}\" (page_id: {p['page_id']}, notebook: {p.get('notebook','?')}, section: {p.get('section','?')}{_pin_site_text(p.get('site_id'))})"
                             for p in _pinned_onenote_pages.values())
            system += f"\n\n\U0001f4cc PINNED ONENOTE PAGES (use update_onenote_page with these page_ids directly \u2014 no need to re-navigate; when a pin has a site_id, pass it to read_onenote_page and update_onenote_page):\n{pins}"
```

Note: `pin_site_text(` appears once per replaced line in the call expressions (the import lines use `pin_site_text as`, which does not match `pin_site_text(`), so the source-count test sees exactly 2 calls. If the count differs, adjust the code, not the test.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_onenote_pin_site.py tests/test_anthropic_tool_schema.py -v`
Expected: all PASS. Also run `python -c "import ast,sys; ast.parse(open('web/routes/chat.py',encoding='utf-8').read())"` to confirm chat.py still parses.

- [ ] **Step 5: Commit**

```bash
git add web/skills/onenote/state.py web/skills/onenote/tools.py web/routes/chat.py tests/test_onenote_pin_site.py
git commit -m "feat: keep site_id on pinned OneNote pages so team pages can be edited"
```

---

### Task 6: Skill text, full suite, and manual run on real notebooks

**Files:**

- Modify: `web/skills/onenote/SKILL.md`
- Modify: `docs/superpowers/specs/2026-10-14-onenote-page-editing-design.md` (status line)

**Interfaces:**

- Consumes: the tools from Tasks 3-5.
- Produces: nothing later tasks use.

- [ ] **Step 1: Update the skill text**

Replace the body of `web/skills/onenote/SKILL.md` after the frontmatter with:

```markdown
# OneNote Workflow

- "Create a page" → call list_onenote_notebooks to find the right notebook, then list_onenote_sections to get the section_id, then create_onenote_page.
- "Show my notebooks / sections / pages" → call list_onenote_notebooks → list_onenote_sections → list_onenote_pages as needed.
- "Add to a page" → if the page is pinned, use update_onenote_page directly with the pinned page_id. If not pinned, navigate to find the page_id first, then call update_onenote_page. The default action appends to the end.
- "Change something already on a page" (fix a typo, tick a to-do, add a table row, move a line, rename the page) → do NOT create a new page and do NOT append a duplicate:
  1. read_onenote_page with include_ids=true to get the outline (element ids).
  2. For a table, read_onenote_page with element_id=<table id> to get its full HTML.
  3. update_onenote_page with action=replace and target=<element id>. For a table, send the whole table with every row (cells cannot be edited one by one). To remove an element, replace it with empty content. To add next to an element, use action=insert with position before or after. To rename the page, use target=title with action=replace.
  4. The result returns a fresh outline. Use ids from the latest outline only; ids can change after every update. If you get target_not_found, read the page again.
  5. Never replace the body. Replace returns previous_html if the change has to be undone.
- Team notebooks: pass the notebook's site_id (from find_onenote_notebook or the pin) to every read and update call. A team page is reached through its section, not by listing a site's notebooks.
- "Pin this page" → after finding a page, call pin_onenote_page (with its site_id for team notebooks) so the user can reference it by name in future messages without re-navigating.
- When a page is pinned, ALWAYS use update_onenote_page directly — NEVER re-navigate through notebooks/sections.
```

- [ ] **Step 2: Mark the spec approved**

In `docs/superpowers/specs/2026-10-14-onenote-page-editing-design.md` change `**Status:** Draft, awaiting review.` to `**Status:** Approved. Plan: docs/superpowers/plans/2026-10-17-onenote-page-editing.md.`

Run: `npx prettier --check docs/superpowers/specs/2026-10-14-onenote-page-editing-design.md docs/superpowers/plans/2026-10-17-onenote-page-editing.md web/skills/onenote/SKILL.md`
Expected: all matched files use Prettier code style. If not, run `npx prettier --write` on the listed files.

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS. Fix any failure caused by this change (for example a test that counts onenote tool properties); do not touch `tests/csrf_route_baseline.txt`.

- [ ] **Step 4: Manual run on real notebooks**

Start the app and use the assistant (not scripts) with a scratch page the assistant creates itself. Do this once for a personal notebook (section "Gator Notes") and once for the team section "Start Here" in the AMD TPM Notebook on the SiloEngineering site (`site_id` `amdcloud.sharepoint.com,74cd1df3-9aa7-4ffb-816e-ef2b5162b0a4,9107b037-0cb1-47e5-b5aa-8e7cc37e5c39`):

1. Ask: "Create a page titled AIGATOR-EDIT-TEST with a heading, two paragraphs, a bulleted list, and a 2-row table." Expected: page created.
2. Ask: "In that page, fix paragraph two to say 'EDITED', add a third row to the table, and move the second paragraph's old text into the list as a new item." Expected: one outline read, one `replace` per changed element, no new page. Open the page in OneNote and confirm the edits and that the page was not duplicated.
3. Ask: "Rename that page to AIGATOR-EDIT-TEST 2." Expected: title changes.
4. Ask: "Remove the first paragraph." Expected: the paragraph is cleared (blank line).
5. Ask: "Replace the whole page body." Expected: the assistant refuses or replaces elements individually; the page is never wiped.
6. Delete the scratch page in OneNote when done.

Expected for the team run: the same results with `site_id` passed on every call.

- [ ] **Step 5: Commit**

```bash
git add web/skills/onenote/SKILL.md docs/superpowers/specs/2026-10-14-onenote-page-editing-design.md docs/superpowers/plans/2026-10-17-onenote-page-editing.md
git commit -m "docs: OneNote edit workflow in the skill text, approved spec and plan"
```

---

## Self-review

- **Spec coverage:** Design 1 (`include_ids`, `element_id`, paging, caps, errors) → Tasks 1 and 3. Design 2 (`site_id`, `action`, `target`, `position`, defaults identical, `<p>` wrapping, title escaping, body-replace refused, empty content clears, pre-read and `target_not_found`, `previous_html`, fresh outline, `gc._request`, 404 hint) → Tasks 2 and 4. Design 3 (`_onenote_root`, pins with `site_id`, prompt lines) → Tasks 3-5. Design 4 (skill text and tool descriptions) → Tasks 3, 4 and 6. Design 5 (guards: schema enums, no new routes, CSRF inventory) → Task 4 step 5. Testing section → each task's tests plus Task 6 manual run. Out-of-scope items are not touched.
- **Placeholders:** none. Every code step has the code.
- **Type consistency:** `outline`/`element_html`/`build_patch_ops`/`EditError` names and signatures are the same in Tasks 1-4; `_fetch_page_html(gc, root, page_id, include_ids)` is defined in Task 3 and used in Task 4; `pin_site_text` defined and used in Task 5.
- **Spec deviation to note:** the spec says `replace` removes with empty content "(sends `<p></p>`)" after the live test; `insert` on `body` and empty content on non-replace actions are refused with `insert_needs_element` and `content_required`, which the spec does not name but follows from the Graph results.
