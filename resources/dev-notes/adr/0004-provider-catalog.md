# ADR 0004: Provider catalog and two wire protocols

- Status: accepted
- Phase: 2.5
- Date: 2026-08-16

## Context

Phase 2 shipped one real provider adapter (`OpenAICompatibleProvider`) plus a
config-dumb constructor contract. Surveying DeepSeek Harness, Qwen Code,
OpenCode, Grok Build, and Hermes Agent showed the same pattern everywhere:
dozens of vendor names collapse to a small number of wire shapes, with vendor
choice living in a catalog above the adapter layer.

The open question for this phase was where vendor selection belongs, and how
many new provider classes are actually required before `loom_app` owns
credentials and CLI UX.

## Decision

1. **Two hand-written wire protocols in `loom_provider`.**
   - `openai-compatible` via the existing `OpenAICompatibleProvider`.
   - `anthropic-messages` via a new `AnthropicMessagesProvider` that maps
     Anthropic SSE events to the same `StreamEvent` union Phase 2 defined.

2. **The vendor catalog lives in `loom_app`, not `loom_provider`.**
   - `providers.toml` rows are plain data: `{id, protocol, base_url, env_key, models}`.
   - `loom_app.catalog.build_provider()` resolves env vars and constructs the
     right adapter. Empty `env_key` means no auth header (local endpoints).

3. **Phase 2.5 ships fifteen catalog rows.**
   OpenAI, Anthropic, DeepSeek, Qwen, Kimi/Moonshot, MiniMax, Z.AI/GLM,
   OpenRouter, Groq, Together, Fireworks, xAI, NVIDIA NIM, Hugging Face
   router, and a generic local OpenAI-compatible endpoint. Fourteen rows are
   catalog-only; Anthropic is the sole new adapter class because its
   `/v1/messages` stream is materially different from OpenAI chat completions.

## Alternatives considered

- **One provider class per vendor name.** Rejected. Hermes lists 37 named
  providers on three adapters; the constraint is curation, not adapter count.
- **Reading `providers.toml` inside `loom_provider`.** Rejected. Keeps adapters
  config-dumb and preserves the Phase 2 layering decision confirmed by Tau,
  Codex, and DSH.
- **Building Bedrock/Vertex/Azure/OAuth/Gemini adapters now.** Rejected. Each
  needs a credential shape `loom_app` does not own yet; the parsing code from
  this phase should reuse later once auth lands.

## Consequences

- Adding a new OpenAI-compatible vendor is a TOML row, not a code change.
- Anthropic integration validates that `StreamEvent` stayed vendor-neutral.
- Deferred work is explicit: `openai-responses`, native Gemini, Bedrock/Vertex/
  Azure auth layers, OAuth-as-provider, and per-model capability metadata in
  the catalog.
