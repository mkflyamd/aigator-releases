"""Regression test: a refused Confluence splice must say WHERE the imbalance is.

Before this fix, _structural_diagnosis only counted tags in the submitted
fragment. A balanced fragment spliced mid-element (the off-by-one </li> case)
produced an empty fragment_tag_counts and named nothing actionable, so retries
with the same fragment looked like "no progress". The diagnosis now reports
which_failed (fragment vs assembly) plus whole-body tag counts.
"""
from unittest.mock import patch

from skills.confluence.tools import _structural_diagnosis, _tool_patch_confluence_page


def test_malformed_fragment_blamed_on_fragment():
    fragment = "<ul><li>orphan"  # missing </li></ul>
    new_body = "<p>before</p>" + fragment + "<p>after</p>"
    diag = _structural_diagnosis(fragment, new_body)
    assert diag["fragment_well_formed"] is False
    assert diag["which_failed"] == "fragment"
    assert diag["fragment_tag_counts"]["li"] == {"open": 1, "close": 0}


def test_balanced_fragment_spliced_mid_element_blamed_on_assembly():
    # Fragment is well-formed on its own ...
    fragment = "<li>new item</li>"
    diag_frag = _structural_diagnosis(fragment, fragment)
    assert diag_frag["fragment_well_formed"] is True
    # ... but the assembled body carries an off-by-one </li> the fragment alone
    # cannot reveal — that's an assembly failure, surfaced via body_tag_counts.
    new_body = "<ul><li>existing" + fragment + "</ul>"  # one </li> short
    diag = _structural_diagnosis(fragment, new_body)
    assert diag["fragment_well_formed"] is True
    assert diag["which_failed"] == "assembly"
    assert diag["body_tag_counts"]["li"] == {"open": 2, "close": 1}


def test_malformed_fragment_rejected_before_splice():
    # A malformed fragment must be blamed on the fragment up front — never let it
    # reach the assembly check where the error reads as a splice corruption, which
    # sends callers into a retry spiral resubmitting the same broken markup.
    with patch("skills.confluence.tools.confluence_api") as api:
        api.return_value = {
            "version": {"number": 3}, "title": "Doc",
            "body": {"storage": {"value": "<p>existing</p>"}},
        }
        result = _tool_patch_confluence_page(
            "123", find="existing", content="<ul><li>orphan", mode="insert_after",
        )
    assert result["patch_applied"] is False
    assert result["which_failed"] == "fragment"
    assert result["fragment_tag_counts"]["li"] == {"open": 1, "close": 0}
    # The page must NOT have been written.
    assert not any(c.args and c.args[0] == "PUT" for c in api.call_args_list)


def test_silent_no_op_reports_failure_when_version_not_incremented():
    # Confluence returns 200 with the SAME version when a save normalizes to
    # byte-identical storage — a silent no-op. The tool must not report success:
    # it returns patch_applied:false + reason and echoes base/returned version so
    # the no-op is self-evident from one result (issue #79).
    def fake_api(method, path, *args, **kwargs):
        if method == "GET":
            return {"version": {"number": 163}, "title": "Doc",
                    "body": {"storage": {"value": "<p>existing</p>"}}}
        # PUT "succeeds" but version stays pinned at 163 (no increment)
        return {"id": "123", "title": "Doc", "version": {"number": 163}, "_links": {"webui": "/x"}}

    with patch("skills.confluence.tools.confluence_api", side_effect=fake_api), \
         patch("skills.confluence.tools.confluence_browse_url", return_value="https://wiki"):
        result = _tool_patch_confluence_page(
            "123", find="existing", content="<p>new</p>", mode="insert_after",
        )
    assert result["patch_applied"] is False
    assert result["reason"] == "no_change_detected"
    assert result["base_version"] == 163
    assert result["version"] == 163


def test_successful_patch_echoes_base_and_new_version():
    # A real save must echo both base_version and the incremented version so a
    # no-op vs a real change is distinguishable from a single result (issue #79).
    def fake_api(method, path, *args, **kwargs):
        if method == "GET":
            return {"version": {"number": 163}, "title": "Doc",
                    "body": {"storage": {"value": "<p>existing</p>"}}}
        return {"id": "123", "title": "Doc", "version": {"number": 164}, "_links": {"webui": "/x"}}

    with patch("skills.confluence.tools.confluence_api", side_effect=fake_api), \
         patch("skills.confluence.tools.confluence_browse_url", return_value="https://wiki"):
        result = _tool_patch_confluence_page(
            "123", find="existing", content="<p>new</p>", mode="insert_after",
        )
    assert result["patch_applied"] is True
    assert result["base_version"] == 163
    assert result["version"] == 164


def test_identity_splice_short_circuits_before_put():
    # If the assembled body is byte-identical to the current body, fail fast with
    # no_change_detected and never issue the PUT (issue #79, #3).
    calls = []

    def fake_api(method, path, *args, **kwargs):
        calls.append(method)
        if method == "GET":
            return {"version": {"number": 163}, "title": "Doc",
                    "body": {"storage": {"value": "<p>existing</p>"}}}
        return {"id": "123", "title": "Doc", "version": {"number": 164}, "_links": {"webui": "/x"}}

    with patch("skills.confluence.tools.confluence_api", side_effect=fake_api), \
         patch("skills.confluence.tools.confluence_browse_url", return_value="https://wiki"):
        result = _tool_patch_confluence_page(
            "123", find="<p>existing</p>", content="<p>existing</p>", mode="replace",
        )
    assert result["patch_applied"] is False
    assert result["reason"] == "no_change_detected"
    assert "PUT" not in calls


def test_successful_patch_emits_no_pane_signal():
    # A direct patch needs no human review, so a successful save must NOT pop a
    # pane mid-stream — the change already landed and the chat reports it. Popping
    # an (empty) pane mid-stream is noise the user can't act on.
    def fake_api(method, path, *args, **kwargs):
        if method == "GET":
            return {"version": {"number": 3}, "title": "Doc",
                    "body": {"storage": {"value": "<p>existing</p>"}}}
        return {"id": "123", "title": "Doc", "version": {"number": 4}, "_links": {"webui": "/x"}}

    with patch("skills.confluence.tools.confluence_api", side_effect=fake_api), \
         patch("skills.confluence.tools.confluence_browse_url", return_value="https://wiki"):
        result = _tool_patch_confluence_page(
            "123", find="existing", content="<p>new</p>", mode="insert_after",
        )
    assert result["patch_applied"] is True
    assert "_pane" not in result


def test_failed_save_does_not_auto_open_edit_form():
    # The patch tool NEVER auto-opens the HITL form. An API rejection returns an
    # actionable error + suggested_next(confluence_open_edit_form); the model calls
    # that tool explicitly if a human rewrite is warranted. Auto-popping the form
    # on intermediate failures the model recovers from was the misfire source.
    def fake_api(method, path, *args, **kwargs):
        if method == "GET":
            return {"version": {"number": 3}, "title": "Doc",
                    "body": {"storage": {"value": "<p>existing</p>"}}}
        raise RuntimeError("Confluence parse error [12,5]")

    with patch("skills.confluence.tools.confluence_api", side_effect=fake_api), \
         patch("skills.confluence.tools.confluence_browse_url", return_value="https://wiki"):
        result = _tool_patch_confluence_page(
            "123", find="existing", content="<p>new</p>", mode="insert_after",
        )
    assert result["patch_applied"] is False
    assert "_pane" not in result


def test_find_not_found_does_not_auto_open_edit_form():
    # find-not-found is fully model-recoverable (retry with a better anchor) — it
    # must not pop the HITL form mid-stream.
    with patch("skills.confluence.tools.confluence_api") as api:
        api.return_value = {"version": {"number": 3}, "title": "Doc",
                            "body": {"storage": {"value": "<p>existing</p>"}}}
        result = _tool_patch_confluence_page(
            "123", find="nonexistent text", content="<p>new</p>", mode="insert_after",
        )
    assert "_pane" not in result
    assert not any(c.args and c.args[0] == "PUT" for c in api.call_args_list)


def test_clean_assembled_body_reports_no_tag_imbalance():
    # _structural_diagnosis runs only after a refusal in production, but a clean
    # assembled body must not invent a body_tag_counts imbalance.
    fragment = "<li>new</li>"
    new_body = "<ul><li>a</li>" + fragment + "</ul>"
    diag = _structural_diagnosis(fragment, new_body)
    assert diag["fragment_well_formed"] is True
    assert "body_tag_counts" not in diag
