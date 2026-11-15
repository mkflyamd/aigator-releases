"""Claude Code is bound to the gateway at launch; Codex's own config is checked."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import generic_agent
from routes import generic_agent_routes
from security import verify_csrf

FAKE = "aigator-fake-api-key"
MODELS = ["Claude-Opus-5", "Claude-Sonnet-5", "Claude-Haiku-4-5", "gpt-5.5"]
PROFILE = {
    "api_key": FAKE,
    "api_key_header": "Ocp-Apim-Subscription-Key",
    "anthropic_url": "https://gw.example.com/Anthropic/v1/",
    "base_url": "https://gw.example.com/Unified",
    "user_id": "someone",
    "active_model": "Claude-Sonnet-5",
}


def test_claude_env_points_at_the_anthropic_endpoint_with_gateway_headers():
    env = generic_agent._claude_env_from_profile(PROFILE, MODELS)
    assert env["ANTHROPIC_BASE_URL"] == "https://gw.example.com/Anthropic"
    assert env["ANTHROPIC_API_KEY"] == FAKE
    assert env["ANTHROPIC_CUSTOM_HEADERS"].splitlines() == [
        f"Ocp-Apim-Subscription-Key: {FAKE}",
        "user: someone",
    ]
    assert env["ANTHROPIC_MODEL"] == "Claude-Sonnet-5"
    assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "Claude-Opus-5"
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "Claude-Haiku-4-5"


@pytest.mark.parametrize("change", [{"api_key": ""}, {"anthropic_url": ""}])
def test_claude_is_left_unbound_without_a_key_or_anthropic_endpoint(change):
    assert generic_agent._claude_env_from_profile({**PROFILE, **change}, MODELS) is None


def test_wsl_launch_forwards_the_variables(monkeypatch):
    monkeypatch.setenv("WSLENV", "KEEP/p")
    env = generic_agent.with_wsl_env(["wsl.exe", "-d", "Ubuntu"], {"A": "1", "B": "2"})
    assert env["WSLENV"] == "KEEP/p:A:B"
    assert generic_agent.with_wsl_env(["claude.exe"], {"A": "1"}) == {"A": "1"}
    assert generic_agent.with_wsl_env(["wsl.exe"], None) is None


def _codex_config(monkeypatch, text):
    monkeypatch.setattr(generic_agent, "_codex_config_text", lambda: text)


def test_codex_counts_as_routed_when_its_provider_is_on_the_gateway_host(monkeypatch):
    _codex_config(
        monkeypatch,
        'model_provider = "gw"\n[model_providers.gw]\nbase_url = "https://gw.example.com/openai/x"\n',
    )
    assert generic_agent.codex_config_routes_to_gateway(PROFILE) is True


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not toml = [",
        'model_provider = "other"\n[model_providers.other]\nbase_url = "https://api.openai.com/v1"\n',
        'model_provider = "missing"\n',
    ],
)
def test_codex_is_unmanaged_otherwise(monkeypatch, text):
    _codex_config(monkeypatch, text)
    assert generic_agent.codex_config_routes_to_gateway(PROFILE) is False


def _app():
    app = FastAPI()
    app.include_router(generic_agent_routes.router)
    app.dependency_overrides[verify_csrf] = lambda: None
    return TestClient(app)


@pytest.fixture
def spawned(monkeypatch):
    calls = []
    monkeypatch.setattr("routes.terminal.create_pty_session", lambda sid, **kw: calls.append(kw))
    monkeypatch.setattr(generic_agent, "wsl_agents", lambda: (None, {}))
    monkeypatch.setattr(generic_agent, "build_command", lambda agent, repo="": [agent])
    monkeypatch.setattr(generic_agent, "gateway_binding", lambda agent: {"ANTHROPIC_API_KEY": FAKE} if agent == "claude" else None)
    return calls


def test_launch_injects_the_gateway_env_only_for_bound_agents(spawned):
    body = {"project_id": "p", "repo_path": "/r", "force_new": True}
    assert _app().post("/api/generic-agent/terminal", json={**body, "agent": "claude"}).status_code == 200
    assert _app().post("/api/generic-agent/terminal", json={**body, "agent": "pi"}).status_code == 200
    assert spawned[0]["env"] == {"ANTHROPIC_API_KEY": FAKE}
    assert spawned[1]["env"] is None


def test_installed_route_reports_which_installed_agents_are_gateway_routed(monkeypatch):
    monkeypatch.setattr(generic_agent, "wsl_agents", lambda: (None, {}))
    monkeypatch.setattr(generic_agent, "is_installed", lambda a: a in {"claude", "pi", "terminal"})
    monkeypatch.setattr(generic_agent, "is_gateway_routed", lambda a: a == "claude")
    body = _app().get("/api/generic-agent/installed").json()
    assert body["gateway_routed"] == {"claude": True, "pi": False}
