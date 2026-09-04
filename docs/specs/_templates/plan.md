# Plan {{NUMBER}}: {{TITLE}}

| Field | Value |
| ----- | ----- |
| Status | `Not started` |
| Author | {{AUTHOR}} |
| Created | {{DATE}} |
| Spec | [spec.md](spec.md) |
| Design | [design.md](design.md) |

<!--
  Written only after design.md is Accepted.

  A plan is an ordered list of slices. A slice is a change that leaves the
  repository working, verifiable, and committable on its own. If a slice cannot
  be verified without the next slice, they are one slice.

  Each slice is executed in a fresh agent context, test first, and ends by
  running its verify command. An agent executing this plan should need nothing
  except this file, spec.md, and design.md.
-->

## Slices

### Slice 1 — <name>

- **Goal:**
- **Files:**
- **Acceptance criteria covered:** <!-- numbers from spec.md -->
- **Tests to write first:**
- **Verify:** `make verify`
- **Done when:**

### Slice 2 — <name>

- **Goal:**
- **Files:**
- **Acceptance criteria covered:**
- **Tests to write first:**
- **Verify:** `make verify`
- **Done when:**

## Coverage Check

<!--
  Every numbered acceptance criterion in spec.md must appear against at least
  one slice. An uncovered criterion means the plan is incomplete, not that the
  criterion was optional.
-->

| Criterion | Slice |
| --------- | ----- |
| 1 | |

## Risks

<!--
  Where this plan is most likely to be wrong, and what would be done about it.
  Name the slice most likely to expand.
-->

-
