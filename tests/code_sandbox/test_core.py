import os
import shutil
import subprocess
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
    shim = tmp_path / ".gator" / "node-shim.js"
    assert env["NODE_OPTIONS"] == f'--preserve-symlinks --preserve-symlinks-main --require="{shim.as_posix()}"'
    assert not shim.exists()
    sandbox.install_node_shim(env)
    assert "asyncNative" in shim.read_text(encoding="utf-8")
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert FAKE not in env.values()
    assert not any("TOKEN" in k or "KEY" in k for k in env)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_node_shim_blocks_piped_spawns_and_closes_callback_form(tmp_path):
    probe = tmp_path / "probe.js"
    probe.write_text(
        "const cp = require('child_process'); const ev = [];\n"
        "cp.exec('x', (e) => ev.push('cb:' + e.code)).on('close', () => ev.push('close'));\n"
        "cp.spawn('x', [], { stdio: 'overlapped' }).on('error', () => ev.push('overlapped'));\n"
        "cp.spawn('x', [], { stdio: ['inherit', 'inherit', 'inherit', 'ipc'] }).on('error', () => ev.push('ipc'));\n"
        "setTimeout(() => console.log(ev.join(',')), 50);\n",
        encoding="utf-8",
    )
    shim = Path(sandbox.__file__).with_name("node_shim.js")
    out = subprocess.run(
        ["node", "--require", str(shim), str(probe)], capture_output=True, text=True, timeout=30, check=True,
    ).stdout.strip()
    assert out == "cb:EPERM,close,overlapped,ipc"


def test_install_node_shim_restores_a_tampered_copy_and_ignores_envs_without_it(tmp_path):
    env = sandbox.build_env({}, tmp_path, None, platform="win32")
    shim = tmp_path / ".gator" / "node-shim.js"
    sandbox.install_node_shim(env)
    original = shim.read_text(encoding="utf-8")
    shim.write_text("tampered", encoding="utf-8")
    sandbox.install_node_shim(env)
    assert shim.read_text(encoding="utf-8") == original
    sandbox.install_node_shim(sandbox.build_env({}, tmp_path / "other", None, platform="linux"))
    assert not (tmp_path / "other").exists()


def test_build_env_posix(tmp_path):
    parent = {"PATH": "/usr/bin", "LANG": "C.UTF-8", "HOME": "/home/me", "GITHUB_TOKEN": FAKE}
    env = sandbox.build_env(parent, tmp_path, None, platform="linux")
    assert env == {
        "PATH": "/usr/bin", "LANG": "C.UTF-8", "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path), "PYTHONIOENCODING": "utf-8",
    }


def test_build_env_prepends_extra_path_dirs_first(tmp_path):
    parent = {"PATH": "/usr/bin"}
    env = sandbox.build_env(parent, tmp_path, None, platform="linux", path_prepend=["/skills/a/bin", "/skills/b/bin"])
    assert env["PATH"] == "/skills/a/bin:/skills/b/bin:/usr/bin"
    win = sandbox.build_env({"Path": r"C:\Windows"}, tmp_path, None, platform="win32", path_prepend=[r"C:\skills\a\bin"])
    assert win["PATH"] == r"C:\skills\a\bin;C:\Windows"
    assert sandbox.build_env(parent, tmp_path, None, platform="linux")["PATH"] == "/usr/bin"


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
    assert '"node_shim.js"' in spec
