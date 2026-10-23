import pytest


def test_default_root_when_unset(store, tmp_path):
    assert store.get_default_root() == tmp_path / "demos"


def test_set_default_root_persists_and_is_used(store, tmp_path):
    target = tmp_path / "mine"
    assert store.set_default_root(str(target)) == target
    assert store.get_default_root() == target
    p = store.create_project()
    assert store.project_path(p["project_id"]).parent == target


def test_reset_default_root(store, tmp_path):
    store.set_default_root(str(tmp_path / "mine"))
    assert store.set_default_root(None) == tmp_path / "demos"
    assert store.get_default_root() == tmp_path / "demos"


def test_relative_root_rejected(store):
    with pytest.raises(ValueError):
        store.set_default_root("relative/path")


def test_unwritable_root_rejected(store, tmp_path):
    blocker = tmp_path / "file.txt"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        store.set_default_root(str(blocker / "sub"))
