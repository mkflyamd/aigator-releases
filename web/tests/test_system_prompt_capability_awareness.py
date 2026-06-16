"""System prompt must make the agent check its real capabilities before refusing
a task — a cluster of three sibling bugs:

- #13: agent falsely claimed it lacked file-edit tools when `run_python` (which can
  write any local file) was active.
- #14: agent was unaware installed CLIs (e.g. `gh`) are reachable via `run_shell`
  and nearly refused a task it could do with one shell command.
- #18: agent forgot capabilities it had already demonstrated in the project and
  invented technical reasons ("requires a session cookie, not a PAT") to refuse.

All three are "refuse based on assumption instead of evidence". The fix hardens the
Honesty section of the system prompt. These tests assert the concrete guidance is
present.
"""
import pathlib

SKILL = (pathlib.Path(__file__).parent.parent / "skills" / "aigator" / "SKILL.md").read_text(encoding="utf-8")
LOW = SKILL.lower()


def test_prompt_documents_run_python_write_capability():
    # #13: run_python can write any local file; HITL outside OUTPUT_DIR is expected.
    assert "run_python" in LOW
    assert "write" in LOW
    assert "output_dir" in LOW, "prompt must state HITL outside OUTPUT_DIR is expected, not a failure (#13)"


def test_prompt_requires_naming_missing_tool_before_refusing():
    # #13: forbid generic refusals — name the specific missing tool.
    assert any(w in LOW for w in ("name the specific", "name the missing", "which tool", "specific tool")), \
        "prompt must require naming the specific missing tool before refusing (#13)"


def test_prompt_documents_shell_cli_access():
    # #14: run_shell exposes installed CLIs; probe before refusing.
    assert "run_shell" in LOW
    assert "gh" in LOW and "git" in LOW
    assert any(w in LOW for w in ("--version", "which ", "probe")), \
        "prompt must instruct probing a CLI (which / --version) before refusing (#14)"


def test_prompt_requires_checking_prior_work_before_refusing():
    # #18: check prior project work (git log / issue history) before claiming impossible.
    assert any(w in LOW for w in ("git log", "issue history", "prior", "previously", "already demonstrated", "done before")), \
        "prompt must require checking prior project work before refusing (#18)"


def test_prompt_forbids_inventing_technical_reasons_without_error():
    # #18: never invent technical limits without citing a real error message.
    assert "error" in LOW
    assert any(w in LOW for w in ("invent", "fabricat", "made up", "made-up")), \
        "prompt must forbid inventing technical reasons without a real error (#18)"
