# Progress

Status: `todo` | `in-progress` | `in-review` | `done` (with commit hash)

| # | Task | Status | Commit |
| --- | --- | --- | --- |
| 01 | [DB foundation: compose, roles, Alembic, schema](T01-db-foundation.md) | done | d278c39 |
| 02 | [Integrity triggers, RLS, grants, seed](T02-integrity-rls-seed.md) | done | 1c2d622 |
| 03 | [Policy parser, AST, pretty-printer](T03-policy-parser.md) | done | 91809ad |
| 04 | [Policy compiler to jsonpath](T04-policy-compiler.md) | done | c52031c |
| 05 | [Policy evaluation, summary, leaf testing](T05-policy-evaluate.md) | done | 579037b |
| 06 | [App skeleton, config, pool, tenant transaction](T06-app-skeleton.md) | done | d577347 |
| 07 | [Identity: JWT, API key, principal, caller](T07-identity.md) | done | 9b764c3 |
| 08 | [Ops CLI: tenant init, policy reset/recompile](T08-ops-cli.md) | done | 5939796 |
| 09 | [Access policy API](T09-policy-api.md) | done | 602236d |
| 10 | [Spec validators and limits](T10-validators-limits.md) | in-review | |
| 11 | [Resources: create, list, get, patch, archive, delete](T11-resources.md) | todo | |
| 12 | [Versions: drafts, publish, retention, current](T12-versions-publish.md) | todo | |
| 13 | [Search query builder and registry_search()](T13-search-core.md) | todo | |
| 14 | [Search API, synonyms, zero-result metric](T14-search-api-synonyms.md) | todo | |
| 15 | [Links: rules, acceptance, cycles, freezing](T15-links.md) | todo | |
| 16 | [Bundle resolution](T16-bundle.md) | todo | |
| 17 | [Uploads and skill resources](T17-uploads.md) | todo | |
| 18 | [Benchmark, hardening, end-to-end walkthrough](T18-benchmark-hardening.md) | todo | |

## Notes

- T09: reserved policies reject delete and rename with `409 policy_reserved` (spec 8.6/14.12 gives no code). Other codes the spec leaves open: `409 policy_name_taken`, `409 policy_limit_reached`, `422 policy_invalid`.
