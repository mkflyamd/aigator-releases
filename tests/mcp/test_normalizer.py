# tests/mcp/test_normalizer.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "web"))

from mcp.normalizer import NormalizeResult, _try_json
from tests.mcp.fixtures.mcp_snippets import (
    PLAYWRIGHT_MCPSERVERS_COMMAND, PLAYWRIGHT_MCPSERVERS_COMMAND_WITH_ENV,
    FILESYSTEM_MCPSERVERS_COMMAND, CONDUCTOR_MCPSERVERS_URL, GITHUB_MCPSERVERS_URL,
    CONDUCTOR_CLAUDE_CODE, CONDUCTOR_VSCODE, CONDUCTOR_REGISTRY,
    PLAYWRIGHT_BARE_OBJECT, CONDUCTOR_BARE_URL_OBJECT, MULTI_SERVER_COMMAND,
    MISSING_COMMAND, MCPSERVERS_NULL, PARTIAL_JSON, GARBAGE,
    EMPTY, WHITESPACE,
)


def _one(text: str) -> NormalizeResult:
    results = _try_json(text)
    assert len(results) == 1, f"expected 1 result, got {len(results)}: {results}"
    return results[0]


# Format 1: mcpServers + command
def test_json_mcpservers_command_basic():
    r = _one(PLAYWRIGHT_MCPSERVERS_COMMAND)
    assert r.ok and r.transport == "stdio"
    assert r.name == "playwright"
    assert r.command == "npx"
    assert r.args == ["@playwright/mcp@latest"]

def test_json_mcpservers_command_with_env():
    r = _one(PLAYWRIGHT_MCPSERVERS_COMMAND_WITH_ENV)
    assert r.ok and r.transport == "stdio"
    assert r.env == {"PWTEST_SCREENSHOT": "on"}

def test_json_mcpservers_command_prerequisite_warning():
    r = _one(PLAYWRIGHT_MCPSERVERS_COMMAND)
    assert "npx" in r.prerequisite_warning

# Format 2: mcpServers + url
def test_json_mcpservers_url():
    r = _one(CONDUCTOR_MCPSERVERS_URL)
    assert r.ok and r.transport == "http"
    assert r.name == "conductor-mcp"
    assert "mcp-platform.amd.com" in r.url

def test_json_mcpservers_url_github():
    r = _one(GITHUB_MCPSERVERS_URL)
    assert r.ok and r.transport == "http"
    assert "githubcopilot" in r.url

# Format 3: mcpServers + type:"http"  (Claude Code style)
def test_json_claude_code_type_http():
    r = _one(CONDUCTOR_CLAUDE_CODE)
    assert r.ok and r.transport == "http"
    assert "mcp-platform.amd.com" in r.url

# Format 4: servers key (VS Code)
def test_json_vscode_servers_key():
    r = _one(CONDUCTOR_VSCODE)
    assert r.ok and r.transport == "http"
    assert r.source == "json_servers"
    assert "mcp-platform.amd.com" in r.url

# Format 5: remotes array (registry schema)
def test_json_registry_schema():
    r = _one(CONDUCTOR_REGISTRY)
    assert r.ok and r.transport == "http"
    assert r.source == "registry_schema"
    assert "mcp-platform.amd.com" in r.url
    assert r.name == "Conductor MCP"

# Format 6: bare server object
def test_json_bare_server_object_stdio():
    r = _one(PLAYWRIGHT_BARE_OBJECT)
    assert r.ok and r.transport == "stdio"
    assert r.command == "npx"

# Format 7: bare URL object
def test_json_bare_url_object():
    r = _one(CONDUCTOR_BARE_URL_OBJECT)
    assert r.ok and r.transport == "http"
    assert "mcp-platform.amd.com" in r.url

# Multi-server → list of results
def test_json_multi_server_returns_multiple():
    results = _try_json(MULTI_SERVER_COMMAND)
    assert len(results) == 2
    names = {r.name for r in results}
    assert "playwright" in names and "filesystem" in names

# Failure cases
def test_json_no_match_garbage():
    assert _try_json(GARBAGE) == []

def test_json_no_match_partial():
    assert _try_json(PARTIAL_JSON) == []

def test_json_missing_command_returns_empty():
    assert _try_json(MISSING_COMMAND) == []

def test_json_mcpservers_null_returns_empty():
    assert _try_json(MCPSERVERS_NULL) == []

def test_json_empty_string_command_returns_empty():
    from tests.mcp.fixtures.mcp_snippets import EMPTY_STRING_COMMAND
    assert _try_json(EMPTY_STRING_COMMAND) == []


# ── Layer 1: URL detection (non-GitHub) ───────────────────────────────────────
from mcp.normalizer import _looks_like_url, _is_github_repo_url, _try_toml, _try_bare_command
from tests.mcp.fixtures.mcp_snippets import (
    CONDUCTOR_URL, GITHUB_API_URL,
    CONDUCTOR_TOML, MULTI_TOML,
    PLAYWRIGHT_COMMAND, FETCH_COMMAND, PYTHON_COMMAND,
)


def test_looks_like_url_http():
    assert _looks_like_url("http://localhost:8765/mcp")

def test_looks_like_url_https():
    assert _looks_like_url("https://mcp-platform.amd.com/mcp/conductor_mcp")

def test_looks_like_url_false_for_json():
    assert not _looks_like_url('{"url":"https://example.com"}')

def test_is_github_repo_url_true():
    assert _is_github_repo_url("https://github.com/microsoft/playwright-mcp")

def test_is_github_repo_url_false_for_other():
    assert not _is_github_repo_url("https://mcp-platform.amd.com/mcp/conductor_mcp")

# ── Layer 3: TOML ─────────────────────────────────────────────────────────────

def test_toml_single_server():
    results = _try_toml(CONDUCTOR_TOML)
    assert len(results) == 1
    r = results[0]
    assert r.ok and r.transport == "http"
    assert r.name == "conductor-mcp"
    assert "mcp-platform.amd.com" in r.url
    assert r.source == "toml"

def test_toml_multi_server():
    results = _try_toml(MULTI_TOML)
    assert len(results) == 2

def test_toml_no_match_for_json():
    assert _try_toml(PLAYWRIGHT_MCPSERVERS_COMMAND) == []

# ── Layer 4: Bare command ─────────────────────────────────────────────────────

def test_bare_command_npx():
    r = _try_bare_command(PLAYWRIGHT_COMMAND)
    assert r is not None
    assert r.ok and r.transport == "stdio"
    assert r.command == "npx"
    assert "@playwright/mcp@latest" in r.args
    assert "npx" in r.prerequisite_warning

def test_bare_command_uvx():
    r = _try_bare_command(FETCH_COMMAND)
    assert r is not None and r.command == "uvx"

def test_bare_command_python():
    r = _try_bare_command(PYTHON_COMMAND)
    assert r is not None and r.command == "python"

def test_bare_command_rejects_json():
    assert _try_bare_command('{"command":"npx"}') is None

def test_bare_command_rejects_unknown_launcher():
    assert _try_bare_command("curl https://example.com") is None


# ── Full pipeline ─────────────────────────────────────────────────────────────
from mcp.normalizer import normalize


def test_pipeline_bare_url():
    r = normalize(CONDUCTOR_URL)
    assert r.ok and r.transport == "http"
    assert "mcp-platform.amd.com" in r.url
    assert r.source == "url"

def test_pipeline_mcpservers_command():
    r = normalize(PLAYWRIGHT_MCPSERVERS_COMMAND)
    assert r.ok and r.transport == "stdio" and r.name == "playwright"

def test_pipeline_toml():
    r = normalize(CONDUCTOR_TOML)
    assert r.ok and r.transport == "http" and r.source == "toml"

def test_pipeline_bare_command():
    r = normalize(PLAYWRIGHT_COMMAND)
    assert r.ok and r.transport == "stdio" and r.command == "npx"

def test_pipeline_multi_server_confidence_medium():
    r = normalize(MULTI_SERVER_COMMAND)
    assert r.ok and r.confidence == "medium"
    assert len(r.all_results) == 2

def test_pipeline_empty_returns_failure():
    r = normalize(EMPTY)
    assert not r.ok

def test_pipeline_whitespace_returns_failure():
    r = normalize(WHITESPACE)
    assert not r.ok

def test_pipeline_llm_fallback_called_on_garbage():
    calls = []
    def mock_llm(prompt: str) -> str:
        calls.append(prompt)
        return '{"transport":"http","name":"test-mcp","url":"https://test.example.com/mcp","command":"","args":[],"env":{}}'

    r = normalize(GARBAGE, llm=mock_llm)
    assert r.ok and r.transport == "http"
    assert r.confidence == "low"
    assert r.source == "llm"
    assert len(calls) == 1

def test_pipeline_llm_not_called_when_json_matches():
    calls = []
    def mock_llm(prompt: str) -> str:
        calls.append(prompt)
        return '{}'

    r = normalize(PLAYWRIGHT_MCPSERVERS_COMMAND, llm=mock_llm)
    assert r.ok
    assert len(calls) == 0  # LLM not reached

def test_pipeline_llm_failure_returns_failure():
    def bad_llm(prompt: str) -> str:
        raise RuntimeError("network error")

    r = normalize(GARBAGE, llm=bad_llm)
    assert not r.ok

def test_pipeline_llm_shell_metachar_rejected():
    def evil_llm(prompt: str) -> str:
        return '{"transport":"stdio","name":"evil","url":"","command":"npx; rm -rf /","args":[],"env":{}}'

    r = normalize(GARBAGE, llm=evil_llm)
    assert not r.ok

def test_pipeline_github_url_calls_fetcher():
    calls = []
    def mock_fetcher(url: str) -> NormalizeResult:
        calls.append(url)
        return NormalizeResult(ok=True, transport="stdio", name="playwright",
                               command="npx", args=["@playwright/mcp@latest"],
                               source="github_readme", confidence="high")

    r = normalize("https://github.com/microsoft/playwright-mcp", fetcher=mock_fetcher)
    assert r.ok and r.source == "github_readme"
    assert len(calls) == 1


# ── GitHub fetcher ────────────────────────────────────────────────────────────

def test_github_fetcher_extracts_config_from_readme(monkeypatch):
    import mcp.github_fetcher as gf

    readme_with_json = """
# Playwright MCP
Install:
```json
{"mcpServers":{"playwright":{"command":"npx","args":["@playwright/mcp@latest"]}}}
```
"""
    meta_json = '{"default_branch":"main"}'

    responses = {
        "https://api.github.com/repos/microsoft/playwright-mcp": meta_json,
        "https://raw.githubusercontent.com/microsoft/playwright-mcp/main/README.md": readme_with_json,
    }

    def fake_get(url, timeout=10):
        class R:
            text = responses[url]
            def json(self): return __import__("json").loads(self.text)
        return R()

    monkeypatch.setattr(gf.httpx, "get", fake_get)

    r = gf.github_fetcher("https://github.com/microsoft/playwright-mcp")
    assert r is not None
    assert r.ok and r.transport == "stdio"
    assert r.name == "playwright"
    assert r.source == "github_readme"


def test_github_fetcher_multiple_configs_returns_chooser(monkeypatch):
    import mcp.github_fetcher as gf

    readme = """
```json
{"mcpServers":{"playwright":{"command":"npx","args":["@playwright/mcp@latest"]}}}
```
```json
{"mcpServers":{"filesystem":{"command":"npx","args":["@modelcontextprotocol/server-filesystem","/tmp"]}}}
```
"""
    def fake_get(url, timeout=10):
        class R:
            text = '{"default_branch":"main"}' if "api.github.com" in url else readme
            def json(self): return __import__("json").loads(self.text)
        return R()

    monkeypatch.setattr(gf.httpx, "get", fake_get)

    r = gf.github_fetcher("https://github.com/microsoft/playwright-mcp")
    assert r is not None and r.ok
    assert r.confidence == "medium"
    assert len(r.all_results) == 2


def test_github_fetcher_network_error_returns_none(monkeypatch):
    import mcp.github_fetcher as gf

    def fail_get(url, timeout=10):
        raise ConnectionError("network down")

    monkeypatch.setattr(gf.httpx, "get", fail_get)
    r = gf.github_fetcher("https://github.com/microsoft/playwright-mcp")
    assert r is None
