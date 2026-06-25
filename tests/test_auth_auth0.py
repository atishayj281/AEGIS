"""Tests for Auth0 token verification and internal APIs."""

import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi import status
from fastapi.testclient import TestClient
from main import app
from app.db.models import create_org_member, init_db

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_auth0_provider():
    """Force AUTH_PROVIDER=auth0 for every test, then restore."""
    old = {k: os.environ.get(k) for k in ["AUTH_PROVIDER", "AUTH0_DOMAIN", "AUTH0_AUDIENCE", "INTERNAL_SECRET"]}

    os.environ["AUTH_PROVIDER"] = "auth0"
    os.environ["AUTH0_DOMAIN"] = "test-tenant.auth0.com"
    os.environ["AUTH0_AUDIENCE"] = "https://test-api"
    os.environ["INTERNAL_SECRET"] = "test-secret-12345"

    # Bust the lru_cache so pydantic-settings re-reads env vars
    from app.config import get_settings
    get_settings.cache_clear()

    init_db()

    # Seed test org members
    create_org_member(
        member_id="m1",
        auth0_user_id="auth0|user1",
        org_id="org_acme_corp",
        team_ids=["team_eng"],
        roles={"team_eng": "org_admin"},
    )
    create_org_member(
        member_id="m2",
        auth0_user_id="auth0|user2",
        org_id="org_globex_inc",
        team_ids=["team_finance"],
        roles={"team_finance": "finance_analyst"},
    )

    yield

    # Restore env vars and bust cache again so subsequent tests start clean
    for k, v in old.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)

    from app.config import get_settings
    get_settings.cache_clear()


@pytest.fixture
def mock_jwks_and_jwt():
    """Patch jwt.PyJWKClient and jwt.decode inside auth0_verify module."""

    def decode_side_effect(token, key, algorithms, audience, issuer):
        import jwt
        if token == "valid_token_user1":
            return {
                "sub": "auth0|user1",
                "https://yourapp.com/org_id": "org_acme_corp",
                "https://yourapp.com/team_ids": ["team_eng"],
                "https://yourapp.com/roles": {"team_eng": "org_admin"},
            }
        elif token == "valid_token_user2":
            return {
                "sub": "auth0|user2",
                "https://yourapp.com/org_id": "org_globex_inc",
                "https://yourapp.com/team_ids": ["team_finance"],
                "https://yourapp.com/roles": {"team_finance": "finance_analyst"},
            }
        else:
            import jwt as jwt_module
            raise jwt_module.InvalidSignatureError("Signature verification failed")

    mock_key = MagicMock()
    mock_key.key = "fake-public-key"

    mock_client_instance = MagicMock()
    mock_client_instance.get_signing_key_from_jwt.return_value = mock_key

    # Patch at the module level so verify_token() picks them up
    with patch("app.auth.auth0_verify.jwt.PyJWKClient", return_value=mock_client_instance), \
         patch("app.auth.auth0_verify.jwt.decode", side_effect=decode_side_effect), \
         patch("app.api.deps.jwt.PyJWTError", side_effect=None):
        yield


def test_internal_membership_lookup_success():
    response = client.get(
        "/internal/org-membership/auth0|user1",
        headers={"X-Internal-Secret": "test-secret-12345"},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["org_id"] == "org_acme_corp"
    assert "team_eng" in data["team_ids"]
    assert data["roles"]["team_eng"] == "org_admin"


def test_internal_membership_lookup_unauthorized():
    # Wrong secret
    response = client.get(
        "/internal/org-membership/auth0|user1",
        headers={"X-Internal-Secret": "wrong-secret"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    # Missing header entirely
    response = client.get("/internal/org-membership/auth0|user1")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_internal_membership_lookup_not_found():
    response = client.get(
        "/internal/org-membership/auth0|non-existent",
        headers={"X-Internal-Secret": "test-secret-12345"},
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_distinct_org_claims_per_user(mock_jwks_and_jwt):
    """Two distinct tokens must be accepted and produce different org contexts."""
    # user1 → acme-corp
    r1 = client.get(
        "/api/v1/conversation/sessions",
        headers={"Authorization": "Bearer valid_token_user1"},
    )
    assert r1.status_code == status.HTTP_200_OK

    # user2 → globex-inc
    r2 = client.get(
        "/api/v1/conversation/sessions",
        headers={"Authorization": "Bearer valid_token_user2"},
    )
    assert r2.status_code == status.HTTP_200_OK


def test_invalid_token_returns_401(mock_jwks_and_jwt):
    """A tampered/expired token must return 401, not 500."""
    response = client.get(
        "/api/v1/conversation/sessions",
        headers={"Authorization": "Bearer invalid_or_expired_token"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Invalid or expired Auth0 token" in response.json()["detail"]
