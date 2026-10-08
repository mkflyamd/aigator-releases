"""_tool_schedule_task must reject scheduling a job whose prompt hardcodes
a Teams "19:preview-..." chat_id — a marker for a conversation that's
never had a message sent, not a stable, reusable resource.

Incident (2026-09-30): a recurring job's own prompt hardcoded exactly this
kind of chat_id for its Teams-send step. It consistently failed, and once
a recipient email was ALSO separately resolved for the same step (per
since-reverted guidance), the two didn't match — the chat_id was for a
bot/agent contact, but the resolved email was for that person's own
personal account — and the message was delivered to the wrong person.
Prompt-only guidance (the teams skill's own SKILL.md, and schedule_task's
own tool description) already says not to do this; this test locks in the
code-level backstop, since that guidance alone was demonstrably not
followed once already.
"""
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def fake_scheduler():
    with patch("scheduler.add_job", new=AsyncMock(
        return_value={"job_id": "job-1", "next_run_time": "2026-01-01T00:00:00"}
    )) as fake_add_job:
        yield fake_add_job


class TestRejectsHardcodedPreviewChatId:
    @pytest.mark.asyncio
    async def test_rejects_prompt_with_preview_chat_id(self, fake_scheduler):
        from skills._always_on.tools import _tool_schedule_task

        result = await _tool_schedule_task(
            name="Daily Update",
            prompt='Call teams_open_compose with chat_id "19:preview-ab0dc05a-05dd-4c99-a9af-c33a85ce1997" and send the update.',
            trigger_type="cron",
            cron_hour=9,
            cron_minute=0,
            skills=["teams"],
        )

        assert "error" in result
        assert "preview" in result["error"].lower()
        fake_scheduler.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ordinary_chat_id_is_not_rejected(self, fake_scheduler):
        """Only the specific "19:preview-" marker is rejected — an ordinary,
        already-established chat_id (e.g. a real group channel) is fine."""
        from skills._always_on.tools import _tool_schedule_task

        result = await _tool_schedule_task(
            name="Team Update",
            prompt='Call read_teams_chats with chat_id "19:d3ec4168c09f4cb78792ef9702f2a963@thread.v2".',
            trigger_type="cron",
            cron_hour=9,
            cron_minute=0,
            skills=["teams"],
        )

        assert result.get("ok") is True
        fake_scheduler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_prompt_without_any_chat_id_schedules_normally(self, fake_scheduler):
        from skills._always_on.tools import _tool_schedule_task

        result = await _tool_schedule_task(
            name="Daily Update",
            prompt="Resolve the recipient by email via search_people, then compose the update.",
            trigger_type="cron",
            cron_hour=9,
            cron_minute=0,
            skills=["teams"],
        )

        assert result.get("ok") is True
        assert result["job_id"] == "job-1"
        fake_scheduler.assert_awaited_once()
