"""Settings → Storage: report sizes of Gator working dirs and clear the scratch
('work') dir, without touching deliverables ('outputs')."""
import asyncio
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest


@pytest.fixture
def patched_dirs(tmp_path, monkeypatch):
    work = tmp_path / "work"
    outputs = tmp_path / "outputs"
    work.mkdir()
    outputs.mkdir()
    import config as cfg
    monkeypatch.setattr(cfg, "WORK_DIR", work)
    monkeypatch.setattr(cfg, "OUTPUTS_DIR", outputs)
    return work, outputs


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_usage_reports_sizes_and_clearable(patched_dirs):
    work, outputs = patched_dirs
    (work / "node_modules").mkdir()
    (work / "node_modules" / "big.js").write_bytes(b"x" * 2048)
    (outputs / "deck.pptx").write_bytes(b"PK" * 10)

    from routes.utils import storage_usage
    res = _run(storage_usage())
    assert res["ok"]
    by_key = {i["key"]: i for i in res["items"]}
    assert by_key["work"]["size_bytes"] >= 2048
    assert by_key["work"]["clearable"] is True
    assert by_key["outputs"]["clearable"] is False


def test_clear_work_empties_scratch(patched_dirs):
    work, _ = patched_dirs
    (work / "sub").mkdir()
    (work / "sub" / "f.txt").write_text("data")
    (work / "top.txt").write_text("data")

    from routes.utils import storage_clear, ClearStorageRequest
    res = _run(storage_clear(ClearStorageRequest(key="work")))
    assert res["ok"] and res["size_bytes"] == 0
    assert work.is_dir()  # dir itself kept
    assert list(work.iterdir()) == []  # contents gone


def test_clear_outputs_is_blocked(patched_dirs):
    _, outputs = patched_dirs
    (outputs / "deck.pptx").write_bytes(b"PK")
    from routes.utils import storage_clear, ClearStorageRequest
    res = _run(storage_clear(ClearStorageRequest(key="outputs")))
    assert res["ok"] is False
    assert list(outputs.iterdir())  # deliverable untouched


def test_clear_unknown_key_rejected(patched_dirs):
    from routes.utils import storage_clear, ClearStorageRequest
    res = _run(storage_clear(ClearStorageRequest(key="nope")))
    assert res["ok"] is False
