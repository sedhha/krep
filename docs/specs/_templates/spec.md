# Spec {{NUMBER}}: {{TITLE}}

| Field | Value |
| ----- | ----- |
| Status | `Draft` |
| Level | {{LEVEL}} |
| Author | {{AUTHOR}} |
| Created | {{DATE}} |
| Design | [design.md](design.md) |
| Plan | [plan.md](plan.md) |
| ADRs | — |

<!--
  A spec answers WHAT and WHY. It must contain no design decisions: no module
  names, no library choices, no schema. If you find yourself writing "we will
  use X", that belongs in design.md.

  Fill the sections below yourself before handing this to an agent. The
  acceptance criteria are the part that matters most — they become tests.
-->

## Problem

<!--
  What is broken or missing today, stated from outside the system. Two or three
  paragraphs at most. If you cannot describe the problem without naming a
  solution, you do not understand the problem yet.
-->

## Goals

<!-- Outcomes, not tasks. Each one observable from outside the system. -->

-

## Non-Goals

<!--
  The most valuable section in the document. Every non-goal you write here is
  scope an agent will not silently invent. Be aggressive.
-->

-

## Acceptance Criteria

<!--
  Each criterion must be independently verifiable and must fail before the work
  and pass after it. Write them so a reviewer can check them without reading
  the implementation.

  Good:  Requesting an unknown agent id returns 404 with an `error.code` of
         `agent_not_found` and does not emit a run record.
  Bad:   Error handling is robust.

  Number them. Tests and reviews cite these numbers.
-->

| # | Criterion | Verified by |
| - | --------- | ----------- |
| 1 | | |

## Constraints

<!--
  Hard limits the design must respect: product rules from
  docs/product/agent-platform-v1.md, accepted ADRs, layer-graph rules,
  performance or security requirements. Link to the source of each.
-->

-

## Open Questions

<!--
  Anything that must be answered before design.md can be accepted. Delete the
  section once empty; an empty Open Questions section reads as "nothing was
  considered".
-->

-
