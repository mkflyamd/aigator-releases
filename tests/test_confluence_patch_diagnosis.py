"""Regression tests for patch_confluence_page structural diagnosis + repair.

Derived from the real failing case on page 1424041584 (excerpt macro
29488222-9871-4bb9-94fd-4f062224deb0): a large nested list where the
"Config / solution specifics" <li> was nested one level too deep instead of
sitting as a sibling section. The strict-XHTML pre-flight must (a) refuse the
malformed splice, (b) name the offending <li> precisely, and (c) offer a
text-preserving repair suggestion — never auto-commit it.

The structural shape below mirrors the fixture; swap in the byte-for-byte
HTML of the live failing/passing content if even tighter coverage is wanted.
"""
import pytest

pytest.importorskip("lxml")  # diagnosis of <li>/<ul> nesting requires the strict XML parse

from skills.confluence.tools import (  # noqa: E402
    _structural_errors,
    _fragment_tag_counts,
    _find_unbalanced_anchor,
    _repair_suggestion,
    _structural_diagnosis,
    _find_in_body,
    _canonical_matches,
    _describe_location,
    _find_element_by_local_id,
    _PRECISE_MATCH,
    _FUZZY_MATCH,
)

_MACRO = (
    '<ac:structured-macro ac:name="excerpt" '
    'ac:macro-id="29488222-9871-4bb9-94fd-4f062224deb0"><ac:rich-text-body>\n'
    '<ul><li><p><strong>Kimi K2.6 Kernel Optimization Targets</strong></p>\n'
    '<ul>\n'
    '<li><p><strong>Workloads Info</strong></p>'
    '<ul><li>Target uplift</li><li>Uplift / gap to target</li></ul></li>\n'
    '{CFG}\n'
    '</ul>\n'
    '</li></ul>\n'
    '</ac:rich-text-body></ac:structured-macro>'
)

# Config <li> never closed (missing </li> after its inner </ul>) — nested too deep.
_FAILING = _MACRO.replace(
    "{CFG}",
    '<li><p><strong>Config / solution specifics:</strong></p><ul><li>detail</li></ul>',
)
# Config <li> properly closed — a sibling section, the version that saved cleanly.
_PASSING = _MACRO.replace(
    "{CFG}",
    '<li><p><strong>Config / solution specifics:</strong></p><ul><li>detail</li></ul></li>',
)


def test_passing_content_validates_clean():
    assert _structural_errors(_PASSING) is None


def test_failing_content_is_refused():
    err = _structural_errors(_FAILING)
    assert err is not None
    assert "tag mismatch" in err["message"].lower()


def test_fragment_counts_flag_the_extra_li():
    counts = _fragment_tag_counts(_FAILING)
    assert "li" in counts
    assert counts["li"]["open"] != counts["li"]["close"]
    # the balanced version has matched counts
    assert "li" not in _fragment_tag_counts(_PASSING)


def test_anchor_names_the_config_li():
    anchor = _find_unbalanced_anchor(_FAILING)
    assert anchor is not None
    assert anchor["tag"] == "li"
    assert "Config / solution specifics" in anchor["text"]


def test_repair_suggestion_preserves_text_and_revalidates():
    repair = _repair_suggestion(_FAILING)
    assert repair is not None
    assert repair["text_preserved"] is True
    # the suggestion is balanced storage format
    assert _structural_errors(repair["repaired_body_suggestion"]) is None


def test_structural_diagnosis_is_complete():
    diag = _structural_diagnosis(_FAILING, _FAILING)
    assert "fragment_tag_counts" in diag
    assert "unbalanced_node" in diag
    assert "parse_errors" in diag and diag["parse_errors"]


# --- Matcher: precise-first ordering + canonical tolerance ----------------

# A body with two table rows; the *intended* anchor is the second row, deep at
# the bottom. The find is the exact tail of that row. A heading sits above the
# first row, so the old macro/heading-first order risked anchoring up there.
_BODY = (
    '<h2>AWS summary</h2>'
    '<table><tbody>'
    '<tr><td><p ac:local-id="row-aws">AWS</p></td></tr>'
    '</tbody></table>'
    '<h2>Workloads</h2>'
    '<table><tbody>'
    '<tr><td><p ac:local-id="row-fw">Fireworks</p></td></tr>'
    '</tbody></table>'
)


def test_exact_match_wins_over_fuzzy():
    needle = '<p ac:local-id="row-fw">Fireworks</p>'
    start, end, mt = _find_in_body(needle, _BODY)
    assert mt == "exact"
    assert _BODY[start:end] == needle


def test_canonical_match_tolerates_entities_and_attr_order():
    # Body uses &nbsp; entity, self-closing <col/>, attr order style->ac:foo.
    body = (
        '<table data-x="1"><col style="w" ac:foo="b"/>'
        '<tbody><tr><td>A&nbsp;B</td></tr></tbody></table>'
    )
    # Needle: contiguous run,   literal, <col> not self-closed, attrs
    # reordered. Exact must fail; canonical must win.
    needle = (
        '<col ac:foo="b" style="w">'
        '<tbody><tr><td>A B</td></tr></tbody></table>'
    )
    assert body.find(needle) == -1  # exact would fail
    start, end, mt = _find_in_body(needle, body)
    assert mt == "canonical"
    assert body[start:start + 4] == "<col"
    assert body[end - 8:end] == "</table>"


def test_canonical_classified_precise_not_fuzzy():
    assert "canonical" in _PRECISE_MATCH
    assert "canonical" not in _FUZZY_MATCH


def test_heading_only_find_is_fuzzy():
    start, end, mt = _find_in_body("workloads", _BODY)
    assert mt == "heading-section"
    assert mt in _FUZZY_MATCH


def test_describe_location_reports_heading_and_local_id():
    needle = '<p ac:local-id="row-fw">Fireworks</p>'
    start, _end, _mt = _find_in_body(needle, _BODY)
    loc = _describe_location(_BODY, start)
    assert loc.get("nearest_heading") == "Workloads"


def test_describe_location_reports_enclosing_macro():
    body = (
        '<ac:structured-macro ac:name="excerpt" ac:macro-id="abc-123">'
        '<ac:rich-text-body><p>inside</p></ac:rich-text-body>'
        '</ac:structured-macro>'
    )
    start = body.find("<p>inside")
    loc = _describe_location(body, start)
    assert loc.get("enclosing_macro_id") == "abc-123"


# --- Structure-aware insert by local-id -----------------------------------
# Real Confluence emits BARE `local-id` on body content (table/tr/td/p/li/ul/h*)
# and `ac:local-id` on macros and some elements. The anchor must handle both.
_TABLE = (
    '<table local-id="tbl-1"><tbody>'
    '<tr local-id="row-aws"><td local-id="c1"><p>AWS</p></td></tr>'
    '<tr local-id="row-fw"><td local-id="c2"><p>Fireworks</p></td></tr>'
    '</tbody></table>'
)


def test_local_id_bare_form_resolves_whole_row():
    span = _find_element_by_local_id(_TABLE, "row-fw")
    assert span not in (None, "multiple")
    start, end = span
    assert _TABLE[start:end] == '<tr local-id="row-fw"><td local-id="c2"><p>Fireworks</p></td></tr>'


def test_local_id_ac_prefixed_form_resolves():
    body = '<p ac:local-id="para-x">hello</p>'
    start, end = _find_element_by_local_id(body, "para-x")
    assert body[start:end] == body


def test_local_id_missing_returns_none():
    assert _find_element_by_local_id(_TABLE, "does-not-exist") is None


def test_local_id_duplicate_returns_multiple():
    dup = '<p local-id="dup">a</p><p local-id="dup">b</p>'
    assert _find_element_by_local_id(dup, "dup") == "multiple"


def test_local_id_void_element_is_just_the_tag():
    body = '<p>x</p><hr local-id="h1" /><p>y</p>'
    start, end = _find_element_by_local_id(body, "h1")
    assert body[start:end] == '<hr local-id="h1" />'


def test_local_id_nested_same_tag_finds_correct_close():
    # Outer ul carries the id; it contains a nested ul. Must capture through the
    # OUTER </ul>, not the inner one.
    body = (
        '<ul local-id="outer"><li>a'
        '<ul local-id="inner"><li>b</li></ul>'
        '</li></ul><p>after</p>'
    )
    start, end = _find_element_by_local_id(body, "outer")
    assert body[start:end].endswith('</li></ul>')
    assert body[end:] == '<p>after</p>'


def test_local_id_insert_after_splices_outside_element():
    span = _find_element_by_local_id(_TABLE, "row-aws")
    start, end = span
    new_row = '<tr local-id="row-new"><td><p>New</p></td></tr>'
    spliced = _TABLE[:end] + new_row + _TABLE[end:]
    # New row lands between the AWS row and the Fireworks row, not nested inside.
    assert '</tr>' + new_row + '<tr local-id="row-fw"' in spliced
