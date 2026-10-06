import sys

import pytest

import secure_store
from sandbox import saved_permissions as sp


def test_empty_by_default():
    assert sp.list_entries() == []
    assert not sp.covers([], ["/x"], [], None)


def test_add_and_cover_paths(tmp_path):
    proj = tmp_path / "proj"
    (proj / "sub").mkdir(parents=True)
    sp.add([], [str(proj)], False, [])
    assert sp.covers([], [str(proj / "sub")], [], None)
    assert sp.covers([str(proj)], [], [], None)
    assert not sp.covers([], [str(tmp_path)], [], None)


def test_paths_covered_by_union_of_entries(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    sp.add([], [str(a)], False, [])
    sp.add([str(b)], [], False, [])
    assert sp.covers([str(b)], [str(a)], [], None)


def test_network_needs_one_entry_with_all_programs(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    sp.add([], [str(proj)], True, ["git", "npm"])
    assert sp.covers([], [str(proj)], ["github.com:443"], {"git"})
    assert sp.covers([], [str(proj)], ["github.com:443"], {"git", "npm"})
    assert not sp.covers([], [str(proj)], ["github.com:443"], {"git", "curl"})
    assert not sp.covers([], [str(proj)], ["github.com:443"], None)


def test_network_not_granted_by_a_folder_only_entry(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    sp.add([], [str(proj)], False, [])
    assert not sp.covers([], [str(proj)], ["github.com:443"], {"git"})


def test_add_dedupes(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    sp.add([], [str(proj)], False, [])
    sp.add([], [str(proj)], False, [])
    assert len(sp.list_entries()) == 1


def test_remove_and_remove_all(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    first = sp.add([], [str(a)], False, [])
    sp.add([], [str(b)], False, [])
    assert sp.remove(first["id"]) is True
    assert sp.remove("nope") is False
    assert len(sp.list_entries()) == 1
    sp.remove_all()
    assert sp.list_entries() == []


@pytest.mark.parametrize("bad", ["x", [], {"version": 2, "entries": []}, {"version": 1, "entries": "x"},
                                 {"version": 1, "entries": [{"id": 1}]}])
def test_bad_stored_data_means_no_permissions(bad):
    secure_store.set_json("sandbox/saved-permissions", bad)
    assert sp.list_entries() == []
    assert not sp.covers([], ["/x"], [], None)


def test_store_exception_means_no_permissions(monkeypatch):
    def boom(name):
        raise RuntimeError("store down")
    monkeypatch.setattr(secure_store, "get_json", boom)
    assert sp.list_entries() == []


def test_describe_plain_words(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    e = sp.add([str(proj)], [str(proj)], True, ["npm", "git"])
    text = sp.describe(e)
    assert "Write to" in text and "Read from" in text
    assert "Use the network with: git, npm" in text


def test_network_stays_tied_to_its_own_paths(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    sp.add([], [str(a)], True, ["git"])
    sp.add([], [str(b)], False, [])
    host = ["evil.com:443"]
    assert not sp.covers([], [str(b)], host, {"git"})
    assert sp.covers([], [str(a)], host, {"git"})
    assert sp.covers([], [str(b)], [], None)


def test_network_with_no_programs_fails_closed(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    sp.add([], [str(a)], True, ["git"])
    assert not sp.covers([], [str(a)], ["h:443"], set())
    assert not sp.covers([], [str(a)], ["h:443"], [])


def test_import_failure_means_no_permissions(monkeypatch, tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    sp.add([], [str(a)], False, [])
    monkeypatch.setitem(sys.modules, "secure_store", None)
    assert sp.list_entries() == []
    assert not sp.covers([], [str(a)], [], None)


def test_add_refuses_to_overwrite_after_read_failure(monkeypatch, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    sp.add([], [str(a)], False, [])
    before = secure_store.get_json("sandbox/saved-permissions")
    real = secure_store.get_json

    def boom(name):
        raise RuntimeError("store down")
    monkeypatch.setattr(secure_store, "get_json", boom)
    with pytest.raises(RuntimeError):
        sp.add([], [str(b)], False, [])
    assert sp.remove(before["entries"][0]["id"]) is False
    monkeypatch.setattr(secure_store, "get_json", real)
    assert secure_store.get_json("sandbox/saved-permissions") == before


def test_add_and_remove_do_not_overwrite_unknown_version(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    future = {"version": 2, "entries": [{"anything": 1}]}
    secure_store.set_json("sandbox/saved-permissions", future)
    with pytest.raises(RuntimeError):
        sp.add([], [str(a)], False, [])
    assert sp.remove("x") is False
    assert secure_store.get_json("sandbox/saved-permissions") == future
    sp.remove_all()
    assert sp.list_entries() == []


def test_entries_with_relative_paths_or_bool_created_are_ignored(tmp_path):
    good = {"id": "g", "read_paths": [], "write_paths": [str(tmp_path)], "network": False, "programs": [], "created": 1.0}
    for bad in (dict(good, id="r", write_paths=["rel/dir"]), dict(good, id="e", read_paths=[""]),
                dict(good, id="b", created=True)):
        secure_store.set_json("sandbox/saved-permissions", {"version": 1, "entries": [good, bad]})
        assert [e["id"] for e in sp.list_entries()] == ["g"]
