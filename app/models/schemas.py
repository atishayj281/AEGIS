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


class ConversationTurnSchema(BaseModel):
    """Public representation of a single conversation turn."""

    role: str  # "user" | "assistant"
    content: str
    timestamp: datetime


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    session_id: str | None = Field(
        default=None,
        description=(
            "Optional conversation session ID.  If omitted, a new session is "
            "created and its ID is returned in the response.  Pass the returned "
            "session_id in subsequent requests to maintain conversation context."
        ),
    )
    team_id: str | None = Field(
        default=None,
        description="Optional team ID context for scoped RBAC authorization.",
    )


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
    # Conversation / session fields
    session_id: str = Field(
        description="Session ID to pass in subsequent requests for multi-turn conversation."
    )
    conversation_turn: int = Field(
        description="1-based index of this exchange within the session."
    )


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
    role: str | None = None
    query: str
    intent: QueryIntent | None = None
    outcome: str
    rbac_violation: bool = False
    security_violation: bool = False
    response_time_ms: float | None = None
    timestamp: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionInfoResponse(BaseModel):
    """Summary information about an active conversation session."""

    session_id: str
    username: str
    turn_count: int
    created_at: datetime
    last_active: datetime
    turns: list[ConversationTurnSchema] = Field(default_factory=list)


class UploadResponse(BaseModel):
    filename: str
    data_source: DataSource
    job_id: str | None = None
    status: str = "processing"
    message: str
