# V2-06 — Resource API scope, cross-tenant links, global approval

Spec: 4.3, 4.5, 6, 6.1, 9.2 (`PUT /admin/registry/{id}/scope`), 9.4. Acceptance: 11, 12, 13, 15.

## Files
- Create: `src/krep/registry/scope.py`, `tests/registry/test_cross_tenant_links.py`, `test_global_approval.py`, `tests/api/test_scope_api.py`
- Modify: `src/krep/registry/links.py`, `prune.py`, `publish.py`, `bundle.py`, `resources.py`, `src/krep/api/registry.py`, `src/krep/api/links.py`, `src/krep/api/admin.py`, `migrations/versions/0011_referrer_function.py` (`SECURITY DEFINER` function returning cross-tenant referrer counts and, for platform callers, organisation slugs)

## Consumes
V2-02 scope and policy slots; V2-04 platform identity; V2-05 audit; V1 links, prune (`version_in_use`), bundle.

## Produces (used by V2-07 and the UI)
- `scope.py`: `set_scope(conn, caller, resource_id, scope, product)` implementing 4.5, including the platform-only move to `global` (transaction flag, published resource required, audit row) and demotion blocked with `409 resource_in_use` while other organisations depend on it.
- Links: scope-pair validation from `link_scope_rules` (`422 link_scope_not_allowed`), same-product rule for product -> product, `manage` on source, `read` on target (cross-tenant read through global rules), frozen `registry_version_deps` rows in the source tenant pointing at global versions.
- `prune.py`/delete: `version_in_use` and resource delete consult the referrer function so cross-tenant referrers block with `409 version_in_use`/`409 resource_in_use`; referrer identities only for platform callers, counts otherwise.
- `PUT /v1/admin/registry/{id}/scope`; `POST /registry/{id}/links` accepts targets in global scope.

## Steps
1. Tests (ac15): every allowed pair works; global -> org/product, cross-product product -> product return `422 link_scope_not_allowed`; flipping a seed row in the test changes the verdict for org -> global with no code change; the rule table CHECK still refuses `global -> org` set to allowed.
2. Cross-tenant lifecycle: an org agent linked to a global skill publishes with a frozen dependency, bundles for any caller of that organisation, is unaffected by a later global skill version (V1 acceptance 20 across tenants), and blocks pruning and deleting the global skill version/resource.
3. Global approval (ac12, ac13): org admin gets `403 scope_not_allowed` setting `global`; platform admin succeeds with an audit row; unpublished resource rejected; owner can demote when unreferenced; another organisation cannot write, archive or delete the global resource.
4. Review-focus: referrer counts leaking tenant identity to non-platform callers, pinned versions of a global skill, global resource archived while referenced, concurrent link creation and demotion (lock ordering).
5. Implement.

## Done when
Acceptance 12, 13 and 15 pass; V1 links, prune and bundle suites stay green.
