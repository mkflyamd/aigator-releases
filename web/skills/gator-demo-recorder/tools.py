"""Gator Demo Recorder tools: probe-backed media inspection, editing and narration merge."""

import logging
import subprocess

import demo_media

SKILL_ID = "gator-demo-recorder"

_PROJECT = {
    "type": "string",
    "description": "Demo project id (optional; defaults to the active project).",
}


def _call(fn, *args, **kwargs) -> dict:
    try:
        return fn(*args, **kwargs)
    except demo_media.MediaError as exc:
        return exc.to_result()
    except subprocess.TimeoutExpired:
        return {"error": "ffmpeg_timeout", "message": "The media operation timed out."}
    except Exception as exc:
        logging.exception("demo media tool failed")
        return {"error": "media_op_failed", "message": str(exc)}


def _opt(value):
    return value if value not in ("", None) else None


def _tool_demo_media_manifest(project_id: str = "") -> dict:
    return _call(demo_media.manifest, _opt(project_id))


def _tool_demo_inspect_frames(source: str, times_sec: list, project_id: str = "") -> dict:
    return _call(demo_media.inspect_frames, _opt(project_id), source, times_sec)


def _tool_demo_replace_interval(start_sec: float, end_sec: float, insert_source: str,
                                insert_start_sec: float = 0, base: str = "", project_id: str = "") -> dict:
    return _call(demo_media.replace_interval, _opt(project_id), start_sec, end_sec, insert_source,
                 insert_start_sec, _opt(base))


def _tool_demo_append_clip(clip: str, clip_start_sec: float = 0, clip_end_sec: float = None,
                           base: str = "", project_id: str = "") -> dict:
    return _call(demo_media.append_clip, _opt(project_id), clip, clip_start_sec, clip_end_sec, _opt(base))


def _tool_demo_cut_intervals(intervals: list, base: str = "", project_id: str = "") -> dict:
    return _call(demo_media.cut_intervals, _opt(project_id), intervals, _opt(base))


def _tool_demo_speed_interval(start_sec: float, end_sec: float, speed: float,
                              base: str = "", project_id: str = "") -> dict:
    return _call(demo_media.speed_interval, _opt(project_id), start_sec, end_sec, speed, _opt(base))


def _tool_demo_merge_narration(intro_mode: str = "", intro_duration_sec: float = None, intro_title: str = "",
                               voice: str = "", video: str = "", approval_id: str = "",
                               project_id: str = "") -> dict:
    return _call(demo_media.merge_narration, _opt(project_id), _opt(video), _opt(intro_mode),
                 intro_duration_sec, _opt(intro_title), _opt(voice), _opt(approval_id))


TOOL_DEFS = [
    {
        "name": "demo_media_manifest",
        "description": (
            "List the real media files in a demo project (source, work, final) with ffprobe-measured "
            "duration, size and streams. Call this before claiming anything about a video's length or contents."
        ),
        "input_schema": {"type": "object", "properties": {"project_id": _PROJECT}, "required": []},
    },
    {
        "name": "demo_inspect_frames",
        "description": (
            "Extract still frames at the given seconds from a project video and save them as PNGs. Times "
            "outside the video's real duration are rejected with the real duration. Max 8 frames per call. "
            "Pass the returned frame paths to describe_images. Only describe what the frames show."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Project-relative video path, e.g. source/recording.mp4"},
                "times_sec": {"type": "array", "items": {"type": "number"}, "description": "Seconds to sample."},
                "project_id": _PROJECT,
            },
            "required": ["source", "times_sec"],
        },
    },
    {
        "name": "demo_replace_interval",
        "description": (
            "Replace [start_sec, end_sec) of the silent recording with the same length from another project "
            "video. Duration is unchanged so narration timing stays valid. Rejects out-of-range times. "
            "The result lists the exact source interval used; quote it, never invent one."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_sec": {"type": "number", "description": "Start of the interval to replace."},
                "end_sec": {"type": "number", "description": "End of the interval to replace."},
                "insert_source": {"type": "string", "description": "Project-relative path of the replacement video."},
                "insert_start_sec": {"type": "number", "description": "Where in the replacement video to start (default 0)."},
                "base": {"type": "string", "description": "Project-relative base video (default: the current recording)."},
                "project_id": _PROJECT,
            },
            "required": ["start_sec", "end_sec", "insert_source"],
        },
    },
    {
        "name": "demo_append_clip",
        "description": (
            "Append a clip (or part of it) to the end of the silent recording. The result gives the new "
            "duration and the exact appended interval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "clip": {"type": "string", "description": "Project-relative path of the clip to append."},
                "clip_start_sec": {"type": "number", "description": "Start inside the clip (default 0)."},
                "clip_end_sec": {"type": "number", "description": "End inside the clip (default: its end)."},
                "base": {"type": "string", "description": "Project-relative base video (default: the current recording)."},
                "project_id": _PROJECT,
            },
            "required": ["clip"],
        },
    },
    {
        "name": "demo_cut_intervals",
        "description": (
            "Remove one or more [start_sec, end_sec) ranges from the silent recording and join the rest, so "
            "the video gets SHORTER. Use it to reach a target length or drop dead time such as loading waits. "
            "The result gives the new duration, removed_sec and a time_map: for every kept piece, its old and "
            "new time range. Narration start times were written against the OLD timeline, so after a cut move "
            "each start_at through time_map and have the user approve the narration again; a narration whose "
            "moment was cut must be reworded or dropped. Quote cut_intervals_sec and output.duration_sec exactly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "intervals": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                    "description": "Ranges to remove, as [start_sec, end_sec] pairs on the current timeline. Must not overlap.",
                },
                "base": {"type": "string", "description": "Project-relative base video (default: the current recording)."},
                "project_id": _PROJECT,
            },
            "required": ["intervals"],
        },
    },
    {
        "name": "demo_speed_interval",
        "description": (
            "Play [start_sec, end_sec) of the silent recording faster (speed 1.25-16) instead of removing it, "
            "so a loading wait reads as fast-forward rather than a jump cut. The video gets shorter by "
            "saved_sec. The result has the same time_map as demo_cut_intervals; apply it to the narration "
            "start times and have the user approve the narration again."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_sec": {"type": "number", "description": "Start of the interval to speed up."},
                "end_sec": {"type": "number", "description": "End of the interval to speed up."},
                "speed": {"type": "number", "description": "Speed factor, 1.25 to 16 (4 = four times faster)."},
                "base": {"type": "string", "description": "Project-relative base video (default: the current recording)."},
                "project_id": _PROJECT,
            },
            "required": ["start_sec", "end_sec", "speed"],
        },
    },
    {
        "name": "demo_merge_narration",
        "description": (
            "Generate the approved narration with TTS and merge it into the recording, producing the final "
            "MP4. If narration is longer than the video the last frame is held and the result reports how "
            "much it was extended. intro_mode 'hold' freezes the first frame; 'card' shows a title card; both "
            "shift narration by the intro length. Omit intro_mode to use the approved narration's intro "
            "choice. Fails with the measured durations if audio and video do not line up."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "intro_mode": {"type": "string", "enum": ["none", "hold", "card"],
                               "description": "Intro style (optional)."},
                "intro_duration_sec": {"type": "number", "description": "Intro length, 0.5-10 (default 2)."},
                "intro_title": {"type": "string", "description": "Title text for 'card' (max 80 chars)."},
                "voice": {"type": "string", "description": "TTS voice id (optional)."},
                "video": {"type": "string", "description": "Project-relative video (default: the current recording)."},
                "approval_id": {"type": "string", "description": "Approval id from the trigger message; a newer approval is refused."},
                "project_id": _PROJECT,
            },
            "required": [],
        },
    },
]

TOOL_STATUS = {
    "demo_media_manifest": "Checking demo media...",
    "demo_inspect_frames": "Extracting video frames...",
    "demo_replace_interval": "Replacing video section...",
    "demo_append_clip": "Appending clip...",
    "demo_cut_intervals": "Cutting video sections...",
    "demo_speed_interval": "Speeding up video section...",
    "demo_merge_narration": "Generating narration and merging video...",
}

TOOL_HANDLERS = {
    "demo_media_manifest": _tool_demo_media_manifest,
    "demo_inspect_frames": _tool_demo_inspect_frames,
    "demo_replace_interval": _tool_demo_replace_interval,
    "demo_append_clip": _tool_demo_append_clip,
    "demo_cut_intervals": _tool_demo_cut_intervals,
    "demo_speed_interval": _tool_demo_speed_interval,
    "demo_merge_narration": _tool_demo_merge_narration,
}
