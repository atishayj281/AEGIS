# Implementation Plan — Enterprise RAG Intelligence Platform Multi-Tenancy Migration

```yaml
plan_version: 1.0
target_repo: enterprise-rag-platform
migration_type: incremental
base_branch: main
pre_migration_tag: pre-migration-v1
total_phases: 6
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
              └── phase_4 (qdrant_storage)
                    └── phase_5 (redis_scale)
                          └── phase_6 (compliance_audit)
```

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
status: not_started
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

## Phase 4 — Vector & Storage Isolation: Qdrant + Object Storage

```yaml
phase_id: phase_4
branch: feature/qdrant-storage
depends_on: [phase_3]
status: not_started
```

### Tasks

**4.1 — Provision Qdrant**
- Add a `qdrant` service to `docker-compose.yml` (image `qdrant/qdrant`) for local dev.
- Add `QDRANT_URL` to `.env.example`.
- Add `qdrant-client` to `requirements.txt`.

**4.2 — Define collections and payload schema**
- File: `app/retrieval/vector_store.py` (new file; remove/replace any existing Milvus-specific module after this phase's verification passes, not before)
- Create one collection per logical content type: `documents`, `public_policies` (adjust names to match actual content types in the existing demo's data folders).
- Every point's payload must include: `org_id` (string, indexed), `team_id` (string, indexed, nullable), `data_source_type` (string), plus existing chunk metadata fields from the current ingestion pipeline.
- Create a payload index on `org_id` and `team_id` for each collection (`client.create_payload_index(...)`).

**4.3 — Mandatory-filter search wrapper**
- File: `app/retrieval/vector_store.py` (same file as 4.2)
- Implement:

```python
def search(
    collection: str,
    query_vector: list[float],
    org_id: str,
    team_id: str | None = None,
    extra_filter: Filter | None = None,
    limit: int = 10,
):
    must = [FieldCondition(key="org_id", match=MatchValue(value=org_id))]
    if team_id:
        must.append(FieldCondition(key="team_id", match=MatchValue(value=team_id)))
    if extra_filter:
        must.extend(extra_filter.must or [])
    return client.search(
        collection_name=collection,
        query_vector=query_vector,
        query_filter=Filter(must=must),
        limit=limit,
    )
```

- `org_id` has no default value. This is intentional — omitting it must raise `TypeError` at call time, not silently search unfiltered.
- Constraint: this must be the only function in the codebase that calls `client.search(...)` directly. Search the codebase for any other direct Qdrant/Milvus client calls and route them through this function. If a call site cannot be routed through this function, stop and report why rather than adding a second unfiltered search path.

**4.4 — Migrate or re-ingest existing embeddings**
- File: `scripts/migrate_to_qdrant.py` (new file)
- Decide migration strategy by inspecting current data volume: if fewer than ~10,000 chunks exist in the current Milvus instance, re-embed from source documents in `data/documents/` rather than writing Milvus-export tooling. If volume is larger, export Milvus vectors directly and re-insert with the new payload schema.
- Every re-ingested/migrated point must be tagged with `org_id = default_org` to match Phase 2's backfill.

**4.5 — Object storage migration**
- File: `app/document/storage.py` (new or modify existing local-filesystem storage module)
- Replace local filesystem reads/writes with an S3-compatible client (`boto3`, pointed at AWS S3, Cloudflare R2, or local MinIO via `docker-compose.yml` for dev).
- Key format: `{org_id}/{data_source_id}/{filename}`. No document may be written without an `org_id` prefix — same "no default value" principle as 4.3.

**4.6 — Cross-tenant adversarial test suite**
- File: `tests/test_tenant_isolation.py` (extend the file created in Phase 2)
- Add:

```python
def test_vector_search_never_leaks_across_orgs(org_a_ctx, org_b_ctx):
    seed_document(org_a_ctx.org_id, "Q4 budget memo")
    seed_document(org_b_ctx.org_id, "Q4 budget memo")
    results = search(collection="documents", query_vector=embed("Q4 budget"), org_id=org_a_ctx.org_id)
    assert all(r.payload["org_id"] == org_a_ctx.org_id for r in results)

def test_storage_keys_are_org_prefixed(org_a_ctx):
    uri = store_document(org_a_ctx.org_id, "data_source_1", "file.pdf", b"...")
    assert uri.startswith(f"{org_a_ctx.org_id}/")
```

### Verification

```bash
pytest tests/test_tenant_isolation.py -v
grep -r "milvus" app/ --include="*.py" ; test $? -ne 0   # only after 4.4 migration confirmed complete
grep -rn "client.search(" app/ --include="*.py" | grep -v "app/retrieval/vector_store.py" ; test $? -ne 0
```

**Phase 4 is complete only if all isolation tests pass, no `milvus` references remain in `app/`, and no direct `client.search(` calls exist outside `vector_store.py`.**

---

## Phase 5 — Statefulness & Horizontal Scale: Redis

```yaml
phase_id: phase_5
branch: feature/redis-scale
depends_on: [phase_4]
status: not_started
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
status: not_started
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
  1. Delete all Qdrant points where `org_id` matches (via the `vector_store.py` filter, not a direct client call).
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

**Phase 6 is complete only if all three test commands pass, with `test_delete_org_leaves_zero_residue` specifically verifying zero remaining rows/points/objects across Postgres, Qdrant, and S3 after deletion.**

---

## Final repository-wide check (run after Phase 6 merges)

```bash
# No legacy code paths should remain
grep -r "sqlite3\|milvus" app/ --include="*.py" ; test $? -ne 0

# Full test suite, all phases
pytest tests/ -v

# Full cross-tenant isolation suite, all layers
pytest tests/test_tenant_isolation.py -v
```

If any of these fail, do not consider the migration complete — identify which phase's verification was insufficient and add a regression test before resolving.