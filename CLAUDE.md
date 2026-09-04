# Krep Agent Platform — Engineering Instructions

This file is the canonical repository instruction source for coding agents. It
is a map, not a manual: it says where knowledge lives rather than restating it.

Use GitHub CLI account `sedhha` for this repository.

## Read First

**[`docs/WORKFLOW.md`](docs/WORKFLOW.md)** — the development workflow. Classify
every task into Level 0–3 and follow only that level's process. Read this before
starting any work, including work that looks trivial.

## Source of Truth

| Question | Document |
| -------- | -------- |
| What are we building, and why? | [`docs/product/agent-platform-v1.md`](docs/product/agent-platform-v1.md) |
| How is the codebase partitioned? | [`docs/architecture/overview.md`](docs/architecture/overview.md) |
| Why is it built this way? | [`docs/adr/`](docs/adr/README.md) |
| What does a capability do and how is it built? | [`docs/specs/`](docs/specs/README.md) |
| How is a bounded task planned? | [`docs/plans/`](docs/plans/README.md) |

Never restate a fact from one of these in another. Link instead.

## Non-Negotiables

- **`make verify` is the gate.** Never describe work as complete, fixed, or
  passing without running it and seeing it pass. Evidence before assertions.
- **The layer graph is enforced in code**, in
  [`tests/architecture/test_layers.py`](tests/architecture/test_layers.py).
  Widening it is a Level 3 change and requires an ADR. Do not edit that file to
  make an import legal.
- **Tests before implementation.** Write the failing test, watch it fail, then
  implement.
- **Ask before committing.** After a coherent, self-contained unit of work,
  stop and ask whether to commit. Never commit unprompted.
- **Secrets never reach LLM context, message state, logs, telemetry, or
  evaluation datasets.**
- **Pydantic models on every API boundary.** No untyped dictionaries cross it.

## Scaffolding New Work

```bash
make spec name=<slug> level=<0|1|2|3>
```

This creates the documents the level requires and prints the exact sequence of
sessions and prompts to run next.

## Code Comments

Default to no comments. Add one only when the *why* is non-obvious and a reader
would otherwise be confused: a hidden constraint, a subtle invariant, or
behaviour that contradicts what the code appears to do. Never write comments
that restate the code, narrate a change, or reference a task or ticket.

## Commits

Every commit created by Claude ends with:

```text
Co-Authored-By: Claude <noreply@anthropic.com>
```

Commits created by Codex do not carry that trailer.
