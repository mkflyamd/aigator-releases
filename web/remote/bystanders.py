"""AI Gator terminal sessions that Remote did not start and that are waiting for their user.

Their prompt is read from the hook file the agent wrote, the same way as for a session Remote started,
so chat shows the same redacted, capped text and offers the same answers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from remote import prompts
from remote.session_host import Project, read_prompt


@dataclass(frozen=True)
class Seen:
    pty_id: str
    project: Project
    prompt: prompts.Prompt
    state_at: float


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
            prompt = read_prompt(pty_id, redact) or prompts.unreadable(state["at"], prompts.UNSEEN_WHY)
            found.append(Seen(pty_id, project, prompt, state["at"]))
        return found
