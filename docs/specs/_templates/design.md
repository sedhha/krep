# Design {{NUMBER}}: {{TITLE}}

| Field | Value |
| ----- | ----- |
| Status | `Draft` |
| Author | {{AUTHOR}} |
| Created | {{DATE}} |
| Spec | [spec.md](spec.md) |
| Review notes | [notes.md](notes.md) |

<!--
  A design answers HOW. It is accepted by a human, not by an agent — setting
  Status to `Accepted` is the architectural commitment gate in docs/WORKFLOW.md.

  Written by an agent after interviewing the human. Reviewed adversarially by a
  different agent in a fresh context, whose findings go to notes.md.
-->

## Approach

<!--
  The chosen approach in a few paragraphs. Lead with the shape of the solution,
  not the file list.
-->

## Alternatives Considered

<!--
  At least one real alternative with an honest reason for rejection. "It was
  worse" is not a reason. If no alternative was considered, the design was not
  designed.
-->

| Alternative | Why not |
| ----------- | ------- |
| | |

## Components

<!--
  One subsection per module or unit. For each, answer the three questions that
  make a unit reviewable in isolation: what does it do, how is it used, what
  does it depend on.
-->

### `krep.<package>.<module>`

- **Purpose:**
- **Interface:**
- **Depends on:**

## Data Flow

<!--
  A diagram for anything with more than two hops. ASCII is fine and diffs well.
  Show the failure path, not only the happy path.
-->

```text
```

## Contracts

<!--
  Schemas, endpoints, events, and persisted shapes introduced or changed. These
  are what other code depends on, so they get named explicitly and reviewed
  hardest.
-->

## Failure Modes

<!--
  For each thing that can fail: what the caller observes, what is retried, what
  is logged, and what state is left behind. Absent this section, error handling
  gets invented per call site.
-->

| Failure | Caller sees | Retry | State left behind |
| ------- | ----------- | ----- | ----------------- |
| | | | |

## Architecture Impact

<!--
  Which layer-graph edges this design uses, and whether any are new. A new edge
  requires an ADR and makes this Level 3. State "no new edges" explicitly when
  true — reviewers need to see that it was checked.
-->

## Testing Strategy

<!--
  Map each numbered acceptance criterion from spec.md to the test that proves
  it, and name the test tier: unit, integration, contract, e2e, or architecture.
-->

| Criterion | Test | Tier |
| --------- | ---- | ---- |
| 1 | | |

## Out of Scope

<!-- Restate the spec's non-goals that were tempting to build anyway. -->

-
