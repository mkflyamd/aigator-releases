from pathlib import Path
from unittest.mock import MagicMock

from skills._m365 import file_transfer as ft
from skills._m365.onedrive_provider import OneDriveProvider


class Err(Exception):
    def __init__(self, status_code):
        super().__init__(f"Graph API {status_code}")
        self.status_code = status_code


def provider(gc=None, **ops):
    gc = gc or MagicMock()
    base = dict(get_item=MagicMock(), download=MagicMock(), copy=MagicMock(), move=MagicMock(), client=lambda: gc)
    base.update(ops)
    return OneDriveProvider(**base), gc


def _drives(gc, drive_type, drive_id="d1", mine="mine"):
    def get(path, params=None, **kw):
        if path == "/me/drive":
            return {"id": mine}
        return {"id": drive_id, "driveType": drive_type}
    gc.get.side_effect = get


def _broken_client():
    raise RuntimeError("not signed in")


SRC, DEST = {"drive_id": "d1", "item_id": "i1"}, {"drive_id": "d2", "folder_id": "f2"}


def test_foreign_owner_true_for_someone_elses_onedrive():
    p, gc = provider()
    _drives(gc, "business", drive_id="theirs")
    assert p.is_foreign_owner({"drive_id": "theirs", "item_id": "i"}) is True


def test_own_onedrive_is_not_foreign():
    p, gc = provider()
    _drives(gc, "business", drive_id="mine")
    assert p.is_foreign_owner({"drive_id": "mine", "item_id": "i"}) is False


def test_sharepoint_library_is_not_foreign():
    p, gc = provider()
    _drives(gc, "documentLibrary", drive_id="lib")
    assert p.is_foreign_owner({"drive_id": "lib", "item_id": "i"}) is False


def test_unverifiable_owner_is_treated_as_foreign():
    p, gc = provider()
    gc.get.side_effect = Err(403)
    assert p.is_foreign_owner({"drive_id": "x", "item_id": "i"}) is True
    p, _ = provider(client=_broken_client)
    assert p.is_foreign_owner({"drive_id": "x", "item_id": "i"}) is True


def test_foreign_owner_drive_path_is_encoded():
    p, gc = provider()
    _drives(gc, "business", drive_id="b!a/b")
    p.is_foreign_owner({"drive_id": "b!a/b", "item_id": "i"})
    assert "/drives/b%21a%2Fb" in [c.args[0] for c in gc.get.call_args_list]


def test_find_in_folder_matches_name_and_size_with_encoded_path():
    p, gc = provider()
    gc.get.return_value = {"id": "X", "name": "a b.docx", "size": 10, "webUrl": "u", "parentReference": {"driveId": "d2"}}
    found = p.find_in_folder({"drive_id": "d/2", "folder_id": "f+2"}, "a b.docx", 10)
    assert found == {"item_id": "X", "drive_id": "d2", "name": "a b.docx", "web_url": "u"}
    assert gc.get.call_args.args[0] == "/drives/d%2F2/items/f%2B2:/a%20b.docx"


def test_find_in_folder_none_on_size_mismatch_or_error():
    p, gc = provider()
    gc.get.return_value = {"id": "X", "name": "a.docx", "size": 99, "webUrl": "u", "parentReference": {}}
    assert p.find_in_folder({"drive_id": "d", "folder_id": "f"}, "a.docx", 10) is None
    gc.get.side_effect = Err(404)
    assert p.find_in_folder({"drive_id": "d", "folder_id": "f"}, "a.docx", 10) is None
    p, _ = provider(client=_broken_client)
    assert p.find_in_folder({"drive_id": "d", "folder_id": "f"}, "a.docx", 10) is None


def test_find_in_folder_none_when_item_has_no_id():
    p, gc = provider()
    gc.get.return_value = {"name": "a.docx", "size": 10}
    assert p.find_in_folder({"drive_id": "d", "folder_id": "f"}, "a.docx", 10) is None


def _writing_download(seen):
    """Stand-in for _tool_download_onedrive_file: writes the bytes over local_path."""
    def dl(file_id, drive_id, local_path):
        dest = Path(local_path)
        seen.append({"parent_existed": dest.parent.is_dir(), "reserved": dest.is_file()})
        dest.write_bytes(b"abc")
        return {"saved_to": str(dest), "name": dest.name, "size_bytes": 3}
    return dl


def test_download_creates_the_downloads_dir_and_saves(tmp_path):
    seen = []
    dl = MagicMock(side_effect=_writing_download(seen))
    p, _ = provider(download=dl)
    target = tmp_path / "Downloads" / "sub" / "a.docx"
    out = p.download({"drive_id": "d", "item_id": "i"}, str(target))
    assert out["saved_to"] == str(target)
    assert target.read_bytes() == b"abc"
    assert seen == [{"parent_existed": True, "reserved": True}]
    dl.assert_called_once_with(file_id="i", drive_id="d", local_path=str(target))


def test_download_never_overwrites_an_existing_local_file(tmp_path):
    target = tmp_path / "a.docx"
    target.write_bytes(b"keep me")
    dl = MagicMock()
    p, _ = provider(download=dl)
    out = p.download({"drive_id": "d", "item_id": "i"}, str(target))
    assert out["error_code"] == "conflict" and "error" in out
    assert target.read_bytes() == b"keep me"
    dl.assert_not_called()


def test_download_exception_maps_to_error_code(tmp_path):
    dl = MagicMock(side_effect=Err(423))
    p, _ = provider(download=dl)
    out = p.download({"drive_id": "d", "item_id": "i"}, str(tmp_path / "a.docx"))
    assert out["error_code"] == "locked" and "error" in out


def test_download_error_dict_without_code_gets_unknown(tmp_path):
    dl = MagicMock(return_value={"error": "Got HTML instead of file bytes"})
    p, _ = provider(download=dl)
    out = p.download({"drive_id": "d", "item_id": "i"}, str(tmp_path / "a.docx"))
    assert out["error_code"] == "unknown" and "Got HTML" in out["error"]


class UploadGC:
    def __init__(self):
        self.paths = []
        self.requests = []

    def put_binary(self, path, data, content_type="application/octet-stream"):
        self.paths.append(path)
        return {"id": "N1", "name": "a.txt", "size": len(data), "webUrl": "https://od/a.txt"}

    def post(self, path, body):
        self.paths.append(path)
        self.session_body = body
        return {"uploadUrl": "https://upload.example/session"}

    def _request(self, method, url, headers=None, content=b"", label=""):
        self.requests.append((method, url, dict(headers or {})))
        resp = MagicMock()
        resp.json.return_value = {"id": "N1", "name": "a.txt", "size": 5, "webUrl": "https://od/a.txt"}
        return resp


def test_upload_returns_item_fields_and_never_overwrites(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")
    gc = UploadGC()
    p, _ = provider(gc=gc)
    out = p.upload(str(f), {"drive_id": "d2", "folder_id": "f2"}, "")
    assert out == {"item_id": "N1", "drive_id": "d2", "name": "a.txt", "web_url": "https://od/a.txt", "size": 5}
    assert gc.paths[0].startswith("/drives/d2/items/f2:/a.txt:/content")
    assert gc.paths[0].endswith("conflictBehavior=rename")


def test_large_upload_session_gets_no_authorization(tmp_path, monkeypatch):
    monkeypatch.setattr(ft, "SIMPLE_UPLOAD_MAX", 1)
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")
    gc = UploadGC()
    p, _ = provider(gc=gc)
    out = p.upload(str(f), {"drive_id": "d2", "folder_id": "f2"}, "a.txt")
    assert out["item_id"] == "N1"
    assert gc.session_body["item"]["@microsoft.graph.conflictBehavior"] == "rename"
    assert gc.requests and all(
        "authorization" not in {k.lower() for k in headers} for _, _, headers in gc.requests
    )


def test_upload_missing_local_file_is_not_found(tmp_path):
    p, _ = provider()
    out = p.upload(str(tmp_path / "nope.txt"), {"drive_id": "d", "folder_id": "f"}, "")
    assert out["error_code"] == "not_found"


def test_upload_file_vanishing_after_check_is_not_found(tmp_path, monkeypatch):
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")

    def gone(path, name=""):
        raise FileNotFoundError(path)

    monkeypatch.setattr(ft, "file_source", gone)
    p, _ = provider(gc=UploadGC())
    out = p.upload(str(f), {"drive_id": "d", "folder_id": "f"}, "")
    assert out["error_code"] == "not_found" and "error" in out


def test_upload_graph_failure_maps_to_error_code(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")
    gc = UploadGC()
    gc.put_binary = MagicMock(side_effect=Err(429))
    p, _ = provider(gc=gc)
    out = p.upload(str(f), {"drive_id": "d", "folder_id": "f"}, "")
    assert out["error_code"] == "throttled" and out["error"]
    p, _ = provider(client=_broken_client)
    out = p.upload(str(f), {"drive_id": "d", "folder_id": "f"}, "")
    assert out["error_code"] == "unknown" and "not signed in" in out["error"]


def test_move_copy_stat_delegate_with_positional_ids():
    move, copy, get_item = MagicMock(return_value={"item_id": "m"}), MagicMock(return_value={"status": "completed"}), MagicMock(return_value={"name": "n"})
    p, _ = provider(move=move, copy=copy, get_item=get_item)
    assert p.move(SRC, DEST, "new.docx") == {"item_id": "m"}
    move.assert_called_once_with("d1", "i1", "d2", "f2", "new.docx")
    assert p.copy(SRC, DEST, "") == {"status": "completed"}
    copy.assert_called_once_with("d1", "i1", "d2", "f2", "")
    assert p.stat(SRC) == {"name": "n"}
    get_item.assert_called_once_with("d1", "i1")


def test_move_copy_stat_exceptions_become_error_results():
    p, _ = provider(move=MagicMock(side_effect=Err(423)), copy=MagicMock(side_effect=Err(403)), get_item=MagicMock(side_effect=Err(404)))
    assert p.move(SRC, DEST, "")["error_code"] == "locked"
    assert p.copy(SRC, DEST, "")["error_code"] == "forbidden"
    assert p.stat(SRC)["error_code"] == "not_found"


def test_tool_error_dicts_without_code_get_unknown():
    bare = MagicMock(return_value={"error": "boom"})
    p, _ = provider(move=bare, copy=bare, get_item=bare)
    for out in (p.move(SRC, DEST, ""), p.copy(SRC, DEST, ""), p.stat(SRC)):
        assert out == {"error": "boom", "error_code": "unknown"}


def test_copy_exception_without_http_status_is_ambiguous():
    p, _ = provider(copy=MagicMock(side_effect=TimeoutError("timed out")))
    out = p.copy(SRC, DEST, "")
    assert out["ambiguous"] is True and out["error_code"] == "unknown"


def test_copy_exception_with_http_status_is_not_ambiguous():
    p, _ = provider(copy=MagicMock(side_effect=Err(500)))
    assert "ambiguous" not in p.copy(SRC, DEST, "")
