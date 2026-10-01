"""tp_teams_send_message's handling of a stale/unusable cached chat_id.

Original issue: a recurring scheduled job's Teams draft carried a
"19:preview-..." chat_id (Microsoft's marker for a 1:1 conversation that's
never had a message sent — not a real, addressable resource yet) and
consistently got a real 404 from Microsoft's Skype chatsvc API on send,
which the draft-approval frontend then misread as "this draft expired"
(it reads any 404/410 that way).

INCIDENT (2026-09-30): an earlier version of this fix auto-resolved a
preview-id failure via the draft's `to` field, reasoning that a preview id
"can only exist because Teams generated it FOR a specific intended
contact." That reasoning turned out to be false in practice: a real draft
had chat_topic "ValliyappanRam,AI Agent" but `to` had independently been
resolved (by the model, following since-reverted SKILL.md guidance) to
Ram's *personal* email — a completely different mailbox. The auto-fallback
trusted `to` without any cross-check against chat_topic and delivered the
message to the wrong person.

Current, correct behavior: NO automatic resolution of any kind, for
preview ids or ordinary ids. `to`/`chat_id`/`chat_topic` are independently
model-supplied fields with no code-level guarantee they name the same
person — verified false in the incident above. Any chat_id failure —
preview or ordinary — fails loudly with the real reason (422, never the
misleading 404/410) and is NEVER silently rerouted to `to`/`recipients`.
The user/model must explicitly re-send (already proven to work — asking
Gator to compose fresh, resolving the recipient properly, sends fine).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


def _fake_skype_response(status_code: int, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = {"id": "msg123"} if status_code in (200, 201) else {}
    return resp


class _FakeSkypeModule:
    def get_auth(self):
        return ("fake-skype-token", "https://regional.example.com")

    def get_global_service(self):
        return "https://global.example.com"


@pytest.fixture
def teams_module():
    import routes.teams as teams

    return teams


class TestNoAutoResolutionEverForAnyChatId:
    """Safety-locking regression tests for the reverted incident: NEITHER a
    preview-id NOR an ordinary chat_id failure may ever be silently
    rerouted to `to`/`recipients` — regardless of whether a recipient is
    populated. Guards against reintroducing the auto-fallback this file's
    docstring explains caused a real misdelivery."""

    @pytest.mark.asyncio
    async def test_preview_id_never_falls_back_even_with_recipient_populated(self, teams_module):
        teams = teams_module
        stale_resp = _fake_skype_response(404, "Conversation not found")

        with patch.object(teams, "_get_skype_module", return_value=_FakeSkypeModule()), \
             patch("httpx.post", return_value=stale_resp), \
             patch.object(teams, "tp_teams_new_chat", new=AsyncMock()) as fake_new_chat:
            req = teams.TeamsSendMessageRequest(
                to="ram.personal@example.com",
                recipients=[{"email": "ram.personal@example.com", "name": "Ram"}],
                message="hello",
                chat_id="19:preview-abc123",
            )
            with pytest.raises(HTTPException) as exc_info:
                await teams.tp_teams_send_message(req)

        assert exc_info.value.status_code == 422
        fake_new_chat.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_preview_id_with_no_recipient_also_fails_honestly(self, teams_module):
        teams = teams_module
        stale_resp = _fake_skype_response(404, "Conversation not found")

        with patch.object(teams, "_get_skype_module", return_value=_FakeSkypeModule()), \
             patch("httpx.post", return_value=stale_resp):
            req = teams.TeamsSendMessageRequest(
                to="", message="hello", chat_id="19:preview-abc123",
            )
            with pytest.raises(HTTPException) as exc_info:
                await teams.tp_teams_send_message(req)

        assert exc_info.value.status_code == 422
        assert exc_info.value.status_code not in (404, 410)

    @pytest.mark.asyncio
    async def test_ordinary_chat_id_never_falls_back_even_with_recipient_populated(self, teams_module):
        teams = teams_module
        stale_resp = _fake_skype_response(404, "Conversation not found")

        with patch.object(teams, "_get_skype_module", return_value=_FakeSkypeModule()), \
             patch("httpx.post", return_value=stale_resp), \
             patch.object(teams, "tp_teams_new_chat", new=AsyncMock()) as fake_new_chat:
            req = teams.TeamsSendMessageRequest(
                to="someone-else@example.com",
                recipients=[{"email": "someone-else@example.com", "name": "Someone Else"}],
                message="hello",
                chat_id="19:an-ordinary-chat-id",
            )
            with pytest.raises(HTTPException) as exc_info:
                await teams.tp_teams_send_message(req)

        assert exc_info.value.status_code == 422
        fake_new_chat.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ordinary_chat_id_with_no_recipient_surfaces_real_reason(self, teams_module):
        """422, not the raw upstream 404 — so the draft-approval frontend
        (which reads 404/410 as "this draft expired") shows the real reason
        instead of a misleading expiry message."""
        teams = teams_module
        stale_resp = _fake_skype_response(404, "Conversation not found")

        with patch.object(teams, "_get_skype_module", return_value=_FakeSkypeModule()), \
             patch("httpx.post", return_value=stale_resp):
            req = teams.TeamsSendMessageRequest(
                to="", message="hello", chat_id="19:an-ordinary-chat-id",
            )
            with pytest.raises(HTTPException) as exc_info:
                await teams.tp_teams_send_message(req)

        assert exc_info.value.status_code == 422
        assert exc_info.value.status_code not in (404, 410)


class TestSuccessPathUnaffected:
    @pytest.mark.asyncio
    async def test_successful_send_via_chat_id_unaffected(self, teams_module):
        teams = teams_module
        ok_resp = _fake_skype_response(201, '{"id": "msg123"}')

        with patch.object(teams, "_get_skype_module", return_value=_FakeSkypeModule()), \
             patch("httpx.post", return_value=ok_resp):
            req = teams.TeamsSendMessageRequest(
                to="", message="hello", chat_id="19:a-real-live-chat",
            )
            result = await teams.tp_teams_send_message(req)

        assert result["sent"] is True
        assert result["chat_id"] == "19:a-real-live-chat"
        assert result["message_id"] == "msg123"
