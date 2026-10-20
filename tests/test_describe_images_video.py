from skills._always_on import tools as ao

HANDLER = ao.TOOL_HANDLERS["describe_images"]


async def test_analyze_sequence_rejects_more_than_eight_frames():
    paths = [f"/tmp/code_runner_out/frames/frame_{i:04d}.png" for i in range(42)]
    r = await HANDLER(task="analyze_sequence", image_paths=paths)

    assert r["ok"] is False
    assert "at most 8" in r["error"] and "analyze_video" in r["error"]
    assert "do not exist" not in r["error"]


async def test_analyze_sequence_with_eight_missing_frames_still_reports_missing():
    paths = [f"/tmp/code_runner_out/frames/frame_{i:04d}.png" for i in range(8)]
    r = await HANDLER(task="analyze_sequence", image_paths=paths)

    assert r["ok"] is False
    assert "do not exist" in r["error"]
