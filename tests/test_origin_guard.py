import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from fastapi.testclient import TestClient

from app import app
from security import origin_allowed

HOST = "127.0.0.1:8000"


@pytest.mark.parametrize("origin", ["http://127.0.0.1:8000", "http://127.0.0.1:8000/"])
def test_same_origin_post_is_allowed(origin):
    assert origin_allowed("POST", HOST, origin, None)


def test_referer_is_used_when_origin_is_missing():
    assert origin_allowed("POST", HOST, None, "http://127.0.0.1:8000/some/page")
    assert not origin_allowed("POST", HOST, None, "https://evil.example/page")


@pytest.mark.parametrize("origin", [
    "https://evil.example", "http://evil.example", "null", "http://127.0.0.1:9999", "http://localhost:8000",
])
def test_foreign_origin_post_is_refused(origin):
    assert not origin_allowed("POST", HOST, origin, None)


def test_dns_rebound_host_is_refused():
    assert not origin_allowed("POST", "evil.example:8000", "http://evil.example:8000", None)


def test_non_browser_requests_and_reads_pass_through():
    assert origin_allowed("POST", HOST, None, None)
    assert origin_allowed("GET", HOST, "https://evil.example", None)


def test_middleware_blocks_cross_origin_state_changes():
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    r = client.post("/api/marketplace/disable/x", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["detail"] == "Cross-origin request blocked"
    r = client.post("/api/marketplace/disable/x", headers={"Origin": "http://127.0.0.1:8000"})
    assert r.json()["detail"] != "Cross-origin request blocked"  # reaches the CSRF check instead
