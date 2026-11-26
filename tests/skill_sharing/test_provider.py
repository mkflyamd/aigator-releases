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
        self.downloads = []

    def get(self, path, params=None):
        if path in self.get_errors:
            raise self.get_errors[path]
        if path in self.items:
            return self.items[path]
        raise _Err(404)

    def get_bytes(self, path):
        self.downloads.append(path)
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


def test_default_root_without_create_returns_none_and_creates_nothing():
    gc = FakeGc()
    assert GraphSharingProvider(gc).default_root(create=False) is None
    assert gc.posts == []


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


def _sized_file(gc, size, data=b"abc"):
    gc.items["/drives/d1/items/f1:/bundle.zip"] = {"id": "b1", "eTag": '"e1"', "file": {}, "size": size}
    gc.blobs["/drives/d1/items/b1/content"] = data
    return {"drive_id": "d1", "folder_id": "f1", "web_url": "", "name": "f"}


def test_read_file_over_the_limit_is_too_large_and_downloads_nothing():
    gc = FakeGc()
    folder = _sized_file(gc, 101)
    with pytest.raises(ShareError) as err:
        GraphSharingProvider(gc).read_file(folder, "bundle.zip", max_bytes=100)
    assert err.value.code == "too_large"
    assert gc.downloads == []


@pytest.mark.parametrize("size", [100, 3])
def test_read_file_at_or_under_the_limit_downloads(size):
    gc = FakeGc()
    folder = _sized_file(gc, size)
    assert GraphSharingProvider(gc).read_file(folder, "bundle.zip", max_bytes=100) == (b"abc", '"e1"')
    assert len(gc.downloads) == 1


def test_read_json_has_a_default_size_limit():
    gc = FakeGc()
    gc.items["/drives/d1/items/f1:/skill.json"] = {"id": "j1", "eTag": '"e1"', "file": {}, "size": 50 * 1024 * 1024}
    folder = {"drive_id": "d1", "folder_id": "f1", "web_url": "", "name": "f"}
    with pytest.raises(ShareError) as err:
        GraphSharingProvider(gc).read_json(folder, "skill.json")
    assert err.value.code == "too_large"
    assert gc.downloads == []


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


def test_write_file_create_fails_when_the_file_exists():
    gc = FakeGc()
    folder = {"drive_id": "d1", "folder_id": "f1", "web_url": "", "name": "f"}
    GraphSharingProvider(gc).write_file_create(folder, "bundle.zip", b"abc")
    assert "conflictBehavior=fail" in gc.puts[0]["path"]
    gc.put_error = _Err(409)
    with pytest.raises(ShareError) as err:
        GraphSharingProvider(gc).write_file_create(folder, "bundle.zip", b"abc")
    assert err.value.code == "conflict"


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


class _InviteGc(FakeGc):
    """Invite calls that name an address in `refuse` fail with 400."""

    def __init__(self, refuse=(), status=400):
        super().__init__()
        self.refuse = set(refuse)
        self.status = status

    def post(self, path, body):
        self.posts.append((path, body))
        if any(r["email"] in self.refuse for r in body["recipients"]):
            raise _Err(self.status)
        return {}


FOLDER = {"drive_id": "d1", "folder_id": "f1", "web_url": "", "name": "f"}


def test_grant_read_returns_nothing_refused_when_every_address_is_accepted():
    gc = _InviteGc()
    assert GraphSharingProvider(gc).grant_read(FOLDER, ["a@contoso.com", "b@contoso.com"]) == []
    assert len(gc.posts) == 1


def test_grant_read_invites_the_rest_when_one_address_is_refused():
    gc = _InviteGc(refuse={"bad@gmail.com"})
    refused = GraphSharingProvider(gc).grant_read(FOLDER, ["a@contoso.com", "bad@gmail.com", "b@contoso.com"])
    assert refused == ["bad@gmail.com"]
    accepted = [r["email"] for _, body in gc.posts[1:] for r in body["recipients"] if r["email"] not in gc.refuse]
    assert accepted == ["a@contoso.com", "b@contoso.com"]


def test_grant_read_reports_every_address_refused():
    gc = _InviteGc(refuse={"x@gmail.com", "y@gmail.com"})
    assert GraphSharingProvider(gc).grant_read(FOLDER, ["x@gmail.com", "y@gmail.com"]) == ["x@gmail.com", "y@gmail.com"]


@pytest.mark.parametrize("status,code", [(403, "forbidden"), (429, "throttled")])
def test_grant_read_still_fails_on_errors_other_than_a_refused_address(status, code):
    gc = _InviteGc(refuse={"a@contoso.com"}, status=status)
    with pytest.raises(ShareError) as err:
        GraphSharingProvider(gc).grant_read(FOLDER, ["a@contoso.com"])
    assert err.value.code == code
    assert len(gc.posts) == 1


def test_grant_read_with_nobody_does_nothing():
    gc = FakeGc()
    GraphSharingProvider(gc).grant_read({"drive_id": "d1", "folder_id": "f1", "web_url": "", "name": "f"}, [])
    assert gc.posts == []


def _drive_gc(drive_type="business", name="OneDrive", item=None, perms=None, perm_error=None, my_id="d1"):
    gc = FakeGc()
    gc.items["/me/drive"] = {"id": my_id}
    gc.items["/drives/d1"] = {"id": "d1", "name": name, "driveType": drive_type}
    gc.items["/drives/d1/items/f9"] = item or {}
    if perms is not None:
        gc.items["/drives/d1/items/f9/permissions"] = {"value": perms}
    if perm_error:
        gc.get_errors["/drives/d1/items/f9/permissions"] = perm_error
    return gc


def test_describe_folder_builds_a_display_path_from_the_drive_and_parents():
    item = {
        "id": "f9",
        "name": "Templates",
        "webUrl": "https://x/Templates",
        "folder": {},
        "parentReference": {"driveId": "d1", "path": "/drives/d1/root:/Team%20Docs/Skills"},
    }
    loc = GraphSharingProvider(_drive_gc(name="Marketing", item=item)).describe_folder("d1", "f9")
    assert loc == {
        "drive_id": "d1",
        "folder_id": "f9",
        "name": "Templates",
        "path": ["Marketing", "Team Docs", "Skills", "Templates"],
        "web_url": "https://x/Templates",
    }


def test_describe_folder_of_a_drive_root_is_just_the_drive_name():
    item = {"id": "f9", "name": "root", "folder": {}, "root": {}, "parentReference": {"driveId": "d1"}}
    assert GraphSharingProvider(_drive_gc(name="OneDrive", item=item)).describe_folder("d1", "f9")["path"] == ["OneDrive"]


def test_describe_folder_refuses_a_file():
    gc = _drive_gc(item={"id": "f9", "name": "a.docx", "file": {}})
    with pytest.raises(ShareError) as err:
        GraphSharingProvider(gc).describe_folder("d1", "f9")
    assert err.value.code == "invalid"


def test_describe_folder_reports_a_missing_folder():
    gc = _drive_gc()
    gc.get_errors["/drives/d1/items/f9"] = _Err(404)
    with pytest.raises(ShareError) as err:
        GraphSharingProvider(gc).describe_folder("d1", "f9")
    assert err.value.code == "not_found"


def test_audience_of_a_sharepoint_library_is_the_library():
    gc = _drive_gc(drive_type="documentLibrary", name="Marketing site")
    assert GraphSharingProvider(gc).audience("d1", "f9", "Templates") == {
        "kind": "library",
        "name": "Marketing site",
        "approx_count": None,
    }


def test_audience_of_an_unshared_folder_in_my_own_onedrive_is_private():
    gc = _drive_gc(perms=[{"roles": ["owner"]}])
    assert GraphSharingProvider(gc).audience("d1", "f9", "Mine")["kind"] == "private"


@pytest.mark.parametrize(
    ("scope", "kind", "name"),
    [("organization", "org", "Your organization"), ("anonymous", "anyone", "Anyone with the link")],
)
def test_audience_with_a_wide_link_names_who_can_open_it(scope, kind, name):
    gc = _drive_gc(perms=[{"roles": ["owner"]}, {"roles": ["read"], "link": {"scope": scope}}])
    out = GraphSharingProvider(gc).audience("d1", "f9", "Mine")
    assert (out["kind"], out["name"]) == (kind, name)


def test_an_anonymous_link_wins_over_an_organization_link():
    gc = _drive_gc(
        perms=[{"link": {"scope": "organization"}}, {"roles": ["read"], "link": {"scope": "anonymous"}}]
    )
    assert GraphSharingProvider(gc).audience("d1", "f9", "Mine")["kind"] == "anyone"


def test_audience_counts_the_people_a_folder_is_already_shared_with():
    gc = _drive_gc(perms=[{"roles": ["owner"]}, {"roles": ["read"]}, {"roles": ["write"]}])
    assert GraphSharingProvider(gc).audience("d1", "f9", "Shared") == {
        "kind": "folder",
        "name": "Shared",
        "approx_count": 2,
    }


def test_audience_is_not_private_when_the_permissions_cannot_be_read():
    gc = _drive_gc(perm_error=_Err(403))
    assert GraphSharingProvider(gc).audience("d1", "f9", "Mine")["kind"] == "folder"


def test_audience_of_a_folder_in_someone_elses_onedrive_is_not_private():
    gc = _drive_gc(perms=[{"roles": ["owner"]}], my_id="mine")
    assert GraphSharingProvider(gc).audience("d1", "f9", "Theirs")["kind"] == "folder"


def test_my_user_id_is_the_directory_id_not_a_display_name():
    gc = FakeGc()
    gc.items["/me"] = {"id": "aad-111", "displayName": "Ann"}
    assert GraphSharingProvider(gc).my_user_id() == "aad-111"
