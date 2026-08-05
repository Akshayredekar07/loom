from dataclasses import FrozenInstanceError

import pytest

from loom_core.tools import ToolDefinition, ToolOutcome


def test_tool_definition() -> None:
    schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    tool = ToolDefinition(
        name="read_file",
        description="Read a file",
        parameters_schema=schema,
    )
    assert tool.name == "read_file"
    assert tool.description == "Read a file"
    assert tool.parameters_schema == schema


def test_tool_outcome_ok() -> None:
    out = ToolOutcome(content="done")
    assert out.content == "done"
    assert out.is_error is False


def test_tool_outcome_error() -> None:
    out = ToolOutcome(content="fail", is_error=True)
    assert out.content == "fail"
    assert out.is_error is True


def test_tool_definition_frozen() -> None:
    tool = ToolDefinition(name="a", description="b", parameters_schema={})
    with pytest.raises(FrozenInstanceError):
        tool.name = "x"  # type: ignore[misc]


def test_tool_outcome_frozen() -> None:
    out = ToolOutcome(content="x")
    with pytest.raises(FrozenInstanceError):
        out.content = "y"  # type: ignore[misc]
