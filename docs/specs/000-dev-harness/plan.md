# Plan 000: Development Harness

| Field | Value |
| ----- | ----- |
| Status | `Shipped` |
| Author | sedhha |
| Created | 2026-09-04 |
| Spec | [spec.md](spec.md) |
| Design | [design.md](design.md) |

## Slices

### Slice 1 — Convention layer

- **Goal:** One workflow definition both agents read, and a documented layer graph.
- **Files:** `docs/WORKFLOW.md`, `docs/architecture/overview.md`, `CLAUDE.md`, `AGENTS.md`, `docs/plans/README.md`
- **Acceptance criteria covered:** 1, 12
- **Tests to write first:** None — prose.
- **Verify:** Read `CLAUDE.md` and confirm it states no fact it does not own.
- **Done when:** Every subject has exactly one owning document, and `AGENTS.md` reaches the workflow through `CLAUDE.md`.

### Slice 2 — Templates and spec index

- **Goal:** The source of every scaffolded document, plus the index it registers into.
- **Files:** `docs/specs/README.md`, `docs/specs/_templates/{spec,design,plan,notes,adr,task-plan}.md`
- **Acceptance criteria covered:** 5 (marker), and the writing conventions
- **Tests to write first:** None — templates.
- **Verify:** `grep -c SPEC_INDEX_END docs/specs/README.md` returns 1.
- **Done when:** Each template's guidance comments say what belongs in the section and what does not.

### Slice 3 — Scaffolding script

- **Goal:** One command scaffolds a level's artifacts and prints the next actions.
- **Files:** `scripts/spec_init.sh`
- **Acceptance criteria covered:** 2, 3, 4, 5, 6
- **Tests to write first:** None — see the exception recorded in `design.md`.
- **Verify:** `bash -n scripts/spec_init.sh`, then a run at each level, then a run with a bad slug and a duplicate slug expecting non-zero exit.
- **Done when:** Level 0 prints guidance and writes nothing; levels 1–3 write exactly their artifact set; every invalid input exits non-zero having written nothing.

### Slice 4 — Verification gates

- **Goal:** A single command that says whether the repository is in a good state.
- **Files:** `Makefile`, `pyproject.toml`
- **Acceptance criteria covered:** 7
- **Tests to write first:** None — configuration. The gate verifies itself.
- **Verify:** `make verify`
- **Done when:** `make verify` runs format checking, linting, strict typing, and tests, and `src/krep/.venv` is excluded from all three tools.

### Slice 5 — Architecture enforcement

- **Goal:** The layer graph becomes a failing assertion.
- **Files:** `tests/architecture/test_layers.py`, `tests/**/__init__.py`
- **Acceptance criteria covered:** 8, 9, 10
- **Tests to write first:** This slice *is* the test. Confirm it fails against a deliberate violation before trusting it.
- **Verify:** `make arch`, then introduce `from krep.api import x` inside `krep/shared/`, confirm failure names the file and rule, revert.
- **Done when:** A violation, an undeclared package, and a cycle each fail with a message that names the fix.

### Slice 6 — CI

- **Goal:** The gate runs without being remembered.
- **Files:** `.github/workflows/verify.yml`
- **Acceptance criteria covered:** 11
- **Tests to write first:** None.
- **Verify:** Workflow run on the first pull request.
- **Done when:** `make verify` runs on push to `main` and on every pull request, with in-progress runs cancelled per ref.

### Slice 7 — Seed the first capability

- **Goal:** The harness's first real user is the API foundation work, so the convention is exercised rather than described.
- **Files:** `docs/specs/001-api-foundation/{spec,design,plan,notes}.md`, `docs/plans/fastapi-setup.md` (removed)
- **Acceptance criteria covered:** None directly; validates 2 and 6 in practice.
- **Tests to write first:** None.
- **Verify:** `docs/specs/001-api-foundation/spec.md` links ADR-0001 and states acceptance criteria; no orphaned plan remains in `docs/plans/`.
- **Done when:** The existing FastAPI intent is expressed as a numbered spec and nothing references the removed file.

## Coverage Check

| Criterion | Slice |
| --------- | ----- |
| 1 | 1 |
| 2 | 3 |
| 3 | 3 |
| 4 | 3 |
| 5 | 2, 3 |
| 6 | 3 |
| 7 | 4 |
| 8 | 5 |
| 9 | 5 |
| 10 | 5 |
| 11 | 6 |
| 12 | 1 |

## Risks

- **The layer graph is guessed ahead of the code.** It is derived from the
  product mental model, not from working modules, so an edge will eventually be
  wrong. That is acceptable: the test forces the correction to be a deliberate,
  documented decision rather than a silent drift.
- **Slice 5 is the slice most likely to expand.** The temptation is to enforce
  secret handling, naming, and file size in the same pass. Those are separate
  decisions and belong to the capabilities that need them.
- **Strict `mypy` on an effectively empty codebase is free now and expensive to
  retrofit.** Enabling it late is the failure mode being avoided; the cost is
  paid on the first real module instead.
