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
