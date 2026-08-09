"""Provider-neutral wire event stream — the only vocabulary loom_core's loop
consumes off a Provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True, slots=True)
class TextDelta:
    type: Literal["text_delta"] = field(default="text_delta", init=False)
    text: str = ""


@dataclass(frozen=True, slots=True)
class ThinkingDelta:
    type: Literal["thinking_delta"] = field(default="thinking_delta", init=False)
    thinking: str = ""


@dataclass(frozen=True, slots=True)
class ToolCallStart:
    type: Literal["tool_call_start"] = field(default="tool_call_start", init=False)
    id: str = ""
    name: str = ""


@dataclass(frozen=True, slots=True)
class ToolCallDelta:
    type: Literal["tool_call_delta"] = field(default="tool_call_delta", init=False)
    id: str = ""
    arguments_fragment: str = ""


@dataclass(frozen=True, slots=True)
class ToolCallEnd:
    type: Literal["tool_call_end"] = field(default="tool_call_end", init=False)
    id: str = ""


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class StreamEnd:
    type: Literal["stream_end"] = field(default="stream_end", init=False)
    stop_reason: Literal["end_turn", "tool_use", "max_tokens", "error"] = "end_turn"
    usage: Usage | None = None


@dataclass(frozen=True, slots=True)
class StreamError:
    type: Literal["stream_error"] = field(default="stream_error", init=False)
    message: str = ""
    retryable: bool = False


StreamEvent = (
    TextDelta
    | ThinkingDelta
    | ToolCallStart
    | ToolCallDelta
    | ToolCallEnd
    | StreamEnd
    | StreamError
)
