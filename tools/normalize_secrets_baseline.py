#!/usr/bin/env python3
"""Normalize .secrets.baseline for cross-platform compatibility.

detect-secrets stores file paths in the baseline using the OS-native separator.
On Windows this produces backslash paths (``docs\\gateway-setup.md``); on Linux
CI the hook rewrites them to forward slashes and sees a diff, failing the
quality gate.

This script normalizes all paths in the baseline to forward slashes and ensures
LF line endings, so the committed baseline matches what CI on Linux produces.

Usage:
    uv run python tools/normalize_secrets_baseline.py          # in-place
    uv run python tools/normalize_secrets_baseline.py --check   # exit 1 if dirty
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / ".secrets.baseline"


def normalize(data: dict) -> dict:
    """Recursively normalize ``filename`` fields and dict keys to forward slashes."""
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            norm_key = key.replace("\\", "/")
            if key == "filename" and isinstance(value, str):
                result[norm_key] = value.replace("\\", "/")
            else:
                result[norm_key] = normalize(value)
        return result
    if isinstance(data, list):
        return [normalize(item) for item in data]
    return data


def main() -> int:
    if not BASELINE.exists():
        print(f".secrets.baseline not found at {BASELINE}", file=sys.stderr)
        return 1

    # The baseline may be UTF-16 LE (Windows default), UTF-8 with BOM, or UTF-8.
    # Read as bytes, detect encoding, decode, then re-serialize as UTF-8 (no BOM).
    raw_bytes = BASELINE.read_bytes()
    if raw_bytes[:2] == b"\xff\xfe":
        raw = raw_bytes.decode("utf-16-le")
    elif raw_bytes[:3] == b"\xef\xbb\xbf":
        raw = raw_bytes[3:].decode("utf-8")
    else:
        raw = raw_bytes.decode("utf-8")

    # Strip any remaining BOM character (U+FEFF) that decode may have left.
    if raw and raw[0] == "\ufeff":
        raw = raw[1:]
    original = raw

    # Parse, normalize paths, re-serialize with sorted keys + LF endings.
    data = json.loads(raw)
    normalized = normalize(data)
    output = json.dumps(normalized, indent=2, sort_keys=True, ensure_ascii=False)
    output += "\n"  # trailing newline

    if "--check" in sys.argv:
        if output != original:
            print(
                "baseline is not normalized — run "
                "`uv run python tools/normalize_secrets_baseline.py` and commit",
                file=sys.stderr,
            )
            return 1
        print("baseline is normalized")
        return 0

    BASELINE.write_text(output, encoding="utf-8", newline="\n")
    if output != original:
        print("baseline normalized (paths -> forward slashes, LF endings)")
    else:
        print("baseline already normalized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
