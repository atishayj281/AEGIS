# Migration State

Last updated: 2026-06-28T17:37:16Z
Current phase: phase_2 — complete, phase_3 ready_to_start

## Discovery Notes

### 1. Repository Status
- **Current Branch**: `semantic-chunker` (Note: We need to branch `feature/auth0` from `main` or clean/commit working tree before proceeding).
- **Current HEAD**: `3d65b27 Implemented sementic chunking instead of fixed size chunking for document store in vector db`
- **Tag status**: `pre-migration-v1` tag does not exist. It must be created on the `main` branch before any Phase 1 code changes.

### 2. Path Mappings & Discovery
- **Auth Module Location**: `app/auth/jwt_auth.py`
- **Existing RBAC Implementation**: `app/auth/rbac.py`
- **SQLite Connection Import Sites**: `app/retrieval/sql_retriever.py`
- **Current Session Store Implementation**: `app/conversation/manager.py` (in-memory, thread-safe `ConversationManager`)
- **Current Vector DB Client Usage**: `app/retrieval/vector_store.py` (Qdrant client already in use, no active Milvus client found on `semantic-chunker` branch).
- **Upload Route Location**: `app/api/routes.py` (inside the `upload_document` endpoint)

### 3. Path Discrepancies and Corrections
- **`app/db/models.py`**: Did not exist originally because `app/db` directory didn't exist. Created in Phase 1, then deleted in Phase 2 task 2.6 (legacy bootstrap membership model superseded by the full tenancy schema in `alembic/versions/0001_tenancy_schema.py`).
- **`app/auth/__init__.py`**: Did not exist. Created in Phase 1 to support central auth and `AUTH_PROVIDER` flags.
- **`app/db/session.py`**: Did not exist. Created in Phase 2 for Postgres/Alembic connectivity (tenant-scoped async session layer).
- **Phase 3 note carried forward**: `app/auth/rbac.py` already exists (found during Phase 1 discovery) and is currently load-bearing — Phase 2 task 2.6 explicitly kept its `DataSource` enum + permissions in place when removing SQLite call sites. Phase 3 must inspect this file's actual current contents before modifying it (plan says "modify existing RBAC module if one exists from the demo" — not replace blindly), and task 3.4 must locate and replace whatever ad hoc role-check call sites currently depend on it.

## Phase Status

| Phase | Status | Branch | Merge commit | Notes |
|-------|--------|--------|---------------|-------|
| 1 — Auth0 | complete | feature/auth0 | 92952ae | All tasks done, tests written |
| 2 — Postgres + RLS | complete | feature/postgres-rls | (confirmed merged by user 2026-06-28; hash not on hand this session — backfill into this row next time repo is connected) | Verification suite (test_tenant_isolation.py, test_query.py, sqlite3 grep) confirmed passed by user. 2.4 (SQLite data migration) was a deliberate skip, not a gap — no legacy data existed to migrate. |
| 3 — Scoped RBAC | complete | feature/rbac-v2 | | Implemented team-scoped role mapping, team membership expiry, and resource grants. Wired resolve_access into routes/pipeline, deleted legacy RBACEngine and ROLE_PERMISSIONS. |
| 4 — Qdrant + Storage | ready_to_start | feature/qdrant-storage | | |
| 5 — Redis + Scale | not_started | feature/redis-scale | | |
| 6 — Compliance | not_started | feature/compliance-audit | | |

## Task-Level Log
- [phase_1 / 1.1] Create Auth0 configuration placeholders in .env and .env.example — done
- [phase_1 / 1.2] Create bootstrap membership table in app/db/models.py — done
- [phase_1 / 1.3] Create Auth0 post-login Action script in docs/auth0_action.js — done
- [phase_1 / 1.4] Create internal membership lookup endpoint in app/api/internal.py — done
- [phase_1 / 1.5] Create JWT verification module in app/auth/auth0_verify.py — done
- [phase_1 / 1.6] centralize feature flag AUTH_PROVIDER and configure FastAPI dependency in app/api/deps.py — done
- [phase_1 / 1.7] Add mock-token tests for legacy & auth0 verify logic in tests/test_auth_legacy.py and tests/test_auth_auth0.py — done
- [phase_1 / 1.8] Committed feature/auth0 branch (92952ae), MIGRATION_STATE.md updated — done
- [phase_2 / 2.1] Provision Postgres + Alembic — done
- [phase_2 / 2.2] Create tenancy schema (0001_tenancy_schema.py) — done. 9 tables, org_id denormalized onto child tables for RLS-without-joins, documents.status as Postgres ENUM.
- [phase_2 / 2.3] Enable RLS (0002_enable_rls.py) — done. FORCE ROW LEVEL SECURITY required since app + Alembic share one DB role; organizations table policy filters on id (no org_id column), not org_id.
- [phase_2 / 2.4] Migrate SQLite data into Postgres — skipped. app/db/models.py confirmed no schema/data ever existed; ConversationManager confirmed ephemeral in-memory by design. Nothing to migrate.
- [phase_2 / 2.5] Tenant-scoped DB session (app/db/session.py) — done. Uses set_config(..., true), not literal SET LOCAL with a bind param (SET expects a literal, not a bound parameter). org_id validated as UUID before reaching SQL, to keep RLS's fail-closed guarantee intact for malformed claims, not just missing ones.
- [phase_2 / 2.6] Replace SQLite call sites — done. app/retrieval/sql_retriever.py and its seed data (invoices/salary_records/budget_reports) deprecated as legacy demo code, not migrated — these tables had no org_id and weren't part of the real schema. DataSource enum + RBAC permissions kept (still load-bearing, unrelated to SQLite removal). app/db/models.py deleted. scripts/ingest_data.py cleaned of stale SQLite references; also fixed a pre-existing crash bug (settings.chroma_persist_dir doesn't exist, replaced with settings.qdrant_url).
- [phase_2 / 2.7] Verification suite run by user: tests/test_tenant_isolation.py::test_sql_rls_blocks_cross_org_read, tests/test_query.py, grep -r "sqlite3" app/ (zero matches) — all confirmed PASS. feature/postgres-rls merged to main. Phase 2 marked complete 2026-06-28.
- [phase_3 / 3.0] Replace flattened role mapping with per-team role resolution — done
- [phase_3 / 3.1a] Add expires_at column to team_memberships table (0003_team_membership_expiry.py) — done
- [phase_3 / 3.1b] Create resource_grants table with RLS policy (0004_resource_grants.py) — done
- [phase_3 / 3.1] Seed test organization team memberships (seed_team_memberships.py) — done
- [phase_3 / 3.2 & 3.3] Implement ROLE_PERMISSIONS_V2 and resolve_access resolver in app/auth/rbac.py — done
- [phase_3 / 3.4] Wire resolve_access into API routes & RAG pipeline, delete legacy RBACEngine and ROLE_PERMISSIONS — done
- [phase_3 / 3.5] Verification suite (test_rbac.py) and compilation verification completed successfully — done