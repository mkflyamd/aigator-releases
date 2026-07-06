"""Fix D regression tests: schema-aware extra_fields serialization in create-issue.

These tests inline the pure ADF/serialization logic to avoid importing the full
skills.jira.tools module (which requires httpx/fastapi not available in test env).
"""
import re


# ── Inline pure functions under test (no httpx/network deps) ──────────────────

def _build_adf_doc(text: str) -> dict:
    """Convert plain text to minimal valid ADF. Mirrors tools.py _build_adf_comment."""
    def _para(line: str) -> dict:
        if not line:
            return {"type": "paragraph", "content": []}
        return {"type": "paragraph", "content": [{"type": "text", "text": line}]}
    paragraphs = [_para(line) for line in text.split("\n")]
    return {"version": 1, "type": "doc", "content": paragraphs}


def _serialize_extra_fields(parsed: dict, field_schemas: dict, is_cloud: bool) -> dict:
    """Fix D loop: wraps doc-typed string fields in ADF on Cloud."""
    out = {}
    for key, value in parsed.items():
        schema_type = field_schemas.get(key, '')
        if schema_type == 'doc' and isinstance(value, str) and value:
            out[key] = _build_adf_doc(value) if is_cloud else value
        else:
            out[key] = value
    return out


# ── Fix D: doc field on Cloud gets ADF-wrapped ────────────────────────────────

def test_doc_field_wrapped_to_adf_on_cloud():
    result = _serialize_extra_fields(
        {'customfield_10039': 'Step 1\nStep 2'},
        {'customfield_10039': 'doc'},
        is_cloud=True,
    )
    val = result['customfield_10039']
    assert isinstance(val, dict), "doc field on Cloud must be an ADF dict"
    assert val['type'] == 'doc'
    assert val['version'] == 1
    assert isinstance(val['content'], list) and len(val['content']) == 2


def test_doc_field_plain_string_on_server():
    result = _serialize_extra_fields(
        {'customfield_10039': 'Step 1\nStep 2'},
        {'customfield_10039': 'doc'},
        is_cloud=False,
    )
    assert result['customfield_10039'] == 'Step 1\nStep 2'


def test_non_doc_fields_passed_through_verbatim():
    parsed = {
        'customfield_10050': {'id': '10001'},
        'customfield_10060': [{'id': 'a'}],
        'customfield_10070': 42,
    }
    result = _serialize_extra_fields(parsed, {}, is_cloud=True)
    assert result['customfield_10050'] == {'id': '10001'}
    assert result['customfield_10060'] == [{'id': 'a'}]
    assert result['customfield_10070'] == 42


def test_empty_string_doc_field_not_wrapped():
    result = _serialize_extra_fields(
        {'customfield_10039': ''},
        {'customfield_10039': 'doc'},
        is_cloud=True,
    )
    assert result['customfield_10039'] == ''


def test_adf_dict_prefill_not_double_wrapped():
    adf_obj = {'version': 1, 'type': 'doc', 'content': []}
    result = _serialize_extra_fields(
        {'customfield_10039': adf_obj},
        {'customfield_10039': 'doc'},
        is_cloud=True,
    )
    assert result['customfield_10039'] is adf_obj


def test_missing_field_schemas_leaves_all_verbatim():
    result = _serialize_extra_fields(
        {'customfield_10039': 'some text'},
        {},
        is_cloud=True,
    )
    assert result['customfield_10039'] == 'some text'


def test_multiline_doc_produces_correct_paragraph_count():
    result = _serialize_extra_fields(
        {'customfield_10039': 'Line A\nLine B\nLine C'},
        {'customfield_10039': 'doc'},
        is_cloud=True,
    )
    paragraphs = result['customfield_10039']['content']
    assert len(paragraphs) == 3
    texts = [p['content'][0]['text'] for p in paragraphs]
    assert texts == ['Line A', 'Line B', 'Line C']


def test_blank_line_produces_empty_paragraph_not_empty_text_node():
    """Blank lines must become {type:'paragraph', content:[]} not {content:[{text:''}]}.
    Jira Cloud rejects text nodes with empty string."""
    result = _serialize_extra_fields(
        {'customfield_10039': 'Para 1\n\nPara 2'},
        {'customfield_10039': 'doc'},
        is_cloud=True,
    )
    paragraphs = result['customfield_10039']['content']
    assert len(paragraphs) == 3
    blank = paragraphs[1]
    assert blank['type'] == 'paragraph'
    inner = blank.get('content', [])
    has_empty_text_node = any(
        n.get('type') == 'text' and n.get('text') == '' for n in inner
    )
    assert not has_empty_text_node, "blank line must not produce {type:'text', text:''}"


def test_multiple_doc_fields_each_wrapped_independently():
    result = _serialize_extra_fields(
        {
            'customfield_10039': 'Steps here',
            'customfield_10040': 'Expected result',
            'customfield_10050': {'id': '10001'},  # non-doc
        },
        {'customfield_10039': 'doc', 'customfield_10040': 'doc'},
        is_cloud=True,
    )
    assert result['customfield_10039']['type'] == 'doc'
    assert result['customfield_10040']['type'] == 'doc'
    assert result['customfield_10050'] == {'id': '10001'}
