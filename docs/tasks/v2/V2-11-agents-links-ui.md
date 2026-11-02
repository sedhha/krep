# V2-11 — Agents and links UI

Spec: 4, 6, 9.4, 10 (agents, links). Acceptance: 9, 11, 12, 15 (UI side), 19.

## Files
- Create: `ui/src/app/org/[slug]/agents/page.tsx`, `agents/new/page.tsx`, `agents/[id]/page.tsx`, `agents/[id]/versions/[n]/page.tsx`, `ui/src/components/PolicyPicker.tsx` (multi-select per action), `ScopePicker.tsx`, `LinkPanel.tsx`, `AgentForm.tsx`, `ui/src/app/platform/global/page.tsx` (global content and scope approval), `ui/tests/e2e/agents.spec.ts`, `ui/tests/unit/AgentForm.test.tsx`
- Modify: `ui/src/lib/api.ts`

## Consumes
V2-02 policy slots and scope, V2-06 links and scope approval, V1 versions/publish endpoints.

## Produces
- Agent list filterable by scope and product; create/edit form with only the fields the V1 agent requires (`model`, `system_prompt`) plus an Advanced JSON block for the rest; scope picker (org or product for org admins); read and manage policy multi-pickers including `open-to-all`; draft editing, publish, make-current, archive, delete.
- Link panel: create (allowed target scopes only, including global targets), pending/accept/reject, unlink; clear messages for `link_scope_not_allowed` and `409 resource_in_use`.
- Platform view of global content: list, move a resource to `global` (platform admin), demote, referrer counts and organisation slugs.

## Steps
1. Unit tests: form validation mirrors V1 required fields and shows the server's field errors; policy and scope pickers produce the request body shape of spec 9.4.
2. E2E (ac19): org-level and product-level agents created with policies; an organisation-level session sees only the first, a product-selected session sees both (ac11, ac9); a user without a read policy does not see a resource; org admin cannot set `global`; platform admin promotes a resource and another organisation's agent links to it; deleting or demoting it is refused with referrers shown to the platform admin only.
3. Review-focus: publishing with pending links, editing a published version (immutable), scope change while linked, stale data after policy edits.
4. Implement.

## Done when
E2E and unit tests pass, lint and typecheck clean, all UI paths for resources, policies and links work against the real backend.
