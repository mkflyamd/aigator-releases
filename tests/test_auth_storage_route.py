import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest
from fastapi.testclient import TestClient

import secure_store
from app import app


@pytest.mark.parametrize("level", ["os-vault", "key-file", "unavailable"])
def test_storage_route_reports_protection_level(monkeypatch, level):
    monkeypatch.setattr(secure_store, "protection_level", lambda: level)
    res = TestClient(app).get("/api/auth/storage")
    assert res.status_code == 200
    assert res.json() == {"level": level}
