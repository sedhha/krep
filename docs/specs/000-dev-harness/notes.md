# Review Notes 000: Development Harness

## Findings

| # | Severity | Finding | Resolution |
| - | -------- | ------- | ---------- |
| 1 | question | Does layering Superpowers plus a local convention layer cost more context than it saves? | Resolved. Measured: the `using-superpowers` hook costs ~780 tokens unconditionally per session, and process skills load only on invocation — `brainstorming` ~3.9k, `test-driven-development` ~2.3k, `writing-plans` ~1.8k, `verification-before-completion` ~0.9k. A full Level 2 feature spends roughly 6–9k tokens of skill text across several sessions, under 1% of the context window, and less than a single avoided rework cycle. `subagent-driven-development` is the expensive one at ~8.1k and is simply not invoked. |
| 2 | major | `docs/plans/fastapi-setup.md` and ADR-0001 already covered the API foundation work, outside the convention this spec creates. | Resolved. Folded into `docs/specs/001-api-foundation/`; ADR-0001 stays in `docs/adr/` and is linked from the spec. The harness's first test case is now the harness. |
| 3 | minor | The layer graph exists in two places: the diagram in `docs/architecture/overview.md` and `ALLOWED_IMPORTS` in the architecture test. | Accepted, not resolved. Both readers are needed — humans read the diagram, CI reads the mapping. The test is declared authoritative in both files, and each points at the other, so a divergence is visible from either side. |
| 4 | question | Should the scaffolding script itself be tested, given the test-first rule? | Resolved. No. The exception and its reasoning are recorded in `design.md` under Testing Strategy: failure is immediate, visible, and non-destructive. Revisit if the script grows logic beyond level dispatch. |

## Decision Log

- 2026-09-04: Rejected Spec Kit, OpenSpec, and BMAD in favour of a local
  convention layer over Superpowers. Reasoning and revisit conditions are in
  `design.md` under Alternatives Considered — OpenSpec's delta model becomes
  interesting once V1 ships and changes start amending shipped behaviour.
- 2026-09-04: `000` reserved for the harness so that product capability numbers
  begin at `001` and stay aligned with the `src/krep/` package skeleton.
- 2026-09-04: Layering enforced by a parametrized pytest walking the AST rather
  than by `import-linter`, avoiding a dependency and a second configuration
  language for a single rule.
