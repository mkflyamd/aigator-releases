import dataclasses
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sandbox import SandboxRequest
from sandbox import launcher_linux as ll

CHECK = Path(__file__).with_name("posix_sandbox_check.py")


def _req(network=False):
    return SandboxRequest(
        argv=["/usr/bin/python3", "code.py"], cwd=Path("/home/me/.gator/outputs/r1"), env={"PATH": "/usr/bin"},
        runtime_paths=[Path("/home/me/app/.venv")], read_paths=[Path("/home/me/data")],
        write_paths=[Path("/home/me/out")], network=network, timeout=5,
    )


def _binds(argv, option):
    """(src, dest) pairs for every `option src dest` triple in the bwrap options (before `--`)."""
    opts = argv[:argv.index("--")]
    return [(opts[i + 1], opts[i + 2]) for i, a in enumerate(opts) if a == option]


def _all_bound(argv):
    return [src for opt in ("--bind", "--ro-bind", "--ro-bind-try") for src, _ in _binds(argv, opt)]


def test_argv_unshares_everything_and_binds_only_what_is_needed():
    argv = ll.build_argv(_req(), "/usr/bin/bwrap")
    assert argv[:4] == ["/usr/bin/bwrap", "--unshare-all", "--die-with-parent", "--new-session"]
    assert "--share-net" not in argv
    ro_try = _binds(argv, "--ro-bind-try")
    for path in (*ll.SYSTEM_RO_PATHS, *ll.ETC_RO_PATHS):
        assert (path, path) in ro_try
    assert ("/usr", "/usr") in ro_try
    assert argv[argv.index("--proc") + 1] == "/proc"
    assert argv[argv.index("--dev") + 1] == "/dev"
    assert argv[argv.index("--tmpfs") + 1] == "/tmp"
    assert ("/home/me/app/.venv", "/home/me/app/.venv") in _binds(argv, "--ro-bind")
    assert ("/home/me/data", "/home/me/data") in _binds(argv, "--ro-bind")
    assert _binds(argv, "--bind") == [("/home/me/out", "/home/me/out"),
                                      ("/home/me/.gator/outputs/r1", "/home/me/.gator/outputs/r1")]
    assert argv[argv.index("--chdir") + 1] == "/home/me/.gator/outputs/r1"
    assert argv[argv.index("--") + 1:] == ["/usr/bin/python3", "code.py"]
    assert argv.count("--") == 1
    bound = _all_bound(argv)
    for forbidden in ("/", "/home", "/home/me", "/home/me/.ssh", "/root", "/etc"):
        assert forbidden not in bound


def test_argv_tmpfs_comes_before_runtime_binds():
    argv = ll.build_argv(_req())
    assert argv.index("--tmpfs") < argv.index("/home/me/app/.venv")


def test_network_only_when_approved():
    assert "--share-net" in ll.build_argv(_req(network=True))


def test_network_off_grants_nothing_network_related():
    argv = ll.build_argv(_req(network=False))
    bound = _all_bound(argv)
    for path in ("/etc/resolv.conf", "/etc/hosts", "/etc/ssl", "/etc/ca-certificates", "/etc/pki"):
        assert path not in bound
        assert path not in ll.ETC_RO_PATHS
    assert "--share-net" not in argv


def test_network_on_adds_resolver_and_certificates():
    bound = _all_bound(ll.build_argv(_req(network=True)))
    for path in ("/etc/resolv.conf", "/etc/hosts", "/etc/ssl", "/etc/ca-certificates", "/etc/pki"):
        assert path in bound


@pytest.mark.parametrize("hostile", ["-x", "--bind", "relative/path", "", "/"])
def test_non_absolute_or_option_like_paths_are_refused(hostile):
    for field in ("runtime_paths", "read_paths", "write_paths"):
        req = dataclasses.replace(_req(), **{field: [hostile]})
        with pytest.raises(ValueError):
            ll.build_argv(req)
    with pytest.raises(ValueError):
        ll.build_argv(dataclasses.replace(_req(), cwd=hostile))


def test_hostile_paths_stay_single_argv_elements():
    hostile = "/home/me/a b\"c'd\n--bind / /;$(x)"
    argv = ll.build_argv(dataclasses.replace(_req(), read_paths=[hostile]))
    assert (hostile, hostile) in _binds(argv, "--ro-bind")
    assert _all_bound(argv).count("/") == 0
    assert len(argv) == len(ll.build_argv(_req()))
    assert argv.count("--bind") == 2


def test_probe_reports_missing_bwrap_with_the_fix(monkeypatch):
    monkeypatch.setattr(ll.shutil, "which", lambda name: None)
    assert "bubblewrap" in ll.probe() and "apt install bubblewrap" in ll.probe()


def test_probe_reports_blocked_user_namespaces(monkeypatch):
    monkeypatch.setattr(ll.shutil, "which", lambda name: "/usr/bin/bwrap")
    monkeypatch.setattr(ll.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, b"", b"setting up uid map: Permission denied"))
    assert ll.probe() == ll.BWRAP_BLOCKED


def test_probe_ok_and_failure_to_run(monkeypatch):
    monkeypatch.setattr(ll.shutil, "which", lambda name: "/usr/bin/bwrap")
    monkeypatch.setattr(ll.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, b"", b""))
    assert ll.probe() is None

    def boom(*a, **k):
        raise subprocess.TimeoutExpired(a, 10)

    monkeypatch.setattr(ll.subprocess, "run", boom)
    assert "TimeoutExpired" in ll.probe()


def _stub_bwrap(monkeypatch):
    monkeypatch.setattr(ll.shutil, "which", lambda name: "/usr/bin/bwrap")
    monkeypatch.setattr(ll, "_real", lambda p: Path(p))


def test_launch_runs_through_bwrap(monkeypatch):
    _stub_bwrap(monkeypatch)
    calls = []
    sentinel = object()

    def fake_run(argv, cwd, env, timeout):
        calls.append((argv, cwd, env, timeout))
        return sentinel

    monkeypatch.setattr(ll, "run_process_group", fake_run)
    req = _req()
    assert ll.launch(req) is sentinel
    argv, cwd, env, timeout = calls[0]
    assert argv == ll.build_argv(req, "/usr/bin/bwrap")
    assert (cwd, env, timeout) == (req.cwd, req.env, 5)


def test_launch_without_bwrap_raises_unavailable_and_runs_nothing(monkeypatch):
    monkeypatch.setattr(ll.shutil, "which", lambda name: None)

    def must_not_run(*a, **k):
        raise AssertionError("process must not start")

    monkeypatch.setattr(ll, "run_process_group", must_not_run)
    with pytest.raises(ll.SandboxUnavailable):
        ll.launch(_req())


def test_launch_refused_path_raises_unavailable_and_runs_nothing(monkeypatch):
    _stub_bwrap(monkeypatch)
    monkeypatch.setattr(ll, "run_process_group", lambda *a, **k: pytest.fail("process must not start"))
    with pytest.raises(ll.SandboxUnavailable):
        ll.launch(dataclasses.replace(_req(), read_paths=["-x"]))


@pytest.mark.skipif(sys.platform == "win32", reason="creating symlinks needs a privilege on Windows")
def test_launch_resolves_real_symlinks(monkeypatch, tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    os.symlink(target, link)
    monkeypatch.setattr(ll.shutil, "which", lambda name: "/usr/bin/bwrap")
    seen = []
    monkeypatch.setattr(ll, "run_process_group", lambda argv, *a: seen.append(argv))
    ll.launch(dataclasses.replace(_req(), cwd=link, read_paths=[link], write_paths=[]))
    bound = _all_bound(seen[0])
    assert os.path.realpath(target) in bound
    assert str(link) not in bound


@pytest.mark.parametrize("exc", [FileNotFoundError, PermissionError])
def test_launch_failure_before_start_is_unavailable(monkeypatch, exc):
    _stub_bwrap(monkeypatch)

    def boom(*a, **k):
        raise exc("exec failed")

    monkeypatch.setattr(ll, "run_process_group", boom)
    with pytest.raises(ll.SandboxUnavailable):
        ll.launch(_req())


def test_launch_other_os_error_is_run_error_not_unavailable(monkeypatch):
    _stub_bwrap(monkeypatch)

    def boom(*a, **k):
        raise OSError(5, "I/O error")

    monkeypatch.setattr(ll, "run_process_group", boom)
    with pytest.raises(ll.SandboxRunError):
        ll.launch(_req())


def _wsl_path(p: Path) -> str:
    s = str(p.resolve())
    return "/mnt/" + s[0].lower() + s[2:].replace("\\", "/")


def _check_command():
    """Command that runs the shared check script with real bubblewrap, or a skip reason."""
    if sys.platform.startswith("linux"):
        if not shutil.which("bwrap"):
            return None, "bubblewrap is not installed (sudo apt install bubblewrap)"
        return [sys.executable, str(CHECK), "linux"], None
    if sys.platform == "win32":
        if not shutil.which("wsl.exe"):
            return None, "wsl.exe not available"
        try:
            r = subprocess.run(["wsl.exe", "-d", "Ubuntu", "--", "sh", "-c", "command -v bwrap && command -v python3"],
                               capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return None, "WSL Ubuntu did not respond"
        if r.returncode != 0:
            return None, "WSL Ubuntu without bubblewrap/python3 (wsl -d Ubuntu -- sudo apt install -y bubblewrap python3)"
        return ["wsl.exe", "-d", "Ubuntu", "--", "env", "PYTHONDONTWRITEBYTECODE=1", "python3", _wsl_path(CHECK), "linux"], None
    return None, "Linux sandbox checks run on Linux or through WSL"


@pytest.mark.real_sandbox
def test_real_bwrap_run():
    cmd, reason = _check_command()
    if cmd is None:
        pytest.skip(reason)
    out = json.loads(subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=True).stdout.strip().splitlines()[-1])
    assert out["probe"] is None
    assert out["default"]["write_run_dir"].startswith("OK")
    assert out["default"]["read_secret"].startswith("DENIED")
    assert out["default"]["read_extra"].startswith("DENIED")
    assert out["default"]["net_external"].startswith("DENIED")
    assert out["default"]["token"] is None
    assert out["with_extra"]["read_extra"] == "OK:extra-data"
    assert out["tree_kill"]["timed_out"] is True
    assert out["leftover_sleepers"] == 0
