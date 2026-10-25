# T17 — Skill archive upload and download

Contract: [skill-archive.md](skill-archive.md). Replaces the S3 upload design. Acceptance: no numbered test; covers the skill-specific part of validators and endpoints.

## Files
- Create: `src/krep/api/skill_archive.py` (multipart parsing and archive download route helpers), `tests/api/test_skill_archive_endpoints.py`
- Modify: `src/krep/api/registry.py`, `src/krep/api/versions.py` (route skill create/edit through multipart), `pyproject.toml` (`python-multipart`), `.env.example` (none expected)

## Consumes
T07 `require_write`, T10 `validate_skill_archive`, T11 `create_resource`, T12 `create_draft` / `replace_draft`.

## Produces
- `async def read_archive_part(request) -> bytes`: reads the multipart `archive` part with a hard 1 MiB + 1 byte cap while streaming, so an oversized body is rejected with `413`/`422` before it is buffered in full.
- Skill create, draft create and draft replace wired to `validate_skill_archive` and the `skills` + `skill_files` writes in one transaction; archive download route.

## Steps
1. Tests (real Postgres through the app, in-memory zips): create-with-archive returns the 7.2 shape and stores `content_sha256`/`size_bytes` that match the bytes; stored `skill_files.content` equals the upload; uploading the same zip twice (two skills, same tenant) leaves one `skill_files` row and two `skills` rows, the same zip from another tenant is a separate row; oversized body (> 1 MiB) is rejected without a row written; invalid archive returns the T10 field errors with nothing written; missing `archive` part or JSON `spec` for a skill is `422`; replace-draft is atomic (old archive survives a bad upload); a published version rejects replace with `409 version_immutable`.
2. Download: returns exact bytes, `application/zip`, `ETag: "<sha256>"`, `Cache-Control: private, no-store`; hidden resource 404 (never 403); another tenant's version id 404 (RLS); an agent version id on the archive route 404.
3. Hardening: logs for a failing upload contain no archive bytes, entry names or frontmatter values (sentinel test, as in T18); no endpoint is reachable without auth.
4. Implement.

## Done when
Tests pass with no AWS dependency anywhere in the project.

## Flag
Nothing is stored outside Postgres in V1. If skills outgrow the 1 MiB cap later, add an `s3_key` column in a new revision and keep this API contract.
