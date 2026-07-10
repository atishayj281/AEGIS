import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import status
from fastapi.testclient import TestClient
from main import app
import jwt

def test_login_identity_org_scoped():
    """An org-scoped token returns status: org_scoped and related metadata."""
    payload = {
        "user_id": "auth0|org_user",
        "org_id": "00000000-0000-0000-0000-000000000001",
        "team_ids": ["team_blue"],
        "roles": {"team_blue": "employee"},
    }
    with patch("app.auth.auth0_verify.verify_token", return_value=payload):
        client = TestClient(app)
        response = client.get(
            "/api/v1/login",
            headers={"Authorization": "Bearer some_token"},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "org_scoped"
        assert data["user_id"] == "auth0|org_user"
        assert data["org_id"] == "00000000-0000-0000-0000-000000000001"
        assert data["roles"] == {"team_blue": "employee"}
        assert data["team_ids"] == ["team_blue"]


def test_login_identity_platform_admin():
    """A verified platform admin token returns status: platform_admin."""
    payload = {
        "user_id": "auth0|platform_admin_user",
        "org_id": None,
        "team_ids": [],
        "roles": ["platform_admin"],
    }
    mock_session = AsyncMock()
    with patch("app.auth.auth0_verify.verify_token", return_value=payload), \
         patch("app.db.session.platform_admin_session", return_value=mock_session), \
         patch("app.api.login.verify_platform_admin_row", return_value=True):
        client = TestClient(app)
        response = client.get(
            "/api/v1/login",
            headers={"Authorization": "Bearer some_token"},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "platform_admin"
        assert data["user_id"] == "auth0|platform_admin_user"


def test_login_identity_platform_admin_inactive_db():
    """If roles claim says platform_admin but DB row is inactive/missing -> unprovisioned."""
    payload = {
        "user_id": "auth0|platform_admin_fake",
        "org_id": None,
        "team_ids": [],
        "roles": ["platform_admin"],
    }
    mock_session = AsyncMock()
    with patch("app.auth.auth0_verify.verify_token", return_value=payload), \
         patch("app.db.session.platform_admin_session", return_value=mock_session), \
         patch("app.api.login.verify_platform_admin_row", return_value=False):
        client = TestClient(app)
        response = client.get(
            "/api/v1/login",
            headers={"Authorization": "Bearer some_token"},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "unprovisioned"
        assert data["user_id"] == "auth0|platform_admin_fake"


def test_login_identity_unprovisioned():
    """A token missing org_id and not a platform admin returns status: unprovisioned."""
    with patch("app.auth.auth0_verify.verify_token", side_effect=jwt.InvalidTokenError("Token is missing required org_id claim")), \
         patch("app.auth.auth0_verify.jwt.decode", return_value={"sub": "auth0|new_user"}):
        client = TestClient(app)
        response = client.get(
            "/api/v1/login",
            headers={"Authorization": "Bearer some_token"},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "unprovisioned"
        assert data["user_id"] == "auth0|new_user"
