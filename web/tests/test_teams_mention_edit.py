"""Issues #90, #92, #119: Teams @mention bugs — static source analysis + import tests.

#90  — AI-composed messages insert @mentions as plain text (not real mention entities)
#92  — @mention loses rich formatting after message edit
#119 — Editing a Teams message silently drops @mentions

Root cause: TeamsEditRequest had no `mentions` field, and there was no shared helper
to serialize Skype mention objects — so the backend never built or sent mention data
on PATCH. The send path had inline serialization; edit had nothing.

These tests verify:
1. TeamsEditRequest accepts a mentions list (was: only `body: str`)
2. A shared _build_skype_mentions() helper exists and produces the correct Skype
   format: [{itemid, mri, displayName}]
3. The edit endpoint body includes mention serialization (same logic as send)
"""

import pathlib
import importlib

SRC = (pathlib.Path(__file__).parent.parent / "routes" / "teams.py").read_text(encoding="utf-8")


class TestTeamsEditRequestHasMentionsField:

    def test_edit_request_model_has_mentions_field(self):
        """TeamsEditRequest must declare a `mentions` field."""
        assert "class TeamsEditRequest" in SRC
        edit_model_start = SRC.find("class TeamsEditRequest")
        # Next class starts the boundary
        next_class = SRC.find("\nclass ", edit_model_start + 1)
        model_body = SRC[edit_model_start:next_class if next_class != -1 else edit_model_start + 500]
        assert "mentions" in model_body, (
            "TeamsEditRequest must have a `mentions` field — "
            "without it the edit endpoint can never receive or serialize mention data."
        )

    def test_edit_request_mentions_defaults_to_empty_list(self):
        """mentions field must default to [] so old callers omitting it still work."""
        edit_model_start = SRC.find("class TeamsEditRequest")
        next_class = SRC.find("\nclass ", edit_model_start + 1)
        model_body = SRC[edit_model_start:next_class if next_class != -1 else edit_model_start + 500]
        assert "mentions" in model_body and "[]" in model_body, (
            "TeamsEditRequest.mentions must default to [] for backwards compatibility."
        )


class TestBuildSkypeMentionsHelper:

    def test_build_skype_mentions_helper_exists(self):
        """A shared _build_skype_mentions helper must exist in routes/teams.py."""
        assert "_build_skype_mentions" in SRC, (
            "_build_skype_mentions() helper must exist so both send and edit share "
            "the same mention serialization logic."
        )

    def test_build_skype_mentions_returns_mri_format(self):
        """Helper body must build '8:orgid:<aad_id>' MRI strings."""
        helper_start = SRC.find("def _build_skype_mentions(")
        assert helper_start != -1
        next_def = SRC.find("\ndef ", helper_start + 1)
        body = SRC[helper_start:next_def if next_def != -1 else helper_start + 800]
        assert '"8:orgid:"' in body or "f\"8:orgid:{" in body, (
            "_build_skype_mentions must produce '8:orgid:<aad_id>' MRI format."
        )

    def test_build_skype_mentions_uses_itemid_key(self):
        """Helper must use 'itemid' key (Skype format), not 'id' (Graph format)."""
        helper_start = SRC.find("def _build_skype_mentions(")
        next_def = SRC.find("\ndef ", helper_start + 1)
        body = SRC[helper_start:next_def if next_def != -1 else helper_start + 800]
        assert '"itemid"' in body, (
            "_build_skype_mentions must use 'itemid' key — "
            "Skype chatsvc rejects 'id' (that's the Graph format)."
        )

    def test_build_skype_mentions_skips_missing_aad_id(self):
        """Helper must skip entries where the AAD user id is empty."""
        helper_start = SRC.find("def _build_skype_mentions(")
        next_def = SRC.find("\ndef ", helper_start + 1)
        body = SRC[helper_start:next_def if next_def != -1 else helper_start + 800]
        assert "not aad_id" in body or "if aad_id" in body, (
            "_build_skype_mentions must skip mentions with no AAD id."
        )

    def test_build_skype_mentions_uses_displayname_key(self):
        """Helper must use 'displayName' key matching Skype's expected format."""
        helper_start = SRC.find("def _build_skype_mentions(")
        next_def = SRC.find("\ndef ", helper_start + 1)
        body = SRC[helper_start:next_def if next_def != -1 else helper_start + 800]
        assert '"displayName"' in body, (
            "_build_skype_mentions must include 'displayName' in the result dict."
        )


class TestEditEndpointSerializesMentions:

    def test_edit_endpoint_calls_build_skype_mentions(self):
        """The edit endpoint handler must call _build_skype_mentions (same as send)."""
        edit_fn_start = SRC.find("async def tp_teams_edit_message(")
        assert edit_fn_start != -1
        # Find the next function boundary
        next_fn = SRC.find("\n@router.", edit_fn_start + 1)
        edit_fn_body = SRC[edit_fn_start:next_fn if next_fn != -1 else edit_fn_start + 3000]
        assert "_build_skype_mentions" in edit_fn_body, (
            "tp_teams_edit_message must call _build_skype_mentions to serialize "
            "mention data into the Skype PUT payload — without this, editing a "
            "message drops all @mentions."
        )

    def test_send_endpoint_uses_shared_helper_not_inline(self):
        """Send endpoint must also use _build_skype_mentions (refactored from inline)."""
        send_fn_start = SRC.find("def tp_teams_send(")
        assert send_fn_start != -1
        next_fn = SRC.find("\n@router.", send_fn_start + 1)
        send_fn_body = SRC[send_fn_start:next_fn if next_fn != -1 else send_fn_start + 5000]
        assert "_build_skype_mentions" in send_fn_body, (
            "tp_teams_send must use _build_skype_mentions so send and edit share "
            "the same mention serialization logic."
        )
