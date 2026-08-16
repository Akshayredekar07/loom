from loom_provider.anthropic_messages import AnthropicMessagesProvider, AnthropicStreamState
from loom_provider.events import StreamEnd, TextDelta, ToolCallDelta, ToolCallEnd, ToolCallStart
from loom_provider.provider import ProviderMessage, ProviderToolCall, ProviderToolSchema


def make_provider() -> AnthropicMessagesProvider:
    return AnthropicMessagesProvider(
        base_url="https://example.invalid/v1",
        api_key="test-key",
        model="claude-test",
    )


def test_build_payload_uses_system_field_and_anthropic_tools() -> None:
    provider = make_provider()
    payload = provider._build_payload(
        (ProviderMessage(role="user", content="hi"),),
        system="be helpful",
        tools=(
            ProviderToolSchema(
                name="read",
                description="read a file",
                parameters_json_schema={"type": "object"},
            ),
        ),
    )
    assert payload["system"] == "be helpful"
    assert payload["tools"][0]["name"] == "read"
    assert payload["tools"][0]["input_schema"] == {"type": "object"}
    assert payload["stream"] is True
    assert payload["max_tokens"] == 8192


def test_build_payload_converts_tool_results_and_assistant_tool_calls() -> None:
    provider = make_provider()
    payload = provider._build_payload(
        (
            ProviderMessage(
                role="assistant",
                content="done",
                tool_calls=(
                    ProviderToolCall(
                        id="toolu_1",
                        name="read",
                        arguments_json='{"path": "/tmp/x"}',
                    ),
                ),
            ),
            ProviderMessage(role="tool", content="file contents", tool_call_id="toolu_1"),
        ),
        system=None,
        tools=(),
    )
    assistant = payload["messages"][0]
    assert assistant["role"] == "assistant"
    assert assistant["content"][0] == {"type": "text", "text": "done"}
    assert assistant["content"][1]["type"] == "tool_use"
    tool_result = payload["messages"][1]
    assert tool_result["role"] == "user"
    assert tool_result["content"][0]["type"] == "tool_result"
    assert tool_result["content"][0]["tool_use_id"] == "toolu_1"


def test_handle_line_parses_text_and_tool_stream() -> None:
    provider = make_provider()
    state = AnthropicStreamState()
    lines = [
        'data: {"type":"message_start","message":{"usage":{"input_tokens":10,"output_tokens":1}}}',
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hi"}}',
        'data: {"type":"content_block_stop","index":0}',
        (
            'data: {"type":"content_block_start","index":1,'
            '"content_block":{"type":"tool_use","id":"toolu_1","name":"read","input":{}}}'
        ),
        (
            'data: {"type":"content_block_delta","index":1,'
            '"delta":{"type":"input_json_delta","partial_json":"{\\"path\\":\\"/x\\"}"}}'
        ),
        'data: {"type":"content_block_stop","index":1}',
        (
            'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},'
            '"usage":{"output_tokens":7}}'
        ),
    ]
    events = []
    for line in lines:
        events.extend(provider._handle_line(line, state))
    assert events[0] == TextDelta(text="hi")
    assert events[1] == ToolCallStart(id="toolu_1", name="read")
    assert events[2] == ToolCallDelta(id="toolu_1", arguments_fragment='{"path":"/x"}')
    assert events[3] == ToolCallEnd(id="toolu_1")
    assert isinstance(events[-1], StreamEnd)
    assert events[-1].stop_reason == "tool_use"
    assert events[-1].usage is not None
    assert events[-1].usage.input_tokens == 10
    assert events[-1].usage.output_tokens == 7


def test_provider_is_a_context_manager_and_close_is_idempotent() -> None:
    provider = make_provider()
    with provider as active:
        assert active is provider
    provider.close()
    provider.close()
