"""What an agent is asking the user (a permission or a question), as chat copy, and the keys that answer it.

The content comes from the agent's own PermissionRequest hook payload, not from the screen. A reply is
mapped to exact keystrokes here; nothing is ever typed for an option this module does not offer, so
"always allow" and "don't ask again" cannot be reached from chat."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Callable

import agent_wake

from remote.commands import _tidy, agent_prefix, elapsed_words, next_block, system_reply

COMMAND_MAX_CHARS = 150
PATH_MAX_CHARS = 200
TOOL_MAX_CHARS = 80
QUESTION_MAX_CHARS = 600
LABEL_MAX_CHARS = 60
DESCRIPTION_MAX_CHARS = 80
CHOICES_MAX = 9
ELLIPSIS = "…"

ENTER, DOWN, ESCAPE = "\r", "\x1b[B", "\x1b"
KEY_PAUSE_SECONDS = 0.2

PERMISSION, PERMISSION_APP, QUESTION, DRAFT, APP_ONLY = "permission", "permission_app", "question", "draft", "app"

# Tools whose dialog was seen live to make option 1 a plain Yes, so one Enter is exactly "allow once".
# A tool not listed here (ExitPlanMode's option 1 switches to auto-accept; MCP dialogs were not seen) is app-only.
ENTER_ALLOW_TOOLS = frozenset({"Bash", "Edit", "Write"})

_PATH_KEYS = ("file_path", "path", "notebook_path")
_DRAFT_WORDS = {"send", "post", "reply", "draft", "forward", "compose", "publish"}
_NUMBER_RE = re.compile(r"^\s*(\d{1,2})\s*[.)]?\s*$")
_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z])(?=[A-Z])")

ALLOW, DENY = "allow", "deny"
ALLOWED, DENIED = "Allowed once.", "Denied."
CANCELLED = "Cancelled. The session is still running."
ANSWER_SENT = "Sent your answer."
ANSWER_MAX_CHARS = 500
ALREADY_ANSWERED = "That was already answered in AI Gator."
OPEN_APP_COMMAND = "Open AI Gator to review the whole command before allowing it."
OPEN_APP_DRAFT = "Open AI Gator to review it and send."
OPEN_APP_QUESTION = "Open AI Gator to answer this one."
OPEN_APP_PERMISSION = "Open AI Gator to review and answer this permission."
ESC_OPTION = "`esc` to cancel it. The session keeps running."
TYPE_OPTION = "Or type your own answer."


@dataclass(frozen=True)
class Choice:
    label: str
    description: str = ""


@dataclass(frozen=True)
class Prompt:
    id: str
    kind: str
    tool: str = ""
    path: str = ""
    path_label: str = "Path"
    command: str = ""
    cut: bool = False
    at: float = 0.0
    question: str = ""
    choices: tuple[Choice, ...] = ()
    why_app: str = ""

    @property
    def answerable(self) -> bool:
        return self.kind in (PERMISSION, QUESTION)

    @property
    def lead(self) -> str:
        return {
            PERMISSION: "permission",
            PERMISSION_APP: "permission",
            QUESTION: "a question",
            DRAFT: "a draft to review",
            APP_ONLY: "a question",
        }[self.kind]


@dataclass(frozen=True)
class Answer:
    keys: tuple[str, ...]
    done: str
    ends_turn: bool = False


@dataclass(frozen=True)
class Refused:
    reason: str


def _plain(text: object, limit: int, redact: Callable[[str], str]) -> tuple[str, bool]:
    """One printable line, redacted, cut with an ellipsis. The flag says whether it differs from the original."""
    raw = str(text or "").strip()
    one = " ".join(redact(raw).split())
    one = "".join(ch for ch in one if ch.isprintable())
    if len(one) <= limit:
        return one, one != raw
    return one[:limit].rstrip() + ELLIPSIS, True


def _is_draft_tool(tool: str) -> bool:
    if not tool.startswith("mcp__"):
        return False
    action = tool.split("__", 2)[-1]
    return any(word.lower() in _DRAFT_WORDS for word in _SPLIT_RE.split(action))


def _shown_path(raw: str, cwd: str) -> str:
    path = raw.replace("\\", "/")
    root = cwd.replace("\\", "/").rstrip("/")
    if root and path.lower().startswith(root.lower() + "/"):
        return path[len(root) + 1 :]
    return path


def _question(tool_input: dict, redact: Callable[[str], str]) -> tuple[str, tuple[Choice, ...], str]:
    """(question, choices, why_app). `why_app` is set when the menu cannot be answered by one number."""
    questions = tool_input.get("questions")
    if not isinstance(questions, list) or not questions or not isinstance(questions[0], dict):
        return "", (), "it could not be read"
    first = questions[0]
    text, _ = _plain(first.get("question"), QUESTION_MAX_CHARS, redact)
    options = first.get("options")
    choices: list[Choice] = []
    for option in options if isinstance(options, list) else []:
        if not isinstance(option, dict):
            continue
        label, _ = _plain(option.get("label"), LABEL_MAX_CHARS, redact)
        description, _ = _plain(option.get("description"), DESCRIPTION_MAX_CHARS, redact)
        if label:
            choices.append(Choice(label, description if description.lower() != label.lower() else ""))
    if len(questions) > 1:
        return text, tuple(choices), "it has several questions"
    if first.get("multiSelect") is True:
        return text, tuple(choices), "it takes several answers"
    if not choices or len(choices) > CHOICES_MAX:
        return text, tuple(choices), "its options could not be read"
    return text, tuple(choices), ""


def parse(payload: dict, at: float, redact: Callable[[str], str] = str) -> Prompt | None:
    """None when the payload names no tool. `at` is the event time, so the same prompt shown twice has two ids."""
    tool = payload.get("tool_name")
    if not isinstance(tool, str) or not tool:
        return None
    raw_input = payload.get("tool_input")
    tool_input = raw_input if isinstance(raw_input, dict) else {}
    digest = json.dumps([at, tool, tool_input], sort_keys=True, default=str).encode("utf-8")
    pid = hashlib.sha256(digest).hexdigest()[:12]
    shown_tool, _ = _plain(tool, TOOL_MAX_CHARS, redact)
    if tool == "AskUserQuestion":
        text, choices, why = _question(tool_input, redact)
        kind = APP_ONLY if why else QUESTION
        return Prompt(pid, kind, tool=shown_tool, at=at, question=text, choices=choices, why_app=why)
    if _is_draft_tool(tool):
        return Prompt(pid, DRAFT, tool=shown_tool, at=at)
    cwd = str(payload.get("cwd") or "")
    command, command_cut = "", False
    if tool == "Bash":
        raw = str(tool_input.get("command") or "")
        command, command_cut = _plain(raw, COMMAND_MAX_CHARS, redact)
    path, path_cut, label = "", False, "Path"
    for key in _PATH_KEYS:
        if tool_input.get(key):
            path, path_cut = _plain(_shown_path(str(tool_input[key]), cwd), PATH_MAX_CHARS, redact)
            break
    else:
        if tool == "WebFetch" and tool_input.get("url"):
            path, path_cut = _plain(tool_input["url"], PATH_MAX_CHARS, redact)
            label = "URL"
    shown = bool(command) if tool == "Bash" else bool(path)
    kind = PERMISSION if tool in ENTER_ALLOW_TOOLS and shown else PERMISSION_APP
    return Prompt(
        pid, kind, tool=shown_tool, at=at, path=path, path_label=label, command=command, cut=command_cut or path_cut
    )


UNSEEN_WHY = "it could not be read from the terminal"


def unreadable(at: float, why: str = "it is too large to show here") -> Prompt:
    """A prompt that could not be read (too large, not the hook's JSON, or no file at all): there is still something to answer."""
    return Prompt(hashlib.sha256(f"unreadable:{at}".encode()).hexdigest()[:12], APP_ONLY, at=at, why_app=why)


def _digits(count: int) -> str:
    return f"1 to {count}" if count > 2 else "1 or 2"


def interrupt(prompt: Prompt) -> Answer:
    """Escape: cancels whatever the agent is asking and ends its turn. The session itself stays up."""
    return Answer((ESCAPE,), CANCELLED, ends_turn=True)


def resolve(prompt: Prompt, text: str, free_text: bool = False) -> Answer | Refused:
    """The keys that answer `prompt` with the user's reply, or why the reply is not an answer. With `free_text`,
    a reply to a question that is not one of its choices is typed as the question's own "other" answer: only for a
    quote-reply to the question or a tagged message, never for a note that merely arrived while it waited.
    Whatever is typed is plain text: control characters and escape sequences never reach the terminal."""
    reply = agent_wake.clean(text)
    if prompt.kind == PERMISSION:
        word = reply.lower().rstrip(".!")
        if word == ALLOW and not prompt.cut:
            return Answer((ENTER,), ALLOWED)
        if word == DENY:
            return Answer((ESCAPE,), DENIED, ends_turn=True)
        return Refused("this session is waiting on a permission.")
    if prompt.kind != QUESTION:
        return Refused("this one has to be answered in AI Gator.")
    match = _NUMBER_RE.match(reply)
    if match:
        number = int(match.group(1))
        if not 1 <= number <= len(prompt.choices):
            return Refused(f"pick {_digits(len(prompt.choices))}, or answer it in AI Gator.")
        return _pick(prompt, number)
    for number, choice in enumerate(prompt.choices, 1):
        if reply.lower() == choice.label.lower():
            return _pick(prompt, number)
    if free_text and reply:
        if len(reply) > ANSWER_MAX_CHARS:
            return Refused(
                f"that answer is {len(reply)} characters and the limit is {ANSWER_MAX_CHARS}. "
                "Shorten it and send it again, or answer it in AI Gator."
            )
        return Answer((*(DOWN,) * len(prompt.choices), reply, ENTER), ANSWER_SENT)
    if reply:
        return Refused(
            f"pick {_digits(len(prompt.choices))}. To answer in your own words, reply to this message "
            "or start with `@gator`."
        )
    return Refused(f"pick {_digits(len(prompt.choices))}, or answer it in AI Gator.")


_FOOTER = "Esctocancel"
_FOOTER_TAIL = re.compile(r"(?:·Tabtoamend|·ctrl\+etoexplain)*")


_BOXES = re.compile(r"[\s─-╿]+")
CHUNK_CHARS = 60


def _identity(prompt: Prompt) -> str:
    """The part of a permission that must be on screen for it to be this one: the start of its command, or the name
    of its file (the dialog may show the path relative to somewhere else)."""
    shown = prompt.command or prompt.path.replace("\\", "/").rsplit("/", 1)[-1]
    return _BOXES.sub("", shown.split("[REDACTED]")[0].rstrip(ELLIPSIS))[:CHUNK_CHARS]


def permission_dialog_showing(tail: str, prompt: Prompt | None = None) -> bool:
    """True when the newest thing on the terminal (ANSI already stripped) is a permission dialog with a plain
    "1. Yes" and nothing after its footer. Whitespace is dropped because the terminal paints spaces as cursor moves.
    With `prompt`, the tool call shown for that dialog must also be the one the prompt describes: two permissions
    asked back to back leave the first one's dialog on screen while the hook file already describes the second."""
    flat = re.sub(r"\s+", "", tail)
    start = flat.rfind("Doyouwantto")
    if start < 0:
        return False
    dialog = flat[start:]
    cut = dialog.rfind(_FOOTER)
    if cut < 0 or "1.Yes" not in dialog[:cut]:
        return False
    if _FOOTER_TAIL.fullmatch(dialog[cut + len(_FOOTER) :]) is None:
        return False
    if prompt is None:
        return True
    identity = _identity(prompt)
    call = max(flat.rfind("●", 0, start), 0)
    return bool(identity) and identity in _BOXES.sub("", flat[call:])


def _pick(prompt: Prompt, number: int) -> Answer:
    return Answer((*(DOWN,) * (number - 1), ENTER), f"Got it: {prompt.choices[number - 1].label}.")


def _facts(prompt: Prompt) -> list[str]:
    lines = [f"Tool: {prompt.tool}"]
    if prompt.command:
        lines.append(f"Command: {prompt.command}")
    if prompt.path:
        lines.append(f"{prompt.path_label}: {prompt.path}")
    return lines


def _options(prompt: Prompt) -> list[str]:
    if prompt.kind == PERMISSION:
        if prompt.cut:
            return [f"`{DENY}` to deny.", OPEN_APP_COMMAND]
        return [f"`{ALLOW}` to allow once.", f"`{DENY}` to deny."]
    if prompt.kind == QUESTION:
        out = []
        for number, choice in enumerate(prompt.choices, 1):
            out.append(f"`{number}` {choice.label}" + (f": {choice.description}" if choice.description else ""))
        return [*out, TYPE_OPTION]
    if prompt.kind == PERMISSION_APP:
        return [OPEN_APP_PERMISSION, ESC_OPTION]
    return [OPEN_APP_QUESTION, ESC_OPTION]


def label(session: str, project: str) -> str:
    """The long form, with the session, because this message is the one the user replies to."""
    return agent_prefix(session, project, several=True)


def waiting_message(
    session: str,
    project: str,
    prompt: Prompt,
    *,
    refused: str = "",
    waited: float | None = None,
    prefix: str = "",
) -> str:
    """One message for one waiting session. `refused` turns it into the answer to a reply that was not sent.
    `waited` is set only for a message that went out after a wait. `prefix` replaces the label of a session
    that is not Remote's own (another agent, a terminal)."""
    tag = prefix or label(session, project)
    after = f", waiting {elapsed_words(waited)}" if waited is not None else ""
    head = f"Not sent: {refused}" if refused else f"Needs you: {prompt.lead}{after}."
    if prompt.kind == DRAFT:
        return _tidy(f"{tag} {head}\n\n{next_block([OPEN_APP_DRAFT, ESC_OPTION])}")
    body = _facts(prompt) if prompt.kind in (PERMISSION, PERMISSION_APP) else ([prompt.question] if prompt.question else [])
    if prompt.kind == APP_ONLY and prompt.why_app:
        body.append(f"This one cannot be answered here: {prompt.why_app}.")
    return _tidy(f"{tag} {head}\n" + "\n".join(body) + f"\n\n{next_block(_options(prompt))}")


def more_waiting(rows: list[tuple[str, float]]) -> str:
    """The one line naming sessions that wait with no message of their own. rows are (session, seconds waiting)."""
    names = ", ".join(f"{name} ({elapsed_words(seconds)})" for name, seconds in rows)
    noun = "session needs" if len(rows) == 1 else "sessions need"
    return system_reply(f"{len(rows)} more {noun} you: {names}.", ["`list` to see them."])


def confirmation(session: str, project: str, done: str, *, prefix: str = "") -> str:
    return _tidy(f"{prefix or label(session, project)} {done}")


def answer_word(prompt: Prompt | None) -> str:
    """What `list` suggests typing after `{session}: `."""
    if prompt is not None and prompt.kind == PERMISSION and not prompt.cut:
        return ALLOW
    return "a number" if prompt is not None and prompt.kind == QUESTION else "your answer"
