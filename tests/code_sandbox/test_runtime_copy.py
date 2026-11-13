import os

import pytest

from sandbox import runtime_copy


def _tool(folder, name="mytool"):
    folder.mkdir(parents=True)
    exe = folder / (name + (".cmd" if os.name == "nt" else ""))
    exe.write_text("@echo off\n" if os.name == "nt" else "#!/bin/sh\n")
    exe.chmod(0o755)
    return exe


def test_unreadable_tool_folder_is_copied_once_and_reused(tmp_path):
    exe = _tool(tmp_path / "prog")
    root = tmp_path / "root"
    first = runtime_copy.readable_copies("mytool --serve", str(exe.parent), lambda p: False, root)
    assert len(first) == 1 and (first[0] / exe.name).exists()
    (first[0] / "sentinel").write_text("kept")
    second = runtime_copy.readable_copies("mytool --serve", str(exe.parent), lambda p: False, root)
    assert second == first and (first[0] / "sentinel").read_text() == "kept"


def test_readable_tool_is_not_copied(tmp_path):
    exe = _tool(tmp_path / "prog")
    root = tmp_path / "root"
    assert runtime_copy.readable_copies("mytool", str(exe.parent), lambda p: True, root) == []
    assert not root.exists()


def test_unknown_program_is_skipped(tmp_path):
    assert runtime_copy.readable_copies("echo hi", str(tmp_path), lambda p: False, tmp_path / "root") == []


@pytest.mark.parametrize("command,expected", [
    ("cd app && npm run dev", ["cd", "npm", "node"]),
    ("node server.js", ["node"]),
    ("npx vite", ["npx", "node"]),
    ("npm i && npm run dev", ["npm", "node"]),
    ('"python" -m http.server', ["python"]),
])
def test_tool_names(command, expected):
    assert runtime_copy.tool_names(command) == expected


def test_too_large_folder_is_refused(tmp_path, monkeypatch):
    exe = _tool(tmp_path / "prog")
    (exe.parent / "big.bin").write_bytes(b"x" * 10)
    monkeypatch.setattr(runtime_copy, "MAX_COPY_BYTES", 1)
    with pytest.raises(runtime_copy.RuntimeCopyError):
        runtime_copy.readable_copies("mytool", str(exe.parent), lambda p: False, tmp_path / "root")
    assert not (tmp_path / "root").exists() or not any((tmp_path / "root").iterdir())


def test_install_relay_copies_both_files(tmp_path):
    relay = runtime_copy.install_relay(tmp_path / "r")
    assert relay == tmp_path / "r" / "relay.py"
    assert (tmp_path / "r" / "wire.py").exists()
    assert runtime_copy.install_relay(tmp_path / "r") == relay
