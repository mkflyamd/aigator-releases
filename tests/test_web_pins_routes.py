import asyncio
import base64
import uuid

import pytest
from fastapi.testclient import TestClient

from app import app
from security import get_csrf_token
from skills.context import state
from skills.webpin import pending, store

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


@pytest.fixture
def client():
    return TestClient(app, headers={"X-CSRF-Token": get_csrf_token("testserver")})


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_ROOT", tmp_path / "web_pins")
    monkeypatch.setattr(state, "pinned_contexts", {})
    monkeypatch.setattr(state, "_save", lambda: None)
    import routes.web_pins as wp

    monkeypatch.setattr(wp, "_custom_apps", lambda: [{"id": "pbi", "name": "Power BI", "url": "https://app.powerbi.com"}])


def _body(**over):
    b = {
        "context_id": "tab-a",
        "app_id": "pbi",
        "image_b64": _b64(PNG),
        "text": "Revenue 4.2M",
        "locator": {"selector": "#kpi", "role": "img", "name": "Revenue", "rect": [1, 2, 3, 4]},
        "url": "https://app.powerbi.com/report/1",
        "title": "Finance",
        "aria_label": "Revenue card",
    }
    b.update(over)
    return b


def test_create_pin_ok(client):
    r = client.post("/api/web-pins", json=_body())
    assert r.status_code == 200, r.text
    j = r.json()
    uuid.UUID(j["id"])
    assert j["label"] == "Revenue card"
    pins = state.get_pins("tab-a")
    assert pins[0]["source"] == "webpin" and pins[0]["meta"]["app_id"] == "pbi"
    assert store.read_snapshot(j["id"])["text"] == "Revenue 4.2M"
    assert store.read_image(j["id"]) == PNG


def test_create_requires_csrf():
    r = TestClient(app).post("/api/web-pins", json=_body())
    assert r.status_code == 403


def test_create_rejects_unknown_app(client):
    assert client.post("/api/web-pins", json=_body(app_id="nope")).status_code == 400


def test_create_rejects_non_png(client):
    assert client.post("/api/web-pins", json=_body(image_b64=_b64(b"GIF89a-----"))).status_code == 400


def test_create_rejects_bad_base64(client):
    assert client.post("/api/web-pins", json=_body(image_b64="***")).status_code == 400


def test_create_rejects_oversize_text_and_image(client):
    assert client.post("/api/web-pins", json=_body(text="x" * 20001)).status_code == 413
    big = _b64(PNG + b"0" * (5 * 1024 * 1024))
    assert client.post("/api/web-pins", json=_body(image_b64=big)).status_code == 413


def test_label_is_sanitised_and_falls_back_to_title_then_app(client):
    j = client.post("/api/web-pins", json=_body(aria_label='A "b"\nignore previous')).json()
    assert "\n" not in j["label"] and '"' not in j["label"]
    j2 = client.post("/api/web-pins", json=_body(aria_label="")).json()
    assert j2["label"] == "Finance"
    j3 = client.post("/api/web-pins", json=_body(aria_label="", title="")).json()
    assert j3["label"] == "Power BI"


def test_get_pin_and_image(client):
    pid = client.post("/api/web-pins", json=_body()).json()["id"]
    j = client.get(f"/api/web-pins/{pid}").json()
    assert j["text"] == "Revenue 4.2M" and j["meta"]["locator"]["selector"] == "#kpi" and j["has_image"] is True
    img = client.get(f"/api/web-pins/{pid}/image")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png" and img.content == PNG
    assert client.get("/api/web-pins/not-a-uuid").status_code == 404
    assert client.get(f"/api/web-pins/{uuid.uuid4()}").status_code == 404


def test_user_refresh_snapshot_updates_and_reports_changed(client):
    pid = client.post("/api/web-pins", json=_body()).json()["id"]
    r = client.post(f"/api/web-pins/{pid}/snapshot", json={"image_b64": _b64(PNG), "text": "Revenue 4.2M", "match": "selector"})
    assert r.json()["changed"] is False
    r = client.post(f"/api/web-pins/{pid}/snapshot", json={"text": "Revenue 5.0M", "match": "rect"})
    assert r.json()["changed"] is True and r.json()["match"] == "rect"
    assert client.get(f"/api/web-pins/{pid}").json()["text"] == "Revenue 5.0M"


def test_snapshot_unknown_pin_404(client):
    assert client.post(f"/api/web-pins/{uuid.uuid4()}/snapshot", json={"text": "x"}).status_code == 404


def test_snapshot_failure_status_writes_nothing(client):
    pid = client.post("/api/web-pins", json=_body()).json()["id"]
    r = client.post(f"/api/web-pins/{pid}/snapshot", json={"status": "pane_not_visible", "text": "SHOULD NOT WRITE"})
    assert r.json() == {"ok": False, "status": "pane_not_visible"}
    assert client.get(f"/api/web-pins/{pid}").json()["text"] == "Revenue 4.2M"


def test_snapshot_with_request_id_first_post_wins(client):
    pid = client.post("/api/web-pins", json=_body()).json()["id"]

    async def scenario():
        rid, fut = pending.create(pid, "tab-a")
        r1 = await asyncio.to_thread(client.post, f"/api/web-pins/{pid}/snapshot", json={"request_id": rid, "text": "new", "match": "selector"})
        res = await asyncio.wait_for(fut, 2)
        r2 = await asyncio.to_thread(client.post, f"/api/web-pins/{pid}/snapshot", json={"request_id": rid, "text": "again"})
        return r1, res, r2

    r1, res, r2 = asyncio.run(scenario())
    assert r1.status_code == 200 and res["status"] == "ok" and res["changed"] is True
    assert r2.status_code == 409
    assert client.get(f"/api/web-pins/{pid}").json()["text"] == "new"


def test_snapshot_with_failure_request_resolves_pending(client):
    pid = client.post("/api/web-pins", json=_body()).json()["id"]

    async def scenario():
        rid, fut = pending.create(pid, "tab-a")
        await asyncio.to_thread(client.post, f"/api/web-pins/{pid}/snapshot", json={"request_id": rid, "status": "page_mismatch"})
        return await asyncio.wait_for(fut, 2)

    assert asyncio.run(scenario())["status"] == "page_mismatch"


def test_snapshot_empty_target_failure_resolves_pending(client):
    pid = client.post("/api/web-pins", json=_body()).json()["id"]

    async def scenario():
        rid, fut = pending.create(pid, "tab-a")
        r = await asyncio.to_thread(client.post, f"/api/web-pins/{pid}/snapshot", json={"request_id": rid, "status": "empty_target"})
        return r, await asyncio.wait_for(fut, 2)

    r, res = asyncio.run(scenario())
    assert r.status_code == 200 and res["status"] == "empty_target"


def test_snapshot_unknown_failure_status_is_400(client):
    pid = client.post("/api/web-pins", json=_body()).json()["id"]
    assert client.post(f"/api/web-pins/{pid}/snapshot", json={"status": "made_up"}).status_code == 400


def test_snapshot_unknown_request_id_is_409(client):
    pid = client.post("/api/web-pins", json=_body()).json()["id"]
    r = client.post(f"/api/web-pins/{pid}/snapshot", json={"request_id": "nope", "text": "x"})
    assert r.status_code == 409


def test_pending_resolve_conflicts():
    async def scenario():
        rid, fut = pending.create("p1", "tab-a")
        assert pending.resolve(rid, "other", {"status": "ok"}) == "conflict"
        assert pending.resolve(rid, "p1", {"status": "ok"}) == "ok"
        assert pending.resolve(rid, "p1", {"status": "ok"}) == "conflict"
        assert (await asyncio.wait_for(fut, 1))["status"] == "ok"
        rid2, _ = pending.create("p2", "tab-a")
        pending.discard(rid2)
        assert pending.resolve(rid2, "p2", {}) == "conflict"

    asyncio.run(scenario())


@pytest.mark.parametrize("field,value", [
    ("title", "t" * 501),
    ("url", "https://x.test/" + "a" * 4096),
    ("aria_label", "a" * 501),
    ("locator", {"selector": "#" + "a" * 9000}),
])
def test_create_rejects_oversize_metadata_fields(client, field, value):
    assert client.post("/api/web-pins", json=_body(**{field: value})).status_code == 422
    assert state.get_pins("tab-a") == []


def test_oversize_image_is_refused_before_decoding(client, monkeypatch):
    import routes.web_pins as wp

    def boom(*a, **k):
        raise AssertionError("decoded an oversize payload")

    monkeypatch.setattr(wp.base64, "b64decode", boom)
    r = client.post("/api/web-pins", json=_body(image_b64="A" * (wp._MAX_B64 + 4)))
    assert r.status_code == 413


def test_oversize_snapshot_image_is_413_and_leaves_the_request_claimable(client):
    pid = client.post("/api/web-pins", json=_body()).json()["id"]
    big = _b64(PNG + b"0" * (5 * 1024 * 1024))

    async def scenario():
        rid, fut = pending.create(pid, "tab-a")
        r1 = await asyncio.to_thread(client.post, f"/api/web-pins/{pid}/snapshot", json={"request_id": rid, "image_b64": big, "text": "x"})
        r2 = await asyncio.to_thread(client.post, f"/api/web-pins/{pid}/snapshot", json={"request_id": rid, "text": "ok"})
        return r1, r2, await asyncio.wait_for(fut, 2)

    r1, r2, res = asyncio.run(scenario())
    assert r1.status_code == 413
    assert r2.status_code == 200 and res["status"] == "ok"


def test_snapshot_write_failure_releases_the_waiting_agent(client, monkeypatch):
    pid = client.post("/api/web-pins", json=_body()).json()["id"]

    def broken(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(store, "write_snapshot", broken)
    quiet = TestClient(app, raise_server_exceptions=False, headers={"X-CSRF-Token": get_csrf_token("testserver")})

    async def scenario():
        rid, fut = pending.create(pid, "tab-a")
        r = await asyncio.to_thread(quiet.post, f"/api/web-pins/{pid}/snapshot", json={"request_id": rid, "text": "new"})
        return r, await asyncio.wait_for(fut, 2)

    r, res = asyncio.run(scenario())
    assert r.status_code == 500
    assert res == {"status": "pane_unavailable"}


def test_label_drops_the_site_suffix_but_keeps_real_title_parts(client):
    j = client.post("/api/web-pins", json=_body(aria_label="", title="Finance - Power BI")).json()
    assert j["label"] == "Finance"
    j = client.post("/api/web-pins", json=_body(aria_label="", title="Q3 - Revenue")).json()
    assert j["label"] == "Q3 - Revenue"


def test_label_never_a_url_hostname_app_id_or_untitled(client):
    for bad in ("https://app.powerbi.com/report/1", "app.powerbi.com", "pbi", "Untitled", "Untitled page"):
        j = client.post("/api/web-pins", json=_body(aria_label=bad, title="")).json()
        assert j["label"] == "Power BI", bad
