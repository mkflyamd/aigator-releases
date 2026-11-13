"""save_api_key must not revert a config write another request makes while its gateway check is in flight."""

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import config as cfg_mod
from routes import config_routes


class _Resp:
    is_success = True
    status_code = 200
    text = ""


def test_concurrent_config_write_survives_api_key_save(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "aigator-fake-api-key")
    monkeypatch.setenv("GATEWAY_USER_ID", "")
    cfg_mod.save_config({"username": "before"})

    import httpx

    def _post_while_another_request_saves(*args, **kwargs):
        cfg_mod.update_config(lambda c: c.update(username="written-during-check"))
        return _Resp()

    monkeypatch.setattr(httpx, "post", _post_while_another_request_saves)

    req = config_routes.ApiKeyRequest(api_key="aigator-fake-api-key", user_id="alice")
    assert asyncio.run(config_routes.save_api_key(req)) == {"ok": True}

    saved = cfg_mod.load_config()
    assert saved["username"] == "written-during-check"
    assert saved["gateway_user_id"] == "alice"
