"""Build-time model fetch: checksum verification and skip-if-present."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "fetch_dictation_model",
    Path(__file__).resolve().parent.parent / "tools" / "fetch_dictation_model.py",
)
fetch_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch_mod)

GOOD = b"model bytes"


@pytest.fixture
def manifest(tmp_path, monkeypatch):
    path = tmp_path / "models.json"
    path.write_text(json.dumps({
        "default": "m",
        "models": {"m": {
            "engine": "fake", "dir": "m-dir", "repo": "o/r", "revision": "abc",
            "files": {"model.bin": hashlib.sha256(GOOD).hexdigest()},
        }},
    }))
    monkeypatch.setattr(fetch_mod, "MANIFEST", path)
    return path


def test_downloads_missing_file_from_pinned_revision(manifest, tmp_path):
    urls = []

    def fake(url, dest):
        urls.append(url)
        dest.write_bytes(GOOD)

    target = fetch_mod.fetch(dest_root=tmp_path / "out", downloader=fake)
    assert (target / "model.bin").read_bytes() == GOOD
    assert urls == ["https://huggingface.co/o/r/resolve/abc/model.bin"]


def test_skips_file_that_already_matches(manifest, tmp_path):
    out = tmp_path / "out" / "m-dir"
    out.mkdir(parents=True)
    (out / "model.bin").write_bytes(GOOD)

    def fail(url, dest):
        raise AssertionError("should not download")

    fetch_mod.fetch(dest_root=tmp_path / "out", downloader=fail)


def test_checksum_mismatch_fails_and_removes_file(manifest, tmp_path):
    def bad(url, dest):
        dest.write_bytes(b"tampered")

    with pytest.raises(SystemExit) as e:
        fetch_mod.fetch(dest_root=tmp_path / "out", downloader=bad)
    assert "checksum mismatch" in str(e.value)
    assert not (tmp_path / "out" / "m-dir" / "model.bin").exists()


def test_unknown_model_id_fails(manifest, tmp_path):
    with pytest.raises(SystemExit):
        fetch_mod.fetch("nope", dest_root=tmp_path / "out")
