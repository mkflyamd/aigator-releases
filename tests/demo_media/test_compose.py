from pathlib import Path

import demo_compose as compose

FILTER_720 = (
    "scale=1280:720:force_original_aspect_ratio=decrease,"
    "pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=30,format=yuv420p"
)


def test_canvas_size_scales_down_and_rounds_even():
    assert compose.canvas_size([{"width": 3840, "height": 2160}]) == (1920, 1080)
    assert compose.canvas_size([{"width": 1280, "height": 720}]) == (1280, 720)
    assert compose.canvas_size([{"width": 1001, "height": 501}]) == (1000, 500)
    assert compose.canvas_size([{"width": 1080, "height": 1920}]) == (606, 1080)


def test_canvas_uses_first_clip_only():
    clips = [{"width": 1280, "height": 720}, {"width": 3840, "height": 2160}]
    assert compose.canvas_size(clips) == (1280, 720)


def test_video_filter():
    assert compose.video_filter(1280, 720) == FILTER_720


def test_normalize_argv():
    argv = compose.normalize_argv("ff", Path("a.mp4"), Path("n.mp4"), 1.5, 8.0, 1280, 720)
    assert argv == ["ff", "-y", "-ss", "1.5", "-t", "8.0", "-i", "a.mp4", "-an", "-vf", FILTER_720,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "n.mp4"]


def test_normalized_name_depends_on_trim_and_canvas(tmp_path):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    base = {"id": "c1", "trim_start": 0.0, "trim_end": None}
    name = compose.normalized_name(base, src, 1280, 720)
    assert name.startswith("c1_") and name.endswith(".mp4") and len(name) == len("c1_") + 8 + len(".mp4")
    assert name == compose.normalized_name(dict(base), src, 1280, 720)
    assert name != compose.normalized_name({**base, "trim_start": 1.0}, src, 1280, 720)
    assert name != compose.normalized_name(base, src, 640, 360)


def test_concat_list_text_escapes_quotes():
    text = compose.concat_list_text([Path("a.mp4"), Path("it's.mp4")])
    assert text == "file 'a.mp4'\nfile 'it'\\''s.mp4'\n"


def test_concat_argv():
    assert compose.concat_argv("ff", Path("list.txt"), Path("t.mp4")) == [
        "ff", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy",
        "-movflags", "+faststart", "t.mp4"]


def test_soundtrack_argv():
    argv = compose.soundtrack_argv("ff", [Path("a.mp3"), Path("b.wav")], Path("s.m4a"))
    assert argv == [
        "ff", "-y", "-i", "a.mp3", "-i", "b.wav", "-filter_complex",
        "[0:a]aresample=48000,aformat=channel_layouts=stereo[a0];"
        "[1:a]aresample=48000,aformat=channel_layouts=stereo[a1];"
        "[a0][a1]concat=n=2:v=0:a=1[a]",
        "-map", "[a]", "-c:a", "aac", "-b:a", "128k", "s.m4a"]
