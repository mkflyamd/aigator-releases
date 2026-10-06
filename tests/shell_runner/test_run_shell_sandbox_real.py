import sys

import pytest

import config
import sandbox
from sandbox.policy import Policy
from skills.code_runner import tools as cr
from skills.shell_runner import tools as sh

pytestmark = pytest.mark.real_sandbox


@pytest.fixture
def real(tmp_path, monkeypatch):
    if sandbox.sandbox_level() != "enforced":
        pytest.skip("OS sandbox is not available here")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(config, "WORK_DIR", work)
    monkeypatch.setattr(cr, "_sandbox_mode", lambda cfg, policy: ("enforced", None))
    monkeypatch.setattr(sh, "load_policy", lambda: Policy())
    return work


def test_write_in_working_folder_and_read_back(real):
    cmd = "echo hello> out.txt & type out.txt" if sys.platform == "win32" else "echo hello > out.txt && cat out.txt"
    r = sh._tool_run_shell(cmd, _context_id="tab")
    assert r["exit_code"] == 0 and "hello" in r["stdout"], r
    assert (real / "out.txt").exists()


def test_read_outside_granted_folders_is_denied(real, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-aigator", encoding="utf-8")
    cmd = f'type "{secret}"' if sys.platform == "win32" else f"cat '{secret}'"
    r = sh._tool_run_shell(cmd, _context_id="tab")
    assert "TOP-SECRET-aigator" not in r["stdout"] and r["exit_code"] != 0, r
