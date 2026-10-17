"""Download an image shown inline in chat."""

import pathlib
import re

import httpx
import pytest
from app import app
from fastapi.testclient import TestClient
from routes import files as files_module
from routes import inline_images
from security import get_csrf_token

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
REMOTE = (
    "https://mcp-platform.amd.com/mcp/txt2img/images/a42668ca.png?token=abc.def&x=1"
)


@pytest.fixture
def client():
    return TestClient(app, headers={"X-CSRF-Token": get_csrf_token("testserver")})


@pytest.fixture
def outputs(tmp_path, monkeypatch):
    root = tmp_path / "outputs"
    (root / "run1").mkdir(parents=True)
    (root / "run1" / "chart.png").write_bytes(PNG)
    (root / "run1" / "notes.txt").write_text("secret")
    monkeypatch.setattr(files_module, "OUTPUTS_DIR", root)
    return root


@pytest.fixture
def remote(monkeypatch, outputs):
    calls = []

    async def fake(url):
        calls.append(url)
        return PNG, "image/png"

    monkeypatch.setattr(inline_images, "_fetch_remote", fake)
    return calls


def test_download_local_output_is_an_attachment(client, outputs):
    r = client.get("/api/inline-image", params={"url": "/api/files/run1/chart.png"})
    assert r.status_code == 200
    assert r.content == PNG
    assert r.headers["content-type"] == "image/png"
    assert 'attachment; filename="chart.png"' in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_download_allowlisted_remote_image(client, remote):
    r = client.get("/api/inline-image", params={"url": REMOTE})
    assert r.status_code == 200
    assert r.content == PNG
    assert remote == [REMOTE]
    assert 'filename="a42668ca.png"' in r.headers["content-disposition"]


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/p.png",
        "https://mcp-platform.amd.com.evil.example/x.png",
        "https://mcp-platform.amd.com@evil.example/x.png",
        "https://user:pw@mcp-platform.amd.com/x.png",
        "http://mcp-platform.amd.com/x.png",
        "https://mcp-platform.amd.com:8443/x.png",
        "file:///C:/Windows/win.ini",
        "/api/other/endpoint",
        "/api/files/run1/../../secret.png",
        "/api/files/run1",
        "",
    ],
)
def test_rejects_urls_outside_the_allowlist(client, outputs, remote, url):
    r = client.get("/api/inline-image", params={"url": url})
    assert r.status_code == 400, r.text
    assert remote == []


def test_remote_image_is_fetched_once_then_served_from_cache(
    client, remote, outputs, picker, tmp_path
):
    for _ in range(3):
        assert client.get("/api/inline-image", params={"url": REMOTE}).content == PNG
    picker[1]["path"] = str(tmp_path / "out.png")
    assert (
        client.post("/api/inline-image/save", json={"url": REMOTE}).json()["ok"] is True
    )
    assert len(remote) == 1
    assert (tmp_path / "out.png").read_bytes() == PNG
    assert any(outputs.glob("inline-*/cached.png"))


def test_failed_fetch_is_not_cached(client, remote, outputs, monkeypatch):
    async def boom(url):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(inline_images, "_fetch_remote", boom)
    assert client.get("/api/inline-image", params={"url": REMOTE}).status_code == 502
    assert not list(outputs.glob("inline-*"))


def test_rejects_non_image_local_file(client, outputs):
    r = client.get("/api/inline-image", params={"url": "/api/files/run1/notes.txt"})
    assert r.status_code == 400


def test_missing_local_file_is_404(client, outputs):
    r = client.get("/api/inline-image", params={"url": "/api/files/run1/gone.png"})
    assert r.status_code == 404


def test_upstream_failure_is_502(client, monkeypatch):
    async def boom(url):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(inline_images, "_fetch_remote", boom)
    r = client.get("/api/inline-image", params={"url": REMOTE})
    assert r.status_code == 502


@pytest.fixture
def picker(monkeypatch):
    calls = []
    answer = {"path": ""}

    def fake(title, filetypes, save, default_name=""):
        calls.append({"save": save, "default_name": default_name})
        return answer["path"]

    monkeypatch.setattr(inline_images, "_open_file_dialog", fake)
    return calls, answer


def test_save_writes_to_the_path_the_user_picked(client, outputs, picker, tmp_path):
    calls, answer = picker
    answer["path"] = str(tmp_path / "chosen.png")
    r = client.post("/api/inline-image/save", json={"url": "/api/files/run1/chart.png"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert (tmp_path / "chosen.png").read_bytes() == PNG
    assert calls == [{"save": True, "default_name": "chart.png"}]


def test_save_adds_missing_extension(client, outputs, picker, tmp_path):
    picker[1]["path"] = str(tmp_path / "noext")
    client.post("/api/inline-image/save", json={"url": "/api/files/run1/chart.png"})
    assert (tmp_path / "noext.png").exists()


def test_save_cancelled_writes_nothing(client, outputs, picker, tmp_path):
    r = client.post("/api/inline-image/save", json={"url": "/api/files/run1/chart.png"})
    assert r.json() == {"ok": False, "cancelled": True}
    assert not list(tmp_path.glob("*.png"))


def test_save_rejects_bad_url_before_opening_the_dialog(client, remote, picker):
    r = client.post(
        "/api/inline-image/save", json={"url": "https://evil.example/p.png"}
    )
    assert r.status_code == 400
    assert picker[0] == []


def test_save_requires_csrf_token(outputs, picker):
    r = TestClient(app).post(
        "/api/inline-image/save", json={"url": "/api/files/run1/chart.png"}
    )
    assert r.status_code == 403
    assert picker[0] == []


def test_backend_allowlist_matches_frontend():
    app_js = (pathlib.Path(__file__).parent.parent / "static" / "app.js").read_text(
        encoding="utf-8"
    )
    m = re.search(r"const INLINE_IMAGE_HOSTS = \[([^\]]*)\]", app_js)
    assert m, "INLINE_IMAGE_HOSTS not found in app.js"
    frontend = set(re.findall(r"'([^']+)'", m.group(1)))
    assert frontend == set(inline_images.INLINE_IMAGE_HOSTS)
