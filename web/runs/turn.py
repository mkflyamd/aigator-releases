"""The chat turn a tool call belongs to. The turn id is the chat task id, so the turn's Stop reaches its runs."""
from __future__ import annotations

import contextvars

current_turn: contextvars.ContextVar[str] = contextvars.ContextVar("run_current_turn", default="")
