"""Program names in a shell command, for "Always allow this" with network.

Returns None for anything that is not a plain sequence of ordinary programs
(interpreters, wrappers, substitutions, code arguments, unreadable quoting).
None means the permission can be granted for this task only, never saved.
Over-inclusive splitting is deliberate: a false None is safe, a false set is not.
"""
from __future__ import annotations

import re
import shlex

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")
_SPLIT = re.compile(r";|&&|\|\||\||&|\n|\r")
_FD_DUP = re.compile(r"\d*>&\d*|&>")
_FORBIDDEN = ("$(", "`", "<(", ">(", "<<")
_INTERPRETERS = frozenset(
    "python python3 py node deno bun ruby perl php bash sh zsh pwsh powershell cmd wsl npx".split()
)
_KEYWORDS = frozenset(
    "eval source . exec env xargs sudo nohup nice time timeout command builtin watch start call find "
    "if then else elif fi for while until do done case esac function select !".split()
)
_CODE_FLAGS = frozenset("-c -e -command -encodedcommand -ec --eval -exec -execdir -ok".split())
_SUFFIXES = (".exe", ".cmd", ".bat")


def programs_in(command: str) -> set[str] | None:
    if not command or not command.strip():
        return None
    if any(marker in command for marker in _FORBIDDEN):
        return None
    try:
        shlex.split(command)
    except ValueError:
        return None
    programs: set[str] = set()
    for statement in _SPLIT.split(_FD_DUP.sub(" ", command)):
        tokens = statement.split()
        if not tokens:
            continue
        first = tokens[0]
        if not _NAME.fullmatch(first):
            return None
        name = first.lower()
        for suffix in _SUFFIXES:
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        if name in _INTERPRETERS or name in _KEYWORDS:
            return None
        if any(token.lower() in _CODE_FLAGS for token in tokens):
            return None
        programs.add(name)
    return programs or None
