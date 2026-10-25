# T16 — Bundle resolution

Spec: 7.9, 8.1, 10. Skill dependencies use the shape in [skill-archive.md](skill-archive.md). Acceptance: 20 (bundle side), 6 (404), walkthrough steps 8-11.

## Files
- Create: `src/krep/registry/bundle.py`, `tests/registry/test_bundle.py`
- Modify: `src/krep/api/registry.py` (add `GET /v1/registry/{id}/bundle?version=`)

## Consumes
T11 `get_visible`; T15 frozen `registry_version_deps`, `list_links`.

## Produces
- `bundle.py`: `async def resolve_bundle(conn, caller, resource_id, version: int | None) -> dict` returning `{root, dependencies[]}` as in 7.9.

## Steps
1. Tests: published root returns frozen deps with `auto_load` only, recursive to depth 5 (6-deep chain truncated at 5), cycle-safe through `UNION`; version omitted = current; skill v5 published later does not change agent v7's bundle (acceptance 20).
2. Draft root: resolves live accepted links in the same shape; pending links excluded.
3. Visibility: invisible root -> 404; dependency included even when the caller could not discover the skill (publisher vouched); archived dependency still resolves.
4. Review-focus: version not found, `version` not an integer, root with zero deps, duplicate dependency via two paths appears once.
5. Skill dependencies carry `spec: {content_sha256, size_bytes, archive_path}` (size from `skill_files.size_bytes`) and never inline zip bytes; the bundle query never selects `skill_files.content`.
6. Implement.

## Done when
Bundle tests pass and the depth-3/10-dep case is ready for T18's timing check.
