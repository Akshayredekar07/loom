# References

Loom's design is adapted from public architecture, not copied from private
source

This file exists so the README can stay focused on the project itself. Come
here when you want to understand *why* a phase is shaped the way it is, or
to go read the original source material directly.

---

## Primary references

### Tau (Hugging Face)

The closest template for this project's phase structure and three-package
split (`tau_ai → tau_agent → tau_coding`). Their own build roadmap — a real,
phase-by-phase build log — is the backbone this project's roadmap adapts.

- Repo: [`huggingface/tau`](https://github.com/huggingface/tau)
- Docs: [twotimespi.dev](https://twotimespi.dev/)
  - [Architecture overview](https://twotimespi.dev/internals/architecture/)
  - [The agent loop & events](https://twotimespi.dev/internals/agent-loop/)
  - [Roadmap](https://twotimespi.dev/roadmap/) (their GitHub issue #1 is the
    original source for the phase list this project's roadmap is adapted from)

### Claude Code (Anthropic)

The production end of the spectrum. Independent community analyses describe
a `QueryEngine` sitting between the UI and the model API, running the loop
as an async generator that yields events rather than returning a final
string — the mechanism behind why the TUI can render live progress instead
of a spinner.

- Anthropic's public Agent SDK loop docs: [code.claude.com/docs/en/agent-sdk/agent-loop](https://code.claude.com/docs/en/agent-sdk/agent-loop)
- Community architecture write-ups (unofficial, useful as secondary reading):
  - [claude-code-from-source.com](https://claude-code-from-source.com/)
  - [Inside Claude Code's architecture](https://zainhas.github.io/blog/2026/inside-claude-code-architecture/)

### OpenAI Codex

Confirms the same shape from a different implementation angle (Rust, not
Python). Notably uses a **Submission Queue / Event Queue** pattern instead of
a single-consumer generator — a client pushes `Op`s into a queue, the session
engine streams `Event`s back, which lets multiple frontends attach to one
live session concurrently. Worth revisiting once Loom's own loop (Phase 3)
works, specifically for this pattern and for how it sandboxes the `bash`
tool.

- Repo: [`openai/codex`](https://github.com/openai/codex)

### Grok Build (xAI)

An independently-built, convergent design — same agent-loop / tools / TUI /
extensions split, implemented as four Rust crates (`xai-grok-shell`,
`xai-grok-tools`, `xai-grok-pager`, plus extensions). Speaks MCP for external
tools and ACP (Agent Client Protocol) for editor embedding rather than
inventing a proprietary protocol.

- Repo: [`xai-org/grok-build`](https://github.com/xai-org/grok-build)

---

## Secondary / not yet analyzed in depth

Worth a look later, once the core loop is working, but not a source for any
current design decision in this project:

- [`codeaashu/claude-code`](https://github.com/codeaashu/claude-code) — community reimplementation
- [OpenCode](https://opencode.ai/) — referenced indirectly (Grok Build's
  `xai-grok-tools` credits ported tool implementations from it)

---

## What got adopted, and from where

A running log — updated as design decisions get made — of which phase
borrowed which idea from which reference, so a design choice can always be
traced back to its source.

| Decision | Adopted from | Where it lives |
|---|---|---|
| Three-package layered split, one-way dependency | Tau (`tau_ai → tau_agent → tau_coding`) | `dev-notes/01-phase-0-foundation.md` §4 |
| `uv` + `ruff` as the toolchain | Tau's own dev workflow | `dev-notes/01-phase-0-foundation.md` §6–7 |
| Content blocks instead of a plain string on `Message` | Tau's `AssistantMessage` ordered content blocks | `dev-notes/02-phase-1-core-types.md` §3 |
| Nested streaming sub-events under `MessageUpdateEvent` | Tau's `assistant_message_event` taxonomy | `dev-notes/02-phase-1-core-types.md` §7 |
| "Final message authoritative, deltas cosmetic" | Explicit design rule stated in Tau's own docs | `dev-notes/02-phase-1-core-types.md` §6 |
| `StopReason` enum + dedicated `AgentErrorEvent` | A second independently-drafted reference set (see `dev-notes/02-phase-1-core-types.md` §11) | `dev-notes/02-phase-1-core-types.md` §7 |
| Provider-level `StreamEvent`, distinct from `AgentEvent` | Same second reference set; flagged as owed to Phase 2 | Not yet built — Phase 2 |
| SQ/EQ (queue-based) event delivery as an alternative worth knowing | Codex's core architecture | Noted for Phase 3, not adopted yet |

---

## Steal-like-an-artist rule

Copy **shapes and boundaries**. Never copy proprietary prompts, private
APIs, or large generated code dumps. Every line in this repo is typed by
hand, phase by phase, against a written design doc — that's the actual
learning, not the resemblance to any one of the projects above.