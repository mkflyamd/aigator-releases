"""Issue #54: the Jira/Confluence config inputs must use generic placeholders,
not AMD-specific examples, now that AI Gator is open-source."""

import pathlib

_INDEX = pathlib.Path(__file__).parent.parent / "web" / "static" / "index.html"


def _atlassian_block() -> str:
    html = _INDEX.read_text(encoding="utf-8")
    # Narrow to the Atlassian inputs so unrelated AMD references elsewhere in
    # the file (gateway example, GitHub Enterprise) don't affect this check.
    start = html.index("atlassian-email-input")
    end = html.index("atlassian-save-btn")
    return html[start:end]


def test_atlassian_inputs_have_no_amd_references():
    block = _atlassian_block()
    lowered = block.lower()
    assert "amd.com" not in lowered
    assert "amd-hub" not in lowered
    assert "amd.atlassian.net" not in lowered


def _site_placeholders() -> str:
    js = (_INDEX.parent / "app.js").read_text(encoding="utf-8")
    start = js.index("const ATLASSIAN_SITE_PLACEHOLDERS")
    return js[start : js.index("};", start)]


def test_atlassian_inputs_use_generic_examples():
    block = _atlassian_block()
    assert "you@company.com" in block
    placeholders = _site_placeholders()
    assert "your-org.atlassian.net" in placeholders
    assert "amd" not in placeholders.lower()


def test_atlassian_url_inputs_not_prefilled_with_value():
    """URL fields should use placeholders, not a hardcoded value= that submits
    an org-specific URL by default."""
    block = _atlassian_block()
    assert 'value="https://' not in block
