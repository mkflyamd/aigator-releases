import os
import sys

import pytest

import secure_store
from sandbox.paths import is_secrets_path
from skills.file_ops import tools as fo

WIN = sys.platform == "win32"
BLOB = b"FAKE:aigator-fake-api-key"
PROTECTED = "That location is protected."


@pytest.fixture
def secrets(tmp_path):
    root = secure_store._root()
    root.mkdir(parents=True)
    (root / "sandbox~saved-permissions.bin").write_bytes(BLOB)
    return root


def _swap_case(text: str) -> str:
    return text.swapcase()


def _link(tmp_path, target):
    link = tmp_path / "link"
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        if not WIN:
            pytest.skip("cannot create symlinks here")
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    return link


def _spellings(tmp_path, secrets):
    out = {
        "direct": str(secrets),
        "traversal": str(secrets.parent / "outputs" / ".." / "secrets"),
        "link": str(_link(tmp_path, secrets)),
    }
    if WIN:
        out["case"] = _swap_case(str(secrets))
        out["verbatim"] = "\\\\?\\" + str(secrets)
        out["trailing_dot"] = str(secrets) + "."
    return out


@pytest.mark.parametrize("kind", ["direct", "traversal", "link", "case", "verbatim", "trailing_dot"])
def test_is_secrets_path_catches_spellings(tmp_path, secrets, kind):
    spell = _spellings(tmp_path, secrets)
    if kind not in spell:
        pytest.skip("Windows-only spelling")
    assert is_secrets_path(spell[kind])
    assert is_secrets_path(os.path.join(spell[kind], "sandbox~saved-permissions.bin"))
    assert is_secrets_path(os.path.join(spell[kind], "new.bin"))


def test_is_secrets_path_allows_outside(tmp_path, secrets):
    assert not is_secrets_path(tmp_path / "work" / "a.txt")
    assert not is_secrets_path(secrets.parent / "outputs" / "a.txt")
    assert not is_secrets_path(str(secrets) + "-other")


@pytest.mark.skipif(not WIN, reason="Windows short names")
def test_is_secrets_path_short_name(secrets):
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetShortPathNameW(str(secrets), buf, 1024)
    if not n or buf.value.lower() == str(secrets).lower():
        pytest.skip("no 8.3 name on this volume")
    assert is_secrets_path(os.path.join(buf.value, "x.bin"))


@pytest.mark.skipif(not WIN, reason="Windows device and UNC spellings")
def test_is_secrets_path_device_and_unc_spellings(secrets):
    import ctypes
    buf = ctypes.create_unicode_buffer(512)
    ctypes.windll.kernel32.QueryDosDeviceW(str(secrets)[:2], buf, 512)
    rest = str(secrets)[2:]
    spellings = ["\\\\?\\GLOBALROOT" + buf.value + rest, "\\\\localhost\\" + str(secrets)[0] + "$" + rest]
    checked = 0
    for s in spellings:
        if os.path.isdir(s):
            checked += 1
            assert is_secrets_path(s + "\\new.bin"), s
    if not checked:
        pytest.skip("no device or admin-share spelling reachable")


@pytest.mark.skipif(not WIN, reason="Windows alternate data streams")
def test_is_secrets_path_refuses_stream_in_folder_part(secrets):
    assert is_secrets_path(str(secrets) + "::$INDEX_ALLOCATION\\x.bin")
    assert is_secrets_path(str(secrets / "sandbox~saved-permissions.bin") + "::$DATA")


def test_is_secrets_path_fails_closed(monkeypatch):
    monkeypatch.setattr(secure_store, "_root", lambda: (_ for _ in ()).throw(OSError("boom")))
    assert is_secrets_path("anything.txt")


def _snapshot(root):
    return {p.name: p.read_bytes() for p in root.iterdir()}


@pytest.mark.parametrize("kind", ["direct", "traversal", "link", "case", "verbatim"])
def test_file_ops_refuse_secrets(tmp_path, secrets, kind):
    spell = _spellings(tmp_path, secrets)
    if kind not in spell:
        pytest.skip("Windows-only spelling")
    folder = spell[kind]
    blob = os.path.join(folder, "sandbox~saved-permissions.bin")
    before = _snapshot(secrets)
    results = [
        fo._tool_read_file(path=blob),
        fo._tool_write_file(path=blob, content="forged"),
        fo._tool_write_file(path=os.path.join(folder, "new.bin"), content="forged"),
        fo._tool_edit_file(path=blob, old_str="FAKE", new_str="EVIL"),
        fo._tool_list_dir(path=folder),
        fo._tool_grep_files(pattern="FAKE", path=folder),
        fo._tool_grep_files(pattern="FAKE", path=blob),
    ]
    for r in results:
        assert r.get("error") == PROTECTED, r
        assert "content" not in r and "entries" not in r and not r.get("matches")
    assert _snapshot(secrets) == before


def test_grep_and_glob_skip_secrets_under_a_parent(tmp_path, secrets):
    (tmp_path / "home" / "notes.txt").write_text("FAKE here", encoding="utf-8")
    home = str(tmp_path / "home")
    grep = fo._tool_grep_files(pattern="FAKE", path=home)
    assert [m["file"] for m in grep["matches"]] == [str(tmp_path / "home" / "notes.txt")]
    glob = fo._tool_glob_files(pattern="*", base_path=home)
    assert not any(is_secrets_path(m) for m in glob["matches"])
    assert str(tmp_path / "home" / "notes.txt") in glob["matches"]


def test_file_ops_still_work_outside(tmp_path, secrets):
    f = tmp_path / "work" / "a.txt"
    assert fo._tool_write_file(path=str(f), content="hello")["ok"]
    assert fo._tool_edit_file(path=str(f), old_str="hello", new_str="bye")["ok"]
    assert fo._tool_read_file(path=str(f))["content"] == "bye"
    assert fo._tool_list_dir(path=str(f.parent))["count"] == 1


def _office_cases(folder):
    from skills.docx import tools as dx
    from skills.excel import tools as xl
    from skills.ppt import tools as pp
    from skills.onedrive import tools as od
    target = os.path.join(folder, "sandbox~saved-permissions.bin")
    return [
        (dx.TOOL_HANDLERS["create_docx"], {"file_path": target, "content": []}),
        (dx.TOOL_HANDLERS["read_docx"], {"file_path": target}),
        (xl.TOOL_HANDLERS["create_excel"], {"file_path": target, "sheets": []}),
        (xl.TOOL_HANDLERS["read_excel"], {"file_path": target, "cell": "A1"}),
        (pp.TOOL_HANDLERS["create_pptx"], {"file_path": target, "slides": []}),
        (pp.TOOL_HANDLERS["read_pptx"], {"file_path": target}),
        (od.TOOL_HANDLERS["download_onedrive_file"], {"file_id": "x", "local_path": target}),
        (pp.TOOL_HANDLERS["pptx_replace_picture"], {"file_path": target, "slide_locator": 1, "picture_locator": 1, "new_image_path": "x.png"}),
        (pp.TOOL_HANDLERS["pptx_replace_picture"], {"file_path": os.path.join(folder, "..", "a.pptx"), "slide_locator": 1, "picture_locator": 1, "new_image_path": target}),
    ]


def _image_reader_cases(folder, out_dir):
    from skills.docx import tools as dx
    from skills.ppt import tools as pp
    img = os.path.join(folder, "sandbox~saved-permissions.bin")
    return [
        (dx.TOOL_HANDLERS["create_docx"], {"file_path": os.path.join(out_dir, "a.docx"), "content": [{"type": "image", "path": img}]}),
        (pp.TOOL_HANDLERS["create_pptx"], {"file_path": os.path.join(out_dir, "a.pptx"), "slides": [{"title": "t", "image": {"path": img}}]}),
    ]


@pytest.mark.parametrize("kind", ["direct", "traversal", "link", "case"])
def test_embedded_image_paths_refuse_secrets(tmp_path, secrets, kind):
    spell = _spellings(tmp_path, secrets)
    if kind not in spell:
        pytest.skip("Windows-only spelling")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    for fn, kwargs in _image_reader_cases(spell[kind], str(out_dir)):
        r = fn(**kwargs)
        assert r.get("error") == PROTECTED, (fn.__name__, r)
    assert list(out_dir.iterdir()) == []


@pytest.mark.parametrize("kind", ["direct", "traversal", "link", "case"])
def test_describe_images_refuses_secrets(tmp_path, secrets, kind):
    import asyncio
    from skills._always_on import tools as ao
    spell = _spellings(tmp_path, secrets)
    if kind not in spell:
        pytest.skip("Windows-only spelling")
    img = os.path.join(spell[kind], "x.png")
    for task in ("extract_data", "analyze_sequence"):
        r = asyncio.run(ao.TOOL_HANDLERS["describe_images"](task=task, image_paths=[img], fields=["a"]))
        assert r.get("error") == PROTECTED, r
    outside = asyncio.run(ao.TOOL_HANDLERS["describe_images"](task="analyze_sequence", image_paths=[str(tmp_path / "x.png")]))
    assert outside.get("error") != PROTECTED


@pytest.mark.parametrize("kind", ["direct", "traversal", "link", "case"])
def test_office_and_download_tools_refuse_secrets(tmp_path, secrets, kind):
    spell = _spellings(tmp_path, secrets)
    if kind not in spell:
        pytest.skip("Windows-only spelling")
    before = _snapshot(secrets)
    for fn, kwargs in _office_cases(spell[kind]):
        r = fn(**kwargs)
        assert r.get("error") == PROTECTED, (fn.__name__, r)
    assert _snapshot(secrets) == before


def test_office_tools_still_accept_open_and_outside(tmp_path, secrets):
    from skills.docx import tools as dx
    out = tmp_path / "work" / "a.docx"
    out.parent.mkdir()
    r = dx.TOOL_HANDLERS["create_docx"](file_path=str(out), content=[{"type": "paragraph", "text": "hi"}])
    assert r.get("error") != PROTECTED and out.exists(), r
