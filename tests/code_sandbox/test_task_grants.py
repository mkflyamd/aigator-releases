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
    task_grants.add("t1", [], [str(a)], ["h.example:443"], now=100.0)
    assert task_grants.covers("t1", [], [str(a)], [], now=101.0)
    assert task_grants.covers("t1", [str(a)], [], ["h.example:443"], now=101.0)
    assert not task_grants.covers("t1", [], [str(a)], ["other.example:443"], now=101.0)
    assert not task_grants.covers("t2", [], [str(a)], [], now=101.0)


def test_union_of_grants(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    task_grants.add("t1", [str(a)], [], [], now=100.0)
    task_grants.add("t1", [], [str(b)], [], now=101.0)
    assert task_grants.covers("t1", [str(a), str(b)], [str(b)], [], now=102.0)


def test_expires_after_ttl(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    task_grants.add("t1", [], [str(a)], [], now=100.0)
    assert task_grants.covers("t1", [], [str(a)], [], now=100.0 + task_grants.TASK_TTL_SECONDS)
    assert not task_grants.covers("t1", [], [str(a)], [], now=100.0 + task_grants.TASK_TTL_SECONDS + 1)


def test_end_for_tab_only_that_tab(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    task_grants.add("t1", [], [str(a)], [], now=100.0)
    task_grants.add("t2", [], [str(a)], [], now=100.0)
    task_grants.end_for_tab("t1")
    assert not task_grants.covers("t1", [], [str(a)], [], now=101.0)
    assert task_grants.covers("t2", [], [str(a)], [], now=101.0)


def test_empty_request_is_covered_even_with_no_grants():
    assert task_grants.covers("t1", [], [], [], now=1.0)
