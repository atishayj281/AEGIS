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