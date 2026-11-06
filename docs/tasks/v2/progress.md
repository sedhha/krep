# V2 Progress

Status: `todo` | `in-progress` | `in-review` | `done` (with commit hash)

Drop 1 (V2-01 to V2-07) is the backend, testable with a stub login issuer and a stand-in `auth` table, no Node. Drop 2 (V2-08 to V2-12) is the UI and starts after drop 1 is done.

| # | Task | Status | Commit |
| --- | --- | --- | --- |
| V2-01 | [Migrations: organisations, identity tables, scope, policy join, roles](V2-01-migrations.md) | done | fb49d17 |
| V2-02 | [Policy-only access, scope and global read](V2-02-policy-only-access.md) | done | 04d83aa |
| V2-03 | [Secret crypto and organisation auth adapters](V2-03-crypto-auth-adapters.md) | done | ef46c71 |
| V2-04 | [Identity: selector mode, login JWT, platform admin](V2-04-identity.md) | done | 5ecdd68 |
| V2-05 | [Platform and organisation routes, audit](V2-05-admin-routes.md) | done | cbee858 |
| V2-06 | [Resource API scope, cross-tenant links, global approval](V2-06-resource-links.md) | done | 88aed63 |
| V2-07 | [Organisation lifecycle and purge](V2-07-lifecycle.md) | done | 62fba06 |
| V2-08 | [Next.js app, Better Auth, BFF proxy](V2-08-next-app-better-auth.md) | done | 8e70d3b |
| V2-09 | [Platform console](V2-09-platform-console.md) | done | 36ef6e7 |
| V2-10 | [Organisation console: products, auth, members, policies](V2-10-org-console.md) | todo | |
| V2-11 | [Agents and links UI](V2-11-agents-links-ui.md) | todo | |
| V2-12 | [End-to-end walkthrough, dev tooling, docs](V2-12-e2e-docs.md) | todo | |

## Notes

- Revision numbers: V2-01 adds `0005`-`0009`; V2-02 `0010` (drops `visibility` and `policy_id`); V2-05 `0011` (platform role grants on tenant tables, needed for atomic organisation creation); V2-06 `0012` (referrer function); V2-07 `0013` (purge function).
