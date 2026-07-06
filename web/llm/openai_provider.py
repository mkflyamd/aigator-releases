"""OpenAI-wire-format LLM provider.

Handles: enterprise gateways, direct OpenAI, and any OpenAI-compatible
endpoint (Ollama, Groq, Mistral, Together AI, etc.).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

from openai import OpenAI

from .base import LLMProvider, StreamEvent, ToolCall
from .gateway import normalize_openai_base_url, profile_headers

logger = logging.getLogger(__name__)
_TIMEOUT = 120.0


class OpenAIProvider(LLMProvider):
    supports_thinking = False
    supports_vision = True

    def __init__(self, profile: dict) -> None:
        self._profile = profile
        self._client = self._build_client(profile)

    def _build_client(self, profile: dict) -> OpenAI:
        base_url = normalize_openai_base_url(profile.get("base_url", ""))
        api_key = profile.get("api_key", "") or "no-key"
        extra_headers = profile_headers(profile)
        return OpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers=extra_headers,
            timeout=_TIMEOUT,
        )

    def refresh_client(self, profile: dict) -> None:
        self._profile = profile
        self._client = self._build_client(profile)

    async def stream_turn(self, model, system, messages, tools, max_tokens=8192) -> AsyncIterator[StreamEvent]:
        # Convert system to string
        if isinstance(system, str):
            system_text = system
        else:
            system_text = " ".join(b.get("text", "") for b in system if b.get("type") == "text")

        oai_messages = [{"role": "system", "content": system_text}] + list(messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": oai_messages,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        SENTINEL: dict = {"__sentinel__": True}

        def _emit(event: dict) -> None:
            """Thread-safe push from producer thread to async consumer."""
            loop.call_soon_threadsafe(queue.put_nowait, event)

        def _producer() -> None:
            text_parts: list[str] = []
            tool_calls_acc: dict[int, dict] = {}
            usage = {"input_tokens": 0, "output_tokens": 0}
            stop_reason = "end_turn"

            def _create_stream(call_kwargs):
                return self._client.chat.completions.create(**call_kwargs)

            try:
                try:
                    stream_ctx = _create_stream(kwargs)
                except Exception as e:
                    err_str = str(e)
                    # Newer OpenAI models (gpt-5.x, gpt-4o, o1, o3) reject max_tokens — retry with max_completion_tokens
                    if "max_tokens" in err_str and "max_completion_tokens" in err_str:
                        retry_kwargs = {k: v for k, v in kwargs.items() if k != "max_tokens"}
                        retry_kwargs["max_completion_tokens"] = kwargs.get("max_tokens")
                        stream_ctx = _create_stream(retry_kwargs)
                    # Inference backends without tool support (vLLM, SGLang, llama.cpp, Ollama, TGI, LiteLLM)
                    # return various 400s — retry without tools so plain prompts still work.
                    elif any(p in err_str.lower() for p in (
                        "tool choice requires", "enable-auto-tool-choice",  # vLLM
                        "tool call is not supported",                        # SGLang
                        "does not support tools", "tools are not supported", # llama.cpp / Ollama / TGI
                        "toolchoice not supported", "tool_choice not supported",  # LiteLLM
                        "does not support tool", "tool use is not supported",
                    )):
                        retry_kwargs = {k: v for k, v in kwargs.items() if k != "tools"}
                        stream_ctx = _create_stream(retry_kwargs)
                    elif "model_terms_required" in err_str:
                        import re as _re
                        url_match = _re.search(r'https://\S+', err_str)
                        url = url_match.group(0).rstrip("'\"") if url_match else "https://console.groq.com"
                        raise RuntimeError(
                            f"This model requires terms acceptance before use. "
                            f"Visit {url} to accept, then try again."
                        ) from e
                    elif "rate_limit_exceeded" in err_str or "tokens per minute" in err_str.lower():
                        import re as _re
                        limit = _re.search(r'Limit (\d+)', err_str)
                        requested = _re.search(r'Requested (\d+)', err_str)
                        detail = f" (limit {limit.group(1)}, request needs {requested.group(1)})" if limit and requested else ""
                        raise RuntimeError(
                            f"Request too large for this model's rate limit{detail}. "
                            f"Try a model with a higher token limit, shorten your conversation, or upgrade your API plan."
                        ) from e
                    else:
                        raise

                with stream_ctx as stream:
                    for chunk in stream:
                        choice = chunk.choices[0] if chunk.choices else None
                        if choice is None:
                            continue
                        delta = choice.delta

                        if delta.content:
                            text_parts.append(delta.content)
                            _emit({"type": "text_delta", "text": delta.content})  # stream text deltas live

                        if delta.tool_calls:
                            for tc_delta in delta.tool_calls:
                                idx = tc_delta.index
                                if idx not in tool_calls_acc:
                                    tool_calls_acc[idx] = {"id": "", "name": "", "json": ""}
                                if tc_delta.id:
                                    tool_calls_acc[idx]["id"] = tc_delta.id
                                if tc_delta.function:
                                    if tc_delta.function.name:
                                        tool_calls_acc[idx]["name"] = tc_delta.function.name
                                    if tc_delta.function.arguments:
                                        tool_calls_acc[idx]["json"] += tc_delta.function.arguments

                        if choice.finish_reason:
                            stop_reason = "tool_use" if choice.finish_reason == "tool_calls" else "end_turn"

                        if chunk.usage:
                            usage["input_tokens"] = chunk.usage.prompt_tokens or 0
                            usage["output_tokens"] = chunk.usage.completion_tokens or 0

                tool_calls: list[ToolCall] = []
                for acc in tool_calls_acc.values():
                    try:
                        inputs = json.loads(acc["json"]) if acc["json"] else {}
                    except json.JSONDecodeError:
                        inputs = {}
                    tc = ToolCall(id=acc["id"], name=acc["name"], inputs=inputs)
                    tool_calls.append(tc)
                    _emit({"type": "tool_call", "id": tc.id, "name": tc.name, "inputs": tc.inputs})

                if tool_calls and stop_reason != "tool_use":
                    stop_reason = "tool_use"

                if tool_calls:
                    raw_content = {"role": "assistant", "content": None, "tool_calls": [
                        {
                            "id": acc["id"],
                            "type": "function",
                            "function": {"name": acc["name"], "arguments": acc["json"]},
                        }
                        for acc in tool_calls_acc.values()
                    ]}
                else:
                    raw_content = {"role": "assistant", "content": "".join(text_parts)}

                _emit({
                    "type": "done",
                    "stop_reason": stop_reason,
                    "text": "".join(text_parts),
                    "thinking": "",
                    "usage": usage,
                    "raw_content": raw_content,
                    "tool_calls": tool_calls,
                })
            except BaseException as exc:
                _emit({"type": "__error__", "exc": exc})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, SENTINEL)

        producer_task = asyncio.create_task(asyncio.to_thread(_producer))
        try:
            while True:
                event = await queue.get()
                if event is SENTINEL:
                    break
                if event.get("type") == "__error__":
                    raise event["exc"]
                yield event
        finally:
            if not producer_task.done():
                producer_task.cancel()
            try:
                await producer_task
            except (asyncio.CancelledError, Exception):
                pass

    def build_assistant_message(self, raw_content):
        """OpenAI raw_content is already a full message dict — return as-is."""
        return raw_content

    def build_tool_result_message(self, tool_calls: list[ToolCall], results: list[dict]) -> list[dict]:
        """OpenAI expects one role=tool message per tool call."""
        if not tool_calls:
            raise ValueError("build_tool_result_message called with empty tool_calls list")
        msgs = []
        for i, tc in enumerate(tool_calls):
            result = results[i] if i < len(results) else {}
            content = result if isinstance(result, str) else json.dumps(result, default=str)
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": content})
        return msgs

    def normalize_tool_schema(self, tool: dict) -> dict:
        """Anthropic format → OpenAI function format."""
        return {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
            },
        }

    def simple_complete(self, prompt: str, model: str | None = None, max_tokens: int = 200) -> str:
        response = self._client.chat.completions.create(
            model=model or self._profile.get("model", "Claude-Haiku-4.5"),
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return (response.choices[0].message.content or "").strip()
