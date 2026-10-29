"""Run the GitHub CLI on the host for the model, outside the command sandbox.

The sandbox cannot reach the OS keyring, so `gh` there is never signed in. Here it runs as the
user, with the user's own `gh auth login`; the token saved in Settings is a per-process fallback
(never an exported variable) used only when `gh` is not signed in for the target host.
"""
import os
import re
import shlex
import shutil
import subprocess
from urllib.parse import urlparse

from . import credentials

_COMMANDS = {
    "issue": {"list", "view", "create", "comment", "edit", "close", "reopen", "status"},
    "pr": {"list", "view", "create", "comment", "edit", "review", "ready", "checks", "diff",
           "status", "close", "reopen"},
    "label": {"list", "create", "edit"},
    "run": {"list", "view", "rerun", "cancel"},
    "workflow": {"list", "view"},
    "release": {"list", "view"},
    "repo": {"view", "list"},
    "search": {"repos", "issues", "prs", "code", "commits"},
    "status": set(),
    "api": set(),
}
# Each of these reads a local file into GitHub, redirects the token to another host, or needs a terminal.
_BLOCKED_FLAGS = {"--body-file", "--template", "--input", "--hostname", "--web", "--editor", "--field",
                  "--raw-field"}
_BLOCKED_SHORT = ("-F", "-w", "-e", "-T")
_SHORT_CLUSTER = re.compile(r"-[A-Za-z]{2,}")
_API_FLAGS = {"--jq", "-q", "--paginate", "--slurp", "-i", "--include", "--cache", "--silent",
              "-X", "--method", "-H", "--header"}
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_TOKEN_VARS = ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_ENTERPRISE_TOKEN", "GH_ENTERPRISE_TOKEN")
_MAX_OUTPUT = 20000
_TIMEOUT = 120


def _hosts() -> set[str]:
    hosts = {"github.com", "www.github.com"}
    if credentials.is_enterprise():
        hosts.add(urlparse(credentials.get_base_url()).hostname or "")
    return hosts


def _flag_name(arg: str) -> str:
    return arg.split("=", 1)[0] if arg.startswith("--") else arg


def _flag_value(args: list, i: int) -> str:
    if "=" in args[i] and args[i].startswith("--"):
        return args[i].split("=", 1)[1]
    return args[i + 1] if i + 1 < len(args) else ""


def validate(args) -> str | None:
    """None when the command may run, otherwise why not."""
    if not isinstance(args, list) or not args or not all(isinstance(a, str) and "\0" not in a for a in args):
        return "args must be a non-empty list of strings, without the leading 'gh'."
    group = args[0]
    if group not in _COMMANDS:
        return f"'gh {group}' is not available here. Allowed: {', '.join(sorted(_COMMANDS))}."
    subs = _COMMANDS[group]
    if subs and (len(args) < 2 or args[1] not in subs):
        shown = " ".join(args[:2])
        return f"'gh {shown}' is not available here. Allowed: {', '.join(sorted(subs))}."
    for i, arg in enumerate(args):
        if i == 0:
            continue
        name = _flag_name(arg)
        if name in _BLOCKED_FLAGS or (not arg.startswith("--") and arg.startswith(_BLOCKED_SHORT)):
            return f"{name} is not available here (use --body with the text instead of a file)."
        if _SHORT_CLUSTER.fullmatch(arg) and any(f"-{c}" in _BLOCKED_SHORT for c in arg[1:]):
            return f"{arg} is not available here (pass each short flag separately, and use --body for text)."
        if name in ("-R", "--repo") and not _REPO.fullmatch(_flag_value(args, i)):
            return "--repo must be OWNER/REPO."
        if "://" in arg and (urlparse(arg).scheme != "https" or urlparse(arg).hostname not in _hosts()):
            return "URLs must be https links to the connected GitHub host."
        if group == "api" and arg.startswith("-"):
            if name not in _API_FLAGS:
                return f"gh api is read-only here; {name} is not available."
            value = _flag_value(args, i)
            if name in ("-X", "--method") and value.upper() != "GET":
                return "gh api is read-only here; use a specific gh command to change something."
            if name in ("-H", "--header") and value.lower().lstrip().startswith("authorization"):
                return "The Authorization header cannot be set."
    return None


def _env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _TOKEN_VARS}
    env.update(GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1", NO_COLOR="1", GH_PAGER="cat")
    if credentials.is_enterprise():
        env["GH_HOST"] = urlparse(credentials.get_base_url()).hostname or ""
    return env


def _logged_in(gh: str, env: dict) -> bool:
    cmd = [gh, "auth", "status"]
    if env.get("GH_HOST"):
        cmd += ["--hostname", env["GH_HOST"]]
    try:
        return subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _error(message: str) -> dict:
    return {"error": message, "stdout": "", "stderr": "", "exit_code": -1}


_APPROVAL_MSG = (
    "The user must approve access to this folder first; an approval card is now shown in the chat. Tell the "
    "user briefly what you asked for and why, then stop and wait. When the user says they approved, call "
    "github_gh again with exactly the same args and cwd. If they deny, do not retry."
)


def _authorized_cwd(args: list, cwd: str, context_id: str) -> tuple[str | None, dict | None]:
    """The folder gh may run in, or a result to return as is (a refusal or the user's approval card).

    Same rule as run_shell: the AI Gator working folder is free, any other folder needs the user's approval.
    """
    from sandbox.policy import load_policy
    from skills.code_runner import tools as code_runner
    from skills.shell_runner import tools as shell_runner

    policy = load_policy()
    located = shell_runner._locate_cwd(cwd, policy, code_runner)
    if isinstance(located, str):
        return None, _error(located)
    run_cwd, project, _scratch = located
    if project is None:
        return str(run_cwd), None
    gate = shell_runner._shell_gate(code_runner, shlex.join(["gh", *args]), [project], [], [], context_id, policy)
    if isinstance(gate, dict):
        if gate.get("approval_required"):
            gate = {**gate, "message": _APPROVAL_MSG}
        return None, gate
    return str(run_cwd), None


def run_gh(args, cwd: str | None = None, context_id: str = "", *, max_output: int = _MAX_OUTPUT,
           use_saved_token: bool = True) -> dict:
    problem = validate(args)
    if problem:
        return _error(problem)
    gh = shutil.which("gh")
    if not gh:
        return _error("The GitHub CLI (gh) is not installed. Use the github_* tools instead.")
    cwd, refused = _authorized_cwd(args, cwd or "", context_id)
    if refused:
        return refused
    env = _env()
    secret = ""
    source = "gh login"
    if not _logged_in(gh, env):
        if not use_saved_token:
            return _error("gh is not signed in on this machine. Run 'gh auth login' once.")
        secret = credentials.get_token()
        if not secret:
            return _error("gh is not signed in on this machine and no GitHub token is connected. "
                          "Connect GitHub in Settings, or run 'gh auth login' once.")
        env["GH_ENTERPRISE_TOKEN" if env.get("GH_HOST") else "GH_TOKEN"] = secret
        source = "saved GitHub token"
    try:
        done = subprocess.run([gh, *args], env=env, cwd=cwd, stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=_TIMEOUT, text=True,
                              encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return _error(f"gh timed out after {_TIMEOUT}s.")
    except OSError as exc:
        return _error(f"gh could not start: {exc}")
    out, err = done.stdout, done.stderr
    if secret:
        out, err = out.replace(secret, "***"), err.replace(secret, "***")
    result = {"stdout": out[:max_output], "stderr": err[:_MAX_OUTPUT], "exit_code": done.returncode,
              "auth": source}
    if len(out) > max_output:
        result["truncated"] = True
    if done.returncode:
        result["error"] = f"gh exited with code {done.returncode}: {err.strip()[:500]}"
    return result
