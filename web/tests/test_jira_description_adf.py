"""Regression test: Jira Cloud (API v3) requires `description` as ADF, not a string.

A plain-string description produced HTTP 400 "Operation value must be an Atlassian
Document", which the create form surfaced as "Required fields are missing" with a red
box on Description. The fix converts the description to ADF on Cloud via _build_adf_doc.
"""
from skills.jira.tools import _build_adf_doc, _build_adf_comment


def test_adf_doc_has_required_envelope():
    doc = _build_adf_doc("Hello world")
    assert doc["type"] == "doc"
    assert doc["version"] == 1
    assert isinstance(doc["content"], list) and doc["content"]


def test_multiline_becomes_separate_paragraphs():
    doc = _build_adf_doc("Context\nRouted from the engagement.\nThird line.")
    assert [p["type"] for p in doc["content"]] == ["paragraph", "paragraph", "paragraph"]
    assert doc["content"][0]["content"][0]["text"] == "Context"


def test_empty_line_yields_empty_text_node_not_crash():
    doc = _build_adf_doc("a\n\nb")
    # blank line still produces a paragraph with an empty text node (valid ADF)
    assert len(doc["content"]) == 3
    assert doc["content"][1]["content"][0]["text"] == ""


def test_doc_builder_is_the_general_comment_builder():
    # description reuses the mention-aware comment builder; mentions still convert
    doc = _build_adf_doc("ping @712020:abc-def")
    nodes = doc["content"][0]["content"]
    assert any(n["type"] == "mention" for n in nodes)
    assert _build_adf_doc is _build_adf_comment
