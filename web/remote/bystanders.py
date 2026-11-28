"""AI Gator terminal sessions that Remote did not start and that are waiting for their user.

Only the fact that one waits, whether it is a permission or a question, and the tool's name are read:
never a command, a path or a question. Remote does not answer these; chat only points the user back
to the app."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from remote import prompts
from remote.session_host import Project


@dataclass(frozen=True)
class Seen:
    pty_id: str
    project: Project
    prompt: prompts.Prompt


class TerminalWatch(Protocol):
    def waiting(self, skip: set[str]) -> list[Seen]: ...


class LocalTerminalWatch:
    """The terminals this backend holds, read from the agent-state files their hooks write."""

    def waiting(self, skip: set[str]) -> list[Seen]:
        """Blocking. `skip` is the terminals Remote itself runs, whose prompts are handled elsewhere."""
        import agent_handoff
        import agent_state
        from routes import terminal
        from skills.code_agent import projects

        labels = terminal.live_pty_labels()
        candidates = [
            pty_id
            for pty_id, meta in labels.items()
            if pty_id not in skip and meta.get("remote_pinned") != "1" and meta.get("project_id")
        ]
        redact = agent_handoff.Redactor(agent_handoff._configured_api_keys())
        known: dict[str, Project | None] = {}
        found: list[Seen] = []
        for pty_id, state in agent_state.read_states(candidates).items():
            if state["state"] != "asking":
                continue
            project_id = labels[pty_id]["project_id"]
            if project_id not in known:
                meta = projects.get_project(project_id)
                repo = (meta or {}).get("repo_path")
                known[project_id] = Project(id=meta["name"], name=meta["name"], repo_path=repo) if repo else None
            project = known[project_id]
            if project is None:
                continue
            entry = terminal.get_pty_session(pty_id)
            if entry is not None and entry.last_user_input > state["at"]:
                continue
            found.append(Seen(pty_id, project, _stand_in(pty_id, state["at"], redact)))
        return found


def _stand_in(pty_id: str, at: float, redact) -> prompts.Prompt:
    """A prompt with no content: the hook payload is read for the tool's name and dropped."""
    import agent_state

    found = agent_state.read_prompt(pty_id)
    payload = found["payload"] if found else None
    tool = payload.get("tool_name") if payload else None
    tool = tool if isinstance(tool, str) else ""
    pid = hashlib.sha256(f"app:{pty_id}:{at}".encode()).hexdigest()[:12]
    if not tool or tool == "AskUserQuestion":
        return prompts.Prompt(pid, prompts.APP_ONLY, at=at)
    shown, _ = prompts._plain(tool, prompts.TOOL_MAX_CHARS, redact)
    return prompts.Prompt(pid, prompts.PERMISSION_APP, tool=shown, at=at)
