"""Celery beat task: data-retention sweep.

Runs daily at 02:00 UTC (configured in ``app/tasks/celery_app.py``).

For each organization that has ``retention_days IS NOT NULL``, this task
deletes ``audit_logs`` rows older than ``retention_days`` days.

Implementation notes
--------------------
- Uses a *synchronous* SQLAlchemy session (``sqlalchemy.create_engine``)
  because Celery workers run in a non-async context.  The connection string is
  the same DATABASE_URL used by the FastAPI async engine, with the driver
  swapped from ``asyncpg`` → ``psycopg2`` at runtime (or directly using
  psycopg2 URL if DATABASE_URL is already sync).
- The sweep executes each org's DELETE without RLS because the task runs as
  the DB superuser context (no ``app.current_org_id`` set).  This is
  intentional — retention enforcement is a privileged operation that must not
  be restricted by per-row tenant isolation.
- Each org's purge is committed separately so a failure in one org does not
  roll back deletions that succeeded.
- The result of each sweep is logged to ``audit_logs`` with
  ``outcome="retention_sweep"`` so auditors can see when purges ran and how
  many rows were deleted.
"""

import logging
import os
from datetime import datetime, timezone

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _get_sync_engine():
    """Return a synchronous SQLAlchemy engine derived from DATABASE_URL."""
    import sqlalchemy as sa

    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://aegis:1234@localhost:5432/aegis",
    )
    # Swap asyncpg driver for psycopg2 (sync)
    sync_url = database_url.replace("+asyncpg", "+psycopg2").replace("postgresql+psycopg2", "postgresql")
    if "+psycopg2" not in sync_url and "postgresql" in sync_url:
        sync_url = sync_url.replace("postgresql://", "postgresql+psycopg2://")
    return sa.create_engine(sync_url, pool_pre_ping=True)


@celery_app.task(name="app.tasks.retention.run_retention_sweep")
def run_retention_sweep() -> dict:
    """Delete audit_logs rows that exceed each org's retention_days threshold.

    Returns a summary dict:
        {
          "orgs_processed": int,
          "total_rows_deleted": int,
          "errors": [str, ...],
        }
    """
    import sqlalchemy as sa
    from sqlalchemy import text

    engine = _get_sync_engine()
    total_deleted = 0
    orgs_processed = 0
    errors: list[str] = []

    try:
        with engine.connect() as conn:
            # Fetch all orgs with a non-null retention window
            orgs = conn.execute(
                text("SELECT id, name, retention_days FROM organizations WHERE retention_days IS NOT NULL")
            ).fetchall()

            for org_id, org_name, retention_days in orgs:
                try:
                    result = conn.execute(
                        text(
                            """
                            DELETE FROM audit_logs
                            WHERE org_id = :org_id
                              AND timestamp < NOW() - (:days || ' days')::INTERVAL
                            """
                        ),
                        {"org_id": str(org_id), "days": retention_days},
                    )
                    rows_deleted = result.rowcount
                    conn.commit()
                    total_deleted += rows_deleted
                    orgs_processed += 1

                    logger.info(
                        "retention_sweep: org=%s (%s) deleted=%d rows older than %d days",
                        org_id,
                        org_name,
                        rows_deleted,
                        retention_days,
                    )

                    # Write a sweep audit record (bypass RLS — direct INSERT)
                    if rows_deleted > 0:
                        conn.execute(
                            text(
                                """
                                INSERT INTO audit_logs
                                    (org_id, query_id, username, role, query, outcome,
                                     rbac_violation, security_violation, timestamp, metadata)
                                VALUES
                                    (:org_id, gen_random_uuid()::text, 'system', 'system',
                                     'retention_sweep', 'retention_sweep',
                                     false, false, now(),
                                     :metadata::jsonb)
                                """
                            ),
                            {
                                "org_id": str(org_id),
                                "metadata": f'{{"rows_deleted": {rows_deleted}, "retention_days": {retention_days}}}',
                            },
                        )
                        conn.commit()

                except Exception as org_exc:
                    conn.rollback()
                    msg = f"org={org_id}: {org_exc}"
                    logger.error("retention_sweep error: %s", msg)
                    errors.append(msg)

    except Exception as exc:
        logger.error("retention_sweep: failed to connect to database: %s", exc)
        errors.append(str(exc))

    return {
        "orgs_processed": orgs_processed,
        "total_rows_deleted": total_deleted,
        "errors": errors,
        "swept_at": datetime.now(timezone.utc).isoformat(),
    }
