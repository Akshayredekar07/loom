"""Runnable, no-network demo of the provider boundary.

uv run python -m loom_provider._demo
"""

from __future__ import annotations

from collections.abc import Iterator

from loom_provider.events import (
    StreamEnd,
    StreamEvent,
    TextDelta,
    ToolCallDelta,
    ToolCallEnd,
    ToolCallStart,
    Usage,
)
from loom_provider.provider import ProviderMessage
from loom_provider.replay import FakeProvider


def fake_tool_call_turn() -> Iterator[StreamEvent]:
    provider = FakeProvider(
        script=[
            TextDelta(text="Let me check that file. "),
            ToolCallStart(id="call_1", name="read"),
            ToolCallDelta(id="call_1", arguments_fragment='{"path": "'),
            ToolCallDelta(id="call_1", arguments_fragment='README.md"}'),
            ToolCallEnd(id="call_1"),
            StreamEnd(stop_reason="tool_use", usage=Usage(input_tokens=42, output_tokens=17)),
        ]
    )
    messages = (ProviderMessage(role="user", content="What's in the README?"),)
    return provider.stream(messages, system="You are a helpful coding agent.")


if __name__ == "__main__":
    for event in fake_tool_call_turn():
        print(event)
