from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import config
import shared
from marketplace import commands, installer, kill_switch, loader, state
from marketplace.installer import skill_id_for_cache_path
from routes.marketplace import router
from security import get_csrf_token

SOLO_MD = "---\nname: Solo\ndescription: solo skill\n---\n# Solo\nDo solo things.\n"
HELPER_MD = "---\nname: Helper\ndescription: helper skill\n---\n# Helper\nHelp.\n"
COMMAND_MD = "---\ndescription: say hello\n---\nSay hello to $ARGUMENTS\n"


@pytest.fixture
def env(tmp_path, monkeypatch):
    skills = tmp_path / "skills-under-test"
    plugins = tmp_path / "plugins"
    cache = plugins / "cache"
    for module in (installer, config):
        monkeypatch.setattr(module, "INSTALLED_SKILLS_DIR", skills)
        monkeypatch.setattr(module, "PLUGINS_DIR", plugins)
    monkeypatch.setattr(shared, "_USER_SKILL_DIRS", [skills, cache])

    (skills / "solo").mkdir(parents=True)
    (skills / "solo" / "SKILL.md").write_text(SOLO_MD, encoding="utf-8")

    bundle_dir = cache / "mkt" / "bundle" / "2.0"
    helper_md = bundle_dir / "skills" / "helper" / "SKILL.md"
    helper_md.parent.mkdir(parents=True)
    helper_md.write_text(HELPER_MD, encoding="utf-8")
    (bundle_dir / "commands").mkdir()
    (bundle_dir / "commands" / "hello-cmd.md").write_text(COMMAND_MD, encoding="utf-8")
    inner = skill_id_for_cache_path(cache, helper_md)
    assert inner

    installer.save_installed([
        {"id": "solo", "version": "1.0", "tier": "Community"},
        {"id": "mine-one", "version": "1.0", "tier": "Mine"},
        {"id": "bundle", "version": "2.0", "tier": "Verified", "source": "mkt",
         "skill_ids": [inner], "command_ids": ["hello-cmd"]},
    ])
    shared.load_installed_skill_prompts()
    commands.register_plugin_commands("bundle", bundle_dir)
    assert "solo" in shared.SKILL_PROMPTS and inner in shared.SKILL_PROMPTS
    assert "hello-cmd" in commands.COMMAND_REGISTRY

    yield SimpleNamespace(inner=inner, skills=skills, bundle_dir=bundle_dir)

    for registry in (shared.SKILL_PROMPTS, shared.SKILL_REQUIRES, shared.SKILL_DESCRIPTIONS, shared.SKILL_OUTPUT_FORMATS):
        for key in ("solo", inner):
            registry.pop(key, None)
    commands.COMMAND_REGISTRY.pop("hello-cmd", None)


@pytest.fixture
def calls(monkeypatch):
    seen = SimpleNamespace(unloaded=[], loaded=[], torn=[], registered_mcp=[])
    monkeypatch.setattr(loader, "unload_skill_tools", lambda sid: seen.unloaded.append(sid))
    monkeypatch.setattr(loader, "load_skill_tools", lambda sid, d, tier: seen.loaded.append((sid, d, tier)) or {"ok": True})
    monkeypatch.setattr(installer, "_teardown_plugin_mcp", lambda pid: seen.torn.append(pid))
    monkeypatch.setattr(installer, "_register_plugin_mcp_servers",
                        lambda pid, d: seen.registered_mcp.append((pid, d)) or [])
    return seen


def test_unknown_skill_is_not_found(env, calls):
    assert kill_switch.disable("nope") == {"ok": False, "error": "skill not found: nope"}
    assert kill_switch.enable("nope")["ok"] is False


def test_a_bundles_inner_skill_cannot_be_disabled_on_its_own(env, calls):
    result = kill_switch.disable(env.inner)
    assert result["ok"] is False
    assert not state.is_disabled(env.inner)


def test_disable_a_standalone_skill(env, calls):
    assert kill_switch.disable("solo") == {"ok": True}
    assert state.is_disabled("solo")
    assert "solo" not in shared.SKILL_PROMPTS
    assert calls.unloaded == ["solo"]
    assert calls.torn == []


def test_disable_a_bundle_takes_down_skills_commands_and_mcp(env, calls):
    assert kill_switch.disable("bundle") == {"ok": True}
    assert env.inner not in shared.SKILL_PROMPTS
    assert "hello-cmd" not in commands.COMMAND_REGISTRY
    assert calls.torn == ["bundle"]
    assert set(calls.unloaded) == {"bundle", env.inner}


def test_disabled_state_survives_prompt_and_command_reloads(env, calls):
    kill_switch.disable("bundle")
    kill_switch.disable("solo")
    shared.load_installed_skill_prompts()
    commands.load_installed_plugin_commands()
    assert "solo" not in shared.SKILL_PROMPTS
    assert env.inner not in shared.SKILL_PROMPTS
    assert "hello-cmd" not in commands.COMMAND_REGISTRY


def test_enable_a_standalone_skill_restores_prompt_and_reloads_tools(env, calls):
    kill_switch.disable("solo")
    assert kill_switch.enable("solo") == {"ok": True}
    assert not state.is_disabled("solo")
    assert "solo" in shared.SKILL_PROMPTS
    assert calls.loaded == [("solo", env.skills / "solo", "Community")]


def test_enable_a_bundle_restores_skills_commands_and_mcp_without_loading_tools(env, calls):
    kill_switch.disable("bundle")
    assert kill_switch.enable("bundle") == {"ok": True}
    assert env.inner in shared.SKILL_PROMPTS
    assert "hello-cmd" in commands.COMMAND_REGISTRY
    assert calls.registered_mcp == [("bundle", env.bundle_dir)]
    assert calls.loaded == []


def test_enable_skips_the_tool_load_when_the_folder_is_not_at_the_install_location(env, calls):
    kill_switch.disable("mine-one")
    assert kill_switch.enable("mine-one") == {"ok": True}
    assert calls.loaded == []


def test_one_failing_step_does_not_stop_the_others(env, monkeypatch, calls):
    def boom(_sid):
        raise RuntimeError("unload failed")

    monkeypatch.setattr(loader, "unload_skill_tools", boom)
    assert kill_switch.disable("solo") == {"ok": True}
    assert state.is_disabled("solo")
    assert "solo" not in shared.SKILL_PROMPTS


def test_run_python_cannot_borrow_a_disabled_skills_folder(env, monkeypatch, calls):
    from skills.code_runner import tools as cr

    monkeypatch.setattr(cr, "USER_SKILL_DIRS", [env.skills])
    assert cr._find_skill_dir("solo") == env.skills / "solo"
    kill_switch.disable("solo")
    assert cr._find_skill_dir("solo") is None


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _post(client, path, token=True):
    return client.post(path, headers={"X-CSRF-Token": get_csrf_token()} if token else {})


def test_routes_require_the_csrf_token(env, calls, client):
    assert _post(client, "/api/marketplace/disable/solo", token=False).status_code == 403
    assert _post(client, "/api/marketplace/enable/solo", token=False).status_code == 403
    assert not state.is_disabled("solo")


def test_routes_return_404_for_an_unknown_skill(env, calls, client):
    assert _post(client, "/api/marketplace/disable/nope").status_code == 404
    assert _post(client, "/api/marketplace/enable/nope").status_code == 404


def test_routes_round_trip_and_the_listing_reports_the_flag(env, calls, client):
    resp = _post(client, "/api/marketplace/disable/solo")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "skill_id": "solo", "disabled": True}
    listing = client.get("/api/marketplace/installed").json()["skills"]
    assert next(s for s in listing if s["id"] == "solo")["disabled"] is True

    resp = _post(client, "/api/marketplace/enable/solo")
    assert resp.json() == {"ok": True, "skill_id": "solo", "disabled": False}
    listing = client.get("/api/marketplace/installed").json()["skills"]
    assert "disabled" not in next(s for s in listing if s["id"] == "solo")


def test_reinstalling_a_disabled_skill_gives_a_fresh_enabled_record(env, calls):
    # The installer replaces the whole record, so a reinstall (approved again by the user)
    # does not carry the disabled flag or the old grants across.
    kill_switch.disable("solo")
    installer._upsert_installed_entry("solo", "1.1", "Community", "", "")
    assert not state.is_disabled("solo")
    entry = state.get_entry("solo")
    assert "disabled" not in entry
    assert "permissions" not in entry
