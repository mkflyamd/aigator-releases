"""
TTS Pipeline for Gator Demo Recorder (Phase 7).

Generates narration audio via Lemonade Server (kokoro-v1) and merges it
with the screen recording, synced to timeline markers.

Standalone usage:
    python tts_pipeline.py --video recording.mp4 --timeline timeline.json \\
        --narration narration.json --output final.mp4
"""

import subprocess
import json
import math
import sys
import time
import os
import argparse
import shutil
import requests
from pathlib import Path

PAUSE_MAX = 10.0


def _pause_after(seg):
    try:
        v = float(seg.get("pause_after", 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(v) or v <= 0:
        return 0.0
    return min(v, PAUSE_MAX)


def get_ffmpeg_path():
    """Ask the Gator recorder API — it already found ffmpeg at startup."""
    import urllib.request as _ur, json as _json, shutil, glob
    try:
        resp = _ur.urlopen("http://localhost:8003/api/recorder/status", timeout=5)
        data = _json.loads(resp.read())
        p = data.get("ffmpeg_path", "")
        if p and os.path.exists(p):
            return p
    except Exception:
        pass
    # Fallback: PATH
    found = shutil.which("ffmpeg")
    if found:
        return found
    # Fallback: WinGet glob — any version
    if os.name == "nt":
        pattern = os.path.expanduser(
            r"~\AppData\Local\Microsoft\WinGet\Packages\*\*\bin\ffmpeg.exe"
        )
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            return matches[0]
    return "ffmpeg"


def get_ffprobe_path():
    """Ask the Gator recorder API for ffprobe_path — same source of truth as ffmpeg."""
    import json as _json
    import urllib.request as _ur

    try:
        resp = _ur.urlopen("http://localhost:8003/api/recorder/status", timeout=5)
        data = _json.loads(resp.read())
        p = data.get("ffprobe_path", "")
        if p and os.path.exists(p):
            return p
    except Exception:
        pass
    # Fallback: same bin dir as ffmpeg
    ffmpeg = get_ffmpeg_path()
    candidate = Path(ffmpeg).parent / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
    if candidate.exists():
        return str(candidate)
    found = shutil.which("ffprobe")
    return found or "ffprobe"


def get_duration(file_path):
    ffprobe = get_ffprobe_path()
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)],
        capture_output=True, text=True
    )
    stdout = result.stdout.strip()
    if not stdout:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)],
            capture_output=True, text=True
        )
        stdout = result.stdout.strip()
    if not stdout:
        raise ValueError(f"Could not determine duration of {file_path}")
    return float(stdout)


def generate_tts(text, out_path, lemonade_url, model, voice):
    resp = requests.post(
        f"{lemonade_url}/v1/audio/speech",
        json={"model": model, "input": text, "voice": voice},
        timeout=60
    )
    resp.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(resp.content)
    return len(resp.content)


def create_silence(duration_sec, out_path, ffmpeg_path):
    subprocess.run(
        [ffmpeg_path, "-y", "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono",
         "-t", str(duration_sec), "-c:a", "libmp3lame", "-b:a", "64k",
         str(out_path)],
        capture_output=True, check=True
    )


def write_progress(path, approval_id, state, stage, step=0, total=0, message="", error=None):
    if not path:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps({
        "approval_id": approval_id, "state": state, "stage": stage,
        "step": step, "total": total, "message": message, "error": error,
        "updated_at": time.time(),
    }), encoding="utf-8")
    os.replace(tmp, p)


def build_synced_audio(narration, out_dir, lemonade_url, model, voice, on_segment=None):
    """
    Build a single audio track where each segment starts at its start_at timestamp.
    Inserts silence between segments to align with the video timeline.
    """
    ffmpeg = get_ffmpeg_path()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    segments = []
    for i, seg in enumerate(narration):
        tts_path = out_dir / f"tts_seg_{i:02d}.mp3"
        # Accept both 'start_at' (pipeline convention) and 'start' (widget output)
        start_at = seg.get("start_at", seg.get("start", i * 5))
        # Use per-segment voice/speed if present, else fall back to function args
        seg_voice = seg.get("voice", voice)
        seg_model = model
        if on_segment:
            on_segment(i + 1, len(narration))
        print(f"  [TTS {i+1}/{len(narration)}] @{start_at:.1f}s: {seg['text'][:60]}...")
        size = generate_tts(seg["text"], tts_path, lemonade_url, seg_model, seg_voice)
        dur = get_duration(tts_path)
        print(f"    -> {tts_path.name} ({size} bytes, {dur:.1f}s)")
        segments.append({
            "path": tts_path, "start_at": start_at,
            "duration": dur, "pause_after": _pause_after(seg),
        })

    # Build: silence + TTS + pause_silence + silence + TTS + ...
    files_to_concat = []
    current_pos = 0.0

    for i, seg in enumerate(segments):
        gap = seg["start_at"] - current_pos
        if gap > 0.1:
            silence_path = out_dir / f"silence_pre_{i:02d}.mp3"
            create_silence(gap, silence_path, ffmpeg)
            files_to_concat.append(silence_path)
            current_pos += gap

        files_to_concat.append(seg["path"])
        current_pos += seg["duration"]

        if seg["pause_after"] > 0:
            silence_path = out_dir / f"silence_post_{i:02d}.mp3"
            create_silence(seg["pause_after"], silence_path, ffmpeg)
            files_to_concat.append(silence_path)
            current_pos += seg["pause_after"]

    concat_list = out_dir / "concat_list.txt"
    with open(concat_list, "w") as f:
        for fp in files_to_concat:
            f.write(f"file '{fp}'\n")

    full_audio = out_dir / "full_narration_synced.mp3"
    subprocess.run(
        [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-c:a", "libmp3lame", "-b:a", "128k", "-ar", "24000", "-ac", "1",
         str(full_audio)],
        capture_output=True, check=True
    )
    print(f"  Synced audio: {full_audio.name} ({current_pos:.1f}s)")
    return full_audio


_SOUNDTRACK_MIX = (
    "[2:a]volume=0.25[bg];"
    "[1:a][bg]amix=inputs=2:duration=first:dropout_transition=0[aout]"
)


def build_merge_argv(ffmpeg, video_path, audio_path, out_path, soundtrack=None):
    argv = [ffmpeg, "-y", "-i", str(video_path), "-i", str(audio_path)]
    if soundtrack:
        argv += ["-i", str(soundtrack), "-filter_complex", _SOUNDTRACK_MIX,
                 "-map", "0:v:0", "-map", "[aout]"]
    else:
        argv += ["-map", "0:v:0", "-map", "1:a:0"]
    argv += ["-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
             "-shortest", "-movflags", "+faststart", str(out_path)]
    return argv


def merge_audio_video(video_path, audio_path, out_path, soundtrack=None):
    ffmpeg = get_ffmpeg_path()
    video_dur = get_duration(video_path)
    audio_dur = get_duration(audio_path)
    print(f"  Video: {video_dur:.1f}s, Audio: {audio_dur:.1f}s")

    if audio_dur > video_dur:
        ext = audio_dur - video_dur + 0.5
        print(f"  Audio longer — extending video by {ext:.1f}s (hold last frame)")
        temp_video = Path(video_path).parent / "video_extended.mp4"
        subprocess.run(
            [ffmpeg, "-y", "-i", str(video_path),
             "-t", str(audio_dur + 0.5),
             "-vf", f"tpad=stop_mode=clone:stop_duration={ext}",
             "-c:v", "libx264", "-preset", "fast", "-crf", "23",
             "-pix_fmt", "yuv420p", "-an", str(temp_video)],
            capture_output=True, check=True
        )
        video_path = temp_video
    elif video_dur > audio_dur:
        pad = video_dur - audio_dur + 0.5
        print(f"  Video longer — padding audio with {pad:.1f}s silence")
        padded = Path(audio_path).parent / "audio_padded.mp3"
        silence = Path(audio_path).parent / "tail_silence.mp3"
        create_silence(pad, silence, ffmpeg)
        cl = Path(audio_path).parent / "audio_pad_list.txt"
        with open(cl, "w") as f:
            f.write(f"file '{audio_path}'\n")
            f.write(f"file '{silence}'\n")
        subprocess.run(
            [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(cl),
             "-c:a", "libmp3lame", "-b:a", "128k", str(padded)],
            capture_output=True, check=True
        )
        audio_path = padded

    subprocess.run(
        build_merge_argv(ffmpeg, video_path, audio_path, out_path, soundtrack),
        capture_output=True, check=True
    )
    print(f"  Final video: {out_path} ({os.path.getsize(out_path)/(1024*1024):.1f} MB)")


def main():
    parser = argparse.ArgumentParser(description="TTS pipeline for Gator demo")
    parser.add_argument("--video", required=True)
    parser.add_argument("--timeline", required=True)
    parser.add_argument("--narration", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--lemonade-url", default="http://localhost:13305")
    parser.add_argument("--model", default="kokoro-v1")
    parser.add_argument("--voice", default="af_heart")
    parser.add_argument("--work-dir", default=None)
    parser.add_argument("--soundtrack", default=None)
    parser.add_argument("--progress-file", default=None)
    parser.add_argument("--approval-id", default=None)
    args = parser.parse_args()

    def progress(state, stage, step=0, total=0, message="", error=None):
        write_progress(args.progress_file, args.approval_id, state, stage, step, total, message, error)

    stage = "tts"
    try:
        work_dir = Path(args.work_dir or Path(args.video).parent / "tts_work")
        work_dir.mkdir(parents=True, exist_ok=True)

        with open(args.timeline) as f:
            timeline = json.load(f)
        with open(args.narration) as f:
            narration = json.load(f)
        total = len(narration)

        print("=" * 60)
        print("  TTS PIPELINE — Synced Narration")
        print("=" * 60)

        def on_segment(step, count):
            progress("running", "tts", step, count, f"Generating speech {step} of {count}")

        print(f"\n[1/3] Generating TTS segments ({total})...")
        audio = build_synced_audio(
            narration, work_dir, args.lemonade_url, args.model, args.voice, on_segment=on_segment
        )

        stage = "merge"
        progress("running", "merge", total, total, "Merging audio and video")
        print(f"\n[2/3] Merging audio with video...")
        merge_audio_video(args.video, audio, args.output, soundtrack=args.soundtrack)

        progress("done", "done", total, total, "Done")
        print(f"\n[3/3] Done! Final: {args.output}")
    except Exception as exc:
        progress("failed", stage, message="Generation failed", error=str(exc))
        raise


if __name__ == "__main__":
    main()
