# **Phase 1 — Core Message, Tool, and Event Types**

> This is the phase where the agent stops being a folder structure and starts
> being a *shape*. Everything from here — the provider layer, the loop, the harness, the
> TUI — is just code that produces or consumes the types in this file. Get this shape
> wrong and every later phase inherits the wrongness. Every example below is runnable.

---

## **Table of Contents**

1. [Goal of this phase](#1-goal-of-this-phase)
2. [The core idea: messages are the state](#2-the-core-idea-messages-are-the-state)
3. [Content blocks — why a message isn't just a string](#3-content-blocks--why-a-message-isnt-just-a-string)
4. [`loom_core/messages.py`](#4-loom_coremessagespy)
5. [`loom_core/tools.py`](#5-loom_coretoolspy)
6. [The event model — why events, not return values](#6-the-event-model--why-events-not-return-values)
7. [`loom_core/events.py`](#7-loom_coreeventspy)
8. [A runnable demo: fake event stream, no model, no I/O](#8-a-runnable-demo-fake-event-stream-no-model-no-io)
9. [Tests](#9-tests)
10. [Comparison table — how the real agents shape this](#10-comparison-table--how-the-real-agents-shape-this)
11. [A second reference set, and what we changed because of it](#11-a-second-reference-set-and-what-we-changed-because-of-it)
12. [Phase 1 checklist](#12-phase-1-checklist)
13. [Common pitfalls at this layer](#13-common-pitfalls-at-this-layer)
14. [Known debt carried into later phases](#14-known-debt-carried-into-later-phases)

---

## **1. Goal of this phase**

By the end of this phase, `loom_core` exports three families of types —
`Message`/content blocks, `ToolDefinition`/`ToolCall`/`ToolResult`, and
`AgentEvent` — with **zero** dependency on any specific model provider, zero
I/O, and zero UI code. You should be able to construct a fake conversation and
a fake event stream entirely in a test file, with no network calls.

Nothing in this phase talks to a real model. That's Phase 2. This phase is
pure data.

---

## **2. The core idea: messages are the state**

Every agent we researched makes the same bet: **the entire conversation state
is one ordered, append-only list of messages.** Not a database. Not a
separate "current tool call" variable next to the transcript. The transcript
*is* the state.

Community analyses of Claude Code's internals converge on this same point
independently — describing it as "one append-only structure solves multiple
problems": persistence is "save the list," replay is "re-run the list," and
context trimming is "operate on the list." Tau's docs describe the same
contract from the harness side — the harness/session owns and appends to a
transcript across turns.

That single decision is why we start here. If the shape of a `Message` is
right, sessions (Phase 7), compaction (Phase 23), and even the TUI transcript
view (Phase 12) all become "operate on this list" instead of needing their own
bespoke state model.

---

## **3. Content blocks — why a message isn't just a string**

A naive `Message` looks like:

```python
@dataclass
class Message:
    role: str
    content: str
```

This breaks the instant a model does more than one thing in a single turn —
which is *every* turn in a coding agent. A single assistant turn commonly
contains: some reasoning text, a decision to call a tool, and (with
extended-thinking models) a thinking block before any of that. Tau's docs are
explicit about this: the final `AssistantMessage` "persists text, thinking,
and tool calls as **ordered content blocks**" — plural, ordered, because order
matters (thinking before the tool call it justifies, text before or after a
tool call depending on what the model actually did).

So: `Message.content` is a **list of content blocks**, not a string. This one
change is the single most important design decision in this file.

---

## **4. `loom_core/messages.py`**

```python
"""Provider-neutral message types.

Nothing in this module knows about OpenAI's or Anthropic's wire format.
Provider adapters (Phase 2) translate *into* these types on the way in and
*out of* them on the way out. That translation boundary is the whole point.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class Role(str, Enum):
    """Who produced a message."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


# --- Content blocks ---------------------------------------------------------
#
# A message is an ordered list of these. Each block type is a frozen
# dataclass: content blocks are immutable once the model has finished
# producing them (the *streaming* view of a block-in-progress lives in
# events.py, not here — this module only holds finished state).


@dataclass(frozen=True, slots=True)
class TextBlock:
    """Plain assistant/user-visible text."""

    type: Literal["text"] = field(default="text", init=False)
    text: str = ""


@dataclass(frozen=True, slots=True)
class ThinkingBlock:
    """Extended-thinking / reasoning content, kept separate from `text`

    so renderers and providers can treat it differently (hide it, fold it,
    strip it before sending history back for models that don't want it).
    """

    type: Literal["thinking"] = field(default="thinking", init=False)
    thinking: str = ""


@dataclass(frozen=True, slots=True)
class ToolCallBlock:
    """The assistant asking to invoke a tool.

    `arguments` is kept as a raw string (the provider adapter is responsible
    for accumulating streamed JSON fragments into one string). Parsing that
    string into real arguments happens at *execution* time, in loom_app's
    tool-execution code — not here, so a malformed-JSON tool call is still a
    perfectly valid, storable `ToolCallBlock`.
    """

    type: Literal["tool_call"] = field(default="tool_call", init=False)
    id: str = ""
    name: str = ""
    arguments_json: str = "{}"

    def parsed_arguments(self) -> dict[str, Any] | None:
        """Best-effort parse of `arguments_json`. Returns None instead of
        raising, so a malformed tool call from the model is still a fully
        storable, replayable Message — the caller decides how to react to
        a None (surface an error to the model, retry, log and skip, ...).
        Deliberately NOT parsed eagerly at construction time: eager parsing
        would mean a malformed-JSON tool call couldn't exist as a valid
        ToolCallBlock at all, which is the wrong failure mode for something
        you need to persist and replay from disk (Phase 7)."""
        try:
            parsed = json.loads(self.arguments_json)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None


@dataclass(frozen=True, slots=True)
class ToolResultBlock:
    """A tool's result, fed back to the model as part of a `Role.TOOL` message."""

    type: Literal["tool_result"] = field(default="tool_result", init=False)
    tool_call_id: str = ""
    content: str = ""
    is_error: bool = False


ContentBlock = TextBlock | ThinkingBlock | ToolCallBlock | ToolResultBlock


# --- Message -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Message:
    """One turn in the transcript. `content` is ordered — order is meaningful."""

    role: Role
    content: tuple[ContentBlock, ...] = ()
    # Free-form provider/telemetry metadata (token usage, stop reason, ...).
    # Kept as `dict[str, Any]` deliberately: it's diagnostic, never something
    # the agent loop branches on. If the loop needs to branch on it, promote
    # the field to a real typed field instead of reading out of this dict.
    metadata: dict[str, Any] = field(default_factory=dict)

    def text(self) -> str:
        """Convenience: concatenate all text blocks. Drops thinking/tool blocks."""
        return "".join(b.text for b in self.content if isinstance(b, TextBlock))

    def tool_calls(self) -> tuple[ToolCallBlock, ...]:
        return tuple(b for b in self.content if isinstance(b, ToolCallBlock))


def user_message(text: str) -> Message:
    """Convenience constructor — what Phase 3's loop calls on every user turn."""
    return Message(role=Role.USER, content=(TextBlock(text=text),))


def system_message(text: str) -> Message:
    return Message(role=Role.SYSTEM, content=(TextBlock(text=text),))
```

### **Why `frozen=True, slots=True`**

- `frozen=True` — a finished `Message` in the transcript should never be
  mutated in place. Any change (e.g. compaction rewriting old messages,
  Phase 23) must produce a *new* `Message`, never edit history silently.
  This makes "replay the session" and "diff two versions of the transcript"
  both trustworthy.
- `slots=True` — no `__dict__` per instance. You'll construct thousands of
  these across a long session; slots keep memory and attribute-typo bugs
  down (a typo'd attribute raises `AttributeError` instead of silently
  creating a new one).

### **Why `arguments_json` stays a raw string here**

This mirrors a real streaming constraint: tool-call arguments arrive from the
model as a stream of JSON *fragments*, not as one clean object. The provider
adapter's job (Phase 2) is to accumulate those fragments into a complete
string once the call finishes. Parsing that string into a Python object is a
*separate* concern — it can fail (models do emit invalid JSON occasionally),
and a parse failure shouldn't corrupt your message type. Keep "what the model
said" and "did we succeed in understanding it" as two different steps.

---

## **5. `loom_core/tools.py`**

```python
"""Tool description types.

This module describes what a tool *is* — its schema — not how it runs.
Execution (Phase 5) lives in loom_app, where filesystem/subprocess access
belongs. loom_core only needs enough shape to (a) tell a provider what tools
exist and (b) validate a ToolCallBlock's name against something real.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Provider-neutral tool schema — turned into OpenAI/Anthropic's specific
    function-calling JSON shape by the provider adapter, not stored in that
    shape here."""

    name: str
    description: str
    # JSON Schema for the tool's arguments object, e.g.:
    # {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
    parameters_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """What a tool execution produced, before it's wrapped into a
    ToolResultBlock and appended to the transcript."""

    content: str
    is_error: bool = False
```

### **Why `ToolDefinition` doesn't include a Python callable**

It's tempting to write `ToolDefinition(name=..., run=some_function)`. Resist
it here. A `ToolDefinition` in `loom_core` is *description only* — this is
what gets sent to the provider so the model knows the tool exists. The
mapping from a tool name to actual executable code (open a file, run a
subprocess) belongs in `loom_app`, one layer up, where filesystem and process
access are allowed to exist. Keeping the callable out of `loom_core` is what
lets you write a fully offline test suite for the agent loop in Phase 3 —
you'll register `ToolDefinition`s with no real implementation at all and just
assert the loop *asks* for the right tool call.

---

## **6. The event model — why events, not return values**

If Phase 3's loop just `return`ed the final message, you'd have no way to
show a spinner, stream tokens live, or drive a TUI that updates as the model
types. So the loop is going to be an **event-producing generator**: instead of
computing an answer and handing it back once, it emits a sequence of small
typed events as things happen, and the *caller* decides what to do with each
one (print it, render it, ignore it, log it).

Tau's docs state this directly: "Every meaningful step is observable as an
event, so print mode, Rich rendering, and the Textual TUI all share the same
core. Frontends render from these provider-neutral events — never from raw
provider chunks." Independent Claude Code analyses converge on the identical
mechanism, describing the loop as an async generator that yields events —
which is what gives a UI "natural backpressure and cancellation" instead of
blocking on one giant network call.

### **The event hierarchy we're stealing**

Tau's own event taxonomy, which this phase's types mirror closely:

- `AgentStartEvent` / `AgentEndEvent` — one whole run begins/ends
- `TurnStartEvent` / `TurnEndEvent` — one assistant response + its tool
  results
- `MessageStartEvent` / `MessageUpdateEvent` / `MessageEndEvent` — a single
  message's lifecycle
- nested under `MessageUpdateEvent`: text/thinking/tool-call
  start/delta/end sub-events — the fine-grained streaming detail
- `ToolExecutionStartEvent` / `ToolExecutionUpdateEvent` /
  `ToolExecutionEndEvent` — a tool actually running

The key rule stated alongside that taxonomy, and the one to hold onto:
**the final message is authoritative; streaming deltas are cosmetic.** Deltas
exist purely so a UI can render responsively. What gets *persisted and
replayed* is always the finished, structured `Message` from Phase 1 §4 — never
a reconstruction from delta events. We enforce that split by putting deltas
in a clearly separate, nested type below.

---

## **7. `loom_core/events.py`**

```python
"""Provider-neutral agent events.

Frontends (print mode, TUI, JSON-stream export) consume this stream and
render it however they like. Nothing in loom_core imports a renderer; nothing
here decides how an event looks on screen — only what happened and when.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from loom_core.messages import Message
from loom_core.tools import ToolOutcome


# --- Streaming sub-events (nested under MessageUpdateEvent) -----------------
#
# These are the fine-grained, cosmetic deltas. A frontend may use them for
# responsive rendering. Nothing downstream (sessions, compaction, replay)
# is allowed to depend on having seen every delta — only on the final
# Message delivered via MessageEndEvent.


class StreamPartKind(str, Enum):
    TEXT_START = "text_start"
    TEXT_DELTA = "text_delta"
    TEXT_END = "text_end"
    THINKING_START = "thinking_start"
    THINKING_DELTA = "thinking_delta"
    THINKING_END = "thinking_end"
    TOOLCALL_START = "toolcall_start"
    TOOLCALL_DELTA = "toolcall_delta"
    TOOLCALL_END = "toolcall_end"


@dataclass(frozen=True, slots=True)
class AssistantMessageEvent:
    """One streaming fragment of an in-progress assistant message."""

    kind: StreamPartKind
    # Index of the content block this fragment belongs to, so a frontend can
    # tell "this delta continues block 2" apart from "a new block started."
    block_index: int
    # Present on *_delta events: the text/thinking/json fragment itself.
    delta: str = ""
    # Present on toolcall_start: which tool is being called, and its call id.
    tool_name: str = ""
    tool_call_id: str = ""


# --- Message lifecycle -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MessageStartEvent:
    role: str


@dataclass(frozen=True, slots=True)
class MessageUpdateEvent:
    assistant_message_event: AssistantMessageEvent


@dataclass(frozen=True, slots=True)
class MessageEndEvent:
    """The authoritative, finished message. Persist/replay from this,
    never from accumulated deltas."""

    message: Message


# --- Tool execution -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolExecutionStartEvent:
    tool_call_id: str
    tool_name: str
    arguments_json: str


@dataclass(frozen=True, slots=True)
class ToolExecutionUpdateEvent:
    """Optional incremental output while a tool runs (e.g. streaming stdout
    from a long-running bash command)."""

    tool_call_id: str
    partial_output: str


@dataclass(frozen=True, slots=True)
class ToolExecutionEndEvent:
    tool_call_id: str
    outcome: ToolOutcome


# --- Turn / agent lifecycle ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class TurnStartEvent:
    turn_index: int


@dataclass(frozen=True, slots=True)
class TurnEndEvent:
    turn_index: int


@dataclass(frozen=True, slots=True)
class AgentStartEvent:
    pass


class StopReason(str, Enum):
    """Why a run ended. Kept as a small closed enum rather than a bare
    string so a `match` on AgentEndEvent.reason can be exhaustive."""

    DONE = "done"  # model produced no more tool calls
    CANCELLED = "cancelled"  # caller cancelled (e.g. user hit Ctrl-C)
    ERROR = "error"  # unrecoverable — see the AgentErrorEvent that precedes this


@dataclass(frozen=True, slots=True)
class AgentEndEvent:
    reason: StopReason = StopReason.DONE


@dataclass(frozen=True, slots=True)
class AgentErrorEvent:
    """A provider/network/parsing failure severe enough to end the run.
    Always emitted immediately before an AgentEndEvent(reason=StopReason.ERROR)
    — kept as a separate event (rather than cramming a message onto
    AgentEndEvent) so a renderer can show a distinct error state, and so a
    session file has a distinct, greppable record of *why* a run stopped
    versus *that* it stopped. `retryable` lets the harness (Phase 4) decide
    whether to offer 'retry' without the caller having to string-match the
    message."""

    message: str
    retryable: bool = False


AgentEvent = (
    AgentStartEvent
    | AgentEndEvent
    | AgentErrorEvent
    | TurnStartEvent
    | TurnEndEvent
    | MessageStartEvent
    | MessageUpdateEvent
    | MessageEndEvent
    | ToolExecutionStartEvent
    | ToolExecutionUpdateEvent
    | ToolExecutionEndEvent
)
```

### **Why `AssistantMessageEvent` is its own nested type, not flattened**

Tau's docs specifically call out that streaming detail is "nested under
`MessageUpdateEvent.assistant_message_event`." Nesting instead of flattening
communicates something real: `MessageUpdateEvent` is the general-purpose
envelope in the outer `AgentEvent` union (so a frontend's top-level `match`
only has one case to handle for "something about a message changed"), while
the *nine* streaming sub-kinds are a private concern of "what kind of update
was it." A frontend that only cares about turn boundaries never has to know
the streaming taxonomy exists.

### **Why `AgentEvent` is a big union type, not a base class with `isinstance`**

Both work in Python. The union + `match` style (Python 3.10+ structural
pattern matching) reads closer to how you'll actually consume this stream in
Phase 6 and Phase 11:

```python
async for event in harness.prompt("..."):
    match event:
        case MessageEndEvent(message=message):
            print(message.text())
        case ToolExecutionStartEvent(tool_name=name):
            print(f"running {name}...")
        case _:
            pass
```

If you'd rather use a common base class with `isinstance` checks, that works
too — the important part is that every event is a distinct, narrow,
`frozen` dataclass, not one bloated event with a dozen optional fields.

---

## **8. A runnable demo: fake event stream, no model, no I/O**

This is the payoff for this phase — you can exercise the entire type system
with zero network access, because nothing here talks to a real provider yet.

### **`packages/loom_core/src/loom_core/_demo.py`**

```python
"""Not part of the public API — a scratch script proving the types compose."""

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
    TurnEndEvent,
    TurnStartEvent,
)
from loom_core.messages import Message, Role, TextBlock, ToolCallBlock


def fake_turn() -> Iterator[AgentEvent]:
    """Simulates one turn: the model streams a sentence, no tool calls."""
    yield AgentStartEvent()
    yield TurnStartEvent(turn_index=0)
    yield MessageStartEvent(role="assistant")

    words = ["Reading", " the", " file", " now."]
    for i, word in enumerate(words):
        yield MessageUpdateEvent(
            assistant_message_event=AssistantMessageEvent(
                kind=StreamPartKind.TEXT_DELTA if i else StreamPartKind.TEXT_START,
                block_index=0,
                delta=word,
            )
        )

    final = Message(role=Role.ASSISTANT, content=(TextBlock(text="".join(words)),))
    yield MessageEndEvent(message=final)
    yield TurnEndEvent(turn_index=0)
    yield AgentEndEvent(reason=StopReason.DONE)


def main() -> None:
    for event in fake_turn():
        match event:
            case MessageUpdateEvent(assistant_message_event=sub):
                print(f"  delta: {sub.kind.value!r} -> {sub.delta!r}")
            case MessageEndEvent(message=msg):
                print(f"FINAL: {msg.text()!r}")
            case _:
                print(event)


if __name__ == "__main__":
    main()
```

### **Run it**

```bash
uv run python -m loom_core._demo
```

You should see each streaming delta printed, then the finished `FINAL:` line
— proving the "deltas are cosmetic, the final Message is authoritative" rule
holds even in this toy example: the final line doesn't depend on having
collected the deltas correctly, it's a real `Message` built directly.

---

## **9. Tests**

### **`tests/loom_core/test_messages.py`**

```python
from loom_core.messages import Message, Role, TextBlock, ToolCallBlock, user_message


def test_message_text_ignores_non_text_blocks() -> None:
    msg = Message(
        role=Role.ASSISTANT,
        content=(
            TextBlock(text="Let me check "),
            ToolCallBlock(id="1", name="read", arguments_json='{"path": "a.py"}'),
            TextBlock(text="that file."),
        ),
    )
    assert msg.text() == "Let me check that file."


def test_message_tool_calls_filters_correctly() -> None:
    call = ToolCallBlock(id="1", name="read", arguments_json="{}")
    msg = Message(role=Role.ASSISTANT, content=(TextBlock(text="ok"), call))
    assert msg.tool_calls() == (call,)


def test_message_is_frozen() -> None:
    msg = user_message("hi")
    try:
        msg.role = Role.SYSTEM  # type: ignore[misc]
    except Exception:
        pass
    else:
        raise AssertionError("Message should be immutable")
```

### **`tests/loom_core/test_events.py`**

```python
from loom_core._demo import fake_turn
from loom_core.events import AgentEndEvent, AgentStartEvent, MessageEndEvent


def test_fake_turn_starts_and_ends_cleanly() -> None:
    events = list(fake_turn())
    assert isinstance(events[0], AgentStartEvent)
    assert isinstance(events[-1], AgentEndEvent)


def test_fake_turn_final_message_matches_deltas() -> None:
    events = list(fake_turn())
    final = next(e for e in events if isinstance(e, MessageEndEvent))
    assert final.message.text() == "Reading the file now."
```

### **Run it**

```bash
uv run pytest tests/loom_core -v
```

---

## **10. Comparison table — how the real agents shape this**

| Concept | This phase (`loom_core`) | Tau (`tau_agent`) | Claude Code (per community analyses) |
|---|---|---|---|
| Message content | ordered tuple of typed content blocks | ordered content blocks on `AssistantMessage` | messages-as-state; content is structured, not a bare string |
| Streaming detail | `AssistantMessageEvent` nested in `MessageUpdateEvent` | `assistant_message_event` nested in `MessageUpdateEvent`, same 9 sub-kinds | delta events consumed by an async-generator loop |
| Source of truth | `MessageEndEvent.message`, deltas are cosmetic | explicit design rule: final message authoritative, deltas cosmetic | messages are the whole state; async generator yields, final `Message` returned as terminal value |
| Tool schema vs. execution | `ToolDefinition` (schema only) vs. execution in `loom_app` | tools registered on the harness; execution wired in `tau_coding` | "Tool interface as the core abstraction" — schema + permissions + execution kept as one uniform interface, but still layered above the loop |
| Event delivery mechanism | plain iterator (sync) for now; Phase 3 upgrades to `async for` | `async for event in harness.prompt(...)` | async generator; "natural backpressure and cancellation" |

---

## **11. A second reference set, and what we changed because of it**

A parallel set of Phase 0/1 notes (same research, independently drafted)
surfaced three real gaps in the version above, now folded in:

- **No error event existed.** `AgentEndEvent` used to carry a bare
  `reason: str`. It's now a closed `StopReason` enum plus a dedicated
  `AgentErrorEvent`, emitted right before an `AgentEndEvent(reason=ERROR)`
  — a renderer can show a real error state, and a session file has a
  distinct, greppable record of *why* a run stopped.
- **No safe way to use a raw tool-call argument string.** We kept
  `arguments_json` as a raw string on purpose (a malformed tool call from
  the model should still be a storable, replayable `Message`) but never
  gave you a safe way to *read* it. `ToolCallBlock.parsed_arguments()`
  now does a best-effort `json.loads`, returning `None` instead of raising
  — storage integrity and usability, without picking one over the other.
- **A missing intermediate layer, for Phase 2 to build, not this one.**
  The other notes define a *separate*, smaller event family
  (`TextDelta`/`ToolCallStart`/`ToolCallDelta`/`ToolCallEnd`/`StreamError`)
  that lives inside the provider package — raw vendor chunks normalize into
  that first, and only then does the loop assemble it into the richer
  `AgentEvent` stream from this file. We hadn't separated those two steps.
  Nothing changes in `loom_core` because of this — it's a heads-up for
  Phase 2, which now needs to define that smaller `StreamEvent` family and
  do the vendor-chunk → `StreamEvent` → `AgentEvent` handoff explicitly,
  instead of pretending providers hand you `AgentEvent`s directly.

Two things from that same reference set we deliberately did **not** adopt:

- **Bundling an executor callable onto the tool type itself.** Their `Tool`
  carries `executor: Callable[..., Awaitable[...]]` directly, in the
  portable layer. That's a real execution concern (subprocess calls,
  filesystem access for `bash`/`write`) leaking into the package that's
  supposed to be testable with zero I/O. Keeping `ToolDefinition` as pure
  schema (§5) is what lets Phase 3's loop tests run with *no* callables at
  all, real or fake.
- **A `Tool.openai_schema()` method on the core type.** That bakes OpenAI's
  specific wire format into the provider-neutral layer — precisely the
  leak the three-layer split exists to prevent. Translating a
  `ToolDefinition` into a vendor's function-calling JSON shape is Phase 2's
  job (the provider adapter), not something the type itself should know
  how to do.

---

## **12. Phase 1 checklist**

- [ ] `loom_core/messages.py` exists: `Role`, `TextBlock`, `ThinkingBlock`,
      `ToolCallBlock`, `ToolResultBlock`, `Message`, `user_message`,
      `system_message`
- [ ] `loom_core/tools.py` exists: `ToolDefinition`, `ToolOutcome`
- [ ] `loom_core/events.py` exists: full event hierarchy + `AgentEvent` union,
      including `StopReason` and `AgentErrorEvent`
- [ ] `ToolCallBlock.parsed_arguments()` returns a dict on valid JSON and
      `None` on malformed JSON, without raising
- [ ] `loom_core/_demo.py` runs and prints deltas + a final message
- [ ] `uv run pytest tests/loom_core -v` passes
- [ ] `uv run mypy packages/loom_core` passes with `strict = true`
- [ ] `uv run ruff check packages/loom_core` passes
- [ ] You can explain, out loud, without looking at this file: why content is
      a list of blocks instead of a string, and why deltas are cosmetic while
      the final message is authoritative
- [ ] `dev-notes/0002-message-and-event-shape.md` written (use the ADR
      template from Phase 0) — record anything you changed from this file
      and why

---

## **13. Common pitfalls at this layer**

- **Making `Message.content` a `list` instead of a `tuple`.** A mutable list
  invites "just append one more block to this old message" — which quietly
  breaks the "history never mutates" rule from §4. Use a tuple, or a frozen
  list wrapper, and make new `Message`s when content changes.
- **Putting `arguments_json` parsing in `loom_core`.** Parsing means JSON
  errors, which means error handling, which means you're one step from
  putting tool-execution logic in a package that isn't supposed to know
  tools can fail at runtime. Keep parsing in `loom_app`, next to execution.
- **Collapsing the event union into one big dataclass with a `type: str`
  field and a dozen optional attributes.** It compiles, mypy won't catch
  missing-field bugs as well, and every consumer ends up writing
  `if event.type == "message_end": ...` instead of getting exhaustiveness
  checking from `match`. Small, distinct, frozen dataclasses are worth the
  extra typing.
- **Reaching for `dict[str, Any]` "just to move faster."** Every place you
  do this in Phase 1 is a place Phase 2's provider adapter has to guess a
  shape instead of being told one by mypy. This phase is exactly the layer
  where the extra ten minutes of typing things properly pays for itself the
  most.

---

## **14. Known debt carried into later phases**

Two things this phase intentionally leaves unfinished, so they're written
down instead of forgotten:

- **No JSON serialization yet.** Every type here is a plain `dataclass` —
  there's no `to_dict`/`from_dict` pair, and none of the content-block union
  types can round-trip through `json.dumps`/`json.loads` on their own. This
  is fine right now (Phase 1 is pure in-memory data), but Phase 7
  (append-only session persistence) needs every one of these types to
  serialize to JSONL and back, including correctly re-discriminating the
  `ContentBlock` union on load using each block's `type` field. Plan on
  writing that dispatch table in Phase 7, not retrofitting it in a panic.
- **No `StreamEvent` type yet.** As noted in §11, the provider layer
  (Phase 2) needs its own small event family distinct from `AgentEvent`,
  so vendor chunks normalize into something before the loop assembles them
  into the richer stream this file defines. Phase 2's doc will define it.

---

## **Where to next?**

Phase 1 gives you a fully offline, fully typed vocabulary for messages, tools,
and events — the same vocabulary every later phase (provider adapters, the
loop, the harness, sessions, the TUI) will speak.

➡️ **Phase 2 — Provider interface with a fake provider and a real one.** This
is where a `Provider` protocol turns a `list[Message]` + `list[ToolDefinition]`
into a stream of the events you just built — first against a fake, in-memory
provider (so the loop in Phase 3 can be tested without any API key), then
against a real OpenAI-compatible endpoint.

Get the Phase 1 checklist fully green, then say the word. 🚀