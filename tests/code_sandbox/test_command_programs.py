import pytest

from sandbox.command_programs import programs_in


@pytest.mark.parametrize("command, expected", [
    ("git status", {"git"}),
    ("git pull && npm install", {"git", "npm"}),
    ("curl https://example.com | tee out.txt", {"curl", "tee"}),
    ("echo hi; echo there", {"echo"}),
    ("GIT.EXE status", {"git"}),
    ("npm.cmd install", {"npm"}),
    ("git log 2>&1", {"git"}),
    ("git status\nnpm test", {"git", "npm"}),
    ("echo 'it is'", {"echo"}),
])
def test_plain_programs(command, expected):
    assert programs_in(command) == expected


@pytest.mark.parametrize("command", [
    "",
    "   ",
    "python script.py",
    "python3 -m http.server",
    "py -3 x.py",
    "node app.js",
    "npx create-thing",
    "bash -c 'curl x'",
    "sh run.sh",
    "powershell -Command Get-Date",
    "cmd /c dir",
    "wsl ls",
    "git status && python x.py",
    "echo $(whoami)",
    "echo `whoami`",
    "diff <(ls) <(ls)",
    "cat <<EOF",
    "eval ls",
    "source env.sh",
    ". ./env.sh",
    "env FOO=1 git status",
    "xargs rm",
    "sudo ls",
    "time git status",
    "find . -exec ls {} +",
    "FOO=bar git status",
    "./run.sh",
    "C:\\tools\\x.exe",
    "/usr/bin/git status",
    "(git status)",
    "{ git status; }",
    "echo 'unbalanced",
    "echo \"a;b\"",
    "git status -c core.pager=x",
    "if true; then git status; fi",
    "for f in a b; do git add $f; done",
    "!git",
])
def test_unsaveable_commands_return_none(command):
    assert programs_in(command) is None
