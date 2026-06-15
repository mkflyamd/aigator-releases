"""Anthropic (Claude) LLM provider implementation."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, AsyncIterator

import anthropic

from .base import LLMProvider, StreamEvent, ToolCall, TurnResult
from .gateway import LLM_GATEWAY_URL, gateway_headers, profile_headers

logger = logging.getLogger(__name__)

LLM_GATEWAY = LLM_GATEWAY_URL  # re-export for config_routes compatibility
_TIMEOUT = 120.0  # seconds

# Default output-token cap. Must be large enough to hold a tool call's arguments:
# a ~44KB HTML body (e.g. confluence_open_edit_form) is ~15-20K output tokens, so
# a low cap truncates the tool-use JSON mid-stream and the required args get lost.
# Claude Opus 4.x supports 32K output tokens. Override via LLM_MAX_OUTPUT_TOKENS.
_DEFAULT_MAX_TOKENS = int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "32000"))


def _resolve_stop_reason(stop_reason: str, has_tool_calls: bool) -> tuple[str, bool]:
    """Decide the authoritative stop_reason and whether a max_tokens truncation was
    masked. Some gateways return stop_reason='end_turn' (or 'max_tokens') even when
    the response carries tool_use blocks; we override to 'tool_use' so the agent
    loop runs the tools. When the original reason was 'max_tokens', the override
    hides the fact that the turn was cut off mid-tool-call (#32), so we report it
    via the second return value for the caller to surface a user notice.

    Returns (authoritative_stop_reason, truncated_during_tool_call). Pure."""
    truncated = bool(has_tool_calls and stop_reason == "max_tokens")
    if has_tool_calls and stop_reason != "tool_use":
        return "tool_use", truncated
    return stop_reason or "end_turn", truncated


class AnthropicProvider(LLMProvider):
    """LLM provider for Claude models via Anthropic API or a compatible gateway."""

    supports_thinking = False  # enabled per-model at call time
    supports_vision = True

    def __init__(self) -> None:
        self._client: anthropic.Anthropic | None = None
        self._refresh_client()

    def _refresh_client(self) -> None:
        from .registry import get_active_profile
        from .gateway import profile_headers, LLM_GATEWAY_URL
        profile = get_active_profile()
        if profile:
            key = profile.get("api_key", "")
            # Prefer anthropic_url (native Anthropic endpoint with caching) over base_url
            raw_url = profile.get("anthropic_url", "") or profile.get("base_url", "")
            base_url = raw_url.rstrip("/") + "/"
            headers = profile_headers(profile)
        else:
            # Fallback for migration period — use env vars
            import os
            key = os.environ.get("ANTHROPIC_API_KEY", "")
            base_url = (LLM_GATEWAY_URL or "https://api.anthropic.com").rstrip("/") + "/"
            from .gateway import gateway_headers
            headers = gateway_headers(key)
        self._client = anthropic.Anthropic(
            api_key="x-gateway-key",
            base_url=base_url,
            default_headers=headers,
            timeout=_TIMEOUT,
        )

    # ── stream_turn ─────────────────────────────────────────────────────

    async def stream_turn(
        self,
        model: str,
        system: str | list[dict],
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> AsyncIterator[StreamEvent]:
        """Stream one Claude turn. system may be str or pre-built list[dict] for caching.

        Tools should already be normalized via normalize_tool_schema() by the caller.
        """
        import shared

        # Build structured system blocks (required for cache_control)
        if isinstance(system, str):
            sys_blocks: list[dict] = [{"type": "text", "text": system}]
        else:
            sys_blocks = list(system)

        # Cache breakpoint 1: end of system prompt
        if shared.PROMPT_CACHING_ENABLED and sys_blocks:
            sys_blocks[-1] = {**sys_blocks[-1], "cache_control": {"type": "ephemeral"}}

        # Cache breakpoint 2: last tool definition
        cached_tools = list(tools)
        if shared.PROMPT_CACHING_ENABLED and cached_tools:
            last_tool = dict(cached_tools[-1])
            last_tool["cache_control"] = {"type": "ephemeral"}
            cached_tools[-1] = last_tool

        # Cache breakpoint 3: last prior history message (moves forward each turn)
        cached_messages = list(messages)
        if shared.PROMPT_CACHING_ENABLED and len(cached_messages) >= 2:
            idx = len(cached_messages) - 2
            msg = dict(cached_messages[idx])
            content = msg.get("content", "")
            if isinstance(content, str):
                content = [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]
            elif isinstance(content, list) and content:
                content = list(content)
                last_block = dict(content[-1])
                last_block["cache_control"] = {"type": "ephemeral"}
                content[-1] = last_block
            msg["content"] = content
            cached_messages[idx] = msg

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": sys_blocks,
            "messages": cached_messages,
        }
        if cached_tools:
            kwargs["tools"] = cached_tools

        # Stream with automatic continuation when stop_reason == "max_tokens".
        # Claude supports response continuation: append the partial assistant
        # content and re-request; Claude picks up exactly where it left off.
        # When the auto-cap is hit, we surface a UI prompt instead of silently
        # truncating, so the user can decide whether to keep going.
        _MAX_CONTINUATIONS = int(os.environ.get("LLM_MAX_AUTO_CONTINUATIONS", "8"))
        _merged_text: list[str] = []
        _merged_thinking: list[str] = []
        _merged_tool_calls: list = []
        _merged_raw: list[dict] = []
        _merged_usage: dict[str, int] = {}

        for _continuation in range(_MAX_CONTINUATIONS + 1):
            _done_event: dict | None = None
            try:
                async for event in self._stream_with_sdk(kwargs):
                    if event["type"] == "done":
                        _done_event = event
                    else:
                        yield event
            except Exception as exc:
                logger.warning("Streaming failed (%s), falling back to non-streaming", exc)
                async for event in self._fallback_non_streaming(kwargs):
                    if event["type"] == "done":
                        _done_event = event
                    else:
                        yield event

            if _done_event is None:
                break

            # Accumulate across continuations
            _merged_text.append(_done_event.get("text", ""))
            _merged_thinking.append(_done_event.get("thinking", ""))
            _merged_tool_calls.extend(_done_event.get("tool_calls", []))
            _merged_raw.extend(_done_event.get("raw_content", []))
            _u = _done_event.get("usage", {})
            for k, v in _u.items():
                _merged_usage[k] = _merged_usage.get(k, 0) + v

            stop_reason = _done_event.get("stop_reason", "end_turn")

            if stop_reason != "max_tokens" or _continuation == _MAX_CONTINUATIONS:
                # Normal finish or continuation cap reached — emit final done
                if stop_reason == "max_tokens" and _continuation == _MAX_CONTINUATIONS:
                    logger.warning(
                        "[provider] max_tokens after %d continuations — surfacing UI prompt",
                        _MAX_CONTINUATIONS,
                    )
                    try:
                        shared.notify_all({
                            "type": "max_tokens_reached",
                            "continuations": _MAX_CONTINUATIONS,
                            "max_tokens": max_tokens,
                            "message": (
                                f"Claude's response hit the output limit after "
                                f"{_MAX_CONTINUATIONS} auto-continuations "
                                f"(~{_MAX_CONTINUATIONS * max_tokens:,} tokens). "
                                f"Reply with 'continue' to keep going, or break the task into smaller steps."
                            ),
                        })
                    except Exception:
                        pass
                elif _done_event.get("truncated_during_tool_call"):
                    logger.warning(
                        "[provider] max_tokens hit mid-tool-call — recovered but surfacing UI notice",
                    )
                    try:
                        shared.notify_all({
                            "type": "max_tokens_reached",
                            "max_tokens": max_tokens,
                            "message": (
                                "The response was cut off at the output limit while running a "
                                "tool, so part of it may be incomplete. Try breaking your request "
                                "into smaller steps, or ask me to continue."
                            ),
                        })
                    except Exception:
                        pass
                yield {
                    **_done_event,
                    "text": "".join(_merged_text),
                    "thinking": "".join(_merged_thinking),
                    "tool_calls": _merged_tool_calls,
                    "raw_content": _merged_raw,
                    "usage": _merged_usage,
                }
                return

            # max_tokens hit mid-text (no tool calls yet) — continue
            logger.warning(
                "[provider] max_tokens on continuation %d — appending partial and re-requesting",
                _continuation,
            )
            partial_raw = _done_event.get("raw_content", [])
            if partial_raw:
                kwargs["messages"] = list(kwargs["messages"]) + [
                    {"role": "assistant", "content": partial_raw}
                ]

    async def _stream_with_sdk(self, kwargs: dict) -> AsyncIterator[StreamEvent]:
        """Use the Anthropic SDK streaming API.

        Producer runs in a thread (SDK stream context is blocking), pushes events
        to an asyncio.Queue via call_soon_threadsafe; this coroutine yields events
        live as they arrive. This is what makes streaming text + stop button work.
        """
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        SENTINEL: dict = {"__sentinel__": True}

        def _emit(event: dict) -> None:
            """Thread-safe push from producer thread to async consumer."""
            loop.call_soon_threadsafe(queue.put_nowait, event)

        def _producer() -> None:
            text_parts: list[str] = []
            thinking_parts: list[str] = []
            tool_calls: list[ToolCall] = []
            raw_content: list[dict] = []
            usage = {"input_tokens": 0, "output_tokens": 0}
            stop_reason = "end_turn"

            # Current tool accumulation state
            current_tool_id: str | None = None
            current_tool_name: str | None = None
            current_tool_json: str = ""

            try:
                with self._client.messages.stream(**kwargs) as stream:
                    for event in stream:
                        etype = getattr(event, "type", "")

                        if etype == "content_block_start":
                            block = event.content_block
                            btype = getattr(block, "type", "")
                            if btype == "tool_use":
                                current_tool_id = block.id
                                current_tool_name = block.name
                                current_tool_json = ""

                        elif etype == "content_block_delta":
                            delta = event.delta
                            dtype = getattr(delta, "type", "")
                            if dtype == "text_delta":
                                text_parts.append(delta.text)
                                _emit({"type": "text_delta", "text": delta.text})  # stream live
                            elif dtype == "thinking_delta":
                                thinking_parts.append(delta.thinking)
                                _emit({
                                    "type": "thinking_delta",
                                    "text": delta.thinking,
                                    "agent": None,
                                })
                            elif dtype == "input_json_delta":
                                current_tool_json += delta.partial_json

                        elif etype == "content_block_stop":
                            if current_tool_id is not None:
                                try:
                                    inputs = json.loads(current_tool_json) if current_tool_json else {}
                                except json.JSONDecodeError:
                                    inputs = {}
                                    logger.warning(
                                        "[provider] tool_use %r arguments did not parse as JSON "
                                        "(%d chars, likely truncated at max_tokens) — args dropped; "
                                        "execute_tool will reject on missing required params",
                                        current_tool_name, len(current_tool_json),
                                    )
                                tc = ToolCall(
                                    id=current_tool_id,
                                    name=current_tool_name or "",
                                    inputs=inputs,
                                )
                                tool_calls.append(tc)
                                _emit({
                                    "type": "tool_call",
                                    "id": tc.id,
                                    "name": tc.name,
                                    "inputs": tc.inputs,
                                })
                                current_tool_id = None
                                current_tool_name = None
                                current_tool_json = ""

                        elif etype == "message_delta":
                            stop_reason = getattr(event.delta, "stop_reason", "end_turn") or "end_turn"
                            u = getattr(event, "usage", None)
                            if u:
                                usage["output_tokens"] = getattr(u, "output_tokens", 0)

                        elif etype == "message_start":
                            u = getattr(event.message, "usage", None)
                            if u:
                                usage["input_tokens"] = getattr(u, "input_tokens", 0)
                                usage["cache_creation_input_tokens"] = getattr(u, "cache_creation_input_tokens", 0)
                                usage["cache_read_input_tokens"] = getattr(u, "cache_read_input_tokens", 0)
                                print(
                                    f"[cache] creation={usage['cache_creation_input_tokens']}"
                                    f" read={usage['cache_read_input_tokens']}"
                                    f" input={usage['input_tokens']}",
                                    flush=True,
                                )

                    # Build raw_content from the final message
                    final_msg = stream.get_final_message()
                    raw_content = [self._block_to_dict(b) for b in final_msg.content]
                    # Some gateways sometimes skip content_block_stop events for tool_use blocks
                    # during streaming, leaving tool_calls empty even though the final message
                    # contains tool_use blocks. Recover by scanning raw_content as a fallback.
                    if not tool_calls:
                        for _block in raw_content:
                            if _block.get("type") == "tool_use":
                                _tc = ToolCall(
                                    id=_block["id"],
                                    name=_block["name"],
                                    inputs=_block.get("input", {}),
                                )
                                tool_calls.append(_tc)
                                _emit({
                                    "type": "tool_call",
                                    "id": _tc.id,
                                    "name": _tc.name,
                                    "inputs": _tc.inputs,
                                })
                                logger.warning(
                                    "[provider] tool_use block %r found in final_msg but missed"
                                    " in streaming events — recovering from raw_content",
                                    _block["name"],
                                )

                    # Some gateways sometimes return stop_reason="end_turn" (or
                    # "max_tokens") even when the response contains tool_use blocks
                    # (it should be "tool_use"). Override so the agent loop runs the
                    # tools; flag the max_tokens case so the consumer can warn the user.
                    authoritative_stop_reason, truncated_during_tool_call = _resolve_stop_reason(
                        stop_reason, bool(tool_calls)
                    )
                    if tool_calls and (stop_reason or "end_turn") != "tool_use":
                        logger.warning(
                            "[provider] gateway returned stop_reason=%r but %d tool_call(s) present"
                            " — overriding to 'tool_use'",
                            stop_reason or "end_turn", len(tool_calls),
                        )

                _emit({
                    "type": "done",
                    "stop_reason": authoritative_stop_reason,
                    "truncated_during_tool_call": truncated_during_tool_call,
                    "text": "".join(text_parts),
                    "thinking": "".join(thinking_parts),
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

    async def _fallback_non_streaming(self, kwargs: dict) -> AsyncIterator[StreamEvent]:
        """Non-streaming fallback: single blocking API call."""
        response = await asyncio.to_thread(self._client.messages.create, **kwargs)

        text = ""
        thinking = ""
        tool_calls: list[ToolCall] = []

        for block in response.content:
            btype = getattr(block, "type", "")
            if btype == "text":
                text += block.text
                yield {"type": "text_delta", "text": block.text}
            elif btype == "thinking":
                thinking += block.thinking
                yield {"type": "thinking_delta", "text": block.thinking, "agent": None}
            elif btype == "tool_use":
                tc = ToolCall(id=block.id, name=block.name, inputs=block.input)
                tool_calls.append(tc)
                yield {"type": "tool_call", "id": tc.id, "name": tc.name, "inputs": tc.inputs}

        raw_content = [self._block_to_dict(b) for b in response.content]
        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }

        yield {
            "type": "done",
            "stop_reason": response.stop_reason or "end_turn",
            "text": text,
            "thinking": thinking,
            "usage": usage,
            "raw_content": raw_content,
            "tool_calls": tool_calls,
        }

    # ── build_tool_result_message ──────────────────────────────────────

    def build_tool_result_message(
        self,
        tool_calls: list[ToolCall],
        results: list[dict],
    ) -> dict:
        """Build Anthropic-format tool result message.

        Handles _images -> multimodal content blocks.
        Compresses oversized results when accumulated turn size warrants it.
        """
        from context_utils import compress_tool_result
        content: list[dict] = []
        total_chars = 0
        for tc, result in zip(tool_calls, results):
            result = compress_tool_result(tc.name, result, total_chars)
            total_chars += len(result if isinstance(result, str) else json.dumps(result, default=str))
            if isinstance(result, dict) and "_images" in result:
                images = result["_images"]
                result_without_images = {k: v for k, v in result.items() if k != "_images"}
                blocks: list[dict] = [{"type": "text", "text": json.dumps(result_without_images)}]
                for img in images[:5]:
                    blocks.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": img.get("media_type", "image/png"),
                            "data": img["base64"],
                        },
                    })
                    blocks.append({
                        "type": "text",
                        "text": f"[Embedded image: {img.get('name', 'image')}]",
                    })
                content.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": blocks,
                })
            else:
                content.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": json.dumps(result),
                })
        return {"role": "user", "content": content}

    # ── normalize_tool_schema ─────────────────────────────────────────

    def normalize_tool_schema(self, tool: dict) -> dict:
        """Identity transform -- tools are already in Anthropic format."""
        return tool

    def simple_complete(self, prompt: str, model: str | None = None, max_tokens: int = 200) -> str:
        response = self._client.messages.create(
            model=model or "Claude-Haiku-4.5",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in response.content if hasattr(b, "text")).strip()

    # ── helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _block_to_dict(block: Any) -> dict:
        """Convert an Anthropic SDK content block to a plain dict.

        Only includes fields the API accepts — excludes internal SDK fields
        like parsed_output that cause 'Extra inputs are not permitted' errors.
        """
        btype = getattr(block, "type", "unknown")
        if btype == "text":
            return {"type": "text", "text": block.text}
        elif btype == "tool_use":
            return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
        elif btype == "thinking":
            return {"type": "thinking", "thinking": block.thinking}
        else:
            # Fallback: use model_dump but exclude None values and known internal fields
            if hasattr(block, "model_dump"):
                d = block.model_dump(exclude_none=True)
                d.pop("parsed_output", None)
                return d
            return {"type": btype}
