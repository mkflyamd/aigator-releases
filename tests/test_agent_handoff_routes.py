"""Handoff routes: prepare, launch with handoff_id, gateway env, CSRF."""

import logging
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import agent_handoff as ah
import generic_agent
from routes import generic_agent_routes
from security import verify_csrf

FAKE = "aigator-fake-api-key"
BODY = {"agent": "claude", "project_id": "demo", "repo_path": "/r", "pty_session_id": "s1"}


def _app(override_csrf=True):
    app = FastAPI()
    app.include_router(generic_agent_routes.router)
    if override_csrf:
        app.dependency_overrides[verify_csrf] = lambda: None
    return TestClient(app)


@pytest.fixture(autouse=True)
def no_wsl(monkeypatch):
    monkeypatch.setattr(generic_agent, "wsl_agents", lambda: (None, {}))


@pytest.fixture
def handoff_env(tmp_path, monkeypatch):
    monkeypatch.setattr(ah, "HANDOFF_DIR", tmp_path / "h")
    monkeypatch.setattr(ah, "_configured_api_keys", lambda: [FAKE])
    monkeypatch.setattr(ah, "_session_started_at", lambda sid: None)
    monkeypatch.setattr(ah, "find_transcript", lambda agent, cwd, home=None, **kw: None)
    monkeypatch.setattr(ah, "capture_pane", lambda sid, red=None: f"pane output {FAKE}")
    import routes.terminal as terminal
    monkeypatch.setattr(
        terminal, "session_owner",
        lambda sid: {"project_id": "demo", "agent": "claude"} if sid == "s1" else None,
    )


@pytest.fixture
def spawned(monkeypatch):
    calls = []

    def fake_create(session_id, **kwargs):
        calls.append({"session_id": session_id, **kwargs})

    import routes.terminal as terminal
    monkeypatch.setattr(terminal, "create_pty_session", fake_create)
    monkeypatch.setattr(generic_agent, "build_opencode_bare_command", lambda repo: ["opencode"])
    monkeypatch.setattr(
        generic_agent, "build_opencode_bare_env",
        lambda: {"OPENCODE_CONFIG_CONTENT": "{}", "GATOR_OPENCODE_KEY": FAKE},
    )
    monkeypatch.setattr(generic_agent, "build_command", lambda agent, repo="", extra=(): [agent])
    monkeypatch.setattr(generic_agent, "build_crush_env", lambda: {"CRUSH_GLOBAL_CONFIG": "/c", "GATOR_CRUSH_KEY": FAKE})
    return calls


def test_prepare_returns_preview_and_targets(handoff_env, monkeypatch):
    monkeypatch.setattr(generic_agent, "is_installed", lambda agent: agent in generic_agent.CORE_AGENT_LABELS)
    r = _app().post("/api/generic-agent/handoff/prepare", json=BODY)
    assert r.status_code == 200
    data = r.json()
    assert len(data["handoff_id"]) == 32 and data["source_kind"] == "capture"
    routed = {t["agent"]: t["gateway_routed"] for t in data["targets"]}
    assert routed == {"claude": False, "codex": False, "crush": True, "opencode-bare": True}


def test_prepare_nothing_to_hand_off_is_422(handoff_env, monkeypatch):
    monkeypatch.setattr(ah, "capture_pane", lambda sid, red=None: "")
    r = _app().post("/api/generic-agent/handoff/prepare", json=BODY)
    assert r.status_code == 422
    assert r.json()["detail"] == "Nothing to hand off from this session."


def test_prepare_requires_csrf(handoff_env):
    assert _app(override_csrf=False).post("/api/generic-agent/handoff/prepare", json=BODY).status_code == 403


def test_launch_with_handoff_returns_prompt_and_gateway_env(handoff_env, spawned):
    client = _app()
    hid = client.post("/api/generic-agent/handoff/prepare", json=BODY).json()["handoff_id"]
    r = client.post("/api/generic-agent/terminal", json={
        "agent": "opencode-bare", "project_id": "demo", "repo_path": "/r", "handoff_id": hid,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["created"] is True and "Continue work from a prior Claude Code session" in data["handoff_prompt"]
    assert FAKE not in data["handoff_prompt"]
    env = spawned[-1]["env"]
    assert "OPENCODE_CONFIG_CONTENT" in env and "GATOR_OPENCODE_KEY" in env


def test_launch_with_handoff_crush_gets_crush_env(handoff_env, spawned):
    client = _app()
    hid = client.post("/api/generic-agent/handoff/prepare", json=BODY).json()["handoff_id"]
    client.post("/api/generic-agent/terminal", json={
        "agent": "crush", "project_id": "demo", "repo_path": "/r", "handoff_id": hid,
    })
    assert "CRUSH_GLOBAL_CONFIG" in spawned[-1]["env"]


@pytest.fixture
def live_existing(spawned, monkeypatch):
    """A tracked, live PTY for ("demo", "opencode-bare") so the reuse path is active."""
    import routes.terminal as terminal

    monkeypatch.setattr(generic_agent, "_active_sessions", {("demo", "opencode-bare"): "existing"})
    monkeypatch.setattr(
        terminal, "get_pty_session",
        lambda sid: SimpleNamespace(done=False) if sid == "existing" else None,
    )
    monkeypatch.setattr(terminal, "close_pty_session", lambda sid: None)


OPENCODE_LAUNCH = {"agent": "opencode-bare", "project_id": "demo", "repo_path": "/r", "force_new": False}


def test_live_session_is_reused_without_handoff(handoff_env, live_existing, spawned):
    r = _app().post("/api/generic-agent/terminal", json=OPENCODE_LAUNCH)
    assert r.json() == {"pty_session_id": "existing", "created": False}
    assert spawned == []


def test_handoff_always_spawns_new_process(handoff_env, live_existing, spawned):
    client = _app()
    hid = client.post("/api/generic-agent/handoff/prepare", json=BODY).json()["handoff_id"]
    r = client.post("/api/generic-agent/terminal", json={**OPENCODE_LAUNCH, "handoff_id": hid})
    data = r.json()
    assert data["created"] is True and data["pty_session_id"] != "existing"
    assert len(spawned) == 1 and spawned[0]["session_id"] == data["pty_session_id"]


def test_unknown_handoff_is_404_and_spawns_nothing(handoff_env, spawned):
    r = _app().post("/api/generic-agent/terminal", json={
        "agent": "opencode-bare", "project_id": "demo", "repo_path": "/r", "handoff_id": "0" * 32,
    })
    assert r.status_code == 404 and spawned == []


def test_handoff_to_a_non_target_agent_is_400_and_loads_and_spawns_nothing(handoff_env, spawned, monkeypatch):
    client = _app()
    hid = client.post("/api/generic-agent/handoff/prepare", json=BODY).json()["handoff_id"]

    def fail(_hid):
        raise AssertionError("must not load the handoff")

    monkeypatch.setattr(ah, "load_handoff", fail)
    r = client.post("/api/generic-agent/terminal", json={
        "agent": "terminal", "project_id": "demo", "repo_path": "/r", "handoff_id": hid,
    })
    assert r.status_code == 400 and spawned == []


def test_handoff_to_an_agent_outside_the_target_list_is_400(handoff_env, spawned, monkeypatch):
    client = _app()
    hid = client.post("/api/generic-agent/handoff/prepare", json=BODY).json()["handoff_id"]
    monkeypatch.setattr(ah, "load_handoff", lambda _hid: pytest.fail("must not load the handoff"))
    monkeypatch.setattr(generic_agent, "is_handoff_target", lambda a: False)
    r = client.post("/api/generic-agent/terminal", json={
        "agent": "codex", "project_id": "demo", "repo_path": "/r", "handoff_id": hid,
    })
    assert r.status_code == 400 and spawned == []


def test_only_listed_agents_are_handoff_targets():
    assert all(generic_agent.is_handoff_target(t["agent"]) for t in generic_agent.handoff_targets())
    assert not generic_agent.is_handoff_target("terminal")


def test_launch_logs_target_and_gateway_flag(handoff_env, spawned, caplog):
    client = _app()
    hid = client.post("/api/generic-agent/handoff/prepare", json=BODY).json()["handoff_id"]
    with caplog.at_level(logging.INFO, logger="agent_handoff"):
        client.post("/api/generic-agent/terminal", json={
            "agent": "opencode-bare", "project_id": "demo", "repo_path": "/r", "handoff_id": hid,
        })
    lines = [r.getMessage() for r in caplog.records if "stage=launched" in r.getMessage()]
    assert len(lines) == 1
    assert "source=claude target=opencode-bare" in lines[0] and "gateway_routed=true" in lines[0]
    assert FAKE not in lines[0] and "pane output" not in lines[0]


def test_installed_route_reports_each_launchable_agent(monkeypatch):
    monkeypatch.setattr(generic_agent, "find_agent_binary", lambda agent: "/bin/x" if agent == "claude" else None)
    monkeypatch.setattr(generic_agent, "build_opencode_bare_command", lambda repo: None)
    r = _app().get("/api/generic-agent/installed")
    assert r.status_code == 200
    installed = r.json()["installed"]
    assert {a: installed[a] for a in ("claude", "codex", "crush", "opencode-bare", "terminal")} == {
        "claude": True,
        "codex": False,
        "crush": False,
        "opencode-bare": False,
        "terminal": True,
    }
    assert installed["pi"] is False and set(generic_agent.EXTRA_AGENTS) <= set(installed)


def test_extra_agents_resolve_by_primary_name_or_alias(monkeypatch):
    on_path = {"cbc": "/bin/cbc", "pi": "/bin/pi"}
    monkeypatch.setattr(generic_agent.shutil, "which", lambda name: on_path.get(name))
    assert generic_agent.build_command("pi") == ["/bin/pi"]
    assert generic_agent.build_command("codebuddy") == ["/bin/cbc"]
    assert generic_agent.build_command("gemini") is None


def test_extra_agents_never_carry_workspace_trust_flags():
    for agent, (_, argv, _) in generic_agent.EXTRA_AGENTS.items():
        assert not any("trust" in part for part in argv), agent
        assert generic_agent.is_supported(agent)


def test_installed_check_is_not_cached(monkeypatch):
    found = {"codex": None}
    monkeypatch.setattr(generic_agent, "find_agent_binary", lambda agent: found.get(agent))
    assert generic_agent.is_installed("codex") is False
    found["codex"] = "/bin/codex"
    assert generic_agent.is_installed("codex") is True


def test_prepare_marks_each_target_installed(handoff_env, monkeypatch):
    monkeypatch.setattr(generic_agent, "is_installed", lambda agent: agent in {"claude", "codex", "opencode-bare"})
    data = _app().post("/api/generic-agent/handoff/prepare", json=BODY).json()
    installed = {t["agent"]: t["installed"] for t in data["targets"]}
    assert installed == {"claude": True, "codex": True, "crush": False, "opencode-bare": True}


def test_prepare_lists_installed_extras_but_not_missing_ones(handoff_env, monkeypatch):
    monkeypatch.setattr(
        generic_agent, "is_installed", lambda agent: agent in {"claude", "pi"}
    )
    data = _app().post("/api/generic-agent/handoff/prepare", json=BODY).json()
    by_agent = {t["agent"]: t for t in data["targets"]}
    assert "pi" in by_agent and "aider" not in by_agent
    assert by_agent["pi"]["label"] == "Pi"
    assert by_agent["pi"]["gateway_routed"] is False
    assert by_agent["codex"]["installed"] is False


def test_extra_agent_can_receive_a_handoff(handoff_env, monkeypatch):
    prepared = _app().post("/api/generic-agent/handoff/prepare", json=BODY).json()
    monkeypatch.setattr(generic_agent, "build_command", lambda agent, repo="", extra=(): ["pi"])
    monkeypatch.setattr("routes.terminal.create_pty_session", lambda *a, **k: None)
    r = _app().post(
        "/api/generic-agent/terminal",
        json={"agent": "pi", "project_id": "demo", "repo_path": "/r", "handoff_id": prepared["handoff_id"]},
    )
    assert r.status_code == 200 and r.json()["created"] is True


@pytest.mark.parametrize(
    "owner",
    [
        {"project_id": "other", "agent": "claude"},
        {"project_id": "demo", "agent": "codex"},
        {"project_id": "demo"},
        None,
    ],
)
def test_prepare_refuses_a_session_that_is_not_the_claimed_projects(handoff_env, monkeypatch, owner):
    import routes.terminal as terminal
    monkeypatch.setattr(terminal, "session_owner", lambda sid: owner)
    captured = []
    monkeypatch.setattr(ah, "capture_pane", lambda sid, red=None: captured.append(sid) or "x")
    r = _app().post("/api/generic-agent/handoff/prepare", json=BODY)
    assert r.status_code == 403
    assert captured == [], "nothing is read from a session that is not theirs"
    assert not (ah.HANDOFF_DIR.exists() and any(ah.HANDOFF_DIR.iterdir()))


def test_prepare_unknown_session_is_refused(handoff_env):
    r = _app().post("/api/generic-agent/handoff/prepare", json={**BODY, "pty_session_id": "nope"})
    assert r.status_code == 403


def test_prepare_reports_a_store_failure_and_keeps_nothing(handoff_env, monkeypatch):
    import file_perms

    def refuse(path, *, directory=False):
        if not directory:
            raise OSError("icacls exited with 5")

    monkeypatch.setattr(file_perms, "restrict_to_owner", refuse)
    r = _app().post("/api/generic-agent/handoff/prepare", json=BODY)
    assert r.status_code == 500
    assert "nothing was saved" in r.json()["detail"]
    assert list(ah.HANDOFF_DIR.iterdir()) == []


def test_session_owner_reads_labels_from_the_live_session_and_the_host(monkeypatch):
    import routes.terminal as terminal

    monkeypatch.setattr(terminal, "_pty_sessions", {"live": SimpleNamespace(meta={"project_id": "p", "agent": "claude"}), "adopted": SimpleNamespace(meta=None)})
    assert terminal.session_owner("live") == {"project_id": "p", "agent": "claude"}

    monkeypatch.setattr(terminal.pty_client, "host_enabled", lambda: True)
    monkeypatch.setattr(terminal.pty_client, "instance_key", lambda: "k")
    monkeypatch.setattr(terminal.pty_client, "find_host", lambda key: object())
    monkeypatch.setattr(
        terminal.pty_client, "host_request",
        lambda info, req: {"sessions": [{"id": "adopted", "meta": {"project_id": "p", "agent": "codex"}}, {"id": "bare"}]},
    )
    assert terminal.session_owner("adopted") == {"project_id": "p", "agent": "codex"}
    assert terminal.session_owner("bare") is None
    assert terminal.session_owner("missing") is None

    monkeypatch.setattr(terminal.pty_client, "host_enabled", lambda: False)
    assert terminal.session_owner("adopted") is None
