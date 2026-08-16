# Phase 2 — Provider Interface: a Fake Provider and a Real One

Phase 1 defines offline types (`Message`, `ToolDefinition`, `AgentEvent`). This phase adds the layer that talks to models: a `Provider` protocol, a `StreamEvent` vocabulary, `FakeProvider` for tests, and `OpenAICompatibleProvider` for real HTTP.

## Table of Contents

1. [Goal of this phase](#1-goal-of-this-phase)
2. [Design rationale](#2-design-rationale)
3. [The puzzle this phase has to solve](#3-the-puzzle-this-phase-has-to-solve)
4. [loom_provider/events.py](#4-loom_providereventspy)
5. [loom_provider/provider.py](#5-loom_providerproviderpy)
6. [loom_provider/fake.py](#6-loom_providerfakepy)
7. [loom_provider/openai_compatible.py](#7-loom_provideropenai_compatiblepy)
8. [A runnable demo: fake provider, scripted tool call, still no model](#8-a-runnable-demo-fake-provider-scripted-tool-call-still-no-model)
9. [Tests](#9-tests)
10. [Key design decisions](#10-key-design-decisions)
11. [Phase 2 checklist](#11-phase-2-checklist)
12. [Common pitfalls at this layer](#12-common-pitfalls-at-this-layer)
13. [Known debt carried into later phases](#13-known-debt-carried-into-later-phases)

## 1. Goal of this phase

By the end of this phase, `loom_provider` exports a `Provider` protocol, a small `StreamEvent` family, and two implementations of that protocol:

- **FakeProvider** — replays a scripted list of `StreamEvent`s. No network. This is what Phase 3's loop tests run against.
- **OpenAICompatibleProvider** — a real provider that opens an HTTP connection to any OpenAI-compatible `/chat/completions` endpoint (OpenAI itself, OpenRouter, a local Ollama/vLLM/LM Studio server, …) and turns the SSE stream into `StreamEvent`s by hand, with no SDK. Holds one `httpx.Client` per instance and reuses it across turns (§7), with a clean `close()` and context-manager interface.

Nothing in this package imports `loom_core`. That's not an accident — it's the one design decision this whole phase hangs off, and §3 below is about why.

## 2. Design rationale

Cross-checked against Tau, pi-agent-core, OpenAI Agents SDK, Codex, Hermes, and Grok Build. Shared pattern:

- **Vendor translation stays in the adapter.** Retry, cancellation, and catalog selection live above the provider layer.
- **`ProviderMessage` is not `loom_core.Message`.** The provider gets a flat wire shape; Phase 3 translates between layers.
- **Two event levels.** `StreamEvent` (provider) vs `AgentEvent` (loop) — smaller stream normalized before assembly.
- **Config-dumb providers.** `base_url`, `api_key`, `model` as constructor args only; env/catalog reads belong in `loom_app`.
- **Reuse one HTTP client per provider instance** (Codex and multi-turn sessions expect this).
- **JSON-primitive fields on every event** — enables Phase 7 serialization and JSON-RPC frontends without redesign.

Deferred to later phases: retry/backoff, cancellation, Anthropic adapter (Phase 2.5), provider catalog UX (Phase 18).

## 3. The puzzle this phase has to solve

Phase 1 said `loom_app` → `loom_core` → `loom_provider` and "loom_core is not allowed to import anything from loom_app" — but never spelled out the `loom_core` ↔ `loom_provider` edge. Read the arrow the same way as Tau's own `tau_coding` → `tau_agent` → `tau_ai`: the higher package imports the lower one. So `loom_core` (Phase 3's loop) is allowed to import `loom_provider`. `loom_provider` must never import `loom_core`.

That's awkward at first glance: a provider adapter has to turn a conversation into an HTTP request, and "conversation" sounds exactly like `loom_core.Message`. If `loom_provider` imported `loom_core.Message` to do that translation, the arrow would point both ways and the whole layering argument would collapse.

The fix — confirmed by Tau shipping its own `tau_ai/content.py` instead of importing `tau_agent`'s message type — is that the provider layer gets its own, smaller message shape. `ProviderMessage` in this phase is *not* `loom_core.Message`. It's the flattened, wire-shaped thing a provider actually needs: a role, a content string, and just enough tool-call/tool-result bookkeeping to keep multi-turn tool use coherent. Translating a rich `loom_core.Message` (ordered content blocks, thinking, immutability) down into a flat `ProviderMessage`, and translating a `StreamEvent` stream back up into `AgentEvent`s, is Phase 3's job — it's the one package allowed to know about both shapes. `loom_provider` never sees a `loom_core.Message` and never needs to.

Same argument for tools: `ProviderToolSchema` here is name + description + raw JSON Schema, not `loom_core.ToolDefinition`. Phase 3 converts one into the other on the way down.

One additional design constraint worth writing down here so Phase 7's serialization work doesn't have to refactor anything: **every field on every `StreamEvent` and `AgentEvent` variant is JSON-primitive-shaped**. That's `str`, `int`, `float`, `bool`, `None`, an `enum` with a plain string value, or a nested frozen dataclass built from the same list — never a socket, a callback, a live exception object, or anything else `json.dumps` can't already handle with `dataclasses.asdict`. `StreamError.message` is a `str` on purpose, not the caught exception itself. Codex's App Server (JSON-RPC over stdio), Grok Build's `streaming-json` headless mode, and Hermes' JSON-RPC-to-tui-gateway all converge on "the event stream is a JSON-serializable wire protocol, not just an in-process Python generator" — that habit, held from this phase forward, makes Phase 7's actual serialization a 15-minute dispatch table instead of a redesign, and it makes a future JSON-RPC frontend possible without touching `loom_core` or `loom_provider` at all. This is a rule to hold yourself to, not a class to write.

## 4. loom_provider/events.py

```python
"""Provider-neutral *wire* event stream.

Deliberately smaller and dumber than loom_core.events.AgentEvent. This is
where a vendor chunk lands after normalization but before it means anything
to an agent loop. loom_core's loop (Phase 3) is the only consumer; it
assembles a StreamEvent sequence into the richer, ordered-content-block
AgentEvent stream. Nothing outside loom_provider and loom_core's loop should
ever need to know StreamEvent exists.

JSON-serializability rule (held from this phase forward, see phase doc §3):
every field on every variant below is a str / int / float / bool / None,
a plain-string-valued enum, or a nested frozen dataclass built from the
same. No sockets, no callbacks, no live exception objects. Spot-check any
new event type against `dataclasses.asdict(event)` + `json.dumps(...)` in a
REPL before adding it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True, slots=True)
class TextDelta:
    """A fragment of plain assistant-visible text."""

    type: Literal["text_delta"] = field(default="text_delta", init=False)
    text: str = ""


@dataclass(frozen=True, slots=True)
class ThinkingDelta:
    """A fragment of extended-thinking / reasoning content, kept distinct
    from TextDelta for the same reason ThinkingBlock is distinct from
    TextBlock in loom_core: renderers and providers may want to treat it
    differently (fold it, hide it, strip it)."""

    type: Literal["thinking_delta"] = field(default="thinking_delta", init=False)
    thinking: str = ""


@dataclass(frozen=True, slots=True)
class ToolCallStart:
    """The model has started asking for a tool call. `name` is usually known
    immediately; `arguments_json` is not — it streams in as ToolCallDelta
    fragments and is only complete at ToolCallEnd."""

    type: Literal["tool_call_start"] = field(default="tool_call_start", init=False)
    id: str = ""
    name: str = ""


@dataclass(frozen=True, slots=True)
class ToolCallDelta:
    """One fragment of a tool call's streamed JSON arguments. Concatenate
    every ToolCallDelta.arguments_fragment sharing an `id`, in order, to
    reconstruct the full arguments string."""

    type: Literal["tool_call_delta"] = field(default="tool_call_delta", init=False)
    id: str = ""
    arguments_fragment: str = ""


@dataclass(frozen=True, slots=True)
class ToolCallEnd:
    """The tool call's arguments are fully streamed."""

    type: Literal["tool_call_end"] = field(default="tool_call_end", init=False)
    id: str = ""


@dataclass(frozen=True, slots=True)
class Usage:
    """Token accounting, when the vendor reports it. Optional on StreamEnd
    because not every provider (or every request to the same provider)
    returns usage — streaming responses in particular sometimes only attach
    it to the final chunk."""

    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class StreamEnd:
    """The turn is over. `stop_reason` is the provider-neutral reason —
    Phase 3's loop branches on this to decide "run tools and continue" vs.
    "the turn is genuinely done." """

    type: Literal["stream_end"] = field(default="stream_end", init=False)
    stop_reason: Literal["end_turn", "tool_use", "max_tokens", "error"] = "end_turn"
    usage: Usage | None = None


@dataclass(frozen=True, slots=True)
class StreamError:
    """Something went wrong: a non-200 response, a transport failure, a
    chunk that didn't parse. `retryable` is the adapter's best guess (rate
    limits and 5xx are retryable; a 400 with a malformed request is not) —
    Phase 3 or Phase 4 decides what to actually do with that guess; this
    layer only reports it."""

    type: Literal["stream_error"] = field(default="stream_error", init=False)
    message: str = ""
    retryable: bool = False


StreamEvent = (
    TextDelta
    | ThinkingDelta
    | ToolCallStart
    | ToolCallDelta
    | ToolCallEnd
    | StreamEnd
    | StreamError
)
```

## 5. loom_provider/provider.py

```python
"""The Provider boundary: conversation-in, StreamEvent-stream-out.

ProviderMessage and ProviderToolSchema are this package's OWN types — not
loom_core.Message / loom_core.ToolDefinition. See the Phase 2 doc, section 3,
for why: it's what keeps the loom_core -> loom_provider dependency arrow
pointing one way. Nothing in this file imports loom_core, and nothing here
ever should.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ProviderToolCall:
    """A completed tool call, as it goes ON THE WIRE in request history —
    not the streaming representation (that's ToolCallStart/Delta/End)."""

    id: str
    name: str
    arguments_json: str


@dataclass(frozen=True, slots=True)
class ProviderMessage:
    """The provider layer's flattened message shape.

    role is one of "system" | "user" | "assistant" | "tool". A "tool" role
    message is a tool RESULT going back to the model, identified by
    tool_call_id. An "assistant" message that called tools carries them in
    tool_calls. This is intentionally close to the OpenAI chat-completions
    wire shape (the most common denominator across compatible endpoints) --
    Anthropic-shaped or other providers translate into this at their own
    adapter boundary, same as they'd translate loom_core.Message if they sat
    one layer up.
    """

    role: str
    content: str = ""
    tool_call_id: str | None = None
    tool_calls: tuple[ProviderToolCall, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ProviderToolSchema:
    """Vendor-agnostic tool schema. Translating this into OpenAI's
    {"type": "function", "function": {...}} envelope, Anthropic's
    {"name", "input_schema"} shape, or anything else, is each Provider
    implementation's job -- never this module's."""

    name: str
    description: str
    parameters_json_schema: dict[str, Any]


class Provider(Protocol):
    """Anything that can turn a conversation into a StreamEvent stream.

    Sync, not async, on purpose -- Phase 1's comparison table already flagged
    this: "plain iterator (sync) for now; Phase 3 upgrades to async for."
    Don't reach for asyncio here just because real providers do I/O; adding
    it in Phase 3, once the loop actually needs concurrent cancellation, is
    less code to carry through Phase 2's tests in the meantime.

    Every Provider implementation is also a context manager -- `with
    provider: ...` is the supported way to consume one, because some
    implementations (OpenAICompatibleProvider) hold a reusable HTTP client
    that needs an explicit close(). Implementations with no I/O resource
    (FakeProvider) still expose close() / __enter__ / __exit__ for shape
    symmetry, so the loop doesn't need an isinstance check.
    """

    def stream(
        self,
        messages: tuple[ProviderMessage, ...],
        *,
        system: str | None = None,
        tools: tuple[ProviderToolSchema, ...] = (),
    ) -> Iterator["StreamEvent"]:  # noqa: F821 (see events.py)
        ...

    def close(self) -> None:
        """Release any held resources (HTTP client, file handle, ...).
        Idempotent -- safe to call more than once."""
        ...
```

## 6. loom_provider/fake.py

```python
"""A Provider that never touches the network.

Exists for the same reason Phase 1's _demo.py hand-built AgentEvents: Phase 3's
agent loop needs to be fully testable without an API key, a mock HTTP server,
or flaky network calls. FakeProvider replays a script of StreamEvents handed
to it up front -- it doesn't inspect the messages or tools you pass in, which
is fine here. Phase 3's loop tests care about "does the loop correctly react
to a tool_call_start/delta/end/stream_end sequence," not "is the fake model's
answer contextually appropriate."

close() / context-manager methods are no-ops here (no I/O resource to
release) but kept on the class for shape symmetry with real providers, so
Phase 3's loop can use `with provider: ...` uniformly without an isinstance
check.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from loom_provider.events import StreamEvent
from loom_provider.provider import ProviderMessage, ProviderToolSchema


@dataclass
class FakeProvider:
    script: Sequence[StreamEvent]

    def stream(
        self,
        messages: tuple[ProviderMessage, ...],
        *,
        system: str | None = None,
        tools: tuple[ProviderToolSchema, ...] = (),
    ) -> Iterator[StreamEvent]:
        yield from self.script

    def close(self) -> None:
        """No resource to release; kept for Provider-shape symmetry.
        Idempotent -- safe to call more than once."""
        return None

    def __enter__(self) -> "FakeProvider":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
```

## 7. loom_provider/openai_compatible.py

```python
"""A real Provider: any OpenAI-compatible /chat/completions endpoint.

OpenAI-compatible, not Anthropic-specific, as the FIRST real provider: the
OpenAI wire shape is what OpenRouter, most self-hosted runtimes (vLLM,
Ollama's /v1 shim, LM Studio), and "custom OpenAI-compatible endpoints" (Tau
supports exactly this category) all speak. One adapter buys the widest
coverage. Add an AnthropicProvider later against the same Provider protocol.

No vendor SDK. This speaks the wire format directly -- an HTTP POST with
"stream": true, reading Server-Sent Events line by line -- because the whole
point of this project is understanding what the SDKs normally hide. httpx is
the one new dependency this phase adds (sync client with streaming support;
stdlib's urllib makes chunked SSE reading painful enough to not be worth it).

Connection lifecycle: ONE httpx.Client is held per provider instance and
reused across calls. Same reasoning as Codex's ModelClient caching its WS
connection between turns -- a multi-turn coding session makes many requests
to the same endpoint, and re-handshaking TCP+TLS on every turn is pure
waste that Phase 3's tool-use round-trip loop will feel immediately. The
client is created lazily on first use, and the provider is a context
manager so callers can rely on `with provider: ...` for clean shutdown
even on exception.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field

import httpx

from loom_provider.events import (
    StreamEnd,
    StreamError,
    StreamEvent,
    TextDelta,
    ToolCallDelta,
    ToolCallEnd,
    ToolCallStart,
    Usage,
)
from loom_provider.provider import ProviderMessage, ProviderToolSchema

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass
class OpenAICompatibleProvider:
    base_url: str
    api_key: str
    model: str
    timeout_s: float = 60.0

    # Held, not exposed in __repr__ because a live client has no useful
    # printable state. Created lazily on first stream() and reused across
    # calls so a multi-turn session doesn't re-handshake TCP+TLS per turn.
    _client: httpx.Client | None = field(default=None, init=False, repr=False)

    # -- lifecycle ----------------------------------------------------

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout_s)
        return self._client

    def close(self) -> None:
        """Release the held HTTP client. Call this (or use the provider as
        a context manager) when you're done -- e.g. at the end of a CLI
        invocation or when a session ends. Idempotent."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "OpenAICompatibleProvider":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- the boundary -------------------------------------------------

    def stream(
        self,
        messages: tuple[ProviderMessage, ...],
        *,
        system: str | None = None,
        tools: tuple[ProviderToolSchema, ...] = (),
    ) -> Iterator[StreamEvent]:
        payload = self._build_payload(messages, system=system, tools=tools)
        open_tool_calls: dict[int, str] = {}  # chunk index -> call id
        client = self._get_client()
        try:
            with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            ) as response:
                if response.status_code != 200:
                    body = response.read().decode("utf-8", errors="replace")
                    yield StreamError(
                        message=f"HTTP {response.status_code}: {body[:500]}",
                        retryable=response.status_code in _RETRYABLE_STATUS,
                    )
                    return
                for line in response.iter_lines():
                    yield from self._handle_line(line, open_tool_calls)
        except httpx.TimeoutException as exc:
            yield StreamError(message=f"request timed out: {exc}", retryable=True)
        except httpx.HTTPError as exc:
            yield StreamError(message=f"transport error: {exc}", retryable=True)

    # -- wire translation, private on purpose: this is the one place in the
    # whole codebase allowed to know the OpenAI chat-completions JSON shape --

    def _build_payload(
        self,
        messages: tuple[ProviderMessage, ...],
        *,
        system: str | None,
        tools: tuple[ProviderToolSchema, ...],
    ) -> dict:
        wire_messages: list[dict] = []
        if system:
            wire_messages.append({"role": "system", "content": system})
        for m in messages:
            entry: dict = {"role": m.role, "content": m.content}
            if m.tool_call_id:
                entry["tool_call_id"] = m.tool_call_id
            if m.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments_json},
                    }
                    for tc in m.tool_calls
                ]
            wire_messages.append(entry)

        payload: dict = {"model": self.model, "messages": wire_messages, "stream": True}
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters_json_schema,
                    },
                }
                for t in tools
            ]
        return payload

    def _handle_line(
        self, line: str, open_tool_calls: dict[int, str]
    ) -> Iterator[StreamEvent]:
        if not line.startswith("data: "):
            return
        data = line[len("data: "):]
        if data == "[DONE]":
            return
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            yield StreamError(message=f"malformed SSE chunk: {data[:200]}")
            return

        choices = chunk.get("choices") or []
        if not choices:
            return
        delta = choices[0].get("delta", {})
        finish_reason = choices[0].get("finish_reason")

        if content := delta.get("content"):
            yield TextDelta(text=content)

        for tc in delta.get("tool_calls") or []:
            index = tc.get("index", 0)
            fn = tc.get("function", {})
            if tc.get("id") and index not in open_tool_calls:
                open_tool_calls[index] = tc["id"]
                yield ToolCallStart(id=tc["id"], name=fn.get("name", ""))
            call_id = open_tool_calls.get(index, tc.get("id", ""))
            if args_fragment := fn.get("arguments"):
                yield ToolCallDelta(id=call_id, arguments_fragment=args_fragment)

        if finish_reason:
            for call_id in open_tool_calls.values():
                yield ToolCallEnd(id=call_id)
            if finish_reason == "tool_calls":
                stop = "tool_use"
            elif finish_reason == "length":
                stop = "max_tokens"
            else:
                stop = "end_turn"
            usage_raw = chunk.get("usage")
            usage = (
                Usage(
                    input_tokens=usage_raw.get("prompt_tokens", 0),
                    output_tokens=usage_raw.get("completion_tokens", 0),
                )
                if usage_raw
                else None
            )
            yield StreamEnd(stop_reason=stop, usage=usage)
```

Add the one new dependency:

```bash
uv add httpx
```

## 8. A runnable demo: fake provider, scripted tool call, still no model

`loom_provider/_demo.py`

```python
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
from loom_provider.fake import FakeProvider
from loom_provider.provider import ProviderMessage


def fake_tool_call_turn() -> Iterator[StreamEvent]:
    """A scripted turn: the model says a sentence, then calls `read` on
    README.md, streamed one JSON fragment at a time -- the same shape a real
    OpenAI-compatible response streams tool-call arguments in."""
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
```

Run it:

```bash
uv run python -m loom_provider._demo
```

```
TextDelta(type='text_delta', text='Let me check that file. ')
ToolCallStart(type='tool_call_start', id='call_1', name='read')
ToolCallDelta(type='tool_call_delta', id='call_1', arguments_fragment='{"path": "')
ToolCallDelta(type='tool_call_delta', id='call_1', arguments_fragment='README.md"}')
ToolCallEnd(type='tool_call_end', id='call_1')
StreamEnd(type='stream_end', stop_reason='tool_use', usage=Usage(input_tokens=42, output_tokens=17))
```

A second, smaller demo that exercises the real provider's context-manager interface (no real call — `base_url` is intentionally invalid; the point is just to show the shape):

```python
# demo_real_provider_shape.py
from loom_provider.openai_compatible import OpenAICompatibleProvider

with OpenAICompatibleProvider(
    base_url="https://example.invalid/v1", api_key="test-key", model="gpt-test"
) as provider:
    # Phase 3's loop will live inside this `with` block.
    # for event in provider.stream(messages, system=system, tools=tools):
    #     ...
    pass
# client is closed here, even on exception.
```

## 9. Tests

`tests/loom_provider/test_fake.py`

```python
from loom_provider._demo import fake_tool_call_turn
from loom_provider.events import StreamEnd, TextDelta, ToolCallEnd, ToolCallStart
from loom_provider.fake import FakeProvider


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
```

`tests/loom_provider/test_openai_compatible.py`

```python
from loom_provider.events import StreamEnd, TextDelta, ToolCallStart
from loom_provider.openai_compatible import OpenAICompatibleProvider
from loom_provider.provider import ProviderMessage, ProviderToolSchema


def make_provider() -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        base_url="https://example.invalid/v1", api_key="test-key", model="gpt-test"
    )


def test_build_payload_includes_system_and_tools() -> None:
    provider = make_provider()
    payload = provider._build_payload(
        (ProviderMessage(role="user", content="hi"),),
        system="be helpful",
        tools=(
            ProviderToolSchema(
                name="read", description="read a file",
                parameters_json_schema={"type": "object"},
            ),
        ),
    )
    assert payload["messages"][0] == {"role": "system", "content": "be helpful"}
    assert payload["tools"][0]["function"]["name"] == "read"
    assert payload["stream"] is True


def test_handle_line_parses_a_text_delta() -> None:
    provider = make_provider()
    line = '''data: {"choices":[{"delta":{"content":"hi"},"finish_reason":null}]}'''
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
    """§7 hardens OpenAICompatibleProvider to hold one httpx.Client per
    instance; this test pins the lifecycle contract callers rely on."""
    provider = make_provider()
    with provider as p:
        assert p is provider
    provider.close()  # safe to call after the with block exited
    provider.close()  # safe to call more than once
```

Real-network integration tests (actually hitting an endpoint) belong behind a `pytest.mark.skipif(not os.environ.get("LOOM_TEST_API_KEY"), ...)` guard, not in the default suite — same reasoning as any project that wants CI to run without secrets. Write one if you have a key handy, but don't block the checklist on it.

Run it:

```bash
uv run pytest tests/loom_provider -v
```

## 10. Key design decisions

| Decision | Choice |
|---|---|
| Wire translation | `_build_payload` / `_handle_line` inside each provider |
| Cross-cutting (retry, cancel) | Deferred to harness (Phase 3/4) |
| HTTP client | One `httpx.Client` per provider instance, with `close()` |
| Config | Plain constructor args; catalog in `loom_app` |
| Event fields | JSON-primitive only (str, int, bool, enums, nested frozen dataclasses) |
| Real providers shipped | `FakeProvider`, `OpenAICompatibleProvider` |

## 11. Phase 2 checklist

- [ ] `loom_provider/events.py` exists: `TextDelta`, `ThinkingDelta`, `ToolCallStart`, `ToolCallDelta`, `ToolCallEnd`, `Usage`, `StreamEnd`, `StreamError`, and the `StreamEvent` union
- [ ] `loom_provider/provider.py` exists: `ProviderMessage`, `ProviderToolCall`, `ProviderToolSchema`, `Provider` protocol (including `close()`)
- [ ] Neither file imports anything from `loom_core`
- [ ] `loom_provider/fake.py` — `FakeProvider` replays a script, no I/O, and exposes `close()` / `__enter__` / `__exit__` as no-ops for shape symmetry
- [ ] `loom_provider/openai_compatible.py` — `OpenAICompatibleProvider` builds a correct payload and parses SSE chunks into `StreamEvent`s
- [ ] `OpenAICompatibleProvider` reuses one `httpx.Client` across calls, exposes `close()` (idempotent), and works as a context manager
- [ ] `FakeProvider` gained the same `close()` / context-manager shape, for API symmetry with real providers
- [ ] Every `StreamEvent` field is JSON-primitive-shaped (spot-check each variant against `dataclasses.asdict(event)` + `json.dumps(...)` mentally, or actually run it once as a sanity test)
- [ ] `dev-notes/0003-provider-boundary.md` records why event fields stay primitive-shaped, so it doesn't get "simplified" away by future-you
- [ ] A one-paragraph note added to Phase 5's future dev-notes stub (or just this doc, bookmarked) about the tool-approval hook point from §14 — doesn't need code yet, needs to not be forgotten
- [ ] `loom_provider/_demo.py` runs and prints a full tool-call lifecycle with no network call
- [ ] `uv run pytest tests/loom_provider -v` passes
- [ ] `uv run mypy packages/loom_provider` passes with `strict = true`
- [ ] `uv run ruff check packages/loom_provider` passes
- [ ] `uv run lint-imports` (or your import-linter invocation) confirms `loom_provider` has zero imports from `loom_core` or `loom_app`
- [ ] You can explain, out loud, without looking at this file: why `ProviderMessage` isn't `loom_core.Message`, and what would break if it were
- [ ] You can explain, out loud, why every `StreamEvent` field is JSON-primitive-shaped, and what would break if a callback or live exception snuck in
- [ ] `dev-notes/0003-provider-boundary.md` written (ADR template from Phase 0) — record anything you changed from this file and why

## 12. Common pitfalls at this layer

- **Importing `loom_core` "just for the types, it's fine."** It compiles today and quietly breaks the whole point of this phase. If you find yourself wanting to pass a `loom_core.ToolDefinition` straight into `Provider.stream`, that's the signal you're about to do Phase 3's translation work inside Phase 2 — stop, and remember `ProviderToolSchema` exists precisely so you don't have to.
- **Indexing tool-call deltas by name instead of the chunk's `index` field.** OpenAI-compatible streams can interleave arguments for more than one tool call in a single turn; the `index` in each chunk is the only stable key until `id` shows up (and `id` sometimes only arrives on the first chunk for that call). `_handle_line`'s `open_tool_calls: dict[int, str]` exists for exactly this reason — don't simplify it away.
- **Treating `finish_reason` as optional to check.** It's the only place a `StreamEnd` gets emitted. Skip it and your loop hangs waiting for an event that never comes, instead of failing loudly.
- **Swallowing `httpx.HTTPError` silently.** A `StreamError` your loop can see and log is worth infinitely more than a generator that just stops. Always end the generator with a `StreamError`, never a bare `return` on failure.
- **Testing the real provider by mocking `httpx` deeply instead of testing `_build_payload`/`_handle_line` directly.** Those two methods are pure functions of a payload/line in, an event stream out — test them as such. Save actual HTTP mocking (or a real integration test) for verifying the `stream()` method wires them together, not for re-testing JSON parsing.
- **Forgetting `close()` because the test ran once and didn't leak.** A single-stream test won't notice the leaked `httpx.Client`; a Phase 3 loop that creates and discards hundreds will. Either use `with provider: ...` or call `provider.close()` explicitly at the end of the consumer's lifetime.
- **Letting a non-primitive field onto a `StreamEvent` variant "just this once."** It's tempting when you're passing a parsed JSON object or an exception around. The habit of holding the line on JSON-primitive fields (§3) is what makes Phase 7 a 15-minute dispatch table; one slip and you've re-opened that work.

## 13. Known debt carried into later phases

Written down on purpose, same discipline as Phase 1 §14:

- **No retry/backoff.** `StreamError.retryable` is reported, never acted on. Phase 4's harness (or Phase 3's loop, if it turns out to belong there) is where a retry policy gets implemented — against a `StreamError` stream that already exists, rather than needing this phase reopened.
- **No cancellation.** `Provider.stream()` runs to completion or raises; there's no way to stop it mid-stream. This is intentionally deferred to the async upgrade Phase 1 already flagged for Phase 3 — cooperative cancellation needs `asyncio`, and bolting a half-cancellation story onto a sync generator now would just be thrown away.
- **Only one real OpenAI-shaped provider.** Anthropic adapter added in Phase 2.5.
- **No provider-side rate-limit awareness beyond a boolean.** Real vendor responses often carry `Retry-After` headers or structured rate-limit payloads; `StreamError.retryable` is a coarse yes/no. Fine for now, revisit if Phase 4's retry logic wants more signal.

Carried forward from the cross-check research pass — *no code change in this phase, just a written note so it doesn't get re-discovered later*:

- **A tool-execution approval / screening hook point (QM).** QM's Strict / Auto / Dangerous security postures — human approval per tool call in Strict, provenance-labelled content screening before tool results reach the model in Auto — is a pattern worth designing room for when Phase 5 builds `read` / `write` / `edit` / `bash`. Nothing to do in `loom_provider` today: this is about where in Phase 5's tool-execution path a callback could sit *between* "the loop decided to call a tool" and "the tool actually ran," and again *between* "the tool produced a result" and "that result gets appended to history and sent back to the model." Leaving an explicit seam there in Phase 5, even if nothing plugs into it until much later, is cheaper than retrofitting an approval gate into an already-built tool-execution loop.
- **Vendor prompt-cache stability (Hermes).** Hermes' own contributor docs call per-conversation prompt caching "sacred" — a long conversation reuses a cached prefix every turn, which only works if that prefix is genuinely byte-identical across requests. `ProviderMessage` is already frozen and history is already append-only in this design, so nothing is broken today — but it's worth carrying forward as an explicit constraint for Phase 4 (the harness) and Phase 23 (compaction): summarizing or rewriting earlier messages in the transcript, however tempting for context-window management, invalidates every vendor's cached prefix from that point forward and turns a cheap cached-prefix request into a full-price one. Compaction needs to be designed with this cost in mind, not just a context-length budget.

---

Phase 2 gives you a provider boundary: `FakeProvider` for tests and `OpenAICompatibleProvider` for real endpoints.

Next: **Phase 2.5** (provider catalog + Anthropic adapter), then **Phase 3** (agent loop).
