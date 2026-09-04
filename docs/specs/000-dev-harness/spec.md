# Spec 000: Development Harness

| Field | Value |
| ----- | ----- |
| Status | `Accepted` |
| Level | 3 |
| Author | sedhha |
| Created | 2026-09-04 |
| Design | [design.md](design.md) |
| Plan | [plan.md](plan.md) |
| ADRs | — |

## Problem

Krep is being built primarily through coding agents, by a single engineer. Two
failure modes dominate that setup.

The first is unbounded scope. An agent given a goal and no stated boundary
builds outward until something stops it, and reviewing that output costs more
than the implementation saved. The second is unverifiable output. Without a
machine-readable pass/fail signal, the human is the feedback loop for every
change: agents cannot iterate to correctness on their own, so autonomy stays
low and every diff needs a careful read.

A third, quieter problem is that architectural rules written only in prose are
followed until the moment they are inconvenient. Nothing detects the violation,
so the structure erodes while the documentation still claims it holds.

Uniform process does not solve this. Applying a full specification lifecycle to
a one-line logging change wastes time and tokens; applying none of it to a new
authorization boundary produces work that has to be redone.

## Goals

- Every piece of work is classified into a ceremony level before it starts, and
  the artifacts it produces match that level.
- Starting a new piece of work is a single command that scaffolds the right
  documents and states the next actions concretely enough to follow without
  recalling the process.
- One command reports whether the repository is in a good state, and agents can
  run it themselves to iterate to correctness.
- The layer graph is enforced by a failing test rather than by prose.
- Implementation and review are always performed by different agents in
  different contexts.
- Product scope, rationale, structure, and capability detail each live in
  exactly one place.

## Non-Goals

- Adopting a third-party spec-driven-development framework. Superpowers is
  already installed and supplies the process skills; a repository-local
  convention layer is enough on top of it.
- Multi-agent orchestration, worktree automation, or parallel agent fan-out.
- Enforcing runtime concerns — secret handling, credential lifecycle, telemetry
  redaction — through static analysis. Those are capability-level test
  concerns, specified with their capabilities.
- Coverage thresholds, mutation testing, or performance budgets in the gate.
- Documentation generation, spec linting, or status dashboards.
- Any product behaviour. This spec produces no code under `src/krep/`.

## Acceptance Criteria

| # | Criterion | Verified by |
| - | --------- | ----------- |
| 1 | `docs/WORKFLOW.md` defines Levels 0–3 with a distinct trigger, artifact set, and flow for each, and states the one-way escalation rule. | Review |
| 2 | `make spec name=<slug> level=<n>` creates exactly the artifacts that level requires and nothing else. | Manual run at each level |
| 3 | `spec_init` refuses to run when the target folder or file already exists, and when the slug is not lower-case kebab-case, exiting non-zero without writing anything. | Manual run |
| 4 | `spec_init` assigns the next unused three-digit number by scanning `docs/specs/`, and the next unused four-digit ADR number by scanning `docs/adr/`. | Manual run |
| 5 | Running `spec_init` at level 2 or 3 appends a row to the index table in `docs/specs/README.md`. | Manual run |
| 6 | `spec_init` prints a numbered sequence of next actions naming, for each step, which agent runs it and the prompt to paste. | Manual run |
| 7 | `make verify` runs format checking, linting, strict type checking, and the test suite, and exits non-zero if any fails. | `make verify` |
| 8 | An import that violates the documented layer graph fails `make arch` with a message naming the file, the illegal import, and the rule. | Deliberate violation, reverted |
| 9 | A new top-level package under `src/krep/` fails the architecture test until its legal dependencies are declared. | Deliberate addition, reverted |
| 10 | The declared layer graph is acyclic, and no package is permitted to import `api` or `workers`. | `tests/architecture/test_layers.py` |
| 11 | `make verify` runs in CI on every push to `main` and every pull request. | `.github/workflows/verify.yml` |
| 12 | `CLAUDE.md` and `AGENTS.md` contain no knowledge of their own — only pointers to the document that owns each subject. | Review |

## Constraints

- Superpowers supplies brainstorming, planning, TDD, and verification skills
  already. This harness must compose with them, not duplicate or contradict
  them.
- Both Claude Code and Codex must read the same workflow definition. Any rule
  stated twice will diverge.
- The scaffolding script must run before the application exists and without an
  activated virtualenv, so it cannot import the package.
- `src/krep/.venv` exists inside the source tree and must be excluded from every
  tool that walks `src/`.
- Python 3.13, `uv` for dependency management, per `pyproject.toml`.
- The layer graph must match the runtime mental model in
  `docs/product/agent-platform-v1.md`, including `tools` depending on
  `connections` and `authorization` for gateway credential resolution.
