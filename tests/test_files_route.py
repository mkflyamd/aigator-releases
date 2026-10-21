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
    monkeypatch.setattr(files_mod, "_overflow_capabilities", {})
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


def test_overflow_file_requires_its_download_capability(client, tmp_outputs):
    from routes.files import register_overflow_file

    run_dir = tmp_outputs / "overflow"
    run_dir.mkdir()
    (run_dir / "tool_output.txt").write_text("sensitive")
    register_overflow_file("overflow", "tool_output.txt", "secret-token")

    assert client.get("/api/files/overflow/tool_output.txt").status_code == 403
    assert client.get("/api/files/overflow/tool_output.txt?token=wrong").status_code == 403
    allowed = client.get("/api/files/overflow/tool_output.txt?token=secret-token")
    assert allowed.status_code == 200
    assert allowed.text == "sensitive"


def test_unregistered_overflow_file_fails_closed(client, tmp_outputs):
    run_dir = tmp_outputs / "stale-overflow"
    run_dir.mkdir()
    (run_dir / "tool_output.txt").write_text("sensitive")

    assert client.get("/api/files/stale-overflow/tool_output.txt").status_code == 403


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


def test_cleanup_removes_old_run_folders_inside_tier_folders(tmp_outputs):
    import os
    import time

    import routes.files as files_mod

    old = tmp_outputs / "community" / "old1"
    fresh = tmp_outputs / "community" / "new1"
    flat_old = tmp_outputs / "flat1"
    for d in (old, fresh, flat_old):
        d.mkdir(parents=True)
    past = time.time() - 48 * 3600
    for d in (old, flat_old):
        os.utime(d, (past, past))

    files_mod.cleanup_old_outputs()

    assert not old.exists() and not flat_old.exists()
    assert fresh.exists() and (tmp_outputs / "community").exists()
