"""Download an image shown inline in chat."""

import pathlib

import httpx
import pytest
from app import app
from fastapi.testclient import TestClient
from routes import files as files_module
from routes import inline_images
from security import get_csrf_token

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
REMOTE = "https://images.example/mcp/txt2img/images/a42668ca.png?token=abc.def&x=1"


def _connections(*conns):
    return {"mcp_connections": list(conns)}


IMAGE_MCP = {"id": "mcp-img", "url": "https://images.example/mcp", "transport": "http"}


@pytest.fixture(autouse=True)
def connected_image_mcp(monkeypatch):
    monkeypatch.setattr(inline_images, "load_config", lambda: _connections(IMAGE_MCP))


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
        "https://images.example.evil.example/x.png",
        "https://images.example@evil.example/x.png",
        "https://user:aigator-fake-api-key@images.example/x.png",  # pragma: allowlist secret
        "http://images.example/x.png",
        "https://images.example:8443/x.png",
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


def test_hosts_come_from_enabled_https_http_mcp_connections(monkeypatch):
    conns = _connections(
        IMAGE_MCP,
        {"id": "off", "url": "https://off.example/mcp", "enabled": False},
        {"id": "plain", "url": "http://plain.example/mcp"},
        {"id": "local", "transport": "stdio", "command": "npx", "args": ["x"]},
        {"id": "blank", "url": ""},
    )
    monkeypatch.setattr(inline_images, "load_config", lambda: conns)
    assert inline_images.inline_image_hosts() == {"images.example"}


def test_no_connected_mcp_means_no_remote_images(client, remote, monkeypatch):
    monkeypatch.setattr(inline_images, "load_config", lambda: _connections())
    assert client.get("/api/inline-image", params={"url": REMOTE}).status_code == 400
    assert remote == []


def test_a_disabled_connection_does_not_allow_its_host(client, remote, monkeypatch):
    off = {**IMAGE_MCP, "enabled": False}
    monkeypatch.setattr(inline_images, "load_config", lambda: _connections(off))
    assert client.get("/api/inline-image", params={"url": REMOTE}).status_code == 400
    assert remote == []


def test_no_company_host_is_built_in():
    root = pathlib.Path(__file__).parent.parent
    for rel in ("routes/inline_images.py", "static/app.js"):
        text = (root / rel).read_text(encoding="utf-8")
        assert "mcp-platform" not in text, rel
