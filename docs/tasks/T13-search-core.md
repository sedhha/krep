# T13 — Search query builder and registry_search()

Spec: 8.1, 8.4, 9.2, 9.3, 9.5. Acceptance: 5, 6, 7, 8, 23, 25. Synonyms are a seam here (empty expansion); T14 fills it.

## Files
- Create: `src/krep/search/query.py`, `src/krep/search/engine.py`, `tests/search/test_query_builder.py`, `test_registry_search.py`
- Modify: none outside `search/`

## Consumes
T11 resources (as fixtures via owner connection or the service), T05 `evaluate`-equivalent SQL (`sat` CTE inline), T06 `tenant_transaction`.

## Produces (used by T14)
- `query.py`: `normalise(q: str) -> str` (spec 9.2 step 1); `expand(q_norm: str, groups: list[list[str]]) -> list[str]` (symmetric, non-transitive, <= 30 terms); `build_tsquery(terms: list[str]) -> str | None`.
- `engine.py`: `async def registry_search(conn, caller, *, q, type=None, tags=None, limit=10, offset=0, groups=()) -> list[SearchHit]` sets `pg_trgm.word_similarity_threshold`, runs the 9.3 query, hydrates in a second query; empty `q` lists visible rows by `updated_at desc`.

## Steps
1. Builder tests: normalisation (symbols, case, 12-token cap, 100-char cap); acceptance 25 inputs (`refund | ) & !`, `'"; --`, only stop words) never raise and return a list.
2. Search tests: visibility matrix in search results; hidden policy-restricted rows absent; acceptance 7 (500 agents, 20 visible, 12 match, pages of 10 and 2); acceptance 8 (policy that errors at evaluation -> hidden, request succeeds); archived/draft rows never returned.
3. Quality tests (acceptance 23): `refunds`, `refnd`, `money back returned` ranking per 9.2 table.
4. Review-focus: `type` filter for unknown type, `tags` with unknown tag, `limit`/`offset` bounds, `offset+limit` beyond branch depth, a private resource of another user in the same tenant.
5. Implement.

## Done when
Acceptance 5-8, 23, 25 pass for the engine.
