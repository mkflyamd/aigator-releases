import json
import subprocess
import sys
from pathlib import Path

import pytest

from sandbox import SandboxRequest
from sandbox import launcher_macos as lm


def _req(network=False):
    return SandboxRequest(
        argv=["/usr/bin/python3", "code.py"], cwd=Path("/Users/me/.gator/outputs/r1"), env={},
        runtime_paths=[Path("/opt/homebrew/opt/python@3.12")], read_paths=[Path('/Users/me/Docs "q"')],
        write_paths=[Path("/Users/me/out")], network=network, timeout=5,
    )


def test_profile_denies_by_default_and_scopes_access():
    profile = lm.build_profile(_req())
    assert profile.startswith("(version 1)\n(deny default)\n")
    assert '(allow file-read* (subpath "/usr") (subpath "/System") (subpath "/Library") (subpath "/bin") (subpath "/private/etc") (subpath "/opt/homebrew/opt/python@3.12") (subpath "/Users/me/Docs \\"q\\""))' in profile
    assert '(allow file-read* file-write* (subpath "/Users/me/.gator/outputs/r1") (subpath "/Users/me/out"))' in profile
    assert "network" not in profile
    assert '"/Users/me"' not in profile  # never the home folder itself


def test_profile_network_only_when_approved():
    profile = lm.build_profile(_req(network=True))
    assert "(allow network-outbound)" in profile
    assert "(allow system-socket)" in profile
    assert "com.apple.dnssd.service" in profile


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


@pytest.mark.real_sandbox
@pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt runs only on macOS (cannot run on the Windows dev machine)")
def test_real_seatbelt_run():
    script = Path(__file__).with_name("posix_sandbox_check.py")
    out = json.loads(subprocess.run([sys.executable, str(script), "macos"], capture_output=True, text=True,
                                    timeout=180, check=True).stdout.strip().splitlines()[-1])
    assert out["probe"] is None
    assert out["default"]["write_run_dir"].startswith("OK")
    assert out["default"]["read_secret"].startswith("DENIED")
    assert out["default"]["read_extra"].startswith("DENIED")
    assert out["default"]["net_external"].startswith("DENIED")
    assert out["default"]["token"] is None
    assert out["with_extra"]["read_extra"] == "OK:extra-data"
    assert out["tree_kill"]["timed_out"] is True
    assert out["leftover_sleepers"] == 0
