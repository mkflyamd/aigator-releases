# tests/mcp/test_integration_universal.py
"""End-to-end: POST /api/config/mcp/analyze → normalize → confirm NormalizeResult fields.
Uses real normalizer (no mocks) for deterministic inputs, mocks for LLM/GitHub paths.
"""
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


def _post(raw_input, fetcher=None, llm=None):
    with patch("routes.mcp_routes._get_fetcher", return_value=fetcher), \
         patch("routes.mcp_routes._get_llm", return_value=llm):
        return client.post("/api/config/mcp/analyze", json={"raw_input": raw_input}).json()


def test_e2e_conductor_url():
    r = _post("https://mcp-platform.amd.com/mcp/conductor_mcp")
    assert r["ok"] and r["transport"] == "http" and r["source"] == "url"

def test_e2e_playwright_mcpservers():
    r = _post('{"mcpServers":{"playwright":{"command":"npx","args":["@playwright/mcp@latest"]}}}')
    assert r["ok"] and r["transport"] == "stdio" and r["name"] == "playwright"

def test_e2e_conductor_vscode():
    r = _post('{"servers":{"conductor":{"url":"https://mcp-platform.amd.com/mcp/conductor_mcp"}}}')
    assert r["ok"] and r["transport"] == "http" and r["source"] == "json_servers"

def test_e2e_conductor_registry_schema():
    r = _post('{"remotes":[{"type":"streamable-http","url":"https://mcp-platform.amd.com/mcp/conductor_mcp"}]}')
    assert r["ok"] and r["transport"] == "http" and r["source"] == "registry_schema"

def test_e2e_conductor_toml():
    r = _post('[mcp_servers.conductor]\nurl = "https://mcp-platform.amd.com/mcp/conductor_mcp"')
    assert r["ok"] and r["transport"] == "http" and r["source"] == "toml"

def test_e2e_playwright_bare_command():
    r = _post("npx @playwright/mcp@latest")
    assert r["ok"] and r["transport"] == "stdio" and r["command"] == "npx"

def test_e2e_multi_server_confidence_medium():
    r = _post('{"mcpServers":{"a":{"command":"npx","args":["pkg-a"]},"b":{"command":"uvx","args":["pkg-b"]}}}')
    assert r["ok"] and r["confidence"] == "medium" and len(r["all_results"]) == 2

def test_e2e_github_url_with_mock():
    from mcp.normalizer import NormalizeResult
    fake = NormalizeResult(ok=True, transport="stdio", name="playwright",
                           command="npx", args=["@playwright/mcp@latest"],
                           source="github_readme", confidence="high")
    r = _post("https://github.com/microsoft/playwright-mcp", fetcher=lambda u: fake)
    assert r["ok"] and r["source"] == "github_readme"

def test_e2e_garbage_no_llm():
    r = _post("totally unrecognized text with no structure at all")
    assert not r["ok"]

def test_e2e_llm_fallback():
    def mock_llm(prompt):
        return '{"transport":"http","name":"custom-mcp","url":"https://custom.example.com/mcp","command":"","args":[],"env":{}}'
    r = _post("some custom proprietary format", llm=mock_llm)
    assert r["ok"] and r["confidence"] == "low" and r["source"] == "llm"
