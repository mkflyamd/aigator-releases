# tests/mcp/test_analyze_route.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "web"))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch

from routes.mcp_routes import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def _analyze(raw_input: str, fetcher=None, llm=None):
    """Helper: POST to analyze endpoint with optional mock overrides."""
    with patch("routes.mcp_routes._get_fetcher", return_value=fetcher), \
         patch("routes.mcp_routes._get_llm", return_value=llm):
        return client.post("/api/config/mcp/analyze", json={"raw_input": raw_input})


def test_analyze_mcpservers_command():
    r = _analyze('{"mcpServers":{"playwright":{"command":"npx","args":["@playwright/mcp@latest"]}}}')
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["transport"] == "stdio"
    assert data["name"] == "playwright"


def test_analyze_bare_url():
    r = _analyze("https://mcp-platform.amd.com/mcp/conductor_mcp")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["transport"] == "http"


def test_analyze_empty_input():
    r = _analyze("")
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_analyze_garbage_no_llm():
    r = _analyze("not json not url not command", llm=None)
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_analyze_garbage_with_llm_fallback():
    def mock_llm(prompt: str) -> str:
        return '{"transport":"http","name":"my-mcp","url":"https://my.server.com/mcp","command":"","args":[],"env":{}}'

    r = _analyze("some custom format text", llm=mock_llm)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["confidence"] == "low"
    assert data["source"] == "llm"


def test_analyze_github_url_with_mock_fetcher():
    from mcp.normalizer import NormalizeResult

    fake_result = NormalizeResult(
        ok=True, transport="stdio", name="playwright",
        command="npx", args=["@playwright/mcp@latest"],
        source="github_readme", confidence="high",
    )

    r = _analyze("https://github.com/microsoft/playwright-mcp", fetcher=lambda url: fake_result)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["source"] == "github_readme"
