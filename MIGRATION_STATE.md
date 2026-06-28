# Migration State

Last updated: 2026-06-25T11:22:00Z
Current phase: phase_1 — complete, phase_2 ready_to_start

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
- **`app/db/models.py`**: Does not exist because `app/db` directory doesn't exist. We will create `app/db/models.py` and the `app/db/` package.
- **`app/auth/__init__.py`**: Does not exist. We will create it to support central auth and `AUTH_PROVIDER` flags.
- **`app/db/session.py`**: Does not exist. We will create it in Phase 2 for Postgres/Alembic connectivity.

## Phase Status

| Phase | Status | Branch | Merge commit | Notes |
|-------|--------|--------|---------------|-------|
| 1 — Auth0 | complete | feature/auth0 | 92952ae | All tasks done, tests written |
| 2 — Postgres + RLS | ready_to_start | feature/postgres-rls | | |
| 3 — Scoped RBAC | not_started | feature/rbac-v2 | | |
| 4 — Qdrant + Storage | not_started | feature/qdrant-storage | | |
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