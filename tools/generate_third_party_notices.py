"""Write THIRD_PARTY_NOTICES.txt for the bundled backend.

Usage: python tools/generate_third_party_notices.py [output-file]

Lists every runtime Python dependency from uv.lock that is installed in the
current environment, with its version, declared license and the license / notice
files shipped in its distribution, followed by the bundled dictation model.
Electron and Chromium license files are added by electron-builder.
"""
from __future__ import annotations

import json
import subprocess
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "web" / "dictation" / "models.json"
DEFAULT_OUT = ROOT / "dist" / "THIRD_PARTY_NOTICES.txt"
LICENSE_FILE_PREFIXES = ("LICENSE", "LICENCE", "COPYING", "NOTICE")
RULE = "=" * 78


def runtime_requirements() -> list[str]:
    out = subprocess.run(
        ["uv", "export", "--locked", "--no-dev", "--no-emit-project", "--no-hashes", "--no-header"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    names = []
    for line in out.splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "-")):
            names.append(line.split("==", 1)[0].split(";", 1)[0].strip())
    return sorted(set(names), key=str.lower)


def declared_license(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    value = meta.get("License-Expression") or ""
    if not value:
        text = (meta.get("License") or "").strip()
        value = text if text and "\n" not in text and len(text) < 80 else ""
    if not value:
        classifiers = [c.rsplit("::", 1)[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
        value = "; ".join(classifiers)
    return value or "see license text below"


def license_files(dist: metadata.Distribution) -> list[tuple[str, str]]:
    found = []
    for f in dist.files or []:
        parts = str(f).replace("\\", "/").split("/")
        in_metadata = parts[0].endswith((".dist-info", ".egg-info"))
        if f.name.upper().startswith(LICENSE_FILE_PREFIXES) and (in_metadata or len(parts) == 2):
            try:
                found.append((f.name, Path(dist.locate_file(f)).read_text(encoding="utf-8", errors="replace").strip()))
            except OSError:
                continue
    return found


def python_section() -> tuple[str, int]:
    parts = []
    count = 0
    for name in runtime_requirements():
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue  # requirement for another platform
        count += 1
        parts.append(f"{RULE}\n{dist.metadata['Name']} {dist.version}\nLicense: {declared_license(dist)}\n")
        for fname, text in license_files(dist):
            parts.append(f"--- {fname} ---\n{text}\n")
    return "\n".join(parts), count


def model_section() -> str:
    data = json.loads(MODELS.read_text(encoding="utf-8"))
    parts = []
    for model_id, model in data["models"].items():
        parts.append(
            f"{RULE}\nDictation model {model_id} ({model['engine']})\n"
            f"Source: https://huggingface.co/{model['repo']} (revision {model['revision']})\n"
            f"License: {model['license']}\n"
        )
    return "\n".join(parts)


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    packages, count = python_section()
    text = (
        "AI Gator third-party notices\n\n"
        "AI Gator itself is licensed under the Apache License, Version 2.0 (see LICENSE).\n"
        "It bundles the software below, each under its own license.\n"
        "Electron and Chromium license files are included in the application directory as\n"
        "LICENSE.electron.txt and LICENSES.chromium.html.\n\n"
        f"{packages}\n{model_section()}"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {out} ({count} Python packages)")
    return 0 if count else 1


if __name__ == "__main__":
    sys.exit(main())
