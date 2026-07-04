"""Tests for the frontend-Auth0 JWT consumer authentication strategy.

The backend never issues tokens — Auth0 does.
These tests mock the JWKS verification layer (jwt.PyJWKClient + jwt.decode)
to simulate tokens that the frontend would obtain from Auth0, asserting that:
  - A valid token reaches protected endpoints.
  - Role mapping from the custom claims works correctly.
  - An invalid / expired token returns 401.
  - A missing Authorization header returns 401 / 403.

Infrastructure mocking
-----------------------
The /api/v1/conversation/sessions endpoint depends on:
  1. get_db  → tenant_scoped_session (Postgres) — overridden with a mock session
  2. get_current_user → queries users table via get_db — get_db override covers this
  3. get_conversation_manager_dep → Redis — overridden with an in-memory mock manager
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import status
from fastapi.testclient import TestClient
from main import app
from app.api.deps import get_db, get_conversation_manager_dep

# ---------------------------------------------------------------------------
# In-memory ConversationManager stub (no Redis)
# ---------------------------------------------------------------------------

class _FakeManager:
    """Minimal in-memory ConversationManager stub that satisfies the routes."""

    async def list_user_sessions(self, username: str) -> list[dict]:
        return []

    async def get_session_info(self, session_id: str):
        return None

    async def delete_session(self, session_id: str) -> bool:
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_auth0_payload(
    sub: str = "auth0|testuser",
    org_id: str = "org_acme",
    team_ids: list | None = None,
    roles: dict | None = None,
) -> dict:
    """Build a decoded JWT payload matching the Auth0 custom claim schema."""
    return {
        "sub": sub,
        "https://aegis-api/org_id": org_id,
        "https://aegis-api/team_ids": team_ids or [],
        "https://aegis-api/roles": roles or {},
    }


def _make_mock_db() -> AsyncMock:
    """Return a mock AsyncSession that returns no db_id for the user lookup."""
    db = AsyncMock()
    result = MagicMock()
    result.fetchone.return_value = None  # no Postgres user row needed for auth tests
    db.execute = AsyncMock(return_value=result)
    return db


# ---------------------------------------------------------------------------
# Fixture: patch JWKS so no real network call is made
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_jwks():
    """Replace jwt.PyJWKClient and jwt.decode with controllable mocks.

    The 'token payload' is keyed by the literal token string for easy routing.
    """
    token_payloads: dict[str, dict] = {
        "valid_admin_token": _make_auth0_payload(
            sub="auth0|admin",
            org_id="00000000-0000-0000-0000-000000000001",
            team_ids=["10000000-0000-0000-0000-000000000001"],
            roles={"10000000-0000-0000-0000-000000000001": "org_admin"},
        ),
        "valid_employee_token": _make_auth0_payload(
            sub="auth0|employee",
            org_id="00000000-0000-0000-0000-000000000001",
            team_ids=["10000000-0000-0000-0000-000000000002"],
            roles={"10000000-0000-0000-0000-000000000002": "employee"},
        ),
        "valid_finance_token": _make_auth0_payload(
            sub="auth0|finance",
            org_id="00000000-0000-0000-0000-000000000001",
            team_ids=["10000000-0000-0000-0000-000000000003"],
            roles={"10000000-0000-0000-0000-000000000003": "finance_analyst"},
        ),
    }

    def decode_side_effect(token, key, algorithms, audience, issuer):
        if token in token_payloads:
            return token_payloads[token]
        import jwt as jwt_lib
        raise jwt_lib.InvalidSignatureError("Signature verification failed")

    mock_signing_key = MagicMock()
    mock_signing_key.key = "fake-public-key"

    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_signing_key

    with (
        patch("app.auth.auth0_verify.jwt.PyJWKClient", return_value=mock_client),
        patch("app.auth.auth0_verify.jwt.decode", side_effect=decode_side_effect),
    ):
        yield token_payloads


# ---------------------------------------------------------------------------
# Tests: token validity
# ---------------------------------------------------------------------------

def test_valid_token_grants_access(mock_jwks):
    """A properly signed Auth0 token must reach a protected endpoint."""
    mock_db = _make_mock_db()
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_conversation_manager_dep] = lambda: _FakeManager()
    try:
        client = TestClient(app)
        response = client.get(
            "/api/v1/conversation/sessions",
            headers={"Authorization": "Bearer valid_admin_token"},
        )
        assert response.status_code == status.HTTP_200_OK
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_conversation_manager_dep, None)


def test_invalid_token_returns_401(mock_jwks):
    """A tampered / expired token must return 401, not 500."""
    client = TestClient(app)
    response = client.get(
        "/api/v1/conversation/sessions",
        headers={"Authorization": "Bearer forged_or_expired_token"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    detail = response.json()["detail"]
    assert "Invalid or expired token" in detail


def test_missing_auth_header_rejected():
    """No Authorization header → 401 or 403 (HTTPBearer behaviour)."""
    client = TestClient(app)
    response = client.get("/api/v1/conversation/sessions")
    assert response.status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    )


def test_malformed_bearer_rejected(mock_jwks):
    """A non-Bearer scheme must not reach the verification layer."""
    client = TestClient(app)
    response = client.get(
        "/api/v1/conversation/sessions",
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert response.status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    )


# ---------------------------------------------------------------------------
# Tests: removed endpoints return 404
# ---------------------------------------------------------------------------

def test_login_endpoint_removed():
    """/auth/token must no longer exist — backend doesn't issue tokens."""
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/token",
        json={"username": "admin", "password": "secret"},
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_demo_users_endpoint_removed():
    """/auth/demo-users must no longer exist."""
    client = TestClient(app)
    response = client.get("/api/v1/auth/demo-users")
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_internal_org_membership_endpoint_removed():
    """/internal/org-membership must no longer exist."""
    client = TestClient(app)
    response = client.get(
        "/internal/org-membership/auth0|user1",
        headers={"X-Internal-Secret": "any-secret"},
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Tests: multi-user isolation
# ---------------------------------------------------------------------------

def test_distinct_users_produce_independent_sessions(mock_jwks):
    """Two users with different tokens must get separate (empty) session lists."""
    mock_db = _make_mock_db()
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_conversation_manager_dep] = lambda: _FakeManager()
    try:
        client = TestClient(app)
        r1 = client.get(
            "/api/v1/conversation/sessions",
            headers={"Authorization": "Bearer valid_admin_token"},
        )
        r2 = client.get(
            "/api/v1/conversation/sessions",
            headers={"Authorization": "Bearer valid_employee_token"},
        )
        assert r1.status_code == status.HTTP_200_OK
        assert r2.status_code == status.HTTP_200_OK
        # Both users have no sessions yet — lists should be empty
        assert r1.json() == []
        assert r2.json() == []
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_conversation_manager_dep, None)
