# ADR 0002: Message and event shape

- Status: accepted
- Phase: 1
- Date: 2026-08-08

## Context

`loom_core` needed a vocabulary for two different things that are easy to
conflate: **finished conversation state** (what actually happened, gets
persisted and replayed) and **the stream of small updates that produce that
state** (what a UI renders live, as it happens). Getting the boundary between
those two wrong — either by flattening messages into plain strings, or by
treating streaming deltas as the source of truth — would have made every
later phase (the provider adapter, the loop, session persistence, the TUI)
harder to build correctly. This ADR records the three shape decisions that
came out of that, plus where the implementation moved during Phase 1 from
what an earlier draft of the plan assumed.

## Decision

### 1. `Message.content` is a tuple of typed content blocks, not a string

`Message.content: tuple[ContentBlock, ...]` — an ordered tuple of
`TextBlock | ThinkingBlock | ToolCallBlock | ToolResultBlock` — never a plain
`str`. A single assistant turn is not just text: the same turn can carry
reasoning content, one or more tool calls, and (as a separate message) tool
results, and the *order* of those pieces is meaningful — a tool call has to
render after the text that led up to it, not before.

**What a plain string would have broken:**
- No way to distinguish "the model said this" from "the model is thinking
  this" from "the model wants to call this tool with these arguments" — a
  renderer or a provider adapter would have to regex-parse a blob of text to
  recover structure that the model already gave us in typed form.
- No way to represent more than one tool call in a single turn without an
  ad-hoc delimiter format, which would then need its own escaping rules and
  its own parser — a second, informal type system growing inside a string
  field.
- Multi-turn tool use (call → result → call → result, all in one logical
  exchange) would have no principled way to round-trip: a `ToolResultBlock`
  needs a `tool_call_id` to correlate back to the call it answers, which a
  string has nowhere to carry.
- mypy can't help you here at all — every consumer would need runtime string
  parsing with no static guarantee the parse succeeded, exactly the
  `dict[str, Any]` failure mode flagged in §13 of the Phase 1 doc.

### 2. Streaming deltas are cosmetic; only `MessageEndEvent.message` is persisted or replayed

The event hierarchy (`AgentStartEvent` → `TurnStartEvent` →
`MessageStartEvent` → `MessageUpdateEvent` → `MessageEndEvent` → ...) exists
so a UI can render responsively — print a spinner, stream tokens as they
arrive, show a tool call assembling live. But the *only* thing that ever gets
written to a session file or replayed is the finished `Message` object
carried on `MessageEndEvent.message`. `MessageUpdateEvent`'s nested
`AssistantMessageEvent` deltas are consumed once, for rendering, and then
discarded — never reconstructed into a `Message` after the fact.

This mirrors Tau's own explicit rule (their docs state renderers work from
provider-neutral events, never raw provider chunks, and that the final
message is authoritative) and matches how Claude Code's async-generator loop
is described in independent community analyses: the generator yields
progress, but a real, structured value is what's actually returned/persisted
at the end.

Enforced structurally, not just by convention: `loom_core/_demo.py`'s
`fake_turn()` builds `final = Message(...)` directly from the same source
data used to generate the deltas, rather than folding the delta stream back
into a `Message`. There is deliberately no `assemble_message_from_deltas()`
helper in this phase — if one gets written later (e.g. inside a provider
adapter that needs to build a `Message` from `StreamEvent`s), it belongs in
Phase 2/3, and it's still only ever used to *produce* the object that goes on
`MessageEndEvent`, never treated as a second source of truth alongside it.

### 3. Divergences from the initial Phase 1 draft

Three changes were made to the plan during Phase 1, all captured in the
Phase 1 doc's own §11 ("a second reference set, and what we changed because
of it") and worth restating here as the actual decision record:

- **`AgentEndEvent.reason` became a closed `StopReason` enum, plus a new
  `AgentErrorEvent`.** The original draft had `AgentEndEvent` carrying a bare
  `reason: str`. A free-form string can't be exhaustively matched on and
  gives a session file no reliable, greppable record of *why* a run ended.
  `AgentErrorEvent` is now emitted immediately before an
  `AgentEndEvent(reason=StopReason.ERROR)`, giving both a typed reason code
  and a distinct event carrying the actual error detail.
- **`ToolCallBlock.parsed_arguments()` was added.** The original draft kept
  `arguments_json` as a raw string (correct — see the "why it stays a raw
  string" note in the Phase 1 doc) but never gave callers a safe way to
  *read* it. Added a best-effort-parse method that returns `None` on a
  `JSONDecodeError` or on valid-but-non-dict JSON, and never raises. See
  issue #3 for the follow-up that confirmed this is where the method belongs
  (on the type itself, in `loom_core`, not in Phase 2's provider layer or
  Phase 5's executor).
- **The raw provider-chunk → `AgentEvent` handoff was identified as missing
  a step, deferred to Phase 2, not built here.** The original draft implied
  providers hand the loop `AgentEvent`s more or less directly. The corrected
  understanding — confirmed independently against Tau, `pi-agent-core`, and
  the OpenAI Agents SDK during Phase 2's research — is that there's a
  distinct, smaller `StreamEvent` family living in `loom_provider`, and the
  loop (Phase 3) is what assembles a `StreamEvent` sequence into the richer
  `AgentEvent`s this file defines. Nothing in `loom_core` changed because of
  this; it changed what Phase 2 was scoped to build.

Two things proposed in that same second-reference-set pass were considered
and explicitly **rejected**:

- **An `executor: Callable[..., Awaitable[...]]` field bundled directly onto
  the tool type.** Rejected because it puts an execution concern
  (subprocess calls, filesystem access) inside the package that's supposed
  to be testable with zero I/O. `ToolDefinition` stays pure schema; execution
  is wired in `loom_app`.
- **A `Tool.openai_schema()` method on the core type.** Rejected because it
  bakes one vendor's wire format into the provider-neutral layer — exactly
  the leak the `loom_app → loom_core → loom_provider` layering exists to
  prevent. Translating `ToolDefinition` into a vendor's function-calling JSON
  shape is a provider adapter's job (Phase 2), not the type's.

## Alternatives considered

- **A single flat `Message` dataclass with optional fields** (`text: str |
  None`, `tool_call: dict | None`, etc.) instead of a content-block union.
  Rejected: optional-field sprawl doesn't compose (what does it mean for
  `tool_call` and `text` to both be set? both `None`?), and it can't express
  more than one tool call per turn without adding a list field anyway, at
  which point you've reinvented the block tuple with worse ergonomics.
- **Reconstructing the persisted `Message` from accumulated deltas** instead
  of carrying it explicitly on `MessageEndEvent`. Rejected: it makes the
  delta stream a second source of truth that has to be assembled correctly
  under all conditions (interleaved tool calls, thinking blocks, provider
  quirks), when the provider adapter can just as easily hand back a real,
  already-correct `Message` at turn-end and let deltas be purely cosmetic.
- **Eagerly parsing `arguments_json` at `ToolCallBlock` construction time**
  instead of lazily via `parsed_arguments()`. Rejected: a malformed tool call
  from the model still needs to exist as a valid, storable, replayable
  `Message` — eager parsing would mean construction itself could fail, which
  is the wrong failure mode for something Phase 7 needs to persist and load
  back from disk unconditionally.
- **A `type: str` field with a dozen optional attributes on one big
  dataclass**, instead of a closed union of small frozen dataclasses, for
  both `ContentBlock` and `AgentEvent`. Rejected per Phase 1 doc §13: it
  compiles, but loses `match`-statement exhaustiveness checking and pushes
  every consumer toward `if event.type == "...":` string comparisons instead
  of a type system catching a missed case.

## Consequences

**Easier:**
- Every later phase gets a typed, exhaustively-matchable vocabulary instead
  of re-deriving structure from strings — Phase 2's provider adapters, Phase
  3's loop, and Phase 7's session persistence all consume the same
  `ContentBlock`/`AgentEvent` unions without guessing shapes.
- A malformed tool call from the model is still a perfectly valid, storable,
  replayable `Message` (raw `arguments_json` + safe `parsed_arguments()`),
  so a parse failure never corrupts history or crashes construction.
- Renderers (print mode, a future TUI) can be swapped freely because they
  all consume the same `AgentEvent` stream and none of them are a special
  case — this was true from Phase 1 and stays true through later phases.
- The "final message authoritative, deltas cosmetic" rule means a crashed or
  interrupted render never corrupts persisted state — there's no delta
  buffer to have gotten out of sync with what's on disk.

**Harder / deferred, on purpose:**
- None of these types serialize to JSON yet (`dataclass`, no `to_dict`/
  `from_dict`). Phase 7 has to write that dispatch table, including
  correctly re-discriminating the `ContentBlock` and `AgentEvent` unions on
  load by each variant's `type` field. Flagged as known debt in the Phase 1
  doc, not forgotten.
- `loom_provider`'s own `StreamEvent` family (Phase 2) duplicates some
  shape (text/tool-call deltas exist in both `StreamEvent` and nested inside
  `AgentEvent`) by design — collapsing them into one type was considered and
  rejected during Phase 2's research (see the Phase 2 ADR / addendum) because
  it would leak vendor-adjacent wire concerns into `loom_core`. Two families
  to keep straight is the accepted cost of that boundary.
- Compaction (Phase 23) has to produce *new* `Message` objects rather than
  mutating history in place, since everything here is `frozen=True` — the
  right constraint for correctness, but it means compaction can't be a
  cheap in-place edit; it's always a rewrite.