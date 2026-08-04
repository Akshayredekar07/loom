# **Phase 0 — Project Foundation and Design Docs**

> Before a single `Message` type exists, we set up the ground it stands on:
> a real package layout, a modern package manager, linters that actually catch mistakes,
> and a place to write down *why* we made each decision. Boring phase. Non-negotiable phase.
> Every example below is runnable. Copy, paste, run.

---

## **Table of Contents**

1. [Goal of this phase](#1-goal-of-this-phase)
2. [Why a "Phase 0" at all](#2-why-a-phase-0-at-all)
3. [Setup — install uv](#3-setup--install-uv)
4. [Project scaffold](#4-project-scaffold)
5. [`pyproject.toml` — the real one](#5-pyprojecttoml--the-real-one)
6. [Ruff — lint + format in one tool](#6-ruff--lint--format-in-one-tool)
7. [mypy — strict from day one](#7-mypy--strict-from-day-one)
8. [pytest — smallest possible test](#8-pytest--smallest-possible-test)
9. [import-linter — enforcing the dependency direction](#9-import-linter--enforcing-the-dependency-direction)
10. [The `loom --version` CLI stub](#10-the-loom---version-cli-stub)
11. [`dev-notes/` and the ADR habit](#11-dev-notes-and-the-adr-habit)
12. [Pre-commit (optional but recommended)](#12-pre-commit-optional-but-recommended)
13. [Phase 0 checklist](#13-phase-0-checklist)
14. [Why it's built this way](#14-why-its-built-this-way)

---

## **1. Goal of this phase**

By the end of this phase you can run:

```bash
uv run loom --version
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run lint-imports
```

...and every single one of those exits `0`, on an otherwise empty project.
Nothing here writes agent code. That's Phase 1.

---

## **2. Why a "Phase 0" at all**

It's tempting to skip straight to "make the model call a tool." Every real
project we researched didn't skip this step, and for the same reasons:

- **Tau** starts its own roadmap with exactly this: "package scaffold, docs and
  ADRs, test/lint/format/typecheck setup, basic `tau --version`" — *before*
  any agent logic exists.
- **Claude Code**'s architecture write-ups describe a `Bootstrap` layer
  (config, telemetry, auth, networking) that exists purely so the rest of the
  system doesn't have to think about setup — it's a foundation layer, done
  once, relied on by everything above it.

If you skip this, you end up retrofitting a package boundary onto 2,000 lines
of tangled agent code around Phase 8, which is exactly the kind of pain this
plan exists to avoid.

---

## **3. Setup — install uv**

`uv` is the modern Python package/venv/tool manager — it replaces
`pip` + `venv` + `pip-tools` + `pipx` with one static binary. It's also what
Tau itself uses (`uv sync --dev`, `uv run pytest`, ...), so we're matching a
project we already know does this well.

### **Install**

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### **Verify**

```bash
uv --version
```

### **Why uv and not pip + venv**

- one binary, no "which python am I in" confusion
- lockfile (`uv.lock`) by default — reproducible installs
- `uv run <cmd>` runs inside the project's venv without you ever typing
  `source .venv/bin/activate`
- `uv tool install` is how you'll eventually ship `loom` as an installable CLI
  (this is literally how `tau-ai` is distributed on PyPI)

---

## **4. Project scaffold**

```bash
mkdir loom && cd loom
uv init --package --python 3.12
```

This gives you a minimal `src/`-layout package. We're going to reshape it into
the three-package split from the plan doc. Do this by hand so you understand
every directory that exists:

```bash
mkdir -p packages/loom_provider/src/loom_provider
mkdir -p packages/loom_core/src/loom_core
mkdir -p packages/loom_app/src/loom_app
mkdir -p dev-notes tests/loom_core tests/loom_provider tests/loom_app
touch packages/loom_provider/src/loom_provider/__init__.py
touch packages/loom_core/src/loom_core/__init__.py
touch packages/loom_app/src/loom_app/__init__.py
```

### **Why three separate packages instead of one package with three folders**

You *can* do this with one package and three top-level modules
(`loom.provider`, `loom.core`, `loom.app`) — Python won't stop you from
importing across them either way. Three **installable** packages (each with
its own `pyproject.toml` as a workspace member) buys you one real thing:
`loom_core` literally cannot `import loom_app` unless it's declared as a
dependency. The boundary becomes a packaging fact, not a promise. If that
feels like overkill for a learning project, the single-package-three-modules
version plus the import-linter rule in [§9](#9-import-linter--enforcing-the-dependency-direction)
gets you 90% of the benefit for less ceremony — pick whichever keeps you
moving. These notes assume the workspace version because it mirrors Tau's
actual layout most closely.

### **Resulting shape**

```text
loom/
├── packages/
│   ├── loom_provider/
│   │   ├── pyproject.toml
│   │   └── src/loom_provider/
│   ├── loom_core/
│   │   ├── pyproject.toml
│   │   └── src/loom_core/
│   └── loom_app/
│       ├── pyproject.toml
│       └── src/loom_app/
├── dev-notes/
├── tests/
├── pyproject.toml         # workspace root
├── README.md
└── CONTRIBUTING.md
```

---

## **5. `pyproject.toml` — the real one**

### **Root `pyproject.toml` (workspace)**

```toml
[project]
name = "loom-workspace"
version = "0.0.0"
requires-python = ">=3.12"

[tool.uv.workspace]
members = ["packages/*"]

[tool.uv.sources]
loom_provider = { workspace = true }
loom_core = { workspace = true }
loom_app = { workspace = true }

[dependency-groups]
dev = [
    "pytest>=8.0",
    "ruff>=0.6",
    "mypy>=1.11",
    "import-linter>=2.0",
]
```

### **`packages/loom_core/pyproject.toml`**

```toml
[project]
name = "loom_core"
version = "0.0.1"
requires-python = ">=3.12"
dependencies = ["loom_provider"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

`loom_core` depends on `loom_provider` (it needs to know the `Provider`
interface) but never on `loom_app`. That's the rule from the plan doc, now
written into a manifest.

### **`packages/loom_app/pyproject.toml`**

```toml
[project]
name = "loom_app"
version = "0.0.1"
requires-python = ">=3.12"
dependencies = ["loom_core", "loom_provider"]

[project.scripts]
loom = "loom_app.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

The `[project.scripts]` entry is what makes `uv run loom` resolve to a real
function — same mechanism that turns `tau-ai` into a `tau` command on PyPI.

### **Install everything**

```bash
uv sync --dev
```

---

## **6. Ruff — lint + format in one tool**

Root `pyproject.toml` additions:

```toml
[tool.ruff]
line-length = 100
target-version = "py312"
src = ["packages/loom_provider/src", "packages/loom_core/src", "packages/loom_app/src"]

[tool.ruff.lint]
select = [
    "E", "F", "I",      # pyflakes/pycodestyle/isort
    "UP",                # pyupgrade — flags old-style syntax
    "B",                 # bugbear — catches common footguns
    "SIM",               # simplify
    "RUF",                # ruff-native rules
]

[tool.ruff.lint.isort]
known-first-party = ["loom_provider", "loom_core", "loom_app"]
```

### **Run it**

```bash
uv run ruff check .
uv run ruff format .
```

### **Why ruff instead of flake8 + isort + black**

One process, one config block, one dependency to update. Tau's own dev
workflow (`uv run ruff check .`, `uv run ruff format --check .`) is the same
pattern — we're matching a decision that's already been made and validated by
a real project, not guessing.

---

## **7. mypy — strict from day one**

```toml
[tool.mypy]
python_version = "3.12"
strict = true
mypy_path = [
    "packages/loom_provider/src",
    "packages/loom_core/src",
    "packages/loom_app/src",
]
namespace_packages = true
explicit_package_bases = true
```

### **Run it**

```bash
uv run mypy packages
```

### **Why strict, and why now**

The entire value of the `loom_core → loom_provider` boundary is that
`loom_core` only knows about *our* types (`Message`, `ToolCall`, `AgentEvent`)
— never a raw `dict` shaped like an OpenAI response. Strict mypy is what
catches it the moment someone (you, in six weeks, tired) passes a loose
`dict[str, Any]` across that boundary instead of a typed object. Turning this
on later, after the boundary is already full of `Any`, is much more painful
than starting strict.

---

## **8. pytest — smallest possible test**

`packages/loom_core/pyproject.toml` doesn't need a pytest config; the root
does:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = [
    "packages/loom_provider/src",
    "packages/loom_core/src",
    "packages/loom_app/src",
]
```

### **`tests/loom_core/test_smoke.py`**

```python
def test_smoke():
    """If this fails, the test runner itself is misconfigured."""
    assert 1 + 1 == 2
```

### **Run it**

```bash
uv run pytest
```

Done. **A working, if empty, test suite.**

---

## **9. import-linter — enforcing the dependency direction**

This is the tool that turns "core never imports app" from a rule you have to
remember into a rule CI checks for you.

```toml
[tool.importlinter]
root_packages = ["loom_provider", "loom_core", "loom_app"]

[[tool.importlinter.contracts]]
name = "Layered architecture"
type = "layers"
layers = [
    "loom_app",
    "loom_core",
    "loom_provider",
]
```

A `layers` contract says: layers listed higher may import from layers listed
lower, never the reverse. If you accidentally write
`from loom_app.cli import render` inside `loom_core`, this fails loudly.

### **Run it**

```bash
uv run lint-imports
```

### **Why bother with a tool for this**

Because the whole reason Tau, Claude Code, and every other agent we looked at
is *readable* is that this exact rule holds throughout the codebase. It's easy
to hold for the first 200 lines. It is not easy to hold at 5,000 lines without
something automated checking it on every commit.

---

## **10. The `loom --version` CLI stub**

We use the standard library's `argparse` here, deliberately — no Typer, no
Click, nothing but core Python, per the "learn it from scratch" goal. You can
swap in Typer/Click later (Phase 6+) once you understand what a CLI framework
is actually saving you from writing by hand.

### **`packages/loom_app/src/loom_app/cli.py`**

```python
from __future__ import annotations

import argparse
import sys

__version__ = "0.0.1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="loom", description="A coding agent, built from scratch.")
    parser.add_argument(
        "--version",
        action="version",
        version=f"loom {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    # Nothing else exists yet — Phase 6 adds the real print-mode entry point.
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### **Run it**

```bash
uv run loom --version
# loom 0.0.1
```

### **Why it works**

- `argparse.ArgumentParser(..., action="version")` is stdlib-only and handles
  `--version`/`--help` conventions for free.
- `main(argv: list[str] | None = None)` takes an optional argv so tests can
  call `main(["--version"])` without touching `sys.argv` — a pattern you'll
  reuse for every CLI command from here on.
- Returning an `int` (not calling `sys.exit` inside `main`) keeps `main`
  testable; only the `if __name__ == "__main__"` guard touches `sys.exit`.

### **Test it**

```python
# tests/loom_app/test_cli.py
import pytest

from loom_app.cli import main


def test_version_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "loom" in capsys.readouterr().out
```

---

## **11. `dev-notes/` and the ADR habit**

Tau keeps its "phase-by-phase build journals, design docs, and ADRs" in a
`dev-notes/` folder in the repo (not on the public docs site) — that's exactly
the habit we're copying. Every phase gets a short write-up: what you built,
what you decided against, and why.

### **`dev-notes/0000-adr-template.md`**

```markdown
# ADR NNNN: <short decision title>

- Status: proposed | accepted | superseded
- Phase: <phase number>
- Date: YYYY-MM-DD

## Context
What problem forced a decision here?

## Decision
What did we choose?

## Alternatives considered
What else did we look at, and why didn't we pick it?

## Consequences
What does this make easier? What does it make harder later?
```

### **`dev-notes/0001-package-split.md`** (your first real ADR)

Write this one now, using the template above, covering the
three-package-vs-one-package-three-modules choice from §4. Do it before
moving to Phase 1 — it's a five-minute habit that pays off the first time you
forget why you made a call.

---

## **12. Pre-commit (optional but recommended)**

```bash
uv add --dev pre-commit
```

### **`.pre-commit-config.yaml`**

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.9
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: local
    hooks:
      - id: mypy
        name: mypy
        entry: uv run mypy packages
        language: system
        pass_filenames: false
      - id: import-linter
        name: import-linter
        entry: uv run lint-imports
        language: system
        pass_filenames: false
```

```bash
uv run pre-commit install
```

Now every commit runs lint, format-check, type-check, and the layering
contract automatically. Optional, but it's the difference between "the rules
exist" and "the rules are enforced."

---

## **13. Phase 0 checklist**

- [ ] `uv --version` works
- [ ] Three workspace packages exist: `loom_provider`, `loom_core`, `loom_app`
- [ ] `uv sync --dev` succeeds
- [ ] `uv run pytest` passes (smoke test + CLI test)
- [ ] `uv run ruff check .` passes
- [ ] `uv run ruff format --check .` passes
- [ ] `uv run mypy packages` passes with `strict = true`
- [ ] `uv run lint-imports` passes with the layered contract in place
- [ ] `uv run loom --version` prints a version and exits `0`
- [ ] `dev-notes/0000-adr-template.md` and `dev-notes/0001-package-split.md` exist
- [ ] (optional) `pre-commit install` run once

All green? Phase 0 is done.

---

## **14. Why it's built this way**

Every choice in this file traces back to one of the two references:

| Choice | Where it comes from |
|---|---|
| `uv` as the package manager | Tau's own `uv sync --dev` / `uv run` workflow |
| `ruff` for lint + format | Tau's own `uv run ruff check .` / `ruff format --check .` |
| `mypy --strict` | not explicitly Tau's choice, but required to make the "provider-neutral types at the boundary" principle enforceable rather than aspirational |
| Three-package workspace with a layers contract | Tau's `tau_ai → tau_agent → tau_coding` one-way dependency, made structurally impossible to violate |
| stdlib `argparse` for the version stub | the "core language, no frameworks" constraint you set — Tau itself uses Typer, but that's a Phase-6-and-later decision, not a Phase-0 one |
| `dev-notes/` + ADRs | Tau's own build-journal habit, referenced directly on their public docs site |

---

## **Where to next?**

- ✅ Phase 0 gives you a repo that lints, type-checks, tests, and enforces its
  own architecture.
- ➡️ **`02-PHASE-1-core-types.md`** — the actual `Message`, `ToolCall`, and
  `AgentEvent` types that every later phase builds on. This is where the
  agent starts existing.

Get every box above checked, then open that file. 🚀