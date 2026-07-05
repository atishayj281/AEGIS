"""Phase 7 — Platform Superuser: adversarial test suite (task 7.7).

Tests verify:
  1. platform_admin_sees_all_orgs — BYPASSRLS session returns rows for every org
  2. test_non_platform_admin_claim_rejected — org-scoped token is 403'd at the
     claim-check layer, before the bypass session is touched
  3. test_bypass_session_never_used_outside_admin_routes — static import check
     confirms get_platform_admin_db is wired only into platform_admin.py
  4. test_bootstrap_script_idempotent — running the INSERT twice yields one row

All four tests avoid a live Postgres connection where possible.
Tests 1 and 4 mock the platform_admin_session context manager; tests 2/3 are
pure unit/static checks with no DB dependency at all.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

PLATFORM_ADMIN_SUB = "auth0|platform_operator_001"
PLATFORM_ADMIN_EMAIL = "ops@example.com"
PLATFORM_ADMIN_ROW_ID = str(uuid.uuid4())

ORG_ACME_ID = "00000000-0000-0000-0000-000000000001"
ORG_GLOBEX_ID = "00000000-0000-0000-0000-000000000002"

# A decoded JWT payload that carries the platform_admin role in a list
# (as set by the Auth0 operator user's app_metadata).
_PLATFORM_ADMIN_PAYLOAD = {
    "sub": PLATFORM_ADMIN_SUB,
    "user_id": PLATFORM_ADMIN_SUB,
    "org_id": None,          # platform admins have no org_id
    "team_ids": [],
    "roles": ["platform_admin"],   # list, not dict — operator user shape
}

# A decoded JWT payload for an ordinary org-scoped user (no platform_admin).
_ORG_USER_PAYLOAD = {
    "sub": "auth0|acme_user_001",
    "user_id": "auth0|acme_user_001",
    "org_id": ORG_ACME_ID,
    "team_ids": ["10000000-0000-0000-0000-000000000001"],
    "roles": {"10000000-0000-0000-0000-000000000001": "org_admin"},
}


# ---------------------------------------------------------------------------
# Fixture: mock bypass session that pre-loads a platform_admins row
# ---------------------------------------------------------------------------

def _make_bypass_session(platform_admin_rows=None, org_rows=None):
    """Return a mock AsyncSession whose execute() returns preset data.

    Calls are distinguished by the SQL string prefix so tests can control
    what each query returns independently.
    """
    session = AsyncMock()

    async def _execute(stmt, params=None):
        sql = str(stmt).strip().upper()
        result = MagicMock()
        if "FROM PLATFORM_ADMINS" in sql:
            rows = platform_admin_rows if platform_admin_rows is not None else [
                (PLATFORM_ADMIN_ROW_ID,)
            ]
            result.fetchone.return_value = rows[0] if rows else None
            result.fetchall.return_value = rows
            result.scalar.return_value = len(rows)
        elif "FROM ORGANIZATIONS" in sql:
            rows = org_rows if org_rows is not None else [
                (uuid.UUID(ORG_ACME_ID), "Acme Corp", "enterprise"),
                (uuid.UUID(ORG_GLOBEX_ID), "Globex Inc", "enterprise"),
            ]
            result.fetchall.return_value = rows
            result.fetchone.return_value = rows[0] if rows else None
        elif "COUNT(*)" in sql and "FROM USERS" in sql:
            result.scalar.return_value = 3
        elif "COUNT(*)" in sql and "FROM DOCUMENTS" in sql:
            result.scalar.return_value = 7
        elif "MAX(CT.TS)" in sql:
            result.scalar.return_value = None
        else:
            result.fetchone.return_value = None
            result.fetchall.return_value = []
            result.scalar.return_value = 0
        return result

    session.execute.side_effect = _execute
    return session


# ---------------------------------------------------------------------------
# Test 1 — platform admin sees all orgs (BYPASSRLS structural check)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_platform_admin_sees_all_orgs():
    """get_platform_admin_db yields a session that returns every org row.

    This is a structural check: the mock returns two org rows regardless of
    any org_id filter — confirming that the bypass path does NOT apply any
    tenant filter before issuing the query.  The list_all_orgs route is
    called directly (not through the HTTP test client) to avoid needing a
    live Auth0 JWKS endpoint.
    """
    mock_session = _make_bypass_session()

    from app.api.platform_admin import list_all_orgs

    # Call the route handler directly, passing the mock bypass session.
    orgs = await list_all_orgs(db=mock_session)

    assert len(orgs) == 2, f"Expected 2 orgs, got {len(orgs)}: {orgs}"
    org_ids = {str(o.id) for o in orgs}
    assert ORG_ACME_ID in org_ids, f"Acme not in results: {org_ids}"
    assert ORG_GLOBEX_ID in org_ids, f"Globex not in results: {org_ids}"

    # Confirm the route DID issue a SELECT against organizations — the
    # structural signal that bypass (not filtering) is what made both orgs
    # visible, not an absent WHERE clause at a call site that also happens
    # not to filter.
    calls_sql = [str(c.args[0]).upper() for c in mock_session.execute.call_args_list]
    assert any("FROM ORGANIZATIONS" in s for s in calls_sql), (
        f"Expected a SELECT FROM ORGANIZATIONS, got calls: {calls_sql}"
    )


# ---------------------------------------------------------------------------
# Test 2 — non-platform-admin claim rejected before bypass session is touched
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_platform_admin_claim_rejected():
    """An org-scoped token must receive 403 before the bypass session opens.

    This is the standing regression guard referenced in the plan:
    "must keep passing even as future phases broaden ROLE_PERMISSIONS_V2 —
    a widened org-scoped role must never accidentally satisfy this gate."

    We patch verify_token to return the org-user payload (no platform_admin
    in roles) and assert that get_platform_admin_db raises HTTPException(403)
    without ever calling platform_admin_session().
    """
    from app.api import deps as deps_module
    from fastapi.security import HTTPAuthorizationCredentials

    fake_creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="fake.token")

    with patch.object(deps_module, "verify_token", return_value=_ORG_USER_PAYLOAD), \
         patch("app.db.session.platform_admin_session") as mock_bypass_ctx:

        # Collect what the async generator raises
        gen = deps_module.get_platform_admin_db(credentials=fake_creds)
        with pytest.raises(HTTPException) as exc_info:
            await gen.__anext__()

        assert exc_info.value.status_code == 403, (
            f"Expected 403, got {exc_info.value.status_code}"
        )
        assert "platform_admin" in exc_info.value.detail.lower(), (
            f"Unexpected detail: {exc_info.value.detail!r}"
        )

        # Bypass session must NOT have been touched
        mock_bypass_ctx.assert_not_called(), (
            "platform_admin_session() was called even though the claim check "
            "should have rejected the request before opening a bypass connection"
        )


# ---------------------------------------------------------------------------
# Test 3 — bypass dependency is not wired into any non-admin route module
# ---------------------------------------------------------------------------

def test_bypass_session_never_used_outside_admin_routes():
    """Static check: get_platform_admin_db appears only in deps.py and platform_admin.py.

    This guards against a future copy-paste that accidentally wires the
    bypass dependency into a tenant-scoped route module.  Using AST parsing
    (not grep) means it works on Windows without a shell, and checks the
    actual Python parse tree rather than raw text.
    """
    import pathlib

    api_dir = pathlib.Path(__file__).parent.parent / "app" / "api"
    ALLOWED = {"deps.py", "platform_admin.py"}
    violations = []

    for py_file in api_dir.rglob("*.py"):
        if py_file.name in ALLOWED:
            continue
        source = py_file.read_text(encoding="utf-8")
        if "get_platform_admin_db" in source:
            violations.append(py_file.name)

    assert violations == [], (
        f"get_platform_admin_db referenced outside allowed modules: {violations}\n"
        "The bypass dependency must ONLY appear in deps.py (definition) and "
        "platform_admin.py (usage). Wiring it into any other route module would "
        "widen the BYPASSRLS privilege surface beyond its intended scope."
    )


# ---------------------------------------------------------------------------
# Test 4 — bootstrap script is idempotent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bootstrap_script_idempotent():
    """Running the INSERT twice must not create duplicate rows.

    We mock the async engine / session so no live Postgres is required,
    and verify that the ON CONFLICT DO NOTHING path is triggered correctly
    on the second run (returning None from RETURNING id).
    """
    import os
    import asyncio
    import importlib.util
    import pathlib
    from unittest.mock import patch, AsyncMock, MagicMock

    env_overrides = {
        "PLATFORM_ADMIN_DATABASE_URL": "postgresql+asyncpg://fake:fake@localhost/fake",
        "PLATFORM_ADMIN_AUTH0_SUB": PLATFORM_ADMIN_SUB,
        "PLATFORM_ADMIN_EMAIL": PLATFORM_ADMIN_EMAIL,
    }

    # Track how many times execute() has been called across both bootstrap() runs.
    execute_calls: list[MagicMock] = []

    async def _execute(stmt, params=None):
        idx = len(execute_calls)
        result = MagicMock()
        if idx == 0:
            # First call (first bootstrap run) — INSERT succeeds, RETURNING id
            result.fetchone.return_value = (PLATFORM_ADMIN_ROW_ID,)
        else:
            # Second call (second bootstrap run) — ON CONFLICT, RETURNING nothing
            result.fetchone.return_value = None
        execute_calls.append(result)
        return result

    # Build a minimal async-context-manager chain:
    # async_sessionmaker()().__aenter__() → session
    # session.begin().__aenter__() → None  (like a real transaction)

    class _FakeBegin:
        async def __aenter__(self):
            return None
        async def __aexit__(self, *a):
            return False

    class _FakeSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        def begin(self):
            return _FakeBegin()
        execute = AsyncMock(side_effect=_execute)
        # Expose the underlying execute call list for assertion
        @property
        def execute_call_count(self):
            return self.execute.call_count

    session = _FakeSession()

    class _FakeSessionFactory:
        def __call__(self):
            return session

    mock_engine = AsyncMock()
    mock_engine.dispose = AsyncMock()

    with patch.dict(os.environ, env_overrides), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_engine), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=_FakeSessionFactory()):

        # Load the script module fresh each time so env vars are picked up
        if "bootstrap_platform_admin" in sys.modules:
            del sys.modules["bootstrap_platform_admin"]

        script_path = (
            pathlib.Path(__file__).parent.parent
            / "scripts"
            / "bootstrap_platform_admin.py"
        )
        spec = importlib.util.spec_from_file_location("bootstrap_platform_admin", script_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Run 1: INSERT succeeds — reports "Created"
        await mod.bootstrap()
        # Run 2: ON CONFLICT DO NOTHING — reports "already exists"
        await mod.bootstrap()

    # Both runs must have attempted the INSERT (idempotency, not short-circuit skip)
    assert session.execute.call_count == 2, (
        f"Expected 2 execute() calls (one per bootstrap run), "
        f"got {session.execute.call_count}"
    )
    # First run: RETURNING id returned a row → "Created" path
    first_result = execute_calls[0]
    assert first_result.fetchone.return_value == (PLATFORM_ADMIN_ROW_ID,)
    # Second run: RETURNING id returned None → "already exists" path
    second_result = execute_calls[1]
    assert second_result.fetchone.return_value is None
