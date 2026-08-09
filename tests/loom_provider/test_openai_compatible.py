"""Unit tests for OpenAICompatibleProvider. Pure payload/line parsing, no
real network calls. The 'real' counterpart lives in
loom_provider/_real_chat.py and is run manually, not via pytest."""

from loom_provider.events import StreamEnd, TextDelta, ToolCallStart
from loom_provider.openai_compatible import OpenAICompatibleProvider
from loom_provider.provider import ProviderMessage, ProviderToolSchema


def make_provider() -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        base_url="https://example.invalid/v1",
        api_key="test-key",
        model="gpt-test",
    )


def test_build_payload_includes_system_and_tools() -> None:
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
    assert payload["messages"][0] == {"role": "system", "content": "be helpful"}
    assert payload["tools"][0]["function"]["name"] == "read"
    assert payload["stream"] is True


def test_handle_line_parses_a_text_delta() -> None:
    provider = make_provider()
    line = 'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":null}]}'
    assert list(provider._handle_line(line, {})) == [TextDelta(text="hi")]


def test_handle_line_emits_stream_end_with_usage_on_finish() -> None:
    provider = make_provider()
    line = (
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
        '"usage":{"prompt_tokens":5,"completion_tokens":3}}'
    )
    events = list(provider._handle_line(line, {}))
    assert isinstance(events[-1], StreamEnd)
    assert events[-1].stop_reason == "end_turn"
    assert events[-1].usage is not None
    assert events[-1].usage.input_tokens == 5


def test_handle_line_starts_tool_call_once_per_index() -> None:
    provider = make_provider()
    open_calls: dict[int, str] = {}
    first = (
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1",'
        '"function":{"name":"read","arguments":""}}]},"finish_reason":null}]}'
    )
    second = (
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0",'
        '"function":{"arguments":"{\\"path\\":1}"}}]},"finish_reason":null}]}'
    )
    events = list(provider._handle_line(first, open_calls)) + list(
        provider._handle_line(second, open_calls)
    )
    starts = [e for e in events if isinstance(e, ToolCallStart)]
    assert len(starts) == 1
    assert open_calls == {0: "c1"}


def test_provider_is_a_context_manager_and_close_is_idempotent() -> None:
    provider = make_provider()
    with provider as p:
        assert p is provider
    provider.close()
    provider.close()  # safe to call more than once
