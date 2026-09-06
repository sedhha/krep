# Documentation Map

Index of every doc in this repository and the facts it owns. Before finishing
any task, check which rows your diff touches and update that doc — see
[`docs/WORKFLOW.md`](WORKFLOW.md#keeping-docs-in-sync).

| Doc | Owns | Update when |
| --- | ---- | ----------- |
| [`README.md`](../README.md) | Project one-liner, doc links, `make` quick reference, the "how to start work" procedure | A `make` target is added/renamed, the doc set changes, or the level-picking procedure changes |
| [`CLAUDE.md`](../CLAUDE.md) | Canonical repo-wide instruction source for coding agents (points elsewhere, restates nothing) | The doc map above it changes, or a new non-negotiable is added |
| [`AGENTS.md`](../AGENTS.md) | Pointer for Codex to `CLAUDE.md` / `docs/WORKFLOW.md` | Only if the pointer target changes |
| [`docs/WORKFLOW.md`](WORKFLOW.md) | The development process: escalation levels, verify gates, doc-sync rule | The escalation levels, verify gates, or doc-sync rule change |
| [`docs/product/agent-platform-v1.md`](product/agent-platform-v1.md) | Product goal, scope, what we're building and why | Product scope or goals change |
| [`docs/architecture/overview.md`](architecture/overview.md) | Runtime mental model, package layout, the layer graph diagram, cross-cutting conventions (Pydantic boundary, mypy strict) | A package is added/renamed/moved, the layer graph changes (readable summary of `tests/architecture/test_layers.py`, which is authoritative), or a repo-wide convention changes |
| [`docs/adr/README.md`](adr/README.md) | Index/purpose statement for the ADR log | The ADR process itself changes |
| [`docs/adr/NNNN-<slug>.md`](adr/README.md) | One durable architectural decision, its context, consequences, and status history | Never edit an existing ADR's decision — append to its Status History, or write a new ADR that supersedes it |
| [`docs/specs/README.md`](specs/README.md) | Index of capability specs, the in-flight status table, writing conventions | A spec folder is added/completed, or spec-writing conventions change |
| [`docs/specs/NNN-<slug>/spec.md`](specs/README.md) | What a capability does: Problem, Goals, Non-Goals, Acceptance Criteria | A capability's intended behavior or acceptance criteria change |
| [`docs/specs/NNN-<slug>/design.md`](specs/README.md) | How a capability is built, its Status (Proposed/Accepted) | The implementation approach for that capability changes |
| [`docs/specs/NNN-<slug>/plan.md`](specs/README.md) | Build order/slices for a capability, each with its own verify command | The slice plan for that capability changes |
| [`docs/specs/NNN-<slug>/notes.md`](specs/README.md) | Adversarial review findings and the Decision Log | New review findings or decisions are logged during that capability's build |
| [`docs/specs/_templates/`](specs/_templates/) | Blank templates for spec/design/plan/notes/adr/task-plan, used by `make spec` | The shape a Level 0-3 artifact must take changes |
| [`docs/plans/README.md`](plans/README.md) | Index/purpose statement for Level 1 task plans | The Level 1 plan format or process changes |
| [`docs/plans/YYYY-MM-DD-<slug>.md`](plans/README.md) | One bounded Level 1 task's plan | N/A — plans are point-in-time; not kept in sync after landing |
| `tests/architecture/test_layers.py` | Enforced layer-graph rules (code, not prose) — authoritative over the diagram in `docs/architecture/overview.md` | The layer graph changes (requires an ADR) |
| `Makefile` | `make` targets referenced by name in `README.md` / `docs/WORKFLOW.md` (`verify`, `fmt`, `lint`, `typecheck`, `arch`, `test`, `spec`, `install`, `help`) | A target is added, renamed, or removed |

Never restate a fact from one doc in another — link instead. A duplicated fact
is a future contradiction.
