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
        ({"action": "replace", "target": "title", "content": ""}, "content_required"),
        ({"action": "replace", "target": "title", "content": "  \n "}, "content_required"),
        ({"action": "append", "target": "body", "content": ""}, "content_required"),
        ({"action": "append", "target": "body", "content": "  \n "}, "content_required"),
    ],
)
def test_build_patch_ops_refusals(kwargs, code):
    kwargs.setdefault("content", "x")
    with pytest.raises(page_edit.EditError) as exc:
        page_edit.build_patch_ops(**kwargs)
    assert exc.value.code == code


def _sig_page(*blocks):
    return "<html><body><div id=\"d1\">" + "".join(blocks) + "</div></body></html>"


def test_expected_signature_replace_removes_span_and_adds_new():
    page = _sig_page('<h2 id="a">Old</h2>', '<ul id="b"><li id="c">x</li></ul>', '<p id="d">tail</p>')
    exp = page_edit.expected_signature(page, "<h2>New</h2>", "replace", "a")
    assert exp == [("h2", "New"), ("ul", "x"), ("li", "x"), ("p", "tail")]


def test_expected_signature_insert_before_and_after():
    page = _sig_page('<p id="a">one</p>', '<p id="b">two</p>')
    before = page_edit.expected_signature(page, "<p>n</p>", "insert", "b", "before")
    after = page_edit.expected_signature(page, "<p>n</p>", "insert", "b", "after")
    assert before == [("p", "one"), ("p", "n"), ("p", "two")]
    assert after == [("p", "one"), ("p", "two"), ("p", "n")]


def test_expected_signature_prepend_body_and_unpredictable_cases():
    page = _sig_page('<p id="a">one</p>')
    assert page_edit.expected_signature(page, "<p>n</p>", "prepend", "body") == [("p", "n"), ("p", "one")]
    assert page_edit.expected_signature(page, "<p>n</p>", "append", "a") is None
    assert page_edit.expected_signature(page, "<p>n</p>", "replace", "missing") is None


def test_signature_ignores_whitespace_blank_paragraphs_and_table_cells():
    page = _sig_page(
        '<p id="a">Hello   <span>big</span>\n world</p>',
        '<p id="b"></p>',
        '<table id="t"><tr id="r"><td id="c"><p id="e">cell</p></td></tr></table>',
    )
    assert page_edit.signature(page) == [("p", "Hellobigworld"), ("table", "cell")]


def test_compare_signatures_reports_only_the_differing_stretch():
    exp = [("h2", "Done"), ("ul", "x"), ("p", "tail")]
    act = [("ul", "x"), ("h2", "Done"), ("p", "tail")]
    diff = page_edit.compare_signatures(exp, act)
    assert diff["expected"][0].startswith("h2: Done")
    assert diff["actual"][0].startswith("ul: x")
    assert page_edit.compare_signatures(exp, list(exp)) is None
