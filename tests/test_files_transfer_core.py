import pytest

from skills._files import transfer as tr

SRC = {"drive_id": "d1", "item_id": "i1"}
DEST = {"drive_id": "d2", "folder_id": "f2"}
META = {"item_id": "i1", "drive_id": "d1", "name": "report.docx", "size": 10, "web_url": "u1"}
MOVED = {"item_id": "i1", "drive_id": "d2", "name": "report.docx", "web_url": "u2"}
LOCKED = {"error": "Move failed: 423", "error_code": "locked"}
DONE = {"status": "completed", "item_id": "n1", "dest_drive_id": "d2"}


class FakeProvider:
    def __init__(self, move=(), copy=None, foreign=False, stat=META, find=None, download=None, upload=None, stat_new=None):
        self.moves = list(move)
        self.copy_result = copy
        self.foreign = foreign
        self.stat_result = stat
        self.stat_new = stat_new or {"item_id": "n1", "drive_id": "d2", "name": "report.docx", "web_url": "u3", "size": 10}
        self.find = find
        self.download_result = download
        self.upload_result = upload
        self.calls = []

    def stat(self, ref):
        self.calls.append("stat")
        return self.stat_new if ref["item_id"] == "n1" else self.stat_result

    def is_foreign_owner(self, ref):
        self.calls.append("is_foreign_owner")
        return self.foreign

    def move(self, ref, dest, new_name):
        self.calls.append("move")
        return self.moves.pop(0)

    def copy(self, ref, dest, new_name):
        self.calls.append("copy")
        return self.copy_result

    def find_in_folder(self, dest, name, size):
        self.calls.append("find")
        return self.find

    def download(self, ref, local_path):
        self.calls.append(("download", local_path))
        return self.download_result

    def upload(self, local_path, dest, name):
        self.calls.append(("upload", local_path, name))
        return self.upload_result


def run(p, **kw):
    sleeps = []
    out = tr.transfer(p, SRC, DEST, sleep=sleeps.append, **kw)
    return out, sleeps


def test_move_success_is_native_move():
    p = FakeProvider(move=[MOVED])
    out, sleeps = run(p)
    assert out["status"] == "moved" and out["method"] == "native_move"
    assert out["original_remains"] is False and out["reason"] is None
    assert out["dest"] == {"drive_id": "d2", "item_id": "i1", "name": "report.docx", "web_url": "u2"}
    assert p.calls == ["stat", "is_foreign_owner", "move"] and sleeps == []


def test_locked_then_free_retries_with_backoff():
    p = FakeProvider(move=[LOCKED, LOCKED, MOVED])
    out, sleeps = run(p)
    assert out["status"] == "moved" and sleeps == [3, 6]
    assert p.calls.count("move") == 3


def test_still_locked_falls_back_to_server_copy():
    p = FakeProvider(move=[LOCKED, LOCKED, LOCKED], copy=DONE)
    out, sleeps = run(p)
    assert (out["status"], out["method"], out["reason"]) == ("copied", "server_copy", "locked")
    assert out["original_remains"] is True
    assert out["dest"]["item_id"] == "n1" and out["dest"]["web_url"] == "u3"
    assert sleeps == [3, 6]
    assert "original" in out["message"].lower()


def test_non_lock_move_error_fails_without_copy():
    p = FakeProvider(move=[{"error": "Move failed: 403", "error_code": "forbidden"}])
    out, _ = run(p)
    assert out["status"] == "failed" and out["error_code"] == "forbidden"
    assert "copy" not in p.calls and out["original_remains"] is True


def test_foreign_owner_copies_instead_of_moving():
    p = FakeProvider(foreign=True, copy=DONE)
    out, _ = run(p)
    assert (out["status"], out["method"], out["reason"]) == ("copied", "server_copy", "not_owner")
    assert out["original_remains"] is True and "move" not in p.calls


def test_copy_mode_skips_owner_check_and_move():
    p = FakeProvider(copy=DONE)
    out, _ = run(p, mode="copy")
    assert out["status"] == "copied" and out["reason"] is None and out["original_remains"] is True
    assert p.calls == ["stat", "copy", "stat"]


def test_pending_copy_resolved_by_finding_item_in_destination():
    found = {"item_id": "n9", "drive_id": "d2", "name": "report.docx", "web_url": "u9"}
    p = FakeProvider(copy={"status": "pending", "monitor_url": "m"}, find=found)
    out, _ = run(p, mode="copy")
    assert out["status"] == "copied" and out["dest"] == found


def test_pending_copy_not_found_stays_pending_and_does_not_fall_back():
    p = FakeProvider(copy={"status": "pending", "monitor_url": "m"}, find=None)
    out, _ = run(p, mode="copy")
    assert out["status"] == "pending" and out["original_remains"] is True
    assert not any(isinstance(c, tuple) for c in p.calls)


def test_copy_error_falls_back_to_download_and_upload(tmp_path):
    up = {"item_id": "n5", "drive_id": "d2", "name": "report.docx", "web_url": "u5"}
    p = FakeProvider(copy={"error": "boom", "error_code": "unknown"},
                     download={"saved_to": str(tmp_path / "report.docx")}, upload=up)
    out, _ = run(p, mode="copy", downloads_dir=tmp_path)
    assert (out["status"], out["method"]) == ("copied", "download_upload")
    assert out["local_copy"] == str(tmp_path / "report.docx") and out["dest"] == up
    assert ("download", str(tmp_path / "report.docx")) in p.calls
    assert ("upload", str(tmp_path / "report.docx"), "report.docx") in p.calls


def test_download_path_never_overwrites_existing_local_file(tmp_path):
    (tmp_path / "report.docx").write_bytes(b"mine")
    up = {"item_id": "n5", "drive_id": "d2", "name": "report (1).docx", "web_url": "u5"}
    p = FakeProvider(copy={"error": "boom", "error_code": "unknown"},
                     download={"saved_to": str(tmp_path / "report (1).docx")}, upload=up)
    run(p, mode="copy", downloads_dir=tmp_path)
    assert ("download", str(tmp_path / "report (1).docx")) in p.calls


@pytest.mark.parametrize("code", ["forbidden", "not_found"])
def test_copy_forbidden_or_missing_does_not_fall_back(code, tmp_path):
    p = FakeProvider(copy={"error": "x", "error_code": code})
    out, _ = run(p, mode="copy", downloads_dir=tmp_path)
    assert out["status"] == "failed" and out["error_code"] == code
    assert not any(isinstance(c, tuple) for c in p.calls)


def test_upload_failure_after_download_reports_local_copy(tmp_path):
    p = FakeProvider(copy={"error": "boom", "error_code": "unknown"},
                     download={"saved_to": str(tmp_path / "report.docx")},
                     upload={"error": "no space", "error_code": "unknown"})
    out, _ = run(p, mode="copy", downloads_dir=tmp_path)
    assert out["status"] == "failed" and out["local_copy"] == str(tmp_path / "report.docx")
    assert out["original_remains"] is True


def test_download_failure_fails_the_transfer(tmp_path):
    p = FakeProvider(copy={"error": "boom", "error_code": "unknown"},
                     download={"error": "dl failed", "error_code": "unknown"})
    out, _ = run(p, mode="copy", downloads_dir=tmp_path)
    assert out["status"] == "failed" and out["local_copy"] is None


def test_bad_mode_fails_before_any_call():
    p = FakeProvider()
    out, _ = run(p, mode="delete")
    assert out["status"] == "failed" and p.calls == []


def test_stat_error_fails():
    p = FakeProvider(stat={"error": "gone", "error_code": "not_found"})
    out, _ = run(p)
    assert out["status"] == "failed" and out["error_code"] == "not_found"
    assert p.calls == ["stat"]


def test_new_name_is_used_for_lookup_and_upload(tmp_path):
    up = {"item_id": "n5", "drive_id": "d2", "name": "renamed.docx", "web_url": "u5"}
    p = FakeProvider(copy={"error": "boom", "error_code": "unknown"},
                     download={"saved_to": str(tmp_path / "report.docx")}, upload=up)
    run(p, mode="copy", new_name="renamed.docx", downloads_dir=tmp_path)
    assert ("upload", str(tmp_path / "report.docx"), "renamed.docx") in p.calls
