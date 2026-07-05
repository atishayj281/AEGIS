"""Tests for POST /admin/users and DELETE /admin/users/{user_id}.

All Auth0 Management API calls are mocked (no live Auth0 connection needed).
Database interactions use a mock AsyncSession injected via dependency override.

Patching notes
--------------
``resolve_access`` is imported into admin.py via ``from app.auth.rbac import
resolve_access``. This binds the name *in the admin module's namespace*, so
we must patch ``app.api.admin.resolve_access`` (the name as bound in admin.py)
rather than ``app.auth.rbac.resolve_access`` (the source attribute).  The
same applies to the auth0_mgmt functions, which are imported lazily with a
``from app.auth import auth0_mgmt`` inside the handler body — patching the
module-level attributes on ``app.auth.auth0_mgmt`` is correct for those.

Test matrix
-----------
1. test_provision_happy_path
   Happy path: Auth0 create + org-add succeed, Postgres INSERTs succeed.
   Verify 201, correct response body, correct Auth0 call signatures.

2. test_provision_auth0_failure_no_postgres_write
   Auth0 create_auth0_user raises — verify 502 returned and no Postgres
   execute calls beyond the two pre-Auth0 SELECT queries.

3. test_provision_postgres_failure_triggers_auth0_rollback
   Auth0 succeeds, Postgres INSERT raises — verify delete_auth0_user is
   called with the correct auth0_user_id and endpoint returns 500.

4. test_provision_non_admin_rejected
   resolve_access returns False — verify 403, Auth0 never called, Postgres
   never called beyond the org-id check SELECTs that happen *after* RBAC.

5. test_deprovision_happy_path
   Happy path for DELETE: Postgres DELETE committed, Auth0 delete called,
   200 returned with auth0_cleanup="deleted".
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.admin import admin_router
from app.api.deps import get_current_user, get_db
from app.auth.jwt_auth import User

# ── Fixture data ──────────────────────────────────────────────────────────────

ORG_ID = str(uuid.UUID("00000000-0000-0000-0000-000000000001"))
TEAM_ID = str(uuid.UUID("10000000-0000-0000-0000-000000000001"))
AUTH0_ORG_ID = "org_testABC123"
AUTH0_USER_ID = "auth0|provisioned_user_abc"
NEW_POSTGRES_USER_ID = str(uuid.UUID("20000000-0000-0000-0000-000000000099"))

ADMIN_USER = User(
    username="auth0|admin_user",
    db_id=uuid.UUID("30000000-0000-0000-0000-000000000001"),
    org_id=ORG_ID,
    team_ids=[TEAM_ID],
    roles={TEAM_ID: "org_admin"},
)

NON_ADMIN_USER = User(
    username="auth0|employee_user",
    db_id=uuid.UUID("30000000-0000-0000-0000-000000000002"),
    org_id=ORG_ID,
    team_ids=[TEAM_ID],
    roles={TEAM_ID: "employee"},
)

PROVISION_BODY = {
    "org_id": ORG_ID,
    "team_id": TEAM_ID,
    "email": "newuser@acme.example.com",
    "display_name": "New User",
    "role": "finance_analyst",
}


# ── App / DB factories ────────────────────────────────────────────────────────


def _make_app(caller: User, mock_db: AsyncMock) -> FastAPI:
    """Minimal FastAPI app with admin router and mocked auth/db dependencies."""
    app = FastAPI()
    app.include_router(admin_router, prefix="/admin")
    app.dependency_overrides[get_current_user] = lambda: caller
    app.dependency_overrides[get_db] = lambda: mock_db
    return app


def _make_provision_db(
    auth0_org_id: str | None = AUTH0_ORG_ID,
    email_dup: bool = False,
    insert_raises: Exception | None = None,
) -> AsyncMock:
    """Build a mock AsyncSession for the provision flow.

    Query order inside POST /admin/users:
      1. SELECT auth0_org_id FROM organizations  → org lookup
      2. SELECT id FROM users WHERE email        → duplicate check
      3. INSERT INTO users                       → new user row
      4. INSERT INTO team_memberships            → membership row

    Args:
        auth0_org_id:   value returned by the org lookup (None → org has no Auth0 id).
        email_dup:      if True, the dup-check returns a row (email already exists).
        insert_raises:  if set, the first INSERT raises this exception.
    """
    db = AsyncMock()

    # Result 1: org lookup
    org_result = MagicMock()
    org_result.fetchone.return_value = (auth0_org_id,) if auth0_org_id is not None else (None,)

    # Result 2: duplicate email check
    dup_result = MagicMock()
    dup_result.fetchone.return_value = ("existing-id",) if email_dup else None

    # Results 3+: INSERTs
    if insert_raises is not None:
        # First INSERT raises; subsequent calls would not be reached
        db.execute = AsyncMock(
            side_effect=[org_result, dup_result, insert_raises]
        )
    else:
        ok_result = MagicMock()
        ok_result.fetchone.return_value = None
        db.execute = AsyncMock(
            side_effect=[org_result, dup_result, ok_result, ok_result]
        )

    return db


# ── Test 1: Happy path (POST) ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_provision_happy_path() -> None:
    """Full happy-path: Auth0 create + org-add, Postgres inserts, 201 returned."""
    mock_db = _make_provision_db()

    with (
        # Patch resolve_access IN admin.py's namespace (it was imported with `from`)
        patch("app.api.admin.resolve_access", new_callable=AsyncMock, return_value=True),
        patch("app.auth.auth0_mgmt.create_auth0_user", new_callable=AsyncMock, return_value=AUTH0_USER_ID) as mock_create,
        patch("app.auth.auth0_mgmt.add_user_to_org", new_callable=AsyncMock) as mock_add_org,
        patch("app.auth.auth0_mgmt.send_password_change_ticket", new_callable=AsyncMock),
        patch("uuid.uuid4", return_value=uuid.UUID(NEW_POSTGRES_USER_ID)),
    ):
        app = _make_app(ADMIN_USER, mock_db)
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.post("/admin/users", json=PROVISION_BODY)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == PROVISION_BODY["email"]
    assert body["auth0_user_id"] == AUTH0_USER_ID
    assert body["status"] == "provisioned"

    # Auth0: user created, then added to org
    mock_create.assert_awaited_once()
    mock_add_org.assert_awaited_once_with(AUTH0_ORG_ID, AUTH0_USER_ID)

    # Postgres: org lookup + dup check + INSERT users + INSERT team_memberships = 4
    assert mock_db.execute.await_count == 4


# ── Test 2: Auth0 failure → no Postgres writes ────────────────────────────────


@pytest.mark.asyncio
async def test_provision_auth0_failure_no_postgres_write() -> None:
    """When Auth0 create_auth0_user raises, Postgres must not be touched beyond
    the two pre-Auth0 SELECT queries (org lookup + dup check)."""
    mock_db = _make_provision_db()

    with (
        patch("app.api.admin.resolve_access", new_callable=AsyncMock, return_value=True),
        patch(
            "app.auth.auth0_mgmt.create_auth0_user",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Auth0 network timeout"),
        ),
    ):
        app = _make_app(ADMIN_USER, mock_db)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/admin/users", json=PROVISION_BODY)

    assert resp.status_code == 502
    assert "Auth0 user creation failed" in resp.json()["detail"]

    # Only the two SELECT queries ran; no INSERT attempted
    assert mock_db.execute.await_count == 2


# ── Test 3: Postgres failure → Auth0 rollback ─────────────────────────────────


@pytest.mark.asyncio
async def test_provision_postgres_failure_triggers_auth0_rollback() -> None:
    """When Postgres INSERT raises, delete_auth0_user must be called once with
    the correct auth0_user_id (compensation), and endpoint returns 500."""
    mock_db = _make_provision_db(
        insert_raises=Exception("DB connection lost during INSERT")
    )

    with (
        patch("app.api.admin.resolve_access", new_callable=AsyncMock, return_value=True),
        patch("app.auth.auth0_mgmt.create_auth0_user", new_callable=AsyncMock, return_value=AUTH0_USER_ID),
        patch("app.auth.auth0_mgmt.add_user_to_org", new_callable=AsyncMock),
        patch("app.auth.auth0_mgmt.delete_auth0_user", new_callable=AsyncMock) as mock_delete,
        patch("uuid.uuid4", return_value=uuid.UUID(NEW_POSTGRES_USER_ID)),
    ):
        app = _make_app(ADMIN_USER, mock_db)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/admin/users", json=PROVISION_BODY)

    assert resp.status_code == 500
    # Compensation: Auth0 user must be deleted with the exact user_id returned
    # by create_auth0_user — not a different id
    mock_delete.assert_awaited_once_with(AUTH0_USER_ID)
    # Response body must tell operator whether rollback succeeded
    assert "Auth0 rollback" in resp.json()["detail"]


# ── Test 4: Non-admin caller rejected ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_provision_non_admin_rejected() -> None:
    """resolve_access returning False must produce 403; Auth0 never called."""
    # DB mock for non-admin: only the org lookup and dup check are relevant,
    # but with resolve_access=False the handler returns before touching the DB.
    mock_db = _make_provision_db()

    with (
        patch("app.api.admin.resolve_access", new_callable=AsyncMock, return_value=False),
        patch("app.auth.auth0_mgmt.create_auth0_user", new_callable=AsyncMock) as mock_create,
    ):
        app = _make_app(NON_ADMIN_USER, mock_db)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/admin/users", json=PROVISION_BODY)

    assert resp.status_code == 403
    assert "org_admin" in resp.json()["detail"].lower()

    # Auth0 must not have been called at all
    mock_create.assert_not_awaited()

    # The RBAC check is the very first step — no DB queries should have run
    mock_db.execute.assert_not_awaited()


# ── Test 5: Deprovision happy path (DELETE) ───────────────────────────────────


@pytest.mark.asyncio
async def test_deprovision_happy_path() -> None:
    """DELETE /admin/users/{id} deletes Postgres row then Auth0 user; 200 returned."""
    target_user_id = str(uuid.UUID("40000000-0000-0000-0000-000000000001"))
    target_email = "target@acme.example.com"
    target_auth0_sub = "auth0|target_user_xyz"

    # DB mock for deprovision flow:
    #   1. SELECT auth0_sub, email FROM users  → lookup
    #   2. DELETE FROM users                   → succeeds
    mock_db = AsyncMock()
    lookup_result = MagicMock()
    lookup_result.fetchone.return_value = (target_auth0_sub, target_email)
    delete_result = MagicMock()
    delete_result.fetchone.return_value = None
    mock_db.execute = AsyncMock(side_effect=[lookup_result, delete_result])

    with (
        patch("app.api.admin.resolve_access", new_callable=AsyncMock, return_value=True),
        patch("app.auth.auth0_mgmt.delete_auth0_user", new_callable=AsyncMock) as mock_auth0_delete,
    ):
        app = _make_app(ADMIN_USER, mock_db)
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.delete(f"/admin/users/{target_user_id}")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user_id"] == target_user_id
    assert body["email"] == target_email
    assert body["auth0_cleanup"] == "deleted"
    assert body["status"] == "deprovisioned"

    # Auth0 must have been called with the correct sub
    mock_auth0_delete.assert_awaited_once_with(target_auth0_sub)

    # Postgres: SELECT (lookup) + DELETE = 2 executes
    assert mock_db.execute.await_count == 2
