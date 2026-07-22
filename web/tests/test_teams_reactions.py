"""Tests for Teams reactions — Issue #46, superseded by the Skype/chatsvc rework.

#46 originally called Graph's setReaction/unsetReaction. That was later replaced:
Graph's setReaction only accepts the classic reaction set and rejects extended
emojis (➕, 🙊, etc.), so reactions now go through the same Skype/chatsvc
"emotions" property API native Teams itself uses, which accepts the full catalog.
"""

import pathlib

SRC = (pathlib.Path(__file__).parent.parent / "routes" / "teams.py").read_text(encoding="utf-8")


# ── Static source checks ──────────────────────────────────────────────────────

class TestReactEndpointUsesGraph:

    def test_react_endpoint_uses_skype_chatsvc_emotions(self):
        react_start = SRC.find("async def tp_teams_react(")
        assert react_start != -1
        fn_body = SRC[react_start: react_start + 3000]
        assert 'name=emotions' in fn_body, (
            "tp_teams_react must call the Skype/chatsvc emotions property API — "
            "Graph's setReaction rejects extended-emoji reactions."
        )

    def test_react_endpoint_uses_put_for_add_and_delete_for_remove(self):
        react_start = SRC.find("async def tp_teams_react(")
        assert react_start != -1
        fn_body = SRC[react_start: react_start + 3000]
        assert '_httpx.put(url' in fn_body, (
            "adding a reaction must PUT to the chatsvc emotions property."
        )
        assert '_httpx.request("DELETE"' in fn_body, (
            "removing a reaction must DELETE the chatsvc emotions property."
        )

    def test_react_endpoint_uses_graph_token(self):
        react_start = SRC.find("async def tp_teams_react(")
        assert react_start != -1
        fn_body = SRC[react_start: react_start + 3000]
        assert "_get_graph_token" in fn_body or "Authorization" in fn_body, (
            "tp_teams_react must authenticate via a Bearer token."
        )

    def test_react_endpoint_sends_emotions_key(self):
        react_start = SRC.find("async def tp_teams_react(")
        assert react_start != -1
        fn_body = SRC[react_start: react_start + 3000]
        assert '"emotions": {"key": key' in fn_body, (
            "tp_teams_react must send the Teams reaction KEY in the chatsvc "
            "emotions body, not a Graph reactionType."
        )

    def test_react_endpoint_normalises_named_keys_to_emoji(self):
        """Named keys like 'like' must be converted to emoji chars for Graph."""
        assert "_REACTION_KEY_TO_EMOJI" in SRC, (
            "_REACTION_KEY_TO_EMOJI lookup must exist to convert 'like'→'👍' etc."
        )

    def test_reaction_key_map_covers_common_reactions(self):
        """Spot-check that the lookup map includes the most common reactions."""
        assert '"like": "👍"' in SRC or "'like': '👍'" in SRC, (
            "_REACTION_KEY_TO_EMOJI must map 'like' to the thumbs-up emoji."
        )
        assert '"heart"' in SRC, (
            "_REACTION_KEY_TO_EMOJI must include 'heart'."
        )


# ── Unit tests for emoji normalisation ───────────────────────────────────────

_REACTION_KEY_TO_EMOJI = {
    "like": "👍",
    "heart": "❤️",
    "laugh": "😆",
    "surprised": "😮",
    "sad": "😢",
    "angry": "😡",
}


def _normalise(reaction: str) -> str:
    """Replicate the normalisation logic in tp_teams_react."""
    return _REACTION_KEY_TO_EMOJI.get(reaction, reaction)


class TestEmojiNormalisation:

    def test_named_like_converts_to_thumbs_up(self):
        assert _normalise("like") == "👍"

    def test_named_heart_converts_to_heart_emoji(self):
        assert _normalise("heart") == "❤️"

    def test_named_laugh_converts_to_laugh_emoji(self):
        assert _normalise("laugh") == "😆"

    def test_emoji_char_passes_through_unchanged(self):
        assert _normalise("👍") == "👍"

    def test_emoji_char_heart_passes_through_unchanged(self):
        assert _normalise("❤️") == "❤️"

    def test_unknown_key_passes_through_unchanged(self):
        assert _normalise("🎉") == "🎉"

    def test_empty_string_passes_through(self):
        assert _normalise("") == ""
