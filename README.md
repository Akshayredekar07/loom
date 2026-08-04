![loom-agent-logo](resources/loom-agent-dark.svg)

<p align="center">
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/python-3.12%2B-blue" alt="Python 3.12+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-informational" alt="License"></a>
  <a href="dev-notes/00-project-plan.md"><img src="https://img.shields.io/badge/status-learning%20project%20%7C%20WIP-yellow" alt="Status"></a>
</p>

<p align="center">
  <a href="#what-is-loom">What is Loom?</a> ·
  <a href="#quick-start">Quick Start</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#repository-layout">Repository Layout</a> ·
  <a href="dev-notes/">Dev Notes</a> ·
  <a href="#references">References</a>
</p>


## **What is Loom?**

Loom is a terminal coding agent, built from the ground up in plain Python — no
LangChain, no CrewAI, no AutoGen, no agent framework of any kind. It exists to
answer one question by actually building the answer: **what is a coding agent
made of, underneath the framework?**

Every real agent worth learning from — [Claude Code](#references),
[OpenAI Codex](#references), [Grok Build](#references), and Hugging Face's
[Tau](#references) — is the same three ideas wearing different clothes:

1. **Messages are the state.** The transcript is an ordered, append-only list. Nothing lives outside it that matters for replay.
2. **The loop is provider-agnostic and UI-agnostic.** It only knows about messages, tools, and events — never a renderer, never a vendor SDK.
3. **Progress is an event stream, not a return value.** The loop emits typed events so any number of frontends can render the same run differently.

Loom builds those three ideas first, by hand, then layers on everything else
— tools, sessions, skills, a TUI — one deliberate phase at a time. This is
**not** a race to feature parity with a 500K-line production agent. It's a
minimal, readable version built to teach you why each piece exists.


## **Quick Start**

**Requirements:** Python 3.12+, [uv](https://docs.astral.sh/uv/)

```bash
# clone the repo
git clone https://github.com/Akshayredekar07/loom.git
cd loom

# install the workspace
uv sync --dev

# once the CLI stub exists (Phase 0)
uv run loom --version
```

Loom isn't installable from PyPI yet — it's built phase by phase, in order,
by you. Start with [`dev-notes/00-project-plan.md`](dev-notes/00-project-plan.md).



## **Architecture**

Three packages, one direction of dependency — enforced, not just documented:

```text
loom_app  →  loom_core  →  loom_provider
(CLI/TUI)    (portable      (vendor-specific
              agent brain)   streaming, normalized)
```

```text
┌─────────────┐     ┌──────────────┐     ┌────────────────┐
│  loom_app   │ ──▶│  loom_core   │ ──▶ │  loom_provider │
│  CLI, TUI,  │     │  messages,   │     │  OpenAI/       │
│  sessions,  │     │  tools,      │     │  Anthropic     │
│  skills     │     │  events,     │     │  adapters,     │
│             │     │  agent loop  │     │  StreamEvent   │
└─────────────┘     └──────────────┘     └────────────────┘
```

`loom_core` never imports `loom_app` — that's a packaging fact enforced by
[import-linter](https://import-linter.readthedocs.io), not a convention
anyone has to remember. Full rationale in
[`dev-notes/01-phase-0-foundation.md`](dev-notes/01-phase-0-foundation.md).


## **Repository Layout**

| Path | Contents |
|---|---|
| `packages/loom_provider/` | Vendor-specific streaming (OpenAI/Anthropic), normalized to one internal `StreamEvent` type |
| `packages/loom_core/` | The portable brain — messages, tools, events, the agent loop, the harness. No I/O, no UI. |
| `packages/loom_app/` | The actual application — CLI, TUI, built-in tools, sessions, skills |
| `dev-notes/` | Phase-by-phase design docs, written before the matching code |
| `dev-notes/adr/` | Architecture Decision Records — one short file per non-obvious design choice |
| `tests/` | Mirrors the package layout, one test dir per package |



## **How to Use This Repo**

This is not a "clone and run" project — it's a "clone and *build*" project.

1. Read a phase's `dev-notes/` doc in full, including the "why" sections.
2. Implement it yourself. Type it; don't paste it.
3. Run that phase's checklist. All boxes green before moving on.
4. Write a short entry in `dev-notes/` — what you built, what you decided
   against, and why. That's what makes the repo legible to future-you.


## **References**

Loom's design is adapted from public architecture, not copied from private
source. Primary references, worth reading directly:

- **Tau** (Hugging Face) — the closest template for this project's phase
  structure and package split. [`huggingface/tau`](https://github.com/huggingface/tau) · [docs](https://twotimespi.dev/)
- **Claude Code** (Anthropic) — the production end of the spectrum; async-generator
  loop, uniform tool interface. [Agent SDK docs](https://code.claude.com/docs/en/agent-sdk/agent-loop)
- **OpenAI Codex** — Submission Queue / Event Queue pattern, one core crate
  behind multiple frontends over a JSON-RPC protocol boundary. [`openai/codex`](https://github.com/openai/codex)
- **Grok Build** (xAI) — independent convergent design: agent loop / tools /
  TUI / extensions as four crates, MCP + ACP for external integration. [`xai-org/grok-build`](https://github.com/xai-org/grok-build)



## **Contributing**

This is a personal learning project — it isn't accepting external
contributions right now. Fork it and build your own version; that's the
point.

## **License**

[MIT](LICENSE) — or swap for [Apache 2.0](LICENSE) if you'd rather match
the license most of the reference projects above use. Pick one before your
first commit and add the matching `LICENSE` file; the badge above assumes MIT.