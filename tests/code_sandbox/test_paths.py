from pathlib import Path

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


def _symlink_or_skip(link, target):
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:  # WinError 1314: no privilege
        pytest.skip(f"cannot create symlinks here: {exc}")


def test_symlinked_protected_dir_is_denied(home, tmp_path):
    data = tmp_path / "data" / "ssh"
    data.mkdir(parents=True)
    (data / "id_rsa").write_text("k")
    (home / ".ssh").rmdir()
    _symlink_or_skip(home / ".ssh", data)
    for target in (data, data / "id_rsa"):
        with pytest.raises(PathNotGrantable):
            normalize_grant_paths([str(target)], home)
    # an ancestor of the resolved form is denied too
    with pytest.raises(PathNotGrantable):
        normalize_grant_paths([str(data.parent)], home)


def test_resolved_protected_form_is_denied_without_symlink_privilege(home, tmp_path, monkeypatch):
    """Same as above but simulates the symlink by patching Path.resolve."""
    from pathlib import Path

    from sandbox import paths

    elsewhere = (tmp_path / "data" / "ssh").resolve()
    real_resolve = Path.resolve

    def fake_resolve(self, *args, **kwargs):
        if paths._key(self) == paths._key(home / ".ssh"):
            return elsewhere
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", fake_resolve)
    with pytest.raises(PathNotGrantable):
        check_grantable(elsewhere, home)
    with pytest.raises(PathNotGrantable):
        check_grantable(elsewhere / "id_rsa", home)
    with pytest.raises(PathNotGrantable):
        check_grantable(elsewhere.parent, home)
    check_grantable(home / "Documents", home)  # unrelated paths stay grantable


def test_darwin_comparison_is_case_insensitive(home, monkeypatch):
    import sys

    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(PathNotGrantable):
        check_grantable(home / ".SSH", home)
    with pytest.raises(PathNotGrantable):
        check_grantable(home / ".Aws" / "credentials", home)
    assert is_within(Path(str(home).upper()) / "x", home)
    assert is_within(home, Path(str(home).upper()))


def test_non_darwin_posix_keeps_case_sensitivity(home, monkeypatch):
    import os
    import sys

    if os.name != "posix":
        pytest.skip("case sensitivity is a POSIX property")
    monkeypatch.setattr(sys, "platform", "linux")
    check_grantable(home / ".SSH", home)


def test_resolve_oserror_becomes_not_grantable(home, monkeypatch):
    from pathlib import Path

    real_resolve = Path.resolve

    def boom(self, *args, **kwargs):
        if self.name == "Documents":
            raise PermissionError("denied")
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", boom)
    with pytest.raises(PathNotGrantable):
        normalize_grant_paths([str(home / "Documents")], home)


def test_hosts_zero_padded_ports_normalized_and_unicode_digits_rejected():
    assert normalize_hosts(["example.com:00080", "example.com:80"]) == ["example.com:80"]
    with pytest.raises(ValueError):
        normalize_hosts(["example.com:00000"])
    with pytest.raises(ValueError):
        normalize_hosts(["example.com:٨٠"])  # Arabic-Indic digits
    with pytest.raises(ValueError):
        normalize_hosts(["example.com:80\n"]) if False else normalize_hosts(["exa mple.com:80"])


# ── Windows alternate spellings (final review C-1) ──────────────────────────

from sandbox.paths import data_volume_form, windows_plain_path  # noqa: E402


@pytest.mark.parametrize("raw, plain", [
    (r"C:\Users\u\Documents", r"C:\Users\u\Documents"),
    (r"\\?\C:\Users\u\.ssh", r"C:\Users\u\.ssh"),
    ("//?/C:/Users/u/x", r"C:\Users\u\x"),
    (r"\\?\d:\data", r"d:\data"),
    (r"\\?\C:", "C:"),
])
def test_windows_plain_path_strips_extended_length_prefix(raw, plain):
    assert windows_plain_path(raw) == plain


@pytest.mark.parametrize("raw", [
    r"\\?\UNC\localhost\C$\Users\u\.ssh",
    r"\\localhost\C$\Users\u\.ssh",
    r"\\127.0.0.1\C$\Users\u",
    "//server/share/x",
    r"\\?\Volume{12345678-1234-1234-1234-123456789abc}\Users\u",
    r"\\.\C:\Users\u\.ssh",
    r"\\?\GLOBALROOT\Device\HarddiskVolume3\Users",
    r"C:\Users\u\notes.txt:secret",
    r"C:\Users\u\.ssh::$DATA",
    r"\\?\C:\Users\u\a:b",
    r"\Users\u",
    r"relative\x",
])
def test_windows_plain_path_rejects_unc_device_and_stream_forms(raw):
    with pytest.raises(PathNotGrantable):
        windows_plain_path(raw)


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows path spellings")
def test_windows_alternate_spellings_of_protected_paths_denied(home):
    share, rest = str(home)[0] + "$", str(home)[3:]
    for raw in (
        "//?/" + str(home / ".ssh"),
        "//?/UNC/localhost/" + share + "/" + rest + "/.ssh",
        "//localhost/" + share + "/" + rest + "/.ssh",
        "//127.0.0.1/" + share + "/" + rest,
    ):
        raw = raw.replace("/", "\\")
        assert raw.startswith("\\\\")
        with pytest.raises(PathNotGrantable):
            normalize_grant_paths([raw], home)
    # The extended-length spelling of a grantable folder is accepted and returned plain.
    doc = home / "Documents" / "project"
    assert normalize_grant_paths(["\\\\?\\" + str(doc)], home) == [doc]


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows path spellings")
def test_check_grantable_normalizes_extended_length_prefix(home):
    with pytest.raises(PathNotGrantable):
        check_grantable(Path("\\\\?\\" + str(home / ".aws")), home)


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows drive types")
def test_network_drive_is_not_grantable(home, monkeypatch):
    from sandbox import paths

    monkeypatch.setattr(paths, "_is_remote_drive", lambda p: True)
    with pytest.raises(PathNotGrantable, match="network"):
        normalize_grant_paths([str(home / "Documents")], home)


# ── Autostart / persistence locations (M-2) ─────────────────────────────────

@pytest.mark.parametrize("rel", [
    ".bashrc", ".profile", ".bash_profile", ".zshrc", ".zprofile",
    "Library/LaunchAgents", "Library/LaunchAgents/x.plist", "Library",
    ".config/autostart", ".config/autostart/x.desktop",
    "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup",
    "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup/x.lnk",
    "AppData/Roaming/Microsoft/Windows/Start Menu",
])
def test_autostart_locations_never_grantable(home, rel):
    with pytest.raises(PathNotGrantable):
        check_grantable(home / rel, home)


# ── macOS firmlinked data volume (I-2) ──────────────────────────────────────

def test_data_volume_form_is_pure():
    assert data_volume_form("/Users/u/.ssh") == "/System/Volumes/Data/Users/u/.ssh"
    assert data_volume_form("/System/Volumes/Data/Users/u") is None
    assert data_volume_form(r"C:\Users\u") is None


@pytest.mark.skipif(__import__("os").name != "posix", reason="POSIX home paths")
def test_darwin_data_volume_spellings_denied(home, monkeypatch):
    import sys

    monkeypatch.setattr(sys, "platform", "darwin")
    data = Path("/System/Volumes/Data" + str(home))
    for target in (data, data / ".ssh", data / ".ssh" / "id_rsa", data / ".gator", data.parent,
                   Path("/System/Volumes/Data"), Path("/System/Volumes")):
        with pytest.raises(PathNotGrantable):
            check_grantable(target, home)
    check_grantable(Path("/System/Volumes/Data/opt/project"), home)
