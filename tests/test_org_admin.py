"""Tests for org-scoped self-service provisioning routes (org_admin.py).

All Auth0 Management API calls are mocked.
Database interactions use mock AsyncSessions injected via dependency
overrides of get_current_user, get_db, and _resolve_caller.

Test matrix
-----------
- org_admin creates a team                                       ✓
- team_lead attempting to create a team → 403                   ✓
- org_admin provisions a user into any team                      ✓
- team_lead provisions a user into their own team               ✓
- team_lead rejected for a team they don't lead → 403           ✓
- either role rejected when attempting to grant org_admin → 403 ✓
- user with zero relevant memberships rejected by _resolve_caller (not silently no-op'd) ✓
- org_admin deactivates a user org-wide                         ✓
- team_lead deactivates a user in their team                    ✓
- team_lead rejected when deactivating user outside their teams ✓
- Postgres failure on provision → Auth0 rollback is triggered   ✓
- role-change Auth0 failure → 502, no Postgres writes           ✓
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.org_admin import router as org_router, _resolve_caller, _CallerCtx
from app.api.deps import get_current_user, get_db
from app.auth.jwt_auth import User
from app.models.provisioning import VALID_ROLES

# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------

ORG_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
ADMIN_USER_ID = uuid.UUID("20000000-0000-0000-0000-000000000001")
LEAD_USER_ID  = uuid.UUID("20000000-0000-0000-0000-000000000002")
TARGET_USER_ID = uuid.UUID("20000000-0000-0000-0000-000000000003")
TEAM_A_ID = uuid.UUID("30000000-0000-0000-0000-000000000001")
TEAM_B_ID = uuid.UUID("30000000-0000-0000-0000-000000000002")
DEFAULT_TEAM_ID = uuid.UUID("30000000-0000-0000-0000-000000000099")
AUTH0_SUB = "auth0|newuser456"
NEW_EMAIL = "newuser@example.com"
NOW = datetime.datetime.now(datetime.timezone.utc)


# ---------------------------------------------------------------------------
# Caller context helpers
# ---------------------------------------------------------------------------

def _org_admin_ctx() -> _CallerCtx:
    user = User(
        username="admin@example.com",
        db_id=ADMIN_USER_ID,
        org_id=str(ORG_ID),
    )
    return _CallerCtx(
        is_org_admin=True,
        led_team_ids=frozenset(),
        org_id=ORG_ID,
        user=user,
    )


def _team_lead_ctx(led_team_id: uuid.UUID = TEAM_A_ID) -> _CallerCtx:
    user = User(
        username="lead@example.com",
        db_id=LEAD_USER_ID,
        org_id=str(ORG_ID),
    )
    return _CallerCtx(
        is_org_admin=False,
        led_team_ids=frozenset([led_team_id]),
        org_id=ORG_ID,
        user=user,
    )


def _no_role_ctx() -> _CallerCtx:
    """Caller with no org_admin and no team_lead memberships."""
    user = User(username="nobody@example.com", db_id=uuid.uuid4(), org_id=str(ORG_ID))
    return _CallerCtx(
        is_org_admin=False,
        led_team_ids=frozenset(),
        org_id=ORG_ID,
        user=user,
    )


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def _make_app(caller_ctx: _CallerCtx, mock_db: AsyncMock) -> FastAPI:
    """Minimal FastAPI with dependency overrides for all three deps."""
    app = FastAPI()
    app.include_router(org_router)

    async def _override_caller() -> _CallerCtx:
        return caller_ctx

    async def _override_db() -> AsyncIterator:
        yield mock_db

    app.dependency_overrides[_resolve_caller] = _override_caller
    app.dependency_overrides[get_db] = _override_db
    return app


# ---------------------------------------------------------------------------
# Helper: build a mock db whose execute() returns different results per call
# ---------------------------------------------------------------------------

def _db(*results: Any) -> AsyncMock:
    """Return an AsyncMock db whose execute() calls return results in order."""
    db = AsyncMock()
    mocks = []
    for r in results:
        m = MagicMock()
        if isinstance(r, Exception):
            m = r
        elif r is None:
            m.fetchone.return_value = None
            m.fetchall.return_value = []
            m.scalar.return_value = None
        elif isinstance(r, list):
            m.fetchone.return_value = r[0] if r else None
            m.fetchall.return_value = r
            m.scalar.return_value = r[0] if r else None
        else:
            m.fetchone.return_value = r
            m.fetchall.return_value = [r]
            m.scalar.return_value = r[0] if isinstance(r, tuple) else r
        mocks.append(m)

    side_effects = []
    for m in mocks:
        if isinstance(m, Exception):
            side_effects.append(m)
        else:
            side_effects.append(m)

    db.execute = AsyncMock(side_effect=side_effects)
    return db


def _user_row(
    user_id: uuid.UUID = TARGET_USER_ID,
    org_id: uuid.UUID = ORG_ID,
    auth0_sub: str = AUTH0_SUB,
    email: str = NEW_EMAIL,
    display_name: str = "Test User",
    is_active: bool = True,
) -> tuple:
    return (user_id, org_id, auth0_sub, email, display_name, is_active, NOW)


# ===========================================================================
# Tests — create_team
# ===========================================================================

@pytest.mark.asyncio
async def test_org_admin_can_create_team() -> None:
    """org_admin creates a team successfully."""
    new_team_id = uuid.uuid4()
    mock_db = _db(
        None,   # dup check: no existing team with that name
        (new_team_id, ORG_ID, "engineering", NOW),  # INSERT RETURNING
    )
    app = _make_app(_org_admin_ctx(), mock_db)
    client = TestClient(app)
    resp = client.post("/api/v1/org/teams", json={"name": "engineering"})

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "engineering"
    assert body["org_id"] == str(ORG_ID)


@pytest.mark.asyncio
async def test_team_lead_cannot_create_team() -> None:
    """team_lead is rejected with 403 when attempting to create a team."""
    mock_db = _db()  # No DB calls expected — blocked before any query
    app = _make_app(_team_lead_ctx(), mock_db)
    client = TestClient(app)
    resp = client.post("/api/v1/org/teams", json={"name": "should-fail"})

    assert resp.status_code == 403
    assert "org_admin" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_create_team_duplicate_name_returns_409() -> None:
    """409 Conflict when a team with the same name already exists."""
    existing_id = uuid.uuid4()
    mock_db = _db(
        (existing_id,),  # dup check: team already exists
    )
    app = _make_app(_org_admin_ctx(), mock_db)
    client = TestClient(app)
    resp = client.post("/api/v1/org/teams", json={"name": "existing-team"})

    assert resp.status_code == 409


# ===========================================================================
# Tests — provision_user
# ===========================================================================

@pytest.mark.asyncio
async def test_org_admin_provisions_user_any_team() -> None:
    """org_admin can provision a user without supplying team_id (uses _org_default)."""
    mock_db = _db(
        (DEFAULT_TEAM_ID,),            # _get_default_team_id (evaluated first)
        None,                          # email dup check: not found (evaluated second)
        _user_row(),                   # INSERT users RETURNING
        None,                          # INSERT team_memberships
    )

    with patch(
        "app.auth.auth0_management.create_auth0_user",
        new_callable=AsyncMock,
        return_value={"user_id": AUTH0_SUB},
    ) as mock_create:
        app = _make_app(_org_admin_ctx(), mock_db)
        client = TestClient(app)
        resp = client.post("/api/v1/org/users", json={"email": NEW_EMAIL, "role": "employee"})

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == NEW_EMAIL
    assert body["role"] == "employee"
    mock_create.assert_awaited_once()


@pytest.mark.asyncio
async def test_org_admin_provisions_user_explicit_team() -> None:
    """org_admin can provision a user into an explicit team."""
    mock_db = _db(
        (TEAM_A_ID,),                  # _validate_team_in_org: team found
        None,                          # email dup check
        _user_row(),                   # INSERT users RETURNING
        None,                          # INSERT team_memberships
    )

    with patch(
        "app.auth.auth0_management.create_auth0_user",
        new_callable=AsyncMock,
        return_value={"user_id": AUTH0_SUB},
    ):
        app = _make_app(_org_admin_ctx(), mock_db)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/org/users",
            json={"email": NEW_EMAIL, "role": "finance_analyst", "team_id": str(TEAM_A_ID)},
        )

    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_team_lead_provisions_user_into_own_team() -> None:
    """team_lead can provision a user into a team they lead."""
    mock_db = _db(
        (TEAM_A_ID,),                  # _validate_team_in_org: team found
        None,                          # email dup check
        _user_row(),                   # INSERT users RETURNING
        None,                          # INSERT team_memberships
    )

    with patch(
        "app.auth.auth0_management.create_auth0_user",
        new_callable=AsyncMock,
        return_value={"user_id": AUTH0_SUB},
    ):
        app = _make_app(_team_lead_ctx(led_team_id=TEAM_A_ID), mock_db)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/org/users",
            json={"email": NEW_EMAIL, "role": "employee", "team_id": str(TEAM_A_ID)},
        )

    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_team_lead_rejected_for_other_team() -> None:
    """team_lead is rejected (403) when supplying a team_id they don't lead."""
    mock_db = _db(
        (TEAM_B_ID,),  # _validate_team_in_org: team exists (different team)
        None,          # email dup check (never reached — blocked first)
    )

    with patch(
        "app.auth.auth0_management.create_auth0_user",
        new_callable=AsyncMock,
    ) as mock_create:
        # Caller leads TEAM_A only; request targets TEAM_B
        app = _make_app(_team_lead_ctx(led_team_id=TEAM_A_ID), mock_db)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/org/users",
            json={"email": NEW_EMAIL, "role": "employee", "team_id": str(TEAM_B_ID)},
        )

    assert resp.status_code == 403
    mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_org_admin_role_rejected_for_org_scoped_route() -> None:
    """Attempting to assign org_admin via org-scoped routes → 403 (both caller roles)."""
    for ctx in [_org_admin_ctx(), _team_lead_ctx()]:
        app = _make_app(ctx, AsyncMock())
        client = TestClient(app)
        resp = client.post(
            "/api/v1/org/users",
            json={"email": NEW_EMAIL, "role": "org_admin", "team_id": str(TEAM_A_ID)},
        )
        assert resp.status_code == 403, f"Expected 403 for caller {ctx}"
        assert "org_admin" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_team_lead_must_supply_team_id_for_provision() -> None:
    """team_lead without team_id → 422."""
    mock_db = _db()
    app = _make_app(_team_lead_ctx(), mock_db)
    client = TestClient(app)
    resp = client.post("/api/v1/org/users", json={"email": NEW_EMAIL, "role": "employee"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_provision_postgres_failure_triggers_rollback() -> None:
    """If Postgres insert fails after Auth0 succeeds, rollback_created_user is called."""
    mock_db = _db(
        (DEFAULT_TEAM_ID,),                    # _get_default_team_id
        None,                                  # email dup check
        Exception("DB connection dropped"),    # INSERT users raises
    )

    with (
        patch(
            "app.auth.auth0_management.create_auth0_user",
            new_callable=AsyncMock,
            return_value={"user_id": AUTH0_SUB},
        ),
        patch(
            "app.auth.auth0_management.rollback_created_user",
            new_callable=AsyncMock,
        ) as mock_rollback,
    ):
        app = _make_app(_org_admin_ctx(), mock_db)
        client = TestClient(app)
        resp = client.post("/api/v1/org/users", json={"email": NEW_EMAIL, "role": "employee"})

    assert resp.status_code == 500
    mock_rollback.assert_awaited_once_with(AUTH0_SUB)


# ===========================================================================
# Tests — update_user (role change)
# ===========================================================================

@pytest.mark.asyncio
async def test_update_user_role_org_admin_forbidden() -> None:
    """Assigning org_admin role via PATCH /api/v1/org/users/{id} → 403."""
    for ctx in [_org_admin_ctx(), _team_lead_ctx()]:
        app = _make_app(ctx, AsyncMock())
        client = TestClient(app)
        resp = client.patch(
            f"/api/v1/org/users/{TARGET_USER_ID}",
            json={"role": "org_admin", "team_id": str(TEAM_A_ID)},
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_update_user_role_change_auth0_failure_returns_502() -> None:
    """If Auth0 sync fails during role change, 502 is returned and Postgres is not written."""
    mock_db = _db(
        _user_row(),                            # SELECT target user
        [(TEAM_A_ID, "employee")],              # SELECT team_memberships
    )

    with patch(
        "app.auth.auth0_management.sync_existing_user",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Auth0 down"),
    ):
        app = _make_app(_org_admin_ctx(), mock_db)
        client = TestClient(app)
        resp = client.patch(
            f"/api/v1/org/users/{TARGET_USER_ID}",
            json={"role": "finance_analyst"},
        )

    assert resp.status_code == 502
    assert "Auth0 metadata sync failed" in resp.json()["detail"]
    # Only the 2 SELECT queries ran — no UPDATE was attempted.
    assert mock_db.execute.await_count == 2


@pytest.mark.asyncio
async def test_update_user_display_name_no_auth0_sync() -> None:
    """display_name-only change does not touch Auth0."""
    updated_row = _user_row(display_name="New Name")
    mock_db = _db(
        _user_row(),     # SELECT existing user
        updated_row,     # UPDATE users RETURNING
        "employee",      # SELECT tm.role re-fetch
    )

    with patch(
        "app.auth.auth0_management.sync_existing_user",
        new_callable=AsyncMock,
    ) as mock_sync:
        app = _make_app(_org_admin_ctx(), mock_db)
        client = TestClient(app)
        resp = client.patch(
            f"/api/v1/org/users/{TARGET_USER_ID}",
            json={"display_name": "New Name"},
        )

    assert resp.status_code == 200, resp.text
    mock_sync.assert_not_called()


@pytest.mark.asyncio
async def test_team_lead_update_user_not_in_team_returns_403() -> None:
    """team_lead attempting to update a user not in their team → 403."""
    mock_db = _db(
        _user_row(),     # SELECT target user (found)
        (TEAM_B_ID,),    # _validate_team_in_org: team exists
        None,            # membership check: user NOT in team B → fetchone returns None
    )

    app = _make_app(_team_lead_ctx(led_team_id=TEAM_A_ID), mock_db)
    client = TestClient(app)
    resp = client.patch(
        f"/api/v1/org/users/{TARGET_USER_ID}",
        json={"role": "employee", "team_id": str(TEAM_B_ID)},
    )

    # Team B isn't led by this caller, so they get 403 at assert_can_act_on_team
    assert resp.status_code == 403


# ===========================================================================
# Tests — deactivate_user
# ===========================================================================

@pytest.mark.asyncio
async def test_org_admin_deactivates_any_user() -> None:
    """org_admin can deactivate any user in the org."""
    mock_db = _db(
        (_user_row()[0],),  # SELECT id: user exists
        None,               # UPDATE is_active = false
    )
    app = _make_app(_org_admin_ctx(), mock_db)
    client = TestClient(app)
    resp = client.delete(f"/api/v1/org/users/{TARGET_USER_ID}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_team_lead_deactivates_user_in_own_team() -> None:
    """team_lead can deactivate a user who is a member of their team."""
    mock_db = _db(
        (_user_row()[0],),      # SELECT id: user exists
        [(TEAM_A_ID,)],         # SELECT user's team_memberships
        None,                   # UPDATE is_active = false
    )
    app = _make_app(_team_lead_ctx(led_team_id=TEAM_A_ID), mock_db)
    client = TestClient(app)
    resp = client.delete(f"/api/v1/org/users/{TARGET_USER_ID}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_team_lead_cannot_deactivate_user_outside_their_teams() -> None:
    """team_lead cannot deactivate a user whose teams don't overlap with their led teams."""
    mock_db = _db(
        (_user_row()[0],),   # SELECT id: user exists
        [(TEAM_B_ID,)],      # SELECT user's teams: only TEAM_B (caller leads TEAM_A)
    )
    app = _make_app(_team_lead_ctx(led_team_id=TEAM_A_ID), mock_db)
    client = TestClient(app)
    resp = client.delete(f"/api/v1/org/users/{TARGET_USER_ID}")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_deactivate_nonexistent_user_returns_404() -> None:
    """Deactivating a user not in the org returns 404."""
    mock_db = _db(None)  # SELECT id: not found
    app = _make_app(_org_admin_ctx(), mock_db)
    client = TestClient(app)
    resp = client.delete(f"/api/v1/org/users/{uuid.uuid4()}")
    assert resp.status_code == 404


# ===========================================================================
# Tests — _resolve_caller rejects users with no relevant role
# ===========================================================================

@pytest.mark.asyncio
async def test_zero_memberships_caller_rejected() -> None:
    """A user with no org_admin or team_lead memberships gets 403, not a silent no-op."""
    # We test _CallerCtx directly — a no-role context should fail assert_can_act_on_team.
    ctx = _no_role_ctx()
    with pytest.raises(Exception) as exc_info:
        ctx.assert_can_act_on_team(TEAM_A_ID)
    assert "403" in str(exc_info.value.status_code)


@pytest.mark.asyncio
async def test_resolve_caller_dependency_rejects_plain_employee(monkeypatch) -> None:
    """An employee with no org_admin/team_lead memberships gets 403 from _resolve_caller."""
    from fastapi import HTTPException as FE

    employee_user = User(
        username="employee@example.com",
        db_id=uuid.uuid4(),
        org_id=str(ORG_ID),
    )

    # DB returns: user has one membership with role='employee' — not admin or lead.
    employee_membership_result = MagicMock()
    employee_membership_result.fetchall.return_value = [(TEAM_A_ID, "employee")]
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=employee_membership_result)

    with pytest.raises(FE) as exc_info:
        await _resolve_caller(user=employee_user, db=mock_db)

    assert exc_info.value.status_code == 403
    assert "org_admin or team_lead" in exc_info.value.detail
