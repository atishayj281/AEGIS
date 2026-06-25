"""Tests for legacy authentication flow (AUTH_PROVIDER=legacy)."""

import os
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from main import app
from app.api.deps import get_auth_service
from app.auth.jwt_auth import User
from app.models.domain import UserRole

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_legacy_provider():
    """Force AUTH_PROVIDER=legacy for every test in this module."""
    old_val = os.environ.get("AUTH_PROVIDER")
    os.environ["AUTH_PROVIDER"] = "legacy"

    # Bust lru_cache so pydantic-settings re-reads the env var
    from app.config import get_settings
    get_settings.cache_clear()

    yield

    if old_val is not None:
        os.environ["AUTH_PROVIDER"] = old_val
    else:
        os.environ.pop("AUTH_PROVIDER", None)

    from app.config import get_settings
    get_settings.cache_clear()


def _get_admin_token() -> str:
    """Produce a valid legacy JWT for an admin user without hitting the login endpoint."""
    auth_service = get_auth_service()
    admin_user = User(username="admin_user", role=UserRole.ADMIN, department="IT")
    token, _ = auth_service.create_token(admin_user)
    return token


def _get_employee_token() -> str:
    auth_service = get_auth_service()
    employee_user = User(username="employee_user", role=UserRole.EMPLOYEE, department="HR")
    token, _ = auth_service.create_token(employee_user)
    return token


def test_legacy_valid_token_grants_access():
    """A properly signed legacy token must reach the protected endpoint."""
    token = _get_admin_token()
    response = client.get(
        "/api/v1/conversation/sessions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_200_OK


def test_legacy_employee_token_grants_access():
    """Employee-role legacy token must also reach non-role-gated endpoints."""
    token = _get_employee_token()
    response = client.get(
        "/api/v1/conversation/sessions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_200_OK


def test_legacy_invalid_token_rejected():
    """A garbage token must be rejected with 401."""
    response = client.get(
        "/api/v1/conversation/sessions",
        headers={"Authorization": "Bearer invalid-token-sig"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_legacy_missing_token_rejected():
    """No Authorization header must return 403 (HTTPBearer) or 401."""
    response = client.get("/api/v1/conversation/sessions")
    assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


def test_legacy_demo_users_endpoint():
    """The demo-users list endpoint should return at least one entry."""
    response = client.get("/api/v1/auth/demo-users")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "users" in data
    assert len(data["users"]) > 0
