# T12 — Versions, publish, retention, current

Spec: 5.1, 6 (content hash), 7.3, 7.4, 7.5, 10. Acceptance: 15, 16, 17, 18, 14 (service level). Link freezing arrives in T15; leave one call-site hook in publish.

## Files
- Create: `src/krep/registry/versions.py`, `publish.py`, `prune.py`, `src/krep/api/versions.py`, `tests/registry/test_versions.py`, `test_publish.py`, `test_prune.py`
- Modify: `src/krep/api/__init__.py`

## Consumes
T11 `lock_resource`, `can_edit`; T10 `validate_spec`, `content_hash`, `get_limit`.

## Produces (used by T15, T16)
- `versions.py`: `create_draft(conn, caller, resource_id, from_version: int | None) -> dict`; `replace_draft(conn, caller, resource_id, n, spec) -> dict` (`409 version_immutable` if published); `delete_version(...)`.
- `prune.py`: `async def version_in_use(conn, version_id) -> list[Referrer]` (links pins and version deps now; hook for runs).
- `publish.py`: `async def publish(conn, caller, resource_id, n, make_current: bool = True) -> dict`; calls `freeze_dependencies(conn, version_id)` which is a no-op stub replaced in T15.
- `POST /v1/registry/{id}/current` repoints current (published and retained only); version list/get/PUT/DELETE/publish endpoints.

## Steps
1. Tests: new draft copies per 7.3 rules; `next_version` increments; draft count toward cap.
2. Publish tests per 7.4 order: locks resource; non-draft rejected; sets `status`, `published_at`, `content_hash`; sets `current_version_id` and `registry.status`; `make_current=false` leaves current; publishing identical spec reports "no changes since vN" in the response.
3. Retention (acceptance 15): 11th publish deletes oldest non-current published version when unreferenced; pinned by a link or depended on by another version -> `409 version_in_use` with the `referenced_by` list and nothing changed (insert referrers via owner connection until T15). Concurrency: two parallel publishes of the same resource serialise.
4. Current (acceptance 18): repoint to older retained version works; non-published or pruned fails; deleting the current version -> `409 version_is_current`.
5. Review-focus: publish a draft whose spec went invalid; publish on archived resource; editing a draft while another request publishes it.
6. Implement.

## Done when
Acceptance 14-18 pass at the service/API level.
