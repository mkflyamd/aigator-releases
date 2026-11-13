import os

import pytest

from sandbox import runtime_copy


def _tool(folder, name="mytool"):
    folder.mkdir(parents=True, exist_ok=True)
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
    (r'"C:\Program Files\nodejs\node.exe" x', [r"C:\Program Files\nodejs\node.exe"]),
    ("node server.js 2>&1", ["node"]),
    ("node a.js 2>&1 && npm run dev", ["node", "npm"]),
    ("NODE_ENV=production node server.js", ["node"]),
    ('echo "a && b" && node x', ["echo", "node"]),
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


def test_too_large_folder_leaves_no_copy(tmp_path, monkeypatch):
    exe = _tool(tmp_path / "prog")
    (exe.parent / "big.bin").write_bytes(b"x" * 10)
    monkeypatch.setattr(runtime_copy, "MAX_COPY_BYTES", 1)
    root = tmp_path / "root"
    with pytest.raises(runtime_copy.RuntimeCopyError):
        runtime_copy.readable_copies("mytool", str(exe.parent), lambda p: False, root)
    assert not root.exists() or list(root.iterdir()) == []


def test_install_relay_copies_both_files(tmp_path):
    relay = runtime_copy.install_relay(tmp_path / "r")
    assert relay == tmp_path / "r" / "relay.py"
    assert (tmp_path / "r" / "wire.py").exists()
    assert runtime_copy.install_relay(tmp_path / "r") == relay


def _link_dir(link, target):
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        import _winapi
        try:
            _winapi.CreateJunction(str(target), str(link))
            return
        except OSError:
            pass
    pytest.skip("cannot create a symlink or junction here")


def test_quoted_path_with_spaces_is_one_token_and_not_copied(tmp_path):
    exe = _tool(tmp_path / "Program Files" / "nodejs", "node")
    command = f'"{exe}" server.js'
    assert runtime_copy.tool_names(command)[0] == str(exe)
    assert runtime_copy.readable_copies(command, str(tmp_path / "empty"), lambda p: False, tmp_path / "root") == []
    assert not (tmp_path / "root").exists()


def test_path_like_programs_are_never_copied(tmp_path):
    exe = _tool(tmp_path / "prog")
    (tmp_path / "empty").mkdir()
    root = tmp_path / "root"
    rel = os.path.relpath(exe, tmp_path / "empty")
    for command in (str(exe), f"./{exe.name}", rel, f"..{os.sep}prog{os.sep}{exe.name}", f"{exe.parent}{os.sep}{exe.name} x"):
        assert runtime_copy.readable_copies(command, str(tmp_path / "empty"), lambda p: False, root) == []
    assert not root.exists()


def test_program_found_only_in_cwd_is_skipped(tmp_path, monkeypatch):
    cwd = tmp_path / "cwd"
    _tool(cwd, "mytool")
    (tmp_path / "other").mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.delenv("NoDefaultCurrentDirectoryInExePath", raising=False)
    root = tmp_path / "root"
    assert runtime_copy.readable_copies("mytool", str(tmp_path / "other"), lambda p: False, root) == []
    assert not root.exists()


def test_folder_with_a_link_is_refused_without_creating_anything(tmp_path):
    exe = _tool(tmp_path / "prog")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    (exe.parent / "lib").mkdir()
    _link_dir(exe.parent / "lib" / "linked", outside)
    root = tmp_path / "root"
    with pytest.raises(runtime_copy.RuntimeCopyError):
        runtime_copy.readable_copies("mytool", str(exe.parent), lambda p: False, root)
    assert not root.exists()


def test_npm_and_node_in_one_folder_make_one_copy(tmp_path):
    npm = _tool(tmp_path / "nodejs", "npm")
    _tool(tmp_path / "nodejs", "node")
    root = tmp_path / "root"
    copies = runtime_copy.readable_copies("npm run dev", str(npm.parent), lambda p: False, root)
    assert len(copies) == 1 and len(list(root.iterdir())) == 1


def test_install_relay_overwrites_a_stale_file(tmp_path):
    (tmp_path / "r").mkdir()
    (tmp_path / "r" / "relay.py").write_text("stale")
    relay = runtime_copy.install_relay(tmp_path / "r")
    assert relay.read_text() != "stale" and "stale" not in relay.read_text()
