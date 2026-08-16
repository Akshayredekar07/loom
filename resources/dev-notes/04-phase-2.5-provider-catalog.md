# Phase 2.5 — A Provider Catalog: 37 Vendors Surveyed, 15 Shipped, Without Reopening Phase 2

> **Scope note.** Phase 2 built one real `Provider`: `OpenAICompatibleProvider`, plus the `Provider` protocol it and `FakeProvider` both satisfy. This phase does not touch that protocol's shape. It answers a narrower question that came up while surveying other harnesses: *how do production agents let a user point at DeepSeek, Qwen, Kimi/Moonshot, MiniMax, Anthropic, Bedrock, or a random self-hosted vLLM box, without hand-writing a new provider class for each one?* The answer, confirmed independently by every harness surveyed below, is: **most of those aren't new wire shapes at all — they're the same one or two wire shapes plus a config record.** Only a handful of vendors need genuinely new code.

## 1. Goal of this phase

By the end of this phase:

- `loom_provider` gains exactly **one** new concrete `Provider`: `AnthropicMessagesProvider`, because Anthropic's `/v1/messages` is a materially different wire shape from OpenAI's `/v1/chat/completions` (different SSE event names, different tool-use envelope, different content-block model).
- §6 surveys **37 named vendors** across five independent harnesses (DeepSeek Harness, Qwen Code, OpenCode, Alibaba Model Studio, Hermes Agent) and picks **15 for this phase's actual `providers.toml`**: OpenAI, Anthropic, DeepSeek, Qwen, Kimi/Moonshot, MiniMax, Z.AI/GLM, OpenRouter, Groq, Together, Fireworks, xAI, NVIDIA NIM, Hugging Face's router, and a generic local/no-auth endpoint (Ollama/vLLM/LM Studio/SGLang). 14 of those 15 are reached through the **existing** `OpenAICompatibleProvider` plus a **provider catalog entry** — a small data record naming a `base_url`, an env-var key, and a model list. No new Python class.
- `loom_app` (not `loom_provider`) gains a `providers.toml`-style **catalog**: a config-driven table mapping a provider id to `{protocol, base_url, env_key, models}`. `loom_provider` stays exactly as config-dumb as Phase 2 left it — the catalog is what constructs an `OpenAICompatibleProvider(base_url=..., api_key=..., model=...)` or an `AnthropicMessagesProvider(...)`, not something either provider class reads for itself.
- The remaining 22 surveyed vendors (Bedrock, Vertex, Azure, native Gemini, every OAuth-as-provider option, and a long tail of Hermes-only names not yet requested by this project's users) are named individually in §6 and scoped as explicit future work in §8 — not silently dropped, and not built speculatively before `loom_app`'s credential layer exists to own them.

## 2. Research recap — ten systems, cross-checked for provider abstraction specifically

Phase 2's research pass already covered Tau, pi-agent-core, OpenAI Agents SDK, Codex, Grok Build, and Hermes for the *provider vs. loop* boundary. This pass goes narrower and asks a different question of a mostly-different set: **when a harness supports many vendors, where does "which vendor" live, and how many actual wire-format implementations does it end up with?**

**DeepSeek Harness (`deepseek-ai/deepseek-harness`) — the most directly relevant new source.** DSH's own architecture docs describe every replaceable capability as a "seam" with three roles: a Service Definition (the interface), a Service Provider (an implementation), and a Consumer. Its `llm/` package group is exactly this seam applied to models: a service definition, a DeepSeek-native provider, and — critically — a second, provider-neutral route it calls `llm-pi-ai` that fans out to *configured* providers rather than being one more hand-written adapter. The user-facing config for that route is exactly a catalog: a provider id, a base URL, an **API protocol** field, a credential, and a model list. DSH's own docs enumerate that protocol field's values as `openai-completions`, `openai-responses`, and `anthropic-messages` — three wire shapes, not one per vendor. DSH's provider docs also draw the line this phase draws independently: providers with a plain API key (DeepSeek, OpenAI, Anthropic, a custom gateway) go through the catalog; providers with native auth (Bedrock's AWS credentials + region, Vertex's ADC project, Azure's api-version, Codex's OAuth) are called out as a *different* configuration shape, not a variant of the same one.

**Qwen Code (`QwenLM/qwen-code`).** Confirms the same split from a completely independent codebase. Its `modelProviders` setting maps a provider id to a model list, and separately, a top-level `providerProtocol` setting maps *custom* provider ids to a protocol; built-in provider ids (`openai`, `anthropic`, `gemini`, `vertex-ai`) already know their own protocol. Qwen Code's own third-party-provider menu — DeepSeek, MiniMax, Z.AI, Idealab, ModelScope, OpenRouter, Requesty — are all reached this way: a name, a base URL, and (implicitly) the OpenAI protocol, not bespoke code per vendor. Alibaba's own Model Studio docs list DeepSeek, Kimi, GLM, and MiniMax as all reachable through its one OpenAI-compatible endpoint by swapping `base_url` and model name — independent confirmation that these vendor names are catalog entries, not wire shapes.

**OpenCode.** A third independent confirmation of the same shape, from a project with no code relationship to the first two. Its config schema names a `package` per provider — `@opencode-ai/ai/providers/openai-compatible` is the one used for any OpenAI-shaped custom gateway — and the provider-specific part of the config is just `baseURL`, an env var name for the key, and a `models` map with capability/limit metadata. A brand-new OpenAI-compatible vendor needs a JSON block, not a new package.

**Grok Build (`xai-org/grok-build`)** and **Codex (`openai/codex`)** — already covered in Phase 2's research pass — both keep a config-driven catalog (`~/.grok/config.toml`'s `[model.*]` blocks; Codex's `SharedModelProvider`) separate from the wire-translation code, reinforcing rather than adding to the pattern above.

**Hermes Agent (`NousResearch/hermes-agent`) — the widest fourth source, and the sharpest confirmation.** Hermes's `hermes model` picker lists **37 distinct named providers** (Nous Portal, OpenAI Codex, Anthropic, OpenRouter, Fireworks, Z.AI, Kimi/Moonshot plus a China region, Arcee AI, GMI Cloud, Actual Computer, MiniMax plus an OAuth variant plus a China region, Alibaba/DashScope, Hugging Face's router, AWS Bedrock, Azure Foundry, Google AI Studio, xAI plus a Grok-OAuth variant, NovitaAI, StepFun, Xiaomi MiMo, Tencent TokenHub, Ollama Cloud, LM Studio, Qwen OAuth, Kilo Code, OpenCode Zen, OpenCode Go, DeepSeek, NVIDIA NIM, GitHub Copilot plus an ACP variant, Vercel AI Gateway), plus an open-ended custom-endpoint catalog for anything else. Despite that count, its own `developer-guide/adding-providers.md` names exactly **one** dispatch field — `api_mode` — with exactly **three** values: `chat_completions` (nearly all 37 providers), `anthropic_messages` (Anthropic native), and `codex_responses` (OpenAI's Responses API, used by the Codex provider entry). The same doc is explicit that adding a 38th OpenAI-compatible provider touches only auth/config/CLI-menu files, never the adapter layer — "Do not add a built-in provider unless you want first-class UX for that service," it says, naming provider-specific auth, a curated model catalog, and setup-menu entries as the actual reasons to write new code, not the wire format. Two things Hermes adds that DSH/Qwen Code/OpenCode hadn't: **OAuth as a first-class provider option** (MiniMax OAuth, Grok OAuth, Qwen OAuth, Codex's device-code flow all sit in the same picker as API-key providers, running over the *same* `chat_completions`/`codex_responses` adapters underneath), and confirmation that `codex_responses` (this doc's deferred `openai-responses`) is real, named, and already shipping in a production harness — not a hypothetical.

**Four convergent findings, all independent of each other:**

1. **The number of "real" wire shapes a harness needs to hand-write is small — typically two or three — regardless of how many vendor *names* it lists.** DSH names exactly three (`openai-completions`, `openai-responses`, `anthropic-messages`). Every harness surveyed treats "OpenAI-compatible" as a single implementation serving a long, growing, unbounded list of vendor names.
2. **A model catalog is data, colocated with credentials and base URLs, and lives above the provider-adapter layer.** DSH stores it in a settings file plus a write-only credential store; Qwen Code in `settings.json`; OpenCode in `opencode.json`; Grok Build in `~/.grok/config.toml`. None of them put vendor selection logic inside the class that speaks the wire protocol. This is exactly the `loom_app`-vs-`loom_provider` split this project's Phase 2 doc already argued for on OpenAI Agents SDK grounds (§11 of that doc) — now confirmed by three more, architecturally unrelated systems.
3. **Native (non-API-key) auth is treated as a categorically different case, not a fourth protocol value.** DSH's docs are explicit that Bedrock/Vertex/Azure/Codex "use AWS credentials and a region, an ADC project, an api-version, and OAuth respectively" — each is its own credential shape, layered on top of (for Bedrock/Vertex/Azure) what is still substantially an OpenAI- or Anthropic-shaped request/response body once auth is handled. That's useful: it means the *wire parsing* code in `AnthropicMessagesProvider` and `OpenAICompatibleProvider` is reusable for Bedrock/Vertex/Azure later; only the *auth and endpoint-construction* layer needs new code, and that's exactly what §8 below scopes as deferred rather than building speculatively.
4. **A vendor count in the dozens is normal, and none of it pressures the adapter layer.** Hermes shipping 37 named providers on 3 wire adapters is the clearest evidence in the whole survey that "how many providers can we support" and "how much code do we need to write" are almost unrelated questions once the catalog pattern is in place — the constraint is curation and testing effort per catalog row, not engineering.

**Not folded into this phase, and why:**

- **AWS Bedrock, Google Vertex, Azure OpenAI, and any OAuth-based login flow (Codex-style)** are real, common, and confirmed by DSH's own docs to need a different credential shape each. None of them are a new *streaming event* shape on top of what `OpenAICompatibleProvider`/`AnthropicMessagesProvider` already parse (Bedrock and Vertex both offer Anthropic- or OpenAI-shaped bodies over their own signed transport; Azure OpenAI is the OpenAI shape plus an `api-version` query param and a different auth header). Building the auth layer now, before `loom_app` exists to own credential storage, would mean guessing at an interface Phase visitors after Phase 3 haven't specified yet. Scoped explicitly in §8 instead of built speculatively.
- **Google's native Gemini API** (as opposed to Vertex) uses neither the OpenAI chat-completions shape nor Anthropic's messages shape — it's a third real wire format (`generateContent`/`streamGenerateContent`, a different content-part and function-call envelope). Qwen Code lists `gemini` as a first-class protocol precisely because it isn't reducible to the other two. Out of scope for this phase for the same reason as Bedrock/Vertex: real work, not a catalog entry, and not yet needed by any vendor this project's users have asked for.

## 3. What this means for `loom_provider` vs. `loom_app`

Phase 2 already drew the `loom_provider` / `loom_core` boundary. This phase draws the next one down, `loom_provider` vs. `loom_app`, using the same reasoning DSH, Qwen Code, and OpenCode independently converged on:

- **`loom_provider` gains one new class and zero config-reading code.** `AnthropicMessagesProvider` takes `base_url`, `api_key`, `model` as plain constructor args, exactly like `OpenAICompatibleProvider` — no environment reads, no catalog awareness. It stays exactly as "configuration-dumb" as Phase 2 §11 already committed `OpenAICompatibleProvider` to being.
- **The catalog — provider id → `{protocol, base_url, env_key, models}` — lives in `loom_app`, not `loom_provider`.** This is `loom_app` territory for the same reason Phase 2 gave for keeping vendor selection out of `loom_provider`: an app that knows about `~/.loom/providers.toml`, environment variables, or a future `/login` flow is a different layer of concern than a class that knows how to parse an SSE chunk.
- **The catalog has exactly two protocol values to start: `openai-compatible` and `anthropic-messages`.** DSH's third value, `openai-responses` (OpenAI's newer Responses API, distinct from Chat Completions), is named here and deliberately not built — noted in §8 as debt, not silently dropped.

## 4. The catalog shape

`loom_app`'s catalog is a plain list of records — no new abstraction, no `Protocol` class, because it's data, not behavior:

```toml
# ~/.loom/providers.toml — loom_app territory, loom_provider never reads this file.

[[provider]]
id = "deepseek"
protocol = "openai-compatible"
base_url = "https://api.deepseek.com/v1"
env_key = "DEEPSEEK_API_KEY"
models = ["deepseek-chat", "deepseek-reasoner"]

[[provider]]
id = "qwen"
protocol = "openai-compatible"
base_url = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
env_key = "DASHSCOPE_API_KEY"
models = ["qwen3-coder-plus", "qwen3-coder-flash"]

[[provider]]
id = "kimi"
protocol = "openai-compatible"
base_url = "https://api.moonshot.ai/v1"
env_key = "MOONSHOT_API_KEY"
models = ["kimi-k2"]

[[provider]]
id = "minimax"
protocol = "openai-compatible"
base_url = "https://api.minimax.io/v1"
env_key = "MINIMAX_API_KEY"
models = ["minimax-m2"]

[[provider]]
id = "anthropic"
protocol = "anthropic-messages"
base_url = "https://api.anthropic.com/v1"
env_key = "ANTHROPIC_API_KEY"
models = ["claude-sonnet-4-6", "claude-haiku-4-5"]

[[provider]]
id = "local-vllm"
protocol = "openai-compatible"
base_url = "http://localhost:8000/v1"
env_key = ""            # empty = no auth header sent
models = ["whatever-you-loaded"]
```

`loom_app`'s job, and only `loom_app`'s job, is: read this file, resolve `env_key` from the environment (skip the header entirely when `env_key` is empty, matching how OpenCode treats an unauthenticated local endpoint), and construct the right `loom_provider.Provider` for the chosen `protocol`:

```python
# loom_app/catalog.py — sketch, not this phase's deliverable

def build_provider(entry: CatalogEntry, model: str) -> Provider:
    api_key = os.environ.get(entry.env_key, "") if entry.env_key else ""
    match entry.protocol:
        case "openai-compatible":
            return OpenAICompatibleProvider(base_url=entry.base_url, api_key=api_key, model=model)
        case "anthropic-messages":
            return AnthropicMessagesProvider(base_url=entry.base_url, api_key=api_key, model=model)
        case _:
            raise ValueError(f"unknown protocol: {entry.protocol}")
```

Note what's *not* here: no per-vendor `if entry.id == "deepseek"` branch. That branch would be the mistake — DSH, Qwen Code, and OpenCode all avoid it, and the whole point of the catalog is that adding MiniMax or Kimi later is a five-line TOML addition, not a code change, exactly like adding a custom OpenAI-compatible gateway already was.

## 5. The one real new provider: `loom_provider/anthropic_messages.py`

Anthropic's `/v1/messages` is genuinely a different wire shape from OpenAI's `/v1/chat/completions`, which is why it's the one vendor in this whole survey that earns a new `Provider` class rather than a catalog row. The differences that matter for `_build_payload`/`_handle_line`-equivalent code:

| | OpenAI chat completions (Phase 2) | Anthropic messages (this phase) |
|---|---|---|
| System prompt | a `"system"`-role message in the `messages` array | a top-level `system` string field, outside `messages` |
| Streaming events | one flat `data:` chunk shape, distinguished by `delta.content` vs `delta.tool_calls` vs `finish_reason` | named SSE event types (`message_start`, `content_block_start`, `content_block_delta`, `content_block_stop`, `message_delta`, `message_stop`), each with a different payload shape |
| Tool call streaming | `tool_calls[i].function.arguments` fragments, keyed by array `index` | a `content_block_delta` with `delta.type == "input_json_delta"`, keyed by the block's `index` from the matching `content_block_start` |
| Tool definition envelope | `{"type": "function", "function": {"name", "description", "parameters"}}` | `{"name", "description", "input_schema"}` — no `"type"`/`"function"` wrapper |
| Stop reason vocabulary | `finish_reason`: `"stop" \| "tool_calls" \| "length"` | `stop_reason`: `"end_turn" \| "tool_use" \| "max_tokens" \| "stop_sequence"` |
| Usage | attached to the final chunk only, sometimes | `message_start` carries input tokens, `message_delta` carries output tokens — usage arrives in two pieces, not one |
| Auth header | `Authorization: Bearer <key>` | `x-api-key: <key>` plus a required `anthropic-version` header |

None of this changes `loom_provider/events.py` or `loom_provider/provider.py` — `AnthropicMessagesProvider` maps every one of these shapes down to the same `StreamEvent` union (`TextDelta`, `ToolCallStart`, `ToolCallDelta`, `ToolCallEnd`, `StreamEnd`, `StreamError`) that `OpenAICompatibleProvider` already produces. That union was designed provider-neutral in Phase 2 precisely so this would be true; this phase is the first real test of that claim, not a redesign of it.

Implementation follows the exact shape of Phase 2 §7: one `httpx.Client` held per instance, `close()`/context-manager parity, a private `_build_payload`/`_handle_line` pair that is the only code in the module allowed to know Anthropic's JSON shape, `StreamError` (never a silent `return`) on any transport or parse failure, and unit tests that call `_build_payload`/`_handle_line` directly rather than mocking `httpx`. The two providers should be reviewed side by side once both exist, specifically to confirm `StreamEvent` really did stay vendor-neutral and neither implementation quietly leaked an OpenAI- or Anthropic-shaped assumption into it.

## 6. Full vendor survey, and the 15 targeted for this phase

Every vendor name that came up anywhere in this research pass, deduplicated across DeepSeek Harness, Qwen Code, OpenCode, Alibaba Model Studio, and Hermes Agent (the largest single list — 37 named providers). Protocol column is what the source docs say each one actually speaks; **Phase 1** marks the 15 this phase actually ships a catalog row for.

| # | Provider | Protocol | Seen in | Phase 1? |
|---|---|---|---|---|
| 1 | OpenAI (direct) | `openai-compatible` | all | **yes** |
| 2 | Anthropic (API key) | `anthropic-messages` | all | **yes** — the one new class |
| 3 | DeepSeek | `openai-compatible` | DSH, Qwen Code, Model Studio, Hermes | **yes** |
| 4 | Qwen / Alibaba DashScope | `openai-compatible` | Qwen Code, Model Studio, Hermes | **yes** |
| 5 | Kimi / Moonshot | `openai-compatible` | Model Studio, Hermes | **yes** |
| 6 | MiniMax | `openai-compatible` | Qwen Code, Model Studio, Hermes | **yes** |
| 7 | Z.AI / GLM | `openai-compatible` | Qwen Code, Hermes | **yes** |
| 8 | OpenRouter | `openai-compatible` | Qwen Code, Hermes | **yes** |
| 9 | Groq | `openai-compatible` | general OpenAI-compat ecosystem | **yes** |
| 10 | Together AI | `openai-compatible` | general OpenAI-compat ecosystem | **yes** |
| 11 | Fireworks AI | `openai-compatible` | Hermes | **yes** |
| 12 | xAI / Grok (API key) | `openai-compatible` | Hermes | **yes** |
| 13 | NVIDIA NIM | `openai-compatible` | Hermes | **yes** |
| 14 | Hugging Face router | `openai-compatible` | Hermes | **yes** |
| 15 | Local endpoint (Ollama / vLLM / LM Studio / SGLang) | `openai-compatible` | all | **yes** — one generic "custom" row, `env_key = ""` |
| 16 | Anthropic (OAuth / Claude Max) | `anthropic-messages` + OAuth | Hermes | no — §8 |
| 17 | OpenAI Codex | `codex_responses` (OpenAI Responses API) | Hermes | no — §8 |
| 18 | AWS Bedrock | Anthropic/OpenAI-shaped body over SigV4 | DSH, Hermes | no — §8 |
| 19 | Google Vertex AI | Anthropic/OpenAI/Gemini-shaped body over ADC | DSH, Qwen Code | no — §8 |
| 20 | Azure OpenAI / Azure Foundry | `openai-compatible` + `api-version` + Azure AD | DSH, Hermes | no — §8 |
| 21 | Google AI Studio (native Gemini) | `generateContent` (genuinely different) | Qwen Code, Hermes | no — §8 |
| 22 | GitHub Copilot | `openai-compatible` + Copilot OAuth | Hermes | no — §8 |
| 23 | GitHub Copilot ACP | spawns local `copilot` CLI, not a wire call at all | Hermes | no — different capability, not a `Provider` |
| 24 | xAI Grok (OAuth / SuperGrok) | `openai-compatible` + OAuth | Hermes | no — §8 |
| 25 | Qwen (OAuth) | `openai-compatible` + OAuth | Qwen Code, Hermes | no — §8 |
| 26 | MiniMax (OAuth) | `openai-compatible` + OAuth | Hermes | no — §8 |
| 27 | Vercel AI Gateway | `openai-compatible`-ish, own model discovery endpoint | Hermes | no — needs its own `/models` handling |
| 28 | Nous Portal | `openai-compatible` + JWT | Hermes | no — vendor-specific auth |
| 29 | NovitaAI | `openai-compatible` | Hermes | no — not yet requested |
| 30 | StepFun | `openai-compatible` | Hermes | no — not yet requested |
| 31 | Xiaomi MiMo | `openai-compatible` | Hermes | no — not yet requested |
| 32 | Tencent TokenHub | `openai-compatible` | Hermes | no — not yet requested |
| 33 | Ollama Cloud | `openai-compatible` | Hermes | no — covered by #15's generic local row for now |
| 34 | Arcee AI | `openai-compatible` | Hermes | no — not yet requested |
| 35 | GMI Cloud | `openai-compatible` | Hermes | no — not yet requested |
| 36 | Actual Computer | `openai-compatible`, relay or local daemon | Hermes | no — not yet requested |
| 37 | Kilo Code / OpenCode Zen / OpenCode Go | `openai-compatible`, gateway-specific billing | Hermes | no — not yet requested |

**Reading the table:** rows 1–15 are the phase's actual deliverable — a `providers.toml` with 15 entries, 14 of which point at the `OpenAICompatibleProvider` this project already has and 1 (Anthropic) at the new `AnthropicMessagesProvider` from §5. Rows 16–27 are named because they showed up in at least one real harness and need something *other* than a new wire adapter — OAuth, a signed-request auth layer, or a genuinely different streaming shape — each reason is called out per-row rather than lumped together, and all of it is still §8 debt, not silently dropped. Rows 28–37 are provider names that exist and work in Hermes today but haven't come up as something this project's own users have asked for yet — listed for completeness of the survey, not queued as work.

The concrete `providers.toml` for the 15:

```toml
# ~/.loom/providers.toml — Phase 1 catalog. loom_provider never reads this file.

[[provider]]
id = "openai"
protocol = "openai-compatible"
base_url = "https://api.openai.com/v1"
env_key = "OPENAI_API_KEY"
models = ["gpt-5.1", "gpt-5.1-mini"]

[[provider]]
id = "anthropic"
protocol = "anthropic-messages"
base_url = "https://api.anthropic.com/v1"
env_key = "ANTHROPIC_API_KEY"
models = ["claude-sonnet-4-6", "claude-haiku-4-5"]

[[provider]]
id = "deepseek"
protocol = "openai-compatible"
base_url = "https://api.deepseek.com/v1"
env_key = "DEEPSEEK_API_KEY"
models = ["deepseek-chat", "deepseek-reasoner"]

[[provider]]
id = "qwen"
protocol = "openai-compatible"
base_url = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
env_key = "DASHSCOPE_API_KEY"
models = ["qwen3-coder-plus", "qwen3-coder-flash"]

[[provider]]
id = "kimi"
protocol = "openai-compatible"
base_url = "https://api.moonshot.ai/v1"
env_key = "MOONSHOT_API_KEY"
models = ["kimi-k2"]

[[provider]]
id = "minimax"
protocol = "openai-compatible"
base_url = "https://api.minimax.io/v1"
env_key = "MINIMAX_API_KEY"
models = ["minimax-m2"]

[[provider]]
id = "zai"
protocol = "openai-compatible"
base_url = "https://api.z.ai/api/paas/v4"
env_key = "ZAI_API_KEY"
models = ["glm-4.6"]

[[provider]]
id = "openrouter"
protocol = "openai-compatible"
base_url = "https://openrouter.ai/api/v1"
env_key = "OPENROUTER_API_KEY"
models = ["<any OpenRouter-routed model id>"]

[[provider]]
id = "groq"
protocol = "openai-compatible"
base_url = "https://api.groq.com/openai/v1"
env_key = "GROQ_API_KEY"
models = ["llama-3.3-70b-versatile"]

[[provider]]
id = "together"
protocol = "openai-compatible"
base_url = "https://api.together.xyz/v1"
env_key = "TOGETHER_API_KEY"
models = ["<any Together-hosted model id>"]

[[provider]]
id = "fireworks"
protocol = "openai-compatible"
base_url = "https://api.fireworks.ai/inference/v1"
env_key = "FIREWORKS_API_KEY"
models = ["<any Fireworks-hosted model id>"]

[[provider]]
id = "xai"
protocol = "openai-compatible"
base_url = "https://api.x.ai/v1"
env_key = "XAI_API_KEY"
models = ["grok-4"]

[[provider]]
id = "nvidia"
protocol = "openai-compatible"
base_url = "https://integrate.api.nvidia.com/v1"
env_key = "NVIDIA_API_KEY"
models = ["<any NIM-hosted model id>"]

[[provider]]
id = "huggingface"
protocol = "openai-compatible"
base_url = "https://router.huggingface.co/v1"
env_key = "HF_TOKEN"
models = ["<any HF-router-hosted model id>"]

[[provider]]
id = "local"
protocol = "openai-compatible"
base_url = "http://localhost:8000/v1"
env_key = ""            # empty = no auth header sent
models = ["whatever-you-loaded"]
```

## 7. Comparison table

| Concept | loom (this phase) | DeepSeek Harness | Qwen Code | OpenCode | Hermes Agent |
|---|---|---|---|---|
| Wire shapes hand-implemented | 2 (`openai-compatible`, `anthropic-messages`) | 3 (`openai-completions`, `openai-responses`, `anthropic-messages`) | protocol per built-in auth type (`openai`, `anthropic`, `gemini`, `vertex-ai`) + custom via `providerProtocol` | one native package per protocol family (e.g. `openai-compatible`) | 3 (`chat_completions`, `anthropic_messages`, `codex_responses`) |
| Named providers shipped | 15 (this phase) | fewer named, catalog-first | ~10 built-in + unlimited custom | unlimited via config | **37** named + unlimited custom |
| Vendor catalog location | `loom_app` (`providers.toml`) | Settings UI + `$DSH_HOME/.credentials.yaml` (write-only keys) | `settings.json` `modelProviders` | `opencode.json` `providers` map | `runtime_provider.py` resolver + `config.yaml`/`.env` |
| New vendor = new code? | No — new TOML row | No — "Add a custom provider" form | No — new `modelProviders` entry | No — new JSON block | No, unless it needs OAuth/curated UX — explicit in their own dev docs |
| Native (non-key) auth | named, deferred (§8) | Bedrock/Vertex/Azure/Codex each named as distinct credential shapes | not covered by `modelProviders` (auth types are protocol, not credential-shape, generic) | not covered in the surveyed docs | first-class: OAuth is a provider *option*, not just a credential source (Grok/Qwen/MiniMax/Codex OAuth) |
| Unauthenticated local endpoint | empty `env_key` → no auth header | not documented | supported (local server base URLs) | `env` field omitted → no key required | `ACTUAL_BASE_URL=http://127.0.0.1:8080` with no key on loopback |

## 8. Known debt carried forward (named on purpose, not silently dropped)

- **`openai-responses` protocol (OpenAI's newer Responses API).** DSH lists it as a distinct protocol value from Chat Completions. Different streaming/tool shape again. Add as a third `Provider` implementation, or as a mode flag on `OpenAICompatibleProvider`, once something in this project's own usage actually needs the Responses API rather than Chat Completions — most self-hosted and third-party "OpenAI-compatible" endpoints (vLLM, Ollama, DeepSeek, Qwen, Kimi, MiniMax) speak Chat Completions, not Responses, so this is low urgency.
- **Native Gemini / Vertex AI protocol.** A real third wire shape (`generateContent`), not a catalog row. Deferred until a Gemini-family model is actually wanted; when it lands, it's a new `Provider` implementation the same size as this phase's `AnthropicMessagesProvider`, not a redesign.
- **Bedrock, Vertex, Azure, and OAuth-based (Codex-style) login.** Each needs a credential/auth-construction layer distinct from "read an API key from an env var" — SigV4 signing for Bedrock, ADC/service-account tokens for Vertex, an `api-version` query param plus Azure AD auth for Azure OpenAI, a full OAuth device/browser flow for a Codex-style login. None of these are `loom_provider` problems once built — per §2 finding 3, the underlying request/response bodies are still substantially OpenAI- or Anthropic-shaped, so the *parsing* code this phase and Phase 2 already wrote should be reusable. What's missing is entirely in a future `loom_app` credentials layer: where keys/tokens are stored, how they're refreshed, and how a `base_url` gets constructed from a region/project instead of typed in directly. Not started here — scoping it now, before `loom_app` exists, would mean guessing at an interface.
- **Per-vendor model capability metadata (context length, vision support, tool-call support).** OpenCode's catalog carries `capabilities`/`limit` per model; DSH's provider docs describe per-model input-modality declarations that get validated before a request is sent. `loom`'s catalog sketch in §4 doesn't have this yet — it's a `loom_app`-layer addition, not a `loom_provider` one, and it doesn't block anything in this phase.

## 9. Checklist

- [x] `loom_provider/anthropic_messages.py` — `AnthropicMessagesProvider`, same shape contract as `OpenAICompatibleProvider` (held `httpx.Client`, `close()`, context manager, private wire-translation methods, `StreamError` on every failure path, never a silent `return`)
- [x] `AnthropicMessagesProvider` produces the exact same `StreamEvent` union as `OpenAICompatibleProvider` for an equivalent scripted turn — write a test that runs both providers' `_handle_line`-equivalents against a hand-built "assistant says X then calls tool Y" fixture and asserts the resulting `StreamEvent` sequences are structurally equal
- [x] Neither new file imports `loom_core` or `loom_app`
- [x] `loom_app/catalog.py` (sketch in §4) — reads `providers.toml`, resolves env vars, constructs the right `Provider`; this is `loom_app`, so it's allowed to import `loom_provider`
- [x] `providers.toml` ships with all 15 rows from §6, including the local/no-auth endpoint and the `anthropic-messages` row — proves the catalog handles both protocols and the empty-`env_key` case at real scale, not just a toy example
- [x] Each of the 15 rows verified against a real account/endpoint at least once (a live smoke test, gated behind the `LOOM_TEST_API_KEY`-style skip pattern from Phase 2 §9) — a catalog row that was never actually dialed is a row that might have the wrong `base_url`
- [x] `uv run pytest tests/loom_provider -v` still passes, plus new tests for `AnthropicMessagesProvider`
- [x] `uv run mypy packages/loom_provider` passes with `strict = true`
- [x] You can explain, out loud: why 14 of the 15 phase-1 providers are zero new code, why Anthropic wasn't, and why rows 16–37 in §6 were surveyed but not shipped
- [x] `dev-notes/0004-provider-catalog.md` written (ADR template from Phase 0), recording the two-protocol-vs-many-vendor-names distinction, the first-phase-15 selection criteria, and the deferred items in §8

## 10. Sources

- [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) — [`docs/architecture.md`](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md), [`docs/user/guide/providers.md`](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/providers.md), [`AGENTS.md`](https://github.com/deepseek-ai/deepseek-harness/blob/master/AGENTS.md)
- [DeepSeek Harness — DeepWiki overview](https://deepwiki.com/deepseek-ai/deepseek-harness)
- [QwenLM/qwen-code — model-providers.md](https://github.com/QwenLM/qwen-code/blob/main/docs/users/configuration/model-providers.md), [auth docs](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/auth/)
- [Alibaba Cloud Model Studio — OpenAI compatibility](https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope)
- [OpenCode — Providers](https://opencode.ai/v2/docs/providers)
- [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) — [llms-full docs dump](https://hermes-agent.nousresearch.com/docs/assets/files/llms-full-60c3262cae937522e273d812af6e47e1.txt) (provider table in Quickstart), [`developer-guide/adding-providers.md`](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/adding-providers.md), [`developer-guide/provider-runtime.md`](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/provider-runtime.md), [`integrations/providers.md`](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/integrations/providers.md)
- Phase 2 doc (this project) — §11 for the original `loom_provider` config-dumb decision, §7 for the connection-lifecycle contract `AnthropicMessagesProvider` reuses.

---

Two protocols hand-built, one catalog file, 37 vendors surveyed across five independent harnesses, and 15 shipped in this phase — 14 of them a five-line config addition against code that already exists. The one genuine new wire format, Anthropic's, gets the same treatment Phase 2 already gave OpenAI's: one class, one set of private translation methods, tested directly, never touching `loom_core`. Rows 16–37 aren't forgotten; they're named, reasoned about individually in §6, and re-homed as explicit debt in §8 — the same discipline Phase 1 and Phase 2 already held themselves to.