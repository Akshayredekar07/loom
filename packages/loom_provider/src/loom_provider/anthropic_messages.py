"""Real Provider: Anthropic /v1/messages endpoint."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from loom_provider.events import (
    StreamEnd,
    StreamError,
    StreamEvent,
    TextDelta,
    ThinkingDelta,
    ToolCallDelta,
    ToolCallEnd,
    ToolCallStart,
    Usage,
)
from loom_provider.provider import ProviderMessage, ProviderToolSchema

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_ANTHROPIC_VERSION = "2023-06-01"


@dataclass
class AnthropicStreamState:
    open_tool_calls: dict[int, str] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class AnthropicMessagesProvider:
    base_url: str
    api_key: str
    model: str
    max_tokens: int = 8192
    timeout_s: float = 60.0

    _client: httpx.Client | None = field(default=None, init=False, repr=False)

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout_s)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> AnthropicMessagesProvider:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def stream(
        self,
        messages: tuple[ProviderMessage, ...],
        *,
        system: str | None = None,
        tools: tuple[ProviderToolSchema, ...] = (),
    ) -> Iterator[StreamEvent]:
        payload = self._build_payload(messages, system=system, tools=tools)
        state = AnthropicStreamState()
        client = self._get_client()
        headers = {
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        try:
            with client.stream(
                "POST",
                f"{self.base_url}/messages",
                headers=headers,
                json=payload,
            ) as response:
                if response.status_code != 200:
                    body = response.read().decode("utf-8", errors="replace")
                    yield StreamError(
                        message=f"HTTP {response.status_code}: {body[:500]}",
                        retryable=response.status_code in _RETRYABLE_STATUS,
                    )
                    return
                for line in response.iter_lines():
                    yield from self._handle_line(line, state)
        except httpx.TimeoutException as exc:
            yield StreamError(message=f"request timed out: {exc}", retryable=True)
        except httpx.HTTPError as exc:
            yield StreamError(message=f"transport error: {exc}", retryable=True)

    def _build_payload(
        self,
        messages: tuple[ProviderMessage, ...],
        *,
        system: str | None,
        tools: tuple[ProviderToolSchema, ...],
    ) -> dict[str, Any]:
        wire_messages: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "tool":
                wire_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": message.tool_call_id,
                                "content": message.content,
                            }
                        ],
                    }
                )
                continue
            if message.role == "assistant" and message.tool_calls:
                blocks: list[dict[str, Any]] = []
                if message.content:
                    blocks.append({"type": "text", "text": message.content})
                for tool_call in message.tool_calls:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tool_call.id,
                            "name": tool_call.name,
                            "input": json.loads(tool_call.arguments_json or "{}"),
                        }
                    )
                wire_messages.append({"role": "assistant", "content": blocks})
                continue
            wire_messages.append({"role": message.role, "content": message.content})

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": wire_messages,
            "stream": True,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.parameters_json_schema,
                }
                for tool in tools
            ]
        return payload

    def _handle_line(self, line: str, state: AnthropicStreamState) -> Iterator[StreamEvent]:
        if not line.startswith("data: "):
            return
        data = line[len("data: ") :]
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            yield StreamError(message=f"malformed SSE chunk: {data[:200]}")
            return
        yield from self._handle_event(event, state)

    def _handle_event(
        self, event: dict[str, Any], state: AnthropicStreamState
    ) -> Iterator[StreamEvent]:
        event_type = event.get("type")
        if event_type == "message_start":
            message = event.get("message") or {}
            usage = message.get("usage") or {}
            state.input_tokens = int(usage.get("input_tokens", 0))
            return

        if event_type == "content_block_start":
            block = event.get("content_block") or {}
            if block.get("type") == "tool_use":
                index = int(event.get("index", 0))
                call_id = str(block.get("id", ""))
                state.open_tool_calls[index] = call_id
                yield ToolCallStart(id=call_id, name=str(block.get("name", "")))
            return

        if event_type == "content_block_delta":
            delta = event.get("delta") or {}
            delta_type = delta.get("type")
            index = int(event.get("index", 0))
            if delta_type == "text_delta":
                if text := delta.get("text"):
                    yield TextDelta(text=text)
            elif delta_type == "thinking_delta":
                if thinking := delta.get("thinking"):
                    yield ThinkingDelta(thinking=thinking)
            elif delta_type == "input_json_delta":
                tool_call_id = state.open_tool_calls.get(index)
                partial_json = delta.get("partial_json")
                if tool_call_id and isinstance(partial_json, str) and partial_json:
                    yield ToolCallDelta(id=tool_call_id, arguments_fragment=partial_json)
            return

        if event_type == "content_block_stop":
            index = int(event.get("index", 0))
            if index in state.open_tool_calls:
                yield ToolCallEnd(id=state.open_tool_calls.pop(index))
            return

        if event_type == "message_delta":
            delta = event.get("delta") or {}
            usage = event.get("usage") or {}
            if output_tokens := usage.get("output_tokens"):
                state.output_tokens = int(output_tokens)
            stop_reason = delta.get("stop_reason")
            if not stop_reason:
                return
            for call_id in list(state.open_tool_calls.values()):
                yield ToolCallEnd(id=call_id)
            state.open_tool_calls.clear()
            stop: Literal["end_turn", "tool_use", "max_tokens"]
            if stop_reason == "tool_use":
                stop = "tool_use"
            elif stop_reason == "max_tokens":
                stop = "max_tokens"
            else:
                stop = "end_turn"
            usage_obj = Usage(
                input_tokens=state.input_tokens,
                output_tokens=state.output_tokens,
            )
            yield StreamEnd(stop_reason=stop, usage=usage_obj)
            return

        if event_type == "error":
            error = event.get("error") or {}
            message = str(error.get("message") or event)
            yield StreamError(message=message, retryable=False)
