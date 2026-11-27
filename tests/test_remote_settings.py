"""Remote control settings: what a save accepts, and that the running loop reads them fresh."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from remote import commands
from remote import loop as remote_loop
from remote import settings
from remote.guard import Guard
from remote.service import RemoteError, RemoteService
from routes import config_routes
from skills.code_agent import projects
from tests.test_remote_runner import BUDGET, Clock, FakeChannel, FakeHost, World
from web.security import verify_csrf

REPO = "C:/repo/budget"


@pytest.fixture
def known_projects(monkeypatch):
    monkeypatch.setattr(
        projects,
        "get_project",
        lambda name: {"name": name, "repo_path": REPO} if name in ("Budget", "Other") else None,
    )
    monkeypatch.setattr(projects, "get_active_project", lambda: None)


def test_a_known_project_blank_and_in_range_numbers_are_accepted(known_projects):
    assert settings.validate({"remote_default_project": "Budget"}) is None
    assert settings.validate({"remote_default_project": ""}) is None
    assert settings.validate({"remote_default_project": None}) is None
    assert settings.validate({"remote_session_idle_hours": 8, "remote_stale_minutes": 15, "remote_armed_max_hours": 24}) is None
    assert settings.validate({"teams_remote_control_enabled": True, "slack_remote_control_enabled": False}) is None


def test_an_unknown_project_is_refused_with_a_clear_reason(known_projects):
    assert 'no project named "Nope"' in settings.validate({"remote_default_project": "Nope"})
    assert settings.validate({"remote_default_project": 7}) is not None


@pytest.mark.parametrize(
    "key,value",
    [
        ("remote_session_idle_hours", 0),
        ("remote_session_idle_hours", 73),
        ("remote_session_idle_hours", "8"),
        ("remote_session_idle_hours", True),
        ("remote_session_idle_hours", None),
        ("remote_stale_minutes", 121),
        ("remote_armed_max_hours", 0.5),
        ("teams_remote_control_enabled", "yes"),
        ("slack_remote_control_enabled", 1),
    ],
)
def test_out_of_range_or_mistyped_values_are_refused(known_projects, key, value):
    assert settings.validate({key: value}) is not None


def _client(monkeypatch, saved):
    store = {}

    def update(mutator):
        cfg = dict(store)
        mutator(cfg)
        store.clear()
        store.update(cfg)
        saved.append(dict(cfg))
        return cfg

    monkeypatch.setattr(config_routes, "_update_config", update)
    app = FastAPI()
    app.include_router(config_routes.router)
    app.dependency_overrides[verify_csrf] = lambda: None
    return TestClient(app), store


def test_saving_an_unknown_default_project_is_a_400_and_stores_nothing(monkeypatch, known_projects):
    saved = []
    client, store = _client(monkeypatch, saved)
    r = client.patch("/api/config", json={"remote_default_project": "Nope"})
    assert r.status_code == 400
    assert "Nope" in r.json()["detail"]
    assert saved == []


def test_saving_valid_remote_settings_stores_them(monkeypatch, known_projects):
    saved = []
    client, store = _client(monkeypatch, saved)
    r = client.patch(
        "/api/config",
        json={"remote_default_project": "Other", "remote_stale_minutes": 30, "slack_remote_control_enabled": True},
    )
    assert r.status_code == 200
    assert store["remote_default_project"] == "Other"
    assert store["remote_stale_minutes"] == 30
    assert store["slack_remote_control_enabled"] is True


def test_the_limits_come_from_config_and_fall_back_to_the_defaults(monkeypatch):
    cfg = {}
    monkeypatch.setattr(settings, "load_config", lambda: cfg)
    assert (settings.idle_seconds(), settings.stale_seconds(), settings.armed_max_seconds()) == (8 * 3600, 15 * 60, 24 * 3600)
    cfg.update(remote_session_idle_hours=2, remote_stale_minutes=5, remote_armed_max_hours=1.5)
    assert (settings.idle_seconds(), settings.stale_seconds(), settings.armed_max_seconds()) == (7200, 300, 5400)
    cfg.update(remote_session_idle_hours="x", remote_stale_minutes=0, remote_armed_max_hours=True)
    assert (settings.idle_seconds(), settings.stale_seconds(), settings.armed_max_seconds()) == (8 * 3600, 15 * 60, 24 * 3600)


async def test_a_changed_idle_limit_applies_to_a_running_service(monkeypatch):
    cfg = {"remote_session_idle_hours": 8}
    monkeypatch.setattr(settings, "load_config", lambda: cfg)
    clock, host = Clock(), FakeHost()
    service = RemoteService(host, default_project=lambda: BUDGET, clock=clock, idle_seconds=settings.idle_seconds)
    session = await service.start(BUDGET, "hi")
    clock.now += 2 * 3600
    await service.tick()
    assert service.list() == [session]
    cfg["remote_session_idle_hours"] = 1
    await service.tick()
    assert service.list() == []


def test_a_changed_armed_limit_applies_to_a_running_guard(monkeypatch):
    cfg = {}
    monkeypatch.setattr(settings, "load_config", lambda: cfg)
    clock = Clock()
    guard = Guard(clock=clock, armed_max_seconds=settings.armed_max_seconds)
    guard.arm()
    clock.now += 2 * 3600
    assert guard.armed
    cfg["remote_armed_max_hours"] = 1
    assert not guard.armed


def test_the_default_project_is_the_chosen_one_else_the_active_one(monkeypatch, known_projects):
    cfg = {}
    monkeypatch.setattr(remote_loop, "load_config", lambda: cfg)
    assert remote_loop.default_project() is None
    monkeypatch.setattr(projects, "get_active_project", lambda: "Other")
    assert remote_loop.default_project().name == "Other"
    cfg["remote_default_project"] = "Budget"
    assert remote_loop.default_project().name == "Budget"


def test_a_chosen_project_that_no_longer_exists_is_refused_not_replaced_by_the_active_one(monkeypatch, known_projects):
    monkeypatch.setattr(remote_loop, "load_config", lambda: {"remote_default_project": "Gone"})
    monkeypatch.setattr(projects, "get_active_project", lambda: "Other")
    with pytest.raises(RemoteError) as refused:
        remote_loop.default_project()
    assert 'The default project "Gone" no longer exists' in str(refused.value)


async def test_a_message_with_a_missing_default_project_gets_a_gator_refusal_and_starts_nothing(tmp_path, monkeypatch, known_projects):
    monkeypatch.setattr(remote_loop, "load_config", lambda: {"remote_default_project": "Gone"})
    w = World(tmp_path)
    w.service._default_project = remote_loop.default_project
    await w.feed(w.msg(100, "old note"))
    await w.feed(w.msg(101, "@gator say ok"))
    assert w.host.n == 0
    assert w.channel.posted == [
        commands.error_reply('The default project "Gone" no longer exists. Choose another in Settings, then resend.')
    ]


@pytest.mark.parametrize(
    "key,low,high",
    [("remote_session_idle_hours", 1, 72), ("remote_stale_minutes", 1, 120), ("remote_armed_max_hours", 1, 168)],
)
def test_the_limits_accept_both_ends_of_their_range(known_projects, key, low, high):
    assert settings.validate({key: low}) is None
    assert settings.validate({key: high}) is None
    assert settings.validate({key: low - 1}) is not None
    assert settings.validate({key: high + 1}) is not None


def test_saving_an_out_of_range_limit_is_a_400_and_stores_nothing(monkeypatch, known_projects):
    saved = []
    client, store = _client(monkeypatch, saved)
    r = client.patch("/api/config", json={"remote_stale_minutes": 500})
    assert r.status_code == 400
    assert "1 to 120" in r.json()["detail"]
    assert saved == []


def test_a_save_is_applied_inside_update_config_so_other_writes_are_not_lost(monkeypatch, known_projects):
    seen = []
    monkeypatch.setattr(config_routes, "_update_config", lambda m: (seen.append(m), {"remote_stale_minutes": 30})[1])
    app = FastAPI()
    app.include_router(config_routes.router)
    app.dependency_overrides[verify_csrf] = lambda: None
    r = TestClient(app).patch("/api/config", json={"remote_stale_minutes": 30, "github_url": "ignored"})
    assert r.status_code == 200
    assert len(seen) == 1
    cfg = {"github_url": "keep"}
    seen[0](cfg)
    assert cfg == {"github_url": "keep", "remote_stale_minutes": 30}
