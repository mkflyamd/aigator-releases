"""Tests for turn_telemetry — structured turn-event logging for triage.

Verifies that turn start/end events are persisted to SQLite, that consecutive
turns in the same context are linked (next_turn_id / next_turn_delay_s), and
that the triage queries (timeline, by-outcome, stuck) return the right rows.
"""
import asyncio
import os
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest

# Override the DB path to a temp file BEFORE importing turn_telemetry
_DB_PATH = os.path.join(os.path.dirname(__file__), "_test_turn_telemetry.db")
os.environ["TURN_TELEMETRY_TEST_DB"] = _DB_PATH

import config
config.TASKS_DB = pathlib.Path(_DB_PATH)

import turn_telemetry
# Full-suite import order can load turn_telemetry through app.py before this
# module runs. Pin the module's captured path explicitly so this test file
# never touches user state.
turn_telemetry.DB_PATH = pathlib.Path(_DB_PATH)


async def _setup():
    await turn_telemetry.init_table()
    # Clear any rows from a prior test so counts are deterministic.
    # Use turn_telemetry's own DB_PATH (captured at import time) — not
    # config.TASKS_DB — so we clean the same DB the module writes to.
    import aiosqlite
    async with aiosqlite.connect(turn_telemetry.DB_PATH) as db:
        await db.execute("DELETE FROM turn_log")
        await db.execute("DELETE FROM tool_call_log")
        await db.commit()


async def _cleanup():
    db_path = turn_telemetry.DB_PATH
    for path in (db_path, db_path.with_name(db_path.name + "-wal"), db_path.with_name(db_path.name + "-shm")):
        if path.exists():
            path.unlink()


def test_log_turn_end_persists_row():
    asyncio.run(_setup())
    try:
        turn_id = turn_telemetry.new_turn_id()

        async def _run():
            await turn_telemetry.log_turn_end(
                turn_id=turn_id, context_id="ctx-test", task_id="task-1",
                turn_index=0, agent="single", model="claude-3.5", provider="AnthropicProvider",
                outcome="end_turn", stop_reason="end_turn",
                tool_calls=[{"name": "read_email", "success": True}],
                tool_error=None, llm_error=None,
                input_tokens=1200, output_tokens=450,
                overflow_prunes=0, retry_count=0, failover_used=False,
                bad_tool_streak=0, duration_ms=3200,
                history_turns=4, active_skills=["email"],
            )
        asyncio.run(_run())

        timeline = asyncio.run(turn_telemetry.get_conversation_timeline("ctx-test"))
        assert len(timeline) == 1
        row = timeline[0]
        assert row["turn_id"] == turn_id
        assert row["context_id"] == "ctx-test"
        assert row["task_id"] == "task-1"
        assert row["outcome"] == "end_turn"
        assert row["stop_reason"] == "end_turn"
        assert row["input_tokens"] == 1200
        assert row["output_tokens"] == 450
        assert row["duration_ms"] == 3200
        assert row["tool_calls"] == [{"name": "read_email", "success": True}]
        assert row["active_skills"] == ["email"]
        assert row["history_turns"] == 4
    finally:
        asyncio.run(_cleanup())


def test_consecutive_turns_are_linked():
    asyncio.run(_setup())
    try:
        async def _run():
            # Turn 1
            await turn_telemetry.log_turn_end(
                turn_id="turn-1", context_id="ctx-link", task_id="task-1",
                turn_index=0, agent="single", model="m", provider="p",
                outcome="stalled", stop_reason="end_turn",
                tool_calls=[{"name": "send_email", "success": False, "error": "Auth expired"}],
                tool_error="Auth expired", llm_error=None,
                input_tokens=100, output_tokens=50,
                overflow_prunes=0, retry_count=0, failover_used=False,
                bad_tool_streak=0, duration_ms=1000,
            )
            # Small delay so next_turn_delay_s > 0
            await asyncio.sleep(0.05)
            # Turn 2 (the follow-up)
            await turn_telemetry.log_turn_end(
                turn_id="turn-2", context_id="ctx-link", task_id="task-2",
                turn_index=0, agent="single", model="m", provider="p",
                outcome="end_turn", stop_reason="end_turn",
                tool_calls=[], tool_error=None, llm_error=None,
                input_tokens=200, output_tokens=80,
                overflow_prunes=0, retry_count=0, failover_used=False,
                bad_tool_streak=0, duration_ms=500,
            )
        asyncio.run(_run())

        timeline = asyncio.run(turn_telemetry.get_conversation_timeline("ctx-link"))
        assert len(timeline) == 2
        # Turn 1 must be linked to Turn 2
        assert timeline[0]["turn_id"] == "turn-1"
        assert timeline[0]["next_turn_id"] == "turn-2"
        assert timeline[0]["next_turn_delay_s"] is not None
        assert timeline[0]["next_turn_delay_s"] > 0
        # Turn 2 has no follow-up (yet)
        assert timeline[1]["turn_id"] == "turn-2"
        assert timeline[1]["next_turn_id"] is None
    finally:
        asyncio.run(_cleanup())


def test_get_turns_by_outcome():
    asyncio.run(_setup())
    turn_telemetry._last_turn_by_context.clear()
    try:
        async def _run():
            await turn_telemetry.log_turn_end(
                turn_id="t1", context_id="c1", task_id="tk1",
                turn_index=0, agent="single", model="m", provider="p",
                outcome="stalled", stop_reason="end_turn",
                tool_calls=[], tool_error="err", llm_error=None,
                input_tokens=0, output_tokens=0,
                overflow_prunes=0, retry_count=0, failover_used=False,
                bad_tool_streak=0, duration_ms=100,
            )
            await turn_telemetry.log_turn_end(
                turn_id="t2", context_id="c2", task_id="tk2",
                turn_index=0, agent="single", model="m", provider="p",
                outcome="end_turn", stop_reason="end_turn",
                tool_calls=[], tool_error=None, llm_error=None,
                input_tokens=0, output_tokens=0,
                overflow_prunes=0, retry_count=0, failover_used=False,
                bad_tool_streak=0, duration_ms=100,
            )
            await turn_telemetry.log_turn_end(
                turn_id="t3", context_id="c3", task_id="tk3",
                turn_index=0, agent="single", model="m", provider="p",
                outcome="stalled", stop_reason="end_turn",
                tool_calls=[], tool_error="err2", llm_error=None,
                input_tokens=0, output_tokens=0,
                overflow_prunes=0, retry_count=0, failover_used=False,
                bad_tool_streak=0, duration_ms=100,
            )
        asyncio.run(_run())

        stalled = asyncio.run(turn_telemetry.get_turns_by_outcome("stalled"))
        assert len(stalled) == 2
        end_turns = asyncio.run(turn_telemetry.get_turns_by_outcome("end_turn"))
        assert len(end_turns) == 1
    finally:
        asyncio.run(_cleanup())


def test_get_stuck_conversations():
    asyncio.run(_setup())
    turn_telemetry._last_turn_by_context.clear()
    try:
        async def _run():
            # Stuck: stalled with no follow-up
            await turn_telemetry.log_turn_end(
                turn_id="stuck-1", context_id="ctx-stuck", task_id="tk1",
                turn_index=0, agent="single", model="m", provider="p",
                outcome="stalled", stop_reason="end_turn",
                tool_calls=[], tool_error="err", llm_error=None,
                input_tokens=0, output_tokens=0,
                overflow_prunes=0, retry_count=0, failover_used=False,
                bad_tool_streak=0, duration_ms=100,
            )
            # Not stuck: stalled but has a follow-up
            await turn_telemetry.log_turn_end(
                turn_id="recovered-1", context_id="ctx-recovered", task_id="tk2",
                turn_index=0, agent="single", model="m", provider="p",
                outcome="stalled", stop_reason="end_turn",
                tool_calls=[], tool_error="err", llm_error=None,
                input_tokens=0, output_tokens=0,
                overflow_prunes=0, retry_count=0, failover_used=False,
                bad_tool_streak=0, duration_ms=100,
            )
            await asyncio.sleep(0.02)
            await turn_telemetry.log_turn_end(
                turn_id="recovered-2", context_id="ctx-recovered", task_id="tk3",
                turn_index=0, agent="single", model="m", provider="p",
                outcome="end_turn", stop_reason="end_turn",
                tool_calls=[], tool_error=None, llm_error=None,
                input_tokens=0, output_tokens=0,
                overflow_prunes=0, retry_count=0, failover_used=False,
                bad_tool_streak=0, duration_ms=100,
            )
        asyncio.run(_run())

        stuck = asyncio.run(turn_telemetry.get_stuck_conversations())
        stuck_ids = [s["turn_id"] for s in stuck]
        assert "stuck-1" in stuck_ids
        assert "recovered-1" not in stuck_ids  # has a follow-up
    finally:
        asyncio.run(_cleanup())


def test_error_messages_are_truncated():
    asyncio.run(_setup())
    try:
        long_error = "x" * 1000
        async def _run():
            await turn_telemetry.log_turn_end(
                turn_id="t-trunc", context_id="c", task_id="tk",
                turn_index=0, agent="single", model="m", provider="p",
                outcome="llm_error", stop_reason=None,
                tool_calls=[], tool_error=None, llm_error=long_error,
                input_tokens=0, output_tokens=0,
                overflow_prunes=0, retry_count=0, failover_used=False,
                bad_tool_streak=0, duration_ms=100,
            )
        asyncio.run(_run())

        timeline = asyncio.run(turn_telemetry.get_conversation_timeline("c"))
        assert len(timeline) == 1
        # 500 chars + the truncation marker
        assert len(timeline[0]["llm_error"]) <= 501
    finally:
        asyncio.run(_cleanup())


def test_log_turn_end_does_not_raise_on_db_failure():
    """Telemetry must never break a chat turn — if the DB write fails, the
    function must swallow the error, not raise."""
    asyncio.run(_setup())
    asyncio.run(_cleanup())
    # DB file is deleted — log_turn_end should swallow the error
    async def _run():
        await turn_telemetry.log_turn_end(
            turn_id="t-no-db", context_id="c", task_id="tk",
            turn_index=0, agent="single", model="m", provider="p",
            outcome="end_turn", stop_reason="end_turn",
            tool_calls=[], tool_error=None, llm_error=None,
            input_tokens=0, output_tokens=0,
            overflow_prunes=0, retry_count=0, failover_used=False,
            bad_tool_streak=0, duration_ms=100,
        )
    # Should not raise
    asyncio.run(_run())


def test_tool_call_log_records_metadata_and_mcp_flag():
    asyncio.run(_setup())
    try:
        async def _run():
            await turn_telemetry.log_tool_call(
                "mcp-jira__search_issues", "error", 42,
                context_id="ctx-tool", task_id="task-tool",
                error_code="mcp_error",
            )
            import aiosqlite
            async with aiosqlite.connect(turn_telemetry.DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM tool_call_log") as cur:
                    return await cur.fetchone()

        row = asyncio.run(_run())
        assert row["tool_name"] == "mcp-jira__search_issues"
        assert row["is_mcp"] == 1
        assert row["outcome"] == "error"
        assert row["duration_ms"] == 42
        assert row["error_code"] == "mcp_error"
    finally:
        asyncio.run(_cleanup())


def test_cleanup_old_records_removes_expired_rows():
    asyncio.run(_setup())
    try:
        async def _run():
            import aiosqlite
            from datetime import datetime, timedelta, timezone

            old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
            recent = datetime.now(timezone.utc).isoformat()
            async with aiosqlite.connect(turn_telemetry.DB_PATH) as db:
                await db.execute("""INSERT INTO turn_log (
                    turn_id, context_id, task_id, turn_index, agent, model, provider,
                    outcome, tool_calls, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    ("old-turn", "ctx", "task", 0, "single", "m", "p", "end_turn", "[]", old),
                )
                await db.execute("""INSERT INTO tool_call_log (
                    created_at, tool_name, is_mcp, outcome, duration_ms
                ) VALUES (?, ?, ?, ?, ?)""", (old, "old_tool", 0, "success", 1))
                await db.execute("""INSERT INTO tool_call_log (
                    created_at, tool_name, is_mcp, outcome, duration_ms
                ) VALUES (?, ?, ?, ?, ?)""", (recent, "recent_tool", 0, "success", 1))
                await db.commit()
            return await turn_telemetry.cleanup_old_records()

        deleted = asyncio.run(_run())
        assert deleted == {"turn_log": 1, "tool_call_log": 1}
    finally:
        asyncio.run(_cleanup())


def test_legacy_error_detail_is_scrubbed_during_schema_upgrade():
    asyncio.run(_cleanup())
    try:
        async def _run():
            import aiosqlite
            async with aiosqlite.connect(turn_telemetry.DB_PATH) as db:
                await db.execute("""CREATE TABLE tool_call_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    is_mcp INTEGER NOT NULL DEFAULT 0,
                    outcome TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    error_detail TEXT
                )""")
                await db.execute("""INSERT INTO tool_call_log (
                    created_at, tool_name, outcome, error_detail
                ) VALUES (?, ?, ?, ?)""", (
                    "2026-09-25T00:00:00+00:00", "legacy_tool", "error", "external response text",
                ))
                await db.commit()
            await turn_telemetry.init_table()
            async with aiosqlite.connect(turn_telemetry.DB_PATH) as db:
                async with db.execute("SELECT error_detail, error_code FROM tool_call_log") as cur:
                    return await cur.fetchone()

        row = asyncio.run(_run())
        assert row == (None, None)
    finally:
        asyncio.run(_cleanup())


def test_pending_tool_telemetry_drains_with_bounded_shutdown():
    async def _run():
        task = asyncio.create_task(asyncio.sleep(0.01))
        turn_telemetry._tool_telemetry_tasks.add(task)
        task.add_done_callback(turn_telemetry._tool_telemetry_tasks.discard)
        await turn_telemetry.drain_tool_call_tasks(timeout_s=0.5)
        assert task.done()

    asyncio.run(_run())
