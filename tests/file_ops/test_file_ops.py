import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "web"))

import pytest
import base64


# ── read_file ────────────────────────────────────────────────────────────────

def test_read_file_text(tmp_path):
    from skills.file_ops.tools import _tool_read_file
    f = tmp_path / "hello.txt"
    f.write_text("hello world", encoding="utf-8")
    result = _tool_read_file(path=str(f))
    assert result.get("error") is None
    assert result["content"] == "hello world"
    assert result["size_bytes"] == len("hello world")


def test_read_file_binary(tmp_path):
    from skills.file_ops.tools import _tool_read_file
    f = tmp_path / "img.bin"
    f.write_bytes(b"\x89PNG\r\n\x1a\n")
    result = _tool_read_file(path=str(f))
    assert result.get("error") is None
    assert result.get("binary") is True
    assert result.get("base64") is not None
    assert base64.b64decode(result["base64"])  # decodeable


def test_read_file_missing(tmp_path):
    from skills.file_ops.tools import _tool_read_file
    result = _tool_read_file(path=str(tmp_path / "nope.txt"))
    assert "error" in result


def test_read_file_too_large(tmp_path, monkeypatch):
    import skills.file_ops.tools as fo_mod
    monkeypatch.setattr(fo_mod, "_MAX_READ_BYTES", 10)
    from skills.file_ops.tools import _tool_read_file
    f = tmp_path / "big.txt"
    f.write_text("x" * 100, encoding="utf-8")
    result = _tool_read_file(path=str(f))
    assert "error" in result
    assert "too large" in result["error"].lower()


# ── write_file ───────────────────────────────────────────────────────────────

def test_write_file_creates_file(tmp_path):
    from skills.file_ops.tools import _tool_write_file
    dest = tmp_path / "out.txt"
    result = _tool_write_file(path=str(dest), content="hello")
    assert result["ok"] is True
    assert dest.read_text() == "hello"


def test_write_file_creates_parent_dirs(tmp_path):
    from skills.file_ops.tools import _tool_write_file
    dest = tmp_path / "a" / "b" / "c.txt"
    result = _tool_write_file(path=str(dest), content="data")
    assert result["ok"] is True
    assert dest.exists()


def test_write_file_overwrites(tmp_path):
    from skills.file_ops.tools import _tool_write_file
    dest = tmp_path / "x.txt"
    dest.write_text("old")
    result = _tool_write_file(path=str(dest), content="new")
    assert result["ok"] is True
    assert dest.read_text() == "new"


# ── list_dir ─────────────────────────────────────────────────────────────────

def test_list_dir_returns_entries(tmp_path):
    from skills.file_ops.tools import _tool_list_dir
    (tmp_path / "file.txt").write_text("x")
    (tmp_path / "subdir").mkdir()
    result = _tool_list_dir(path=str(tmp_path))
    assert result.get("error") is None
    names = [e["name"] for e in result["entries"]]
    assert "file.txt" in names
    assert "subdir" in names


def test_list_dir_dirs_first(tmp_path):
    from skills.file_ops.tools import _tool_list_dir
    (tmp_path / "afile.txt").write_text("x")
    (tmp_path / "bdir").mkdir()
    result = _tool_list_dir(path=str(tmp_path))
    types = [e["type"] for e in result["entries"]]
    assert types[0] == "dir"


def test_list_dir_missing_path(tmp_path):
    from skills.file_ops.tools import _tool_list_dir
    result = _tool_list_dir(path=str(tmp_path / "nope"))
    assert "error" in result


# ── glob_files ───────────────────────────────────────────────────────────────

def test_glob_files_finds_matches(tmp_path):
    from skills.file_ops.tools import _tool_glob_files
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.py").write_text("")
    (tmp_path / "c.txt").write_text("")
    result = _tool_glob_files(pattern="*.py", base_path=str(tmp_path))
    assert result["count"] == 2
    assert all(m.endswith(".py") for m in result["matches"])


def test_glob_files_truncates(tmp_path, monkeypatch):
    import skills.file_ops.tools as fo_mod
    monkeypatch.setattr(fo_mod, "_MAX_GLOB", 5)
    from skills.file_ops.tools import _tool_glob_files
    for i in range(10):
        (tmp_path / f"f{i}.txt").write_text("")
    result = _tool_glob_files(pattern="*.txt", base_path=str(tmp_path))
    assert result.get("truncated") is True
    assert len(result["matches"]) == 5


# ── grep_files ───────────────────────────────────────────────────────────────

def test_grep_files_finds_pattern(tmp_path):
    from skills.file_ops.tools import _tool_grep_files
    (tmp_path / "a.py").write_text("def hello():\n    pass\n")
    (tmp_path / "b.py").write_text("x = 1\n")
    result = _tool_grep_files(pattern="def hello", path=str(tmp_path))
    assert result["count"] == 1
    assert result["matches"][0]["line_number"] == 1


def test_grep_files_no_match(tmp_path):
    from skills.file_ops.tools import _tool_grep_files
    (tmp_path / "a.py").write_text("x = 1\n")
    result = _tool_grep_files(pattern="ZZZNOMATCH", path=str(tmp_path))
    assert result["count"] == 0
    assert result.get("error") is None


# ── delete_file ──────────────────────────────────────────────────────────────
# Deletion is intentionally not supported via any skill — users must delete manually.
# The implementation is commented out in tools.py; these tests verify it stays disabled.

# def test_delete_file_requires_confirmation(tmp_path): ...   # disabled with feature
# def test_delete_file_confirmed_deletes(tmp_path): ...        # disabled with feature
# def test_delete_file_missing_returns_error(tmp_path): ...    # disabled with feature
# def test_delete_file_directory_rejected(tmp_path): ...       # disabled with feature

def test_delete_file_not_in_tool_defs():
    """delete_file must not be exposed as a callable tool."""
    import skills.file_ops.tools as mod
    tool_names = [t["name"] for t in mod.TOOL_DEFS]
    assert "delete_file" not in tool_names

def test_delete_file_not_in_tool_handlers():
    """delete_file must not be registered in TOOL_HANDLERS."""
    import skills.file_ops.tools as mod
    assert "delete_file" not in mod.TOOL_HANDLERS


def test_tool_contract():
    import skills.file_ops.tools as mod
    from skills._skill_utils import validate_tool_contract
    assert validate_tool_contract(mod, "file_ops") is True
