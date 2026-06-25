"""API route definitions."""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from pathlib import Path

from app import __version__
from app.api.deps import (
    get_auth_service,
    get_current_user,
    get_pipeline,
    get_vector_store,
    get_conversation_manager_dep,
)
from app.auth.jwt_auth import AuthService, User
from app.models.schemas import (
    AccessDeniedResponse,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    SecurityViolationResponse,
    TokenRequest,
    TokenResponse,
    UploadResponse,
    SessionInfoResponse,
    ConversationTurnSchema,
)
from app.pipeline import RAGPipeline
from app.retrieval.vector_store import VectorStore
from app.models.domain import DataSource
from app.conversation.manager import ConversationManager

router = APIRouter()


@router.post("/auth/token", response_model=TokenResponse)
async def login(request: TokenRequest, auth: AuthService = Depends(get_auth_service)):
    user = auth.authenticate(request.username, request.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    token, expires_in = auth.create_token(user)
    return TokenResponse(access_token=token, role=user.role, expires_in=expires_in)


@router.get("/auth/demo-users")
async def list_demo_users(auth: AuthService = Depends(get_auth_service)):
    return {"users": auth.list_demo_users(), "note": "Demo credentials for evaluation only"}


@router.post(
    "/query",
    response_model=QueryResponse | AccessDeniedResponse | SecurityViolationResponse,
)
async def query(
    request: QueryRequest,
    user: User = Depends(get_current_user),
    pipeline: RAGPipeline = Depends(get_pipeline),
):
    return await pipeline.process_query(
        request.query,
        user,
        top_k=request.top_k,
        session_id=request.session_id,
    )


@router.get("/conversation/sessions", response_model=list[dict])
async def list_sessions(
    user: User = Depends(get_current_user),
    manager: ConversationManager = Depends(get_conversation_manager_dep),
):
    return manager.list_user_sessions(user.username)


@router.get("/conversation/sessions/{session_id}", response_model=SessionInfoResponse)
async def get_session(
    session_id: str,
    user: User = Depends(get_current_user),
    manager: ConversationManager = Depends(get_conversation_manager_dep),
):
    session = manager.get_session_info(session_id)
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
    session = manager.get_session_info(session_id)
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
    
    deleted = manager.delete_session(session_id)
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
async def audit_stats(user: User = Depends(get_current_user), pipeline: RAGPipeline = Depends(get_pipeline)):
    return pipeline.audit_logger.get_stats()


@router.get("/audit/recent")
async def audit_recent(user: User = Depends(get_current_user), pipeline: RAGPipeline = Depends(get_pipeline)):
    entries = pipeline.audit_logger.get_recent(20)
    return {"entries": [e.model_dump() for e in entries]}


@router.post("/document/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    data_source: DataSource = Form(...),
    user: User = Depends(get_current_user),
    vector_store: VectorStore = Depends(get_vector_store),
):
    from app.auth.rbac import RBACEngine
    from app.document.parser import DocumentParser
    from app.config import get_settings

    settings = get_settings()
    rbac = RBACEngine()

    # Enforce RBAC validation
    if not rbac.can_access(user.role, data_source):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access Denied: Your role '{user.role.value}' does not have permission to write to {data_source.value}.",
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

    # Read bytes and save locally
    file_bytes = await file.read()
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / filename
    try:
        file_path.write_bytes(file_bytes)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save file: {str(e)}",
        )

    # Parse and index contents
    try:
        chunks = []
        if ext in [".txt", ".md", ".log"]:
            text = DocumentParser.parse_txt(file_bytes)
            chunks = vector_store._semantic_chunk_text(text)
        elif ext == ".pdf":
            text = DocumentParser.parse_pdf(file_bytes)
            chunks = vector_store._semantic_chunk_text(text)
        elif ext == ".docx":
            text = DocumentParser.parse_docx(file_bytes)
            chunks = vector_store._semantic_chunk_text(text)
        elif ext == ".csv":
            chunks = DocumentParser.parse_csv(file_bytes)
        elif ext in [".xlsx", ".xls"]:
            chunks = DocumentParser._semantic_chunk_text(file_bytes)
        elif ext == ".json":
            chunks = DocumentParser.parse_json(file_bytes)
        elif ext in [".png", ".jpg", ".jpeg"]:
            text = DocumentParser.parse_image(file_bytes, filename)
            chunks = vector_store._semantic_chunk_text(text)

        chunks_ingested = vector_store.ingest_chunks(chunks, filename, data_source)
    except Exception as e:
        # Clean up file on error
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse or ingest file: {str(e)}",
        )

    # Save the mapping to registry
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

    return UploadResponse(
        filename=filename,
        data_source=data_source,
        chunks_ingested=chunks_ingested,
        message=f"File successfully uploaded and parsed into {chunks_ingested} search chunks.",
    )


@router.get("/documents")
async def list_documents(
    user: User = Depends(get_current_user),
    vector_store: VectorStore = Depends(get_vector_store),
):
    from app.config import get_settings
    from app.retrieval.vector_store import DOCUMENT_SOURCE_MAP
    from app.auth.rbac import RBACEngine
    import json

    settings = get_settings()
    rbac = RBACEngine()

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
                    if not rbac.can_access(user.role, ds_enum):
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
):
    from app.config import get_settings
    from app.retrieval.vector_store import DOCUMENT_SOURCE_MAP
    from app.auth.rbac import RBACEngine
    from app.models.domain import DataSource
    import json

    settings = get_settings()
    rbac = RBACEngine()

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
        if not rbac.can_access(user.role, ds_enum):
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
):
    from app.config import get_settings
    from app.models.domain import UserRole, DataSource
    from app.auth.rbac import RBACEngine
    import json

    # RBAC: Only Admin can delete documents
    if user.role != UserRole.ADMIN:
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

    # Delete points from Qdrant vector store
    from qdrant_client.http.models import Filter, FieldCondition, MatchValue
    try:
        if vector_store._client.collection_exists(vector_store.COLLECTION_NAME):
            vector_store._client.delete(
                collection_name=vector_store.COLLECTION_NAME,
                points_selector=Filter(
                    must=[FieldCondition(key="source_name", match=MatchValue(value=filename))]
                )
            )
    except Exception as e:
        print(f"Warning: failed to delete points from vector store for {filename}: {e}")

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

