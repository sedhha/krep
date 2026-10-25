# T10 — Spec validators and limits

Spec: 5.3 (validator seam), 6, 7.5, 10 (`GET /limits`, `GET /registry/types`). Skills follow [skill-archive.md](skill-archive.md), not spec 6's skill spec. Acceptance: 16 (limit lookup), 17.

## Files
- Create: `src/krep/registry/specs.py`, `src/krep/registry/skill_archive.py`, `src/krep/registry/limits.py`, `src/krep/api/limits.py`, `tests/registry/test_specs.py`, `tests/registry/test_skill_archive.py`, `test_limits.py`
- Modify: `pyproject.toml` (a CEL syntax-check library; confirm choice in the PR description; `pyyaml` for SKILL.md frontmatter, `safe_load` only)

## Produces (used by T11, T12, T14, T15, T17)
- `specs.py`: `VALIDATORS: dict[str, Callable[[dict], list[FieldError]]]` keyed by type; `validate_spec(type: str, spec: dict) -> list[FieldError]`; `validate_resource_fields(name, slug, description, tags, visibility, policy_id, meta) -> list[FieldError]`; `canonical_json(obj) -> bytes`; `content_hash(type: str, spec: dict) -> str`. Skills have no JSON spec validator: `VALIDATORS` holds agent only; skill specs are `{"content_sha256": ...}` produced from a validated archive.
- `skill_archive.py`: `validate_skill_archive(data: bytes, slug: str) -> tuple[SkillArchive | None, list[FieldError]]` and the limit constants, exactly per skill-archive.md.
- `limits.py`: `async def get_limit(conn, *, tenant_id, key, resource_type=None, product=None, org=None) -> int` implementing the spec 7.5 query exactly; `async def effective_limits(conn, tenant_id) -> dict`.
- `GET /v1/limits`, `GET /v1/registry/types`.

## Steps
1. Tests: agent spec valid example from spec 6 passes; invalid JSON Schema (Draft 2020-12) in `input_schema`/`output_schema`, unparsable CEL in `hitl_rules[].when`, missing `model`/`system_prompt` fail with field paths; `tool_refs` unvalidated; tags/slug/name/meta (16 KB) rules from the 6 table.
2. Skill archive tests (`test_skill_archive.py`, archives built in memory with `zipfile`, no files on disk): valid minimal archive passes and returns hash/size/name/description; hash equals `hashlib.sha256(data)`; each failure returns an `archive...` field error: not a zip, empty, > 1 MiB, missing `SKILL.md`, `SKILL.md` not directly under the single top-level dir, two top-level dirs, directory name != frontmatter `name`, frontmatter `name` != slug, no frontmatter, unclosed frontmatter, non-mapping YAML, `name` uppercase/leading hyphen/`--`/65 chars, empty or 1025-char `description`, `compatibility` 501 chars, non-string `metadata` value, `allowed-tools` not a string, `..` path, absolute path, backslash path, duplicate (case-insensitive) names, symlink entry, encrypted entry, 201 entries, uncompressed total > 5 MiB with a tiny compressed size (zip bomb, including an entry whose declared `file_size` lies), frontmatter block > 16 KB, YAML with a Python object tag rejected by `safe_load`. A body over 500 lines yields a warning, not an error. Unknown frontmatter keys are accepted.
3. Content hash: identical specs with different key order hash identically; any change differs; hash is sha256 hex of canonical JSON of `{type, spec}`; for a skill the spec is `{"content_sha256": <hex>}`.
4. Limits: most specific scope wins, type-specific beats type-agnostic (acceptance 17 with a tenant row inserted via owner connection); `GET /v1/limits` returns effective values for the caller's tenant.
5. Implement.

## Done when
Validator, skill archive, hash and limit tests pass.
