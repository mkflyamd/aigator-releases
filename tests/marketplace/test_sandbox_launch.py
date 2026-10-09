import sandbox
from marketplace import sandbox_launch as L
from marketplace.permissions import Permissions


def _run(skill_dir, perms=Permissions(), argv=("python", "x.py")):
    return L.run_in_sandbox("demo", "tool", list(argv), skill_dir, L.new_run_dir(), perms, 30)


def test_request_shape_default_is_no_network_no_extra_paths(fake_sandbox, make_skill_dir):
    skill = make_skill_dir({"SKILL.md": "x"})
    fake_sandbox.result = sandbox.SandboxResult(returncode=0, stdout="ok", stderr="", timed_out=False)
    run = _run(skill)
    assert run.ok and run.stdout == "ok" and run.returncode == 0
    req = fake_sandbox.requests[0]
    assert req.network is False
    assert list(req.read_paths) == [] and list(req.write_paths) == []
    assert skill.resolve() in [p.resolve() for p in req.runtime_paths]
    assert req.timeout == 30
    assert "ANTHROPIC_API_KEY" not in req.env and "GATEWAY_USER_ID" not in req.env


def test_network_only_for_an_approved_non_empty_declaration(fake_sandbox, make_skill_dir):
    skill = make_skill_dir({"SKILL.md": "x"})
    _run(skill, Permissions(network=("a.example.com",)))
    _run(skill, Permissions(network=("a.example.com",), invalid=True))
    assert [r.network for r in fake_sandbox.requests] == [True, False]


def test_declared_folders_become_read_paths(fake_sandbox, make_skill_dir, tmp_path):
    skill = make_skill_dir({"SKILL.md": "x"})
    docs = tmp_path / "docs"
    docs.mkdir()
    _run(skill, Permissions(filesystem=(str(docs),)))
    assert [p.resolve() for p in fake_sandbox.requests[0].read_paths] == [docs.resolve()]


def test_run_folder_is_the_working_folder_not_the_skill_folder(fake_sandbox, make_skill_dir):
    skill = make_skill_dir({"SKILL.md": "x"})
    _run(skill)
    assert fake_sandbox.requests[0].cwd != skill


def test_failures_fail_closed_and_never_run_unsandboxed(fake_sandbox, make_skill_dir):
    skill = make_skill_dir({"SKILL.md": "x"})
    for exc in (sandbox.SandboxUnavailable("no sandbox"), sandbox.SandboxRunError("boom"), OSError("ledger")):
        fake_sandbox.raises = exc
        run = _run(skill)
        assert run.ok is False and run.error
    fake_sandbox.raises = None


def test_timeout_is_reported(fake_sandbox, make_skill_dir):
    skill = make_skill_dir({"SKILL.md": "x"})
    fake_sandbox.result = sandbox.SandboxResult(returncode=-1, stdout="", stderr="", timed_out=True)
    run = _run(skill)
    assert run.ok and run.timed_out


def test_a_protected_skill_folder_is_refused_before_launch(fake_sandbox):
    from pathlib import Path

    run = _run(Path.home())
    assert run.ok is False
    assert fake_sandbox.requests == []


def test_every_launch_is_logged(fake_sandbox, make_skill_dir, caplog):
    import logging

    skill = make_skill_dir({"SKILL.md": "x"})
    with caplog.at_level(logging.INFO, logger="aigator.skill_audit"):
        _run(skill, Permissions(network=("a.example.com",)))
    assert "skill-launch skill=demo kind=tool network=true declared_hosts=a.example.com" in caplog.text
