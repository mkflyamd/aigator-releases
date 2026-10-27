"""Core file-transfer module: store a Source into OneDrive without overwriting."""

import hashlib
import json

import pytest

from skills._m365 import file_transfer as ft


class Err(Exception):
    def __init__(self, status_code, msg=""):
        super().__init__(f"Graph API {status_code}: {msg}")
        self.status_code = status_code


class Resp:
    def __init__(self, data=None, status=200):
        self._data = data or {}
        self.status_code = status
        self.content = b"x" if data is not None else b""

    def json(self):
        return self._data


class FakeGC:
    def __init__(self, existing=None, fail_upload_at=None, reported_size=None):
        self.folders = set(existing or [])
        self.files = {}
        self.calls = []
        self.sessions = []
        self.chunks = []
        self.fail_upload_at = fail_upload_at
        self.reported_size = reported_size
        self._buf = b""

    def _headers(self):
        return {"Authorization": "Bearer t", "Content-Type": "application/json"}

    def get(self, path, params=None, **kw):
        self.calls.append(("GET", path))
        key = path.split("/root:/", 1)[1] if "/root:/" in path else ""
        if key in self.folders:
            return {"id": f"folder:{key}", "folder": {}}
        if key in self.files:
            f = self.files[key]
            return {"id": f"file:{key}", "name": key.rsplit("/", 1)[-1],
                    "size": len(f), "webUrl": f"https://od/{key}"}
        raise Err(404)

    def post(self, path, body):
        self.calls.append(("POST", path, body))
        if path.endswith("/createUploadLink") or "createUploadSession" in path:
            self.sessions.append((path, body))
            return {"uploadUrl": "https://upload.example/session1"}
        parent = path.split("/root:/", 1)[1].rsplit(":/children", 1)[0] if "/root:/" in path else ""
        key = f"{parent}/{body['name']}" if parent else body["name"]
        self.folders.add(key)
        return {"id": f"folder:{key}", "name": body["name"]}

    def put_binary(self, path, data, content_type="application/octet-stream"):
        self.calls.append(("PUT_BINARY", path))
        key = path.split("/root:/", 1)[1].split(":/content", 1)[0]
        if "conflictBehavior=fail" in path and key in self.files:
            raise Err(409, "nameAlreadyExists")
        self.files[key] = data
        size = self.reported_size if self.reported_size is not None else len(data)
        return {"id": f"file:{key}", "name": key.rsplit("/", 1)[-1], "size": size,
                "webUrl": f"https://od/{key}"}

    def _request(self, method, url, headers=None, content=None, label=""):
        assert url.startswith("https://upload.example/"), url
        assert "Authorization" not in (headers or {}), "uploadUrl is pre-authenticated"
        rng = headers["Content-Range"]
        start, rest = rng.split(" ")[1].split("-")
        end, total = rest.split("/")
        self.chunks.append((int(start), int(end), int(total), len(content)))
        self._buf += content
        if self.fail_upload_at is not None and int(start) == self.fail_upload_at:
            raise Err(500, "boom")
        if int(end) + 1 == int(total):
            size = self.reported_size if self.reported_size is not None else len(self._buf)
            return Resp({"id": "file:big", "name": "big.bin", "size": size,
                         "webUrl": "https://od/big"}, 201)
        return Resp({"nextExpectedRanges": [f"{int(end) + 1}-"]}, 202)


def test_safe_filename_replaces_forbidden_characters():
    assert ft.safe_filename('a/b\\c:d*e?f"g<h>i|j#k%l') == "a_b_c_d_e_f_g_h_i_j_k_l"
    assert ft.safe_filename("  name.vtt. ") == "name.vtt"
    assert ft.safe_filename("") == "file"


def test_ensure_folder_creates_each_missing_segment_once():
    gc = FakeGC(existing=["Documents"])
    ft.ensure_folder(gc, "", "Documents/Gator/2026-W43")
    posts = [c for c in gc.calls if c[0] == "POST"]
    assert [p[2]["name"] for p in posts] == ["Gator", "2026-W43"]
    assert all(p[2]["@microsoft.graph.conflictBehavior"] == "fail" for p in posts)
    before = len(posts)
    ft.ensure_folder(gc, "", "Documents/Gator/2026-W43")
    assert len([c for c in gc.calls if c[0] == "POST"]) == before


def test_ensure_folder_returns_each_folder_link():
    gc = FakeGC(existing=["Documents"])
    chain = ft.ensure_folder(gc, "", "Documents/Gator")
    assert [c["path"] for c in chain] == ["Documents", "Documents/Gator"]


def test_store_reports_folder_links():
    gc = FakeGC(existing=["Documents"])
    out = ft.store(gc, ft.bytes_source("m.vtt", b"abc"), "Documents")
    assert [f["path"] for f in out["folders"]] == ["Documents"]
    assert "folder_web_url" in out


def test_ensure_folder_uses_drive_id_when_given():
    gc = FakeGC()
    ft.ensure_folder(gc, "b!abc", "X")
    assert any(c[0] == "POST" and c[1].startswith("/drives/b!abc/root") for c in gc.calls)


def test_store_small_file_simple_upload_with_sha256():
    gc = FakeGC(existing=["Documents"])
    data = b"WEBVTT\n\n00:00.000 --> 00:01.000\nhello\n"
    out = ft.store(gc, ft.bytes_source("m.vtt", data), "Documents")
    assert out["status"] == "saved"
    assert out["sha256"] == hashlib.sha256(data).hexdigest()
    assert out["size"] == len(data)
    assert out["web_url"] == "https://od/Documents/m.vtt"
    assert gc.files["Documents/m.vtt"] == data
    assert any("conflictBehavior=fail" in c[1] for c in gc.calls if c[0] == "PUT_BINARY")


def test_store_existing_file_is_never_overwritten():
    gc = FakeGC(existing=["Documents"])
    gc.files["Documents/m.vtt"] = b"old"
    out = ft.store(gc, ft.bytes_source("m.vtt", b"new"), "Documents")
    assert out["status"] == "exists"
    assert gc.files["Documents/m.vtt"] == b"old"
    assert not any(c[0] == "PUT_BINARY" for c in gc.calls)


def test_store_existing_file_of_a_different_size_is_not_reported_as_saved():
    gc = FakeGC(existing=["Documents"])
    gc.files["Documents/m.vtt"] = b"partial"
    out = ft.store(gc, ft.bytes_source("m.vtt", b"the whole file"), "Documents")
    assert out["status"] == "error"
    assert out["error"] == "existing_file_size_mismatch"
    assert out["expected_size"] == len(b"the whole file")
    assert out["reported_size"] == len(b"partial")
    assert gc.files["Documents/m.vtt"] == b"partial"
    assert not any(c[0] == "PUT_BINARY" for c in gc.calls)


def test_store_existing_file_on_conflict_fail_is_error():
    gc = FakeGC(existing=["Documents"])
    gc.files["Documents/m.vtt"] = b"original"
    out = ft.store(gc, ft.bytes_source("m.vtt", b"new"), "Documents", on_conflict="fail")
    assert out["status"] == "error"
    assert out["error"] == "already_exists"


def test_store_race_409_reports_exists_without_overwrite():
    gc = FakeGC(existing=["Documents"])
    orig_get = gc.get

    seen = []

    def racing_get(path, params=None, **kw):
        if path.endswith("/m.vtt") and not seen:
            seen.append(1)
            raise Err(404)
        return orig_get(path, params, **kw)

    gc.get = racing_get
    gc.files["Documents/m.vtt"] = b"old"
    out = ft.store(gc, ft.bytes_source("m.vtt", b"new"), "Documents")
    assert out["status"] == "exists"
    assert gc.files["Documents/m.vtt"] == b"old"


def test_store_size_mismatch_is_error():
    gc = FakeGC(existing=["Documents"], reported_size=3)
    out = ft.store(gc, ft.bytes_source("m.vtt", b"abcdef"), "Documents")
    assert out["status"] == "error"
    assert out["error"] == "size_mismatch"


def test_store_large_file_uses_upload_session_in_320kib_multiples():
    gc = FakeGC(existing=["Documents"])
    total = ft.SIMPLE_UPLOAD_MAX + 1_000_000
    data = bytes(range(256)) * (total // 256 + 1)
    data = data[:total]
    pieces = [data[i:i + 1_500_000] for i in range(0, total, 1_500_000)]
    src = ft.Source(name="rec.mp4", size=total, open=lambda: iter(pieces))
    out = ft.store(gc, src, "Documents")
    assert out["status"] == "saved"
    assert out["sha256"] == hashlib.sha256(data).hexdigest()
    assert len(gc.sessions) == 1
    body = gc.sessions[0][1]
    assert body["item"]["@microsoft.graph.conflictBehavior"] == "fail"
    assert gc._buf == data
    for start, end, tot, n in gc.chunks[:-1]:
        assert n % (320 * 1024) == 0
    assert gc.chunks[0][0] == 0
    assert gc.chunks[-1][1] + 1 == total
    for (s1, e1, _, _), (s2, _, _, _) in zip(gc.chunks, gc.chunks[1:]):
        assert s2 == e1 + 1


def test_store_large_file_failure_returns_error_not_saved():
    gc = FakeGC(existing=["Documents"], fail_upload_at=ft.CHUNK)
    total = ft.CHUNK * 2 + 10
    src = ft.Source(name="rec.mp4", size=total, open=lambda: iter([b"x" * total]))
    out = ft.store(gc, src, "Documents")
    assert out["status"] == "error"
    assert "boom" in out["detail"]


def test_store_large_file_source_shorter_than_declared_is_error():
    gc = FakeGC(existing=["Documents"])
    total = ft.SIMPLE_UPLOAD_MAX + 10
    src = ft.Source(name="rec.mp4", size=total, open=lambda: iter([b"x" * 100]))
    out = ft.store(gc, src, "Documents")
    assert out["status"] == "error"
    assert out["error"] == "source_size_mismatch"


def test_store_sanitizes_name():
    gc = FakeGC(existing=["Documents"])
    out = ft.store(gc, ft.bytes_source("a/b:c.vtt", b"x"), "Documents")
    assert out["name"] == "a_b_c.vtt"
    assert "Documents/a_b_c.vtt" in gc.files


def test_store_never_deletes():
    gc = FakeGC(existing=["Documents"])
    ft.store(gc, ft.bytes_source("m.vtt", b"x"), "Documents")
    assert not any(c[0] == "DELETE" for c in gc.calls)
    assert not hasattr(ft, "delete") and not hasattr(ft, "move")
