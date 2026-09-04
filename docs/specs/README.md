# Capability Specifications

One folder per capability, numbered in the order it was specified. A folder is
created by `make spec` — see [`docs/WORKFLOW.md`](../WORKFLOW.md) for when a
piece of work earns one.

```text
docs/specs/NNN-<slug>/
├── spec.md      WHAT and WHY.   Written by a human. No design decisions.
├── design.md    HOW.            Written by an agent. Accepted by a human.
├── plan.md      BUILD ORDER.    Ordered, independently verifiable slices.
└── notes.md     WORKING LOG.    Review findings and implementation decisions.
```

`_templates/` holds the source of every scaffolded file. Improving a template
improves every future spec, so fix the template rather than fixing the same
thing in each spec.

## Index

| # | Capability | Status | Spec | Design | Plan |
| - | ---------- | ------ | ---- | ------ | ---- |
| 000 | Development harness | Accepted | [spec](000-dev-harness/spec.md) | [design](000-dev-harness/design.md) | [plan](000-dev-harness/plan.md) |
| 001 | API Foundation | Draft | [spec](001-api-foundation/spec.md) | [design](001-api-foundation/design.md) | [plan](001-api-foundation/plan.md) |
<!-- scripts/spec_init.sh appends rows above this marker: SPEC_INDEX_END -->

Status is one of `Draft`, `Designing`, `Accepted`, `In progress`, `Shipped`, or
`Abandoned`. It reflects the spec's own lifecycle, not how much code exists.

## Numbering

`000` is reserved for the development harness itself — the tooling, conventions,
and gates that all other specs are built through. Product capabilities start at
`001` and are assigned by `spec_init` in creation order. Numbers are permanent:
an abandoned spec keeps its number and is marked `Abandoned` rather than reused,
so that references in commits, ADRs, and review notes never rot.

## Writing Conventions

These apply to every document in `docs/`. They exist because both humans and
agents read these files, and agents follow a document's structure literally.

**Separate WHAT from HOW, strictly.** A spec that names a library has already
foreclosed the design. A design that re-argues the requirements has lost the
thread. When editing, if a sentence feels out of place, it usually belongs in
the sibling document.

**State non-goals explicitly.** An agent given a goal and no boundary will build
outward until stopped. Every non-goal is scope you do not have to review later.

**Make acceptance criteria falsifiable.** "Requests without a valid API key
return 401 and emit no run record" can be tested. "Authentication is secure"
cannot. Number them, and cite the numbers from tests, plans, and reviews.

**Write one fact in one place, then link.** Product scope lives in
`docs/product/`, rationale in `docs/adr/`, structure in `docs/architecture/`.
Restating any of them inside a spec creates a copy that will silently go stale
and then be believed.

**Prefer a table to a list, and a list to a paragraph.** Tables force the missing
column to become visible. A paragraph hides the gap.

**Keep diagrams in fenced `text` blocks.** ASCII diagrams diff cleanly in review
and render everywhere, including inside an agent's context window.

**Say when something was checked and found absent.** "No new layer-graph edges"
is informative; an empty section is ambiguous between "none" and "not
considered".

**Delete the guidance comments as you fill a template in.** A template still
full of `<!-- -->` blocks at review time means the document was scaffolded and
not written.
