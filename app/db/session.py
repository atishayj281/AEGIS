"""Async SQLAlchemy engine, session factory, and tenant-scoped sessions.

This module is the runtime counterpart to the RLS policies added in
migration 0002 (alembic/versions/0002_enable_rls.py). Those policies read
the Postgres session-local setting `app.current_org_id` to decide which
rows are visible; this module is what actually sets that setting, once
per transaction, from the Auth0-verified org_id on the request.

Two correctness points carried over from 0002, restated here because this
is where they get enforced:

1. SET LOCAL semantics, not SET. SET is connection-scoped and survives
   until changed or the connection closes — on a pooled connection, that
   means one request's org_id could leak into the next request that
   happens to reuse the same physical connection from the pool.
   set_config('app.current_org_id', <value>, true) — note the third
   argument, is_local=true — gives transaction-scoped behavior instead:
   it's automatically reset at COMMIT/ROLLBACK regardless of what happens
   to the underlying connection afterward. This is the actual correctness
   reason, not a style preference. (set_config is used rather than the
   literal `SET LOCAL ... = :param` statement because SET expects a
   literal value at parse time, not a bound parameter — set_config is a
   regular SQL function, so it accepts org_id as a genuine bound argument
   instead of requiring string interpolation.)

2. org_id is validated as a real UUID in Python before it ever reaches
   SQL. The RLS policy casts current_setting(...)::uuid — if that setting
   holds a malformed string, Postgres raises a hard error (22P02) from
   inside the policy itself, which is a fail-LOUD path, not the fail-CLOSED
   "zero rows" guarantee the rest of this system is built around. A
   request with an unset org_id fails closed by design; a request with a
   garbled org_id should fail with a clean 400, not an unhandled 500 from
   deep inside a query. tenant_scoped_session enforces this before SET
   LOCAL ever runs.

Phase 7 — Platform superuser bypass
------------------------------------
A second engine (`_platform_admin_engine`) connects under the
`aegis_platform_admin` Postgres role, which carries BYPASSRLS.  It uses a
separate connection pool (pool_size=2, max_overflow=0 — admin-only,
low-volume) and deliberately does NOT call SET LOCAL app.current_org_id:

  * Calling it anyway would be misleading dead code — BYPASSRLS means RLS
    policies are skipped entirely for this role, so the setting is never
    consulted.  Leaving it out makes the bypass path unambiguous.
  * More importantly, mixing bypass logic into tenant_scoped_session (e.g.
    via an `if bypass:` flag) would be exactly the accidental-widening this
    phase is designed to prevent: a future maintainer adding a flag could
    accidentally pass `bypass=True` from an org-scoped code path.
    Two separate functions with two separate entry points make that class
    of mistake structurally impossible rather than just convention-dependent.
"""

import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Module-level singleton async engine, created on first use."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            get_settings().database_url,
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
        )
    return _session_factory


class InvalidOrgIdError(ValueError):
    """Raised when org_id is missing or not a syntactically valid UUID.

    Deliberately a plain ValueError subclass rather than an HTTPException:
    this module has no FastAPI dependency, by design, so it stays usable
    from scripts/tests/other contexts. app/api/deps.py is responsible for
    catching this and translating it into a 400 response.
    """


def _validate_org_id(org_id: str | uuid.UUID) -> uuid.UUID:
    if not org_id:
        raise InvalidOrgIdError("org_id is required and cannot be empty")
    if isinstance(org_id, uuid.UUID):
        return org_id
    try:
        return uuid.UUID(str(org_id))
    except (ValueError, AttributeError, TypeError) as e:
        raise InvalidOrgIdError(f"org_id is not a valid UUID: {org_id!r}") from e


@asynccontextmanager
async def tenant_scoped_session(
    org_id: str | uuid.UUID,
) -> AsyncIterator[AsyncSession]:
    """Yield an AsyncSession with app.current_org_id set for this transaction only.

    org_id is validated as a real UUID before the setting is applied, so a
    malformed claim value raises InvalidOrgIdError here rather than a raw
    Postgres cast error surfacing from inside an RLS policy later.

    Uses set_config('app.current_org_id', :org_id, true) rather than the
    literal statement `SET LOCAL app.current_org_id = :org_id`. SET is a
    SQL command, not a function — Postgres expects its value as a literal
    token at parse time, not a server-side bound parameter, so passing
    :org_id directly into a SET LOCAL string is unreliable (and the only
    "safe" alternative without set_config would be manual string
    interpolation, which is a SQL-injection risk for a value that
    ultimately comes from a JWT claim). set_config() is a regular SQL
    function, so it accepts org_id as a genuine bound argument. Its third
    argument, is_local=true, is exactly the SET LOCAL semantics the task
    calls for: scoped to the current transaction, automatically reverted
    on COMMIT or ROLLBACK, never leaking onto the pooled connection for
    the next request.
    """
    validated_org_id = _validate_org_id(org_id)

    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_org_id', :org_id, true)"),
                {"org_id": str(validated_org_id)},
            )
            yield session


# ---------------------------------------------------------------------------
# Phase 7 — Platform admin bypass engine and session factory
# ---------------------------------------------------------------------------

_platform_admin_engine: AsyncEngine | None = None
_platform_admin_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_platform_admin_engine() -> AsyncEngine:
    """Module-level singleton for the BYPASSRLS admin engine.

    Connects under the `aegis_platform_admin` Postgres role via
    PLATFORM_ADMIN_DATABASE_URL.  Pool is intentionally small (size=2,
    max_overflow=0) — this path is admin-only and low-volume.

    Returns None-safe: if PLATFORM_ADMIN_DATABASE_URL is not set (e.g. in
    tests that only want to import this module), callers should guard with
    `if get_platform_admin_engine() is None` or let the KeyError propagate
    as a hard startup failure (correct for production).
    """
    global _platform_admin_engine
    if _platform_admin_engine is None:
        settings = get_settings()
        url = settings.platform_admin_database_url
        if not url:
            raise RuntimeError(
                "PLATFORM_ADMIN_DATABASE_URL is not set. "
                "Set it in .env or the environment before starting the server."
            )
        _platform_admin_engine = create_async_engine(
            url,
            pool_size=2,
            max_overflow=0,
            pool_pre_ping=True,
        )
    return _platform_admin_engine


def get_platform_admin_session_factory() -> async_sessionmaker[AsyncSession]:
    """Session factory bound to the BYPASSRLS engine."""
    global _platform_admin_session_factory
    if _platform_admin_session_factory is None:
        _platform_admin_session_factory = async_sessionmaker(
            bind=get_platform_admin_engine(),
            expire_on_commit=False,
        )
    return _platform_admin_session_factory


@asynccontextmanager
async def platform_admin_session() -> AsyncIterator[AsyncSession]:
    """Yield an AsyncSession that bypasses all RLS policies.

    This session connects as `aegis_platform_admin` (BYPASSRLS role) and
    therefore sees rows across every org_id without any tenant filter.

    Deliberately does NOT set app.current_org_id:
      - BYPASSRLS means RLS policies are skipped entirely — the setting
        would never be consulted and including it would be misleading.
      - Omitting it also makes the bypass path structurally distinct from
        tenant_scoped_session, preventing accidental reuse via copy-paste.

    Use ONLY from get_platform_admin_db in app/api/deps.py, which gates
    access behind both a JWT claim check and a platform_admins DB row
    check before this context manager is entered.  No other code path
    should call platform_admin_session() directly.
    """
    factory = get_platform_admin_session_factory()
    async with factory() as session:
        async with session.begin():
            yield session