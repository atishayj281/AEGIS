"""Tests for the frontend-Auth0 JWT consumer authentication strategy.

The backend never issues tokens — Auth0 does.
These tests mock the JWKS verification layer (jwt.PyJWKClient + jwt.decode)
to simulate tokens that the frontend would obtain from Auth0, asserting that:
  - A valid token reaches protected endpoints.
  - Role mapping from the custom claims works correctly.
  - An invalid / expired token returns 401.
  - A missing Authorization header returns 401 / 403.
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi import status
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


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
            org_id="org_acme",
            team_ids=["team_eng"],
            roles={"team_eng": "org_admin"},
        ),
        "valid_employee_token": _make_auth0_payload(
            sub="auth0|employee",
            org_id="org_acme",
            team_ids=["team_hr"],
            roles={"team_hr": "employee"},
        ),
        "valid_finance_token": _make_auth0_payload(
            sub="auth0|finance",
            org_id="org_acme",
            team_ids=["team_finance"],
            roles={"team_finance": "finance_analyst"},
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
    response = client.get(
        "/api/v1/conversation/sessions",
        headers={"Authorization": "Bearer valid_admin_token"},
    )
    assert response.status_code == status.HTTP_200_OK


def test_invalid_token_returns_401(mock_jwks):
    """A tampered / expired token must return 401, not 500."""
    response = client.get(
        "/api/v1/conversation/sessions",
        headers={"Authorization": "Bearer forged_or_expired_token"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    detail = response.json()["detail"]
    assert "Invalid or expired token" in detail


def test_missing_auth_header_rejected():
    """No Authorization header → 401 or 403 (HTTPBearer behaviour)."""
    response = client.get("/api/v1/conversation/sessions")
    assert response.status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    )


def test_malformed_bearer_rejected(mock_jwks):
    """A non-Bearer scheme must not reach the verification layer."""
    response = client.get(
        "/api/v1/conversation/sessions",
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert response.status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    )


# ---------------------------------------------------------------------------
# Tests: role mapping from custom claims
# ---------------------------------------------------------------------------

def test_role_mapping_admin(mock_jwks):
    """org_admin in roles claim → ADMIN UserRole → access to admin endpoints."""
    from app.api.deps import _map_roles_to_user_role
    from app.models.domain import UserRole

    role = _map_roles_to_user_role({"team_eng": "org_admin"})
    assert role == UserRole.ADMIN


def test_role_mapping_finance_analyst(mock_jwks):
    from app.api.deps import _map_roles_to_user_role
    from app.models.domain import UserRole

    role = _map_roles_to_user_role({"team_finance": "finance_analyst"})
    assert role == UserRole.FINANCE_ANALYST


def test_role_mapping_unknown_defaults_to_employee(mock_jwks):
    from app.api.deps import _map_roles_to_user_role
    from app.models.domain import UserRole

    role = _map_roles_to_user_role({"team_x": "unknown_role"})
    assert role == UserRole.EMPLOYEE


def test_role_mapping_empty_defaults_to_employee():
    from app.api.deps import _map_roles_to_user_role
    from app.models.domain import UserRole

    role = _map_roles_to_user_role({})
    assert role == UserRole.EMPLOYEE


# ---------------------------------------------------------------------------
# Tests: removed endpoints return 404
# ---------------------------------------------------------------------------

def test_login_endpoint_removed():
    """/auth/token must no longer exist — backend doesn't issue tokens."""
    response = client.post(
        "/api/v1/auth/token",
        json={"username": "admin", "password": "secret"},
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_demo_users_endpoint_removed():
    """/auth/demo-users must no longer exist."""
    response = client.get("/api/v1/auth/demo-users")
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_internal_org_membership_endpoint_removed():
    """/internal/org-membership must no longer exist."""
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
