# V2-09 — Platform console

Spec: 3.3, 3.5, 7, 9.2, 10 (platform console). Acceptance: 6 (UI side), 16 (UI side), 19 (first half).

## Files
- Create: `ui/src/app/platform/layout.tsx`, `organizations/page.tsx`, `organizations/new/page.tsx` (wizard), `organizations/[id]/page.tsx`, `users/page.tsx`, `audit/page.tsx`, `ui/src/components/ui/*` (shadcn primitives used), `ui/src/components/AdapterForm.tsx` (renders from JSON Schema), `ui/tests/e2e/platform.spec.ts`, `ui/tests/unit/AdapterForm.test.tsx`
- Modify: `ui/src/lib/api.ts` (admin client)

## Consumes
V2-05 platform routes, V2-07 lifecycle routes, V2-08 app shell and Better Auth `admin` plugin.

## Produces
- Platform area visible only when `GET /v1/me` says `is_platform_admin`.
- Organisation list and create wizard (details, first admin by username, optional auth config rendered from `GET /admin/auth-adapters`, capability rules defaulted from spec 3.6); detail page with suspend/activate, schedule/cancel delete (grace input bounded 1-90), legal hold, purge blockers, member attach/detach.
- Users page (Better Auth admin plugin): list, create, ban/unban (with deny-list pairing), reset password, grant/revoke platform admin, delete orphan accounts.
- Audit log page.

## Steps
1. Unit tests: `AdapterForm` renders fields and write-only secret inputs from a schema, validation messages from `422 auth_config_invalid`.
2. E2E: a non-admin cannot reach `/platform` and the API still refuses; platform admin creates an organisation with its first admin and an HMAC config, sees `secret_set` but never the secret; suspend blocks that organisation's user immediately; schedule delete shows the date and blockers; legal hold disables purge; ban pairing works from the UI.
3. Review-focus: secret never in DOM, network responses, or Playwright traces; destructive actions need confirmation and show the audit row afterwards.
4. Implement.

## Done when
E2E and unit tests pass, lint and typecheck clean, platform admin can onboard and hand over an organisation entirely from the UI.
