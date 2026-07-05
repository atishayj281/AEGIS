"""API route definitions."""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from pathlib import Path

from app.db.storage import store_document, delete_document as object_storage_delete

from app import __version__
from app.api.deps import (
    get_current_user,
    get_pipeline,
    get_vector_store,
    get_conversation_manager_dep,
    get_db,
    get_rate_limiter,
)
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth.rbac import resolve_access
from app.auth.jwt_auth import User
from app.models.schemas import (
    AccessDeniedResponse,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    SecurityViolationResponse,
    UploadResponse,
    SessionInfoResponse,
    ConversationTurnSchema,
)
from app.pipeline import RAGPipeline
from app.retrieval.vector_store import VectorStore
from app.models.domain import DataSource
from app.conversation.manager import ConversationManager
from app.security.rate_limiter import RateLimiter

router = APIRouter()





@router.post(
    "/query",
    response_model=QueryResponse | AccessDeniedResponse | SecurityViolationResponse,
)
async def query(
    request: QueryRequest,
    user: User = Depends(get_current_user),
    pipeline: RAGPipeline = Depends(get_pipeline),
    db: AsyncSession = Depends(get_db),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
):
    # Rate-limit check — must be first so we don't run any pipeline work for
    # requests that are already over the quota.
    allowed, count = await rate_limiter.is_allowed(
        org_id=str(user.org_id or "unknown"),
        username=user.username,
    )
    if not allowed:
        from fastapi import Response
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Rate limit exceeded: {rate_limiter.max_requests} requests per minute. "
                "Please wait before sending another query."
            ),
            headers={"Retry-After": "60"},
        )

    return await pipeline.process_query(
        request.query,
        user,
        db=db,
        top_k=request.top_k,
        session_id=request.session_id,
        team_id=request.team_id,
    )


@router.get("/conversation/sessions", response_model=list[dict])
async def list_sessions(
    user: User = Depends(get_current_user),
    manager: ConversationManager = Depends(get_conversation_manager_dep),
):
    return await manager.list_user_sessions(user.username)


@router.get("/conversation/sessions/{session_id}", response_model=SessionInfoResponse)
async def get_session(
    session_id: str,
    user: User = Depends(get_current_user),
    manager: ConversationManager = Depends(get_conversation_manager_dep),
):
    session = await manager.get_session_info(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found or has expired.",
        )
    # Strictly validate ownership
    if session.username != user.username:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: You do not own this conversation session.",
        )
    
    turns_schemas = [
        ConversationTurnSchema(
            role=turn.role,
            content=turn.content,
            timestamp=turn.timestamp,
        )
        for turn in session.turns
    ]
    
    return SessionInfoResponse(
        session_id=session.session_id,
        username=session.username,
        turn_count=len(session.turns),
        created_at=session.created_at,
        last_active=session.last_active,
        turns=turns_schemas,
    )


@router.delete("/conversation/sessions/{session_id}")
async def delete_session(
    session_id: str,
    user: User = Depends(get_current_user),
    manager: ConversationManager = Depends(get_conversation_manager_dep),
):
    session = await manager.get_session_info(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found or has expired.",
        )
    # Strictly validate ownership
    if session.username != user.username:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: You do not own this conversation session.",
        )
    
    deleted = await manager.delete_session(session_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete session.",
        )
    
    return {"status": "success", "message": f"Session '{session_id}' successfully deleted."}


@router.get("/health", response_model=HealthResponse)
async def health(vector_store: VectorStore = Depends(get_vector_store)):
    from app.models.domain import DataSource

    return HealthResponse(
        status="healthy",
        version=__version__,
        indexed_documents=vector_store.document_count,
        data_sources=[ds.value for ds in DataSource],
    )


@router.get("/audit/stats")
async def audit_stats(
    user: User = Depends(get_current_user),
    pipeline: RAGPipeline = Depends(get_pipeline),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate audit statistics for the caller's org (Postgres-backed)."""
    return await pipeline.audit_logger.get_stats_async(db)


@router.get("/audit/recent")
async def audit_recent(
    user: User = Depends(get_current_user),
    pipeline: RAGPipeline = Depends(get_pipeline),
    db: AsyncSession = Depends(get_db),
):
    """Return the 20 most recent audit entries for the caller's org (Postgres-backed)."""
    entries = await pipeline.audit_logger.get_recent_async(db, limit=20)
    return {"entries": [e.model_dump() for e in entries]}


@router.post("/document/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    data_source: DataSource = Form(...),
    user: User = Depends(get_current_user),
    vector_store: VectorStore = Depends(get_vector_store),
    db: AsyncSession = Depends(get_db),
):
    from app.document.parser import DocumentParser
    from app.config import get_settings

    settings = get_settings()

    # Enforce RBAC validation
    ctx = {
        "db": db,
        "user_id": user.db_id,
        "org_id": user.org_id,
        "roles": user.roles,
        "team_ids": user.team_ids,
    }
    if not await resolve_access(ctx, data_source.value, team_id=None):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access Denied: You do not have permission to write to {data_source.value}.",
        )

    # Sanitize and get filename
    filename = Path(file.filename).name
    ext = Path(filename).suffix.lower()

    # Map file types to target directories
    if ext in [".txt", ".pdf", ".docx", ".md", ".log"]:
        target_dir = settings.data_dir / "documents"
    elif ext in [".csv", ".xlsx", ".xls"]:
        target_dir = settings.data_dir / "csv"
    elif ext in [".json"]:
        target_dir = settings.data_dir / "json"
    elif ext in [".png", ".jpg", ".jpeg"]:
        target_dir = settings.data_dir / "images"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file extension: {ext}",
        )

    # Read bytes and store via org-prefixed object storage (task 4.5)
    file_bytes = await file.read()
    try:
        storage_uri = store_document(
            org_id=user.org_id,
            data_source_id=data_source.value,
            filename=filename,
            file_bytes=file_bytes,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save file: {str(e)}",
        )

    # Enqueue background ingestion
    try:
        from app.tasks.ingestion import process_document
        job = process_document.delay(user.org_id, data_source.value, filename, ext, file_bytes)
        job_id = job.id
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to enqueue ingestion task: {str(e)}",
        )

    # Save the mapping to registry (flat-file — kept for backward compat)
    registry_path = settings.data_dir / "documents_registry.json"
    import json
    registry = {}
    if registry_path.exists():
        try:
            with open(registry_path, "r", encoding="utf-8") as rf:
                registry = json.load(rf)
        except Exception:
            pass
    registry[filename] = data_source.value
    try:
        with open(registry_path, "w", encoding="utf-8") as wf:
            json.dump(registry, wf, indent=2)
    except Exception:
        pass

    # Record upload in Postgres for GDPR erasure targeting (task 6.2 / Phase 6).
    # Best-effort: a DB failure here must not block the upload response.
    try:
        from sqlalchemy import text as _text
        await db.execute(
            _text(
                """
                INSERT INTO document_uploads
                    (org_id, user_id, filename, data_source, storage_key)
                VALUES (:org_id, :user_id, :filename, :data_source, :storage_key)
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "org_id": user.org_id,
                "user_id": user.db_id,
                "filename": filename,
                "data_source": data_source.value,
                "storage_key": storage_uri,
            },
        )
    except Exception as _reg_exc:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "upload_document: failed to record in document_uploads (%s) — proceeding.", _reg_exc
        )

    return UploadResponse(
        filename=filename,
        data_source=data_source,
        job_id=job_id,
        status="processing",
        message="File successfully uploaded and queued for processing.",
    )


@router.get("/documents")
async def list_documents(
    user: User = Depends(get_current_user),
    vector_store: VectorStore = Depends(get_vector_store),
    db: AsyncSession = Depends(get_db),
):
    from app.config import get_settings
    from app.retrieval.vector_store import DOCUMENT_SOURCE_MAP
    import json

    settings = get_settings()

    ctx = {
        "db": db,
        "user_id": user.db_id,
        "org_id": user.org_id,
        "roles": user.roles,
        "team_ids": user.team_ids,
    }

    # Load registry
    registry = {}
    registry_path = settings.data_dir / "documents_registry.json"
    if registry_path.exists():
        try:
            with open(registry_path, "r", encoding="utf-8") as f:
                registry = json.load(f)
        except Exception:
            pass

    all_files = []

    # Target folders to scan
    dirs = [
        settings.data_dir / "documents",
        settings.data_dir / "csv",
        settings.data_dir / "json",
        settings.data_dir / "images"
    ]

    from datetime import datetime

    for directory in dirs:
        if not directory.exists():
            continue
        for p in directory.glob("*"):
            if p.is_file():
                filename = p.name
                
                # Determine data source
                ds_val = registry.get(filename)
                if not ds_val:
                    ds = DOCUMENT_SOURCE_MAP.get(filename)
                    if ds:
                        ds_val = ds.value
                    else:
                        ext = p.suffix.lower()
                        if ext == ".pdf":
                            ds_val = "pdf_documents"
                        elif ext == ".csv":
                            ds_val = "operational_datasets"
                        elif ext == ".json":
                            ds_val = "audit_logs"
                        else:
                            ds_val = "public_policies"

                # Check if current user role can access this datasource
                try:
                    from app.models.domain import DataSource
                    ds_enum = DataSource(ds_val)
                    if not await resolve_access(ctx, ds_enum.value, team_id=None):
                        continue # Skip unauthorized files
                except Exception:
                    pass

                size_bytes = p.stat().st_size
                if size_bytes >= 1024 * 1024:
                    size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
                else:
                    size_str = f"{size_bytes / 1024:.0f} KB"

                mtime = p.stat().st_mtime
                date_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")

                all_files.append({
                    "id": filename,
                    "name": filename,
                    "category": ds_val,
                    "date": date_str,
                    "size": size_str,
                    "content": ""
                })

    return all_files


@router.get("/documents/{filename}")
async def get_document(
    filename: str,
    user: User = Depends(get_current_user),
    vector_store: VectorStore = Depends(get_vector_store),
    db: AsyncSession = Depends(get_db),
):
    from app.config import get_settings
    from app.retrieval.vector_store import DOCUMENT_SOURCE_MAP
    from app.models.domain import DataSource
    import json

    settings = get_settings()

    ctx = {
        "db": db,
        "user_id": user.db_id,
        "org_id": user.org_id,
        "roles": user.roles,
        "team_ids": user.team_ids,
    }

    # Find the file on disk
    target_path = None
    dirs = [
        settings.data_dir / "documents",
        settings.data_dir / "csv",
        settings.data_dir / "json",
        settings.data_dir / "images"
    ]
    for directory in dirs:
        p = directory / filename
        if p.exists() and p.is_file():
            target_path = p
            break

    if not target_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{filename}' not found.",
        )

    # Determine category
    registry = {}
    registry_path = settings.data_dir / "documents_registry.json"
    if registry_path.exists():
        try:
            with open(registry_path, "r", encoding="utf-8") as f:
                registry = json.load(f)
        except Exception:
            pass

    ds_val = registry.get(filename)
    if not ds_val:
        ds = DOCUMENT_SOURCE_MAP.get(filename)
        if ds:
            ds_val = ds.value
        else:
            ext = target_path.suffix.lower()
            if ext == ".pdf":
                ds_val = "pdf_documents"
            elif ext == ".csv":
                ds_val = "operational_datasets"
            elif ext == ".json":
                ds_val = "audit_logs"
            else:
                ds_val = "public_policies"

    # Enforce RBAC
    try:
        ds_enum = DataSource(ds_val)
        if not await resolve_access(ctx, ds_enum.value, team_id=None):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access Denied: Your role does not have permission to view {ds_val}.",
            )
    except ValueError:
        pass

    # Read content
    content = ""
    try:
        ext = target_path.suffix.lower()
        if ext in [".txt", ".md", ".log", ".json", ".csv"]:
            content = target_path.read_text(encoding="utf-8", errors="ignore")
        else:
            content = f"[Binary file {ext.upper()} - Preview unavailable. Size: {target_path.stat().st_size} bytes]"
    except Exception as e:
        content = f"[Error reading file: {str(e)}]"

    size_bytes = target_path.stat().st_size
    if size_bytes >= 1024 * 1024:
        size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        size_str = f"{size_bytes / 1024:.0f} KB"

    from datetime import datetime
    date_str = datetime.fromtimestamp(target_path.stat().st_mtime).strftime("%Y-%m-%d")

    return {
        "id": filename,
        "name": filename,
        "category": ds_val,
        "date": date_str,
        "size": size_str,
        "content": content
    }


@router.delete("/documents/{filename}")
async def delete_document(
    filename: str,
    user: User = Depends(get_current_user),
    vector_store: VectorStore = Depends(get_vector_store),
    db: AsyncSession = Depends(get_db),
):
    from app.config import get_settings
    from app.models.domain import DataSource
    import json

    ctx = {
        "db": db,
        "user_id": user.db_id,
        "org_id": user.org_id,
        "roles": user.roles,
        "team_ids": user.team_ids,
    }

    # RBAC: Only Admin can delete documents
    if not await resolve_access(ctx, "*", team_id=None):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: Only Administrators can delete documents.",
        )

    settings = get_settings()

    # Find the file on disk
    target_path = None
    dirs = [
        settings.data_dir / "documents",
        settings.data_dir / "csv",
        settings.data_dir / "json",
        settings.data_dir / "images"
    ]
    for directory in dirs:
        p = directory / filename
        if p.exists() and p.is_file():
            target_path = p
            break

    if not target_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{filename}' not found.",
        )

    # Delete from disk
    try:
        target_path.unlink()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete file from disk: {str(e)}",
        )

    # Delete vectors from Pinecone namespace (task 4.3 — routes through VectorStore, never direct client)
    vector_store.delete_by_source(user.org_id, filename)

    # Delete from object storage (task 4.5)
    try:
        object_storage_delete(
            org_id=user.org_id,
            data_source_id="unknown",  # registry lookup not yet available at delete time
            filename=filename,
        )
    except Exception as e:
        print(f"Warning: failed to delete object from storage for {filename}: {e}")

    # Remove from registry
    registry_path = settings.data_dir / "documents_registry.json"
    if registry_path.exists():
        try:
            with open(registry_path, "r", encoding="utf-8") as f:
                registry = json.load(f)
            if filename in registry:
                del registry[filename]
                with open(registry_path, "w", encoding="utf-8") as f:
                    json.dump(registry, f, indent=2)
        except Exception:
            pass

    return {"status": "success", "message": f"Document '{filename}' deleted successfully."}

