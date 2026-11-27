"""The relay's data: A2A v1.0 messages and tasks, plus the endpoints that send and receive them."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

META_KEY = "ai.gator.relay"


class TaskState(str, Enum):
    SUBMITTED = "TASK_STATE_SUBMITTED"
    WORKING = "TASK_STATE_WORKING"
    COMPLETED = "TASK_STATE_COMPLETED"
    FAILED = "TASK_STATE_FAILED"
    CANCELED = "TASK_STATE_CANCELED"
    INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
    REJECTED = "TASK_STATE_REJECTED"
    AUTH_REQUIRED = "TASK_STATE_AUTH_REQUIRED"

    @property
    def terminal(self) -> bool:
        return self in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED, TaskState.REJECTED)


@dataclass(frozen=True)
class Endpoint:
    """Something that can send or receive: a terminal agent (`pty:<uuid>`) or a chat tab (`chat:<tab>`)."""

    id: str
    name: str = ""
    project_id: str | None = None

    @property
    def kind(self) -> str:
        return self.id.partition(":")[0]

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "project_id": self.project_id}


def pty_endpoint(pty_id: str, name: str = "", project_id: str | None = None) -> Endpoint:
    return Endpoint(f"pty:{pty_id}", name, project_id)


def chat_endpoint(tab: str, name: str = "", project_id: str | None = None) -> Endpoint:
    return Endpoint(f"chat:{tab}", name, project_id)


def new_id() -> str:
    return str(uuid.uuid4())


def iso(at: float) -> str:
    return datetime.fromtimestamp(at, timezone.utc).isoformat(timespec="seconds")


@dataclass
class Task:
    id: str
    context_id: str
    message_id: str
    sender: Endpoint
    target: Endpoint | None
    text: str
    hop: int
    created_at: float
    state: TaskState = TaskState.SUBMITTED
    code: str = ""
    reason: str = ""
    delivery: str = ""
    extra: dict = field(default_factory=dict)

    def as_a2a(self) -> dict:
        """The task as an A2A Task. The relay's own fields live under one namespaced metadata key."""
        status: dict = {"state": self.state.value, "timestamp": iso(self.created_at)}
        if self.reason:
            status["message"] = {
                "messageId": new_id(),
                "role": "ROLE_AGENT",
                "parts": [{"text": self.reason}],
            }
        relay_meta: dict = {
            "sender": self.sender.as_dict(),
            "target": self.target.as_dict() if self.target else None,
            "hop": self.hop,
            "delivery": self.delivery,
            "code": self.code,
            **self.extra,
        }
        return {
            "id": self.id,
            "contextId": self.context_id,
            "status": status,
            "history": [
                {
                    "messageId": self.message_id,
                    "contextId": self.context_id,
                    "taskId": self.id,
                    "role": "ROLE_USER",
                    "parts": [{"text": self.text}],
                    "metadata": {META_KEY: {"sender": self.sender.as_dict(), "hop": self.hop}},
                }
            ],
            "metadata": {META_KEY: relay_meta},
        }
