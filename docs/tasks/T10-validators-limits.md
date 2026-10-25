# T10 — Spec validators and limits

Spec: 5.3 (validator seam), 6, 7.5, 10 (`GET /limits`, `GET /registry/types`). Acceptance: 16 (limit lookup), 17.

## Files
- Create: `src/krep/registry/specs.py`, `src/krep/registry/limits.py`, `src/krep/api/limits.py`, `tests/registry/test_specs.py`, `test_limits.py`
- Modify: `pyproject.toml` (a CEL syntax-check library; confirm choice in the PR description)

## Produces (used by T11, T12, T14, T15, T17)
- `specs.py`: `VALIDATORS: dict[str, Callable[[dict], list[FieldError]]]` keyed by type; `validate_spec(type: str, spec: dict) -> list[FieldError]`; `validate_resource_fields(name, slug, description, tags, visibility, policy_id, meta) -> list[FieldError]`; `canonical_json(obj) -> bytes`; `content_hash(type: str, spec: dict) -> str`.
- `limits.py`: `async def get_limit(conn, *, tenant_id, key, resource_type=None, product=None, org=None) -> int` implementing the spec 7.5 query exactly; `async def effective_limits(conn, tenant_id) -> dict`.
- `GET /v1/limits`, `GET /v1/registry/types`.

## Steps
1. Tests: agent spec valid example from spec 6 passes; invalid JSON Schema (Draft 2020-12) in `input_schema`/`output_schema`, unparsable CEL in `hitl_rules[].when`, missing `model`/`system_prompt` fail with field paths; skill spec `resources` rules (<= 20, text <= 64 KB, `url` must be https, file entries need `s3_key`, `size`, `content_type`); `tool_refs` unvalidated; tags/slug/name/meta (16 KB) rules from the 6 table.
2. Content hash: identical specs with different key order hash identically; any change differs; hash is sha256 hex of canonical JSON of `{type, spec}`.
3. Limits: most specific scope wins, type-specific beats type-agnostic (acceptance 17 with a tenant row inserted via owner connection); `GET /v1/limits` returns effective values for the caller's tenant.
4. Implement.

## Done when
Validator, hash and limit tests pass.
