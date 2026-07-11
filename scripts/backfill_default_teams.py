"""Backfill _org_default teams for pre-existing organizations.

One-off data repair script — NOT part of the Alembic migration chain.

Background
----------
As of the fix in platform_admin.create_org, every NEW organization
automatically gets a reserved team named ``_org_default`` inserted in the
same transaction.  Organizations that were created BEFORE that fix have no
such row, which causes update_user to return HTTP 500 when a platform admin
tries to assign a role to a user in that org who has zero team_memberships.

This script finds every org that is missing its ``_org_default`` team and
inserts one, using ON CONFLICT DO NOTHING so it is safe to re-run multiple
times (idempotent).

Usage
-----
From the repo root, with the virtualenv activated and DATABASE_URL set:

    python -m scripts.backfill_default_teams

Or, passing the connection string explicitly:

    DATABASE_URL=postgresql+asyncpg://user:pass@host/dbname \\
        python -m scripts.backfill_default_teams

The script prints one line per org it repairs (or "Nothing to do" if all
orgs already have their default team).  Exit code is 0 on success, non-zero
on any error.

Safety notes
------------
- Uses INSERT ... ON CONFLICT DO NOTHING — fully idempotent, safe to re-run.
- Runs in a single transaction; rolls back entirely on any DB error.
- Does NOT touch organizations, users, or team_memberships — only inserts
  rows into teams.
- The uq_teams_org_id_name constraint (org_id, name) guarantees exactly one
  _org_default per org; the ON CONFLICT clause targets that constraint.
"""

from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncConnection


async def backfill(database_url: str) -> None:
    engine = create_async_engine(database_url, echo=False)

    async with engine.begin() as conn:  # single transaction
        # Find every org that has no _org_default team yet.
        missing = await conn.execute(
            text(
                "SELECT o.id, o.name "
                "FROM organizations o "
                "WHERE NOT EXISTS ("
                "    SELECT 1 FROM teams t "
                "    WHERE t.org_id = o.id AND t.name = '_org_default'"
                ") "
                "ORDER BY o.name"
            )
        )
        rows = missing.fetchall()

        if not rows:
            print("Nothing to do — all organizations already have an _org_default team.")
            return

        print(f"Found {len(rows)} organization(s) missing an _org_default team. Inserting...")

        for org_id, org_name in rows:
            await conn.execute(
                text(
                    "INSERT INTO teams (org_id, name) "
                    "VALUES (:org_id, '_org_default') "
                    "ON CONFLICT ON CONSTRAINT uq_teams_org_id_name DO NOTHING"
                ),
                {"org_id": str(org_id)},
            )
            print(f"  + Inserted _org_default team for org '{org_name}' ({org_id})")

        print(f"Done. {len(rows)} team(s) inserted.")

    await engine.dispose()


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print(
            "ERROR: DATABASE_URL environment variable is not set.\n"
            "Example:\n"
            "  DATABASE_URL=postgresql+asyncpg://user:pass@localhost/aegis "
            "python -m scripts.backfill_default_teams",
            file=sys.stderr,
        )
        sys.exit(1)

    # Ensure the driver is asyncpg — SQLAlchemy sync URLs won't work here.
    if "asyncpg" not in database_url:
        # Attempt a best-effort rewrite of common sync URL schemes.
        database_url = database_url.replace(
            "postgresql://", "postgresql+asyncpg://"
        ).replace(
            "postgres://", "postgresql+asyncpg://"
        )

    try:
        asyncio.run(backfill(database_url))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
