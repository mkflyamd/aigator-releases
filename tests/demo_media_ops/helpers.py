import subprocess
from pathlib import Path

import demo_media as dm


def make_video(path: Path, seconds: float, *, color: str = "blue", size: str = "160x90",
               fps: int = 10, audio: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg, _ = dm.find_binaries()
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", f"color=c={color}:s={size}:r={fps}:d={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)
    return path


def approve(pid, segments, intro=None):
    import narration_approval
    flags = {f"intro_{k}": v for k, v in (intro or {}).items()}
    return narration_approval.approve(pid, segments, flags)["approval"]["approval_id"]
