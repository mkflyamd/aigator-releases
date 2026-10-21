import pytest

from sandbox import task_grants
from sandbox.paths import paths_covered


@pytest.fixture(autouse=True)
def _fresh():
    task_grants._reset()
    yield
    task_grants._reset()


def test_paths_covered_rules(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    sub = a / "sub"
    for d in (a, b, sub):
        d.mkdir()
    assert paths_covered([], [sub], [], [a])
    assert paths_covered([sub], [], [], [a])
    assert paths_covered([sub], [], [a], [])
    assert not paths_covered([], [sub], [a], [])
    assert not paths_covered([b], [], [], [a])
    assert paths_covered([], [], [], [])
    assert not paths_covered([a], [], [sub], [])


def test_grant_covers_subset_only(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    task_grants.add("t1", [], [str(a)], ["h.example:443"])
    assert task_grants.covers("t1", [], [str(a)], [])
    assert task_grants.covers("t1", [str(a)], [], ["h.example:443"])
    assert not task_grants.covers("t1", [], [str(a)], ["other.example:443"])
    assert not task_grants.covers("t2", [], [str(a)], [])


def test_union_of_grants(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    task_grants.add("t1", [str(a)], [], [])
    task_grants.add("t1", [], [str(b)], [])
    assert task_grants.covers("t1", [str(a), str(b)], [str(b)], [])


def test_grant_has_no_time_limit(tmp_path, monkeypatch):
    import time
    a = tmp_path / "a"
    a.mkdir()
    task_grants.add("t1", [], [str(a)], [])
    monkeypatch.setattr(time, "time", lambda: 1e12)
    assert task_grants.covers("t1", [], [str(a)], [])


def test_end_for_tab_only_that_tab(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    task_grants.add("t1", [], [str(a)], [])
    task_grants.add("t2", [], [str(a)], [])
    task_grants.end_for_tab("t1")
    assert not task_grants.covers("t1", [], [str(a)], [])
    assert task_grants.covers("t2", [], [str(a)], [])


def test_empty_request_is_covered_even_with_no_grants():
    assert task_grants.covers("t1", [], [], [])
