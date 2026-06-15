from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.domain import DataSource, QueryDomain, QueryIntent, UserRole


class TokenRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole
    expires_in: int


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)


class Citation(BaseModel):
    source_type: str
    source_name: str
    excerpt: str
    relevance_score: float
    data_source: DataSource


class RetrievalTrace(BaseModel):
    data_source: DataSource
    method: str
    result_count: int
    latency_ms: float
    status: str


class QueryResponse(BaseModel):
    query: str
    answer: str
    intent: QueryIntent
    domain: QueryDomain
    confidence: float = Field(ge=0.0, le=1.0)
    citations: list[Citation]
    retrieval_trace: list[RetrievalTrace]
    access_granted: bool = True
    masked_fields: list[str] = Field(default_factory=list)
    query_id: str
    response_time_ms: float
    timestamp: datetime


class AccessDeniedResponse(BaseModel):
    query: str
    access_granted: bool = False
    message: str
    required_permission: DataSource | None = None
    query_id: str
    timestamp: datetime


class SecurityViolationResponse(BaseModel):
    query: str
    blocked: bool = True
    reason: str
    violation_type: str
    query_id: str
    timestamp: datetime


class HealthResponse(BaseModel):
    status: str
    version: str
    indexed_documents: int
    data_sources: list[str]


class AuditLogEntry(BaseModel):
    query_id: str
    username: str
    role: UserRole
    query: str
    intent: QueryIntent | None = None
    outcome: str
    rbac_violation: bool = False
    security_violation: bool = False
    response_time_ms: float | None = None
    timestamp: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class UploadResponse(BaseModel):
    filename: str
    data_source: DataSource
    chunks_ingested: int
    message: str
