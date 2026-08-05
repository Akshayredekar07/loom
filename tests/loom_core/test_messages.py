from dataclasses import FrozenInstanceError

import pytest

from loom_core.messages import (
    Message,
    Role,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
    system_message,
    user_message,
)


def test_role_values() -> None:
    assert Role.SYSTEM == "system"
    assert Role.USER == "user"
    assert Role.ASSISTANT == "assistant"
    assert Role.TOOL == "tool"


def test_text_block() -> None:
    block = TextBlock(text="hello")
    assert block.type == "text"
    assert block.text == "hello"


def test_thinking_block() -> None:
    block = ThinkingBlock(thinking="reason")
    assert block.type == "thinking"
    assert block.thinking == "reason"


def test_tool_call_block_parsed_ok() -> None:
    block = ToolCallBlock(id="1", name="search", arguments_json='{"q": "x"}')
    assert block.type == "tool_call"
    assert block.parsed_arguments() == {"q": "x"}


def test_tool_call_block_parsed_none_on_bad_json() -> None:
    block = ToolCallBlock(arguments_json="{bad")
    assert block.parsed_arguments() is None


def test_tool_call_block_parsed_none_on_non_dict() -> None:
    block = ToolCallBlock(arguments_json="[1, 2]")
    assert block.parsed_arguments() is None


def test_tool_result_block() -> None:
    block = ToolResultBlock(tool_call_id="1", content="ok", is_error=False)
    assert block.type == "tool_result"
    assert block.tool_call_id == "1"
    assert block.content == "ok"
    assert block.is_error is False


def test_user_message() -> None:
    msg = user_message("hi")
    assert msg.role is Role.USER
    assert len(msg.content) == 1
    assert isinstance(msg.content[0], TextBlock)
    assert msg.content[0].text == "hi"
    assert msg.text() == "hi"
    assert msg.tool_calls() == ()


def test_system_message() -> None:
    msg = system_message("sys")
    assert msg.role is Role.SYSTEM
    assert msg.text() == "sys"
    assert msg.tool_calls() == ()


def test_message_text_and_tool_calls() -> None:
    msg = Message(
        role=Role.ASSISTANT,
        content=(
            TextBlock(text="a"),
            ThinkingBlock(thinking="t"),
            ToolCallBlock(id="c1", name="f", arguments_json="{}"),
            TextBlock(text="b"),
        ),
    )
    assert msg.text() == "ab"
    calls = msg.tool_calls()
    assert len(calls) == 1
    assert calls[0].id == "c1"
    assert calls[0].name == "f"


def test_message_frozen() -> None:
    msg = user_message("x")
    with pytest.raises(FrozenInstanceError):
        msg.role = Role.SYSTEM  # type: ignore[misc]


def test_message_metadata_default() -> None:
    msg = user_message("x")
    assert msg.metadata == {}
