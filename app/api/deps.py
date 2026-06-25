"""FastAPI dependencies.

Authentication: the frontend obtains an Auth0 access_token and sends it as
    Authorization: Bearer <token>
The backend verifies the RS256 signature via Auth0's JWKS endpoint and maps
custom claims to a User object. No login endpoint or token issuance exists
on the backend.
"""

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.auth0_verify import verify_token
from app.auth.jwt_auth import User
from app.config import get_settings
from app.models.domain import UserRole
from app.pipeline import RAGPipeline
from app.retrieval.vector_store import VectorStore
from app.conversation.manager import ConversationManager, get_conversation_manager

security = HTTPBearer()

_pipeline: RAGPipeline | None = None
_vector_store: VectorStore | None = None
_conversation_manager: ConversationManager | None = None


def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore(get_settings())
    return _vector_store


def get_conversation_manager_dep() -> ConversationManager:
    global _conversation_manager
    if _conversation_manager is None:
        settings = get_settings()
        _conversation_manager = get_conversation_manager(
            max_turns=settings.conversation_max_turns,
            ttl_minutes=settings.conversation_session_ttl_minutes,
        )
    return _conversation_manager


def get_pipeline() -> RAGPipeline:
    global _pipeline
    if _pipeline is None:
        get_conversation_manager_dep()
        _pipeline = RAGPipeline()
    return _pipeline


def _map_roles_to_user_role(roles_claim: dict) -> UserRole:
    """Map Auth0 custom roles dict (team_id → role_name) to a single UserRole.

    Priority order mirrors the RBAC permission hierarchy.
    """
    values = set(roles_claim.values())
    if "admin" in values or "org_admin" in values:
        return UserRole.ADMIN
    if "compliance_officer" in values:
        return UserRole.COMPLIANCE_OFFICER
    if "finance_analyst" in values:
        return UserRole.FINANCE_ANALYST
    if "operations_engineer" in values:
        return UserRole.OPERATIONS_ENGINEER
    return UserRole.EMPLOYEE


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    """Verify the Auth0 Bearer token and return the authenticated User.

    The frontend is responsible for obtaining the token from Auth0.
    This dependency only validates the RS256 signature via JWKS and
    maps the claims to a User object — it never issues tokens itself.
    """
    try:
        payload = verify_token(credentials.credentials)
    except jwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    roles_claim = payload.get("roles") or {}
    return User(
        username=payload.get("user_id", "unknown"),
        role=_map_roles_to_user_role(roles_claim),
        department="General",
        org_id=payload.get("org_id"),
        team_ids=payload.get("team_ids", []),
        roles=roles_claim,
    )
