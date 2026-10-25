# Agents Table Setup

The call should come to registry and then registry uses the token claims to show discoverable resources.

## Agent Registry Table

- ID (Unique ID for every Agent)
- Name (Agent Name for Identification)
- Description (Agent Description - which would be used for semantic + full text search in registry)
- Description Search Vector (Vector representation of the description for semantic search)
- Tags (Tags associated with the agent for categorization and search)
- Version (Agent Version for tracking changes and updates)
- Status (Current status of the agent, e.g., draft, published, archived)
- Created At (Timestamp when the agent was created)
- Updated At (Timestamp when the agent was last updated)
- Updated By (Identifier of the user who last updated the agent)
- Meta (JSONB - Additional metadata associated with the agent)
- Tenant ID (mandatory first filter, enforced by RLS)
- Resource Type (Agent|Skill|Tool)

## Claude Feedback

Round 6. Earlier rounds are removed; approved items are under "Locked". Reply inline and say `reread`. `docs/specs/v1.md` has NOT been updated for this round yet (it still has the claims-mapping/DNF design); I will update it, plus the Alembic change, once you approve.

### 1. How much control do organisations really have over JWT claims?

> You: Someone using an AWS-generated token might not control how claims look. Take SSO services and other JWT issuers and tell me how much control consumers have.

You are right: it ranges from none to full, and the shapes differ even where control exists. From general knowledge of each vendor (details change by plan/version, so treat as directional):

| Issuer                                     | Control over claims                                                                                                                                                                            | Shape quirks that matter to us                                                                                                                                                   |
| ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AWS Cognito                                | Medium. Custom attributes appear as `custom:xyz` in the ID token; a pre-token-generation Lambda can add/override/suppress claims (access-token customisation depends on trigger version/tier). | Access token has a fixed core (`sub`, `client_id`, `scope`, `cognito:groups`); keys contain colons.                                                                              |
| Okta                                       | High, on a custom authorization server (expression-based custom claims, group filters). Org authorization server is more limited.                                                              | Claim names are whatever the admin chose.                                                                                                                                        |
| Microsoft Entra ID                         | Medium. Optional claims, app roles, limited claims mapping.                                                                                                                                    | `roles` for app roles, `groups` as GUIDs, `tid`/`oid`; **group overage**: with many groups the token omits `groups` and only carries a pointer to Graph. v1 vs v2 tokens differ. |
| Auth0                                      | High via Actions, but custom claims must be **namespaced URLs** (`https://acme.com/roles`).                                                                                                    | Keys contain `:` `/` `.`; a dotted-string path cannot address them.                                                                                                              |
| Keycloak                                   | Very high (protocol mappers).                                                                                                                                                                  | Defaults are nested: `realm_access.roles`, `resource_access.<client>.roles`.                                                                                                     |
| Google, Apple, social logins               | None. Fixed claims (`sub`, `email`, `hd`, ...).                                                                                                                                                | No groups or roles at all.                                                                                                                                                       |
| CI OIDC (e.g. GitHub Actions)              | Almost none (fixed claims such as `repository`, `ref`).                                                                                                                                        | Claims describe a workflow, not a person.                                                                                                                                        |
| AWS IAM / STS / API Gateway JWT authorizer | Not a claim source: they validate or federate tokens from another issuer.                                                                                                                      | Nothing to customise at this layer.                                                                                                                                              |

Consequences for the design:

1. **We cannot assume claim names, nesting, or types.** The same idea is `groups`, `roles`, `memberOf`, `cognito:groups`, `https://acme.com/roles` or `realm_access.roles` depending on the IdP, and a customer may have several IdPs.
2. **Scalar-or-array is common** (a single role arrives as a string, several as an array), so comparisons must tolerate both.
3. **Claim keys can contain dots and slashes**, so paths must be arrays of segments, not dotted strings.
4. **A claim can be absent for reasons the customer cannot fix** (Entra group overage). Rules must fail closed and be testable against a real sample token.
5. **Tenant id, user id and admin/writer role must also be resolved from arbitrary tokens.** Last round's `claims_mapping` and fixed `tenant_id` assumption do not survive this.
6. Mitigation that already exists in the platform: `v1-platform.md` section 3 lets the customer's backend send a trusted `principal` object. Customers who cannot shape their IdP can map claims into a clean principal in their own code, and our engine should be able to read either.

So yes, this changes the policy engine completely. It does not change versions, links, limits, RLS, search structure or named/editable policies.

### 2. Verdict: compile rules to Postgres `jsonpath`, evaluate per policy

Two ideas combine:

**(a) Compile target = SQL/JSON path.** Postgres evaluates a boolean `jsonpath` against any JSON document, with `&&`, `||`, `!`, comparisons, filters, `starts with`, `like_regex`, and bound variables. Users write rules over raw token paths; we compile them to a `jsonpath` stored in the policy row, and SQL evaluates it against the caller's token passed as one bound parameter. No claims-mapping, no DNF, no clause cap, no knowledge of token shape.

**(b) Evaluate policies, not resources.** A tenant has tens or hundreds of policies but possibly thousands of resources. Step 1 evaluates every policy of the tenant against the token (one SQL pass, tiny). Step 2 filters resources by `policy_id IN (satisfied policies)`. Still one SQL statement, still filter-before-rank, no app-side filtering.

```text
rule text  --parse-->  AST (canonical, UI edits this)  --compile-->  jsonpath (stored)
                                                                        |
request: verified token --(bound param)--> jsonb_path_match(token, jsonpath) per POLICY
                                                                        |
                          satisfied policy ids --> resources WHERE policy_id IN (...) --> rank
```

**Rule language (CEL-flavoured subset, parsed by our own small grammar):**

```text
expr    := or ;  or := and ("||" and)* ;  and := unary ("&&" unary)*
unary   := "!" unary | "(" expr ")" | cmp
cmp     := operand ("=="|"!="|"<"|"<="|">"|">=") literal
         | literal "in" operand                         // "admin" in token.roles
         | operand "in" "[" literal ("," literal)* "]"   // token.org.region in ["emea","apac"]
         | operand "." ("startsWith"|"endsWith") "(" string ")"
         | "has" "(" operand ")"
operand := ("token" | "principal") ( "." ident | "[" string "]" )*
literal := string | number | true | false | null | var.tenant_id
```

**Compile examples** (all of the semantics below were run on PostgreSQL 17.11 + pgvector 0.8.7; see "Verified"):

| Rule                                         | Compiled `jsonpath`                                                                    |
| -------------------------------------------- | -------------------------------------------------------------------------------------- |
| `token.department == "billing"`              | `exists($.token.department[*] ? (@ == "billing"))`                                     |
| `"admin" in token.roles`                     | `exists($.token.roles[*] ? (@ == "admin"))`                                            |
| `token.org.region in ["emea","apac"]`        | `exists($.token.org.region[*] ? (@ == "emea" \|\| @ == "apac"))`                       |
| `token.clearance >= 3`                       | `exists($.token.clearance[*] ? (@ >= 3))`                                              |
| `token["https://acme.com/roles"] == "admin"` | `exists($.token."https://acme.com/roles"[*] ? (@ == "admin"))`                         |
| `has(token.org.region)`                      | `exists($.token.org.region)`                                                           |
| `token.email.endsWith("@acme.com")`          | `exists($.token.email[*] ? (@ like_regex "@acme\\.com$"))` (escaped literal, anchored) |
| `token.tid == var.tenant_id`                 | `exists($.token.tid[*] ? (@ == $tenant_id))` with vars `{"tenant_id": "<tenant>"}`     |
| `!("contractors" in token.groups)`           | `!(exists($.token.groups[*] ? (@ == "contractors")))`                                  |

Every comparison is wrapped in `exists(... ? (...))` on purpose: it yields a definite true/false, so `&&`, `||`, `!` behave as ordinary two-valued logic even when a claim is missing or the wrong type.

Full example (the "billing leads" policy, written as text):

```text
token.department == "billing"
  && ("manager" in token.roles || "support-lead" in token.roles)
  && !("contractors" in token.groups)
```

compiles to:

```text
exists($.token.department[*] ? (@ == "billing"))
 && (exists($.token.roles[*] ? (@ == "manager")) || exists($.token.roles[*] ? (@ == "support-lead")))
 && !(exists($.token.groups[*] ? (@ == "contractors")))
```

**Safety:** compilation walks the validated AST only. String literals are escaped, path segments are validated (no control characters), nothing authored by users is concatenated into SQL; the jsonpath and the token travel as bound parameters, and Postgres rejects malformed jsonpath at write time (the column type is `jsonpath`).

**Verified** (throwaway container, not the full schema): scalar and array claims, missing claim, `NOT` on missing claim, nested path, numeric comparison, string-vs-number (no coercion, false), namespaced URL key, `&&`/`||`/`!` combination, bound variables, `starts with`, `like_regex`, `exists`, null, list membership, and malformed-jsonpath rejection all behaved as described above. Timing: 1,000 policies evaluated against one token in about 0.14 ms.

### 3. Discovery query (replaces the clause predicate)

```sql
WITH sat AS MATERIALIZED (            -- policies this caller satisfies (one pass over the tenant's policies)
  SELECT p.id FROM access_policies p
  WHERE p.tenant_id = :tenant
    AND jsonb_path_match(:doc::jsonb, p.compiled_path, :vars::jsonb, true)   -- true = silent, errors count as false
), visible AS MATERIALIZED (
  SELECT id, name, search_tsv, embedding
  FROM registry r
  WHERE r.tenant_id = :tenant AND r.status = 'published'
    AND (:type IS NULL OR r.type = :type)
    AND (:tags::text[] IS NULL OR r.tags @> :tags)
    AND ( r.visibility = 'tenant'
       OR (r.visibility = 'private' AND r.created_by = :user)
       OR (r.visibility = 'restricted' AND r.policy_id IN (SELECT id FROM sat)) )
)
-- lex / sem / RRF unchanged from the spec
```

- `:doc` is `{"token": <verified claims>, "principal": <optional trusted backend principal>}`; `:vars` is `{"tenant_id": "<tenant>"}`.
- Cost scales with the number of **policies** (cap with limit `max_policies`, default 500), not resources. Optional later: cache the satisfied set per (tenant, token hash, policies version) for ~60 s.
- A runtime error or unknown result evaluates as "not satisfied" (fail closed).

### 4. Semantics (must be documented to customers, shown in the UI)

- **Lax and existential:** `token.roles == "admin"` is true if the claim is the string `admin` or an array containing it. This is deliberate because IdPs are inconsistent about scalar vs array.
- **`!=` means "no element equals":** `token.roles != "admin"` is true when the claim is missing or has no `admin`. (Not "some element differs".)
- **No type coercion:** `token.cl_str >= 3` is false when the claim is the string `"3"`. The test tool flags type mismatches.
- **Missing claim = false**, so `!(...)` over a missing claim is true. Use `has()` to require presence.
- **Entra group overage** appears as a missing `groups` claim: rules over it fail closed. The test tool warns; the documented workaround is app roles or a backend-supplied `principal`.
- **Test with a real token:** `POST /v1/access-policies/{id}/test` takes a pasted, decoded sample token, shows each leaf as true/false, the overall result, and type warnings. The UI also offers path autocomplete from the pasted sample, since users cannot guess claim names.

### 5. Identity resolution (tenant, user, management roles) without controlling the token

> Needed because the registry itself must get `tenant_id`, `user_id` and write/admin rights out of arbitrary tokens.

```sql
token_issuers(issuer PK, tenant_id uuid NULL,            -- fixed tenant per issuer (typical enterprise SSO), or
              tenant_claim_path text[] NULL,             -- read tenant from a claim (path segments)
              user_claim_path text[] NOT NULL DEFAULT '{sub}',
              audience text, jwks_uri text,
              admin_policy_id uuid NULL, writer_policy_id uuid NULL,
              CHECK (tenant_id IS NOT NULL OR tenant_claim_path IS NOT NULL))
```

- `registry:admin` / `registry:write` are no longer token permissions: they are **named policies evaluated by the same engine** (`admin_policy_id`, `writer_policy_id`). Example admin policy: `"grc-admins" in token.groups`.
- Onboarding a tenant = insert one `token_issuers` row (ops task) plus its two policies. Bootstrapping the first admin policy is done by ops, not through the API.

### 6. What changes in `docs/specs/v1.md` once you approve

- Drop: `access_clauses`, DNF compiler, claims mapping (single/set/ordinal), `max_policy_clauses`, the 7x2-term complexity test.
- Add to `access_policies`: `source text`, `ast jsonb` (source of truth), `compiled_path jsonpath`; drop `expr`. Keep `rev`, history, usage count, test, summary.
- Add: `token_issuers`, limits `max_policies` (500) and `max_policy_nodes` (100); parser + compiler + pretty-printer unit tests (golden table of rule -> jsonpath, plus the semantic cases above run against a Postgres container).
- Rewrite sections 4.1–4.3, 8.2–8.6, the search predicate in 9.2, acceptance tests 2, 5, 6, and the build order step 2.
- Alembic for migrations (as discussed).

### Locked (still valid)

- Postgres + pgvector, search behind `registry_search()`; filter first, then rank; RRF.
- Named tenant-level policies with `rev` + history (last 20), edit once applies everywhere, usage count, test endpoint.
- Visibility `private | tenant | restricted(policy_id)`; hidden resources return 404.
- Latest 10 published versions, block on referenced oldest, hard delete with CASCADE/RESTRICT/SET NULL; draft cap 50 per tenant per type; `resource_limits` with most-specific-scope resolution.
- `registry_types`, generic links (`registry_links`, `link_rules`, `registry_version_deps`), accept-by-source, freeze at publish.
- RLS via per-transaction `set_config('app.tenant_id', ..., true)` with a non-superuser app role.

### Decisions

- **D1. Compile target:** A (recommended) `jsonpath` evaluated in SQL per policy, resources filtered by satisfied policy ids | B generate SQL text per request from all policies (plan bloat, injection surface) | C evaluate rules in the app and pass ids (not SQL-compiled; you ruled this out).
  > > Would using jsonpath be slow? We need to also be fast as fuck boi we need to be fast as fuck. If we're go with A
- **D2. Rule language:** A (recommended) CEL-flavoured subset with our own small parser (full control of semantics; same syntax users meet in runtime CEL) | B real CEL via a library (more syntax, semantics differ: arrays, missing keys, type errors) | C visual builder only, no text form.
  > > We choose A given we do support all those ANDing ORing NOTing conjunction disjunction criterias we talked about
- **D3. Evaluation document:** A (recommended) `{token, principal}` so customers who cannot shape their IdP can send a trusted backend principal | B token only.
  > > What is principal? Give an example and yes looks good to me as long as all common issuers support both. I remember a lot of providers might give you token only and when a client or end user authenticates they may/may not get tokens.
- **D4. Tenant/user/role resolution:** A (recommended) `token_issuers` table + admin/writer policies | B static config file or env per deployment | C require customers to add `tenant_id` and roles to tokens (not viable per your point).
  > > A looks good
- **D5. String matching:** A (recommended) `startsWith` / `endsWith` only, no free regex (no ReDoS surface) | B also allow `matches()` with a pattern length cap.
  > > A is fine given it sorts our requirements and is performant.
