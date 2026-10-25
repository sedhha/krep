# T18 — Benchmark, hardening, end-to-end walkthrough

Spec: 12, 15, 14 (full sweep), 11. Acceptance: all remaining; 1-28 verified present.

## Files
- Create: `benchmarks/seed.py`, `benchmarks/run.py`, `tests/e2e/test_walkthrough.py`, `docs/registry/benchmark.md`
- Modify: `README.md` (run, migrate, test, env var names)

## Steps
1. End-to-end test of the spec 15 walkthrough (steps 0-11), including the API-key + principal variant.
2. Coverage audit: map acceptance tests 1-28 to test names in `docs/registry/benchmark.md` or a short table in progress.md; add any missing test.
3. Benchmark seed (10,000 resources, 30% restricted, 300 policies, 40-group token) and runner measuring search, policy save (100-node rule) and bundle (depth 3, 10 deps) p95 against the 12 targets; attach `EXPLAIN (ANALYZE, BUFFERS)` of the search query.
4. Hardening checks: no claim, principal, prompt or skill content in logs (sentinel test); every route requires auth; `krep_app` cannot write global tables.

## Done when
All 28 acceptance tests present and green; p95 targets met or deviations recorded with the EXPLAIN output.
