"""Real Provider: any OpenAI-compatible /chat/completions endpoint.

Holds one httpx.Client per instance, reused across turns, with a clean
close() and context-manager interface.
"""

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
    ToolCallDelta,
    ToolCallEnd,
    ToolCallStart,
    Usage,
)
from loom_provider.provider import ProviderMessage, ProviderToolSchema

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass
class OpenAICompatibleProvider:
    base_url: str
    api_key: str
    model: str
    timeout_s: float = 60.0

    _client: httpx.Client | None = field(default=None, init=False, repr=False)

    def _get_client(self) -> httpx.Client:
        """Lazily create, then reuse, one client per provider instance."""
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout_s)
        return self._client

    def close(self) -> None:
        """Release the HTTP client. Safe to call more than once."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> OpenAICompatibleProvider:
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
        open_tool_calls: dict[int, str] = {}
        client = self._get_client()
        try:
            with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
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
                    yield from self._handle_line(line, open_tool_calls)
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
        if system:
            wire_messages.append({"role": "system", "content": system})
        for m in messages:
            entry: dict[str, Any] = {"role": m.role, "content": m.content}
            if m.tool_call_id:
                entry["tool_call_id"] = m.tool_call_id
            if m.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": tc.arguments_json,
                        },
                    }
                    for tc in m.tool_calls
                ]
            wire_messages.append(entry)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": wire_messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters_json_schema,
                    },
                }
                for t in tools
            ]
        return payload

    def _handle_line(self, line: str, open_tool_calls: dict[int, str]) -> Iterator[StreamEvent]:
        if not line.startswith("data: "):
            return
        data = line[len("data: ") :]
        if data == "[DONE]":
            return
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            yield StreamError(message=f"malformed SSE chunk: {data[:200]}")
            return

        choices = chunk.get("choices") or []
        if not choices:
            return
        delta = choices[0].get("delta", {})
        finish_reason = choices[0].get("finish_reason")

        if content := delta.get("content"):
            yield TextDelta(text=content)

        for tc in delta.get("tool_calls") or []:
            index = tc.get("index", 0)
            fn = tc.get("function", {})
            if tc.get("id") and index not in open_tool_calls:
                open_tool_calls[index] = tc["id"]
                yield ToolCallStart(id=tc["id"], name=fn.get("name", ""))
            call_id = open_tool_calls.get(index) or tc.get("id")
            if not call_id:
                continue
            if args_fragment := fn.get("arguments"):
                yield ToolCallDelta(id=call_id, arguments_fragment=args_fragment)

        if finish_reason:
            for call_id in open_tool_calls.values():
                yield ToolCallEnd(id=call_id)
            stop: Literal["end_turn", "tool_use", "max_tokens"]
            if finish_reason == "tool_calls":
                stop = "tool_use"
            elif finish_reason == "length":
                stop = "max_tokens"
            else:
                stop = "end_turn"
            usage_raw = chunk.get("usage")
            usage = (
                Usage(
                    input_tokens=usage_raw.get("prompt_tokens", 0),
                    output_tokens=usage_raw.get("completion_tokens", 0),
                )
                if usage_raw
                else None
            )
            yield StreamEnd(stop_reason=stop, usage=usage)
