# Krep

Krep is a native LangGraph agent platform for enterprise agent execution, tool
integration, authorization, durable workflows, telemetry, and evaluation.

The project is currently in the specification and foundation-design phase.

## Documentation

- [Development workflow](docs/WORKFLOW.md) — start here
- [V1 product specification](docs/product/agent-platform-v1.md)
- [Architecture](docs/architecture/overview.md)
- [Architectural decisions](docs/adr/README.md)
- [Capability specifications](docs/specs/README.md)
- [Level 1 task plans](docs/plans/README.md)

## Development

```bash
make install                          # sync the virtualenv
make verify                           # the gate: format, lint, types, tests
make spec name=<slug> level=<0-3>     # scaffold docs for new work
make help                             # every target
```

## How to Start a Piece of Work

This section is the *procedure*. [`docs/WORKFLOW.md`](docs/WORKFLOW.md) is the
*contract* — the level definitions, the escalation rule, and why any of it
exists. Read that once; come back here when you have forgotten the steps.

### 1. Pick a level

Classify before you start. When torn between two levels, take the higher one —
escalating mid-task is allowed, de-escalating is not.

| Level | Ask yourself | Example |
| ----- | ------------ | ------- |
| **0** | Can I state the whole diff in one sentence? | Fix a typo, rename a variable, change a log line |
| **1** | Am I changing a flow that already exists in this repo? | Add a field to an existing endpoint's response |
| **2** | Am I adding a capability, a module, or a contract others will depend on? | The tool gateway, the agent registry |
| **3** | Does this touch auth, data boundaries, or the layer graph? | CEL authorization, credential lifecycle |

If there is no existing code to change, it is **not** Level 1. A new module is
Level 2 at minimum.

### 2. Scaffold

```bash
make spec name=agent-registry level=2
```

The slug is lower-case kebab-case. The command creates the documents that level
requires, registers them in
[`docs/specs/README.md`](docs/specs/README.md), and prints the numbered sequence
of sessions to run next — so you never have to remember step 3 while doing
step 2.

```bash
make spec name=some-tweak level=0                                  # prints guidance, writes nothing
make spec name=add-request-id level=1 title="Add requestId to logs" # one short plan
make spec name=agent-registry level=2                              # spec + design + plan + notes
make spec name=tool-gateway level=3                                # the above, plus an ADR stub
```

It refuses to run on a bad slug, an invalid level, or an existing target, and
writes nothing when it refuses. Safe to retry.

### 3. Work the printed steps

Each numbered step is a **fresh session**. Carry the files forward, never the
chat history — a context that argued about the design is the worst possible
reviewer of it.

For Level 2 and 3, the shape is:

```text
you      → spec.md          Problem, Goals, Non-Goals, numbered Acceptance Criteria.
                            No design decisions. This is the part only you can do.
agent A  → design.md        Interviews you, then writes it. No code.
agent B  → notes.md         Fresh context, adversarial review of spec + design. No code.
you      → accept           Resolve notes.md by editing spec/design. Set design Status
                            to Accepted. This is the architectural commitment gate.
agent A  → plan.md          Ordered slices, each independently verifiable.
agent    → code             One fresh session per slice. Tests first. make verify after each.
agent B  → diff review      Fresh context, against the acceptance criteria by number.
you      → ship             Read the diff. Update the Index status. Commit.
```

Use two different tools for agent A and agent B — Claude Code and Codex — not
two sessions of one. Their failure modes differ, which is the entire point of
the second pass.

### 4. Verify before claiming anything

```bash
make verify
```

Exit zero is the only authoritative signal that the repository is in a good
state. Nothing is complete, fixed, or passing until this has been run and seen
to pass. Ask an agent for evidence, not assurance.

`make arch` on its own checks the layer graph in
[`docs/architecture/overview.md`](docs/architecture/overview.md). If it fails,
the fix is the import — or an ADR. It is never the test.

### If you lose your place

| Question | Where to look |
| -------- | ------------- |
| What is in flight, and how far along? | The Index table in [`docs/specs/README.md`](docs/specs/README.md) |
| What are the steps again? | Re-run `make spec` for a scratch slug, read the output, delete the folder |
| Which step is this spec on? | The `Status` field in its `spec.md` and `design.md` |
| Why was it built this way? | The spec's `notes.md` Decision Log, then [`docs/adr/`](docs/adr/README.md) |
| What are the rules, and why? | [`docs/WORKFLOW.md`](docs/WORKFLOW.md) |
| How do I write a good spec? | Writing Conventions in [`docs/specs/README.md`](docs/specs/README.md), and [`000-dev-harness`](docs/specs/000-dev-harness/spec.md) as a worked example |
