# Registry V1 benchmark and acceptance audit

## Running the benchmark

Point `KREP_DATABASE_URL` (role `krep_app`) at a migrated, throwaway database and run:

```bash
uv run python -m benchmarks.run
```

`benchmarks/seed.py` creates a fresh tenant with 10,000 published agents (30% restricted, 10% private, 60% tenant-visible), 300 access policies of the form `token.groups == "gN"`, a 40-group token (`g0`..`g39`), and a bundle fixture (one agent, 4 direct skills, 3 second-level, 3 third-level: depth 3, 10 dependencies). The runner uses 4 concurrent clients with 100 iterations each and calls the service functions in-process (no HTTP layer).

## Results

Local Docker, PostgreSQL 17 (`pgvector/pgvector:pg17`), one run.

| What | mean ms | p95 ms | p95 target ms | met |
| --- | --- | --- | --- | --- |
| search, one word | 14.3 | 16.9 | 100.0 | yes |
| search, three words | 14.6 | 16.4 | 100.0 | yes |
| policy save, 100-node rule | 2.4 | 2.9 | 100.0 | yes |
| bundle, depth 3, 10 deps | 11.7 | 15.7 | 30.0 | yes |

All p95 targets from spec section 12 are met.

## EXPLAIN (ANALYZE, BUFFERS) of the one-word search

Captured with the 300 seeded policies, before the policy-save phase.

```text
Limit  (cost=10.72..10.73 rows=2 width=24) (actual time=9.525..9.528 rows=10 loops=1)
  Buffers: shared hit=573
  CTE sat
    ->  Result  (cost=0.28..4.30 rows=1 width=16) (actual time=0.004..0.436 rows=40 loops=1)
          One-Time Filter: ((NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid = '5a6132a8-4bf0-4ce3-b7f4-03e2f2bbf9e1'::uuid)
          Buffers: shared hit=105
          ->  Index Scan using access_policies_tenant on access_policies p  (cost=0.28..4.30 rows=1 width=16) (actual time=0.003..0.434 rows=40 loops=1)
                Index Cond: (tenant_id = '5a6132a8-4bf0-4ce3-b7f4-03e2f2bbf9e1'::uuid)
                Filter: jsonb_path_match('{"token": {"groups": ["g0", "g1", "g2", "g3", "g4", "g5", "g6", "g7", "g8", "g9", "g10", "g11", "g12", "g13", "g14", "g15", "g16", "g17", "g18", "g19", "g20", "g21", "g22", "g23", "g24", "g25", "g26", "g27", "g28", "g29", "g30", "g31", "g32", "g33", "g34", "g35", "g36", "g37", "g38", "g39"]}, "principal": {}}'::jsonb, compiled_path, '{"tenant_id": "5a6132a8-4bf0-4ce3-b7f4-03e2f2bbf9e1"}'::jsonb, true)
                Rows Removed by Filter: 260
                Buffers: shared hit=105
  CTE visible
    ->  Result  (cost=0.31..6.09 rows=1 width=158) (actual time=0.449..1.792 rows=6407 loops=1)
          One-Time Filter: ((NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid = '5a6132a8-4bf0-4ce3-b7f4-03e2f2bbf9e1'::uuid)
          Buffers: shared hit=573
          ->  Index Scan using registry_tenant_type_status on registry r  (cost=0.31..6.09 rows=1 width=158) (actual time=0.448..1.502 rows=6407 loops=1)
                Index Cond: ((tenant_id = '5a6132a8-4bf0-4ce3-b7f4-03e2f2bbf9e1'::uuid) AND (status = 'published'::text))
                Filter: ((visibility = 'tenant'::text) OR ((visibility = 'private'::text) AND (created_by = 'bench-user'::text)) OR ((visibility = 'restricted'::text) AND (ANY (policy_id = (hashed SubPlan 2).col1))))
                Rows Removed by Filter: 3604
                Buffers: shared hit=573
                SubPlan 2
                  ->  CTE Scan on sat  (cost=0.00..0.02 rows=1 width=16) (actual time=0.004..0.439 rows=40 loops=1)
                        Buffers: shared hit=105
  CTE lex
    ->  WindowAgg  (cost=0.04..0.06 rows=1 width=28) (actual time=2.618..2.626 rows=50 loops=1)
          Buffers: shared hit=573
          ->  Limit  (cost=0.04..0.04 rows=1 width=20) (actual time=2.616..2.619 rows=50 loops=1)
                Buffers: shared hit=573
                ->  Sort  (cost=0.04..0.04 rows=1 width=20) (actual time=2.616..2.617 rows=50 loops=1)
                      Sort Key: (ts_rank_cd(v.search_tsv, '''refund'''::tsquery)) DESC, v.id
                      Sort Method: top-N heapsort  Memory: 30kB
                      Buffers: shared hit=573
                      ->  CTE Scan on visible v  (cost=0.00..0.02 rows=1 width=20) (actual time=0.454..2.599 rows=135 loops=1)
                            Filter: (search_tsv @@ '''refund'''::tsquery)
                            Rows Removed by Filter: 6272
                            Buffers: shared hit=573
  CTE fuzzy
    ->  WindowAgg  (cost=0.04..0.06 rows=1 width=28) (actual time=6.816..6.824 rows=50 loops=1)
          ->  Limit  (cost=0.04..0.04 rows=1 width=20) (actual time=6.816..6.819 rows=50 loops=1)
                ->  Sort  (cost=0.04..0.04 rows=1 width=20) (actual time=6.816..6.817 rows=50 loops=1)
                      Sort Key: (word_similarity('refund'::text, v_1.name)) DESC, v_1.id
                      Sort Method: top-N heapsort  Memory: 30kB
                      ->  CTE Scan on visible v_1  (cost=0.00..0.02 rows=1 width=20) (actual time=0.016..6.800 rows=135 loops=1)
                            Filter: ('refund'::text <% name)
                            Rows Removed by Filter: 6272
  ->  Sort  (cost=0.22..0.22 rows=2 width=24) (actual time=9.525..9.526 rows=10 loops=1)
        Sort Key: (((COALESCE((1.0 / ((60 + lex.rnk))::numeric), '0'::numeric) + COALESCE((1.0 / ((60 + fuzzy.rnk))::numeric), '0'::numeric)))::double precision) DESC, lex_1.id
        Sort Method: top-N heapsort  Memory: 25kB
        Buffers: shared hit=573
        ->  Hash Left Join  (cost=0.13..0.21 rows=2 width=24) (actual time=9.499..9.522 rows=50 loops=1)
              Hash Cond: (lex_1.id = fuzzy.id)
              Buffers: shared hit=573
              ->  Hash Right Join  (cost=0.10..0.12 rows=2 width=24) (actual time=9.488..9.496 rows=50 loops=1)
                    Hash Cond: (lex.id = lex_1.id)
                    Buffers: shared hit=573
                    ->  CTE Scan on lex  (cost=0.00..0.02 rows=1 width=24) (actual time=0.000..0.002 rows=50 loops=1)
                    ->  Hash  (cost=0.07..0.07 rows=2 width=16) (actual time=9.487..9.487 rows=50 loops=1)
                          Buckets: 1024  Batches: 1  Memory Usage: 11kB
                          Buffers: shared hit=573
                          ->  Unique  (cost=0.06..0.07 rows=2 width=16) (actual time=9.472..9.481 rows=50 loops=1)
                                Buffers: shared hit=573
                                ->  Sort  (cost=0.06..0.07 rows=2 width=16) (actual time=9.472..9.475 rows=100 loops=1)
                                      Sort Key: lex_1.id
                                      Sort Method: quicksort  Memory: 25kB
                                      Buffers: shared hit=573
                                      ->  Append  (cost=0.00..0.05 rows=2 width=16) (actual time=2.619..9.463 rows=100 loops=1)
                                            Buffers: shared hit=573
                                            ->  CTE Scan on lex lex_1  (cost=0.00..0.02 rows=1 width=16) (actual time=2.619..2.631 rows=50 loops=1)
                                                  Buffers: shared hit=573
                                            ->  CTE Scan on fuzzy fuzzy_1  (cost=0.00..0.02 rows=1 width=16) (actual time=6.817..6.829 rows=50 loops=1)
              ->  Hash  (cost=0.02..0.02 rows=1 width=24) (actual time=0.006..0.006 rows=50 loops=1)
                    Buckets: 1024  Batches: 1  Memory Usage: 11kB
                    ->  CTE Scan on fuzzy  (cost=0.00..0.02 rows=1 width=24) (actual time=0.000..0.002 rows=50 loops=1)
Planning Time: 0.088 ms
Execution Time: 9.563 ms
```

## Observations

- The first run of the one-word search averaged about 52 ms, against 7.6 ms in spec section 12. The plan showed the planner estimating the `visible` CTE at 1 row (actual 6,407), so it chose nested-loop left joins that re-ran the `lex` and `fuzzy` CTEs once per visible row (`loops=6407`, about 320,000 rows removed by join filter).
- Fixed in `search/engine.py`: `lex` and `fuzzy` are `MATERIALIZED`, and the final select starts from `SELECT id FROM lex UNION SELECT id FROM fuzzy` and left-joins both, instead of joining every visible row. Results are identical; the one-word search now averages about 12 ms and the plan above shows no per-row CTE rescans.
- Bundle resolution measured 3 ms on a fresh database and about 11 ms when the same database already held several seeded tenants (more than 30,000 rows); both are inside the 30 ms target. The numbers above are from the latter.
- Policy evaluation (`sat` CTE) takes well under 1 ms for 300 policies.

## Acceptance test map (spec section 14)

| # | Tests |
| --- | --- |
| 1 | `test_ac1_*` in db/test_rls.py, api/test_registry_endpoints.py, registry/test_links.py |
| 2 | `test_ac2_*` in identity/test_resolve.py |
| 3 | `test_ac3_*` in identity/test_resolve.py |
| 4 | `test_ac4_*` in cli/test_tenant_init.py, cli/test_policy_reset.py, identity/test_caller_permissions.py |
| 5 | `test_ac5_*` in registry/test_resources.py, search/test_registry_search.py, policy/test_semantics_pg.py |
| 6 | `test_ac6_*` in registry/test_resources.py, api/test_search_endpoint.py, search/test_registry_search.py |
| 7 | `test_ac7_*` in search/test_registry_search.py |
| 8 | `test_ac8_*` in search/test_registry_search.py, policy/test_semantics_pg.py |
| 9 | `test_ac9_*` in policy/test_compile_golden.py (rows 1-13), policy/test_parser.py (rows 14-15), policy/test_semantics_pg.py |
| 10 | `test_ac10_*` in policy/test_compile_safety.py, policy/test_semantics_pg.py |
| 11 | `test_ac11_*` in api/test_policies.py |
| 12 | `test_ac12_*` in api/test_policies.py |
| 13 | `test_ac13_*` in api/test_policies.py, policy/test_leaves.py, policy/test_summary.py |
| 14 | `test_ac14_*` in db/test_immutability.py, registry/test_publish.py |
| 15 | `test_ac15_*` in registry/test_prune.py, registry/test_freeze.py |
| 16 | `test_ac16_*` in api/test_registry_endpoints.py, registry/test_versions.py, registry/test_resources.py |
| 17 | `test_ac17_*` in api/test_limits.py, registry/test_prune.py |
| 18 | `test_ac18_*` in registry/test_publish.py |
| 19 | `test_ac19_*` in registry/test_links.py |
| 20 | `test_ac20_*` in registry/test_freeze.py, registry/test_bundle.py |
| 21 | `test_ac21_*` in registry/test_links.py |
| 22 | `test_ac22_*` in registry/test_links.py, registry/test_resources.py |
| 23 | `test_ac23_*` in search/test_registry_search.py |
| 24 | `test_ac24_*` in search/test_synonyms.py, api/test_search_endpoint.py |
| 25 | `test_ac25_*` in search/test_query_builder.py, search/test_registry_search.py |
| 26 | `test_ac26_*` in api/test_search_endpoint.py |
| 27 | `test_ac27_*` in registry/test_new_type.py |
| 28 | `test_ac28_*` in db/test_migrations.py |

Hardening checks (T18 step 4): `tests/e2e/test_hardening.py` covers "every route requires auth" and "no claim, principal, prompt or skill content in logs"; `tests/db/test_rls.py::test_krep_app_has_no_ddl_and_read_only_global_tables` covers `krep_app` being unable to write global tables. The spec section 15 walkthrough (steps 0-11, including the API key plus principal variant) is `tests/e2e/test_walkthrough.py`.
