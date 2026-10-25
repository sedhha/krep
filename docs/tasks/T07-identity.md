# T07 — Identity: JWT, API key, principal, caller

Spec: 4.1-4.3, 5 (`token_issuers`, `api_keys`), 17 items 6-8. Acceptance: 2, 3, 4.

## Files
- Create: `src/krep/identity/jwt.py`, `resolve.py`, `principal.py`, `src/krep/api/deps.py`, `tests/identity/test_jwt.py`, `test_resolve.py`, `test_principal.py`, `test_caller_permissions.py`

## Consumes
T05 `evaluate(conn, compiled_path, doc, tenant_id) -> bool`; T06 `tenant_transaction`, `ApiError`.

## Produces (used by T08-T17)
- `principal.py`: `decode_principal(header: str | None) -> dict | None` (base64url JSON object <= 4 KB, `id` string required else `ApiError(400, "principal_id_required")`).
- `jwt.py`: `async def verify_token(token: str, issuer_row) -> dict` with a JWKS cache (TTL-bounded, refetch on unknown `kid`, https only).
- `resolve.py`: `@dataclass class Caller: tenant_id: UUID; user_id: str; doc: dict; can_write: bool; can_admin: bool`; `async def resolve_caller(pool, headers) -> Caller` handling mode A user JWT, B machine JWT (`client:<sub>` user when no principal), C `X-API-Key` (sha256 lookup, revoked keys rejected).
- `api/deps.py`: FastAPI dependencies `get_caller`, `require_write`, `require_admin` (403 `forbidden`), and a `db` dependency yielding a tenant transaction for the caller.

## Steps
1. Tests with a locally generated RSA key and fake JWKS: fixed-tenant issuer and `tenant_claim_path` issuer both resolve (acceptance 2); unknown issuer, wrong audience, expired, disabled issuer, `alg=none`, non-https `jwks_uri` -> `401 unauthenticated`.
2. Principal tests (acceptance 3): honored for `allow_principal` B/C; ignored for mode A; missing `id` -> 400; oversize or non-object -> 400.
3. Permission tests (acceptance 4): no reserved policies -> nobody writes or administers; after inserting them (owner connection) the rules grant exactly the described callers; `can_write = can_admin or writers`.
4. Review-focus: tenant claim missing or not a UUID; token with `sub` missing; api key for revoked key; `X-Principal` with invalid base64.
5. Implement.

## Done when
Tests pass; no endpoint exists yet beyond a health probe, but the dependencies are exercised through a test-only route.
