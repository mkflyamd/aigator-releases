"""Central scrubber for text that is persisted to logs and telemetry."""
from __future__ import annotations

import re
from pathlib import Path

_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
_KEY_VALUE = re.compile(
    r"""(?ix)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|passwd)
        (["']?\s*[:=]\s*["']?)([^\s"',&;]+)"""
)
_USER_DIR = re.compile(r"(?i)((?:[A-Za-z]:)?[\\/](?:Users|home)[\\/])[^\\/\s\"']+")


def sanitize(text: str | None) -> str | None:
    if not text:
        return text
    home = str(Path.home())
    for variant in {home, home.replace("\\", "/")}:
        text = text.replace(variant, "~")
    text = _USER_DIR.sub(r"\1<user>", text)
    text = _BEARER.sub(lambda m: f"{m.group(1)} [redacted]", text)
    return _KEY_VALUE.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", text)
