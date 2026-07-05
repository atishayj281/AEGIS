"""Bootstrap script — insert the first platform_admins row.

Usage
-----
    python scripts/bootstrap_platform_admin.py

Required environment variables
-------------------------------
    PLATFORM_ADMIN_DATABASE_URL   Connection string for aegis_platform_admin role.
    PLATFORM_ADMIN_AUTH0_SUB      Auth0 'sub' claim of the operator user,
                                  e.g. "auth0|6507c1234abcdef01234567".
    PLATFORM_ADMIN_EMAIL          Email address of the operator user.

Idempotency
-----------
Uses INSERT ... ON CONFLICT (auth0_sub) DO NOTHING — running this script
twice (or more) is safe and will not create duplicate rows or raise an error.
This matches the pattern used by scripts/seed_team_memberships.py (Phase 3)
and scripts/migrate_sqlite_to_pg.py (Phase 2, skipped).

Note on password
----------------
The aegis_platform_admin Postgres role is created by migration 0009 without
a password.  Set it once, outside version control, before running this script:
    ALTER ROLE aegis_platform_admin WITH PASSWORD '<strong-secret>';
Then configure PLATFORM_ADMIN_DATABASE_URL to include that password.
"""

import asyncio
import os
import sys
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Read env vars — fail early with a clear message if any are missing.
# ---------------------------------------------------------------------------

def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(
            f"ERROR: {name} is not set.\n"
            "See .env.example for the full list of Phase 7 env vars.",
            file=sys.stderr,
        )
        sys.exit(1)
    return value


async def bootstrap() -> None:
    db_url = _require_env("PLATFORM_ADMIN_DATABASE_URL")
    auth0_sub = _require_env("PLATFORM_ADMIN_AUTH0_SUB")
    email = _require_env("PLATFORM_ADMIN_EMAIL")

    # Use a small pool — this is a one-shot administrative script.
    engine = create_async_engine(db_url, pool_size=1, max_overflow=0)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            async with session.begin():
                # ON CONFLICT DO NOTHING — idempotent as required.
                result = await session.execute(
                    text(
                        "INSERT INTO platform_admins (id, auth0_sub, email, is_active) "
                        "VALUES (:id, :auth0_sub, :email, true) "
                        "ON CONFLICT (auth0_sub) DO NOTHING "
                        "RETURNING id"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "auth0_sub": auth0_sub,
                        "email": email,
                    },
                )
                row = result.fetchone()
                if row is None:
                    # ON CONFLICT branch — row already existed.
                    print(
                        f"platform_admins row for {auth0_sub!r} already exists "
                        "(no change made — idempotent run)."
                    )
                else:
                    print(
                        f"Created platform_admins row: id={row[0]}, "
                        f"auth0_sub={auth0_sub!r}, email={email!r}."
                    )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(bootstrap())
