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
