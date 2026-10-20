import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

import security


def _client():
    app = FastAPI()

    @app.post("/x", dependencies=[Depends(security.verify_csrf)])
    def x():
        return {"ok": True}

    return TestClient(app)


def test_token_differs_per_origin_and_is_stable_for_one_origin():
    a = security.get_csrf_token("127.0.0.1:8000")
    assert a == security.get_csrf_token("127.0.0.1:8000")
    assert a == security.get_csrf_token(" 127.0.0.1:8000 ".upper())
    assert a != security.get_csrf_token("localhost:8000")
    assert a != security.get_csrf_token("127.0.0.1:8001")


def test_token_from_another_origin_is_refused():
    client = _client()
    good = {"X-CSRF-Token": security.get_csrf_token("127.0.0.1:8000"), "Host": "127.0.0.1:8000"}
    assert client.post("/x", headers=good).status_code == 200
    stolen = {"X-CSRF-Token": security.get_csrf_token("localhost:8000"), "Host": "127.0.0.1:8000"}
    assert client.post("/x", headers=stolen).status_code == 403
    assert client.post("/x", headers={"Host": "127.0.0.1:8000"}).status_code == 403


def test_index_page_embeds_a_token_bound_to_its_host():
    import app as app_module

    client = TestClient(app_module.app)
    html = client.get("/", headers={"Host": "127.0.0.1:8000"}).text
    assert security.get_csrf_token("127.0.0.1:8000") in html
    assert security.get_csrf_token("localhost:8000") not in html
    assert client.get("/api/csrf", headers={"Host": "localhost:8000"}).json()["csrf_token"] == security.get_csrf_token("localhost:8000")
