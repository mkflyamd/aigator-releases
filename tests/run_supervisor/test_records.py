import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "web"))

import pytest

from runs.records import ACTIVE_STATES, STATES, RunRecord, RunStore, exit_info, tail_of


def test_states_are_the_contract_set():
    assert set(STATES) == {
        "awaiting_approval", "preparing", "running", "finished", "timed_out", "cancelled", "denied",
        "policy_blocked", "expired", "failed_to_start", "interrupted", "abandoned",
    }
    assert ACTIVE_STATES == {"awaiting_approval", "preparing", "running"}


@pytest.mark.parametrize("code, hex_code, crash", [
    (0, "0x00000000", False),
    (3, "0x00000003", False),
    (-1073740791, "0xC0000409", True),
    (0xC0000409, "0xC0000409", True),
    (0xBFFFFFFF, "0xBFFFFFFF", False),
])
def test_exit_info_reports_hex_and_crash_value_as_facts(code, hex_code, crash):
    assert exit_info(code) == {"code": code, "hex": hex_code, "is_crash_value": crash}


def test_exit_info_for_no_exit_is_none():
    assert exit_info(None) is None


def test_tail_is_capped_and_marked():
    text, truncated = tail_of("a" * 5000, 100)
    assert truncated is True
    assert len(text) <= 100 + 80
    assert text.endswith("a" * 100)
    assert tail_of("short", 100) == ("short", False)


def test_store_round_trips_a_record(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    rec = RunRecord(id="r1", context_id="tab-1", path="host", kind="command", scope="tab", state="running",
                    facts={"urls_seen": ["http://127.0.0.1:1/"]}, grant_ids=["g1"])
    store.upsert(rec.to_dict())
    got = store.get("r1")
    assert got["state"] == "running"
    assert got["facts"]["urls_seen"] == ["http://127.0.0.1:1/"]
    assert got["grant_ids"] == ["g1"]


def test_store_ignores_a_stale_write(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    newer = RunRecord(id="r1", context_id="tab-1", path="host", kind="command", scope="tab", state="finished", rev=5)
    older = RunRecord(id="r1", context_id="tab-1", path="host", kind="command", scope="tab", state="running", rev=3)
    store.upsert(newer.to_dict())
    store.upsert(older.to_dict())
    assert store.get("r1")["state"] == "finished"


def test_store_lists_one_tabs_records_newest_first(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    for i, tab in enumerate(["tab-1", "tab-2", "tab-1"]):
        store.upsert(RunRecord(id=f"r{i}", context_id=tab, path="host", kind="command", scope="tab",
                               state="finished", created_at=100.0 + i).to_dict())
    assert [r["id"] for r in store.list("tab-1")] == ["r2", "r0"]


def test_store_interrupts_active_records_only(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    for rid, state in [("a", "awaiting_approval"), ("b", "preparing"), ("c", "running"), ("d", "finished")]:
        store.upsert(RunRecord(id=rid, context_id="t", path="host", kind="command", scope="tab", state=state).to_dict())
    assert sorted(r["id"] for r in store.interrupt_active(now=50.0)) == ["a", "b", "c"]
    assert [store.get(x)["state"] for x in "abcd"] == ["interrupted"] * 3 + ["finished"]


def test_store_purges_old_terminal_records_only(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    store.upsert(RunRecord(id="old", context_id="t", path="host", kind="command", scope="tab", state="finished",
                           created_at=1.0, finished_at=1.0).to_dict())
    store.upsert(RunRecord(id="live", context_id="t", path="host", kind="command", scope="tab", state="running",
                           created_at=1.0).to_dict())
    store.purge(older_than=100.0)
    assert store.get("old") is None
    assert store.get("live") is not None


def test_persisted_output_tail_is_scrubbed_and_capped(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    secret_line = "Authorization: Bearer aigator-fake-api-key"  # pragma: allowlist secret
    rec = RunRecord(id="r1", context_id="t", path="host", kind="command", scope="tab", state="finished",
                    output_tail=secret_line + "\n" + "x" * 10_000)
    store.upsert(rec.to_dict())
    saved = store.get("r1")["output_tail"]
    assert "aigator-fake-api-key" not in saved
    assert len(saved) <= 2200


def test_a_store_that_cannot_open_never_raises(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    store = RunStore(blocker / "runs.db")
    store.upsert(RunRecord(id="r1", context_id="t", path="host", kind="command", scope="tab", state="running").to_dict())
    assert store.get("r1") is None
