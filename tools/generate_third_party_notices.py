"""Write THIRD_PARTY_NOTICES.txt for the bundled backend.

Usage: python tools/generate_third_party_notices.py [output-file]

Lists every runtime Python dependency from uv.lock that is installed in the
current environment, with its version, declared license and the license / notice
files shipped in its distribution, followed by the bundled dictation model and the
front-end libraries vendored under web/static/vendor.
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
VENDOR_DIR = ROOT / "web" / "static" / "vendor"

# Versions and licenses come from the upstream npm package metadata; each file listed
# is byte-identical to the file of that name in the package tarball, except the
# floating-ui bundle (jsDelivr combination of the two packages named in its header).
VENDORED = [
    {
        "name": "xterm.js (@xterm/xterm)",
        "version": "5.5.0",
        "license": "MIT",
        "copyright": [
            "Copyright (c) 2017-2019, The xterm.js authors (https://github.com/xtermjs/xterm.js)",
            "Copyright (c) 2014-2016, SourceLair Private Company (https://www.sourcelair.com)",
            "Copyright (c) 2012-2013, Christopher Jeffrey (https://github.com/chjj/)",
        ],
        "files": ["xterm/xterm.js", "xterm/xterm.css"],
    },
    {
        "name": "xterm.js fit addon (@xterm/addon-fit)",
        "version": "0.10.0 (the file is identical in 0.9.0)",
        "license": "MIT",
        "copyright": ["Copyright (c) 2019, The xterm.js authors (https://github.com/xtermjs/xterm.js)"],
        "files": ["xterm/addon-fit.js"],
    },
    {
        "name": "Mermaid",
        "version": "11.17.2",
        "license": "MIT",
        "copyright": ["Copyright (c) 2014 - 2022 Knut Sveidqvist"],
        "files": ["mermaid/mermaid.min.js"],
        "note": "The bundle embeds DOMPurify 3.4.12 (c) Cure53 and other contributors, "
        "released under MPL-2.0 OR Apache-2.0 (https://github.com/cure53/DOMPurify).",
    },
    {
        "name": "Quill",
        "version": "1.3.7",
        "license": "BSD-3-Clause",
        "copyright": ["Copyright (c) 2014, Jason Chen", "Copyright (c) 2013, salesforce.com"],
        "files": ["quill.min.js", "quill.snow.css"],
    },
    {
        "name": "FullCalendar",
        "version": "6.1.17",
        "license": "MIT",
        "copyright": ["Copyright (c) 2021 Adam Shaw"],
        "files": ["fullcalendar.min.js"],
    },
    {
        "name": "Floating UI (@floating-ui/core and @floating-ui/dom)",
        "version": "core 1.6.8, dom 1.6.12",
        "license": "MIT",
        "copyright": ["Copyright (c) 2021-present Floating UI contributors"],
        "files": ["floating-ui.dom.umd.min.js"],
    },
]

MIT_TEXT = """Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE."""

BSD3_TEXT = """All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:

1. Redistributions of source code must retain the above copyright
notice, this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright
notice, this list of conditions and the following disclaimer in the
documentation and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
contributors may be used to endorse or promote products derived from
this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE."""

LICENSE_TEXTS = {"MIT": MIT_TEXT, "BSD-3-Clause": BSD3_TEXT}


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


def vendored_section() -> str:
    parts = []
    for lib in VENDORED:
        lines = [f"{RULE}\n{lib['name']} {lib['version']}", f"License: {lib['license']}", f"Files: {', '.join(lib['files'])}"]
        if lib.get("note"):
            lines.append(lib["note"])
        parts.append("\n".join(lines) + "\n")
    for license_id in sorted({lib["license"] for lib in VENDORED}):
        notices = "\n".join(c for lib in VENDORED if lib["license"] == license_id for c in lib["copyright"])
        separator = "\n\n" if license_id == "MIT" else "\n"
        parts.append(f"{RULE}\nFront-end libraries under {license_id}\n\n{notices}{separator}{LICENSE_TEXTS[license_id]}\n")
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
        f"{packages}\n{model_section()}\n{vendored_section()}"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {out} ({count} Python packages)")
    return 0 if count else 1


if __name__ == "__main__":
    sys.exit(main())
