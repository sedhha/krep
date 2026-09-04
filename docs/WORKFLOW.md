# Development Workflow

This file is the canonical workflow contract for humans and coding agents working
in this repository. `CLAUDE.md` and `AGENTS.md` point here.

## Core Principles

1. **Ceremony scales with the task.** A typo fix and a new auth boundary do not
   deserve the same process. Pick a level below and follow only that level.
2. **The human owns *why*; agents own *how* up to the architecture boundary.**
   Product intent, trade-offs, correctness criteria, and architectural
   invariants are decided by a human. Agents propose; humans approve
   architectural commitments.
3. **Every instruction ends in a verify command.** `make verify` is the single
   machine-readable pass/fail signal. Without it, the human becomes the feedback
   loop and autonomy is unsafe.
4. **Whoever wrote it does not review it.** Implementation and review happen in
   different agents, or at minimum in a fresh context. A context that debugged
   the code cannot independently review the code.
5. **Fresh context per phase.** Research, planning, implementation, and review
   each start clean. Carry forward artifacts (`spec.md`, `design.md`,
   `plan.md`), never conversation history.

## Escalation Levels

Classify the work before starting, and say the classification out loud so it can
be overridden. When in doubt between two levels, take the higher one. The
ratchet is one-way: discovering hidden complexity mid-task escalates the level;
nothing de-escalates mid-task.

| Level | Trigger | Artifacts | Flow |
| ----- | ------- | --------- | ---- |
| **0** — trivial | The diff can be stated in one sentence. Typo, log line, rename, comment, config value. | none | prompt → code → `make verify` |
| **1** — task | A bounded change to a flow that already exists in this repo. New endpoint, new service method, local refactor, added test. | `docs/plans/YYYY-MM-DD-<slug>.md` | explore → plan → code → `make verify` → diff review |
| **2** — feature | A new capability, a new module, or a new contract others depend on. | `docs/specs/NNN-<slug>/{spec,design,plan,notes}.md` | brainstorm → spec → design → acceptance criteria → sliced implementation → fresh-context review |
| **3** — system | Auth model, data boundaries, cross-module restructure, anything changing the layer graph. | Level 2 **plus** an ADR and a migration/rollback note | Level 2 plus threat model and adversarial review |

If there is no existing flow in this repository to change, the work is **not**
Level 1. A brand-new module is Level 2 at minimum.

## Level 2 / 3 Sequence

`scripts/spec_init.sh` scaffolds the folder and prints these steps with
paste-ready prompts.

```text
make spec name=<slug> level=2
        │
        ▼
1. HUMAN    Fill spec.md: Problem, Goals, Non-Goals, Acceptance Criteria.
            Leave design decisions blank. Criteria must be observable
            and testable, not aspirational.
        │
        ▼
2. AGENT A  Interview the human, then write design.md. No code.
        │
        ▼
3. AGENT B  Fresh context. Adversarially review spec.md + design.md.
            Unstated assumptions, missing edge cases, violated
            invariants, over-engineering. Findings to notes.md. No code.
        │
        ▼
4. HUMAN    Resolve notes.md. Set design.md Status to Accepted.
            This is the architectural commitment gate.
        │
        ▼
5. AGENT A  Fresh context. spec.md + design.md → plan.md.
            Every slice carries its own verify command.
        │
        ▼
6. AGENT    Fresh context per slice. Test first. `make verify` after each.
        │
        ▼
7. AGENT B  Fresh context. Review the diff against spec.md acceptance
            criteria. Not against the implementation's own logic.
        │
        ▼
8. HUMAN    Read the diff. Ship.
```

Agent A and Agent B must be different sessions. Using two different tools
(Claude Code and Codex) is stronger than two sessions of one tool, because their
failure modes differ.

## Verification Gates

```bash
make verify        # fmt-check + lint + typecheck + arch + test. The gate.
make fmt           # apply formatting
make lint          # ruff check
make typecheck     # mypy strict
make arch          # layer-graph enforcement only
make test          # pytest
```

`make verify` must pass before any work is described as complete. Claiming
completion without running it is a process violation, not an optimism problem.

Architectural rules live in code, not prose. If a rule matters, it belongs in
`tests/architecture/` or a lint rule — a rule stated only in Markdown will
eventually be ignored by a human or an agent under time pressure.

## Where Truth Lives

| Question | Source of truth |
| -------- | --------------- |
| What are we building and why? | `docs/product/agent-platform-v1.md` |
| How do the pieces fit together? | `docs/architecture/overview.md` |
| Why is it built this way? | `docs/adr/` |
| What does capability NNN do? | `docs/specs/NNN-<slug>/spec.md` |
| How is capability NNN built? | `docs/specs/NNN-<slug>/design.md` |
| What is the build order? | `docs/specs/NNN-<slug>/plan.md` |
| Which invariants are enforced? | `tests/architecture/` |

Never restate one of these in another. Link instead. A duplicated fact is a
future contradiction.
