# Implementation Plan — Enterprise RAG Intelligence Platform Multi-Tenancy Migration

```yaml
plan_version: 1.3
target_repo: enterprise-rag-platform
migration_type: incremental
base_branch: main
pre_migration_tag: pre-migration-v1
total_phases: 8
```

## Instructions for the executing agent

- Work one phase at a time, in the order given. Do not start a phase until all tasks in every phase listed in its `depends_on` are complete and verified.
- Each phase has its own branch: `feature/<phase-branch-name>`, created from `main` only after the previous phase's branch has been merged into `main`. Never branch from an unmerged feature branch.
- Before starting Phase 1, run: `git tag pre-migration-v1` on the current `main` HEAD if the tag does not already exist.
- Every task lists exact file paths. If a file does not exist yet, create it. If it exists, modify only the sections relevant to the task — do not rewrite unrelated code in the same file.
- After completing all tasks in a phase, run every command listed under that phase's `Verification` section. Do not merge to `main` or proceed to the next phase if any verification command fails or any assertion is false.
- If a task's instructions conflict with code already in the repo (e.g. a file path doesn't match the existing structure), stop and request clarification rather than guessing the intended location.
- Treat every SQL migration as additive and reversible: write a corresponding down-migration for every up-migration.
- Do not delete the legacy code path (SQLite access, in-memory session store, self-issued JWT issuer) until the phase that explicitly says to remove it. Earlier phases run new and legacy paths side by side behind a feature flag.

---

## Phase dependency graph

```
phase_1 (auth0)
  └── phase_2 (postgres_rls)
        └── phase_3 (rbac_v2)
              └── phase_4 (pinecone_storage)
                    └── phase_5 (redis_scale)
                          └── phase_6 (compliance_audit)
                                └── phase_7 (platform_superuser)
                                └── phase_8 (org_scoped_rbac)
```

`phase_8` depends on `phase_3` (it replaces `ROLE_PERMISSIONS_V2`, which 3.2/3.3
introduced) and does not depend on `phase_7` — the two are independent
extensions of the tenancy model and can be built in either order. Listed
after `phase_7` here only because that is the current state of `main`.

No phase may run concurrently with another. Each depends strictly on the one before it.

---

## Phase 1 — Identity: Auth0 Integration

```yaml
phase_id: phase_1
branch: feature/auth0
depends_on: []
status: complete
```

### Rationale (one line, for context only)
`org_id` must be a value the rest of the system can trust before any tenant-isolation logic (Phase 2+) is built against it.

### Tasks

**1.1 — Create Auth0 tenant and two test organizations**
- Action: manual, outside codebase. Create an Auth0 tenant. Create two Auth0 Organizations: `acme-corp` and `globex-inc`.
- Output: record `AUTH0_DOMAIN`, `AUTH0_AUDIENCE`, `AUTH0_CLIENT_ID` as environment variables in `.env.example` (placeholder values only, never real secrets).

**1.2 — Create bootstrap membership table**
- File: `app/db/models.py` (or equivalent existing models file — locate before creating a new one)
- Add table `org_members` with columns: `id (uuid, pk)`, `auth0_user_id (str, unique, indexed)`, `org_id (str, indexed)`, `team_ids (json array)`, `roles (json object, team_id -> role)`, `created_at (timestamp)`.
- This table is the source of truth that the Auth0 Action (task 1.3) reads from.

**1.3 — Create Auth0 post-login Action**
- Action: written in Auth0's Action editor (JavaScript), not part of this repo's codebase. Document the Action source in `docs/auth0_action.js` for version control even though it must also be pasted into the Auth0 dashboard.
- The Action must call back to an internal endpoint (`GET /internal/org-membership/{auth0_user_id}`, see task 1.4) and inject the response into custom token claims: `https://yourapp.com/org_id`, `https://yourapp.com/team_ids`, `https://yourapp.com/roles`.

**1.4 — Internal membership lookup endpoint**
- File: `app/api/internal.py` (new file)
- Add `GET /internal/org-membership/{auth0_user_id}` returning `{org_id, team_ids, roles}` from the `org_members` table created in 1.2.
- This endpoint must be reachable only from Auth0's Action runtime — restrict via a shared secret header (`X-Internal-Secret`), value from `INTERNAL_SECRET` env var, not via public auth.

**1.5 — JWT verification module**
- File: `app/auth/auth0_verify.py` (new file)
- Implement `verify_token(token: str) -> dict` using `PyJWKClient` against `https://{AUTH0_DOMAIN}/.well-known/jwks.json`, validating signature (RS256), audience, and issuer.
- Return dict with keys: `user_id`, `org_id`, `team_ids`, `roles`.
- Implement FastAPI dependency `get_current_context(authorization: str = Header(...))` that calls `verify_token` and raises `HTTPException(401, ...)` on any `jwt.PyJWTError`.

**1.6 — Feature flag for auth provider**
- File: `app/auth/__init__.py` or equivalent central auth module
- Add `AUTH_PROVIDER` env var, values `legacy` or `auth0`. When `legacy`, route to the existing JWT issuer unmodified. When `auth0`, route to `get_current_context` from 1.5.
- Do not remove or modify the existing legacy JWT issuer file in this phase.

**1.7 — Migrate demo users**
- Action: manual, Auth0 dashboard. Create 5 Auth0-backed users (one per existing demo role) inside `acme-corp`, plus at least 1 user inside `globex-inc` for later cross-tenant testing.
- Populate corresponding rows in `org_members` (task 1.2) for each.

### Verification

```bash
# 1. Confirm both legacy and auth0 paths work behind the flag
AUTH_PROVIDER=legacy pytest tests/test_auth_legacy.py -v
AUTH_PROVIDER=auth0 pytest tests/test_auth_auth0.py -v

# 2. Confirm two different orgs produce two different org_id claims
pytest tests/test_auth_auth0.py::test_distinct_org_claims_per_user -v

# 3. Confirm tampered/expired token is rejected with 401, not 500
pytest tests/test_auth_auth0.py::test_invalid_token_returns_401 -v
```

**Phase 1 is complete only if all three commands above exit 0 and existing query/upload endpoint tests (`tests/test_query.py`, `tests/test_upload.py`) still pass unmodified under `AUTH_PROVIDER=legacy`.**

---

## Phase 2 — Tenancy Schema: Postgres + Row-Level Security

```yaml
phase_id: phase_2
branch: feature/postgres-rls
depends_on: [phase_1]
status: complete
```

### Tasks

**2.1 — Provision Postgres and migration tooling**
- Add `alembic` to `requirements.txt` if not present.
- File: `alembic.ini`, `alembic/env.py` — standard Alembic init pointed at `DATABASE_URL` env var.
- Local dev: add a `postgres` service to `docker-compose.yml` (image `postgres:16`).

**2.2 — Create full tenancy schema**
- File: `alembic/versions/0001_tenancy_schema.py` (new migration)
- Create tables exactly as follows (types are Postgres-native; use `UUID` via `pgcrypto` or `uuid-ossp` extension for ids):

```sql
organizations(id uuid pk, name text, plan_tier text, sso_connection_id text, created_at timestamptz)
teams(id uuid pk, org_id uuid fk -> organizations.id, name text, created_at timestamptz)
users(id uuid pk, org_id uuid fk -> organizations.id, idp_subject text unique, email text, display_name text, created_at timestamptz)
team_memberships(id uuid pk, team_id uuid fk -> teams.id, user_id uuid fk -> users.id, role text, granted_at timestamptz, expires_at timestamptz nullable)
data_sources(id uuid pk, org_id uuid fk -> organizations.id, team_id uuid fk -> teams.id nullable, type text, name text, config_json jsonb)
documents(id uuid pk, org_id uuid fk -> organizations.id, data_source_id uuid fk -> data_sources.id, storage_uri text, status text, created_at timestamptz)
conversations(id uuid pk, org_id uuid fk -> organizations.id, user_id uuid fk -> users.id, team_id uuid fk -> teams.id, created_at timestamptz)
conversation_turns(id uuid pk, conversation_id uuid fk -> conversations.id, role text, content_masked text, ts timestamptz)
audit_events(id uuid pk, org_id uuid fk -> organizations.id, actor_user_id uuid fk -> users.id, action text, resource text, ts timestamptz)
```

- Write the corresponding down-migration dropping these tables in reverse FK order.

**2.3 — Enable RLS on every tenant-scoped table**
- File: `alembic/versions/0002_enable_rls.py` (new migration, depends on `0001`)
- For every table listed in 2.2 that has an `org_id` column, execute:

```sql
ALTER TABLE <table_name> ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON <table_name>
  USING (org_id = current_setting('app.current_org_id', true)::uuid);
```

- Use `current_setting('app.current_org_id', true)` — the `true` second argument is required. It returns `NULL` instead of raising when the setting is unset, so a request that bypasses the session-scoping middleware (task 2.5) sees zero rows rather than an unhandled exception.
- Down-migration: `ALTER TABLE <table_name> DISABLE ROW LEVEL SECURITY;` and `DROP POLICY tenant_isolation ON <table_name>;` for each table.

**2.4 — Migrate existing SQLite data**
- File: `scripts/migrate_sqlite_to_pg.py` (new file)
- Read existing `data/enterprise.db` tables (`invoices`, `salaries`, `budgets` or equivalent — inspect actual schema before writing migration logic).
- Create one row in `organizations` named `default_org` if it does not exist. Backfill every migrated row with this org's id.
- Idempotency requirement: running this script twice must not create duplicate rows. Use an `INSERT ... ON CONFLICT DO NOTHING` pattern or check-before-insert.

**2.5 — Tenant-scoped DB session middleware**
- File: `app/db/session.py` (new or modify existing session module)
- Implement:

```python
from contextlib import asynccontextmanager
from sqlalchemy import text

@asynccontextmanager
async def tenant_scoped_session(org_id: str):
    async with engine.begin() as conn:
        await conn.execute(
            text("SET LOCAL app.current_org_id = :org_id"),
            {"org_id": org_id},
        )
        yield conn
```

- Use `SET LOCAL`, not `SET`. `SET LOCAL` is scoped to the current transaction only; on a pooled connection, plain `SET` would leak one request's org context into the next request reusing that connection. This is a correctness requirement, not a style preference.
- Add FastAPI dependency `get_db(ctx: dict = Depends(get_current_context))` that opens `tenant_scoped_session(ctx["org_id"])` and yields the connection.

**2.6 — Replace SQLite call sites**
- Files: `app/retrieval/sql_retriever.py` and any other module currently importing the SQLite connection directly (search the codebase for `sqlite3` or the existing DB connection import before starting; enumerate every call site rather than assuming this list is complete).
- Replace each with the `get_db` dependency from 2.5. Do not change query logic beyond the connection/session source.

### Verification

```bash
# 1. Cross-tenant isolation — zero rows leak even with a deliberately
#    malformed query that omits an explicit WHERE org_id clause
pytest tests/test_tenant_isolation.py::test_sql_rls_blocks_cross_org_read -v

# 2. Existing demo data intact and scoped to default_org
pytest tests/test_query.py -v

# 3. Confirm SQLite is no longer imported anywhere
grep -r "sqlite3" app/ --include="*.py" | grep -v "^Binary" ; test $? -ne 0
```

**Phase 2 is complete only if both pytest commands pass and the `grep` command finds zero remaining `sqlite3` imports in `app/`.**

---

## Phase 3 — Scoped RBAC: Team Memberships & Permission Resolution

```yaml
phase_id: phase_3
branch: feature/rbac-v2
depends_on: [phase_2]
status: complete
```

### Discovery findings folded into this phase (2026-06-28)

Repo inspection ahead of this phase surfaced three gaps between the plan's
assumptions and what Phase 1/2 actually left behind. All three are now
explicit tasks below rather than implicit sub-steps, so each gets its own
test instead of being verified only as a side effect of 3.3/3.4:

1. `team_memberships` (created in Phase 2's `0001_tenancy_schema.py`) has
   no `expires_at` column — task 3.3's step 3 requires one. New migration:
   task 3.1a.
2. `resource_grants` does not exist anywhere in the schema. The original
   plan buried its creation inside 3.3 (the resolver-logic task) as an
   aside ("create this table... if it does not exist"). Pulled out into
   its own task (3.1b) so schema creation is verified independently of
   resolver logic, matching how 3.1a is handled.
3. **This is the one that actually changes behavior, not just schema.**
   `app/api/deps.py::_map_roles_to_user_role` currently collapses Auth0's
   `roles` claim — which is a real `team_id -> role_name` dict, already
   present on the verified JWT — down into a single flattened `UserRole`
   per user, before any route ever sees it. `resolve_access(ctx,
   data_source_type, team_id)` is supposed to resolve a *per-team* role,
   but by the time `ctx`/`user` reaches any call site today, the
   per-team information is already gone. Per-team resolution must
   replace the flattening, not sit alongside it — leaving both would mean
   two disagreeing sources of truth for "what role does this user have,"
   which defeats the purpose of this phase. New task: 3.0, sequenced
   first since 3.1's seeding and 3.3's resolver both depend on real
   per-team roles existing end-to-end, not just in the DB.

### Tasks

**3.0 — Replace flattened role mapping with per-team role resolution**
- File: `app/api/deps.py`
- Remove `_map_roles_to_user_role` and its single `UserRole` field on the
  context/user object entirely — do not keep it as a fallback. Every call
  site that read `user.role` is, by definition, a call site 3.4 must
  update; leaving the flattened field in place would let an unmigrated
  call site silently keep working off stale logic instead of failing
  loudly.
- Add a function (e.g. `get_role_for_team(roles_claim: dict, team_id: str) -> str | None`)
  that looks up `roles_claim.get(team_id)` directly from the JWT's
  already-verified `roles` dict (`team_id -> role_name`, populated by the
  Auth0 Action from Phase 1 — no new claim shape needed, the data was
  already there).
- Update the `User` object (or `ctx` dict, whichever 3.3/3.4 standardize
  on) to drop `role: UserRole` and keep `roles: dict` and `team_ids: list`
  as the only source of role information. `org_id` stays as-is — this
  task only touches role flattening, not tenant scoping.
- This task has no independent pytest target in this phase's Verification
  section because its correctness is only observable through 3.3/3.4's
  tests (a per-team role resolves correctly) and is covered by
  `test_legacy_single_team_user_unchanged` — a user with exactly one team
  must resolve to the same effective permissions as the old flattened
  behavior did, so the replacement is provably non-regressive for the
  common case even though the mechanism changed.

**3.1 — Seed team memberships for test orgs**
- File: `scripts/seed_team_memberships.py` (new file)
- For `acme-corp` and `globex-inc` (created in Phase 1/2), create at least one team each, and assign the 7 roles below across test users: `org_admin`, `team_lead`, `compliance_officer`, `finance_analyst`, `operations_engineer`, `employee`, `guest`.
- Depends on 3.0 — seed data is only meaningful once roles are resolved per-team rather than flattened.

**3.1a — Add `expires_at` to `team_memberships`**
- File: `alembic/versions/0003_team_membership_expiry.py` (new migration, depends on `0002`)
- `ALTER TABLE team_memberships ADD COLUMN expires_at timestamptz NULL;`
- Down-migration: `ALTER TABLE team_memberships DROP COLUMN expires_at;`
- Nullable, no default — an absent `expires_at` means "does not expire," consistent with how 3.3 step 3 treats `NULL` (skip the expiry check, not "treat as already expired").

**3.1b — Create `resource_grants` table**
- File: `alembic/versions/0004_resource_grants.py` (new migration, depends on `0003`)
- Columns: `id (uuid, pk)`, `org_id (uuid, fk -> organizations.id)`, `user_id (uuid, fk -> users.id)`, `data_source_id (uuid, fk -> data_sources.id)`, `granted_at (timestamptz, default now())`, `expires_at (timestamptz, nullable)`.
- `org_id` included and RLS-enabled on this table too (same `tenant_isolation` policy pattern as migration `0002`) — every other tenant-scoped table got this in Phase 2, and a resource grant is exactly the kind of row that must not leak across orgs.
- Down-migration: drop the RLS policy, then drop the table.

**3.2 — Role permission map**
- File: `app/auth/rbac.py` (modify existing RBAC module — confirmed present from Phase 1/2 discovery; do not create a second file)
- Existing `ROLE_PERMISSIONS` in this file is keyed on `UserRole` enum values
  and `DataSource` enum values from the original single-tenant demo. Do not
  delete it yet — `RBACEngine.can_access` etc. remain in place until 3.4
  confirms every call site has moved off them, per the "earlier phases run
  old and new paths side by side" rule. The dict below is the *new*,
  string-keyed map `resolve_access` (3.3) reads from; it is additive in
  this task, superseding the old dict only once 3.4 finishes:

```python
ROLE_PERMISSIONS_V2 = {
    "org_admin":           {"*"},
    "team_lead":           {"*"},
    "compliance_officer":  {"compliance_records", "audit_logs", "public_policies"},
    "finance_analyst":     {"financial_db", "invoice_records", "public_policies"},
    "operations_engineer": {"audit_logs", "system_metrics", "public_policies"},
    "employee":            {"public_policies"},
    "guest":               set(),
}
```

**3.3 — Permission resolver**
- File: `app/auth/rbac.py` (same file as 3.2)
- Implement `resolve_access(ctx: dict, data_source_type: str, team_id: str | None) -> bool` following this exact step order (do not reorder — each step may only narrow access, never widen it):
  1. Tenant filter is implicit — RLS (Phase 2) already scopes any DB query to `ctx["org_id"]` before this function is called. Do not re-implement tenant filtering here.
  2. Look up team membership for `(ctx["user_id"], team_id)` — this is a real DB lookup against `team_memberships` (not `ctx["roles"]` from the JWT; the JWT claim from 3.0 tells you *which* teams/roles existed at token-issue time, but `team_memberships` is the authoritative, revocable record). If no membership exists, skip to step 4.
  3. If membership has a non-null `expires_at` (column added in 3.1a) and it is in the past, return `False` immediately.
  4. Check `ROLE_PERMISSIONS_V2[membership.role]` (3.2) — if it contains `"*"` or `data_source_type`, return `True`.
  5. Fall back to checking `resource_grants` (table created in 3.1b). Return `True` only if a non-expired grant exists for this exact `data_source_id`.

**3.4 — Wire resolver into existing routes**
- Files: `app/api/routes.py` — four confirmed call sites (`rbac.can_access(user.role, data_source)` at the upload-time check, the query-time loop, the second query-time check, and a direct `UserRole.ADMIN` check guarding document deletion). Locate the exact current line numbers before editing, since line numbers drift; match by the `rbac.can_access(` and `UserRole.ADMIN` substrings instead of by line number.
- Replace every one of these four with a call to `resolve_access`. Pass `team_id` through from the request context — if the existing query/intent classification layer (`app/intent/`, `app/routing/`) does not currently carry `team_id`, add it as a required field on the relevant request/context objects.
- The direct `if user.role != UserRole.ADMIN` delete-route check has no `data_source_type` to check against — it's a pure role gate, not a per-source one. Translate it to `resolve_access(ctx, "*", team_id=None)` (org-wide admin check, no specific data source) rather than inventing a second, parallel admin-check helper.
- Once all four call sites are confirmed migrated (by the tests below passing), remove `ROLE_PERMISSIONS`, `RBACEngine`, and the old `UserRole`-keyed permission dict from `app/auth/rbac.py` in this same task — per 3.2's note, the old path was only kept alive until this point.

### Verification

```bash
pytest tests/test_rbac.py::test_different_teams_different_permissions -v
pytest tests/test_rbac.py::test_guest_resource_grant_only -v
pytest tests/test_rbac.py::test_expired_guest_grant_denied -v
pytest tests/test_rbac.py::test_legacy_single_team_user_unchanged -v
grep -rn "UserRole.ADMIN\|rbac.can_access(" app/api/routes.py ; test $? -ne 0
```

**Phase 3 is complete only if all four pytest targets pass and the grep finds zero remaining direct role checks in `routes.py` (confirming 3.4's old-path removal actually happened, not just that the new path also works).**

---

## Phase 4 — Vector & Storage Isolation: Pinecone (namespace-per-org) + Object Storage

```yaml
phase_id: phase_4
branch: feature/pinecone-storage
depends_on: [phase_3]
status: complete
superseded_plan: qdrant_storage (see "Revision note" below)
```

### Revision note (2026-06-30)

The original Phase 4 plan (`feature/qdrant-storage`, written before any repo discovery)
assumed: (a) `app/retrieval/vector_store.py` did not yet exist and would be created fresh,
(b) the codebase was actively running Milvus and needed a Milvus→Qdrant migration script,
and (c) tenant isolation would be enforced via payload filtering on `org_id`/`team_id`
inside one or more Qdrant collections.

Discovery (this session) found all three assumptions wrong:

1. `app/retrieval/vector_store.py` already exists and is a mature, Qdrant-backed
   `VectorStore` class — lazy collection creation, idempotent payload-index
   bootstrapping, and a semantic chunking pipeline (`SemanticChunker` +
   `NVIDIAEmbeddings`) already wired through it.
2. No Milvus client exists anywhere on `aegis-handler`. The one `milvus_db_path`
   reference in the file is dead/commented-out legacy naming, not a live system.
   There is nothing to migrate *from* — Milvus was never live on this branch.
3. **Critically, the existing `VectorStore` has no tenant isolation at all.**
   There is no `org_id` or `team_id` anywhere in the payload schema, the ingest
   path, or `search()`. The single collection (`enterprise_documents`) is shared
   across every org. RBAC (Phase 3) correctly gates which `DataSource` categories
   a user may query, but does nothing to stop a user in `acme-corp` from
   retrieving chunks that belong to `globex-inc`. This is the actual gap Phase 4
   must close — the Postgres-RLS tenant boundary from Phase 2 does not currently
   extend to the vector layer.

Separately, after discovery, the vendor decision itself changed: this phase
moves off Qdrant onto **Pinecone**, using **one namespace per `org_id`** rather
than payload-filtering within a shared index/collection. This is a deliberate,
explicit revision to the architecture-decision log (previously: "Qdrant over
Milvus" — see `MIGRATION_STATE.md` discovery notes), not an accidental drift.
Rationale and tradeoffs accepted going in:

- **Why namespaces over payload filtering:** a Pinecone namespace is a hard
  isolation boundary enforced by the index itself — a query is scoped to
  exactly one namespace per call. This is a stronger guarantee than "trust
  that every call site remembers to apply the org_id filter," which is the
  failure mode the Phase 4 plan (in either vendor) exists to eliminate.
- **Tradeoff accepted — no local dev parity:** Pinecone is API-only, hosted
  service, no local emulator. The `docker-compose.yml` Qdrant service this
  plan originally specified (task 4.1) does not have a Pinecone equivalent.
  Local/dev/CI work against a real (or sandboxed) Pinecone index over the
  network from this phase onward.
- **Tradeoff accepted — serverless cost curve:** Pinecone serverless pricing
  is per-Read-Unit, scaling with namespace size queried; at low query volume
  this is cheap-to-free, but there is a well-documented "scale cliff" at
  high query volume / large namespaces where self-hosted alternatives become
  cheaper. Not a concern at current/demo scale; worth revisiting if/when
  query volume grows materially.
- **What's being thrown away:** the existing Qdrant `VectorStore`
  implementation (collection lifecycle, payload-index bootstrapping,
  chunking pipeline wiring) is being replaced, not extended. The chunking
  pipeline itself (`SemanticChunker` + `NVIDIAEmbeddings`) is vendor-agnostic
  and is preserved as-is; only the storage/query backend changes.

The task list below replaces the original Phase 4 task list in full. Tasks
4.4 ("migrate from Milvus") and the Qdrant-specific collection/payload-index
tasks (original 4.1–4.3) are dropped as moot. Task numbering restarts at 4.1
under the new plan to avoid any ambiguity with the superseded version.

### Tasks

**4.1 — Provision Pinecone**
- Action: manual, outside codebase. Create a Pinecone project and a single
  serverless index (e.g. `aegis-documents`), with vector dimension matching
  the existing NVIDIA embedding model's output (`nvidia/nv-embed-v1` —
  confirm exact dimension from the model docs or by inspecting a live
  embedding call before creating the index; do not guess).
- Add `PINECONE_API_KEY` and `PINECONE_INDEX_NAME` to `.env.example`
  (placeholder values only).
- Add `pinecone` (the current official Python SDK package — confirm exact
  package name, as it has changed across SDK versions) to `requirements.txt`.
- Remove `qdrant-client` from `requirements.txt` once 4.3 confirms no
  remaining references.

**4.2 — Rewrite `VectorStore` for Pinecone, namespace-per-org**
- File: `app/retrieval/vector_store.py` (modify in place — this file
  already exists; do not create a second module)
- Replace the `QdrantClient` instantiation with a Pinecone client + handle
  to the single index created in 4.1. There is no per-content-type
  collection split (matching the existing single-collection design) —
  content-type filtering (`data_source`) continues to work as a metadata
  filter *within* a namespace, same as it does today within the Qdrant
  collection.
- Every ingest and query operation must take a required `org_id: str`
  parameter with **no default value** — omitting it must raise `TypeError`
  at call time, not silently fall through to an unscoped operation. This
  mirrors the "no default value" principle from the original plan's 4.3/4.5
  and is non-negotiable for the same reason: a missing `org_id` must fail
  loudly, not search/write unfiltered.
- Namespace naming: use the `org_id` value directly as the Pinecone
  namespace string (Pinecone namespaces are plain strings scoped to an
  index, no separate provisioning step required — confirm this against
  current Pinecone SDK docs before implementing, since namespace handling
  has changed across SDK versions).
- `team_id`, where present, continues to be carried as point/vector
  metadata (not a second namespace dimension) and filtered on at query
  time within the org's namespace — splitting namespaces further by team
  is out of scope for this phase unless a concrete need surfaces.
- Preserve `_semantic_chunk_text`, `_chunker`, and `_embedding_model` as-is;
  only the storage/query backend (currently `self._client = QdrantClient(...)`
  and the `_ensure_collection` / `_ensure_payload_indexes` / `upsert` /
  `query_points` calls) is replaced.
- `DOCUMENT_SOURCE_MAP` and `FILTERABLE_PAYLOAD_FIELDS`-equivalent metadata
  handling (`data_source`) is preserved; `org_id` (and `team_id` where
  applicable) are added as additional required metadata fields on every
  upserted point.

**4.3 — Mandatory-namespace search wrapper**
- File: `app/retrieval/vector_store.py` (same file as 4.2)
- `search()` signature gains a required `org_id: str` parameter (no
  default), used to select the Pinecone namespace for the query. As in the
  original plan's 4.3, this must be the **only** function in the codebase
  that calls the Pinecone query API directly — search the codebase for any
  other direct Pinecone client calls and route them through this function.
  If a call site cannot be routed through this function, stop and report
  why rather than adding a second unfiltered search path.
- Confirm via `grep -rn "qdrant\|QdrantClient" app/ --include="*.py"` that
  no other module references the old client directly before considering
  this task complete.

**4.4 — Re-ingest existing documents with org_id tagging**
- File: `scripts/migrate_to_pinecone.py` (new file)
- Per the decision already made: **clean re-ingest, not in-place tagging.**
  Re-run ingestion from source documents in `data/documents/` (the same
  source `ingest_documents()` already reads from) through the rewritten
  `VectorStore`, writing into the appropriate org's Pinecone namespace.
  Do not attempt to read/migrate/export anything from the old Qdrant
  collection — it is discarded, not converted.
- Every re-ingested point must be tagged with `org_id = default_org`,
  matching the convention already established in Phase 2's SQL backfill
  (`organizations` row named `default_org`) — there is no existing
  multi-org real document set to preserve, so this is the only tagging
  decision needed.
- Idempotency requirement, consistent with the original plan's pattern for
  migration scripts: running this script twice must not create duplicate
  points. Use deterministic point IDs (the existing `hashlib.md5(...)`
  chunk-id scheme already does this) so a re-run safely upserts rather than
  duplicates.
- Once this script has been run successfully and 4.6's tests pass, the old
  Qdrant collection/instance may be decommissioned (manual step, outside
  codebase — not a task this script needs to automate).

**4.5 — Object storage migration**
- File: `app/document/storage.py` (new, or modify existing local-filesystem
  storage module — locate the actual current module before creating a new
  one; not yet confirmed present in discovery, check before assuming it
  doesn't exist)
- Unchanged from the original plan: replace local filesystem reads/writes
  with an S3-compatible client (`boto3`, pointed at AWS S3, Cloudflare R2,
  or local MinIO via `docker-compose.yml` for dev — this part of local dev
  is unaffected by the Pinecone decision, since object storage and vector
  storage are independent).
- Key format: `{org_id}/{data_source_id}/{filename}`. No document may be
  written without an `org_id` prefix — same "no default value" principle
  as 4.2/4.3.

**4.6 — Cross-tenant adversarial test suite**
- File: `tests/test_tenant_isolation.py` (extend the file from Phase 2/3)
- Add:

```python
def test_vector_search_never_leaks_across_orgs(org_a_ctx, org_b_ctx):
    seed_document(org_a_ctx.org_id, "Q4 budget memo")
    seed_document(org_b_ctx.org_id, "Q4 budget memo")
    results = vector_store.search(
        query="Q4 budget",
        allowed_sources=[...],
        org_id=org_a_ctx.org_id,
    )
    assert all(r.org_id == org_a_ctx.org_id for r in results)
    # Namespace isolation should make this structurally true, not just
    # filter-true — assert zero cross-namespace results, not zero
    # incorrectly-tagged results.

def test_search_requires_org_id():
    with pytest.raises(TypeError):
        vector_store.search(query="test", allowed_sources=[...])

def test_storage_keys_are_org_prefixed(org_a_ctx):
    uri = store_document(org_a_ctx.org_id, "data_source_1", "file.pdf", b"...")
    assert uri.startswith(f"{org_a_ctx.org_id}/")
```

- `VectorResult` (the existing dataclass) gains an `org_id` field so the
  isolation test above can assert on it directly rather than inferring
  isolation only from absence of cross-org content.

### Verification

```bash
pytest tests/test_tenant_isolation.py -v
grep -rn "qdrant\|QdrantClient" app/ --include="*.py" ; test $? -ne 0
grep -rn "milvus" app/ --include="*.py" ; test $? -ne 0
grep -rn "\.query(" app/ --include="*.py" | grep -v "app/retrieval/vector_store.py" ; test $? -ne 0
```

**Phase 4 is complete only if all isolation tests pass, no `qdrant`/`QdrantClient`
references remain in `app/` (confirming the vendor swap is fully done, not
partially), no `milvus` references remain (confirming the original dead-code
mention was cleaned up too, not just left as a stale comment), and no direct
Pinecone query calls exist outside `vector_store.py`.**

---

## Phase 5 — Statefulness & Horizontal Scale: Redis

```yaml
phase_id: phase_5
branch: feature/redis-scale
depends_on: [phase_4]
status: complete
```

### Tasks

**5.1 — Provision Redis**
- Add `redis` service to `docker-compose.yml`.
- Add `redis` (`redis.asyncio`) to `requirements.txt`. Add `REDIS_URL` to `.env.example`.

**5.2 — Redis-backed session store**
- File: `app/conversation/session_store.py` (replace existing in-memory implementation — locate it first; do not create a second, parallel session store)
- Implement:

```python
import json
import redis.asyncio as redis

r = redis.from_url(os.environ["REDIS_URL"])
TTL_SECONDS = int(os.environ.get("CONVERSATION_SESSION_TTL_MINUTES", 60)) * 60

def _key(org_id: str, session_id: str) -> str:
    return f"conversation:{org_id}:{session_id}"

async def append_turn(org_id: str, session_id: str, turn: dict):
    key = _key(org_id, session_id)
    history = await get_history(org_id, session_id)
    history.append(turn)
    history = history[-MAX_TURNS:]
    await r.set(key, json.dumps(history), ex=TTL_SECONDS)

async def get_history(org_id: str, session_id: str) -> list:
    raw = await r.get(_key(org_id, session_id))
    return json.loads(raw) if raw else []
```

- `MAX_TURNS` must read from the existing `CONVERSATION_MAX_TURNS` env var already defined in the demo's config.
- Remove the existing in-process TTL eviction thread/loop entirely in this task — Redis key expiry (`ex=TTL_SECONDS`) replaces it. Do not leave both running.

**5.3 — Containerize for multi-replica run**
- File: `Dockerfile` (new, if not present)
- File: `docker-compose.yml` (modify) — add 2 replicas of the API service plus a basic reverse proxy (`nginx`, round-robin) in front of them, for local verification of statelessness.

**5.4 — Background ingestion queue**
- Add `celery` to `requirements.txt`.
- File: `app/tasks/ingestion.py` (new file)
- Move the parse → chunk → embed pipeline (currently presumably synchronous in the upload route — locate the exact function before modifying) into a Celery task, using the Redis instance from 5.1 as the broker.
- File: `app/api/document.py` (or wherever the upload route lives) — modify the upload endpoint to enqueue the task and return `{"job_id": ..., "status": "processing"}` immediately rather than blocking until ingestion finishes.

### Verification

```bash
pytest tests/test_session_store.py -v
# Manual/scripted: kill one of the 2 API replicas mid-conversation,
# confirm the other replica serves the next turn with full history intact
pytest tests/test_multi_replica_sessions.py -v
pytest tests/test_ingestion_queue.py::test_upload_returns_job_id_immediately -v
```

**Phase 5 is complete only if all three test commands pass and no in-memory session dict or eviction thread remains anywhere in `app/conversation/`.**

---

## Phase 6 — Compliance & Audit: Per-Tenant Export and Metering

```yaml
phase_id: phase_6
branch: feature/compliance-audit
depends_on: [phase_5]
status: complete
```

### Tasks

**6.1 — Org data export endpoint**
- File: `app/api/compliance.py` (new file)
- Add `GET /api/v1/org/{org_id}/export`, restricted to `org_admin` role via the Phase 3 `resolve_access` resolver.
- Bundle: all `documents` rows + underlying S3 objects, all `audit_events` rows, all `conversations` + `conversation_turns` rows for the given `org_id`, into a single downloadable archive (zip).

**6.2 — Cascading org deletion**
- File: `app/api/org.py` (new file, or extend org management module if one exists from Phase 1/2)
- Add `DELETE /api/v1/org/{org_id}`, `org_admin`-only, requiring an explicit confirmation token in the request body (e.g. `{"confirm": "DELETE-<org_id>"}`) to prevent accidental calls.
- Deletion order (must be exact — deleting Postgres rows first and failing partway through Qdrant/S3 cleanup would leave orphaned vector/storage data with no way to find it again):
  1. Delete all vector points/records where `org_id` matches (via the `vector_store.py` namespace/filter interface from Phase 4, not a direct client call).
  2. Delete all S3 objects under the `{org_id}/` prefix.
  3. Delete all Postgres rows for that `org_id` (RLS-scoped delete, relying on the cascading FKs defined in Phase 2's schema).

**6.3 — Usage metering**
- File: `app/observability/metrics.py` (new file)
- On every query and every document ingestion, increment per-org counters: `queries_this_month`, `documents_indexed`, `storage_bytes_used`. Store in a new `usage_counters` table (`org_id`, `metric_name`, `value`, `period_start`) via a new Alembic migration.
- Expose via `GET /api/v1/audit/stats` (extend the existing endpoint from the demo rather than creating a duplicate).

**6.4 — Request correlation logging**
- File: `app/middleware/logging.py` (new file)
- Add middleware that attaches `org_id` and a generated `request_id` to every log line for the duration of the request (use `contextvars`, not a global, to avoid cross-request leakage under concurrent execution).

### Verification

```bash
pytest tests/test_compliance.py::test_export_contains_only_own_org_data -v
pytest tests/test_compliance.py::test_delete_org_leaves_zero_residue -v
pytest tests/test_metrics.py -v
```

**Phase 6 is complete only if all three test commands pass, with `test_delete_org_leaves_zero_residue` specifically verifying zero remaining rows/points/objects across Postgres, Pinecone, and S3 after deletion.**

---

## Phase 7 — Platform Superuser: Postgres BYPASSRLS Role

```yaml
phase_id: phase_7
branch: feature/platform-superuser
depends_on: [phase_2]
status: complete
```

### Rationale (one line, for context only)
An operator account needs to see/manage every org for support, billing, and incident response. No role value inside an org-scoped table (`team_memberships.role`, `ROLE_PERMISSIONS_V2`) can grant this, because every such table — including `organizations` itself — is `FORCE ROW LEVEL SECURITY`-scoped to one `org_id` at a time. This phase adds a narrow, Postgres-enforced escape hatch rather than extending RBAC into a layer it was never designed to cross.

### Discovery findings folded into this phase (pre-implementation)

Repo inspection ahead of this phase found no existing platform-admin scaffolding anywhere in the codebase — worth stating explicitly so the executing agent doesn't waste a cycle re-deriving it:

1. `app/auth/rbac.py`'s `ROLE_PERMISSIONS_V2` (Phase 3) is entirely org-scoped. There is no role string meaning "every org," and adding one wouldn't work regardless — RLS filters rows before `resolve_access` ever runs, per Phase 3's own design.
2. `organizations` itself carries `FORCE ROW LEVEL SECURITY` from Phase 2's `0002_enable_rls.py`. A session with no `app.current_org_id` set cannot `SELECT` from `organizations` at all — there's a chicken-and-egg problem for any cross-org operation that a policy-level `OR` clause would require touching *every* existing Phase 2/3/4 policy to fix. A `BYPASSRLS` role avoids modifying any of that.
3. `get_current_user`/`get_db` (Phase 1/2) never insert a `users` row implicitly — the only precedent for out-of-band row creation is a manually-run seed script (Phase 3's `scripts/seed_team_memberships.py`). This phase's bootstrap script follows that same precedent rather than adding implicit creation to request-time code.
4. The compliance endpoints added in Phase 6 (`/api/v1/org/{org_id}/export`, `DELETE /api/v1/org/{org_id}`) are `org_admin`-scoped — an `org_admin` can only export/delete *their own* org. Nothing today lets an operator act across orgs, which is the actual gap this phase closes; Phase 7 does not modify Phase 6's endpoints, it adds a separate admin-only surface.

### Tasks

**7.1 — Create `aegis_platform_admin` Postgres role + `platform_admins` table**
- File: `alembic/versions/0005_platform_admin_bypass.py` (new migration — confirm the actual latest revision id on `main` before setting `down_revision`; Phase 6 likely added its own `usage_counters` migration, so chain after whichever migration is truly last, not assumed to be `0004`)
- Create the role idempotently (`DO $$ ... IF NOT EXISTS ... $$`) with `LOGIN BYPASSRLS` — not `SUPERUSER`, which would be a strictly wider grant than needed.
- Grant `ALL PRIVILEGES ON ALL TABLES IN SCHEMA public` plus `ALTER DEFAULT PRIVILEGES ... GRANT ALL ON TABLES`, so tables added by Phase 6 (`usage_counters`) and any future migration are automatically visible without a follow-up grant.
- Do **not** set a password in the migration file. Set it once, manually, via `ALTER ROLE aegis_platform_admin WITH PASSWORD '...'` outside version control.
- Create `platform_admins(id uuid pk, auth0_sub text unique not null, email text not null, created_at timestamptz default now(), is_active boolean not null default true)`. No RLS on this table — every access path to it goes through the bypass connection anyway, so RLS here adds no isolation value and would be circular.
- Down-migration: revoke grants, `DROP ROLE IF EXISTS aegis_platform_admin`, `DROP TABLE platform_admins`.

**7.2 — Second engine + session factory for the bypass role**
- File: `app/db/session.py` (modify existing — add alongside `engine`/`tenant_scoped_session`, do not restructure the existing tenant-scoped path)
- Add `PLATFORM_ADMIN_DATABASE_URL` env var (same host/port/database as `DATABASE_URL`, different role/password). Add placeholder to `.env.example`.
- Add a second `create_async_engine` bound to this URL, small pool (`pool_size=2, max_overflow=0` — this path is admin-only, low-volume) with its own `async_sessionmaker`.
- The bypass session factory does **not** call `SET LOCAL app.current_org_id` — irrelevant for a `BYPASSRLS` connection, and setting it anyway would be misleading dead code.

**7.3 — Gate dependency in `deps.py`**
- File: `app/api/deps.py` (modify existing — add alongside `get_current_user`/`get_db`)
- Add `get_platform_admin_db(claims: dict = Depends(get_current_context), session: AsyncSession = Depends(<7.2's bypass session dependency>))`.
- Check the JWT's `roles` claim for a `platform_admin` value; raise `HTTPException(403, ...)` if absent, **before** the bypass session is used for anything. This must reject even a syntactically valid `platform_admin`-claimed token if no matching `platform_admins` row exists yet — the DB-level check and the claim-level check are two independent layers, not one.
- Kept as a separate dependency, not a flag on `get_db` — mixing a rare, high-privilege path into the hot-path dependency used by every request is exactly the accidental-widening this phase exists to avoid.

**7.4 — Auth0 dashboard: create operator user + grant claim**
- Action: manual, outside codebase, same convention as Phase 1's 1.1/1.3/1.7.
- Create a dedicated Auth0 user for the platform operator (own login, not a role grant layered onto an existing account).
- Set `app_metadata: {"roles": ["platform_admin"]}` — confirm this merges correctly with the live Post-Login Action's existing claim shape (the checked-in `docs/auth0_action.js` may be stale relative to the dashboard; verify against the live Action, not the file).

**7.5 — Bootstrap script**
- File: `scripts/bootstrap_platform_admin.py` (new file, same idiom as `scripts/seed_team_memberships.py`)
- Reads `PLATFORM_ADMIN_AUTH0_SUB` and `PLATFORM_ADMIN_EMAIL` from the environment.
- Inserts into `platform_admins` via the bypass session factory, using `INSERT ... ON CONFLICT (auth0_sub) DO NOTHING` — idempotency requirement, consistent with every other bootstrap script in this plan (2.4, 4.4).

**7.6 — Platform-admin routes: cross-org visibility**
- File: `app/api/platform_admin.py` (new file)
- Add `GET /api/v1/platform/orgs` (list every org, bypassing RLS) and `GET /api/v1/platform/orgs/{org_id}/summary` (basic health: user count, document count, last activity), both gated exclusively by `get_platform_admin_db` from 7.3.
- Do not add write/delete operations in this task — Phase 6's `org_admin`-scoped delete/export already exists; this phase's initial surface is read-only cross-org visibility. A future phase can add cross-org write operations once the read path has proven itself in practice.

**7.7 — Adversarial test suite**
- File: `tests/test_platform_admin.py` (new file, same structural pattern as `tests/test_tenant_isolation.py`)
- Add:

```python
def test_platform_admin_sees_all_orgs(org_a_ctx, org_b_ctx, platform_admin_ctx):
    seed_org(org_a_ctx.org_id)
    seed_org(org_b_ctx.org_id)
    orgs = platform_admin_list_orgs(platform_admin_ctx)
    assert org_a_ctx.org_id in {o.id for o in orgs}
    assert org_b_ctx.org_id in {o.id for o in orgs}
    # Structural check: true because BYPASSRLS makes org_id filtering
    # inapplicable, not because every row happens to carry a matching flag.

def test_non_platform_admin_claim_rejected(org_a_ctx):
    with pytest.raises(HTTPException) as exc:
        get_platform_admin_db(claims=org_a_ctx.claims, session=...)
    assert exc.value.status_code == 403

def test_bypass_session_never_used_outside_admin_routes():
    # Static check: get_platform_admin_db must not appear as a Depends()
    # anywhere under app/api/routes.py, app/api/compliance.py, or app/api/org.py.
    ...

def test_bootstrap_script_idempotent():
    run_bootstrap_script()
    run_bootstrap_script()
    assert count_platform_admins_with_sub(TEST_SUB) == 1
```

- `test_non_platform_admin_claim_rejected` is a standing regression guard: it must keep passing even as future phases broaden `ROLE_PERMISSIONS_V2` — a widened org-scoped role must never accidentally satisfy this gate.

### Verification

```bash
# 1. Bypass role structurally sees cross-org data
pytest tests/test_platform_admin.py::test_platform_admin_sees_all_orgs -v

# 2. Non-platform-admin tokens rejected before touching the bypass session
pytest tests/test_platform_admin.py::test_non_platform_admin_claim_rejected -v

# 3. No other route wires the bypass dependency in
pytest tests/test_platform_admin.py::test_bypass_session_never_used_outside_admin_routes -v
grep -rn "get_platform_admin_db" app/api/ | grep -v "app/api/deps.py" | grep -v "platform_admin.py" ; test $? -ne 0

# 4. Bootstrap script is safe to re-run
pytest tests/test_platform_admin.py::test_bootstrap_script_idempotent -v

# 5. Existing tenant isolation across all layers is untouched
pytest tests/test_tenant_isolation.py -v
pytest tests/test_compliance.py -v
```

**Phase 7 is complete only if all five verification steps pass, with (3)'s grep confirming the bypass dependency is wired into `platform_admin.py` and nowhere else, and (5) confirming this phase made zero changes to Phase 2–6 behavior — this phase must be purely additive, not a modification of the existing tenancy or compliance model.**

---

## Phase 8 — Org-Scoped RBAC: Per-Organization Role Definitions

```yaml
phase_id: phase_8
branch: feature/org-scoped-rbac
depends_on: [phase_3]
status: not_started
```

### Rationale (one line, for context only)
`ROLE_PERMISSIONS_V2` (Phase 3) is a single Python dict shared by every org on
the platform — two orgs cannot have different roles, and the same role name
cannot mean different things for different orgs. Different customers have
genuinely different org structures and compliance needs; this phase moves
role definitions from a hardcoded module constant into per-org, database-backed
configuration.

### Discovery findings folded into this phase (pre-implementation)

1. `ROLE_PERMISSIONS_V2` is defined once, at module scope, in `app/auth/rbac.py`,
   with no `org_id` dimension anywhere in it. `resolve_access` step 4
   (`ROLE_PERMISSIONS_V2[membership.role]`) looks this up by role name alone —
   `acme-corp`'s `compliance_officer` and `globex-inc`'s `compliance_officer`
   necessarily resolve to the identical permission set today, because there is
   only one dict, not one per org.
2. `team_memberships.role` is a free-text column (added in Phase 2's
   `0001_tenancy_schema.py`) with no foreign key or check constraint tying it
   to a defined set of valid roles per org. This means the schema already
   permits an org-specific role name to be assigned to a membership — it's
   only `resolve_access`'s hardcoded lookup that prevents it from resolving to
   anything meaningful. This phase closes that gap rather than widening the
   schema further.
3. This phase changes step 4 of `resolve_access` (defined in Phase 3, task
   3.3) and nothing else in that function — steps 1, 2, 3, and 5 (tenant
   filter, membership lookup, expiry check, `resource_grants` fallback) are
   unaffected and must not be touched by this phase's tasks.
4. Two existing orgs (`acme-corp`, `globex-inc`) currently rely on the global
   `ROLE_PERMISSIONS_V2` values. This phase must backfill both orgs with
   their current effective permissions before removing the global dict, so
   that no existing user's access silently changes as a side effect of this
   migration. This is a correctness requirement, not just good practice —
   test 8.6 below exists specifically to catch a bad backfill.

### Tasks

**8.1 — Create `org_role_permissions` table**
- File: `alembic/versions/0006_org_role_permissions.py` (new migration —
  confirm the actual latest revision id on `main` before setting
  `down_revision`; do not assume it is `0005`, since Phase 6/7 migrations may
  have landed in an order this plan doc doesn't fully capture)
- Columns: `id (uuid, pk)`, `org_id (uuid, fk -> organizations.id)`,
  `role_name (text)`, `allowed_data_sources (jsonb)` — a JSON array of data
  source type strings, or the literal `["*"]` for full access, mirroring
  `ROLE_PERMISSIONS_V2`'s existing `{"*"}` convention so the semantics carry
  over exactly. `created_at (timestamptz, default now())`,
  `updated_at (timestamptz, default now())`.
- Unique constraint on `(org_id, role_name)` — one definition per role name
  per org, no duplicates.
- Enable RLS with the same `tenant_isolation` policy pattern as every other
  `org_id`-bearing table since Phase 2 — this table is exactly the kind of
  data that must not leak across orgs (one org's custom role definitions are
  not another org's business).
- Down-migration: drop the RLS policy, then drop the table.

**8.2 — Backfill existing orgs with current global permissions**
- File: `scripts/backfill_org_role_permissions.py` (new file, same idiom as
  `scripts/seed_team_memberships.py` and `scripts/migrate_sqlite_to_pg.py`)
- For every existing org (at minimum `acme-corp` and `globex-inc`, and any
  other org present in `organizations` at run time — do not hardcode just
  the two demo orgs), insert one `org_role_permissions` row per key in the
  current `ROLE_PERMISSIONS_V2` dict, translating `{"*"}` to `["*"]` and
  each other set to a JSON array of its members.
- Idempotency requirement, consistent with every other migration/seed script
  in this plan: use `INSERT ... ON CONFLICT (org_id, role_name) DO NOTHING`,
  so running this script twice does not error or duplicate rows.
- This script must run and be verified (task 8.6's backfill test) **before**
  8.4 removes `ROLE_PERMISSIONS_V2` — per the "earlier phases run old and new
  paths side by side" rule from the top-level instructions, both the global
  dict and the new per-org table exist simultaneously until the cutover task
  confirms the new path is correct.

**8.3 — Update `resolve_access` step 4 to read per-org permissions**
- File: `app/auth/rbac.py` (modify existing — same file as Phase 3's 3.2/3.3;
  do not create a second RBAC module)
- Replace the step 4 lookup:
  ```python
  # Before (Phase 3):
  allowed = ROLE_PERMISSIONS_V2.get(membership.role, set())

  # After (this phase):
  allowed = get_org_role_permissions(ctx["org_id"], membership.role)
  ```
- Implement `get_org_role_permissions(org_id: str, role_name: str) -> set[str]`
  as a DB lookup against `org_role_permissions` (RLS-scoped automatically via
  the existing tenant-scoped session, consistent with how every other lookup
  in `resolve_access` already works — no new session-scoping mechanism is
  needed here).
- **Fallback behavior, explicit and deliberate:** if no row exists for
  `(org_id, role_name)` — e.g. an org that has not yet defined any custom
  roles — fall back to `ROLE_PERMISSIONS_V2.get(role_name, set())` rather than
  returning an empty set outright. This keeps any org that hasn't touched
  role configuration behaviorally identical to today, and is the reason
  `ROLE_PERMISSIONS_V2` is not deleted in this task (see 8.4).
- Do not alter steps 1, 2, 3, or 5 of `resolve_access` in this task — this is
  a narrow, single-step change, matching the discipline Phase 3's 3.3
  established ("each step may only narrow access, never widen it").

**8.4 — Org role management endpoints**
- File: `app/api/org_roles.py` (new file)
- Add, all `org_admin`-only via the existing `resolve_access(ctx, "*",
  team_id=None)` org-wide admin check (same pattern Phase 3's 3.4 established
  for the delete route — do not invent a second admin-check helper):
  - `GET /api/v1/org/{org_id}/roles` — list all `org_role_permissions` rows
    for the org (falling back to `ROLE_PERMISSIONS_V2`'s keys, with a flag
    indicating "default" vs. "custom", if the org has not defined any of its
    own yet).
  - `POST /api/v1/org/{org_id}/roles` — create or update a role definition
    (`role_name`, `allowed_data_sources`), upserting into
    `org_role_permissions`.
  - `DELETE /api/v1/org/{org_id}/roles/{role_name}` — remove a custom role
    definition, reverting that role name to the global `ROLE_PERMISSIONS_V2`
    fallback (via 8.3's fallback logic) rather than to "no access" — deleting
    a customization should not silently lock out every member who holds that
    role.
- Guard against removing or renaming a role that is still assigned to at
  least one active (non-expired) `team_memberships` row without an explicit
  confirmation flag in the request body — same defensive pattern as Phase
  6's `DELETE /api/v1/org/{org_id}` confirmation-token requirement.

**8.5 — Remove global dict only once per-org path is proven**
- File: `app/auth/rbac.py` (same file)
- **Do not remove `ROLE_PERMISSIONS_V2` in this phase.** Unlike Phase 3's
  3.4, which had a clear cutover point (all four call sites migrated), this
  phase's fallback behavior (8.3) means the global dict remains a permanent,
  intentional part of the design — it is the platform-wide default for any
  org that has not customized a given role, not legacy code awaiting
  deletion. Document this explicitly in a comment above the dict so a future
  agent does not mistake it for dead code and remove it.

**8.6 — Adversarial and regression test suite**
- File: `tests/test_org_rbac.py` (new file, same structural pattern as
  `tests/test_rbac.py` from Phase 3)
- Add:

```python
def test_same_role_name_different_permissions_per_org(org_a_ctx, org_b_ctx):
    set_org_role(org_a_ctx.org_id, "compliance_officer", ["compliance_records"])
    set_org_role(org_b_ctx.org_id, "compliance_officer", ["compliance_records", "financial_db"])
    assert resolve_access(org_a_ctx_as("compliance_officer"), "financial_db", team_id=T) is False
    assert resolve_access(org_b_ctx_as("compliance_officer"), "financial_db", team_id=T) is True
    # The critical assertion: identical role name, genuinely different
    # effective permissions, because org_id is now part of the lookup key.

def test_backfill_preserves_existing_access(org_a_ctx):
    # Regression guard: an org that existed before this phase must see
    # zero change in effective permissions immediately after backfill.
    for role, expected in ROLE_PERMISSIONS_V2.items():
        assert get_org_role_permissions(org_a_ctx.org_id, role) == expected

def test_org_without_custom_roles_falls_back_to_global(org_c_ctx):
    # org_c_ctx is a freshly created org with no org_role_permissions rows.
    assert get_org_role_permissions(org_c_ctx.org_id, "employee") == {"public_policies"}

def test_deleting_custom_role_reverts_to_fallback_not_lockout(org_a_ctx):
    set_org_role(org_a_ctx.org_id, "employee", ["public_policies", "system_metrics"])
    delete_org_role(org_a_ctx.org_id, "employee", confirm=True)
    assert get_org_role_permissions(org_a_ctx.org_id, "employee") == {"public_policies"}

def test_custom_role_definitions_do_not_leak_across_orgs(org_a_ctx, org_b_ctx):
    set_org_role(org_a_ctx.org_id, "quality_inspector", ["compliance_records"])
    roles_b = list_org_roles(org_b_ctx.org_id)
    assert "quality_inspector" not in {r.role_name for r in roles_b}
```

- `test_backfill_preserves_existing_access` is the load-bearing regression
  test for this entire phase — per the discovery finding above, a bad
  backfill is the single most likely way this phase silently breaks existing
  users' access.

### Verification

```bash
# 1. Same role name genuinely means different things per org
pytest tests/test_org_rbac.py::test_same_role_name_different_permissions_per_org -v

# 2. Backfill did not change any existing org's effective permissions
pytest tests/test_org_rbac.py::test_backfill_preserves_existing_access -v

# 3. Orgs with no customization behave exactly as before this phase
pytest tests/test_org_rbac.py::test_org_without_custom_roles_falls_back_to_global -v

# 4. Deleting a customization reverts to default, never to lockout
pytest tests/test_org_rbac.py::test_deleting_custom_role_reverts_to_fallback_not_lockout -v

# 5. Custom role definitions are tenant-isolated like every other org_id-scoped table
pytest tests/test_org_rbac.py::test_custom_role_definitions_do_not_leak_across_orgs -v

# 6. Existing Phase 3 RBAC suite still passes unmodified — steps 1/2/3/5 of
#    resolve_access were not touched by this phase
pytest tests/test_rbac.py -v

# 7. Confirm ROLE_PERMISSIONS_V2 still exists (fallback, not dead code) but
#    is only referenced from within rbac.py itself, not directly from routes
grep -rn "ROLE_PERMISSIONS_V2" app/ --include="*.py" | grep -v "app/auth/rbac.py" ; test $? -ne 0
```

**Phase 8 is complete only if all seven verification steps pass, with (2)
specifically confirming zero regression for `acme-corp`/`globex-inc`'s
existing users, and (7) confirming the global dict survives as an internal
fallback rather than being deleted or bypassed by any route calling it
directly.**

---

## Final repository-wide check (run after Phase 8 merges)

```bash
# No legacy code paths should remain
grep -r "sqlite3\|qdrant\|milvus" app/ --include="*.py" ; test $? -ne 0

# Bypass role/URL never referenced outside its own module
grep -rln "aegis_platform_admin\|PLATFORM_ADMIN_DATABASE_URL" app/ \
  | grep -v "app/db/session.py" | grep -v "app/api/deps.py" ; test $? -ne 0

# No route module other than platform_admin.py imports the bypass dependency
grep -rn "get_platform_admin_db" app/api/routes.py app/api/compliance.py app/api/org.py ; test $? -ne 0

# ROLE_PERMISSIONS_V2 remains an internal fallback only, not referenced
# directly by any route
grep -rn "ROLE_PERMISSIONS_V2" app/ --include="*.py" | grep -v "app/auth/rbac.py" ; test $? -ne 0

# Full test suite, all phases
pytest tests/ -v

# Full cross-tenant isolation suite, all layers
pytest tests/test_tenant_isolation.py -v

# Full org-scoped RBAC suite
pytest tests/test_org_rbac.py -v
```

If any of these fail, do not consider the migration complete — identify which phase's verification was insufficient and add a regression test before resolving.