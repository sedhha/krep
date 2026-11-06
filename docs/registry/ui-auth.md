# UI auth spike (V2-08)

Run against a throwaway database (`krep_spike`) with the compose roles, `better-auth@1.7.15`, `next@16.4.4`, `pg@8`.

## Results

| Assumption (spec 3.4) | Result |
| --- | --- |
| Schema `auth` placement via connection search path | Works. `new Pool({ connectionString, options: "-c search_path=auth" })` as `krep_auth`; all five tables (`user`, `session`, `account`, `verification`, `jwks`) land in `auth`, nothing in `public`. |
| Migration CLI | `@better-auth/cli` is deprecated; its last release is 1.4.21. The maintained CLI is the `auth` package (same version as `better-auth`). The 1.4.21 CLI still migrated correctly against the 1.7.15 config, but the task should use `pnpm dlx auth@1.7.15 migrate`. |
| `username` + `admin` + `jwt` together | Work. Sign-up (`/api/auth/sign-up/email` with `username`), username sign-in (`/api/auth/sign-in/username`), `GET /api/auth/token` (JWT from the session cookie) and `GET /api/auth/jwks` all respond. |
| Alembic after Better Auth | `alembic upgrade head` succeeds; `auth_users` view is created by 0009 over `auth."user"`; `krep_app` reads it and gets `permission denied for schema auth` on the table itself. |
| JWKS shape accepted by FastAPI verifier | **Fails with defaults.** Better Auth signs with `EdDSA` (Ed25519, `kty: OKP`); `krep.identity.jwt.ALGORITHMS` has no `EdDSA`, so every login JWT would return `401`. **Decision: add `EdDSA` to `ALGORITHMS`** (one line, `pyjwt[crypto]` already installed, no new dependency; test `test_v2ac1_eddsa_signed_login_jwt_is_accepted`). It widens the shared allow-list for V1 issuers too. ES256 via `jwks.keyPairConfig` was the config-only alternative; verified that the real `verify_token` accepts both. |
| Claim names | Default payload is the whole user record (`name`, `email`, `role`, `banned`, ...) plus `sub`, `iat`, `exp`, `iss`, `aud`. With `definePayload: ({ user }) => ({ username: user.username })` it is `{username, sub, iat, exp, iss, aud}`; `sub` is the Better Auth user id (text), matching `memberships.user_id`. |
| `auth_users` view over generated tables | Columns `id, username, email, name` exist with those names; `krep_owner` reads `auth."user"` through the default privileges in `02-roles-v2.sql`. |

## Other findings

- `docker/initdb/02-roles-v2.sql` already creates `krep_auth` and schema `auth` with the grants the view needs; `docker-compose.yml` needs no change. An already-initialised dev volume (like the current one: roles exist, no `auth` schema) needs `docker compose down -v` or the two statements run once by hand.
- `jwt` plugin `expirationTime` takes a duration string; `${KREP_LOGIN_JWT_TTL_SECONDS}s` works.
- Session cookie: `better-auth.session_token`, `HttpOnly; SameSite=Lax; Path=/`, 7-day max age; `Secure` is added on https base URLs only.
- Better Auth's origin check applies to cookie-bearing requests; a cookieless sign-in with a foreign `Origin` header returned 200 in dev. The proxy therefore enforces its own same-origin check.
- Rate limiting defaults to production only; the config sets `rateLimit.enabled` explicitly.
- Next.js 16 writes an `AGENTS.md` into `ui/` unless `agentRules: false` is set in `next.config.ts`.
- Ban pairing (admin plugin `banUser`) is not exercised in the spike; it is covered by the e2e test.

## Review focus (step 4)

- **JWT refresh:** the proxy asks Better Auth for a token on every request (`auth.api.getToken`), so the forwarded JWT is always fresh; there is no refresh logic. The cost is one signature per proxied call.
- **Cookie flags:** `better-auth.session_token` is `HttpOnly; SameSite=Lax; Path=/`; `Secure` is added when `BETTER_AUTH_URL` is https. Run behind https before any non-local use.
- **CSRF / origin:** the proxy refuses a foreign `Sec-Fetch-Site`/`Origin` and requires one of them on unsafe methods; it compares against the request's own origin, so behind a reverse proxy it should compare with `BETTER_AUTH_URL`. Better Auth routes use `trustedOrigins: [BETTER_AUTH_URL]`, and its origin check only applies to cookie-bearing requests (see above).
- **Open sign-up rate limiting:** `rateLimit.enabled` is explicit. Better Auth keys the limit by the `X-Forwarded-For` header by default, so when the app is reachable directly a client can rotate that header to dodge the limit; the e2e suite uses exactly that to stay under it. The reverse proxy in front must overwrite `X-Forwarded-For`. The storage is in-memory, so limits reset on restart and are per instance.
- **Secrets:** `BETTER_AUTH_SECRET`, database URLs and the platform key are read from the environment only; `auth.ts` fails at start when one is missing.
- **Ban pairing:** `banUser` runs the Better Auth ban and the FastAPI `disable` together and reports any failure, so a retry is always safe (both are idempotent). The e2e test bans through the admin plugin (admin role set in SQL for the test) and the platform key.
