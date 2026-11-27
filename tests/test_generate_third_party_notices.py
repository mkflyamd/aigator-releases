import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "generate_third_party_notices.py"


def _load():
    spec = importlib.util.spec_from_file_location("generate_third_party_notices", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_notices_list_packages_licenses_and_dictation_model(tmp_path, monkeypatch):
    mod = _load()
    monkeypatch.setattr(mod, "runtime_requirements", lambda: ["pytest", "not-installed-on-this-platform"])
    out = tmp_path / "THIRD_PARTY_NOTICES.txt"
    monkeypatch.setattr(sys, "argv", ["generate_third_party_notices.py", str(out)])

    assert mod.main() == 0

    text = out.read_text(encoding="utf-8")
    assert "Apache License, Version 2.0" in text
    assert "\npytest " in text
    assert "not-installed-on-this-platform" not in text
    assert "Dictation model base.en" in text
    assert "LICENSE.electron.txt" in text
    assert "xterm.js (@xterm/xterm) 5.5.0" in text
    assert "Quill 1.3.7" in text
    assert "Front-end libraries under BSD-3-Clause" in text
    assert "Copyright (c) 2021 Adam Shaw" in text


def test_every_vendored_file_is_listed_in_the_notices():
    mod = _load()
    listed = {f for lib in mod.VENDORED for f in lib["files"]}
    on_disk = {p.relative_to(mod.VENDOR_DIR).as_posix() for p in mod.VENDOR_DIR.rglob("*") if p.is_file()}
    assert on_disk == listed
    assert {lib["license"] for lib in mod.VENDORED} <= set(mod.LICENSE_TEXTS)
