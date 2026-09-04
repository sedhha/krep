# Architectural Decision Records

ADRs capture durable architectural choices and the cost accepted in making them.
They exist so that a future reader can reconstruct not just what was decided but
what was believed at the time.

An ADR is required for any Level 3 change — see
[`docs/WORKFLOW.md`](../WORKFLOW.md) — and specifically for any change to the
layer graph in [`docs/architecture/overview.md`](../architecture/overview.md).

`make spec name=<slug> level=3` stubs the next-numbered record from
[`docs/specs/_templates/adr.md`](../specs/_templates/adr.md). To write one by
hand, use the next four-digit sequence number and a short kebab-case title.

Statuses are `Proposed`, `Accepted`, `Superseded`, and `Retired`. Do not rewrite
an accepted decision to change its meaning: supersede it with a new ADR and mark
the old one `Superseded` with a link. Every ADR states its negative
consequences — a record with only positives is marketing.

## Records

| # | Decision | Status |
| - | -------- | ------ |
| [0001](0001-swagger-setup.md) | FastAPI Swagger setup | Proposed |
