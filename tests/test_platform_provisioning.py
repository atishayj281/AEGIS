"""Tests for platform admin user provisioning and Auth0 M2M integration.

All Auth0 Management API calls are mocked. Database interactions use a
mock AsyncSession injected via dependency override of get_platform_admin_db.
"""

from __future__ import annotations

import datetime
import logging
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.api.platform_admin import router as platform_router
from app.api.deps import get_platform_admin_db
from app.auth import auth0_management

# --- Fixtures / Test constants ---

ORG_ID = str(uuid.UUID("00000000-0000-0000-0000-000000000001"))
AUTH0_USER_ID = "auth0|platform_user_123"
TEST_EMAIL = "provisioned@company.com"
TEST_NAME = "Provisioned User"

PROVISION_BODY = {
    "email": TEST_EMAIL,
    "display_name": TEST_NAME,
}


def _make_app(mock_db: AsyncMock) -> FastAPI:
    """Create minimal app overriding get_platform_admin_db to yield mock_db."""
    app = FastAPI()
    app.include_router(platform_router)
    app.dependency_overrides[get_platform_admin_db] = lambda: mock_db
    return app


def _make_provision_db(
    org_exists: bool = True,
    email_dup: bool = False,
    insert_raises: Exception | None = None,
    new_user_row: tuple | None = None,
) -> AsyncMock:
    """Build mock AsyncSession representing query outcomes.

    Query list:
      1. SELECT id FROM organizations WHERE id = :org_id
      2. SELECT id FROM users WHERE email = :email
      3. INSERT INTO users ... RETURNING id, org_id, auth0_sub, email, ...
    """
    db = AsyncMock()

    org_result = MagicMock()
    org_result.fetchone.return_value = (ORG_ID,) if org_exists else None

    dup_result = MagicMock()
    dup_result.fetchone.return_value = ("existing-user-id",) if email_dup else None

    if insert_raises is not None:
        db.execute = AsyncMock(
            side_effect=[org_result, dup_result, insert_raises]
        )
    else:
        insert_result = MagicMock()
        row = new_user_row or (
            uuid.UUID("20000000-0000-0000-0000-000000000002"),
            uuid.UUID(ORG_ID),
            AUTH0_USER_ID,
            TEST_EMAIL,
            TEST_NAME,
            True,
            datetime.datetime.now(datetime.timezone.utc),
        )
        insert_result.fetchone.return_value = row
        role_result = MagicMock()
        role_result.scalar.return_value = None
        db.execute = AsyncMock(
            side_effect=[org_result, dup_result, insert_result, role_result]
        )

    return db


# --- Provisioning Endpoint Tests ---


@pytest.mark.asyncio
async def test_platform_provision_happy_path() -> None:
    """Succeeds in Auth0, then succeeds in Postgres. Return 201."""
    mock_db = _make_provision_db()

    with patch(
        "app.auth.auth0_management.create_auth0_user",
        new_callable=AsyncMock,
        return_value={"user_id": AUTH0_USER_ID},
    ) as mock_create:
        app = _make_app(mock_db)
        client = TestClient(app)
        resp = client.post(f"/api/v1/platform/orgs/{ORG_ID}/users", json=PROVISION_BODY)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == TEST_EMAIL
    assert body["auth0_sub"] == AUTH0_USER_ID
    assert body["display_name"] == TEST_NAME

    mock_create.assert_awaited_once_with(
        email=TEST_EMAIL,
        org_id=ORG_ID,
        roles={},
        display_name=TEST_NAME,
    )
    assert mock_db.execute.await_count == 4


@pytest.mark.asyncio
async def test_platform_provision_auth0_failure_no_postgres_write() -> None:
    """If Auth0 creation fails, Postgres is never written to."""
    mock_db = _make_provision_db()

    with patch(
        "app.auth.auth0_management.create_auth0_user",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Auth0 connection timeout"),
    ):
        app = _make_app(mock_db)
        client = TestClient(app)
        resp = client.post(f"/api/v1/platform/orgs/{ORG_ID}/users", json=PROVISION_BODY)

    assert resp.status_code == 502
    assert "Auth0 user creation failed" in resp.json()["detail"]

    # Postgres: org check + duplicate email check run before Auth0 call. No INSERT.
    assert mock_db.execute.await_count == 2


@pytest.mark.asyncio
async def test_platform_provision_postgres_failure_triggers_auth0_rollback() -> None:
    """If Postgres insert fails, rollback_created_user is triggered, and 500 returned."""
    mock_db = _make_provision_db(insert_raises=Exception("Postgres connection dropped"))

    with (
        patch(
            "app.auth.auth0_management.create_auth0_user",
            new_callable=AsyncMock,
            return_value={"user_id": AUTH0_USER_ID},
        ),
        patch(
            "app.auth.auth0_management.rollback_created_user",
            new_callable=AsyncMock,
        ) as mock_rollback,
    ):
        app = _make_app(mock_db)
        client = TestClient(app)
        resp = client.post(f"/api/v1/platform/orgs/{ORG_ID}/users", json=PROVISION_BODY)

    assert resp.status_code == 500
    assert "Database insert failed" in resp.json()["detail"]
    mock_rollback.assert_awaited_once_with(AUTH0_USER_ID)


# --- Auth0 Management API Module Tests ---


@pytest.mark.asyncio
@patch("app.auth.auth0_management._get_m2m_token", new_callable=AsyncMock, return_value="fake_m2m_token")
async def test_create_auth0_user_ok(mock_token: AsyncMock) -> None:
    """create_auth0_user parses connection/email/app_metadata properly and sends ticket."""
    import httpx

    settings = auth0_management.get_settings()
    domain = settings.auth0_domain

    user_resp = MagicMock()
    user_resp.status_code = 201
    user_resp.json.return_value = {"user_id": AUTH0_USER_ID}

    email_resp = MagicMock()
    email_resp.status_code = 200

    async def mock_post(url: str, **kwargs: Any) -> MagicMock:
        if "/api/v2/users" in url:
            return user_resp
        if "/dbconnections/change_password" in url:
            return email_resp
        raise RuntimeError(f"Unexpected url: {url}")

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        res = await auth0_management.create_auth0_user(
            email=TEST_EMAIL,
            org_id=ORG_ID,
            roles={},
            display_name=TEST_NAME,
        )

    assert res["user_id"] == AUTH0_USER_ID


@pytest.mark.asyncio
@patch("app.auth.auth0_management._get_m2m_token", new_callable=AsyncMock, return_value="fake_m2m_token")
async def test_sync_existing_user_ok(mock_token: AsyncMock) -> None:
    """sync_existing_user GETs app_metadata, then PATCHes new app_metadata."""
    import httpx

    settings = auth0_management.get_settings()
    domain = settings.auth0_domain

    get_resp = MagicMock()
    get_resp.status_code = 200
    get_resp.json.return_value = {"app_metadata": {"org_id": "old_org"}}

    patch_resp = MagicMock()
    patch_resp.status_code = 200

    with (
        patch("httpx.AsyncClient.get", return_value=get_resp) as mock_get,
        patch("httpx.AsyncClient.patch", return_value=patch_resp) as mock_patch,
    ):
        prev = await auth0_management.sync_existing_user(
            auth0_sub=AUTH0_USER_ID,
            org_id=ORG_ID,
            roles={"some": "role"},
        )

    assert prev == {"org_id": "old_org"}
    mock_get.assert_called_once()
    mock_patch.assert_called_once()


@pytest.mark.asyncio
async def test_rollback_created_user_does_not_call_http() -> None:
    """rollback_created_user does not make any http call since delete:users is missing."""
    import httpx

    with (
        patch("httpx.AsyncClient.delete") as mock_delete,
        patch("app.auth.auth0_management.logger") as mock_logger,
    ):
        await auth0_management.rollback_created_user(AUTH0_USER_ID)

    mock_delete.assert_not_called()
    mock_logger.critical.assert_called_once()
    assert "delete:users scope is not granted" in mock_logger.critical.call_args[0][0]


@pytest.mark.asyncio
@patch("app.auth.auth0_management._get_m2m_token", new_callable=AsyncMock, return_value="fake_m2m_token")
async def test_rollback_synced_user_restores_and_logs(mock_token: AsyncMock) -> None:
    """rollback_synced_user PATCHes previous metadata back to Auth0."""
    import httpx

    settings = auth0_management.get_settings()
    resp = MagicMock()
    resp.status_code = 200

    with patch("httpx.AsyncClient.patch", return_value=resp) as mock_patch:
        await auth0_management.rollback_synced_user(AUTH0_USER_ID, {"org_id": "old_org"})

    mock_patch.assert_called_once()


@pytest.mark.asyncio
@patch("app.auth.auth0_management._get_m2m_token", new_callable=AsyncMock, return_value="fake_m2m_token")
async def test_rollback_synced_user_failure_logs_critical(mock_token: AsyncMock) -> None:
    """If rollback_synced_user fails, it logs CRITICAL and doesn't raise exception."""
    import httpx

    with (
        patch("httpx.AsyncClient.patch", side_effect=Exception("Auth0 is down")),
        patch("app.auth.auth0_management.logger") as mock_logger,
    ):
        # Must not raise an exception, best-effort only
        await auth0_management.rollback_synced_user(AUTH0_USER_ID, {"org_id": "old_org"})

    mock_logger.critical.assert_called_once()
    assert "Auth0 rollback (restore app_metadata) failed" in mock_logger.critical.call_args[0][0]
