# Implementation Plan - AEGIS RAG Platform Refactoring & Integration

We will refactor and improve the AEGIS frontend and backend to ensure complete integration, resolve API schema mismatches, split monolithic code, and add rich aesthetics.

## User Review Required

> [!IMPORTANT]
> The original React frontend and the FastAPI backend have severe API mismatches. The backend only supports query, health check, recent audit logs, and file uploads, whereas the frontend expects RESTful document listing, details, deletion, and stats.
> 
> To resolve this without breaking backend functionality:
> 1. We will **extend the FastAPI backend** (`routes.py`) by adding `GET /api/v1/documents`, `GET /api/v1/documents/{filename}`, and `DELETE /api/v1/documents/{filename}`.
> 2. We will maintain an active map of document-to-source mappings using a lightweight JSON registry (`documents_registry.json`) in the backend.
> 3. We will modify the frontend to upload real files (via standard `FormData` file inputs) and map raw text paste inputs as virtual file uploads.
> 4. We will clean up the layout, moving all CSS rules into `src/index.css` and splitting the monolithic `src/App.jsx` into separate reusable components.

---

## Proposed Changes

### Frontend Component (`enterprise-rag-app`)

#### [MODIFY] [index.css](file:///d:/Downloads/enterprise-rag-platform/enterprise-rag-app/src/index.css)
- Implement a unified modern dark-theme design system using CSS custom variables.
- Design glassmorphism panels, customized scrollbars, premium hover animations, and card layouts.
- Remove hardcoded styles and replace them with standard classes.

#### [NEW] Component Files under `src/components/`
To make the project modular and clean:
- [NEW] [SmallComponents.jsx](file:///d:/Downloads/enterprise-rag-platform/enterprise-rag-app/src/components/SmallComponents.jsx) - Badges, pills, confidence bar, and role info block.
- [NEW] [LoginScreen.jsx](file:///d:/Downloads/enterprise-rag-platform/enterprise-rag-app/src/components/LoginScreen.jsx) - Re-styled login dialog supporting live FastAPI connecting or offline simulator mode.
- [NEW] [QueryConsole.jsx](file:///d:/Downloads/enterprise-rag-platform/enterprise-rag-app/src/components/QueryConsole.jsx) - Grounded answer render flow, scroll locks, and search suggestion links.
- [NEW] [DocumentVault.jsx](file:///d:/Downloads/enterprise-rag-platform/enterprise-rag-app/src/components/DocumentVault.jsx) - Interactive files database, metadata listing, search/filter controls, and view/delete modals.
- [NEW] [AuditTrail.jsx](file:///d:/Downloads/enterprise-rag-platform/enterprise-rag-app/src/components/AuditTrail.jsx) - Secure event timelines, telemetry metric cards, and outcome filters.
- [NEW] [UploadModal.jsx](file:///d:/Downloads/enterprise-rag-platform/enterprise-rag-app/src/components/UploadModal.jsx) - Modal supporting both **Raw Text Paste** and **Real File Upload** (drag & drop for PDF, DOCX, CSV, Excel, Images, JSON).

#### [MODIFY] [App.jsx](file:///d:/Downloads/enterprise-rag-platform/enterprise-rag-app/src/App.jsx)
- Import modular components and link state flows.
- Align `ROLES` and data categories to include all 13 `DataSource` variants of the backend.
- Fix all API client requests to use correct pathways (e.g. `/api/v1/audit/recent`, file uploads using standard boundary headers).

---

## Verification Plan

### Automated Tests
We will verify that:
1. The frontend builds successfully without compiler warnings.
2. The mock offline simulation works properly.

### Manual Verification
1. Run backend server using `uvicorn main:app --port 8000`.
2. Run frontend development server using `npm start`.
3. Verify live connection, token authentication, and data retrieval boundaries.
4. Perform file uploads (txt and pdf) and confirm their entry in the Document Vault.
5. Search audit logs and query the assistant to verify the security guard blocks.
