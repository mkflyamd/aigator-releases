"""Native shell execution — run_shell tool (bash/WSL -> PowerShell -> cmd)."""

import os
import re
import subprocess
import time

SKILL_ID = "shell_runner"
# Foundational capability: gh/git/CLI access must be visible on every turn, not
# gated behind skill selection/inference (the brittle path that kept hiding it).
ALWAYS_ON = True

# ── Shell auto-detection (checked once at import time) ──────────────────────

def _detect_shell() -> tuple:
    """Return (shell_name, argv_prefix). Checked in priority order."""
    # Priority 1: bash via WSL
    try:
        r = subprocess.run(["wsl.exe", "bash", "--version"],
                           capture_output=True, timeout=3)
        if r.returncode == 0:
            return "bash", ["wsl.exe", "bash", "-c"]
    except Exception:
        pass

    # Priority 2: bash via Git Bash
    git_bash = r"C:\Program Files\Git\bin\bash.exe"
    if os.path.isfile(git_bash):
        try:
            r = subprocess.run([git_bash, "--version"],
                               capture_output=True, timeout=3)
            if r.returncode == 0:
                return "bash", [git_bash, "-c"]
        except Exception:
            pass

    # Priority 3: PowerShell
    try:
        r = subprocess.run(["powershell.exe", "-Command", "$PSVersionTable"],
                           capture_output=True, timeout=5)
        if r.returncode == 0:
            return "powershell", ["powershell.exe", "-Command"]
    except Exception:
        pass

    # Priority 4: cmd (always available on Windows)
    return "cmd", ["cmd.exe", "/c"]


_DETECTED_SHELL, _DETECTED_ARGV = _detect_shell()

# Delete-op blocklist — statement-level check, not substring (issue #76).
# Substring match false-positived on heredoc bodies and command arguments
# that merely *mention* these words (e.g. "echo 'rm is dangerous'").
_DELETE_COMMANDS = {
    "rm", "del", "rmdir", "rd", "deltree", "format", "remove-item", "ri",
}

# Strip heredoc bodies before scanning. Matches: <<EOF ... \nEOF, <<'EOF' ... \nEOF, <<-EOF ... \n\tEOF
_HEREDOC_RE = re.compile(
    r"<<-?\s*['\"]?(\w+)['\"]?.*?\n.*?^\s*\1\s*$",
    re.DOTALL | re.MULTILINE,
)

# Shell statement separators — split command into individual statements
_STATEMENT_SEP_RE = re.compile(r"(?:;|&&|\|\||\||\n|\r)")


def _find_delete_command(command: str):
    """Find a destructive command invocation in `command`.

    Strips heredoc bodies, splits on shell separators, and checks the first
    token of each statement against the delete-command set. This avoids
    false positives from heredoc text or command arguments that merely
    mention these words.

    Returns (matched_token, position) where matched_token is the offending
    command name as it appeared in the source and position is its character
    offset in the original command, or (None, -1) if nothing matched.
    """
    stripped = _HEREDOC_RE.sub("", command)
    for stmt in _STATEMENT_SEP_RE.split(stripped):
        stmt = stmt.strip()
        if not stmt:
            continue
        # Strip leading env-var assignments and sudo/command prefixes
        tokens = stmt.split()
        idx = 0
        while idx < len(tokens) and (
            "=" in tokens[idx] and not tokens[idx].startswith(("-", "/"))
            or tokens[idx] in ("sudo", "command", "exec", "time", "nohup")
        ):
            idx += 1
        if idx >= len(tokens):
            continue
        raw = tokens[idx]
        first = raw.lower().lstrip("\\/")
        # Handle path-prefixed commands like /usr/bin/rm or ./rm
        first = first.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if first in _DELETE_COMMANDS:
            return raw, command.find(raw)
    return None, -1


def _has_delete_command(command: str) -> bool:
    """Boolean wrapper around _find_delete_command."""
    token, _ = _find_delete_command(command)
    return token is not None


def _tool_run_shell(
    command: str,
    shell: str = "",
    cwd: str = "",
    timeout: int = 60,
) -> dict:
    """Execute a shell command and return stdout, stderr, exit_code, shell_used, runtime_ms."""
    # Safety: block delete operations (statement-level, heredoc-aware)
    _del_token, _del_pos = _find_delete_command(command)
    if _del_token is not None:
        return {
            "error": (
                f"Delete operations are blocked: matched command '{_del_token}' "
                f"at position {_del_pos}. Ask the user to run this command manually."
            ),
            "stdout": "", "stderr": "", "exit_code": -1,
            "shell_used": _DETECTED_SHELL, "runtime_ms": 0,
        }

    # Resolve which shell to use
    if shell == "bash":
        argv_prefix = _DETECTED_ARGV if _DETECTED_SHELL == "bash" else ["cmd.exe", "/c"]
        shell_used = "bash"
    elif shell == "powershell":
        argv_prefix = ["powershell.exe", "-Command"]
        shell_used = "powershell"
    elif shell == "cmd":
        argv_prefix = ["cmd.exe", "/c"]
        shell_used = "cmd"
    else:
        argv_prefix = _DETECTED_ARGV
        shell_used = _DETECTED_SHELL

    cwd_path = cwd or os.path.expanduser("~")

    start = time.monotonic()
    try:
        proc = subprocess.run(
            argv_prefix + [command],
            cwd=cwd_path,
            capture_output=True,
            timeout=timeout,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        result = {
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
            "exit_code": proc.returncode,
            "shell_used": shell_used,
            "runtime_ms": elapsed_ms,
        }
        if proc.returncode != 0:
            result["error"] = f"Command exited with code {proc.returncode}"
        return result

    except subprocess.TimeoutExpired:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {
            "stdout": "", "stderr": "", "exit_code": -1,
            "shell_used": shell_used, "runtime_ms": elapsed_ms,
            "error": f"Command timed out after {timeout}s.",
        }
    except Exception as exc:
        return {
            "stdout": "", "stderr": "", "exit_code": -1,
            "shell_used": shell_used, "runtime_ms": 0,
            "error": str(exc),
        }


TOOL_DEFS = [
    {
        "name": "run_shell",
        "description": (
            "Run a shell command (bash/WSL, PowerShell, or cmd). "
            "Auto-detects the best available shell. Returns stdout, stderr, exit_code, shell_used, runtime_ms. "
            "Delete operations (rm, del, rmdir, Remove-Item, format) are blocked — tell the user to run those manually. "
            "Use file_ops tools for simple read/write/list — use run_shell when you need a full command pipeline."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute",
                },
                "shell": {
                    "type": "string",
                    "enum": ["bash", "powershell", "cmd"],
                    "description": "Override auto-detected shell (optional)",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory — defaults to user home (optional)",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds — default 60 (optional)",
                },
            },
            "required": ["command"],
        },
    }
]

TOOL_STATUS = {
    "run_shell": "Running shell command...",
}

TOOL_HANDLERS = {
    "run_shell": _tool_run_shell,
}
