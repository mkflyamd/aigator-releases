"""Base types and abstract provider interface for multi-LLM support."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal


@dataclass
class ToolCall:
    """A tool invocation extracted from an LLM response."""
    id: str
    name: str
    inputs: dict[str, Any]


@dataclass
class TurnResult:
    """Complete result of one LLM turn."""
    stop_reason: Literal["tool_use", "end_turn", "max_tokens"]
    text: str
    tool_calls: list[ToolCall]
    raw_content: list[dict]  # plain dicts via model_dump() for msg accumulation
    usage: dict[str, int]
    thinking: str = ""


# StreamEvent types yielded by stream_turn():
#   {"type": "text_delta",     "text": "..."}
#   {"type": "thinking_delta", "text": "...", "agent": None|str}
#   {"type": "tool_call",      "id": "...", "name": "...", "inputs": {...}}
#   {"type": "done",           "stop_reason": "...", "usage": {...},
#                              "raw_content": [...], "tool_calls": [...],
#                              "text": "...", "thinking": "..."}
StreamEvent = dict[str, Any]


class LLMProvider(ABC):
    """Abstract base for LLM providers (Anthropic, OpenAI, DeepSeek, ...)."""

    supports_thinking: bool = False
    supports_vision: bool = True

    @abstractmethod
    async def stream_turn(
        self,
        model: str,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 8192,
    ) -> AsyncIterator[StreamEvent]:
        """Stream one LLM turn. Yields StreamEvent dicts.

        Must yield a final {"type": "done", ...} event.
        """
        ...  # pragma: no cover

    def build_assistant_message(self, raw_content: list[dict]) -> dict | list[dict]:
        """Build the assistant message(s) to append to the conversation.

        Default implementation wraps raw_content as Anthropic-style content blocks.
        OpenAI provider overrides to return the message dict directly.
        """
        return {"role": "assistant", "content": raw_content}

    @abstractmethod
    def build_tool_result_message(
        self,
        tool_calls: list[ToolCall],
        results: list[dict],
    ) -> dict | list[dict]:
        """Build the user-role message carrying tool results back to the model.

        Handles _images -> multimodal content blocks for providers that support vision.
        May return a single dict or a list of dicts (OpenAI needs one per tool call).
        """
        ...  # pragma: no cover

    @abstractmethod
    def normalize_tool_schema(self, tool: dict) -> dict:
        """Convert from Anthropic-native tool format to this provider's format.

        Anthropic format: {name, description, input_schema}
        OpenAI format:    {type: "function", function: {name, description, parameters}}
        """
        ...  # pragma: no cover

    def simple_complete(self, prompt: str, model: str | None = None, max_tokens: int = 200) -> str:
        """Synchronous single-turn completion — no tools, no streaming.

        Used for lightweight internal calls like skill classification.
        Subclasses must override. Returns the assistant text or raises.
        """
        raise NotImplementedError(f"{type(self).__name__} does not implement simple_complete")
