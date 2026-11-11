import hashlib

import pytest

from skills._m365 import file_transfer as ft


class Err(Exception):
    def __init__(self, status_code, msg=""):
        super().__init__(f"Graph API {status_code}: {msg}")
        self.status_code = status_code


class Resp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class FakeGC:
    def __init__(self, reported_size=None, put_error=None):
        self.reported_size = reported_size
        self.put_error = put_error
        self.put_paths = []
        self.sessions = []
        self.chunks = []
        self.received = b""

    def put_binary(self, path, data, content_type="application/octet-stream"):
        if self.put_error:
            raise self.put_error
        self.put_paths.append(path)
        size = self.reported_size if self.reported_size is not None else len(data)
        return {"id": "N1", "name": "a.txt", "size": size, "webUrl": "https://od/a.txt"}

    def post(self, path, body):
        self.sessions.append((path, body))
        return {"uploadUrl": "https://upload.example/s1"}

    def _request(self, method, url, headers=None, content=None, label=""):
        assert url.startswith("https://upload.example/")
        assert "Authorization" not in (headers or {}), "uploadUrl is pre-authenticated"
        start, rest = headers["Content-Range"].split(" ")[1].split("-")
        end, total = rest.split("/")
        self.chunks.append((int(start), int(end), int(total)))
        self.received += content
        if int(end) + 1 == int(total):
            return Resp({"id": "N2", "name": "big.bin", "size": int(total), "webUrl": "https://od/big.bin"})
        return Resp({"nextExpectedRanges": [f"{int(end) + 1}-"]})


def test_small_file_put_into_folder_by_id_with_rename_conflict(tmp_path):
    f = tmp_path / "my file.txt"
    f.write_bytes(b"hello")
    gc = FakeGC()
    out = ft.store_in_folder(gc, ft.file_source(str(f)), "drive/1", "folder+2")
    assert out["status"] == "saved"
    assert out["id"] == "N1" and out["drive_id"] == "drive/1" and out["size"] == 5
    assert out["sha256"] == hashlib.sha256(b"hello").hexdigest()
    path = gc.put_paths[0]
    assert path.startswith("/drives/drive%2F1/items/folder%2B2:/my%20file.txt:/content")
    assert path.endswith("?@microsoft.graph.conflictBehavior=rename")


def test_large_file_uses_upload_session_in_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(ft, "SIMPLE_UPLOAD_MAX", 4)
    monkeypatch.setattr(ft, "CHUNK", 4)
    f = tmp_path / "big.bin"
    f.write_bytes(b"0123456789")
    gc = FakeGC()
    out = ft.store_in_folder(gc, ft.file_source(str(f)), "d2", "f2")
    assert out["status"] == "saved" and out["size"] == 10
    assert gc.chunks == [(0, 3, 10), (4, 7, 10), (8, 9, 10)]
    assert gc.received == b"0123456789"
    session_path, body = gc.sessions[0]
    assert session_path == "/drives/d2/items/f2:/big.bin:/createUploadSession"
    assert body["item"]["@microsoft.graph.conflictBehavior"] == "rename"


def test_size_mismatch_is_an_error(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")
    out = ft.store_in_folder(FakeGC(reported_size=3), ft.file_source(str(f)), "d", "f")
    assert out["status"] == "error" and out["error"] == "size_mismatch"


def test_graph_failure_is_reported_with_error_code(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")
    out = ft.store_in_folder(FakeGC(put_error=Err(403, "denied")), ft.file_source(str(f)), "d", "f")
    assert out["status"] == "error" and out["error"] == "transfer_failed"
    assert out["error_code"] == "forbidden"
    assert "403" in out["detail"]


def test_unsafe_characters_in_name_are_sanitised(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"x")
    gc = FakeGC()
    ft.store_in_folder(gc, ft.file_source(str(f), name='q3: "plan".txt'), "d", "f")
    assert "%22" not in gc.put_paths[0] and "%3A" not in gc.put_paths[0]
    assert "/q3_%20_plan_.txt:/content" in gc.put_paths[0]


class RealisticGC(FakeGC):
    """Mimics GraphClient._request: an empty headers dict is replaced by the bearer headers."""

    def __init__(self, fail_on_chunk=False):
        super().__init__()
        self.fail_on_chunk = fail_on_chunk
        self.sent = []

    def _request(self, method, url, headers=None, content=None, label=""):
        hdrs = headers or {"Authorization": "Bearer aigator-fake-api-key"}
        self.sent.append((method, url, hdrs))
        if method == "DELETE":
            return Resp({})
        if self.fail_on_chunk:
            raise Err(500, "boom")
        return Resp({"id": "N2", "name": "big.bin", "size": 1, "webUrl": "https://od/big.bin"})


def _delete_calls(gc):
    return [c for c in gc.sent if c[0] == "DELETE"]


def test_cancel_after_chunk_failure_sends_no_authorization(tmp_path, monkeypatch):
    monkeypatch.setattr(ft, "SIMPLE_UPLOAD_MAX", 4)
    monkeypatch.setattr(ft, "CHUNK", 4)
    f = tmp_path / "big.bin"
    f.write_bytes(b"0123456789")
    gc = RealisticGC(fail_on_chunk=True)
    out = ft.store_in_folder(gc, ft.file_source(str(f)), "d", "f")
    assert out["status"] == "error" and out["error"] == "transfer_failed"
    deletes = _delete_calls(gc)
    assert len(deletes) == 1
    assert deletes[0][1] == "https://upload.example/s1"
    assert "Authorization" not in deletes[0][2]


def test_cancel_after_source_size_mismatch_sends_no_authorization(tmp_path, monkeypatch):
    monkeypatch.setattr(ft, "SIMPLE_UPLOAD_MAX", 4)
    monkeypatch.setattr(ft, "CHUNK", 4)
    f = tmp_path / "big.bin"
    f.write_bytes(b"0123456789")
    source = ft.file_source(str(f))
    source.size = 12  # the file is shorter than declared, so the session is abandoned
    gc = RealisticGC()
    out = ft.store_in_folder(gc, source, "d", "f")
    assert out["status"] == "error" and out["error"] == "source_size_mismatch"
    deletes = _delete_calls(gc)
    assert len(deletes) == 1
    assert "Authorization" not in deletes[0][2]


@pytest.mark.parametrize("bad", ["replace", "rename&x=1", "fail\n", ""])
def test_unsupported_on_conflict_is_rejected_before_any_call(tmp_path, bad):
    f = tmp_path / "a.txt"
    f.write_bytes(b"x")
    gc = FakeGC()
    with pytest.raises(ValueError):
        ft.store_in_folder(gc, ft.file_source(str(f)), "d", "f", on_conflict=bad)
    assert gc.put_paths == [] and gc.sessions == []


def test_fail_conflict_is_accepted(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"x")
    gc = FakeGC()
    ft.store_in_folder(gc, ft.file_source(str(f)), "d", "f", on_conflict="fail")
    assert gc.put_paths[0].endswith("conflictBehavior=fail")
