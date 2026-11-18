import json

import pytest

from skills._sharing.errors import ShareError


@pytest.fixture(autouse=True)
def _all_tiers_allowed(tmp_path):
    from sandbox import policy

    (tmp_path / "sandbox-policy.json").write_text(
        json.dumps({"marketplace_allowed_tiers": ["Native", "Verified", "Community", "Mine"]}), encoding="utf-8"
    )
    policy._reset_cache()
    yield
    policy._reset_cache()


class FakeProvider:
    """In-memory stand-in for GraphSharingProvider with the same method names and error codes."""

    def __init__(self):
        self.folders = {}
        self.files = {}
        self.grants = []
        self.ungrantable = set()
        self.writes = []
        self.fail_on = {}
        self._n = 0

    def _maybe_fail(self, op):
        err = self.fail_on.pop(op, None)
        if err:
            raise err

    def _folder(self, parent_id, name, create):
        key = (parent_id, name)
        if key not in self.folders:
            if not create:
                return None
            self._n += 1
            self.folders[key] = {
                "drive_id": "d1",
                "folder_id": f"f{self._n}",
                "web_url": f"https://onedrive.example/{name}",
                "name": name,
            }
        return dict(self.folders[key])

    def default_root(self):
        return self._folder("", "AI Gator Skills", True)

    def child_folder(self, parent, name, create=True):
        return self._folder(parent["folder_id"], name, create)

    def read_file(self, folder, name, max_bytes=None):
        self._maybe_fail("read_file")
        found = self.files.get((folder["folder_id"], name))
        if found is not None and max_bytes is not None and len(found[0]) > max_bytes:
            raise ShareError("too_large", "too big")
        return found

    def read_json(self, folder, name, max_bytes=None):
        found = self.read_file(folder, name, max_bytes)
        return (json.loads(found[0]), found[1]) if found else None

    def _put(self, folder, name, data):
        self._n += 1
        self.files[(folder["folder_id"], name)] = (data, f'"e{self._n}"')
        self.writes.append((folder["name"], name))

    def write_file(self, folder, name, data):
        self._maybe_fail("write_file")
        self._put(folder, name, data)

    def write_json_create(self, folder, name, doc):
        self._maybe_fail("write_json_create")
        if (folder["folder_id"], name) in self.files:
            raise ShareError("conflict", "exists")
        self._put(folder, name, json.dumps(doc).encode())

    def write_json_replace(self, folder, name, doc, etag):
        self._maybe_fail("write_json_replace")
        current = self.files.get((folder["folder_id"], name))
        if current is None or current[1] != etag:
            raise ShareError("conflict", "changed")
        self._put(folder, name, json.dumps(doc).encode())

    def grant_read(self, folder, emails):
        self._maybe_fail("grant_read")
        refused = [e for e in emails if e in self.ungrantable]
        granted = [e for e in emails if e not in self.ungrantable]
        if granted:
            self.grants.append((folder["folder_id"], granted))
        return refused


@pytest.fixture
def provider():
    return FakeProvider()


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    from marketplace import installer

    root = tmp_path / "installed"
    root.mkdir()
    monkeypatch.setattr(installer, "INSTALLED_SKILLS_DIR", root)
    monkeypatch.setattr(installer, "PLUGINS_DIR", tmp_path / "plugins")
    return root


@pytest.fixture
def make_mine(skills_dir):
    from marketplace import installer

    def make(name="Weekly Report", instructions="Do the thing", extra=None):
        skill_id = installer.create_user_skill(name, "Summarise the week", instructions)["skill_id"]
        for rel, data in (extra or {}).items():
            path = skills_dir / "mine" / skill_id / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return skill_id

    return make
