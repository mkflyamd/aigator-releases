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
        if isinstance(self.find, list):  # scripted: one result per call, the last one repeats
            return self.find.pop(0) if len(self.find) > 1 else self.find[0]
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
    assert p.calls == ["stat", "find", "copy", "stat"]


def test_pending_copy_resolved_by_finding_item_in_destination():
    found = {"item_id": "n9", "drive_id": "d2", "name": "report.docx", "web_url": "u9"}
    p = FakeProvider(copy={"status": "pending", "monitor_url": "m"}, find=[None, found])
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


STOP_DL = {"error": "stop", "error_code": "unknown"}


@pytest.mark.parametrize("new_name,local_name", [
    ("../x.bat", "x.bat"),
    ("..\\x.bat", "x.bat"),
    ("C:/Windows/Temp/a.bat", "a.bat"),
    ("a:b.txt", "ab.txt"),
    ("..", "file"),
])
def test_local_download_path_stays_inside_downloads_dir(new_name, local_name, tmp_path):
    p = FakeProvider(copy={"error": "boom", "error_code": "unknown"}, download=STOP_DL)
    run(p, mode="copy", new_name=new_name, downloads_dir=tmp_path)
    downloads = [c for c in p.calls if isinstance(c, tuple) and c[0] == "download"]
    assert downloads == [("download", str(tmp_path / local_name))]


def test_remote_new_name_is_passed_to_upload_unchanged(tmp_path):
    up = {"item_id": "n5", "drive_id": "d2", "name": "a:b.txt", "web_url": "u5"}
    p = FakeProvider(copy={"error": "boom", "error_code": "unknown"},
                     download={"saved_to": str(tmp_path / "ab.txt")}, upload=up)
    run(p, mode="copy", new_name="a:b.txt", downloads_dir=tmp_path)
    assert ("upload", str(tmp_path / "ab.txt"), "a:b.txt") in p.calls


@pytest.mark.parametrize("code", ["conflict", "throttled"])
def test_copy_conflict_or_throttled_does_not_fall_back(code, tmp_path):
    p = FakeProvider(copy={"error": "x", "error_code": code})
    out, _ = run(p, mode="copy", downloads_dir=tmp_path)
    assert out["status"] == "failed" and out["error_code"] == code
    assert out["original_remains"] is True
    assert not any(isinstance(c, tuple) for c in p.calls)


def _upload_to_n1(tmp_path, stat_new):
    up = {"item_id": "n1", "drive_id": "d2", "name": "report.docx", "web_url": "u5"}
    return FakeProvider(copy={"error": "boom", "error_code": "unknown"},
                        download={"saved_to": str(tmp_path / "report.docx")}, upload=up,
                        stat_new=stat_new)


def test_upload_size_mismatch_fails_verification(tmp_path):
    p = _upload_to_n1(tmp_path, {"item_id": "n1", "drive_id": "d2", "name": "report.docx", "web_url": "u5", "size": 3})
    out, _ = run(p, mode="copy", downloads_dir=tmp_path)
    assert out["status"] == "failed" and out["error_code"] == "verify_failed"
    assert out["local_copy"] == str(tmp_path / "report.docx") and out["original_remains"] is True


def test_upload_stat_failure_fails_verification(tmp_path):
    p = _upload_to_n1(tmp_path, {"error": "gone", "error_code": "not_found"})
    out, _ = run(p, mode="copy", downloads_dir=tmp_path)
    assert out["status"] == "failed" and out["error_code"] == "verify_failed"
    assert out["local_copy"] == str(tmp_path / "report.docx") and out["original_remains"] is True


def test_upload_verified_by_stat_after_upload(tmp_path):
    p = _upload_to_n1(tmp_path, None)
    out, _ = run(p, mode="copy", downloads_dir=tmp_path)
    assert out["status"] == "copied" and out["method"] == "download_upload"
    assert p.calls[-1] == "stat"


@pytest.mark.parametrize("copy", [{"status": "pending", "monitor_url": "m"}, {"status": "completed"}])
def test_find_in_folder_error_dict_is_not_a_found_item(copy):
    p = FakeProvider(copy=copy, find={"error": "list failed", "error_code": "unknown"})
    out, _ = run(p, mode="copy")
    assert out["status"] == "pending" and out["dest"] is None


LANDED = {"item_id": "n7", "drive_id": "d2", "name": "report.docx", "web_url": "u7"}
AMBIGUOUS = {"error": "Copy request failed: timed out", "error_code": "unknown", "ambiguous": True}
LOOKUP_FAILED = {"error": "lookup failed", "error_code": "unknown"}


def _uploads(p):
    return [c for c in p.calls if isinstance(c, tuple) and c[0] == "upload"]


def test_ambiguous_copy_error_is_pending_without_upload(tmp_path):
    p = FakeProvider(move=[LOCKED, LOCKED, LOCKED], copy=AMBIGUOUS, find=[None, LANDED],
                     download={"saved_to": str(tmp_path / "report.docx")}, upload=MOVED)
    out, _ = run(p, downloads_dir=tmp_path)
    assert (out["status"], out["method"], out["reason"]) == ("pending", "server_copy", "locked")
    assert out["original_remains"] is True and out["dest"] is None
    assert "destination" in out["message"] and "not retry" in out["message"].lower()
    assert _uploads(p) == [] and not any(isinstance(c, tuple) for c in p.calls)


@pytest.mark.parametrize("copy", [
    {"error": "Copy request returned HTTP 500: oops", "error_code": "unknown"},
    {"error": "Copy request returned HTTP 423: locked", "error_code": "locked"},
])
def test_definite_copy_refusal_falls_back_to_download_and_upload(copy, tmp_path):
    up = {"item_id": "n5", "drive_id": "d2", "name": "report.docx", "web_url": "u5"}
    p = FakeProvider(copy=copy, find=[None, LANDED],
                     download={"saved_to": str(tmp_path / "report.docx")}, upload=up)
    out, _ = run(p, mode="copy", downloads_dir=tmp_path)
    assert (out["status"], out["method"]) == ("copied", "download_upload")
    assert out["dest"] == up and len(_uploads(p)) == 1


def test_failed_snapshot_never_reports_a_later_match_as_the_copy():
    p = FakeProvider(copy={"status": "pending", "monitor_url": "m"}, find=[LOOKUP_FAILED, LANDED])
    out, _ = run(p, mode="copy")
    assert out["status"] == "pending" and out["dest"] is None
    assert out["original_remains"] is True


def test_pending_copy_with_pre_existing_match_stays_pending():
    old = {"item_id": "old1", "drive_id": "d2", "name": "report.docx", "web_url": "u0"}
    p = FakeProvider(copy={"status": "pending", "monitor_url": "m"}, find=[old, old])
    out, _ = run(p, mode="copy")
    assert out["status"] == "pending" and out["dest"] is None
    assert not any(isinstance(c, tuple) for c in p.calls)
