from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class Role(str, Enum):
    """Message producer role."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class TextBlock:
    """Plain visible text."""

    type: Literal["text"] = field(default="text", init=False)
    text: str = ""


@dataclass(frozen=True, slots=True)
class ThinkingBlock:
    """Reasoning content, kept separate from text."""

    type: Literal["thinking"] = field(default="thinking", init=False)
    thinking: str = ""


@dataclass(frozen=True, slots=True)
class ToolCallBlock:
    """Assistant request to invoke a tool. arguments_json stays raw."""

    type: Literal["tool_call"] = field(default="tool_call", init=False)
    id: str = ""
    name: str = ""
    arguments_json: str = "{}"

    def parsed_arguments(self) -> dict[str, Any] | None:
        """Parse arguments_json; return None on failure."""
        try:
            parsed = json.loads(self.arguments_json)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None


@dataclass(frozen=True, slots=True)
class ToolResultBlock:
    """Tool result for a Role.TOOL message."""

    type: Literal["tool_result"] = field(default="tool_result", init=False)
    tool_call_id: str = ""
    content: str = ""
    is_error: bool = False


ContentBlock = TextBlock | ThinkingBlock | ToolCallBlock | ToolResultBlock


@dataclass(frozen=True, slots=True)
class Message:
    """One transcript turn. content order is meaningful."""

    role: Role
    content: tuple[ContentBlock, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def text(self) -> str:
        """Concatenate text blocks only."""
        return "".join(b.text for b in self.content if isinstance(b, TextBlock))

    def tool_calls(self) -> tuple[ToolCallBlock, ...]:
        """Return tool-call blocks in order."""
        return tuple(b for b in self.content if isinstance(b, ToolCallBlock))


def user_message(text: str) -> Message:
    """Build a user message."""
    return Message(role=Role.USER, content=(TextBlock(text=text),))


def system_message(text: str) -> Message:
    """Build a system message."""
    return Message(role=Role.SYSTEM, content=(TextBlock(text=text),))
