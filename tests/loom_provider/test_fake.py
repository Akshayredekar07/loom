from loom_provider.demo import fake_tool_call_turn
from loom_provider.events import StreamEnd, TextDelta, ToolCallEnd, ToolCallStart
from loom_provider.replay import FakeProvider


def test_fake_turn_yields_full_tool_call_lifecycle() -> None:
    events = list(fake_tool_call_turn())
    assert isinstance(events[1], ToolCallStart)
    assert isinstance(events[-2], ToolCallEnd)
    assert isinstance(events[-1], StreamEnd)
    assert events[-1].stop_reason == "tool_use"


def test_fake_provider_ignores_its_inputs() -> None:
    """FakeProvider replays the same script regardless of what you pass it --
    this is a documented limitation (see events.py docstring), so pin it
    with a test instead of letting it become surprising later."""
    provider = FakeProvider(script=[TextDelta(text="hi")])
    without_system = list(provider.stream(messages=()))
    with_system = list(provider.stream(messages=(), system="anything"))
    assert without_system == with_system


def test_fake_provider_is_a_context_manager() -> None:
    """close() / __enter__ / __exit__ exist for shape symmetry with real
    providers, so the loop can use `with provider: ...` uniformly."""
    provider = FakeProvider(script=[TextDelta(text="hi")])
    with provider as p:
        assert p is provider
    provider.close()  # must be safe to call more than once
    provider.close()  # idempotent
