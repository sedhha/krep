# T17 — Uploads and skill resources

Spec: 6 (skill resources, limits), 11 (S3), 10 (`POST /uploads`). Acceptance: covers the file-resource part of validators; no numbered acceptance test.

## Files
- Create: `src/krep/uploads/s3.py`, `src/krep/api/uploads.py`, `tests/uploads/test_uploads.py`
- Modify: `pyproject.toml` (boto3), `src/krep/config.py` (bucket name, region, KMS key id), `src/krep/registry/specs.py` (file resources must reference a key under the caller's tenant prefix), `.env.example`

## Consumes
T07 `require_write`, T10 skill validator.

## Produces
- `s3.py`: `def presign_put(tenant_id: UUID, filename: str, content_type: str, size: int) -> tuple[str, str]` returning `(upload_url, s3_key)`; key prefix is `<tenant_id>/skills/`; expiry 300 s; SSE-KMS headers signed in; size capped at 10 MB.
- `POST /v1/uploads` -> `{upload_url, s3_key}`.

## Steps
1. Tests with a stubbed boto3 client (no network): key starts with the caller's tenant id, expiry 300, SSE-KMS and content-type signed, > 10 MB rejected (`422`), path traversal or odd filenames sanitised.
2. Skill validator tests: a `file` resource whose `s3_key` is under another tenant's prefix is rejected with a field error.
3. Implement; the bucket itself (private, block public access, SSE-KMS) is infrastructure and out of scope here; note the required settings in the README for infra to match.

## Done when
Tests pass without AWS credentials.

## Flag
Bucket creation belongs to Terraform (private, block public access, SSE-KMS); not part of this repo's task.
