import json
from urllib.parse import quote

import pytest

from skills._sharing.errors import ShareError
from skills._sharing.provider import ROOT_FOLDER_NAME, GraphSharingProvider


def q(value):
    return quote(value, safe="")


class _Err(Exception):
    def __init__(self, status):
        super().__init__(f"http {status}")
        self.status_code = status


class FakeGc:
    def __init__(self):
        self.items = {}
        self.blobs = {}
        self.get_errors = {}
        self.post_errors = {}
        self.posts = []
        self.puts = []
        self.put_error = None

    def get(self, path, params=None):
        if path in self.get_errors:
            raise self.get_errors[path]
        if path in self.items:
            return self.items[path]
        raise _Err(404)

    def get_bytes(self, path):
        return self.blobs[path]

    def post(self, path, body):
        self.posts.append((path, body))
        if path in self.post_errors:
            raise self.post_errors[path]
        return {
            "id": "new-" + body.get("name", "x"),
            "name": body.get("name", ""),
            "webUrl": "https://onedrive.example/" + body.get("name", ""),
            "folder": {},
            "parentReference": {"driveId": "d1"},
        }

    def put_binary(self, path, data, content_type="application/octet-stream", extra_headers=None):
        self.puts.append({"path": path, "data": data, "extra_headers": extra_headers})
        if self.put_error:
            raise self.put_error
        return {"id": "file1", "name": "x", "webUrl": "https://x", "size": len(data)}


def _folder_item(item_id, name):
    return {"id": item_id, "name": name, "webUrl": f"https://onedrive.example/{name}", "folder": {}, "parentReference": {"driveId": "d1"}}


ROOT_GET = f"/me/drive/root:/{q(ROOT_FOLDER_NAME)}"


def test_default_root_creates_the_folder_when_missing():
    gc = FakeGc()
    root = GraphSharingProvider(gc).default_root()
    assert root["drive_id"] == "d1"
    assert root["folder_id"] == "new-AI Gator Skills"
    assert gc.posts[0][0] == "/me/drive/root/children"
    assert gc.posts[0][1]["@microsoft.graph.conflictBehavior"] == "fail"


def test_default_root_reuses_an_existing_folder():
    gc = FakeGc()
    gc.items[ROOT_GET] = _folder_item("root1", ROOT_FOLDER_NAME)
    root = GraphSharingProvider(gc).default_root()
    assert root["folder_id"] == "root1"
    assert gc.posts == []


def test_default_root_survives_a_creation_race():
    gc = FakeGc()
    gets = iter([_Err(404), _folder_item("root1", ROOT_FOLDER_NAME)])

    def racing_get(path, params=None):
        out = next(gets)
        if isinstance(out, Exception):
            raise out
        return out

    gc.get = racing_get
    gc.post_errors["/me/drive/root/children"] = _Err(409)
    assert GraphSharingProvider(gc).default_root()["folder_id"] == "root1"


def test_a_file_in_the_way_of_a_folder_is_a_conflict():
    gc = FakeGc()
    gc.items[ROOT_GET] = {"id": "f1", "name": ROOT_FOLDER_NAME, "file": {}, "parentReference": {"driveId": "d1"}}
    with pytest.raises(ShareError) as err:
        GraphSharingProvider(gc).default_root()
    assert err.value.code == "conflict"


def test_child_folder_creates_under_the_parent():
    gc = FakeGc()
    parent = {"drive_id": "d1", "folder_id": "p1", "web_url": "", "name": "p"}
    child = GraphSharingProvider(gc).child_folder(parent, "weekly-report")
    assert child["drive_id"] == "d1"
    assert gc.posts[0][0] == "/drives/d1/items/p1/children"


def test_child_folder_without_create_returns_none_when_missing():
    gc = FakeGc()
    parent = {"drive_id": "d1", "folder_id": "p1", "web_url": "", "name": "p"}
    assert GraphSharingProvider(gc).child_folder(parent, "nope", create=False) is None
    assert gc.posts == []


def test_ids_are_percent_encoded():
    gc = FakeGc()
    parent = {"drive_id": "b!x/y", "folder_id": "01/AB=", "web_url": "", "name": "p"}
    seen = []
    gc.get = lambda path, params=None: seen.append(path) or (_ for _ in ()).throw(_Err(404))
    GraphSharingProvider(gc).child_folder(parent, "v1", create=False)
    assert seen == [f"/drives/{q('b!x/y')}/items/{q('01/AB=')}:/v1"]


def test_read_json_returns_document_and_etag():
    gc = FakeGc()
    folder = {"drive_id": "d1", "folder_id": "f1", "web_url": "", "name": "f"}
    gc.items["/drives/d1/items/f1:/skill.json"] = {"id": "j1", "eTag": '"e1"', "file": {}}
    gc.blobs["/drives/d1/items/j1/content"] = json.dumps({"latest": 2}).encode()
    assert GraphSharingProvider(gc).read_json(folder, "skill.json") == ({"latest": 2}, '"e1"')


def test_read_json_returns_none_when_the_file_is_missing():
    folder = {"drive_id": "d1", "folder_id": "f1", "web_url": "", "name": "f"}
    assert GraphSharingProvider(FakeGc()).read_json(folder, "skill.json") is None


def test_read_json_rejects_garbage():
    gc = FakeGc()
    folder = {"drive_id": "d1", "folder_id": "f1", "web_url": "", "name": "f"}
    gc.items["/drives/d1/items/f1:/skill.json"] = {"id": "j1", "eTag": '"e1"', "file": {}}
    gc.blobs["/drives/d1/items/j1/content"] = b"not json"
    with pytest.raises(ShareError) as err:
        GraphSharingProvider(gc).read_json(folder, "skill.json")
    assert err.value.code == "invalid"


def test_forbidden_is_reported_with_a_code():
    gc = FakeGc()
    folder = {"drive_id": "d1", "folder_id": "f1", "web_url": "", "name": "f"}
    gc.get_errors["/drives/d1/items/f1:/skill.json"] = _Err(403)
    with pytest.raises(ShareError) as err:
        GraphSharingProvider(gc).read_json(folder, "skill.json")
    assert err.value.code == "forbidden"


def test_write_file_replaces():
    gc = FakeGc()
    folder = {"drive_id": "d1", "folder_id": "f1", "web_url": "", "name": "f"}
    GraphSharingProvider(gc).write_file(folder, "bundle.zip", b"abc")
    assert "conflictBehavior=replace" in gc.puts[0]["path"]


def test_write_json_create_fails_when_the_file_exists():
    gc = FakeGc()
    gc.put_error = _Err(409)
    folder = {"drive_id": "d1", "folder_id": "f1", "web_url": "", "name": "f"}
    with pytest.raises(ShareError) as err:
        GraphSharingProvider(gc).write_json_create(folder, "skill.json", {"latest": 1})
    assert err.value.code == "conflict"
    assert "conflictBehavior=fail" in gc.puts[0]["path"]


def test_write_json_replace_sends_if_match_and_maps_412():
    gc = FakeGc()
    folder = {"drive_id": "d1", "folder_id": "f1", "web_url": "", "name": "f"}
    GraphSharingProvider(gc).write_json_replace(folder, "skill.json", {"latest": 2}, '"e1"')
    assert gc.puts[0]["extra_headers"] == {"If-Match": '"e1"'}
    gc.put_error = _Err(412)
    with pytest.raises(ShareError) as err:
        GraphSharingProvider(gc).write_json_replace(folder, "skill.json", {"latest": 3}, '"e1"')
    assert err.value.code == "conflict"


def test_write_json_replace_refuses_a_missing_etag():
    gc = FakeGc()
    folder = {"drive_id": "d1", "folder_id": "f1", "web_url": "", "name": "f"}
    with pytest.raises(ShareError) as err:
        GraphSharingProvider(gc).write_json_replace(folder, "skill.json", {"latest": 2}, "")
    assert err.value.code == "conflict"
    assert gc.puts == []


def test_grant_read_is_read_only_and_silent():
    gc = FakeGc()
    folder = {"drive_id": "d1", "folder_id": "f1", "web_url": "", "name": "f"}
    GraphSharingProvider(gc).grant_read(folder, ["a@contoso.com", "b@contoso.com"])
    path, body = gc.posts[0]
    assert path == "/drives/d1/items/f1/invite"
    assert body == {
        "recipients": [{"email": "a@contoso.com"}, {"email": "b@contoso.com"}],
        "roles": ["read"],
        "requireSignIn": True,
        "sendInvitation": False,
    }


def test_grant_read_with_nobody_does_nothing():
    gc = FakeGc()
    GraphSharingProvider(gc).grant_read({"drive_id": "d1", "folder_id": "f1", "web_url": "", "name": "f"}, [])
    assert gc.posts == []
