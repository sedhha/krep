# V2-02 — Policy-only access, scope and global read

Spec: 4.1, 4.2, 4.3, 4.4, 4.5, 9.4 (registry body shape). Acceptance: 9, 10, 11, 12 (service level, without the platform route), 13, 14, 17.

## Files
- Create: `migrations/versions/0010_drop_visibility.py`, `src/krep/registry/policies.py` (attach/replace/list `registry_policies`), `tests/registry/test_policy_slots.py`, `test_scope.py`, `tests/search/test_scope_search.py`
- Modify: `src/krep/registry/resources.py`, `specs.py`, `src/krep/search/engine.py`, `src/krep/api/registry.py`, `src/krep/db/models.py`, `src/krep/policy/store.py`, `src/krep/api/policies.py`, `src/krep/cli.py`, `benchmarks/seed.py`, and the V1 tests listed by `grep -rlE "visibility|policy_id" tests` (update only those references)

## Consumes
V2-01 schema; V1 `evaluate`, `can_edit`, `Caller`.

## Produces (used by V2-04, V2-06)
- `policies.py`: `set_policies(conn, caller, resource_id, action, policy_ids)` (max 10 per action, same-tenant policies only, `open-to-all` allowed), `list_policies(conn, resource_id)`.
- `Caller` gains `product_id: UUID | None`; discovery and get-by-id use the 4.2 predicate (scope, product, `registry_policies`, `sat` including policies referenced by global resources, creator and admin branches); management checks use `manage` policies plus `registry-writers`.
- Scope editing per 4.5: `product` <-> `org`; `global` accepted only when the transaction carries `app.platform_admin = on`; demoting a global resource with other-organisation referrers returns `409 resource_in_use` (referrer check hook; real data arrives in V2-06).
- Create/patch bodies take `scope`, `product`, `policies: {"read": [...], "manage": [...]}`; `visibility`/`policy_id` removed everywhere and dropped in `0010`.

## Steps
1. Tests first, written against the new API: no read policy -> invisible to others, visible to creator and admin (ac9); several read policies OR (ac10); `open-to-all` at org/product/global reach, restricted global policy evaluated against the caller's own token (ac11); scope changes and `403 scope_not_allowed` without the platform flag (ac12); other tenant cannot write a global resource (ac13); `manage` policy grants edit, read-only caller cannot, capability policies fail closed (ac14).
2. Update V1 tests that used `visibility`/`policy_id` to the new shape and run the whole V1 suite (ac17).
3. Review-focus: global resource whose policy is deleted or errors; product-scoped resource requested without `X-Product`; `sat` cost with global policies (rerun the benchmark and keep the p95 targets).
4. Implement, then add revision `0010` dropping the old columns.

## Done when
Acceptance 9-14 pass at service/API level, V1 suite green after the migration, benchmark targets still met.
