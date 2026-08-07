# tests/test_events.py
from __future__ import annotations

import pytest

from loom_core.events import (
    AgentEndEvent,
    AgentErrorEvent,
    AgentEvent,
    AgentStartEvent,
    AssistantMessageEvent,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    StopReason,
    StreamPartKind,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
    ToolExecutionUpdateEvent,
    TurnEndEvent,
    TurnStartEvent,
)
from loom_core.messages import Message, Role, TextBlock
from loom_core.tools import ToolOutcome


def test_stream_part_kind_values() -> None:
    assert StreamPartKind.TEXT_START == "text_start"
    assert StreamPartKind.TEXT_DELTA == "text_delta"
    assert StreamPartKind.TEXT_END == "text_end"
    assert StreamPartKind.THINKING_START == "thinking_start"
    assert StreamPartKind.THINKING_DELTA == "thinking_delta"
    assert StreamPartKind.THINKING_END == "thinking_end"
    assert StreamPartKind.TOOLCALL_START == "toolcall_start"
    assert StreamPartKind.TOOLCALL_DELTA == "toolcall_delta"
    assert StreamPartKind.TOOLCALL_END == "toolcall_end"
    assert len(StreamPartKind) == 9


def test_stop_reason_values() -> None:
    assert StopReason.DONE == "done"
    assert StopReason.CANCELLED == "cancelled"
    assert StopReason.ERROR == "error"
    assert len(StopReason) == 3


def test_agent_start_event() -> None:
    event = AgentStartEvent()
    assert isinstance(event, AgentStartEvent)


def test_agent_end_event_defaults_to_done() -> None:
    event = AgentEndEvent()
    assert event.reason is StopReason.DONE


def test_agent_end_event_with_explicit_reason() -> None:
    event = AgentEndEvent(reason=StopReason.CANCELLED)
    assert event.reason is StopReason.CANCELLED


def test_agent_error_event() -> None:
    event = AgentErrorEvent(message="provider timeout", retryable=True)
    assert event.message == "provider timeout"
    assert event.retryable is True


def test_agent_error_event_defaults() -> None:
    event = AgentErrorEvent(message="boom")
    assert event.retryable is False


def test_turn_events() -> None:
    start = TurnStartEvent(turn_index=0)
    end = TurnEndEvent(turn_index=0)
    assert start.turn_index == 0
    assert end.turn_index == 0


def test_message_start_event() -> None:
    event = MessageStartEvent(role="assistant")
    assert event.role == "assistant"


def test_message_update_event() -> None:
    sub = AssistantMessageEvent(kind=StreamPartKind.TEXT_DELTA, block_index=0, delta="hi")
    event = MessageUpdateEvent(assistant_message_event=sub)
    assert event.assistant_message_event is sub
    assert event.assistant_message_event.delta == "hi"


def test_message_end_event() -> None:
    msg = Message(role=Role.ASSISTANT, content=(TextBlock(text="done"),))
    event = MessageEndEvent(message=msg)
    assert event.message is msg


def test_assistant_message_event_defaults() -> None:
    event = AssistantMessageEvent(kind=StreamPartKind.TEXT_START, block_index=1)
    assert event.delta == ""
    assert event.tool_name == ""
    assert event.tool_call_id == ""


def test_assistant_message_event_tool_fields() -> None:
    event = AssistantMessageEvent(
        kind=StreamPartKind.TOOLCALL_START,
        block_index=2,
        tool_name="read_file",
        tool_call_id="call_1",
        delta='{"path": "x.py"}',
    )
    assert event.tool_name == "read_file"
    assert event.tool_call_id == "call_1"
    assert event.delta == '{"path": "x.py"}'


def test_tool_execution_start_event() -> None:
    event = ToolExecutionStartEvent(
        tool_call_id="call_1",
        tool_name="read_file",
        arguments_json='{"path": "math_utils.py"}',
    )
    assert event.tool_call_id == "call_1"
    assert event.tool_name == "read_file"
    assert event.arguments_json == '{"path": "math_utils.py"}'


def test_tool_execution_update_event() -> None:
    event = ToolExecutionUpdateEvent(tool_call_id="call_1", partial_output="chunk\n")
    assert event.partial_output == "chunk\n"


def test_tool_execution_end_event() -> None:
    outcome = ToolOutcome(content="file contents")
    event = ToolExecutionEndEvent(tool_call_id="call_1", outcome=outcome)
    assert event.outcome is outcome
    assert event.outcome.content == "file contents"


def test_events_are_frozen() -> None:
    event = AgentEndEvent(reason=StopReason.DONE)
    with pytest.raises(AttributeError):
        event.reason = StopReason.ERROR  # type: ignore[misc]

    sub = AssistantMessageEvent(kind=StreamPartKind.TEXT_DELTA, block_index=0, delta="x")
    with pytest.raises(AttributeError):
        sub.delta = "y"  # type: ignore[misc]


ALL_EVENT_TYPES = (
    AgentStartEvent,
    AgentEndEvent,
    AgentErrorEvent,
    TurnStartEvent,
    TurnEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    MessageEndEvent,
    ToolExecutionStartEvent,
    ToolExecutionUpdateEvent,
    ToolExecutionEndEvent,
)


@pytest.mark.parametrize("cls", ALL_EVENT_TYPES)
def test_event_is_agent_event(cls: type) -> None:
    """Every concrete event type is a valid member of the AgentEvent union."""
    # Build a minimal valid instance for each class
    if cls is AgentStartEvent:
        instance = AgentStartEvent()
    elif cls is AgentEndEvent:
        instance = AgentEndEvent()
    elif cls is AgentErrorEvent:
        instance = AgentErrorEvent(message="err")
    elif cls is TurnStartEvent:
        instance = TurnStartEvent(turn_index=0)
    elif cls is TurnEndEvent:
        instance = TurnEndEvent(turn_index=0)
    elif cls is MessageStartEvent:
        instance = MessageStartEvent(role="assistant")
    elif cls is MessageUpdateEvent:
        instance = MessageUpdateEvent(
            assistant_message_event=AssistantMessageEvent(
                kind=StreamPartKind.TEXT_START, block_index=0
            )
        )
    elif cls is MessageEndEvent:
        instance = MessageEndEvent(
            message=Message(role=Role.ASSISTANT, content=(TextBlock(text=""),))
        )
    elif cls is ToolExecutionStartEvent:
        instance = ToolExecutionStartEvent(tool_call_id="c1", tool_name="t", arguments_json="{}")
    elif cls is ToolExecutionUpdateEvent:
        instance = ToolExecutionUpdateEvent(tool_call_id="c1", partial_output="")
    elif cls is ToolExecutionEndEvent:
        instance = ToolExecutionEndEvent(tool_call_id="c1", outcome=ToolOutcome(content=""))
    else:
        pytest.fail(f"unhandled class: {cls}")

    assert isinstance(instance, AgentEvent)


def test_agent_error_conventionally_pairs_with_error_stop_reason() -> None:
    """Documented contract: AgentErrorEvent is followed by AgentEndEvent(ERROR)."""
    err = AgentErrorEvent(message="network failure", retryable=True)
    end = AgentEndEvent(reason=StopReason.ERROR)
    assert end.reason is StopReason.ERROR
    assert isinstance(err, AgentEvent)
    assert isinstance(end, AgentEvent)
