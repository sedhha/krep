# V2-12 — End-to-end walkthrough, dev tooling and docs

Spec: 12, 14 (all), 15. Acceptance: 19 plus a final pass over 1-18.

## Files
- Create: `ui/tests/e2e/walkthrough.spec.ts`, `src/krep/devtools.py` (`krep dev-token`), `tests/cli/test_dev_token.py`, `docs/registry/v2-acceptance-audit.md`
- Modify: `src/krep/api/main.py` (`KREP_ENABLE_DOCS` mounts `/docs` and `/openapi.json`, default off), `src/krep/cli.py`, `README.md` (V2 run, test and setup sections), `docs/tasks/v2/progress.md`

## Consumes
All previous V2 tasks.

## Produces
- Walkthrough test following spec 14 test 19 end to end: two users sign up, first is granted platform admin by CLI, creates an organisation with the second as admin, who adds a product, an HMAC auth config, a policy, an organisation-level and a product-level agent, links to a platform global skill, and verifies visibility from organisation-level and product-selected sessions.
- `krep dev-token --org <slug> --claims '<json>'`: mints a JWT from the organisation's HMAC secret; refuses unless `KREP_ENV=local`.
- `KREP_ENABLE_DOCS` flag (off by default; tests assert `404` when off).
- Acceptance audit: a table mapping each of the 19 V2 tests and the 28 V1 tests to the test names that prove them, with any gaps called out.

## Steps
1. Tests first: dev-token behaviour (local only, claims, expiry), docs flag on/off, walkthrough skeleton failing for missing pieces.
2. Run the full backend suite, V1 benchmark and the Playwright suite; record results in the audit file.
3. Review-focus: README steps run from a clean checkout in the order given in spec 12; no endpoint reachable without a credential except sign-in/sign-up routes.
4. Implement.

## Done when
Full backend and UI suites green, benchmark targets met, audit file shows no unmapped acceptance test.

## Flag
Security and Legal reviews (spec 15) are not part of this task; list them as open items in the audit file.
