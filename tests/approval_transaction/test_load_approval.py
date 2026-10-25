import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

import narration_approval as na

SCRIPT = (Path(__file__).resolve().parents[2] / "web" / "skills" / "gator-demo-recorder"
          / "scripts" / "load_approval.py")
spec = importlib.util.spec_from_file_location("load_approval_under_test", SCRIPT)
la = importlib.util.module_from_spec(spec)
spec.loader.exec_module(la)

SEGS = [{"text": "Open the app"}, {"text": "Naïve café — ünïcode 日本語"}]


def _approved(store, data=b"raw-one"):
    p = store.create_project()
    raw = Path(p["path"]) / "source" / "rec.mp4"
    raw.write_bytes(data)
    store.update_project(p["project_id"], raw=str(raw))
    out = na.approve(p["project_id"], SEGS, {"music": False})
    return Path(out["path"]), out["approval"], raw


def test_hash_parity_with_backend():
    for segs, flags in [(SEGS, {"music": True}), ([{"text": "a", "start": 1.5}], {})]:
        assert la.canonical_hash(segs, flags) == na.canonical_hash(segs, flags)


@pytest.mark.parametrize("size", [0, 10, 65536, 65537, 200_000])
def test_fingerprint_parity_with_backend(tmp_path, size):
    f = tmp_path / "m.bin"
    f.write_bytes(bytes(i % 251 for i in range(size)))
    assert la.media_fingerprint(f) == na.media_fingerprint(f)


def test_load_returns_verified_record(store):
    root, approval, _ = _approved(store)
    rec = la.load(root, approval["approval_id"])
    assert rec["segments"] == SEGS and rec["version"] == 1


def test_load_without_id_uses_current(store):
    root, approval, _ = _approved(store)
    assert la.load(root)["approval_id"] == approval["approval_id"]


def test_missing_when_no_approval(store):
    p = store.create_project()
    with pytest.raises(la.ApprovalError) as e:
        la.load(p["path"])
    assert e.value.code == "missing"


def test_superseded_when_id_is_old(store):
    root, approval, _ = _approved(store)
    na.approve(Path(root).name, [{"text": "New words"}], {})
    with pytest.raises(la.ApprovalError) as e:
        la.load(root, approval["approval_id"])
    assert e.value.code == "superseded"


def test_corrupt_when_record_tampered(store):
    root, approval, _ = _approved(store)
    rec_path = root / "work" / "approvals" / f"{approval['approval_id']}.json"
    rec = json.loads(rec_path.read_text("utf-8"))
    rec["segments"][0]["text"] = "tampered"
    rec_path.write_text(json.dumps(rec), encoding="utf-8")
    with pytest.raises(la.ApprovalError) as e:
        la.load(root)
    assert e.value.code == "corrupt"


def test_corrupt_when_record_file_missing(store):
    root, approval, _ = _approved(store)
    (root / "work" / "approvals" / f"{approval['approval_id']}.json").unlink()
    with pytest.raises(la.ApprovalError) as e:
        la.load(root)
    assert e.value.code == "corrupt"


def test_stale_media_when_raw_changes(store):
    root, _, raw = _approved(store)
    raw.write_bytes(b"a completely different recording")
    with pytest.raises(la.ApprovalError) as e:
        la.load(root)
    assert e.value.code == "stale_media"


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                          text=True, encoding="utf-8")


def test_cli_success_writes_segments(store, tmp_path):
    root, approval, _ = _approved(store)
    out = tmp_path / "segments.json"
    r = _run("--project-dir", str(root), "--approval-id", approval["approval_id"],
             "--segments-out", str(out))
    assert r.returncode == 0
    body = json.loads(r.stdout)
    assert body["ok"] is True and body["segment_count"] == 2
    assert json.loads(out.read_text("utf-8")) == SEGS


def test_cli_failure_exit_2_with_code(store):
    p = store.create_project()
    r = _run("--project-dir", p["path"])
    assert r.returncode == 2
    body = json.loads(r.stdout)
    assert body["ok"] is False and body["code"] == "missing" and body["error"]


def _set_current_edit(store, root, data):
    pid = Path(root).name
    edit = Path(root) / "work" / "edits" / "edit_001.mp4"
    edit.parent.mkdir(parents=True, exist_ok=True)
    edit.write_bytes(data)
    store.set_ext(pid, "media", {"current": "work/edits/edit_001.mp4", "current_base": "source/rec.mp4"})
    return edit


def test_stale_media_when_an_edit_becomes_current(store):
    root, _, _ = _approved(store)
    _set_current_edit(store, root, b"an edited recording")
    with pytest.raises(la.ApprovalError) as e:
        la.load(root)
    assert e.value.code == "stale_media"


def test_load_matches_backend_pin_when_an_edit_is_current(store):
    root, _, _ = _approved(store)
    _set_current_edit(store, root, b"an edited recording")
    na.approve(Path(root).name, SEGS, {"music": False})
    assert la.load(root)["version"] == 2
