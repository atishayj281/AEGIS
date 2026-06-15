# Enterprise RAG Intelligence Platform

A secure, context-aware Retrieval-Augmented Generation (RAG) platform for querying heterogeneous enterprise data sources with strict Role-Based Access Control (RBAC).

## Features

- **Natural Language Queries** — Plain English questions across PDFs, SQL, CSV, and JSON logs
- **Multi-Format Ingestion** — Upload and index PDFs, DOCX files, CSV rows, Excel cells, JSON logs, and Images (with metadata extraction)
- **Secure Document Upload** — API-driven file upload routes protected by strict JWT and role-based validation
- **Intent Classification** — Routes queries by compliance, audit, finance, operations, and policy domains
- **Hybrid Retrieval** — Vector semantic search + SQL + CSV filtering + JSON log queries
- **RBAC Enforcement** — Five roles with granular data source permissions
- **Security Layer** — Prompt injection detection, sensitive data masking, JWT auth
- **Grounded Responses** — Source-backed answers with citations, confidence scores, and retrieval traces
- **Observability** — Audit logging, RBAC violation tracking, performance metrics

## Architecture

The platform operates on a single unified architecture integrating the secure file ingestion/parsing flow with the hybrid retrieval-augmented generation (RAG) query pipeline.

```text
                      +-------------------+            +-------------------+
                      |   User Upload     |            |    User Query     |
                      +---------+---------+            +---------+---------+
                                |                                |
                                v                                v
                      +-------------------+            +-------------------+
                      |   JWT & RBAC Check|            |Intent Classify &  |
                      +---------+---------+            |RBAC Query check   |
                                |                      +---------+---------+
                                v                                |
                      +-------------------+                      v
                      |    File Router    |            +-------------------+
                      +---------+---------+            |   Query Router    |
                                |                      +---------+---------+
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
 |  Data Folders |      |  Data Folders |      |  Data Folders | |
 |  (/documents) |      |     (/csv)    |      |    (/json)    | |
 +-------+-------+      +-------+-------+      +-------+-------+ |
         |                      |                      |         |
         v                      v                      v         |
 +-------+-------+      +-------+-------+      +-------+-------+ |
 | Vector Store  |      | SQL Database  |      |   JSON Logs   | |
 | (ChromaDB)    |      | (SQLite)      |      | (Audit/Log)   | |
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

## Quick Start

### Prerequisites

- Python 3.10+
- pip

### Installation

```bash
cd enterprise-rag-platform
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
```

### Ingest Sample Data

```bash
python scripts/ingest_data.py
```

### Run the API Server

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Open API docs at [http://localhost:8000/docs](http://localhost:8000/docs)

### Run Demo

```bash
python scripts/demo.py
```

### Run Tests

```bash
pytest tests/ -v
```

## Demo Users

| Username | Password | Role |
|----------|----------|------|
| admin_user | admin123 | Admin |
| compliance_officer | compliance123 | Compliance Officer |
| finance_analyst | finance123 | Finance Analyst |
| ops_engineer | ops123 | Operations Engineer |
| employee_user | employee123 | Employee |

## API Usage

### 1. Authenticate

```bash
curl -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username": "compliance_officer", "password": "compliance123"}'
```

### 2. Query

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the compliance requirements for customer data retention?"}'
```

### 3. Ingest/Upload Document

```bash
curl -X POST http://localhost:8000/api/v1/document/upload \
  -H "Authorization: Bearer <TOKEN>" \
  -F "file=@/path/to/policy.pdf" \
  -F "data_source=compliance_records"
```
*Note: Supported formats include PDF, DOCX, TXT, CSV, XLSX/XLS, JSON, PNG, JPG, and JPEG. Files are saved locally and immediately parsed, chunked, and embedded into ChromaDB.*

### 4. List Demo Users

Retrieves a list of credentials and roles available for testing the platform.

```bash
curl -X GET http://localhost:8000/api/v1/auth/demo-users
```

### 5. Health Check

Returns health status of the application, version number, count of currently indexed document chunks in ChromaDB, and active data sources.

```bash
curl -X GET http://localhost:8000/api/v1/health
```

### 6. Audit Stats

Retrieves aggregate audit telemetry metrics (requires authentication).

```bash
curl -X GET http://localhost:8000/api/v1/audit/stats \
  -H "Authorization: Bearer <TOKEN>"
```

### 7. Recent Audit Logs

Retrieves the 20 most recent logged events in the audit trail (requires authentication).

```bash
curl -X GET http://localhost:8000/api/v1/audit/recent \
  -H "Authorization: Bearer <TOKEN>"
```

## Sample Queries by Role

| Role | Example Query | Expected Behavior |
|------|---------------|-------------------|
| Compliance Officer | GDPR retention policy | Retrieves compliance documents |
| Operations Engineer | Failed login attempts last 24h | Queries JSON audit logs |
| Finance Analyst | Pending invoices for Vendor ABC | SQL query on invoices table |
| Employee | Executive salary information | **Access Denied** |
| Any | Ignore previous instructions... | **Security Blocked** |

## RBAC Matrix

| Data Source | Admin | Compliance | Finance | Operations | Employee |
|-------------|-------|------------|---------|------------|----------|
| Compliance Records | ✓ | ✓ | | | |
| Audit Logs | ✓ | ✓ | | ✓ | |
| Financial Database | ✓ | | ✓ | | |
| Invoice Records | ✓ | | ✓ | | |
| System Metrics | ✓ | | | ✓ | |
| Salary Records | ✓ | | | | |
| Public Policies | ✓ | ✓ | ✓ | ✓ | ✓ |

## Sample Data

```
data/
├── documents/          # Compliance, infrastructure, policy text, PDF, Word documents
├── csv/                # Server metrics (operational datasets) and Excel files
├── json/               # Audit/login logs and audit trails
├── images/             # Uploaded image files
├── rbac/users.json     # User-role mappings
└── enterprise.db       # SQLite (invoices, salaries, budgets) — auto-created
```

## Optional: LLM Integration

Set `OPENAI_API_KEY` in `.env` for GPT-powered response generation. Without it, the platform uses template-based grounded responses from retrieved context.

```env
OPENAI_API_KEY=sk-your-key
OPENAI_MODEL=gpt-4o-mini
```

## Design Decisions

1. **ChromaDB** for local vector search — unified semantic indexing of PDFs, DOCX, text logs, CSV rows, Excel files, JSON records, and Image metadata.
2. **SQLite** for structured data — portable, zero-config SQL backend
3. **Rule-based intent classification** — deterministic, explainable routing (extensible to ML models)
4. **Hybrid retrieval** — combines semantic, keyword re-ranking, and structured queries
5. **Defense in depth** — RBAC checked before retrieval; sensitive fields masked in output
6. **Template fallback** — works fully offline without API keys for demos and CI

## Project Structure

```
enterprise-rag-platform/
├── app/
│   ├── auth/           # JWT authentication & RBAC engine
│   ├── security/       # Prompt injection & data masking
│   ├── intent/         # Intent classification
│   ├── routing/        # Data source routing
│   ├── retrieval/      # Vector, SQL, CSV, JSON retrievers
│   ├── document/       # Document upload and multi-format parsers
│   ├── generation/     # Grounded response generation
│   ├── observability/  # Audit logging
│   ├── api/            # FastAPI routes
│   └── pipeline.py     # Main orchestrator
├── data/               # Sample enterprise datasets
├── scripts/            # Ingestion & demo scripts
├── tests/              # RBAC & security tests
├── main.py             # Application entry point
└── requirements.txt
```

## License

MIT — For evaluation and demonstration purposes.
