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

    @staticmethod
    def _canonical_to_oai(messages: list[dict]) -> list[dict]:
        """Convert Anthropic-canonical history messages to OpenAI wire format.

        Canonical (Anthropic) format stored in conversation_store:
          assistant turn with tools: {role: assistant, content: [{type: tool_use, id, name, input}]}
          assistant turn text:       {role: assistant, content: [{type: text, text: "..."}]}
          tool results:              {role: user, content: [{type: tool_result, tool_use_id, content}]}
          user text:                 {role: user, content: "..." | [{type: text, text: "..."}]}

        OpenAI wire format needed by the API:
          assistant with tools: {role: assistant, content: null, tool_calls: [{id, type, function}]}
          assistant text:       {role: assistant, content: "..."}
          tool results:         [{role: tool, tool_call_id: "...", content: "..."}]  (one per result)
          user text:            {role: user, content: "..."}
        """
        oai: list[dict] = []
        for m in messages:
            role = m.get("role")
            content = m.get("content")

            # ── Legacy OpenAI-format passthrough (pre-migration history) ──
            # Sessions stored before canonical migration may still have OpenAI-wire
            # messages. Pass them through as-is so old history stays usable.
            if role == "tool":
                oai.append(m)
                continue
            if role == "assistant" and m.get("tool_calls"):
                oai.append(m)
                continue

            if role == "assistant":
                if isinstance(content, list):
                    tool_use_blocks = [b for b in content if b.get("type") == "tool_use"]
                    text_blocks = [b for b in content if b.get("type") == "text"]
                    text = "".join(b.get("text", "") for b in text_blocks)
                    if tool_use_blocks:
                        oai.append({
                            "role": "assistant",
                            "content": text or None,
                            "tool_calls": [
                                {
                                    "id": b["id"],
                                    "type": "function",
                                    "function": {
                                        "name": b["name"],
                                        "arguments": json.dumps(b.get("input", {})),
                                    },
                                }
                                for b in tool_use_blocks
                            ],
                        })
                    else:
                        oai.append({"role": "assistant", "content": text or ""})
                elif isinstance(content, str):
                    oai.append({"role": "assistant", "content": content})
                else:
                    # None / no content — emit empty string rather than dropping so
                    # any following tool messages remain paired correctly
                    oai.append({"role": "assistant", "content": ""})

            elif role == "user":
                if isinstance(content, list):
                    tool_result_blocks = [b for b in content if b.get("type") == "tool_result"]
                    if tool_result_blocks:
                        # Expand each tool_result into a separate role=tool message
                        for b in tool_result_blocks:
                            tr_content = b.get("content", "")
                            if isinstance(tr_content, list):
                                tr_content = " ".join(
                                    x.get("text", "") for x in tr_content if x.get("type") == "text"
                                )
                            oai.append({
                                "role": "tool",
                                "tool_call_id": b.get("tool_use_id", ""),
                                "content": tr_content or "",
                            })
                    else:
                        text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
                        oai.append({"role": "user", "content": text})
                else:
                    oai.append({"role": "user", "content": content or ""})

            else:
                # Preserve any other roles (system, etc.) as-is
                oai.append(m)

        return oai

    async def stream_turn(self, model, system, messages, tools, max_tokens=8192) -> AsyncIterator[StreamEvent]:
        # Convert system to string
        if isinstance(system, str):
            system_text = system
        else:
            system_text = " ".join(b.get("text", "") for b in system if b.get("type") == "text")

        oai_messages = [{"role": "system", "content": system_text}] + self._canonical_to_oai(messages)

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

    def build_assistant_message(self, raw_content) -> dict:
        """Convert OpenAI raw_content to Anthropic canonical format for storage.

        raw_content is either:
          - dict with tool_calls: {role, content, tool_calls: [{id, type, function}]}
          - dict with text only:  {role, content: "..."}
        Returns Anthropic canonical: {role: assistant, content: [blocks]}
        """
        if isinstance(raw_content, dict) and raw_content.get("tool_calls"):
            blocks: list[dict] = []
            text = raw_content.get("content") or ""
            if text:
                blocks.append({"type": "text", "text": text})
            for tc in raw_content["tool_calls"]:
                fn = tc.get("function", {})
                args_str = fn.get("arguments", "{}")
                try:
                    args = json.loads(args_str) if args_str else {}
                except json.JSONDecodeError:
                    args = {}
                blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": fn.get("name", ""),
                    "input": args,
                })
            return {"role": "assistant", "content": blocks}
        # Plain text response
        text = raw_content.get("content", "") if isinstance(raw_content, dict) else ""
        # Always emit at least one text block — Anthropic API rejects content: []
        return {"role": "assistant", "content": [{"type": "text", "text": text or ""}]}

    def build_tool_result_message(self, tool_calls: list[ToolCall], results: list[dict]) -> dict:
        """Build tool results in Anthropic canonical format for storage.

        Returns a single user message with tool_result content blocks,
        matching what AnthropicProvider produces so history is uniform.
        """
        if not tool_calls:
            raise ValueError("build_tool_result_message called with empty tool_calls list")
        content: list[dict] = []
        for tc, result in zip(tool_calls, results):
            result_str = result if isinstance(result, str) else json.dumps(result, default=str)
            content.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": result_str,
            })
        return {"role": "user", "content": content}

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
        mdl = model or self._profile.get("model", "Claude-Haiku-4.5")
        msgs = [{"role": "user", "content": prompt}]
        try:
            response = self._client.chat.completions.create(
                model=mdl, max_tokens=max_tokens, messages=msgs,
            )
        except Exception as err:
            # Newer OpenAI models (gpt-5.x, gpt-4o, o1, o3) reject max_tokens —
            # retry with max_completion_tokens (same pattern as stream_turn).
            err_str = str(err)
            if "max_tokens" in err_str and "max_completion_tokens" in err_str:
                response = self._client.chat.completions.create(
                    model=mdl, max_completion_tokens=max_tokens, messages=msgs,
                )
            else:
                raise
        return (response.choices[0].message.content or "").strip()
