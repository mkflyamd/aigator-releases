"""Per-tab task state for the continuation classifier.

Tracks which skills are active, whether the model is awaiting user input
(pending confirmation or data), and a confidence score that decays when
the conversation drifts away from the active task.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

PendingType = Literal["confirmation", "data_input"]
ExpectedFormat = Literal["email", "name", "number", "date", "any"]


@dataclass
class PendingInfo:
    type: PendingType
    expected_format: ExpectedFormat | None
    purpose: str        # human label, e.g. "email_recipient"
    asked_on_turn: int


@dataclass
class TaskState:
    active_skills: list[str] = field(default_factory=list)
    pending: PendingInfo | None = None
    confidence: float = 0.0
    turns_since_last_update: int = 0


class TaskStateStore:
    """In-memory store keyed by context_id (tab ID). No async lock needed —
    all access is from the single asyncio event loop via chat.py."""

    def __init__(self) -> None:
        self._store: dict[str, TaskState] = {}

    def get(self, context_id: str) -> TaskState | None:
        return self._store.get(context_id)

    def get_or_create(self, context_id: str) -> TaskState:
        if context_id not in self._store:
            self._store[context_id] = TaskState()
        return self._store[context_id]

    def update(self, context_id: str, **kwargs) -> TaskState:
        """Update fields on an existing or new state; resets turns_since_last_update."""
        state = self.get_or_create(context_id)
        valid = TaskState.__dataclass_fields__
        for k, v in kwargs.items():
            if k not in valid:
                raise ValueError(f"TaskState has no field '{k}'")
            setattr(state, k, v)
        state.turns_since_last_update = 0
        return state

    def decay(self, context_id: str) -> None:
        """Called after each turn. Clears stale pending after 3 silent turns."""
        state = self._store.get(context_id)
        if state is None:
            return
        state.turns_since_last_update += 1
        if state.turns_since_last_update >= 3 and state.pending is not None:
            state.pending = None
            state.confidence = max(0.0, state.confidence - 0.2)

    def clear(self, context_id: str) -> None:
        self._store.pop(context_id, None)
