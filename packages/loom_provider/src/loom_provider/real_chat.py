"""Real-network smoke test for OpenAICompatibleProvider. NOT a pytest test —
run this manually to see a real LLM stream through the provider layer,
including a full tool-call round trip (call -> execute -> feed result back).

Setup:
    1. uv add python-dotenv
    2. Create .env (gitignored) with:
           LOOM_OPENAI_BASE_URL=https://openrouter.ai/api/v1
           LOOM_OPENAI_API_KEY=sk-or-...
           LOOM_OPENAI_MODEL=openrouter/free
    3. Run:
           uv run python -m loom_provider.real_chat
           uv run python -m loom_provider.real_chat "tell me a joke about http"
           uv run python -m loom_provider.real_chat --tools "compare weather in Paris"
           uv run python -m loom_provider.real_chat --tools "compare weather in Tokyo"
"""

from __future__ import annotations

import json
import os
import random
import sys
from typing import Any

from dotenv import load_dotenv

from loom_provider.events import (
    StreamEnd,
    StreamError,
    TextDelta,
    ToolCallDelta,
    ToolCallEnd,
    ToolCallStart,
)
from loom_provider.openai_compatible import OpenAICompatibleProvider
from loom_provider.provider import ProviderMessage, ProviderToolSchema

MAX_TOOL_ROUNDS = 4


def build_provider() -> OpenAICompatibleProvider:
    base_url = os.environ.get("LOOM_OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    api_key = os.environ.get("LOOM_OPENAI_API_KEY", "")
    model = os.environ.get("LOOM_OPENAI_MODEL", "openrouter/free")
    if not api_key:
        print(
            "error: LOOM_OPENAI_API_KEY not set in environment or .env",
            file=sys.stderr,
        )
        sys.exit(2)
    return OpenAICompatibleProvider(base_url=base_url, api_key=api_key, model=model)


def demo_tools() -> tuple[ProviderToolSchema, ...]:
    return (
        ProviderToolSchema(
            name="get_weather",
            description=("Get the current weather (temperature in Celsius, condition) for a city."),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"},
                },
                "required": ["city"],
            },
        ),
        ProviderToolSchema(
            name="calculate",
            description="Evaluate a simple arithmetic expression, e.g. '14/100*7.3'.",
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Arithmetic expression",
                    },
                },
                "required": ["expression"],
            },
        ),
    )


def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    """Fake tool backends — good enough to prove the round trip actually works."""
    if name == "get_weather":
        city = arguments.get("city", "unknown")
        temp = round(random.uniform(5, 35), 1)
        condition = random.choice(["clear", "cloudy", "rainy", "windy"])
        return json.dumps({"city": city, "temp_c": temp, "condition": condition})
    if name == "calculate":
        expr = arguments.get("expression", "")
        try:
            # NOTE: eval on model-supplied input is fine for a local smoke test only.
            result = eval(expr, {"__builtins__": {}})
        except Exception as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps({"result": result})
    return json.dumps({"error": f"unknown tool {name}"})


def parse_args(argv: list[str]) -> tuple[str, bool]:
    use_tools = "--tools" in argv
    positional = [a for a in argv if not a.startswith("--")]
    default_prompt = (
        "compare weather in Paris and Tokyo right now, tell me which is warmer, "
        "and what's 14% of the temperature difference between them?"
        if use_tools
        else "Say hi in one short sentence."
    )
    prompt = positional[0] if len(positional) > 0 else default_prompt
    return prompt, use_tools


def run_stream(
    provider: OpenAICompatibleProvider,
    messages: tuple[ProviderMessage, ...],
    system: str,
    tools: tuple[ProviderToolSchema, ...],
) -> tuple[str, list[dict[str, Any]], list[ProviderMessage]]:
    """Run one stream; return (stop_reason, tool_calls, new messages)."""
    stop_reason = "unknown"
    tool_calls: dict[str, dict[str, Any]] = {}
    new_messages: list[ProviderMessage] = []
    assistant_text = ""

    for event in provider.stream(messages, system=system, tools=tools):
        if isinstance(event, TextDelta):
            print(event.text, end="", flush=True)
            assistant_text += event.text
        elif isinstance(event, ToolCallStart):
            print(
                f"\n[tool_call_start] id={event.id} name={event.name}",
                flush=True,
            )
            tool_calls[event.id] = {"name": event.name, "arguments": ""}
        elif isinstance(event, ToolCallDelta):
            print(
                f"[tool_call_delta] id={event.id} args+={event.arguments_fragment!r}",
                flush=True,
            )
            tool_calls[event.id]["arguments"] += event.arguments_fragment
        elif isinstance(event, ToolCallEnd):
            print(f"[tool_call_end] id={event.id}", flush=True)
        elif isinstance(event, StreamEnd):
            print(
                f"\n\n[stream_end] stop_reason={event.stop_reason}",
                flush=True,
            )
            stop_reason = event.stop_reason
            if event.usage is not None:
                print(
                    f"[usage] in={event.usage.input_tokens} out={event.usage.output_tokens}",
                    flush=True,
                )
        elif isinstance(event, StreamError):
            print(
                f"\n[stream_error] retryable={event.retryable} message={event.message}",
                flush=True,
            )
            stop_reason = "error"

    if assistant_text:
        new_messages.append(ProviderMessage(role="assistant", content=assistant_text))

    if tool_calls:
        for call_id, call in tool_calls.items():
            try:
                args = json.loads(call["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            result = execute_tool(call["name"], args)
            print(f"[tool_exec] {call['name']}({args}) -> {result}", flush=True)
            new_messages.append(ProviderMessage(role="tool", content=result, tool_call_id=call_id))

    return stop_reason, list(tool_calls.values()), new_messages


def main() -> None:
    load_dotenv()
    prompt, use_tools = parse_args(sys.argv[1:])
    system = "You are a helpful, terse assistant. Use tools when they help answer accurately."
    tools = demo_tools() if use_tools else ()
    messages: tuple[ProviderMessage, ...] = (ProviderMessage(role="user", content=prompt),)

    with build_provider() as provider:
        print(f"[provider] {provider.base_url} model={provider.model}\n", flush=True)
        for round_num in range(1, MAX_TOOL_ROUNDS + 1):
            print(f"\n--- round {round_num} ---", flush=True)
            stop_reason, tool_calls, new_messages = run_stream(provider, messages, system, tools)
            messages = messages + tuple(new_messages)
            if not tool_calls or stop_reason == "error":
                break
        else:
            print(
                "\n[warn] hit MAX_TOOL_ROUNDS without a final answer",
                file=sys.stderr,
            )
        print(flush=True)


if __name__ == "__main__":
    main()
