from dataclasses import dataclass

from loom_provider.anthropic_messages import AnthropicMessagesProvider, AnthropicStreamState
from loom_provider.events import StreamEnd, StreamEvent, TextDelta, ToolCallDelta, ToolCallStart
from loom_provider.openai_compatible import OpenAICompatibleProvider


@dataclass(frozen=True, slots=True)
class NormalizedEvent:
    kind: str
    text: str = ""
    call_id: str = ""
    call_name: str = ""
    arguments_fragment: str = ""
    stop_reason: str = ""


def normalize(events: list[StreamEvent]) -> list[NormalizedEvent]:
    normalized: list[NormalizedEvent] = []
    for event in events:
        if isinstance(event, TextDelta):
            normalized.append(NormalizedEvent(kind="text", text=event.text))
        elif isinstance(event, ToolCallStart):
            normalized.append(
                NormalizedEvent(kind="tool_start", call_id=event.id, call_name=event.name)
            )
        elif isinstance(event, ToolCallDelta):
            normalized.append(
                NormalizedEvent(
                    kind="tool_delta",
                    call_id=event.id,
                    arguments_fragment=event.arguments_fragment,
                )
            )
        elif isinstance(event, StreamEnd):
            normalized.append(NormalizedEvent(kind="stream_end", stop_reason=event.stop_reason))
    return normalized


def replay_openai(lines: list[str]) -> list[StreamEvent]:
    provider = OpenAICompatibleProvider(
        base_url="https://example.invalid/v1",
        api_key="test-key",
        model="gpt-test",
    )
    open_tool_calls: dict[int, str] = {}
    events: list[StreamEvent] = []
    for line in lines:
        events.extend(provider._handle_line(line, open_tool_calls))
    return events


def replay_anthropic(lines: list[str]) -> list[StreamEvent]:
    provider = AnthropicMessagesProvider(
        base_url="https://example.invalid/v1",
        api_key="test-key",
        model="claude-test",
    )
    state = AnthropicStreamState()
    events: list[StreamEvent] = []
    for line in lines:
        events.extend(provider._handle_line(line, state))
    return events


def test_openai_and_anthropic_emit_equivalent_stream_events_for_tool_turn() -> None:
    openai_lines = [
        'data: {"choices":[{"delta":{"content":"Let me check"},"finish_reason":null}]}',
        (
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1",'
            '"function":{"name":"read","arguments":""}}]},"finish_reason":null}]}'
        ),
        (
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
            '"function":{"arguments":"{\\"path\\":\\"/tmp/x\\"}"}}]},'
            '"finish_reason":null}]}'
        ),
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
    ]
    anthropic_lines = [
        'data: {"type":"message_start","message":{"usage":{"input_tokens":1,"output_tokens":1}}}',
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
        (
            'data: {"type":"content_block_delta","index":0,'
            '"delta":{"type":"text_delta","text":"Let me check"}}'
        ),
        'data: {"type":"content_block_stop","index":0}',
        (
            'data: {"type":"content_block_start","index":1,'
            '"content_block":{"type":"tool_use","id":"c1","name":"read","input":{}}}'
        ),
        (
            'data: {"type":"content_block_delta","index":1,'
            '"delta":{"type":"input_json_delta","partial_json":"{\\"path\\":\\"/tmp/x\\"}"}}'
        ),
        'data: {"type":"content_block_stop","index":1}',
        (
            'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},'
            '"usage":{"output_tokens":3}}'
        ),
    ]

    openai_events = normalize(replay_openai(openai_lines))
    anthropic_events = normalize(replay_anthropic(anthropic_lines))

    assert openai_events == anthropic_events
    assert openai_events[-1].stop_reason == "tool_use"
