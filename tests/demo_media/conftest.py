import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    import demo_projects as dp

    cfg: dict = {}
    monkeypatch.setattr(dp, "INDEX_PATH", tmp_path / "gator" / "demo_projects.json")
    monkeypatch.setattr(dp, "DEFAULT_ROOT", tmp_path / "demos")
    monkeypatch.setattr(dp, "load_config", lambda: dict(cfg))
    monkeypatch.setattr(dp, "save_config", lambda d: (cfg.clear(), cfg.update(d)))
    return dp


def _ffprobe_json(kind="video", duration=10.0, width=1920, height=1080,
                  vcodec="h264", acodec="aac", has_audio=True, attached_pic=False):
    streams = []
    if kind == "video":
        streams.append({"codec_type": "video", "codec_name": vcodec, "width": width,
                        "height": height, "disposition": {"attached_pic": 0}})
        if has_audio:
            streams.append({"codec_type": "audio", "codec_name": acodec})
    else:
        streams.append({"codec_type": "audio", "codec_name": acodec})
        if attached_pic:
            streams.append({"codec_type": "video", "codec_name": "mjpeg", "width": 500,
                            "height": 500, "disposition": {"attached_pic": 1}})
    return {"streams": streams, "format": {"duration": str(duration)}}


@pytest.fixture
def fake_ffprobe(monkeypatch):
    import demo_media_probe as probe

    def install(**kwargs):
        data = _ffprobe_json(**kwargs)
        monkeypatch.setattr(probe, "_run_ffprobe", lambda path: data)

    return install
