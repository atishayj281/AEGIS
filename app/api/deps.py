"""FastAPI dependencies."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.jwt_auth import AuthService, User
from app.config import get_settings
from app.pipeline import RAGPipeline
from app.retrieval.vector_store import VectorStore
from app.conversation.manager import ConversationManager, get_conversation_manager

security = HTTPBearer()

_auth_service: AuthService | None = None
_pipeline: RAGPipeline | None = None
_vector_store: VectorStore | None = None
_conversation_manager: ConversationManager | None = None


def get_auth_service() -> AuthService:
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService(get_settings())
    return _auth_service


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
        # Initialise conversation manager with settings first
        get_conversation_manager_dep()
        _pipeline = RAGPipeline()
    return _pipeline


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    auth: AuthService = Depends(get_auth_service),
) -> User:
    settings = get_settings()
    if getattr(settings, "auth_provider", "legacy") == "auth0":
        from app.auth.auth0_verify import verify_token
        from app.models.domain import UserRole
        import jwt

        try:
            payload = verify_token(credentials.credentials)
            
            # Map roles dict (team_id -> role) to UserRole
            roles_claim = payload.get("roles") or {}
            values = set(roles_claim.values())
            
            if "admin" in values or "org_admin" in values:
                role = UserRole.ADMIN
            elif "compliance_officer" in values:
                role = UserRole.COMPLIANCE_OFFICER
            elif "finance_analyst" in values:
                role = UserRole.FINANCE_ANALYST
            elif "operations_engineer" in values:
                role = UserRole.OPERATIONS_ENGINEER
            elif "employee" in values:
                role = UserRole.EMPLOYEE
            else:
                role = UserRole.EMPLOYEE
                
            return User(
                username=payload.get("user_id", "unknown"),
                role=role,
                department="General",
                org_id=payload.get("org_id"),
                team_ids=payload.get("team_ids"),
                roles=payload.get("roles")
            )
        except jwt.PyJWTError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid or expired Auth0 token: {str(e)}",
                headers={"WWW-Authenticate": "Bearer"},
            ) from e
    else:
        user = auth.decode_token(credentials.credentials)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user
