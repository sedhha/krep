# V2-03 — Secret crypto and organisation auth adapters

Spec: 5.1-5.4, 9.2 (`GET /admin/auth-adapters` schema shape). Acceptance: 3 (adapter side), 5, 18. Pure Python plus one table already created in V2-01.

## Files
- Create: `src/krep/auth/__init__.py`, `adapters.py` (Protocol and registry), `hmac.py`, `crypto.py`, `store.py` (read/write `auth_configs`), `tests/auth/test_crypto.py`, `test_hmac_adapter.py`, `test_registry.py`
- Modify: `src/krep/cli.py` (`krep keys generate`), `src/krep/config.py` (`KREP_ENCRYPTION_KEYS`), `pyproject.toml` (`cryptography`), `.env.example`, `README.md` env table

## Consumes
V2-01 `auth_configs`; V1 `identity/jwt.py` conventions (PyJWT).

## Produces (used by V2-04, V2-05)
- `crypto.py`: `encrypt(plaintext: str) -> tuple[bytes, str]` (ciphertext, key id), `decrypt(ciphertext: bytes, key_id: str) -> str`; Fernet via `MultiFernet`, first key encrypts, all decrypt; startup error when the key list is missing or malformed.
- `adapters.py`: `AuthAdapter` Protocol and `get_adapter(type)`, `list_adapters()` returning JSON Schema (from the pydantic config model) and secret field names.
- `hmac.py`: config model per 5.2 (`algorithms`, `audience`, `issuer`, `user_claim_path`, `allow_principal`; secret >= 32 bytes) and `verify`.
- `store.py`: `save_config(conn, tenant, product, adapter, config, secret, actor) -> dict` (bumps `rev`, encrypts), `load_effective(conn, tenant, product) -> ResolvedConfig | None` (product override else organisation), decrypted verifier cached 60 s by `(config id, rev)`.

## Steps
1. Crypto tests: round trip; wrong key fails; rotation (new primary key prepended, old ciphertext still decrypts, re-save re-encrypts under the new key id); ciphertext differs per call; malformed key list rejected.
2. HMAC tests: valid HS256/384/512; wrong secret, expired, missing `exp`, `alg: none`, RS256 header, algorithm not in config list, wrong `aud`/`iss`, 30 s leeway boundary, weak secret rejected at save (`422 auth_config_invalid`).
3. Adapter registry tests: schema lists secret fields; a fake second adapter registered in the test appears in `list_adapters()` and verifies end to end without core edits (ac18).
4. Secret hygiene: sentinel secret never appears in `repr`, logs, API-shaped dicts or exceptions (ac5 service level); `load_effective` product override vs organisation fallback.
5. Implement.

## Done when
Acceptance 5 (service level) and 18 pass; HMAC verification matrix is green.
