"""Provider boundary: conversation in, StreamEvent stream out. This package
owns its own message and tool shapes (ProviderMessage, ProviderToolSchema)"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from loom_provider.events import StreamEvent


@dataclass(frozen=True, slots=True)
class ProviderToolCall:
    id: str
    name: str
    arguments_json: str


@dataclass(frozen=True, slots=True)
class ProviderMessage:
    role: str
    content: str = ""
    tool_call_id: str | None = None
    tool_calls: tuple[ProviderToolCall, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ProviderToolSchema:
    name: str
    description: str
    parameters_json_schema: dict[str, Any]


class Provider(Protocol):
    def stream(
        self,
        messages: tuple[ProviderMessage, ...],
        *,
        system: str | None = None,
        tools: tuple[ProviderToolSchema, ...] = (),
    ) -> Iterator[StreamEvent]: ...

    def close(self) -> None: ...
