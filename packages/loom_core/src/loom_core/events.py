from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from loom_core.messages import Message
from loom_core.tools import ToolOutcome


class StreamPartKind(StrEnum):
    TEXT_START = "text_start"
    TEXT_DELTA = "text_delta"
    TEXT_END = "text_end"
    THINKING_START = "thinking_start"
    THINKING_DELTA = "thinking_delta"
    THINKING_END = "thinking_end"
    TOOLCALL_START = "toolcall_start"
    TOOLCALL_DELTA = "toolcall_delta"
    TOOLCALL_END = "toolcall_end"


@dataclass(frozen=True, slots=True)
class AssistantMessageEvent:
    """One streaming fragment of an in-progress assistant message."""

    kind: StreamPartKind
    block_index: int
    delta: str = ""
    tool_name: str = ""
    tool_call_id: str = ""


@dataclass(frozen=True, slots=True)
class MessageStartEvent:
    role: str


@dataclass(frozen=True, slots=True)
class MessageUpdateEvent:
    assistant_message_event: AssistantMessageEvent


@dataclass(frozen=True, slots=True)
class MessageEndEvent:
    """The authoritative finished message. Persist or replay from this,
    never from accumulated deltas."""

    message: Message


@dataclass(frozen=True, slots=True)
class ToolExecutionStartEvent:
    tool_call_id: str
    tool_name: str
    arguments_json: str


@dataclass(frozen=True, slots=True)
class ToolExecutionUpdateEvent:
    """Optional incremental output while a tool runs (e.g. streaming stdout
    from a long-running bash command)."""

    tool_call_id: str
    partial_output: str


@dataclass(frozen=True, slots=True)
class ToolExecutionEndEvent:
    tool_call_id: str
    outcome: ToolOutcome


@dataclass(frozen=True, slots=True)
class TurnStartEvent:
    turn_index: int


@dataclass(frozen=True, slots=True)
class TurnEndEvent:
    turn_index: int


@dataclass(frozen=True, slots=True)
class AgentStartEvent:
    pass


class StopReason(StrEnum):
    DONE = "done"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class AgentEndEvent:
    reason: StopReason = StopReason.DONE


@dataclass(frozen=True, slots=True)
class AgentErrorEvent:
    """Provider, network, or parsing failure severe enough to end the run.

    Always emitted immediately before an AgentEndEvent with
    reason=StopReason.ERROR. Kept as a separate event so renderers can show a
    distinct error state and session files have a greppable record of why a
    run stopped. ``retryable`` lets the harness decide whether to offer retry
    without string-matching the message.
    """

    message: str
    retryable: bool = False


AgentEvent = (
    AgentStartEvent
    | AgentEndEvent
    | AgentErrorEvent
    | TurnStartEvent
    | TurnEndEvent
    | MessageStartEvent
    | MessageUpdateEvent
    | MessageEndEvent
    | ToolExecutionStartEvent
    | ToolExecutionUpdateEvent
    | ToolExecutionEndEvent
)
