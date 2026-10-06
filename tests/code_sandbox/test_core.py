import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import sandbox

FAKE = "aigator-fake-api-key"


def _req(tmp_path):
    return sandbox.SandboxRequest(
        argv=["python", "x.py"], cwd=tmp_path, env={}, runtime_paths=[], read_paths=[],
        write_paths=[], network=False, timeout=5,
    )


def test_build_env_windows_keeps_allow_list_and_drops_tokens(tmp_path):
    parent = {
        "Path": r"C:\Windows\System32", "SystemRoot": r"C:\Windows", "windir": r"C:\Windows",
        "ComSpec": r"C:\Windows\System32\cmd.exe", "PATHEXT": ".EXE", "GITHUB_TOKEN": FAKE,
        "JIRA_API_TOKEN": FAKE, "USERPROFILE": r"C:\Users\me", "OPENAI_API_KEY": FAKE,
    }
    env = sandbox.build_env(parent, tmp_path, r"C:\npm\node_modules", platform="win32")
    assert env["PATH"] == r"C:\Windows\System32"
    assert env["SYSTEMROOT"] == r"C:\Windows"
    assert env["COMSPEC"].endswith("cmd.exe")
    for key in ("TEMP", "TMP", "LOCALAPPDATA", "APPDATA", "USERPROFILE"):
        assert env[key] == str(tmp_path)
    assert env["NODE_PATH"] == r"C:\npm\node_modules"
    assert env["NODE_OPTIONS"] == "--preserve-symlinks --preserve-symlinks-main"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert FAKE not in env.values()
    assert not any("TOKEN" in k or "KEY" in k for k in env)


def test_build_env_posix(tmp_path):
    parent = {"PATH": "/usr/bin", "LANG": "C.UTF-8", "HOME": "/home/me", "GITHUB_TOKEN": FAKE}
    env = sandbox.build_env(parent, tmp_path, None, platform="linux")
    assert env == {
        "PATH": "/usr/bin", "LANG": "C.UTF-8", "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path), "PYTHONIOENCODING": "utf-8",
    }


def test_telemetry_record_is_metadata_only():
    rec = sandbox.telemetry_record("r1", "pptx", "enforced", True, 2, 1, "approved")
    assert rec == {
        "run_id": "r1", "skill_id": "pptx", "level": "enforced", "network": True,
        "extra_read": 2, "extra_write": 1, "approval": "approved",
    }


def test_level_is_probed_once_and_cached(monkeypatch):
    calls = []
    fake = SimpleNamespace(probe=lambda: calls.append(1))
    monkeypatch.setattr(sandbox, "_PROBE", None)
    monkeypatch.setattr(sandbox, "_launcher", lambda: fake)
    assert sandbox.sandbox_level() == "enforced"
    assert sandbox.sandbox_unavailable_reason() is None
    assert sandbox.sandbox_level() == "enforced"
    assert calls == [1]


def test_unavailable_reason_and_launch_refused(monkeypatch, tmp_path):
    fake = SimpleNamespace(probe=lambda: "install bubblewrap", launch=lambda req: pytest.fail("ran"))
    monkeypatch.setattr(sandbox, "_PROBE", None)
    monkeypatch.setattr(sandbox, "_launcher", lambda: fake)
    assert sandbox.sandbox_level() == "unavailable"
    assert sandbox.sandbox_unavailable_reason() == "install bubblewrap"
    with pytest.raises(sandbox.SandboxUnavailable, match="install bubblewrap"):
        sandbox.launch_sandboxed(_req(tmp_path))


def test_probe_exception_means_unavailable(monkeypatch):
    def boom():
        raise OSError("nope")

    monkeypatch.setattr(sandbox, "_PROBE", None)
    monkeypatch.setattr(sandbox, "_launcher", lambda: SimpleNamespace(probe=boom))
    assert sandbox.sandbox_level() == "unavailable"
    assert "OSError" in sandbox.sandbox_unavailable_reason()


def test_launch_delegates_when_enforced(monkeypatch, tmp_path):
    result = sandbox.SandboxResult(0, "ok", "", False)
    fake = SimpleNamespace(probe=lambda: None, launch=lambda req: result)
    monkeypatch.setattr(sandbox, "_PROBE", None)
    monkeypatch.setattr(sandbox, "_launcher", lambda: fake)
    assert sandbox.launch_sandboxed(_req(tmp_path)) is result


@pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX only")
def test_run_process_group_times_out_and_kills(tmp_path):
    res = sandbox.run_process_group(
        [sys.executable, "-c", "import time; print('hi', flush=True); time.sleep(30)"],
        tmp_path, dict(os.environ), 2,
    )
    assert res.timed_out and res.returncode == -1
    assert "hi" in res.stdout


def test_spec_bundles_sandbox_modules():
    spec = (Path(__file__).parents[2] / "packaging" / "aigator-backend.spec").read_text(encoding="utf-8")
    for name in ("sandbox", "sandbox.policy", "sandbox.paths", "sandbox.approvals",
                 "sandbox.launcher_windows", "sandbox.launcher_macos", "sandbox.launcher_linux"):
        assert f'"{name}"' in spec
