import dataclasses
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from sandbox import SandboxRequest
from sandbox import launcher_macos as lm


_STRING = re.compile(r'"(?:[^"\\]|\\.)*"', re.S)


def _rules(profile):
    return profile.splitlines()


def _literals(profile, kind):
    return re.findall(rf'\({kind} "((?:[^"\\]|\\.)*)"\)', profile)


def _req(network=False):
    return SandboxRequest(
        argv=["/usr/bin/python3", "code.py"], cwd=Path("/Users/me/.gator/outputs/r1"), env={},
        runtime_paths=[Path("/opt/homebrew/opt/python@3.12")], read_paths=[Path('/Users/me/Docs "q"')],
        write_paths=[Path("/Users/me/out")], network=network, timeout=5,
    )


def test_profile_denies_by_default_and_scopes_access():
    profile = lm.build_profile(_req())
    assert profile.startswith("(version 1)\n(deny default)\n")
    rules = _rules(profile)
    system = '(allow file-read* (subpath "/usr") (subpath "/System") (subpath "/Library") (subpath "/bin") (subpath "/private/etc"))'
    data_deny = '(deny file-read* (subpath "/System/Volumes/Data"))'
    granted = '(allow file-read* (subpath "/opt/homebrew/opt/python@3.12") (subpath "/Users/me/Docs \\"q\\""))'
    # The firmlinked data volume (/System/Volumes/Data/Users/...) is denied after the /System
    # allow (last match wins), and before the runtime and granted paths so those still apply.
    assert rules.index(system) < rules.index(data_deny) < rules.index(granted)
    assert '(allow file-read* file-write* (subpath "/Users/me/.gator/outputs/r1") (subpath "/Users/me/out"))' in profile
    assert not [r for r in _rules(profile) if "network" in r or "system-socket" in r]
    subpaths = _literals(profile, "subpath")
    assert "/Users/me" not in subpaths and "/" not in subpaths  # never the home folder or root itself
    # Processes abort at start-up unless the root directory entry itself is readable; only that literal.
    assert '(allow file-read-data (literal "/"))' in rules
    assert _literals(profile, "literal").count("/") == 1


def test_profile_network_only_when_approved():
    rules = _rules(lm.build_profile(_req(network=True)))
    assert "(allow network-outbound (remote ip))" in rules
    assert '(allow network-outbound (literal "/private/var/run/mDNSResponder"))' in rules
    assert "(allow network-outbound)" not in rules  # a bare rule would also allow AF_UNIX sockets
    assert not [r for r in rules if "network-inbound" in r or "network-bind" in r]
    assert "(allow system-socket)" in rules
    assert any("com.apple.dnssd.service" in r for r in rules)
    # AI Gator's own localhost API stays unreachable: the deny comes after the allow (last match wins).
    assert rules.index('(deny network-outbound (remote ip "localhost:*"))') > rules.index("(allow network-outbound (remote ip))")


def test_quote_escapes_backslash_quote_and_control_characters():
    assert lm._quote("a\\b") == '"a\\\\b"'
    assert lm._quote('a"b') == '"a\\"b"'
    assert lm._quote("a\nb\rc\td") == '"a\\nb\\rc\\td"'


def test_hostile_path_stays_one_string_literal():
    hostile = 'a"\n(allow file-read* (subpath "/"))'
    req = dataclasses.replace(_req(), read_paths=[hostile, "/Users/me/back\\slash"])
    profile = lm.build_profile(req)
    for literal in _STRING.findall(profile):
        assert "\n" not in literal and "\r" not in literal
    assert lm._quote(hostile) in profile
    assert '(subpath "/Users/me/back\\\\slash")' in profile
    assert '(allow file-read* (subpath "/"))' not in _rules(profile)
    assert "/" not in _literals(profile, "subpath")
    assert len(_rules(profile)) == len(_rules(lm.build_profile(_req())))
    stripped = _STRING.sub('""', profile)
    assert stripped.count("(") == stripped.count(")")


def test_probe_reports_missing_sandbox_exec(monkeypatch, tmp_path):
    monkeypatch.setattr(lm, "SANDBOX_EXEC", str(tmp_path / "missing-sandbox-exec"))
    assert "sandbox-exec" in lm.probe()


def test_probe_reports_sandbox_exec_failures(monkeypatch, tmp_path):
    fake = tmp_path / "sandbox-exec"
    fake.write_text("")
    monkeypatch.setattr(lm, "SANDBOX_EXEC", str(fake))
    monkeypatch.setattr(lm.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 71))
    assert "refused" in lm.probe()

    def boom(*a, **k):
        raise subprocess.TimeoutExpired(a, 10)

    monkeypatch.setattr(lm.subprocess, "run", boom)
    assert "TimeoutExpired" in lm.probe()
    monkeypatch.setattr(lm.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0))
    assert lm.probe() is None


def test_launch_runs_profile_through_sandbox_exec(monkeypatch, tmp_path):
    fake = tmp_path / "sandbox-exec"
    fake.write_text("")
    monkeypatch.setattr(lm, "SANDBOX_EXEC", str(fake))
    monkeypatch.setattr(lm, "_real", lambda p: Path(p))
    calls = []
    sentinel = object()

    def fake_run(argv, cwd, env, timeout):
        calls.append((argv, cwd, env, timeout))
        return sentinel

    monkeypatch.setattr(lm, "run_process_group", fake_run)
    req = _req()
    assert lm.launch(req) is sentinel
    argv, cwd, env, timeout = calls[0]
    assert argv[:2] == [str(fake), "-p"]
    assert argv[2] == lm.build_profile(req)
    assert argv[3:] == req.argv
    assert (cwd, env, timeout) == (req.cwd, req.env, 5)


def test_launch_resolves_symlinked_paths_into_profile(monkeypatch, tmp_path):
    fake = tmp_path / "sandbox-exec"
    fake.write_text("")
    monkeypatch.setattr(lm, "SANDBOX_EXEC", str(fake))
    monkeypatch.setattr(lm, "_real", lambda p: Path("/private") / str(Path(p).as_posix()).lstrip("/"))
    seen = []
    monkeypatch.setattr(lm, "run_process_group", lambda argv, *a: seen.append(argv))
    lm.launch(_req())
    assert '(subpath "/private/Users/me/.gator/outputs/r1")' in seen[0][2]


def test_launch_without_sandbox_exec_raises_unavailable_and_runs_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(lm, "SANDBOX_EXEC", str(tmp_path / "missing"))

    def must_not_run(*a, **k):
        raise AssertionError("process must not start")

    monkeypatch.setattr(lm, "run_process_group", must_not_run)
    with pytest.raises(lm.SandboxUnavailable):
        lm.launch(_req())


@pytest.mark.skipif(sys.platform == "win32", reason="creating symlinks needs a privilege on Windows")
def test_launch_resolves_real_symlinks(monkeypatch, tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    os.symlink(target, link)
    fake = tmp_path / "sandbox-exec"
    fake.write_text("")
    monkeypatch.setattr(lm, "SANDBOX_EXEC", str(fake))
    seen = []
    monkeypatch.setattr(lm, "run_process_group", lambda argv, *a: seen.append(argv))
    req = dataclasses.replace(_req(), cwd=link, read_paths=[link], write_paths=[])
    lm.launch(req)
    subpaths = _literals(seen[0][2], "subpath")
    assert os.path.realpath(target) in subpaths
    assert str(link) not in subpaths


@pytest.mark.parametrize("exc", [FileNotFoundError, PermissionError])
def test_launch_failure_before_start_is_unavailable(monkeypatch, tmp_path, exc):
    fake = tmp_path / "sandbox-exec"
    fake.write_text("")
    monkeypatch.setattr(lm, "SANDBOX_EXEC", str(fake))

    def boom(*a, **k):
        raise exc("exec failed")

    monkeypatch.setattr(lm, "run_process_group", boom)
    with pytest.raises(lm.SandboxUnavailable):
        lm.launch(_req())


def test_launch_other_os_error_is_run_error_not_unavailable(monkeypatch, tmp_path):
    fake = tmp_path / "sandbox-exec"
    fake.write_text("")
    monkeypatch.setattr(lm, "SANDBOX_EXEC", str(fake))

    def boom(*a, **k):
        raise OSError(5, "I/O error")

    monkeypatch.setattr(lm, "run_process_group", boom)
    with pytest.raises(lm.SandboxRunError):
        lm.launch(_req())


@pytest.mark.real_sandbox
@pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt runs only on macOS (cannot run on the Windows dev machine)")
def test_real_seatbelt_run():
    script = Path(__file__).with_name("posix_sandbox_check.py")
    out = json.loads(subprocess.run([sys.executable, str(script), "macos"], capture_output=True, text=True,
                                    timeout=180, check=True).stdout.strip().splitlines()[-1])
    assert out["probe"] is None
    assert out["default"]["write_run_dir"].startswith("OK")
    assert out["default"]["read_secret"].startswith("DENIED")
    assert out["default"]["read_secret_via_data_volume"].startswith("DENIED")
    assert out["default"]["read_extra"].startswith("DENIED")
    assert out["default"]["net_external"].startswith("DENIED")
    assert out["default"]["token"] is None
    assert out["with_extra"]["read_extra"] == "OK:extra-data"
    assert out["tree_kill"]["timed_out"] is True
    assert out["leftover_sleepers"] == 0
