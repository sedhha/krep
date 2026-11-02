# V2-10 — Organisation console: products, auth, members, policies

Spec: 3.5, 3.6, 5, 8.6 and 8.2 of V1 (policy management), 9.3, 10 (organisation console, rule builder). Acceptance: 7 (UI side), 10 (UI side), 19 (second half). Starts with a spike.

## Files
- Create: `ui/src/app/org/[slug]/layout.tsx` (organisation and product picker), `products/page.tsx`, `auth/page.tsx`, `members/page.tsx`, `capabilities/page.tsx`, `policies/page.tsx`, `policies/[id]/page.tsx`, `ui/src/lib/ruleTree.ts` (builder tree <-> V1 AST converters), `ui/src/components/RuleBuilder.tsx`, `ui/tests/unit/ruleTree.test.ts`, `ui/tests/e2e/org-console.spec.ts`, `docs/registry/rule-builder-spike.md`

## Consumes
V2-05 organisation routes, V1 policy endpoints (`preview`, `test`, history, restore), V2-08 app shell.

## Produces
- Organisation and optional product selection (from `GET /v1/me`), sent as `X-Org`/`X-Product` on every call.
- Products (create, archive), organisation and product auth config (form from the adapter schema, effective-auth view, test-a-token), members (add by exact username or email, groups), capability policies.
- Policies: list with usage count, create/edit with `react-querybuilder` mapped to the V1 AST through `ruleTree.ts`, server preview after every edit (text comes from the server), test against a pasted token with per-leaf results, history and restore, `rev_conflict` handling, read-only `open-to-all`.

## Steps
1. Spike first (write findings to `docs/registry/rule-builder-spike.md`): round-trip every V1 AST node type (`cmp`, `member`, `in_list`, `starts_with`, `ends_with`, `has`, `and`, `or`, `not`, `var.tenant_id`) through the builder tree and back; list anything that cannot be represented and how the UI falls back (text editor). Stop and report if a core node cannot round-trip.
2. Unit tests: converter round trips against the 15 golden rules from V1 section 8.3; unsupported shapes fall back without data loss.
3. E2E: org admin adds a product, a policy in the builder (preview text matches server), sees usage counts; attaches a second user by username with a group and that user's access changes on the next request; org writer sees no admin screens; an org admin cannot select another organisation.
4. Review-focus: stale `rev`, deleting an in-use policy (`409 policy_in_use`), group names with spaces, very large rules (limits `422 policy_too_large` surfaced clearly).
5. Implement.

## Done when
Spike accepted, converter and E2E tests pass, lint and typecheck clean.
