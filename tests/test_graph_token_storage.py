import importlib.util
import json
import time
from pathlib import Path

import pytest

import secure_store

FAKE = "aigator-fake-api-key"
SRC = Path(__file__).resolve().parents[1] / "web" / "skills" / "m365-email" / "graph_client.py"


@pytest.fixture
def gc(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("graph_client_under_test", SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "TOKEN_FILE", tmp_path / "legacy" / "token.json")
    monkeypatch.setattr(mod, "OLD_TOKEN_FILE", tmp_path / "legacy" / "old.json")
    monkeypatch.delenv("MS_ACCESS_TOKEN", raising=False)
    return mod


def _seed(mod, **kw):
    c = mod.GraphClient()
    c._refresh_token = kw.get("refresh", "r1")
    c._tenant_id = "t"
    c._client_id = "c"
    c._access_token = kw.get("access", FAKE)
    c._expires_at = kw.get("expires_at", time.time() + 3600)
    c._save_token()
    return c


def test_save_then_new_client_loads_token(gc):
    _seed(gc)
    c2 = gc.GraphClient()
    assert (c2._refresh_token, c2._tenant_id, c2._access_token) == ("r1", "t", FAKE)


def test_token_is_not_written_as_plaintext_json(gc):
    _seed(gc)
    assert FAKE not in json.dumps(
        [str(p) for p in (secure_store._home()).rglob("*") if p.is_file() and p.suffix == ".json"]
    )
    assert not list(secure_store._home().rglob("*.json"))
    assert secure_store.get_json("graph/token")["refresh_token"] == "r1"


def test_legacy_token_file_is_migrated(gc):
    legacy = secure_store._home() / ".config" / "microsoft-graph" / "token.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"refresh_token": "legacy-r", "tenant_id": "t", "client_id": "c"}))
    c = gc.GraphClient()
    assert c._refresh_token == "legacy-r"
    assert not legacy.exists()


def test_refresh_adopts_rotated_refresh_token(gc, monkeypatch):
    c = _seed(gc, expires_at=0.0)

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(
                {"access_token": "aigator-fake-api-key", "refresh_token": "r2", "expires_in": 3600}
            ).encode()

    monkeypatch.setattr(gc.urllib.request, "urlopen", lambda *a, **k: _Resp())
    assert c.get_token() == "aigator-fake-api-key"
    assert secure_store.get_json("graph/token")["refresh_token"] == "r2"
    assert gc.GraphClient()._refresh_token == "r2"
