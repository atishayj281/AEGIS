import pytest
import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
import uuid

from app.auth.rbac import resolve_access
from app.db.session import get_session_factory

# predictable seeded UUIDs
ORG_ACME = "00000000-0000-0000-0000-000000000001"
TEAM_ENG = "10000000-0000-0000-0000-000000000001"
TEAM_HR = "10000000-0000-0000-0000-000000000002"
TEAM_FINANCE = "10000000-0000-0000-0000-000000000003"

USER_OPS = "30000000-0000-0000-0000-000000000005"       # auth0|ops
USER_GUEST = "30000000-0000-0000-0000-000000000007"     # auth0|guest
USER_COMPLIANCE = "30000000-0000-0000-0000-000000000003" # auth0|compliance


@pytest.fixture
async def db_session():
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_org_id', :org_id, true)"),
                {"org_id": ORG_ACME}
            )
            yield session
    from app.db.session import get_engine
    await get_engine().dispose()


@pytest.mark.asyncio
async def test_different_teams_different_permissions(db_session):
    # ops engineer in team_eng should access system_metrics on team_eng but not finance DB
    ctx = {
        "db": db_session,
        "user_id": USER_OPS,
        "org_id": ORG_ACME,
        "roles": {TEAM_ENG: "operations_engineer"},
        "team_ids": [TEAM_ENG],
    }

    assert await resolve_access(ctx, "system_metrics", team_id=TEAM_ENG) is True
    assert await resolve_access(ctx, "financial_database", team_id=TEAM_ENG) is False
    assert await resolve_access(ctx, "financial_database", team_id=TEAM_FINANCE) is False


@pytest.mark.asyncio
async def test_guest_resource_grant_only(db_session):
    # Guest has no default access to compliance_records
    ctx = {
        "db": db_session,
        "user_id": USER_GUEST,
        "org_id": ORG_ACME,
        "roles": {TEAM_HR: "guest"},
        "team_ids": [TEAM_HR],
    }

    ds_id = str(uuid.uuid4())
    # Create test data source
    await db_session.execute(
        text(
            "INSERT INTO data_sources (id, org_id, name, source_type) "
            "VALUES (:ds_id, :org_id, 'Guest DS', 'compliance_records')"
        ),
        {"ds_id": ds_id, "org_id": ORG_ACME}
    )

    # Before grant: denied
    assert await resolve_access(ctx, "compliance_records", team_id=TEAM_HR, data_source_id=ds_id) is False

    # Grant access
    await db_session.execute(
        text(
            "INSERT INTO resource_grants (org_id, user_id, data_source_id) "
            "VALUES (:org_id, :user_id, :ds_id)"
        ),
        {"org_id": ORG_ACME, "user_id": USER_GUEST, "ds_id": ds_id}
    )

    # After grant: allowed
    assert await resolve_access(ctx, "compliance_records", team_id=TEAM_HR, data_source_id=ds_id) is True

    # Cleanup
    await db_session.execute(text("DELETE FROM resource_grants WHERE data_source_id = :ds_id"), {"ds_id": ds_id})
    await db_session.execute(text("DELETE FROM data_sources WHERE id = :ds_id"), {"ds_id": ds_id})


@pytest.mark.asyncio
async def test_expired_guest_grant_denied(db_session):
    ctx = {
        "db": db_session,
        "user_id": USER_GUEST,
        "org_id": ORG_ACME,
        "roles": {TEAM_HR: "guest"},
        "team_ids": [TEAM_HR],
    }

    ds_id = str(uuid.uuid4())
    await db_session.execute(
        text(
            "INSERT INTO data_sources (id, org_id, name, source_type) "
            "VALUES (:ds_id, :org_id, 'Guest DS 2', 'compliance_records')"
        ),
        {"ds_id": ds_id, "org_id": ORG_ACME}
    )

    expired_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    # Grant access with expired time
    await db_session.execute(
        text(
            "INSERT INTO resource_grants (org_id, user_id, data_source_id, expires_at) "
            "VALUES (:org_id, :user_id, :ds_id, :expires_at)"
        ),
        {"org_id": ORG_ACME, "user_id": USER_GUEST, "ds_id": ds_id, "expires_at": expired_time}
    )

    # Access should be denied due to expiry
    assert await resolve_access(ctx, "compliance_records", team_id=TEAM_HR, data_source_id=ds_id) is False

    # Cleanup
    await db_session.execute(text("DELETE FROM resource_grants WHERE data_source_id = :ds_id"), {"ds_id": ds_id})
    await db_session.execute(text("DELETE FROM data_sources WHERE id = :ds_id"), {"ds_id": ds_id})


@pytest.mark.asyncio
async def test_legacy_single_team_user_unchanged(db_session):
    # compliance_officer on team_hr should access compliance_records on team_hr
    ctx = {
        "db": db_session,
        "user_id": USER_COMPLIANCE,
        "org_id": ORG_ACME,
        "roles": {TEAM_HR: "compliance_officer"},
        "team_ids": [TEAM_HR],
    }

    assert await resolve_access(ctx, "compliance_records", team_id=TEAM_HR) is True
    assert await resolve_access(ctx, "salary_records", team_id=TEAM_HR) is False
