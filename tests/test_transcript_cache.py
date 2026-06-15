import sys, pathlib, os
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web" / "skills" / "m365-teams" / "scripts"))


def test_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("GATOR_TRANSCRIPT_CACHE_DIR", str(tmp_path))
    import importlib, transcript_config, transcript_cache
    importlib.reload(transcript_config)
    importlib.reload(transcript_cache)

    assert transcript_cache.read("tx-1") is None
    transcript_cache.write("tx-1", "WEBVTT\n\nhello\n")
    assert transcript_cache.read("tx-1") == "WEBVTT\n\nhello\n"
    if os.name == "posix":
        path = tmp_path / "tx-1.vtt"
        assert (path.stat().st_mode & 0o777) == 0o600


def test_cache_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("GATOR_TRANSCRIPT_CACHE_DIR", str(tmp_path))
    import importlib, transcript_config, transcript_cache
    importlib.reload(transcript_config)
    importlib.reload(transcript_cache)

    import pytest
    with pytest.raises(ValueError):
        transcript_cache.write("../evil", "x")
    with pytest.raises(ValueError):
        transcript_cache.read("../evil")
