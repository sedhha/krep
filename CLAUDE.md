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
| How should a human drive an agent through this? | [`docs/spec_driven_development/README.md`](docs/spec_driven_development/README.md) |

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

## Reply Style

Chat carries decisions. Files carry documents. Never put the same content in
both.

- **Never paste back content that now lives in a file.** Say what changed and
  where: "Added criterion 9 to `spec.md`; resolved findings 2–5 in `notes.md`."
  The human opens the file. This applies to findings tables, diffs, edited
  sections, and generated docs alike.
- **Default to under six lines.** Expand only when asked, or when a real
  trade-off needs stating.
- **Decisions are multiple-choice, not essays.** When the human's judgment is
  genuinely required, ask with concrete options and a recommendation. When it
  is not required, decide and say what you decided in one line.
- **No preamble, no recap, no "great question."** Lead with the answer or the
  action.
- **Say the level out loud once**, at the start, so it can be overridden.
- **Evidence before assertions**, always — see Non-Negotiables below.

## Shorthand

The human drives phases with the shorthand vocabulary defined in
[`docs/spec_driven_development/README.md`](docs/spec_driven_development/README.md#the-shorthand)
(`lvl?`, `draft design`, `review`, `resolve N …`, `accept`, `plan`, `slice N`,
`implement`, `verify`, `where? NNN`, `reread <path>`, `park <note>`, `why?`).
Honour those exactly and do not do more than the verb asks — `draft design` and `review` in
particular are explicit no-code instructions.

`where? NNN` inspects a spec folder and reports the phase. Read `spec.md`,
`design.md` (its Status field), `notes.md` (unresolved Resolution cells), and
`plan.md`, then answer in exactly three lines — phase, the evidence that
decided it, the next command — using the phase table in
[`docs/spec_driven_development/README.md`](docs/spec_driven_development/README.md#where-am-i-resuming-an-existing-spec).
No summary of the spec, no recap of prior work, no offer to start the next
phase.

    Phase 5 gate — all 10 notes.md findings resolved, design.md Status is Draft.
    Evidence: notes.md Resolution column full; design.md line 5 `Draft`.
    Next: read the design diff, then `accept`.

`implement` is the no-questions build. Pre-flight the artifacts first:
acceptance criteria numbered and verifiable, `design.md` Accepted, no
unresolved blocker/major findings in `notes.md`, `plan.md` sliced with verify
commands, no unanswered Open Questions, no ambiguity that would force a
mid-build judgment call. **If anything is missing, stop and name it exactly —
do not guess and do not build part of it.** If the pre-flight is clean, build
every slice test-first with `make verify` after each, straight through, asking
nothing. Report at the end: slices landed, verify output, and each acceptance
criterion mapped to the test proving it.

`reread <path>` means the human hand-edited that file; re-read it before acting
on it. Prefer that the human edits prose directly over dictating prose for you
to transcribe.

## Calling The Context Boundary

When a phase finishes — design drafted, review resolved, design accepted, plan
written, a slice landed and verified — **say so and tell the human to clear**.
Do not wait to be asked. End the phase with exactly this shape:

```text
Phase done: <what finished>. Clear context and resume with:
<the one-line resume prompt for the next phase>
```

Before saying it, check whether anything decided in this conversation exists
only in the conversation. If so, write it into `notes.md`'s Decision Log first,
then call the boundary — a decision that dies on clear is a process bug.

Do not carry a second phase in a context that has already finished one.

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
