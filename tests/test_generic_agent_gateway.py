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
    "api_key": FAKE,  # pragma: allowlist secret
    "api_key_header": "Ocp-Apim-Subscription-Key",  # pragma: allowlist secret
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
    monkeypatch.setattr(generic_agent, "build_command", lambda agent, repo="", extra=(): [agent])
    monkeypatch.setattr(
        generic_agent,
        "gateway_binding",
        lambda agent: ((), {"ANTHROPIC_API_KEY": FAKE}) if agent == "claude" else None,
    )
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


def test_pi_gets_an_extension_registering_both_gateway_providers(tmp_path, monkeypatch):
    monkeypatch.setattr(generic_agent, "_PI_EXTENSION_DIR", tmp_path)
    args, env = generic_agent._pi_binding_from_profile(PROFILE, MODELS)
    assert args == ("-e", str(tmp_path / "gateway.mjs"), "--provider", "gator-anthropic", "--model", "Claude-Sonnet-5")
    assert env == {"GATOR_GATEWAY_KEY": FAKE}
    source = (tmp_path / "gateway.mjs").read_text(encoding="utf-8")
    assert source.count("pi.registerProvider(") == 2
    assert '"baseUrl": "https://gw.example.com/Anthropic"' in source
    assert '"baseUrl": "https://gw.example.com/Unified/v1"' in source
    assert '"Ocp-Apim-Subscription-Key": "GATOR_GATEWAY_KEY"' in source
    assert FAKE not in source


def test_pi_defaults_to_an_available_provider_when_the_active_model_has_none(tmp_path, monkeypatch):
    monkeypatch.setattr(generic_agent, "_PI_EXTENSION_DIR", tmp_path)
    profile = {**PROFILE, "anthropic_url": "", "active_model": "Claude-Sonnet-5"}
    args, _ = generic_agent._pi_binding_from_profile(profile, MODELS)
    assert args[-4:] == ("--provider", "gator-gateway", "--model", "gpt-5.5")


def test_pi_is_unbound_without_a_key(tmp_path, monkeypatch):
    monkeypatch.setattr(generic_agent, "_PI_EXTENSION_DIR", tmp_path)
    assert generic_agent._pi_binding_from_profile({**PROFILE, "api_key": ""}, MODELS) is None


def test_argv_bindings_do_not_apply_to_agents_that_only_exist_in_wsl(monkeypatch):
    binding = (("-e", "C:/x.mjs"), {"K": "v"})
    monkeypatch.setattr(generic_agent, "gateway_binding", lambda agent: binding)
    monkeypatch.setattr(generic_agent, "find_agent_binary", lambda agent: None)
    assert generic_agent.effective_binding("pi") is None
    monkeypatch.setattr(generic_agent, "find_agent_binary", lambda agent: "C:/bin/pi.cmd")
    assert generic_agent.effective_binding("pi") == binding
    assert generic_agent.build_command("pi", "", binding[0]) == ["C:/bin/pi.cmd", "-e", "C:/x.mjs"]


def test_claude_is_launched_with_a_session_id_that_a_handoff_can_look_up():
    cmd = generic_agent.pin_session("claude", ["claude.exe"], "pty-1")
    assert cmd[:2] == ["claude.exe", "--session-id"]
    assert generic_agent.pinned_session_id("pty-1") == cmd[2]
    generic_agent.unpin_session("pty-1")
    assert generic_agent.pinned_session_id("pty-1") is None


def test_only_native_claude_launches_are_pinned():
    assert generic_agent.pin_session("codex", ["codex.exe"], "pty-2") == ["codex.exe"]
    assert generic_agent.pin_session("claude", ["wsl.exe", "claude"], "pty-3") == ["wsl.exe", "claude"]
    assert generic_agent.pinned_session_id("pty-2") is None
    assert generic_agent.pinned_session_id("pty-3") is None


def test_a_wsl_claude_launch_gets_a_session_id_for_the_history_link_but_not_for_handoff():
    wsl = ["wsl.exe", "-d", "Ubuntu", "--", "bash", "-lc", "exec claude"]
    cmd = generic_agent.pin_session("claude", wsl, "pty-4")
    sid = generic_agent.linked_session_id("pty-4")
    assert cmd == [*wsl[:-1], f"exec claude --session-id {sid}"]
    assert generic_agent.pinned_session_id("pty-4") is None
    assert generic_agent.ptys_for_session("claude", sid) == ["pty-4"]
    generic_agent.unpin_session("pty-4")


def test_a_native_claude_launch_is_found_by_its_pinned_session_id():
    cmd = generic_agent.pin_session("claude", ["claude.exe"], "pty-5")
    assert generic_agent.ptys_for_session("claude", cmd[2]) == ["pty-5"]
    assert generic_agent.ptys_for_session("codex", cmd[2]) == []
    generic_agent.unpin_session("pty-5")
