import pytest

from sandbox.paths import PathNotGrantable, check_grantable, is_within, normalize_grant_paths, normalize_hosts


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    for sub in (".ssh", ".aws", ".gator/outputs/run1", ".config/gcloud", "Documents/project"):
        (h / sub).mkdir(parents=True)
    (h / "Documents" / "project" / "notes.txt").write_text("n")
    return h.resolve()


def test_normalizes_dedupes_and_sorts(home):
    doc = home / "Documents" / "project"
    raw = [str(doc), str(doc / "notes.txt"), str(doc) + "/", str(doc / ".." / "project")]
    assert normalize_grant_paths(raw, home) == sorted({doc, doc / "notes.txt"}, key=lambda p: str(p).lower())


@pytest.mark.parametrize("rel", ["", ".ssh", ".ssh/id_rsa", ".aws", ".gator", ".gator/secrets",
                                  ".config", ".config/gcloud", ".config/gcloud/x"])
def test_deny_list_is_never_grantable(home, rel):
    with pytest.raises(PathNotGrantable):
        normalize_grant_paths([str(home / rel)], home)


def test_parent_of_home_and_roots_are_denied(home):
    with pytest.raises(PathNotGrantable):
        check_grantable(home.parent, home)
    with pytest.raises(PathNotGrantable):
        check_grantable(type(home)(home.anchor), home)


def test_gator_outputs_is_grantable(home):
    assert normalize_grant_paths([str(home / ".gator" / "outputs" / "run1")], home) == [
        home / ".gator" / "outputs" / "run1"
    ]


def test_relative_missing_and_bad_types_rejected(home):
    with pytest.raises(PathNotGrantable, match="absolute"):
        normalize_grant_paths(["Documents"], home)
    with pytest.raises(PathNotGrantable, match="does not exist"):
        normalize_grant_paths([str(home / "Documents" / "nope.txt")], home)
    with pytest.raises(PathNotGrantable):
        normalize_grant_paths([""], home)
    with pytest.raises(PathNotGrantable):
        normalize_grant_paths({"a": 1}, home)


def test_empty_is_empty(home):
    assert normalize_grant_paths(None, home) == []
    assert normalize_grant_paths([], home) == []


def test_is_within(home):
    assert is_within(home / "a" / "b", home)
    assert is_within(home, home)
    assert not is_within(home.parent / "homeX", home)


def test_hosts_normalized_and_validated():
    assert normalize_hosts(["API.Example.com:443", "api.example.com:443", "[::1]:8080"]) == [
        "[::1]:8080", "api.example.com:443",
    ]
    for bad in (["example.com"], ["example.com:0"], ["example.com:70000"], ["http://x:1"], [3]):
        with pytest.raises(ValueError):
            normalize_hosts(bad)
    assert normalize_hosts(None) == []
