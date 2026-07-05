"""Audit logging — dual-write: Postgres (primary) and flat file (fallback).

Architecture
------------
``log_async``  — awaitable; INSERTs into the ``audit_logs`` Postgres table
                 scoped to the caller's org.  Falls back to the flat file on
                 any DB error so the pipeline never silently swallows audit
                 events.

``log``        — kept for backward compatibility and for call sites that run
                 outside an async context (e.g. Celery tasks).  Writes to the
                 flat file only.

``get_recent_async`` / ``get_stats_async``
                — query Postgres; used by the ``/audit/recent`` and
                  ``/audit/stats`` endpoints introduced in Phase 6.

``get_recent`` / ``get_stats``
                — sync fallback; read from the flat file.  Retained for tests
                  that do not provision a Postgres connection.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import Settings, get_settings
from app.models.schemas import AuditLogEntry

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class AuditLogger:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.log_path = self.settings.audit_log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: list[AuditLogEntry] = []

    # ── Sync (flat-file) interface — backward compat ─────────────────────────

    def log(self, entry: AuditLogEntry) -> None:
        """Write an audit entry to the flat file.

        This remains a synchronous call so it can be used from Celery tasks
        and legacy call sites.  The pipeline uses ``log_async`` instead.
        """
        self._entries.append(entry)
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(entry.model_dump_json() + "\n")
        except Exception as exc:
            logger.error("AuditLogger: flat-file write failed: %s", exc)

    def get_recent(self, limit: int = 50) -> list[AuditLogEntry]:
        if not self.log_path.exists():
            return self._entries[-limit:]

        entries: list[AuditLogEntry] = []
        with open(self.log_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(AuditLogEntry.model_validate_json(line))
                    except Exception:
                        continue
        return entries[-limit:]

    def get_stats(self) -> dict:
        recent = self.get_recent(1000)
        return {
            "total_logged": len(recent),
            "rbac_violations": sum(1 for e in recent if e.rbac_violation),
            "security_violations": sum(1 for e in recent if e.security_violation),
            "avg_response_time_ms": (
                round(sum(e.response_time_ms or 0 for e in recent) / len(recent), 2) if recent else 0
            ),
        }

    # ── Async (Postgres) interface — Phase 6 ─────────────────────────────────

    async def log_async(self, entry: AuditLogEntry, db: "AsyncSession", org_id: str) -> None:
        """INSERT an audit entry into Postgres.

        Falls back to the flat-file logger on any exception so audit events
        are never silently dropped even if the DB is temporarily unreachable.

        Parameters
        ----------
        entry:  The audit entry to persist.
        db:     An ``AsyncSession`` that already has ``app.current_org_id``
                set by the ``get_db`` dependency (required for RLS).
        org_id: The caller's org UUID string — stored as the ``org_id``
                column value so the RLS policy can filter it.
        """
        from sqlalchemy import text

        try:
            await db.execute(
                text(
                    """
                    INSERT INTO audit_logs
                        (org_id, query_id, username, role, query, intent, outcome,
                         rbac_violation, security_violation, response_time_ms,
                         timestamp, metadata)
                    VALUES
                        (:org_id, :query_id, :username, :role, :query, :intent,
                         :outcome, :rbac_violation, :security_violation,
                         :response_time_ms, :timestamp, :metadata::jsonb)
                    """
                ),
                {
                    "org_id": org_id,
                    "query_id": entry.query_id,
                    "username": entry.username,
                    "role": entry.role,
                    "query": entry.query,
                    "intent": entry.intent.value if entry.intent else None,
                    "outcome": entry.outcome,
                    "rbac_violation": entry.rbac_violation,
                    "security_violation": entry.security_violation,
                    "response_time_ms": entry.response_time_ms,
                    "timestamp": entry.timestamp,
                    "metadata": json.dumps(entry.metadata),
                },
            )
        except Exception as exc:
            logger.error(
                "AuditLogger.log_async: Postgres INSERT failed (%s). "
                "Falling back to flat-file write.",
                exc,
            )
            self.log(entry)

    async def get_recent_async(
        self,
        db: "AsyncSession",
        limit: int = 50,
        username: str | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[AuditLogEntry]:
        """SELECT recent audit entries from Postgres, newest first.

        RLS ensures the query is automatically scoped to the caller's org.
        """
        from sqlalchemy import text

        clauses = ["1=1"]
        params: dict = {"limit": limit}
        if username:
            clauses.append("username = :username")
            params["username"] = username
        if from_date:
            clauses.append("timestamp >= :from_date")
            params["from_date"] = from_date
        if to_date:
            clauses.append("timestamp <= :to_date")
            params["to_date"] = to_date

        where = " AND ".join(clauses)
        rows = (
            await db.execute(
                text(
                    f"SELECT query_id, username, role, query, intent, outcome, "
                    f"rbac_violation, security_violation, response_time_ms, "
                    f"timestamp, metadata "
                    f"FROM audit_logs "
                    f"WHERE {where} "
                    f"ORDER BY timestamp DESC "
                    f"LIMIT :limit"
                ),
                params,
            )
        ).fetchall()

        entries: list[AuditLogEntry] = []
        for row in rows:
            try:
                entries.append(
                    AuditLogEntry(
                        query_id=row[0] or "",
                        username=row[1],
                        role=row[2],
                        query=row[3],
                        intent=row[4],
                        outcome=row[5],
                        rbac_violation=row[6],
                        security_violation=row[7],
                        response_time_ms=row[8],
                        timestamp=row[9],
                        metadata=row[10] if isinstance(row[10], dict) else {},
                    )
                )
            except Exception as exc:
                logger.warning("AuditLogger.get_recent_async: failed to parse row: %s", exc)
        return entries

    async def get_stats_async(self, db: "AsyncSession") -> dict:
        """Aggregate audit statistics from Postgres for the caller's org."""
        from sqlalchemy import text

        row = (
            await db.execute(
                text(
                    """
                    SELECT
                        COUNT(*)                                          AS total,
                        SUM(CASE WHEN rbac_violation THEN 1 ELSE 0 END)  AS rbac_violations,
                        SUM(CASE WHEN security_violation THEN 1 ELSE 0 END) AS sec_violations,
                        AVG(response_time_ms)                             AS avg_rt_ms
                    FROM audit_logs
                    """
                )
            )
        ).fetchone()

        if not row:
            return {
                "total_logged": 0,
                "rbac_violations": 0,
                "security_violations": 0,
                "avg_response_time_ms": 0,
            }

        return {
            "total_logged": int(row[0] or 0),
            "rbac_violations": int(row[1] or 0),
            "security_violations": int(row[2] or 0),
            "avg_response_time_ms": round(float(row[3] or 0), 2),
        }
