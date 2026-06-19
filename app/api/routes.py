"""API route definitions."""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from pathlib import Path

from app import __version__
from app.api.deps import get_auth_service, get_current_user, get_pipeline, get_vector_store
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
)
from app.pipeline import RAGPipeline
from app.retrieval.vector_store import VectorStore
from app.models.domain import DataSource

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
    return await pipeline.process_query(request.query, user, top_k=request.top_k)


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

    return UploadResponse(
        filename=filename,
        data_source=data_source,
        chunks_ingested=chunks_ingested,
        message=f"File successfully uploaded and parsed into {chunks_ingested} search chunks.",
    )
