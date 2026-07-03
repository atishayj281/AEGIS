# Enterprise RAG Intelligence Platform

A secure, multi-tenant Retrieval-Augmented Generation (RAG) platform for querying heterogeneous enterprise data sources with strict tenant isolation, Auth0-based authentication, and scoped Role-Based Access Control (RBAC).

---

## Features

- **Strict Tenant Isolation** — Fully enforced at the relational database layer using Postgres Row-Level Security (RLS) policies, and at the vector layer using Pinecone namespaces (one namespace per `org_id`).
- **Auth0-Integrated JWT Verification** — Decentralized token verification using JWKS. Extracts tenant context (`org_id`, `team_ids`, and `roles`) directly from custom JWT claims.
- **Scoped RBAC Engine** — Granular permission resolution per team. Supports team-scoped roles (`org_admin`, `team_lead`, `compliance_officer`, `finance_analyst`, `operations_engineer`, `employee`, and `guest`).
- **Resource Grants & Expirations** — Temporary and granular data source access through a `resource_grants` table and time-bound `team_memberships` expirations.
- **Natural Language Queries** — Context-aware questions routed across vector data, CSVs, and JSON logs.
- **Multi-Format Ingestion** — API-driven secure upload routes for PDF, DOCX, CSV, Excel, JSON, and Images, storing raw files in S3-compatible Object Storage.
- **Multi-Turn Conversations** — Redis-backed, highly-available session management with sliding-window history limits and native TTL eviction.
- **Asynchronous Ingestion** — Celery background workers backed by Redis queue for non-blocking document ingestion and semantic chunking.
- **High Availability & Scalability** — Containerized architecture using Nginx as a reverse proxy for load balancing across multiple API replicas.
- **Security & Observability** — Inbound prompt injection defense, outbound PII/sensitive data masking, and detailed audit trails.

---

## Architecture

The platform integrates secure ingestion, multi-tenant isolation, and a context-aware RAG pipeline:

```text
                       +-------------------+            +-------------------+
                       |   User Upload     |            |    User Query     |
                       +---------+---------+            +---------+---------+
                                 |                                |
                                 v                                v
                       +-------------------+            +-------------------+
                       | Auth0 JWT & RLS   |            | Intent Classify & |
                       | Scoped RBAC Check |            | Scoped RBAC Check |
                       +---------+---------+            +---------+---------+
                                 |                                |
                                 v                                v
                       +-------------------+            +-------------------+
                       |   Storage Router  |            |   Query Router    |
                       +---------+---------+            +---------+---------+
                                 |                                |
                                 v                                |
                       +-------------------+                      |
                       |DocumentParser (PDF|                      |
                       |Docx, CSV, xls,img)|                      |
                       +---------+---------+                      |
                                 |                                |
          +----------------------+----------------------+         |
          |                      |                      |         |
          v                      v                      v         v
  +---------------+      +---------------+      +---------------+ |
  | Object Store  |      |  Data Folders |      |  Data Folders | |
  | (S3 / Local)  |      |     (/csv)    |      |    (/json)    | |
  +-------+-------+      +-------+-------+      +-------+-------+ |
          |                      |                      |         |
          v                      v                      v         |
  +-------+-------+      +-------+-------+      +-------+-------+ |
  | Vector Store  |      |   Postgres    |      |   JSON Logs   | |
  | (Pinecone)    |      |   (With RLS)  |      | (Audit/Log)   | |
  +--+---------+--+      +-------+-------+      +-------+-------+ |
     ^         |                 |                      |         |
     |         +--------+        |        +-------------+         |
     |                  |        |        |                       |
     |                  v        v        v                       |
     |                +--------------------+                      |
     | Ingests chunks | Context Aggregator <----------------------+
     +----------------+---------+----------+
                                |
                                v
                      +--------------------+
                      | Response Generator |
                      +---------+----------+
                                |
                                v
                      +--------------------+
                      |   Final Response   |
                      +--------------------+
```

---

## Quick Start

### Prerequisites

- Python 3.10+
- Docker & Docker Compose (for Postgres, Redis, API replicas, Celery, and Nginx)
- Pinecone Account & Index (Serverless, dimension 4096 for `nvidia/nv-embed-v1`)

### Installation

1. Clone the repository and set up a virtual environment:
   ```bash
   cd enterprise-rag-platform
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Start the local Postgres database:
   ```bash
   docker-compose up -d
   ```

3. Run database migrations:
   ```bash
   alembic upgrade head
   ```

4. Seed the database with multi-tenant organizations, teams, and users:
   ```bash
   python scripts/seed_team_memberships.py
   ```

5. Run the full platform (API replicas, Celery, Nginx, Redis, Postgres):
   ```bash
   docker-compose up --build -d
   ```

Open API documentation at [http://localhost/docs](http://localhost/docs). Note that Nginx runs on port 80 and load-balances the API.

### Running Tests

To run the unit test suite (including the tenant isolation and scoped RBAC verification):
```bash
pytest -v
```

---

## Seeded Users for Testing

For local development and testing, the seeding script creates the following Auth0 mock users inside the organization `acme-corp` (`00000000-0000-0000-0000-000000000001`):

| Auth0 Subject (`sub`) | Role | Active Team |
|----------------------|------|-------------|
| `auth0|admin` | `org_admin` | Engineering Team |
| `auth0|lead` | `team_lead` | Engineering Team |
| `auth0|compliance` | `compliance_officer` | HR Team |
| `auth0|finance` | `finance_analyst` | Finance Team |
| `auth0|ops` | `operations_engineer` | Engineering Team |
| `auth0|employee` | `employee` | HR Team |
| `auth0|guest` | `guest` | HR Team |

For testing endpoints, pass the corresponding mock token (`admin_token`, `employee_token`, `finance_token`, etc.) in the `Authorization` header.

---

## API Usage

### 1. Query the Platform (with optional Team Context)

To query the RAG pipeline, send a POST request with the user's mock token. You can optionally restrict the query scope to a specific `team_id` to resolve permissions under that team:

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Authorization: Bearer admin_token" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What are the compliance requirements for customer data retention?",
    "team_id": "10000000-0000-0000-0000-000000000002"
  }'
```

### 2. Multi-Turn Follow-up

To continue a conversation thread, include the `session_id` returned from the initial query:

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Authorization: Bearer admin_token" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Who is the primary contact for this policy?",
    "session_id": "session-uuid-here"
  }'
```

### 3. Ingest/Upload Document

Upload files to a specific target data source:

```bash
curl -X POST http://localhost:8000/api/v1/document/upload \
  -H "Authorization: Bearer admin_token" \
  -F "file=@/path/to/policy.pdf" \
  -F "data_source=compliance_records"
```

---

## Scoped RBAC Matrix

Permissions are resolved dynamically based on the active team context:

| Data Source | org_admin | team_lead | compliance_officer | finance_analyst | operations_engineer | employee | guest |
|-------------|-----------|-----------|--------------------|-----------------|---------------------|----------|-------|
| Compliance Records | ✓ | ✓ | ✓ | | | | (via Grant) |
| Audit Logs | ✓ | ✓ | ✓ | | ✓ | | |
| Financial Database | ✓ | ✓ | | ✓ | | | |
| Invoice Records | ✓ | ✓ | | ✓ | | | |
| System Metrics | ✓ | ✓ | | | ✓ | | |
| Salary Records | ✓ | | | | | | |
| Public Policies | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Internal Docs | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

*Note: Guests can be granted access to specific data sources via the `resource_grants` table.*

---

## Project Structure

```text
enterprise-rag-platform/
├── alembic/            # Database schema migration versions
├── app/
│   ├── auth/           # Auth0 JWT verification & Scoped RBAC engine
│   ├── security/       # Prompt injection & data masking
│   ├── intent/         # Intent classification
│   ├── routing/        # Data source routing
│   ├── retrieval/      # Vector, SQL, CSV, JSON retrievers
│   ├── conversation/   # Redis-backed session & history store
│   ├── document/       # Document upload and multi-format parsers
│   ├── generation/     # Grounded response generation
│   ├── observability/  # Audit logging
│   ├── api/            # FastAPI routes
│   ├── tasks/          # Celery background workers for asynchronous ingestion
│   └── pipeline.py     # Main orchestrator
├── data/               # Sample enterprise datasets
├── scripts/            # Database seeding & ingestion scripts
├── tests/              # Tenant isolation, RBAC, and conversation tests
├── main.py             # Application entry point
└── requirements.txt
```

---

## License

MIT — For evaluation and demonstration purposes.
