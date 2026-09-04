# Design 000: Development Harness

| Field | Value |
| ----- | ----- |
| Status | `Accepted` |
| Author | sedhha |
| Created | 2026-09-04 |
| Spec | [spec.md](spec.md) |
| Review notes | [notes.md](notes.md) |

## Approach

The harness has three parts, matching the three things an agent needs: intent,
context, and feedback.

**Intent** is a level classification plus scaffolded documents. A single
convention file, `docs/WORKFLOW.md`, defines Levels 0–3 and is referenced by
both `CLAUDE.md` and `AGENTS.md` so Claude Code and Codex read one definition.
`scripts/spec_init.sh` turns a chosen level into the exact files that level
requires, then prints the sequence of sessions and prompts to run next — so the
process does not have to be recalled, only followed.

**Context** is a fixed set of single-owner documents: product scope, structure,
rationale, and per-capability specs. `CLAUDE.md` is deliberately a table of
contents rather than a manual, because a large instruction file is read
selectively and its middle is effectively invisible. Each document owns its
subject and links to the others rather than restating them.

**Feedback** is `make verify`, a single command combining format checking,
linting, strict typing, and tests, plus an architecture test that turns the
layer graph from prose into a failing assertion. Every agent instruction ends
in that command, which is what makes iteration to correctness possible without
a human in the loop for each attempt.

## Alternatives Considered

| Alternative | Why not |
| ----------- | ------- |
| GitHub Spec Kit | Its constitution → specify → clarify → plan → tasks → analyze → implement lifecycle is uniform, and the cost falls hardest on the small changes that make up most of the work. Its value is strongest for teams needing auditability, which is not the current constraint. |
| OpenSpec's `specs/` + `changes/` delta model | Separating current truth from proposed deltas pays off in brownfield code. Krep is greenfield: for a while every spec *is* the delta, so the second directory is bookkeeping without a reader. Worth revisiting once V1 ships and changes start amending shipped behaviour. |
| BMAD | Models an AI software organisation with analyst, architect, and scrum-master personas. For a single senior engineer this substitutes simulated hierarchy for the engineer's own judgement, which is the thing worth amplifying. |
| A single large `CLAUDE.md` holding the whole workflow | Reported to work poorly at scale: the file grows, and instructions in its middle stop being followed. Progressive disclosure through a map plus owned documents keeps each read small and relevant. |
| Layer rules as prose in the architecture doc | Followed until inconvenient, and nothing detects the violation. The documentation then describes a structure the code no longer has. |
| A `ruff` custom rule or import-linter for layering | `import-linter` would work, but it adds a dependency and a second configuration language for one rule. A parametrized pytest walking the AST is around 150 lines, needs no dependency, and produces a message naming the file and the rule. |
| Python CLI (`krep-spec` console script) for scaffolding | Couples the development tooling to the package being built, and needs a synced virtualenv. The script must work on a fresh clone before any code exists. |

## Components

### `docs/WORKFLOW.md`

- **Purpose:** The single definition of the level classification, the Level 2/3
  session sequence, the verification gates, and the source-of-truth map.
- **Interface:** Read by humans and by both agents; referenced from `CLAUDE.md`
  and transitively from `AGENTS.md`.
- **Depends on:** Nothing. It is the root of the convention layer.

### `scripts/spec_init.sh`

- **Purpose:** Scaffold the artifacts a level requires; print the next actions.
- **Interface:** `spec_init.sh <slug> [--level N] [--title "..."]`, wrapped as
  `make spec name=<slug> [level=N] [title="..."]`. Exits non-zero on an invalid
  slug, an invalid level, or an existing target.
- **Depends on:** `docs/specs/_templates/`, `git config user.name`, POSIX
  `awk`. No Python, no virtualenv, no network.

### `docs/specs/_templates/`

- **Purpose:** The source of every scaffolded document. Guidance lives in HTML
  comments so it is visible while writing and absent when rendered, and so an
  unfilled template is obvious at review time.
- **Interface:** `{{NUMBER}}`, `{{ADR_NUMBER}}`, `{{SLUG}}`, `{{TITLE}}`,
  `{{DATE}}`, `{{AUTHOR}}`, `{{LEVEL}}` substituted by literal string
  replacement in the script.
- **Depends on:** Nothing.

### `tests/architecture/test_layers.py`

- **Purpose:** Enforce the layer graph. Authoritative over the diagram in the
  architecture overview.
- **Interface:** `ALLOWED_IMPORTS`, a mapping from package to the set of
  sibling packages it may import. Five tests: package coverage, referential
  integrity of the mapping, no entrypoint may be imported, acyclicity, and a
  per-package import check parametrized over the packages found on disk.
- **Depends on:** `ast`, `pathlib`, `pytest`. It parses rather than imports, so
  it needs no runtime dependency and cannot be defeated by import side effects.

### `Makefile`

- **Purpose:** Name every gate, so an instruction can end in a command rather
  than a description.
- **Interface:** `install`, `fmt`, `fmt-check`, `lint`, `typecheck`, `arch`,
  `test`, `test-unit`, `cov`, `verify`, `spec`, `clean`, `help`.
- **Depends on:** `uv`, and the dev dependency group in `pyproject.toml`.

## Data Flow

```text
  human picks a level  ──▶  make spec name=X level=2
                                    │
                                    ▼
                    spec_init.sh   validate slug + level
                                   scan docs/specs/  ──▶ next NNN
                                   render templates  ──▶ docs/specs/NNN-X/
                                   append index row  ──▶ docs/specs/README.md
                                   print steps 1..8
                                    │
        ┌───────────────────────────┴──────────────────────────┐
        ▼                                                      ▼
   spec.md (human)                                    each step is a
        ▼                                             fresh session; only
   design.md (agent A)                                files cross between
        ▼                                             them, never chat
   notes.md (agent B, adversarial)
        ▼
   human accepts design.md  ◀── the architectural commitment gate
        ▼
   plan.md (agent A)
        ▼
   slice N (agent) ──▶ make verify ──┐
        ▲                            │ fails
        └────────────────────────────┘
        ▼ passes
   diff review (agent B) ──▶ human ──▶ ship
```

Failure paths: an invalid slug, level, or pre-existing target exits non-zero
before writing anything, so a mistyped command never leaves a half-scaffolded
folder. A missing index marker in `docs/specs/README.md` skips the index append
rather than failing the scaffold, because a spec folder is more valuable than
its index row. A failing `make verify` returns the agent to the slice it was
implementing; it never advances the sequence.

## Contracts

- **Level → artifacts.** Level 0: none. Level 1:
  `docs/plans/YYYY-MM-DD-<slug>.md`. Level 2: `docs/specs/NNN-<slug>/` with
  `spec.md`, `design.md`, `plan.md`, `notes.md`. Level 3: Level 2 plus
  `docs/adr/NNNN-<slug>.md`.
- **Numbering.** Spec numbers are three digits, ADR numbers four, both assigned
  as one past the highest found on disk. `000` is reserved for this harness;
  capabilities start at `001`. Numbers are permanent — an abandoned spec keeps
  its number and is marked `Abandoned`.
- **Index marker.** `docs/specs/README.md` contains the literal
  `SPEC_INDEX_END` inside an HTML comment. Rows are inserted immediately before
  it.
- **`make verify` exit code.** Zero means the repository is in a good state.
  This is the only signal any agent instruction may treat as authoritative.
- **`ALLOWED_IMPORTS`** is the machine-readable layer graph. Widening it is a
  Level 3 change requiring an ADR.

## Failure Modes

| Failure | Caller sees | Retry | State left behind |
| ------- | ----------- | ----- | ----------------- |
| Slug not kebab-case | `error: slug must be lower-case kebab-case` | Rerun with a valid slug | None |
| Level outside 0–3 | `error: level must be 0, 1, 2, or 3` | Rerun | None |
| Target folder or file exists | `error: refusing to overwrite …` | Choose another slug, or edit in place | None |
| Same slug already specced under a different number | `error: a spec for '<slug>' already exists` | Reuse the existing spec | None |
| Missing template file | `error: missing template: …` | Restore the template | Possibly an empty folder; harmless |
| `SPEC_INDEX_END` marker absent | Scaffold succeeds, no index row | Add the row by hand | Folder created, index unchanged |
| `git config user.name` unset | Author renders as `unknown` | Set it, edit the file | Document created |
| Illegal import introduced | `make arch` fails naming file, import, and rule | Fix the import or write an ADR | Unstaged code |
| New package undeclared | Architecture test fails naming the package | Declare it in `ALLOWED_IMPORTS` and the overview | Unstaged code |

## Architecture Impact

No new layer-graph edges. This spec adds no code under `src/krep/`; it
*declares* the graph that already matches the product mental model and makes it
enforceable. Two edges are worth naming because they look like violations and
are not: `tools → connections` and `tools → authorization`, both required
because the Tool Gateway authorizes a call and resolves its credential before
dispatch.

The `integrations → shared` restriction is the load-bearing rule. It keeps
adapters ignorant of product concepts so that CEL, persistence, or the LangGraph
binding can each be replaced without touching capability code.

## Testing Strategy

| Criterion | Test | Tier |
| --------- | ---- | ---- |
| 1 | Review of `docs/WORKFLOW.md` | Review |
| 2 | `spec_init.sh` executed at levels 0, 1, 2, 3 | Manual |
| 3 | `spec_init.sh` with a bad slug, then a duplicate slug | Manual |
| 4 | Number assignment observed against existing `docs/specs/` and `docs/adr/` | Manual |
| 5 | Index row appended in `docs/specs/README.md` | Manual |
| 6 | Next-steps block inspected in terminal output | Manual |
| 7 | `make verify` | Gate |
| 8 | Deliberate illegal import, `make arch`, revert | Architecture |
| 9 | Deliberate new package, `make arch`, revert | Architecture |
| 10 | `test_layer_graph_is_acyclic`, `test_no_package_may_import_an_entrypoint` | Architecture |
| 11 | `.github/workflows/verify.yml` runs `make verify` on push and PR | CI |
| 12 | Review of `CLAUDE.md` and `AGENTS.md` | Review |

Criteria 2–6 are verified by running the script, not by automated tests. A test
harness for a scaffolding script that is run a few dozen times a year, whose
failure is immediately visible and non-destructive, would cost more than it
returns. This is a deliberate exception to the test-first rule, not an
oversight — if the script grows conditional logic beyond level dispatch, it
earns tests.

## Out of Scope

- Third-party SDD frameworks. Revisit OpenSpec's delta model after V1 ships.
- Automated spec linting or a status dashboard. The index table and `git` are
  sufficient at this scale.
- Coverage thresholds in the gate. They reward test count over test quality
  while the codebase is still small enough for that to distort behaviour.
- Worktree and parallel-agent automation.
