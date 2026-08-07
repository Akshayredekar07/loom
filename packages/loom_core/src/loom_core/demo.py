from __future__ import annotations

from collections.abc import Iterator

from loom_core.events import (
    AgentEndEvent,
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
from loom_core.messages import (
    Message,
    Role,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from loom_core.tools import ToolOutcome


def _stream(block_index: int, text: str, *, thinking: bool = False) -> Iterator[MessageUpdateEvent]:
    """Yield start/delta/.../end events for one text or thinking block, word by word."""
    start_kind = StreamPartKind.THINKING_START if thinking else StreamPartKind.TEXT_START
    delta_kind = StreamPartKind.THINKING_DELTA if thinking else StreamPartKind.TEXT_DELTA
    end_kind = StreamPartKind.THINKING_END if thinking else StreamPartKind.TEXT_END

    words = text.split(" ")
    yield MessageUpdateEvent(
        assistant_message_event=AssistantMessageEvent(kind=start_kind, block_index=block_index)
    )
    for i, word in enumerate(words):
        piece = word if i == 0 else " " + word
        yield MessageUpdateEvent(
            assistant_message_event=AssistantMessageEvent(
                kind=delta_kind, block_index=block_index, delta=piece
            )
        )
    yield MessageUpdateEvent(
        assistant_message_event=AssistantMessageEvent(kind=end_kind, block_index=block_index)
    )


def fake_agent_run(task: str, filename: str) -> Iterator[AgentEvent]:
    """Simulates an agent that thinks, calls a read_file tool, then answers using the result."""
    yield AgentStartEvent()

    # Turn 0: think, decide to read the file, call the tool
    yield TurnStartEvent(turn_index=0)
    yield MessageStartEvent(role="assistant")

    thinking_text = f"The user wants: {task}. I should read {filename} before answering."
    yield from _stream(block_index=0, text=thinking_text, thinking=True)

    plan_text = f"Let me check {filename} first."
    yield from _stream(block_index=1, text=plan_text)

    tool_call_id = "call_1"
    arguments_json = f'{{"path": "{filename}"}}'
    yield MessageUpdateEvent(
        assistant_message_event=AssistantMessageEvent(
            kind=StreamPartKind.TOOLCALL_START,
            block_index=2,
            tool_name="read_file",
            tool_call_id=tool_call_id,
        )
    )
    yield MessageUpdateEvent(
        assistant_message_event=AssistantMessageEvent(
            kind=StreamPartKind.TOOLCALL_DELTA,
            block_index=2,
            delta=arguments_json,
            tool_call_id=tool_call_id,
        )
    )
    yield MessageUpdateEvent(
        assistant_message_event=AssistantMessageEvent(
            kind=StreamPartKind.TOOLCALL_END, block_index=2, tool_call_id=tool_call_id
        )
    )

    turn0_message = Message(
        role=Role.ASSISTANT,
        content=(
            ThinkingBlock(thinking=thinking_text),
            TextBlock(text=plan_text),
            ToolCallBlock(id=tool_call_id, name="read_file", arguments_json=arguments_json),
        ),
    )
    yield MessageEndEvent(message=turn0_message)

    yield ToolExecutionStartEvent(
        tool_call_id=tool_call_id, tool_name="read_file", arguments_json=arguments_json
    )
    yield ToolExecutionUpdateEvent(
        tool_call_id=tool_call_id, partial_output="reading first chunk...\n"
    )
    yield ToolExecutionUpdateEvent(
        tool_call_id=tool_call_id, partial_output="reading rest of file...\n"
    )

    file_contents = "def add(a, b):\n    return a + b\n"
    outcome = ToolOutcome(content=file_contents)
    yield ToolExecutionEndEvent(tool_call_id=tool_call_id, outcome=outcome)

    yield TurnEndEvent(turn_index=0)

    # Turn 1: use the tool result to answer
    yield TurnStartEvent(turn_index=1)
    yield MessageStartEvent(role="tool")
    tool_result_message = Message(
        role=Role.TOOL,
        content=(ToolResultBlock(tool_call_id=tool_call_id, content=file_contents),),
    )
    yield MessageEndEvent(message=tool_result_message)

    yield MessageStartEvent(role="assistant")
    answer_text = (
        f"{filename} defines a single function, add, that returns the sum of two arguments."
    )
    yield from _stream(block_index=0, text=answer_text)

    final_message = Message(role=Role.ASSISTANT, content=(TextBlock(text=answer_text),))
    yield MessageEndEvent(message=final_message)
    yield TurnEndEvent(turn_index=1)

    yield AgentEndEvent(reason=StopReason.DONE)


def main() -> None:
    for event in fake_agent_run(task="summarize this file", filename="math_utils.py"):
        match event:
            case MessageUpdateEvent(assistant_message_event=sub):
                print(f"  [{sub.kind.value}] block={sub.block_index} {sub.delta!r}")
            case MessageEndEvent(message=msg):
                print(f"MESSAGE DONE ({msg.role}): {msg.content}")
            case ToolExecutionUpdateEvent(partial_output=out):
                print(f"  tool output: {out!r}")
            case ToolExecutionEndEvent(outcome=outcome):
                print(f"TOOL DONE: content={outcome.content!r}")
            case _:
                print(event)


if __name__ == "__main__":
    main()
