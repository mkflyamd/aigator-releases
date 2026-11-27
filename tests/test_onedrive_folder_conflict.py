"""Creating a OneDrive folder can ask Graph to fail on a name clash instead of renaming."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "web"))

from routes.onedrive import router  # noqa: E402
from security import get_csrf_token  # noqa: E402

PERSONAL = "/api/onedrive/folders/root"
SHARED = "/api/onedrive/drives/d1/folders/root"


class _Clash(Exception):
    status_code = 409


class _Gc:
    def __init__(self, error=None):
        self.error = error
        self.sent = []

    def post(self, path, body):
        self.sent.append((path, body))
        if self.error:
            raise self.error
        return {"id": "new1", "name": body["name"] + (" 1" if body["@microsoft.graph.conflictBehavior"] == "rename" else "")}


def _post(gc, path, body):
    app = FastAPI()
    app.include_router(router)
    with patch("skills._m365.helpers.get_graph_client", return_value=gc):
        return TestClient(app).post(path, json=body, headers={"X-CSRF-Token": get_csrf_token("testserver")})


@pytest.mark.parametrize("path", [PERSONAL, SHARED])
def test_the_default_still_renames_on_a_clash(path):
    gc = _Gc()
    res = _post(gc, path, {"name": "Docs"})
    assert res.status_code == 200
    assert res.json() == {"id": "new1", "name": "Docs 1"}
    assert gc.sent[0][1]["@microsoft.graph.conflictBehavior"] == "rename"


@pytest.mark.parametrize("path", [PERSONAL, SHARED])
def test_fail_mode_asks_graph_to_fail(path):
    gc = _Gc()
    res = _post(gc, path, {"name": "Docs", "conflict": "fail"})
    assert res.status_code == 200
    assert gc.sent[0][1]["@microsoft.graph.conflictBehavior"] == "fail"


@pytest.mark.parametrize("path", [PERSONAL, SHARED])
def test_fail_mode_reports_an_existing_folder_as_a_409(path):
    res = _post(_Gc(_Clash()), path, {"name": "Docs", "conflict": "fail"})
    assert res.status_code == 409
    assert res.json()["detail"]["error"] == "folder_exists"
    assert "Docs" in res.json()["detail"]["message"]


@pytest.mark.parametrize("path", [PERSONAL, SHARED])
def test_other_failures_in_fail_mode_are_still_a_500(path):
    res = _post(_Gc(RuntimeError("boom")), path, {"name": "Docs", "conflict": "fail"})
    assert res.status_code == 500


@pytest.mark.parametrize("path", [PERSONAL, SHARED])
def test_a_clash_in_rename_mode_is_not_reported_as_folder_exists(path):
    res = _post(_Gc(_Clash()), path, {"name": "Docs"})
    assert res.status_code == 500


@pytest.mark.parametrize("path", [PERSONAL, SHARED])
@pytest.mark.parametrize("value", ["replace", "", None, 3])
def test_an_unknown_conflict_value_is_a_400(path, value):
    gc = _Gc()
    res = _post(gc, path, {"name": "Docs", "conflict": value})
    assert res.status_code == 400
    assert gc.sent == []
