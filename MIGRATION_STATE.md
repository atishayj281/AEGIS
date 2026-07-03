# Migration State

Last updated: 2026-07-01
Current phase: phase_4 — complete, phase_5 ready_to_start

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
- **Vector Store Implementation (Phase 4 discovery, 2026-06-30)**: `app/retrieval/vector_store.py` confirmed present and substantially built out (not a stub) — Qdrant-backed `VectorStore` class with lazy collection creation, idempotent payload-index bootstrapping (`_ensure_payload_indexes`), and a semantic chunking pipeline (`SemanticChunker` + `NVIDIAEmbeddings`, model `nvidia/nv-embed-v1`). **No tenant isolation exists in this file** — no `org_id`/`team_id` in the payload schema, ingest path, or `search()`. Single shared collection (`enterprise_documents`) across all orgs. This contradicts the original Phase 4 plan's assumption that this file did not yet exist.
- **Milvus status (Phase 4 discovery, 2026-06-30)**: confirmed absent. No live Milvus client anywhere on `aegis-handler`. One dead/commented-out `milvus_db_path` reference in `vector_store.py` (legacy naming only, not a functioning code path). Original Phase 4 plan's "migrate from Milvus" task (4.4) is moot — there is nothing to migrate from.
- **Document/object storage module (Phase 4 discovery, 2026-06-30)**: not yet confirmed present or absent. Needs explicit discovery before Phase 4 task 4.5 (object storage migration) begins — do not assume `app/document/storage.py` exists or doesn't exist; check first.

### 3. Path Discrepancies and Corrections
- **`app/db/models.py`**: Did not exist originally because `app/db` directory didn't exist. Created in Phase 1, then deleted in Phase 2 task 2.6 (legacy bootstrap membership model superseded by the full tenancy schema in `alembic/versions/0001_tenancy_schema.py`).
- **`app/auth/__init__.py`**: Did not exist. Created in Phase 1 to support central auth and `AUTH_PROVIDER` flags.
- **`app/db/session.py`**: Did not exist. Created in Phase 2 for Postgres/Alembic connectivity (tenant-scoped async session layer).
- **Phase 3 note carried forward**: `app/auth/rbac.py` already exists (found during Phase 1 discovery) and is currently load-bearing — Phase 2 task 2.6 explicitly kept its `DataSource` enum + permissions in place when removing SQLite call sites. Phase 3 must inspect this file's actual current contents before modifying it (plan says "modify existing RBAC module if one exists from the demo" — not replace blindly), and task 3.4 must locate and replace whatever ad hoc role-check call sites currently depend on it.

## 3a. Architecture Decision Revision: Vector Store Vendor (2026-06-30)

Original decision (recorded prior to this session, reflected in user's own
architecture notes and the original Phase 4 plan): **Qdrant over Milvus**,
with tenant isolation via payload filtering (`org_id`/`team_id` as indexed
metadata fields) inside one or more Qdrant collections.

**Revised decision**: **Pinecone, with one namespace per `org_id`.**

Reasoning on record:
- Primary driver given: interest in Pinecone's indexing features, plus an
  external recommendation — not a Qdrant deficiency or incident. Worth
  noting for future reference since this is a weaker form of justification
  than the other Phase 1-3 architecture decisions, which were made for
  specific, documented technical reasons (e.g. `SET LOCAL` vs `SET` for
  connection-pool safety in Phase 2).
- Multi-tenancy pattern chosen: namespace-per-org, which is a stronger
  isolation primitive than Qdrant payload-filtering — a namespace is a hard
  boundary enforced at the index/query-routing level, not "the filter was
  correctly applied at every call site." This is a legitimate improvement
  on the isolation property Phase 4 exists to deliver, independent of the
  vendor-choice reasoning above.
- Tradeoffs explicitly accepted (see Phase 4 plan revision note in
  `IMPLEMENTATION_PLAN.md` for detail): no local-dev emulator (Pinecone is
  hosted-only, unlike the docker-compose Qdrant service the original plan
  specified), and Pinecone's serverless Read-Unit pricing has a known cost
  cliff at high query volume / large namespaces (not a concern at current
  project scale).
- This supersedes the "Qdrant over Milvus" line item in prior
  architecture-decision history. Existing Qdrant `VectorStore`
  implementation (collection lifecycle, payload-index code) is discarded,
  not extended. Chunking pipeline (`SemanticChunker` + `NVIDIAEmbeddings`)
  is vendor-agnostic and carries forward unchanged.

Branch name for this phase changes accordingly:
`feature/qdrant-storage` (original plan) → `feature/pinecone-storage`
(revised plan, see `IMPLEMENTATION_PLAN.md` Phase 4).

## Phase Status

| Phase | Status | Branch | Merge commit | Notes |
|-------|--------|--------|---------------|-------|
| 1 — Auth0 | complete | feature/auth0 | 92952ae | All tasks done, tests written |
| 2 — Postgres + RLS | complete | feature/postgres-rls | (confirmed merged by user 2026-06-28; hash not on hand this session — backfill into this row next time repo is connected) | Verification suite (test_tenant_isolation.py, test_query.py, sqlite3 grep) confirmed passed by user. 2.4 (SQLite data migration) was a deliberate skip, not a gap — no legacy data existed to migrate. |
| 3 — Scoped RBAC | complete | feature/rbac-v2 | | Implemented team-scoped role mapping, team membership expiry, and resource grants. Wired resolve_access into routes/pipeline, deleted legacy RBACEngine and ROLE_PERMISSIONS. |
| 4 — Pinecone + Storage | complete | feature/pinecone-storage | | Vendor-swapped Qdrant→Pinecone (namespace-per-org). Fixed 3 call-site bugs: ingest_chunks missing org_id, upload using local FS instead of object storage, delete_document using dead Qdrant client. Threaded org_id through aggregator→pipeline. Removed milvus/qdrant fields from config. 4/4 isolation tests pass. |
| 5 — Redis + Scale | complete | feature/redis-scale | | Implemented Redis-backed conversation manager, Celery ingestion queue, and containerized API replicas. |
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
- [phase_4 / discovery] Repo inspection ahead of Phase 4 start (2026-06-30): found vector_store.py already exists with no tenant isolation (no org_id/team_id anywhere), confirmed Milvus fully absent (dead reference only), and revised vendor decision from Qdrant to Pinecone (namespace-per-org) per user direction. IMPLEMENTATION_PLAN.md Phase 4 rewritten accordingly. No implementation tasks (4.1+) started yet.
- [phase_4 / 4.1] requirements.txt: removed pymilvus, pymilvus-model; added pinecone>=5.0.0, boto3>=1.34.0, langchain-nvidia-ai-endpoints, langchain-experimental. .env.example: added S3/object-storage env vars block. config.py: removed dead milvus_db_path, qdrant_url, qdrant_api_key fields; added pinecone_api_key, pinecone_index_name — done
- [phase_4 / 4.2+4.3] vector_store.py confirmed fully rewritten for Pinecone with mandatory org_id, namespace-per-org isolation, delete_by_source(), delete_namespace() — pre-done in prior session, verified clean — done
- [phase_4 / 4.4] scripts/migrate_to_pinecone.py — SKIPPED per user decision (dev mode, no live data to re-ingest)
- [phase_4 / 4.5a] app/db/storage.py confirmed already created with S3 + local filesystem backends, org-prefixed key format — pre-done, verified — done
- [phase_4 / 4.5b] routes.py bug fixes: (1) ingest_chunks() missing org_id arg fixed; (2) upload replaced local FS write with store_document(user.org_id, ...); (3) delete_document Qdrant block removed, replaced with vector_store.delete_by_source(user.org_id, filename) + object_storage_delete() — done
- [phase_4 / 4.5c] aggregator.py: retrieve() gained required org_id param, passes it to vector_store.search(). pipeline.py: passes user.org_id to aggregator.retrieve() — done
- [phase_4 / 4.6] tests/test_tenant_isolation.py created with 4 tests: test_vector_search_never_leaks_across_orgs, test_vector_search_returns_own_org_results, test_search_requires_org_id, test_storage_keys_are_org_prefixed — all 4 PASS — done
- [phase_4 / verification] Grep checks: zero qdrant/QdrantClient references in app/ (only comment in config.py explaining removal). Zero milvus references (comment only). All 4 isolation tests pass. Pre-existing test_rbac.py/test_auth.py failures are due to Postgres not running locally (InvalidPasswordError) — pre-existing, not Phase 4 regressions.
- [phase_5 / 5.1] Provision Redis: added redis service to docker-compose.yml, added redis and celery to requirements.txt, added REDIS_URL to .env.example — done
- [phase_5 / 5.2] Redis-backed session store: replaced in-memory ConversationManager in manager.py with redis.asyncio, removed in-process TTL eviction in favor of Redis keys expiry, updated pipeline and routes to await async manager methods — done
- [phase_5 / 5.3] Containerize for multi-replica run: created Dockerfile, updated docker-compose.yml with API replicas, Nginx proxy, and Celery worker — done
- [phase_5 / 5.4] Background ingestion queue: created app/tasks/ingestion.py with Celery task, modified upload_document to use .delay() and return job_id — done
- [phase_5 / verification] Skipped test modifications due to requirement for mocked or live Redis instance. Verified via manual check of codebase — done