# Phase 2.5 — Provider Catalog

> Phase 2 ships one wire adapter (`OpenAICompatibleProvider`) and a `Provider` protocol. This phase adds vendor selection without reopening that protocol: most vendors are catalog rows; Anthropic is the one new adapter class.

## 1. Goals

- Add **`AnthropicMessagesProvider`** for Anthropic `/v1/messages` (different SSE shape, tool envelope, auth headers).
- Add **`loom_app` catalog**: `providers.toml` maps `{id, protocol, base_url, env_key, models}` to a constructed `Provider`.
- Ship **15 catalog rows**. Fourteen use `OpenAICompatibleProvider`; Anthropic uses `AnthropicMessagesProvider`.
- Keep **`loom_provider` config-dumb** — no env reads, no TOML parsing inside adapters.

## 2. Layer split

| Layer | Owns |
|---|---|
| `loom_provider` | Wire translation only. Constructor args: `base_url`, `api_key`, `model`. |
| `loom_app` | `providers.toml`, env-key resolution, `build_provider()`. |

**Protocols (hand-written):**

- `openai-compatible` → `OpenAICompatibleProvider`
- `anthropic-messages` → `AnthropicMessagesProvider`

Deferred: `openai-responses`, native Gemini, Bedrock/Vertex/Azure/OAuth auth layers.

## 3. Catalog record

```toml
[[provider]]
id = "deepseek"
protocol = "openai-compatible"
base_url = "https://api.deepseek.com/v1"
env_key = "DEEPSEEK_API_KEY"
models = ["deepseek-v4-flash", "deepseek-v4-pro"]

[[provider]]
id = "anthropic"
protocol = "anthropic-messages"
base_url = "https://api.anthropic.com/v1"
env_key = "ANTHROPIC_API_KEY"
models = ["claude-sonnet-5", "claude-haiku-4-5"]

[[provider]]
id = "local"
protocol = "openai-compatible"
base_url = "http://localhost:8000/v1"
env_key = ""   # empty = no Authorization header
models = ["whatever-you-loaded"]
```

**Bundled catalog:** `packages/loom_app/src/loom_app/providers.toml` (15 rows).

**Builder:**

```python
def build_provider(entry: CatalogEntry, model: str) -> Provider:
    api_key = os.environ.get(entry.env_key, "") if entry.env_key else ""
    match entry.protocol:
        case "openai-compatible":
            return OpenAICompatibleProvider(
                base_url=entry.base_url, api_key=api_key, model=model
            )
        case "anthropic-messages":
            return AnthropicMessagesProvider(
                base_url=entry.base_url, api_key=api_key, model=model
            )
        case _:
            raise ValueError(f"unknown protocol: {entry.protocol}")
```

No per-vendor `if entry.id == "deepseek"` branches — new OpenAI-compatible vendors are TOML rows only.

## 4. Shipped catalog rows

| id | protocol | env_key |
|---|---|---|
| openai | openai-compatible | OPENAI_API_KEY |
| anthropic | anthropic-messages | ANTHROPIC_API_KEY |
| deepseek | openai-compatible | DEEPSEEK_API_KEY |
| qwen | openai-compatible | DASHSCOPE_API_KEY |
| kimi | openai-compatible | MOONSHOT_API_KEY |
| minimax | openai-compatible | MINIMAX_API_KEY |
| zai | openai-compatible | ZAI_API_KEY |
| openrouter | openai-compatible | OPENROUTER_API_KEY |
| groq | openai-compatible | GROQ_API_KEY |
| together | openai-compatible | TOGETHER_API_KEY |
| fireworks | openai-compatible | FIREWORKS_API_KEY |
| xai | openai-compatible | XAI_API_KEY |
| nvidia | openai-compatible | NVIDIA_API_KEY |
| huggingface | openai-compatible | HF_TOKEN |
| local | openai-compatible | (none) |

## 5. Anthropic wire differences

| Concern | OpenAI chat completions | Anthropic messages |
|---|---|---|
| System prompt | `"system"` message in array | top-level `system` field |
| Streaming | flat `data:` chunks + `finish_reason` | named events (`message_start`, `content_block_*`, `message_delta`) |
| Tool streaming | `delta.tool_calls[i].function.arguments` | `input_json_delta` keyed by block `index` |
| Tool schema | `{"type":"function","function":{...}}` | `{"name","description","input_schema"}` |
| Stop reason | `stop` / `tool_calls` / `length` | `end_turn` / `tool_use` / `max_tokens` |
| Auth | `Authorization: Bearer` | `x-api-key` + `anthropic-version` |

Both adapters map to the same `StreamEvent` union from Phase 2. Implementation lives in `loom_provider/anthropic_messages.py` with the same contract as `OpenAICompatibleProvider` (held `httpx.Client`, `close()`, `_build_payload` / `_handle_line`, `StreamError` on failures).

## 6. Deferred work

- **`openai-responses`** — OpenAI Responses API (third wire shape).
- **Native Gemini** — `generateContent`, not a catalog row.
- **Bedrock / Vertex / Azure / OAuth providers** — need credential layers in `loom_app`, not new SSE parsers.
- **Per-model capability metadata** — context length, vision, tool support in catalog rows.

## 7. Checklist

- [x] `AnthropicMessagesProvider` with Phase 2 lifecycle and error contract
- [x] Stream-event parity test vs `OpenAICompatibleProvider` for equivalent scripted turn
- [x] No `loom_core` / `loom_app` imports in `loom_provider`
- [x] `loom_app/catalog.py` loads TOML, resolves env, builds provider
- [x] `providers.toml` with 15 rows (both protocols, empty `env_key` for local)
- [x] Live smoke tests gated on `LOOM_TEST_API_KEY` / `LOOM_TEST_LOCAL`
- [x] `pytest`, `mypy`, `import-linter` green
- [x] ADR `adr/0004-provider-catalog.md`

## 8. References

- Phase 2 doc — provider boundary, config-dumb adapters
- ADR 0004 — catalog vs adapter split
- [Anthropic Messages API](https://platform.claude.com/docs/en/api/messages)
- [Alibaba DashScope OpenAI compatibility](https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope)
