# **Build Your Own Coding Agent — From Scratch, No Frameworks**

> This is the master plan file. Everything else (phase docs, ADRs, code) hangs off this one.
> We are not copying anyone's code. We're stealing the *shape* — the architecture, the boundaries,
> the reasons a design won — and rebuilding it ourselves, one phase at a time, in plain Python.
> Every phase gets its own file. You don't open phase 2 until phase 1's checklist is green.

---

## **Table of Contents**

1. [What we're building](#1-what-were-building)
2. [Research — what the real agents look like under the hood](#2-research--what-the-real-agents-look-like-under-the-hood)
3. [Design principles we're stealing](#3-design-principles-were-stealing)
4. [Project name and repo layout](#4-project-name-and-repo-layout)
5. [The phase plan](#5-the-phase-plan)
6. [Toolchain preview (detail lives in Phase 0 doc)](#6-toolchain-preview-detail-lives-in-phase-0-doc)
7. [How to use these notes](#7-how-to-use-these-notes)
8. [Sources](#8-sources)

---

## **1. What we're building**

A terminal coding agent, built in layers, from raw Python — no LangChain, no
CrewAI, no agent framework of any kind. By the end you'll have something that:

- talks to a real LLM provider (OpenAI/Anthropic-style) and streams tokens back,
- can call tools (`read`, `write`, `edit`, `bash`) and feed results back to the model,
- runs a proper **agent loop** (prompt → stream → tool calls → tool results → repeat),
- persists sessions to disk and can resume them,
- has both a non-interactive "print mode" CLI and, later, an interactive TUI,
- is organized so the "brain" (agent loop) never imports the "face" (CLI/TUI).

That last point is the whole game. Every real agent we researched — Claude Code,
Codex, Tau — draws this same line. We're going to draw it too, on purpose, from
day one, instead of discovering we need it after everything is tangled together.

We are **not** trying to out-build Claude Code (512K LOC, custom Ink/React
terminal renderer, 50+ tools, sub-agent orchestration). We're building the
*minimal, readable version* that teaches you why each of those pieces exists —
the same goal Hugging Face's Tau project set for itself.

---

## **2. Research — what the real agents look like under the hood**

Quick findings from digging into each project you listed, so the plan below
isn't guesswork.

### **`huggingface/tau`** — the direct template for this plan

Tau is explicitly built as a teaching project: "a minimalist agent that teaches
you to create coding agents." It's a Python port of the architectural ideas
behind `pi.dev`. It ships as three packages with a **strict one-way dependency
direction**:

```text
tau_coding  →  tau_agent  →  tau_ai
```

- **`tau_ai`** — provider-specific streaming (OpenAI, Anthropic, …) translated
  into one provider-neutral event stream. Nothing above it cares which vendor
  is in use.
- **`tau_agent`** — the portable brain: messages, tools, events, the agent
  loop, the harness, session primitives. **Must not** import Textual, Rich,
  CLI code, or config-path logic. This is the reusable core.
- **`tau_coding`** — the actual coding-agent *application*: CLI, built-in
  tools, project instructions (`AGENTS.md`), skills/prompts, on-disk sessions,
  provider config, and the Textual TUI.

Their own summary of the idea, which we're borrowing wholesale:

```text
AgentHarness  = reusable brain
CodingSession = coding-agent environment
TUI           = one possible frontend
```

Tau's own build roadmap (their GitHub issue #1 — this is the "Phase plan" you
pasted me) is a real, working, phase-by-phase build log of exactly this kind of
project, and it's the backbone of the plan below. We're not copying it
verbatim; we're adapting it so you understand *why* each phase exists, not just
*that* it exists.

### **Claude Code** (Anthropic) — the production end of the spectrum

Independent source analyses (community write-ups, not Anthropic's own docs)
describe a layered pipeline: entry points → bootstrap (config/auth/telemetry) →
setup (hooks/plugins/watchers) → a custom terminal UI → a central
**QueryEngine** → tools/services/state. The core insight they all converge on:

> The QueryEngine sits between the UI and the model API, running the loop
> *"send message → get response → execute tools → send results → repeat."*
> Tools are a uniform interface (schema + permission logic + execution), so
> adding a capability never touches the loop or the UI.

Two implementation details worth stealing even at small scale:
- the loop is written as an **async generator that yields events**, not a
  function that returns a final string — this is what lets a UI render
  progress instead of a spinner;
- messages are the **entire state** — nothing is tracked out-of-band, so
  persistence, replay, and context-trimming are all just "operate on the
  message list."

Anthropic's own public Agent SDK docs describe the same loop from the outside:
receive prompt → attach system prompt/tools/history → stream → tool calls →
tool results appended → repeat until no more tool calls.

### **OpenAI Codex CLI**

Same family of design (Rust/TS core, tool-call loop, provider abstraction,
sandboxed shell execution as a first-class tool). We're treating it here as
confirmation, not a second architecture to copy — the shape rhymes with Tau and
Claude Code closely enough that re-deriving it from Codex specifically wouldn't
teach you anything new at this stage. Worth a skim later, once your own loop
works, specifically for how it sandboxes `bash`/shell tool execution.

### **`xai-org/grok-build`, `codeaashu/claude-code`, opencode**

Community/experimental reimplementations. Useful as secondary references once
your own core loop is working — good for "how did someone else solve the same
problem I just solved" comparisons — but we're not basing phase design on them
directly; Tau + Claude Code's public architecture write-ups give us enough
signal, and are the two most documented, most teachable references available.

### **The pattern, stated once**

Every single one of these systems is the same three ideas wearing different
clothes:

1. **Messages are the state.** The transcript is an ordered, append-only list.
   Nothing lives outside it that matters for replay.
2. **The loop is provider-agnostic and UI-agnostic.** It only knows about
   messages, tools, and events. It never imports a renderer.
3. **Progress is an event stream, not a return value.** The loop `yield`s
   (or, in Python terms, is an async generator / callback stream) so any
   number of frontends can render the same run differently.

That's the whole architecture. Everything else — skills, sessions, TUIs,
slash commands, compaction — is application-layer stuff bolted onto those
three ideas. We build the three ideas first, and bolt on the rest deliberately,
phase by phase.

---

## **3. Design principles we're stealing**

Lifted and adapted from Tau's own internals docs and from what the Claude Code
analyses converge on independently:

- **One job per layer.** A package/module answers one question. If you can't
  say what a file's one job is, it's in the wrong place.
- **Dependency direction is a hard rule, not a convention.** `app → core →
  provider`. The core never imports the app. Enforce this with linting
  (import-graph checks), not just discipline.
- **Events, not callbacks buried in control flow.** The loop communicates by
  emitting typed events. A renderer's whole job becomes: *consume the stream,
  draw what you see.*
- **The final message is authoritative; streaming deltas are cosmetic.**
  Nested `text_delta`/`toolcall_delta` events exist for responsive rendering
  only. What gets persisted and replayed is the finalized structured message.
- **Small layers beat magic.** No hidden reflection, no dynamic tool
  discovery via decorators-that-do-too-much. If you can't read a 200-line
  file top to bottom and understand it, it's not small enough yet.
- **Provider-neutral types at the boundary.** OpenAI's and Anthropic's wire
  formats never leak past the provider-adapter layer. The agent loop only
  ever sees *our* `Message`/`ToolCall`/`AgentEvent` types.

We'll restate the relevant ones at the top of each phase doc, because they're
easy to say once and forget by phase 5.

---

## **4. Project name and repo layout**

Pick a real name before you start — placeholder names make commit history
annoying later. These notes use **`loom`** as the placeholder project name
(swap it for whatever you like — sed it out later, it's a global find/replace).

Mirroring Tau's three-package split, generalized so it's not Tau-branded:

```text
loom/
├── packages/
│   ├── loom_provider/     # talking to models — provider-neutral event stream
│   │                      #   (Phase 2)
│   ├── loom_core/         # the portable brain: messages, tools, events,
│   │                      #   the agent loop, the harness (Phases 1, 3, 4)
│   └── loom_app/          # the CLI/TUI application: built-in tools, sessions,
│                          #   skills, slash commands (Phase 5 onward)
├── dev-notes/             # phase-by-phase build journal + ADRs (Phase 0)
├── tests/
├── pyproject.toml
├── README.md
└── CONTRIBUTING.md
```

Dependency direction, enforced later with an import-linter rule:

```text
loom_app  →  loom_core  →  loom_provider
```

`loom_core` is not allowed to import anything from `loom_app` — no CLI parsing,
no Rich, no Textual, no filesystem-path config. That's the one rule that keeps
this whole project honest as it grows.

---

## **5. The phase plan**

Adapted from Tau's own roadmap (their GitHub issue #1), renumbered and
reworded around our package names. Each phase becomes its own `dev-notes/PHASE_N_*.md`
file, written *before* you write the code for that phase — design first, code
second, same as the real project did it.

```text
0.  Project foundation and design docs.
1.  Core message, tool, and event types.
2.  Provider interface — fake provider + one real provider.
3.  Pure agent loop (no persistence, no CLI, no I/O beyond the provider).
4.  Reusable AgentHarness (transcript owner, prompt()/continue_(), cancellation).
5.  Built-in coding tools: read, write, edit, bash.
6.  Non-interactive print-mode CLI.
7.  Append-only session persistence (JSONL).
8.  Coding session wrapper — CodingSession wraps the harness + persistence.
9.  Skills and prompt templates (markdown-based).
10. System prompt assembly (tool docs + skills index + project context).
11. Print and event rendering modes (final-text / JSON-stream / transcript).
12. Interactive TUI behind an adapter boundary.
13. App home directory, resource paths, project-level instructions.
14. Session manager and resume.
15. Slash command registry.
16. Robust skills/prompt discovery (user-level + project-level, precedence).
17. TUI slash-command autocomplete.
18. Provider configuration and multi-provider setup.
19. Project context discovery and reload (AGENTS.md-style files).
20. Packaging and installation polish (uv tool / pipx, first-run docs).
21. Context accounting and live usage display.
22. Thinking-mode controls (if your provider supports extended thinking).
23. Compaction and context management.
24. Extensions (local plugin loading, event subscriptions).
25. Polish pass — richer rendering, diff viewer, theming.
```

Notes on the renumbering vs. the source roadmap you pasted:
- Their phases `20.1`–`20.4` became our `21`–`23` (flat numbers are easier to
  file as separate docs).
- Their `21` (Extensions, marked "Implemented" in your notes) and `22`
  (Compaction) are swapped in our version — build compaction before
  extensions. Extensions are more fun to design *against* a stable core, and
  compaction touches the harness/session boundary, which you want settled
  first.
- We are giving you **Phase 0 and Phase 1 now**, as separate files, per your
  request. Do not ask for Phase 2 until Phase 1's checklist (in that file) is
  fully green — that's the discipline that makes "learning by building" work
  instead of "pasting code you don't understand."

---

## **6. Toolchain preview (detail lives in Phase 0 doc)**

Modern, no-framework-for-the-agent-itself, but yes to good dev tooling:

| Concern | Tool | Why |
|---|---|---|
| Package/dependency manager | **uv** | what Tau itself uses; single fast tool replaces pip+venv+pip-tools |
| Linting | **ruff** | one binary replaces flake8+isort+a dozen plugins |
| Formatting | **ruff format** | same tool, no separate `black` needed |
| Type checking | **mypy** (strict) | catches boundary mistakes between packages before runtime |
| Testing | **pytest** | standard, and Tau uses it too |
| Import-boundary enforcement | **import-linter** | turns "core never imports app" from a rule you remember into a rule CI checks |

Full install commands and config files are in `01-PHASE-0-foundation.md`.

---

## **7. How to use these notes**

1. Read a phase doc fully before writing code for it — including the "why"
   sections, not just the code blocks.
2. Implement the phase yourself. Don't paste; type it. If something in a code
   block doesn't make sense, that's the thing to slow down on, not skip.
3. Run the phase's checklist. All boxes green before moving on.
4. Write a short entry in `dev-notes/` for what you built and *why you chose
   what you chose* — even a few sentences. This is what makes the project
   readable to future-you, exactly like Tau's own `dev-notes/` build journal.
5. Come back for the next phase file.

---

## **8. Sources**

- Tau repository — <https://github.com/huggingface/tau>
- Tau roadmap (the phase list this plan adapts) — <https://github.com/huggingface/tau/issues/1>
- Tau docs site — <https://twotimespi.dev/>
  - Architecture overview — <https://twotimespi.dev/internals/architecture/>
  - The agent loop & events — <https://twotimespi.dev/internals/agent-loop/>
  - Design principles — <https://twotimespi.dev/internals/design-principles/>
  - Extensions/event payloads — <https://twotimespi.dev/guides/extensions/>
- Claude Code architecture analyses (community, unofficial):
  - <https://zainhas.github.io/blog/2026/inside-claude-code-architecture/>
  - <https://claude-code-from-source.com/>
  - <https://dev.to/brooks_wilson_36fbefbbae4/claude-code-architecture-explained-agent-loop-tool-system-and-permission-model-rust-rewrite-41b2>
- Anthropic's public Agent SDK loop docs — <https://code.claude.com/docs/en/agent-sdk/agent-loop>
- `huggingface/smolagents` (for a contrasting, code-executing agent style) — <https://github.com/huggingface/smolagents>

Not independently re-analyzed for this plan (secondary references, revisit
after your own loop works): `openai/codex`, `xai-org/grok-build`,
`codeaashu/claude-code`, opencode.

---

## **Where to next?**

Two files are ready:

- ✅ `01-PHASE-0-foundation.md` — repo scaffold, uv, ruff, mypy, pytest,
  import-linter, ADR template, `loom --version`.
- ✅ `02-PHASE-1-core-types.md` — `Message`, content blocks, `ToolCall`/
  `ToolResult`, and the full `AgentEvent` hierarchy, in plain dataclasses.

Finish both, get their checklists green, then say the word for Phase 2
(provider interface). 🚀