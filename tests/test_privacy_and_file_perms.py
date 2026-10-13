import asyncio
import json
import os
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import aiosqlite

import file_perms
import turn_telemetry


def test_restrict_to_owner_limits_a_file_to_the_current_user(tmp_path):
    target = tmp_path / "private.db"
    target.write_text("x")
    file_perms.forget(target)
    file_perms.restrict_to_owner(target)
    if os.name == "posix":
        assert (target.stat().st_mode & 0o777) == 0o600
    else:
        acl = subprocess.run(["icacls", str(target)], capture_output=True, text=True).stdout
        assert "Everyone" not in acl and "BUILTIN\\Users" not in acl and "Authenticated Users" not in acl


def test_restrict_database_reports_failure(tmp_path, monkeypatch):
    target = tmp_path / "x.db"
    target.write_text("x")
    file_perms.forget(target)

    def boom(*args, **kwargs):
        raise OSError("no")

    monkeypatch.setattr(file_perms, "restrict_to_owner", boom)
    assert file_perms.restrict_database(target) is False


def test_privacy_mode_telemetry_keeps_outcomes_and_drops_names_paths_and_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("AIGATOR_PRIVACY_MODE", "1")
    monkeypatch.setattr(turn_telemetry, "DB_PATH", tmp_path / "tasks.db")
    monkeypatch.setattr(turn_telemetry, "_initialized", False)

    async def run():
        await turn_telemetry.init_table()
        await turn_telemetry.log_tool_call("mcp-crm-lookup", "error", 12, error_code="timeout")
        await turn_telemetry.log_turn_end(
            turn_id="t1", context_id="c1", task_id="k1", turn_index=0, agent="a", model="m", provider="p",
            outcome="error", stop_reason=None,
            tool_calls=[{"name": "mcp-crm-lookup", "success": False, "error": r"C:\Projects\Apollo\x.txt failed"}],
            tool_error=r"C:\Projects\Apollo\x.txt failed", llm_error=None, input_tokens=5, output_tokens=7,
            overflow_prunes=0, retry_count=0, failover_used=False, bad_tool_streak=0, duration_ms=9,
            active_skills=["jira", "confluence"],
        )
        async with aiosqlite.connect(turn_telemetry.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            tool = await (await db.execute("SELECT * FROM tool_call_log")).fetchone()
            turn = await (await db.execute("SELECT * FROM turn_log")).fetchone()
        return dict(tool), dict(turn)

    tool, turn = asyncio.run(run())
    dump = json.dumps([tool, turn])
    for secret in ("crm", "Apollo", "Projects", "jira", "confluence"):
        assert secret not in dump
    assert tool["outcome"] == "error" and tool["duration_ms"] == 12
    assert turn["outcome"] == "error" and turn["input_tokens"] == 5 and turn["output_tokens"] == 7
    assert len(json.loads(turn["tool_calls"])) == 1 and len(json.loads(turn["active_skills"])) == 2
