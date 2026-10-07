import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "web"))

import json

import pytest

import sandbox
from marketplace import installer, state
from marketplace.permissions import Permissions


def _skill(make_skill_dir, command="exit 0", event="BeforeEmailSend", name="demo"):
    return make_skill_dir({"hooks.json": json.dumps({"hooks": [{"event": event, "command": command}]})}, name)


def test_hook_runs_in_a_throwaway_run_folder_with_no_grants_by_default(make_skill_dir, fake_sandbox):
    skill = _skill(make_skill_dir)

    from hooks.executor import fire_event

    fire_event("BeforeEmailSend", skill, skill_id="demo")
    req = fake_sandbox.requests[0]
    assert req.network is False
    assert list(req.read_paths) == [] and list(req.write_paths) == []
    assert req.cwd != skill                      # the sandbox makes cwd writable, so never the skill folder
    assert skill.resolve() in [p.resolve() for p in req.runtime_paths]
    assert req.argv[-1].strip('"') == "exit 0"   # the author's command is one argument to the shell


def test_hook_argv_uses_the_platform_shell(make_skill_dir, fake_sandbox):
    skill = _skill(make_skill_dir, "echo hi")

    from hooks.executor import fire_event

    fire_event("BeforeEmailSend", skill)
    argv = fake_sandbox.requests[0].argv
    if os.name == "nt":
        # the command is passed verbatim (RawArg) so inner quotes are not backslash-escaped
        assert argv[0].lower().endswith("cmd.exe") and argv[1:4] == ["/d", "/s", "/c"]
        assert isinstance(argv[-1], sandbox.RawArg) and argv[-1] == '"echo hi"'
    else:
        assert argv[:2] == ["/bin/sh", "-c"]
        assert argv[-1] == "echo hi"


def test_approved_permissions_widen_exactly_the_declared_access(make_skill_dir, fake_sandbox, tmp_path):
    skill = _skill(make_skill_dir)
    docs = tmp_path / "reports"
    docs.mkdir()
    perms = Permissions(filesystem=(str(docs),), network=("api.example.com",))

    from hooks.executor import fire_event

    fire_event("BeforeEmailSend", skill, skill_id="demo", perms=perms)
    req = fake_sandbox.requests[0]
    assert req.network is True
    assert [p.resolve() for p in req.read_paths] == [docs.resolve()]
    assert list(req.write_paths) == []


def test_a_declared_secrets_path_is_not_granted(make_skill_dir, fake_sandbox):
    from pathlib import Path

    skill = _skill(make_skill_dir)
    secrets = Path.home() / ".ssh"
    perms = Permissions(filesystem=(str(secrets),))

    from hooks.executor import fire_event

    fire_event("BeforeEmailSend", skill, skill_id="demo", perms=perms)
    granted = [p.resolve() for p in fake_sandbox.requests[0].read_paths]
    assert secrets.resolve() not in granted


def test_fire_all_skill_hooks_passes_the_approved_grant_for_each_skill(make_skill_dir, fake_sandbox, monkeypatch):
    skill = _skill(make_skill_dir, name="granted")
    installer.save_installed([{"id": "granted", "version": "1.0", "source": "mp"}])
    state.record_approval("granted", Permissions(network=("api.example.com",)).to_dict())
    monkeypatch.setattr(state, "skill_dir_for", lambda entry: skill)

    from hooks.executor import fire_all_skill_hooks

    assert fire_all_skill_hooks("BeforeEmailSend")["blocked"] is False
    assert fake_sandbox.requests[0].network is True


def test_a_legacy_skill_with_no_recorded_approval_gets_no_grants(make_skill_dir, fake_sandbox, monkeypatch):
    skill = _skill(make_skill_dir, name="legacy")
    installer.save_installed([{"id": "legacy", "version": "1.0"}])
    monkeypatch.setattr(state, "skill_dir_for", lambda entry: skill)

    from hooks.executor import fire_all_skill_hooks

    fire_all_skill_hooks("BeforeEmailSend")
    req = fake_sandbox.requests[0]
    assert req.network is False and list(req.read_paths) == []


def test_a_disabled_skills_hooks_do_not_run(make_skill_dir, fake_sandbox, monkeypatch):
    skill = _skill(make_skill_dir, name="off")
    installer.save_installed([{"id": "off", "version": "1.0", "disabled": True}])
    monkeypatch.setattr(state, "skill_dir_for", lambda entry: skill)

    from hooks.executor import fire_all_skill_hooks

    assert fire_all_skill_hooks("BeforeEmailSend")["blocked"] is False
    assert fake_sandbox.requests == []


def test_the_run_folder_is_removed_after_the_hook(make_skill_dir, fake_sandbox):
    skill = _skill(make_skill_dir)

    from hooks.executor import fire_event

    fire_event("BeforeEmailSend", skill)
    assert not fake_sandbox.requests[0].cwd.exists()


needs_sandbox = pytest.mark.skipif(
    sandbox.sandbox_level() != "enforced", reason="OS sandbox is not enforced on this machine"
)


@needs_sandbox
def test_real_sandbox_exit_codes_decide_the_gate(make_skill_dir):
    from hooks.executor import fire_event

    assert fire_event("BeforeEmailSend", _skill(make_skill_dir, "exit 0", name="ok"), skill_id="ok")["blocked"] is False
    blocked = fire_event("BeforeEmailSend", _skill(make_skill_dir, "exit 3", name="no"), skill_id="no")
    assert blocked["blocked"] is True


@needs_sandbox
def test_real_sandbox_hook_cannot_write_into_the_skill_folder(make_skill_dir):
    skill = make_skill_dir({"SKILL.md": "x"}, name="writer")  # the fixture only creates the folder when given files
    target = skill / "pwned.txt"
    # Control: the same kind of write into the throwaway cwd succeeds, so the failure
    # below is the sandbox denying the write and not a shell syntax error.
    (skill / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": [
                    {"event": "BeforeEmailSend", "command": "echo x > ok.txt"},
                    {"event": "BeforeTeamsMessage", "command": f'echo x > "{target}"'},
                ]
            }
        )
    )

    from hooks.executor import fire_event

    assert fire_event("BeforeEmailSend", skill, skill_id="writer")["blocked"] is False
    result = fire_event("BeforeTeamsMessage", skill, skill_id="writer")
    assert result["blocked"] is True
    assert not target.exists()


@needs_sandbox
def test_real_sandbox_hook_with_quoted_argument_runs_verbatim(make_skill_dir):
    skill = make_skill_dir({"SKILL.md": "x"}, name="quoted dir")
    script = 'echo "a b" | findstr /c:"a b"' if os.name == "nt" else "test \"$0\" = sh && echo 'a b' | grep -q 'a b'"
    (skill / "hooks.json").write_text(
        json.dumps({"hooks": [{"event": "BeforeEmailSend", "command": script}]})
    )

    from hooks.executor import fire_event

    assert fire_event("BeforeEmailSend", skill, skill_id="quoted")["blocked"] is False
