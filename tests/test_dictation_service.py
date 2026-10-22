"""Model registry and service behaviour for local dictation."""
import json

import pytest

from dictation import engine as engine_mod
from dictation import service


class FakeEngine:
    loads = 0

    def load(self, model_dir):
        FakeEngine.loads += 1
        self.model_dir = model_dir

    def transcribe(self, pcm16):
        return f"heard {len(pcm16)} bytes"


@pytest.fixture
def registry(tmp_path, monkeypatch):
    FakeEngine.loads = 0
    manifest = {
        "default": "m1",
        "models": {
            "m1": {"engine": "fake", "dir": "m1-dir"},
            "m2": {"engine": "fake", "dir": "m2-dir"},
        },
    }
    mpath = tmp_path / "models.json"
    mpath.write_text(json.dumps(manifest))
    bundled = tmp_path / "bundled"
    user = tmp_path / "user"
    monkeypatch.setattr(service, "MANIFEST_PATH", mpath)
    monkeypatch.setattr(service, "USER_MODELS_DIR", user)
    monkeypatch.setenv("AIGATOR_MODELS_DIR", str(bundled))
    engine_mod.register_engine("fake", FakeEngine)
    service.reset()
    yield {"bundled": bundled, "user": user}
    service.reset()
    engine_mod._ENGINES.pop("fake", None)


def _make_model(root, name):
    d = root / name
    d.mkdir(parents=True)
    (d / "model.bin").write_bytes(b"x")
    return d


def test_default_model_used_when_config_has_none(registry):
    assert service.active_model_id({}) == "m1"


def test_config_override_selects_model(registry):
    assert service.active_model_id({"dictation": {"model": "m2"}}) == "m2"


def test_unknown_model_lists_known_ids(registry):
    with pytest.raises(service.DictationUnavailable) as e:
        service.active_model_id({"dictation": {"model": "nope"}})
    assert "m1" in str(e.value) and "m2" in str(e.value)


def test_missing_model_files_is_unavailable(registry):
    with pytest.raises(service.DictationUnavailable):
        service.transcribe(b"\x00\x00", cfg={})


def test_bundled_model_is_found_and_engine_loads_once(registry):
    _make_model(registry["bundled"], "m1-dir")
    assert service.transcribe(b"\x00\x00", cfg={}) == "heard 2 bytes"
    assert service.transcribe(b"\x00\x00\x00\x00", cfg={}) == "heard 4 bytes"
    assert FakeEngine.loads == 1


def test_user_directory_wins_over_bundled(registry):
    _make_model(registry["bundled"], "m1-dir")
    user_dir = _make_model(registry["user"], "m1-dir")
    assert service.resolve_model_dir("m1") == user_dir


def test_switching_model_reloads_engine(registry):
    _make_model(registry["bundled"], "m1-dir")
    _make_model(registry["bundled"], "m2-dir")
    service.transcribe(b"\x00\x00", cfg={})
    service.transcribe(b"\x00\x00", cfg={"dictation": {"model": "m2"}})
    assert FakeEngine.loads == 2


def test_unknown_engine_name_is_unavailable(registry, tmp_path):
    manifest = {"default": "m1", "models": {"m1": {"engine": "ghost", "dir": "m1-dir"}}}
    service.MANIFEST_PATH.write_text(json.dumps(manifest))
    service.reset()
    _make_model(registry["bundled"], "m1-dir")
    with pytest.raises(service.DictationUnavailable):
        service.transcribe(b"\x00\x00", cfg={})


def test_engine_load_failure_is_unavailable_and_retried(registry, monkeypatch):
    _make_model(registry["bundled"], "m1-dir")
    calls = {"n": 0}

    class Flaky(FakeEngine):
        def load(self, model_dir):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            super().load(model_dir)

    engine_mod.register_engine("fake", Flaky)
    with pytest.raises(service.DictationUnavailable):
        service.transcribe(b"\x00\x00", cfg={})
    assert service.transcribe(b"\x00\x00", cfg={}) == "heard 2 bytes"


def test_shipped_manifest_is_valid():
    manifest = json.loads(service.MANIFEST_PATH.read_text())
    assert manifest["default"] in manifest["models"]
    for entry in manifest["models"].values():
        assert {"engine", "dir", "repo", "revision", "files"} <= set(entry)
        assert "model.bin" in entry["files"]
        assert all(len(h) == 64 for h in entry["files"].values())
