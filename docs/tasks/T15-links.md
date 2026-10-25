# T15 — Links

Spec: 5.3, 7.8, 7.4 step 4, 7.7, 10. Acceptance: 19, 20, 21, 22, 27.

## Files
- Create: `src/krep/registry/links.py`, `src/krep/api/links.py`, `tests/registry/test_links.py`, `test_freeze.py`, `test_new_type.py`
- Modify: `src/krep/registry/publish.py` (replace the `freeze_dependencies` stub), `src/krep/api/__init__.py`

## Consumes
T12 `publish`, `version_in_use`; T11 `can_edit`, `lock_resource`.

## Produces (used by T16)
- `links.py`: `create_link(conn, caller, resource_id, other_id, relation, direction, pinned_version, auto_load) -> dict`; `accept_link`, `reject_link`, `delete_link`; `list_links(conn, caller, resource_id, direction, status)`; `async def freeze_dependencies(conn, version_id) -> None` writing `registry_version_deps`.
- Endpoints: `POST/GET /v1/registry/{id}/links`, `POST /v1/links/{id}/accept|reject`, `DELETE /v1/links/{id}`.

## Steps
1. Rule tests: pair not in `link_rules` -> `422 link_not_allowed`; `auto_load=true` rejected when not allowed; archived or cross-tenant target rejected; creator needs write on the origin side.
2. Acceptance tests (19): skill-initiated link on another's agent is `pending` with `accept_by`/`waiting_on`, ignored by freeze and bundle, active after accept; reject keeps it out. Cycle (21): `422 link_cycle` through accepted links of any relation.
3. Freeze (20): publishing agent v7 writes deps to skill current v4; later skill v5 publish leaves v7 deps untouched; unpinned vs pinned; unpublished target -> `422 dependency_unpublished`; version prune blocked by these deps (re-check acceptance 15 with real referrers).
4. Acceptance 22: delete skill with inbound links -> `409 resource_in_use` with referrers.
5. Acceptance 27: add a throwaway `tool` type through a test-only migration/SQL per 5.3 and create, version, publish and search it with no change to registry, search or policy code.
6. Implement.

## Done when
Acceptance 19-22 and 27 pass.
