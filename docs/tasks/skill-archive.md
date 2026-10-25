# Skill archive contract (supersedes spec 6 skill spec, 7.5 file limits, 10 `POST /uploads`, 11 skill S3 bucket)

A skill version is one zip in the [agentskills.io format](https://agentskills.io/specification), stored in Postgres. No S3, no presigned upload, no `instructions`/`resources` fields.

## Storage (already in migration 0001)
Content-addressed, deduplicated per tenant:
- `skill_files(tenant_id, content_sha256, size_bytes, content bytea)`, primary key `(tenant_id, content_sha256)`. The database checks that `content_sha256` is lowercase hex, equals `sha256(content)`, and that `size_bytes = octet_length(content)` and is 1..1048576. `STORAGE EXTERNAL`. Rows are never updated.
- `skills(version_id, registry_id, tenant_id, type, content_sha256)` references `skill_files(tenant_id, content_sha256)` with `ON DELETE RESTRICT`: a file referenced by any skill version cannot be deleted, and a skill cannot reference a missing file or another tenant's file.
- Dedupe is per tenant only. The same zip in two tenants is two rows; a global store would let one tenant detect another's uploads and bypass RLS isolation.
- Upload: after validation, `INSERT INTO skill_files ... ON CONFLICT DO NOTHING`, then insert the `skills` row with the hash. Uploading identical bytes twice leaves one `skill_files` row and two `skills` rows. Copying a draft (`from_version`) copies only the `skills` row.
- Orphan cleanup: after any statement that deletes `skills` rows (delete draft, delete version, prune, delete resource), in the same transaction run `DELETE FROM skill_files f WHERE f.tenant_id = :t AND f.content_sha256 = ANY(:hashes) AND NOT EXISTS (SELECT 1 FROM skills s WHERE s.tenant_id = f.tenant_id AND s.content_sha256 = f.content_sha256)`, with `hashes` = the hashes just released. Take `pg_advisory_xact_lock(hashtextextended(:t || ':' || :hash, 0))` for the hash in both upload and cleanup so a concurrent upload cannot lose its file between the insert and the `skills` row.
- Never `SELECT content` except in the archive download endpoint and the bundle's explicit fetch; list, get and search read `skills`, and size comes from `skill_files` without selecting `content`.

## Limits (constants in `registry/skill_archive.py`, not `resource_limits`)
| Limit | Value |
| --- | --- |
| zip size | <= 1 MiB (1,048,576 bytes), matches the DB CHECKs |
| uncompressed total | <= 5 MiB, enforced while reading (never trust `ZipInfo.file_size`) |
| entries | <= 200 |
| `SKILL.md` frontmatter block | <= 16 KB |

## Validation: `validate_skill_archive(data: bytes, slug: str) -> tuple[SkillArchive | None, list[FieldError]]`
Pure function, no database, no network. Field paths start with `archive`.
1. `len(data)` in 1..1 MiB and the bytes start with a zip signature; `zipfile` opens it and the central directory is readable; otherwise `archive: not a valid zip`.
2. Entries: no absolute paths, no `..` segments, no backslashes or drive letters, no NUL, no duplicate names (case-insensitive), no symlinks (unix mode `S_IFLNK`), no encrypted entries (flag bit 0), count <= 200; directory entries ignored.
3. Zip-bomb guard: stream-read each entry with a running total capped at 5 MiB; exceeding it fails the whole archive.
4. Layout: exactly one top-level directory, and it contains `SKILL.md` (case-sensitive) directly. Directory name must equal the frontmatter `name` and the registry `slug` (agentskills: name must match the parent directory).
5. `SKILL.md` starts with a `---` YAML frontmatter block closed by `---`; parsed with `yaml.safe_load` only; result must be a mapping.
6. Frontmatter fields per agentskills: `name` 1-64 chars, `^[a-z0-9]+(-[a-z0-9]+)*$`; `description` 1-1024 chars non-empty; `license` string (optional); `compatibility` 1-500 chars (optional); `metadata` mapping of string to string (optional); `allowed-tools` string (optional). Unknown keys are ignored, not stored.
7. A `SKILL.md` body over 500 lines is a `warnings` entry in the response, not an error.
8. Returns `SkillArchive(content_sha256, size_bytes, name, description)`; callers never receive parsed frontmatter beyond that (nothing is stored).

## Transport
- `POST /v1/registry` with `type: skill`: `multipart/form-data`, part `metadata` (the 7.2 JSON without `spec`), part `archive` (`application/zip`). A JSON body with `spec` for a skill is `422 validation_failed` (`spec: skills take an archive`).
- `POST /v1/registry/{id}/versions` for a skill with `from_version`/current copies the `skills` row of the source version (the file is shared by hash); a multipart body with `archive` instead creates the draft from the upload.
- `PUT /v1/registry/{id}/versions/{n}` for a skill: multipart with `archive`; `409 version_immutable` if published.
- `GET /v1/registry/{id}/versions/{n}/archive`: same visibility as version get; `200 application/zip`, `ETag: "<content_sha256>"`, `Cache-Control: private, no-store`.
- If `description` is omitted at create, it defaults to the frontmatter `description`.
- `POST /v1/uploads` is removed from the API.

## Content hash and bundle
- Skill content hash = `sha256(canonical_json({"type": "skill", "spec": {"content_sha256": <hex>}}))`; identical archives hash identically.
- A skill dependency in a bundle returns `spec: {content_sha256, size_bytes, archive_path}` where `archive_path` is the relative download path above; zip bytes are never inlined in JSON.

## Logging
Never log archive bytes, file names inside the archive, or frontmatter values (conventions already forbid skill content). Log only tenant, route, status, size, and `content_sha256`.

## Decisions to confirm
1. One top-level directory named after the skill (vs `SKILL.md` at the zip root).
2. `multipart/form-data` for skill create/edit (vs a separate `PUT .../archive` after creating metadata, which would need a nullable archive on drafts).
3. Frontmatter is validated and discarded, not stored (no `frontmatter jsonb`).
