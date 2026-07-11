# AEGIS — Enterprise RAG Intelligence Platform (Frontend)

> **A** **G**rounded **E**nterprise **I**ntelligence **S**ystem  
> Secure, role-aware chat interface for the Enterprise RAG backend — built with React 19.

[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react)](https://react.dev)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## Overview

AEGIS is the frontend client for the [Enterprise RAG Platform](../enterprise-rag-handler/README.md). It provides a premium dark-themed UI through which enterprise employees can:

- **Query** internal documents using natural language via the AI assistant
- **Manage** the document vault — upload, preview, and delete indexed files
- **Monitor** a real-time RBAC audit trail with access-violation telemetry

The client connects to a FastAPI backend over `http://localhost:8000` but ships with a full **offline demo mode** so it runs without any backend — useful for evaluation, testing, and screenshots.

---

## Key Features

| Feature | Description |
|---|---|
| 🔐 **JWT Authentication** | Login with real credentials or launch a one-click demo session |
| 🧠 **Grounded AI Responses** | Every answer is cited from retrieved context with a confidence score |
| 🚫 **RBAC Enforcement** | Five roles — each sees only authorized data sources |
| 🛡 **Prompt Injection Guard** | Client-side pre-check + server enforcement for injection attempts |
| 📄 **Document Vault** | Grid view of indexed files with upload, preview, and delete actions |
| 📋 **Audit Trail** | Timestamped log of all queries with ALLOWED / DENIED / BLOCKED outcomes |
| 📡 **Live / Demo toggle** | Falls back gracefully to offline simulation if the backend is unreachable |
| ✨ **Offline Simulation** | Full in-browser query simulation with RBAC rules — no backend required |

---

## Tech Stack

| Layer | Technology |
|---|---|
| UI Framework | React 19 |
| Icons | Lucide React |
| Styling | Vanilla CSS (design tokens, glassmorphism, dark mode) |
| Auth | JWT (Bearer token) decoded client-side with `atob` |
| API transport | Native `fetch` — no external HTTP library |
| Build tooling | Create React App / react-scripts |

---

## Project Structure

```
enterprise-rag-app/
├── public/
│   └── index.html              # App shell
├── src/
│   ├── index.css               # Global dark theme design system & tokens
│   ├── App.jsx                 # Root — auth state, API client, nav orchestration
│   └── components/
│       ├── SmallComponents.jsx # Design tokens (C), role profiles, badges, pills
│       ├── LoginScreen.jsx     # Connect / Demo login interface
│       ├── QueryConsole.jsx    # AI chat with grounded responses & suggestions
│       ├── DocumentVault.jsx   # File registry — upload, preview, delete
│       ├── AuditTrail.jsx      # Access log timeline + telemetry cards
│       ├── UploadModal.jsx     # Drag-and-drop + raw text paste ingestion modal
│       ├── ViewModal.jsx       # Full document content preview
│       └── DeleteConfirm.jsx   # Deletion confirmation dialog
├── package.json
└── README.md
```

---

## Quick Start

### Prerequisites

- Node.js 18+ and npm

### Install & Run

```bash
# From the enterprise-rag-app directory
npm install
npm start
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

> **No backend?** Click any role card on the login screen to enter offline demo mode immediately.

---

## Connecting to the Backend

By default the app targets `http://localhost:8000`. To connect:

1. Start the backend (see [enterprise-rag-handler/README.md](../enterprise-rag-handler/README.md)):
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```
2. On the login screen, enter any of the demo credentials below and click **Connect to API**.

The connection status pill in the top-right corner shows:
- 🟢 **Connected** — live backend session
- 🟡 **Demo Mode** — offline simulation
- 🔴 **Error** — backend unreachable

---

## Demo Users & Roles

| Username | Password | Role | Access Level |
|---|---|---|---|
| `admin_user` | `admin123` | **Admin** | All data sources |
| `team_lead` | `lead123` | **Team Lead** | All data sources (scoped to own team) |
| `compliance_officer` | `compliance123` | **Compliance Officer** | Compliance records, audit logs, public policies |
| `finance_analyst` | `finance123` | **Finance Analyst** | Financial database, invoices, public policies |
| `ops_engineer` | `ops123` | **Operations Engineer** | System metrics, audit logs, public policies |
| `employee_user` | `employee123` | **Employee** | Public policies only |

> In **Demo Mode** simply click the role card — no password required.

---

## Org-Scoped Self-Service Provisioning

AEGIS supports decentralized org-scoped provisioning:
- **`org_admin`** has full access to create teams (via the **Manage Teams** tab) and provision/update/deactivate users org-wide.
- **`team_lead`** has access to provision/update/deactivate users strictly within the teams they lead.
- The **Organization UUID** input field is automatically resolved by the backend from caller context and hidden from the UI.
- Granting/promoting to `org_admin` is restricted to platform superusers.

---

## RBAC Data Source Matrix

| Data Source | Admin | Compliance | Finance | Ops | Employee |
|---|:---:|:---:|:---:|:---:|:---:|
| Compliance Records | ✅ | ✅ | | | |
| Audit Logs | ✅ | ✅ | | ✅ | |
| Financial Database | ✅ | | ✅ | | |
| Invoice Records | ✅ | | ✅ | | |
| System Metrics | ✅ | | | ✅ | |
| Salary Records | ✅ | | | | |
| Public Policies | ✅ | ✅ | ✅ | ✅ | ✅ |

---

## API Integration

The frontend communicates with the backend over these endpoints:

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/auth/token` | Authenticate and receive JWT |
| `POST` | `/api/v1/query` | Submit a natural language query |
| `GET` | `/api/v1/documents` | List all indexed documents |
| `POST` | `/api/v1/document/upload` | Upload a new document (`multipart/form-data`) |
| `DELETE` | `/api/v1/documents/{id}` | Delete a document (Admin only) |
| `GET` | `/api/v1/audit/recent` | Fetch the 20 most recent audit log entries |
| `GET` | `/api/v1/audit/stats` | Fetch aggregate telemetry metrics |

All requests (except `/auth/token`) require the `Authorization: Bearer <token>` header.

---

## Offline Simulation (Demo Mode)

When no backend is available the app runs entirely in the browser:

- **Query Console** — evaluates queries against 11 pre-loaded documents using client-side RBAC rules; detects prompt-injection patterns and responds with grounded, source-cited answers
- **Document Vault** — supports upload, preview, and delete against a local in-memory document list
- **Audit Trail** — logs every action in real time, including DENIED and BLOCKED outcomes with accurate telemetry counters

No network requests are made in demo mode.

---

## Component Architecture

```
App (auth state, API client, nav)
├── LoginScreen          — credential form + role card launcher
├── QueryConsole         — chat thread, message history, RBAC query simulation
├── DocumentVault        — searchable file grid, filter chips, action buttons
│   ├── UploadModal      — tabbed: file drag-drop | raw text paste
│   ├── ViewModal        — rendered document content viewer
│   └── DeleteConfirm    — guarded deletion dialog
└── AuditTrail           — telemetry stat cards + filterable event timeline
```

Key design decisions:
- **Stable `useRef` callbacks** — `apiClient`, `normalizeDocumentHelper`, and `normalizeLogHelper` are stabilized via `useRef` to prevent `useEffect` from re-running on every render (eliminating the continuous `listDocuments` polling bug)
- **Split effects** — `AuditTrail` uses separate effects for live API fetching (`[live, apiBase, token]`) and offline stats recalculation (`[live, logs]`), so adding local audit entries never triggers a redundant API call
- **Modular extraction** — the original 1,300-line monolith was refactored into 7 focused components, each owning its own loading/error/busy state

---

## Available Scripts

```bash
npm start          # Development server at http://localhost:3000
npm test           # Run tests in watch mode
npm run build      # Production build in /build
```

---

## Related

- **Backend** → [`enterprise-rag-handler`](../enterprise-rag-handler/README.md) — FastAPI + Milvus + SQLite RAG pipeline
- **GitHub** → [atishayj281/AEGIS](https://github.com/atishayj281/AEGIS) (branch: `aegis-client`)

---

## License

MIT — For evaluation and demonstration purposes.
