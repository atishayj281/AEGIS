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

from app.auth.auth0_verify import verify_token, get_current_context
from app.auth.jwt_auth import User
from app.config import get_settings
from app.pipeline import RAGPipeline
from app.retrieval.vector_store import VectorStore
from app.conversation.manager import ConversationManager, get_conversation_manager
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import (
    InvalidOrgIdError,
    tenant_scoped_session,
    platform_admin_session,
)

from typing import AsyncIterator

security = HTTPBearer()

_pipeline: RAGPipeline | None = None
_vector_store: VectorStore | None = None
_conversation_manager: ConversationManager | None = None


async def get_db(
    context: dict = Depends(get_current_context),
) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an org-scoped AsyncSession.

    Keyed off get_current_context (the Auth0-verified org_id from Phase 1),
    not off get_current_user — get_current_context is the lower-level dict
    dependency that both get_current_user and this dependency independently
    build on, so a route can depend on get_db without also paying for a
    second, separate JWT verification pass for get_current_user.

    Every query run through the yielded session is scoped by the
    tenant_isolation RLS policies (migration 0002) to context["org_id"]
    for the lifetime of this one request's transaction — see
    app/db/session.py for why that's set via set_config(..., true)
    (transaction-scoped) rather than a session-wide SET.

    A missing or malformed org_id claim raises InvalidOrgIdError inside
    tenant_scoped_session before any query runs; that's translated to a
    400 here rather than propagating as an unhandled 500, since by this
    point the token itself already passed signature/audience/issuer
    verification — an invalid org_id at this stage is a malformed claim,
    not a forged or invalid token.
    """
    org_id = context.get("org_id")
    try:
        async with tenant_scoped_session(org_id) as session:
            yield session
    except InvalidOrgIdError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid org_id claim: {e}",
        ) from e

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


from app.security.rate_limiter import RateLimiter

_rate_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """Return the singleton RateLimiter, configured from Settings."""
    global _rate_limiter
    if _rate_limiter is None:
        settings = get_settings()
        _rate_limiter = RateLimiter(
            max_requests=settings.rate_limit_requests_per_minute,
            window_seconds=60,
        )
    return _rate_limiter



from sqlalchemy import text

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
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

    username = payload.get("user_id", "unknown")
    roles_claim = payload.get("roles") or {}
    
    # Query database to retrieve user ID
    result = await db.execute(
        text("SELECT id FROM users WHERE auth0_sub = :sub"),
        {"sub": username}
    )
    row = result.fetchone()
    db_id = row[0] if row else None

    return User(
        username=username,
        db_id=db_id,
        department="General",
        org_id=payload.get("org_id"),
        team_ids=payload.get("team_ids", []),
        roles=roles_claim,
    )


# ---------------------------------------------------------------------------
# Phase 7 — Platform admin bypass dependency
# ---------------------------------------------------------------------------

async def get_platform_admin_db(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a BYPASSRLS session for platform admins.

    Two independent guard layers, evaluated in this order:

    1. JWT claim check (cheap, no DB round-trip):
       The token's `roles` list must contain "platform_admin".  Any token
       that passes Auth0 RS256 verification but lacks this claim is rejected
       with 403 before a bypass session is ever opened.  This is the first
       line of defence and must remain unconditional — it must not be gated
       on, or combined with, the org-scoped get_current_context path.

    2. platform_admins DB row check (authoritative, revocable):
       Even a syntactically valid "platform_admin"-claimed token is rejected
       if no matching active row exists in the `platform_admins` table.
       This lets operators be revoked by flipping `is_active = false`
       without waiting for the JWT to expire.

    The bypass session (platform_admin_session()) is only opened AFTER both
    checks pass, so a rejected call never touches the BYPASSRLS connection
    pool.

    This dependency is intentionally separate from get_db / get_current_user:
    mixing a rare, high-privilege path into the hot-path dependency used by
    every request is exactly the accidental-widening this phase exists to
    avoid.  Do NOT add `bypass: bool = False` to get_db as a shortcut.
    """
    # --- Layer 1: Verify JWT and extract claims ---
    try:
        payload = verify_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    roles_list = payload.get("roles", [])
    # roles may be a list (platform_admin claim) or a dict (team_id->role map).
    # Handle both shapes defensively.
    if isinstance(roles_list, dict):
        roles_list = list(roles_list.values())
    if "platform_admin" not in roles_list:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="platform_admin role required",
        )

    auth0_sub = payload.get("user_id") or payload.get("sub")

    # --- Layer 2: Verify platform_admins DB row exists and is active ---
    # This check uses the bypass session itself — the platform_admins table
    # has no RLS, so this query is safe to run on either connection.
    # We use the bypass session here for consistency (avoids needing to pass
    # an org_id just to check a non-RLS table).
    async with platform_admin_session() as session:
        result = await session.execute(
            text(
                "SELECT id FROM platform_admins "
                "WHERE auth0_sub = :sub AND is_active = true "
                "LIMIT 1"
            ),
            {"sub": auth0_sub},
        )
        if result.fetchone() is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No active platform_admins record found for this token",
            )
        # Yield the already-open bypass session to the route handler.
        yield session

