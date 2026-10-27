"""Download the bundled dictation model and verify it against the manifest.

Usage: python tools/fetch_dictation_model.py [model-id] [--dest DIR]

Files come from the Hugging Face repo and revision pinned in
web/dictation/models.json and are checked against the SHA-256 recorded there.
A mismatch fails the build.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "web" / "dictation" / "models.json"
DEFAULT_DEST = ROOT / "models" / "dictation"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url) as resp, dest.open("wb") as out:
        while block := resp.read(1 << 20):
            out.write(block)


def fetch(model_id: str | None = None, dest_root: Path = DEFAULT_DEST, downloader=download) -> Path:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    model_id = model_id or manifest["default"]
    if model_id not in manifest["models"]:
        raise SystemExit(f"unknown model '{model_id}' (known: {', '.join(sorted(manifest['models']))})")
    entry = manifest["models"][model_id]
    target = dest_root / entry["dir"]
    target.mkdir(parents=True, exist_ok=True)
    for name, expected in entry["files"].items():
        path = target / name
        if path.is_file() and sha256_of(path) == expected:
            continue
        url = f"https://huggingface.co/{entry['repo']}/resolve/{entry['revision']}/{name}"
        print(f"downloading {name}", file=sys.stderr)
        downloader(url, path)
        actual = sha256_of(path)
        if actual != expected:
            path.unlink()
            raise SystemExit(f"checksum mismatch for {name}: expected {expected}, got {actual}")
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model_id", nargs="?")
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    args = parser.parse_args()
    print(fetch(args.model_id, args.dest))


if __name__ == "__main__":
    main()
