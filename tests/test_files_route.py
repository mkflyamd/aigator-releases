import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch


@pytest.fixture
def tmp_outputs(tmp_path, monkeypatch):
    """Point OUTPUTS_DIR at a tmp directory for testing."""
    import config as cfg_mod
    import routes.files as files_mod
    monkeypatch.setattr(cfg_mod, "OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(files_mod, "OUTPUTS_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def client(tmp_outputs):
    from routes.files import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_serve_existing_file(client, tmp_outputs):
    run_dir = tmp_outputs / "abc123"
    run_dir.mkdir()
    (run_dir / "output.gif").write_bytes(b"GIF89a")

    resp = client.get("/api/files/abc123/output.gif")
    assert resp.status_code == 200
    assert resp.content == b"GIF89a"


def test_missing_file_returns_404(client, tmp_outputs):
    resp = client.get("/api/files/nonexistent/file.gif")
    assert resp.status_code == 404


def test_path_traversal_rejected(client, tmp_outputs):
    resp = client.get("/api/files/../../../etc/passwd")
    # FastAPI URL routing normalises this — just ensure no 200
    assert resp.status_code != 200


def test_cleanup_old_outputs(tmp_outputs):
    import time
    from routes.files import cleanup_old_outputs

    old_dir = tmp_outputs / "old_run"
    old_dir.mkdir()
    (old_dir / "file.gif").write_bytes(b"old")
    # Force mtime to be 25 hours ago
    old_time = time.time() - 25 * 3600
    import os
    os.utime(old_dir, (old_time, old_time))

    new_dir = tmp_outputs / "new_run"
    new_dir.mkdir()
    (new_dir / "file.gif").write_bytes(b"new")

    cleanup_old_outputs()
    assert not old_dir.exists()
    assert new_dir.exists()
