# V2-07 — Organisation lifecycle and purge

Spec: 7, 8 (`organizations` lifecycle columns), 9.2 (lifecycle routes). Acceptance: 16.

## Files
- Create: `migrations/versions/0013_purge_function.py` (`purge_organization(uuid)` run as owner, purge-only session flag honoured by the immutability trigger), `src/krep/org/lifecycle.py`, `src/krep/jobs.py`, `tests/org/test_lifecycle.py`, `tests/org/test_purge.py`
- Modify: `src/krep/api/admin.py` (suspend, activate, schedule-delete, cancel-delete, legal-hold), `src/krep/cli.py` (`krep jobs purge-due`), `src/krep/config.py` (`KREP_ORG_DELETE_GRACE_DAYS`), `.env.example`, `README.md`

## Consumes
V2-01 columns `status`, `delete_after`, `legal_hold`; V2-04 selector (suspended organisations are `401`); V2-05 audit; V2-06 cross-tenant referrer function.

## Produces
- `lifecycle.py`: `suspend`, `activate`, `schedule_delete(grace_days)` (default 30, max 90, `422` above), `cancel_delete`, `set_legal_hold`; each writes an audit row.
- `jobs.py`: `purge_due(owner_conn) -> list[PurgeResult]` selecting `pending_delete` organisations past `delete_after` without `legal_hold` and without foreign dependents on their global resources; refused organisations are reported with their blockers.
- `purge_organization(uuid)`: deletes every row of the tenant in dependency order in one transaction (resources, versions, subtypes, files, links and deps, policies and history, synonyms, products, auth configs, memberships, limits overrides), nulls `admin_audit_log.detail` for that tenant, keeps organisation id/action/timestamp rows.

## Steps
1. Lifecycle tests: suspend gives immediate `401` for every request of that organisation, activate restores; schedule/cancel; grace bounds; state machine rejects invalid transitions (`409`).
2. Purge tests (ac16): nothing deleted before `delete_after`; nothing while `legal_hold`; nothing while other organisations link to its global resources (blockers reported); after clearing, every tenant table has zero rows for it; other tenants (including their links to nothing of the purged one) untouched; audit `detail` nulled; rerun is idempotent.
3. Safety tests: purge runs only through the owner role; the app and platform roles cannot call it; the immutability trigger flag is local to the purge transaction and cannot be set by `krep_app`.
4. Review-focus: foreign keys with `RESTRICT` (links target, version deps) ordering, large tenants (10,000 resources benchmark seed) complete within one transaction, a concurrent request during purge.
5. Implement.

## Done when
Acceptance 16 passes; full backend suite green; `uv run pytest -q` and the V1 benchmark still meet their targets.

## Flag
Orphaned accounts in schema `auth` are not touched here (spec 7); the platform console deletes them in drop 2.
