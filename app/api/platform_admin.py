"""Platform superuser API routes (Phase 7).

All routes in this module use get_platform_admin_db as their sole
auth/DB dependency — that dependency enforces two independent guards
(JWT platform_admin claim + active platform_admins row) before the
BYPASSRLS session is yielded.  No other auth dependency is needed here;
adding a second, weaker dependency (e.g. get_current_user) alongside it
would create two disagreeing sources of truth for the access decision.

Scope of this module (Phase 7 initial surface: read-only cross-org visibility)
--------------------------------------------------------------------------------
  GET /api/v1/platform/orgs                    — list every org
  GET /api/v1/platform/orgs/{org_id}/summary   — per-org health metrics

Write operations (cross-org delete, cross-org export) are NOT added here.
Phase 6's org_admin-scoped delete/export already exists; a platform-level
write surface belongs in a future phase once the read path has proven itself.
See Phase 7 plan note: "Do not add write/delete operations in this task."
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_platform_admin_db

router = APIRouter(prefix="/api/v1/platform", tags=["platform-admin"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class OrgSummary(BaseModel):
    """Lightweight org descriptor returned by the list endpoint."""
    id: uuid.UUID
    name: str
    plan_tier: str | None


class OrgDetail(BaseModel):
    """Per-org health metrics returned by the summary endpoint."""
    id: uuid.UUID
    name: str
    plan_tier: str | None
    user_count: int
    document_count: int
    # ISO-8601 string from the DB; None if the org has no conversations yet.
    last_activity: str | None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/orgs",
    response_model=list[OrgSummary],
    summary="List all organizations (platform admin only)",
    description=(
        "Returns every organization row, bypassing RLS. "
        "Only accessible to tokens with the platform_admin role "
        "that have a matching active row in the platform_admins table."
    ),
)
async def list_all_orgs(
    db: AsyncSession = Depends(get_platform_admin_db),
) -> list[OrgSummary]:
    """Return every row in the organizations table (RLS bypassed).

    The BYPASSRLS connection guarantees this query is not filtered by
    app.current_org_id — it truly returns all orgs, not just those that
    happen to match the setting (which is never set on the bypass session).
    """
    result = await db.execute(
        text("SELECT id, name, plan_tier FROM organizations ORDER BY name")
    )
    rows = result.fetchall()
    return [
        OrgSummary(id=row[0], name=row[1], plan_tier=row[2]) for row in rows
    ]


@router.get(
    "/orgs/{org_id}/summary",
    response_model=OrgDetail,
    summary="Get per-org health summary (platform admin only)",
)
async def get_org_summary(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_platform_admin_db),
) -> OrgDetail:
    """Return basic health metrics for a single org.

    Metrics are computed at query time (no materialized cache) — appropriate
    for a low-volume admin surface.  If the org_id is not found, 404 is
    returned rather than silently returning zeros, so callers can distinguish
    "org exists but empty" from "org does not exist."
    """
    # Fetch org row
    org_result = await db.execute(
        text("SELECT id, name, plan_tier FROM organizations WHERE id = :org_id"),
        {"org_id": str(org_id)},
    )
    org_row = org_result.fetchone()
    if org_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization {org_id} not found",
        )

    # User count
    user_result = await db.execute(
        text("SELECT COUNT(*) FROM users WHERE org_id = :org_id"),
        {"org_id": str(org_id)},
    )
    user_count = user_result.scalar() or 0

    # Document count
    doc_result = await db.execute(
        text("SELECT COUNT(*) FROM documents WHERE org_id = :org_id"),
        {"org_id": str(org_id)},
    )
    doc_count = doc_result.scalar() or 0

    # Last activity — most recent conversation turn timestamp for this org.
    # conversations joins conversation_turns; no direct org_id on turns.
    last_activity_result = await db.execute(
        text(
            "SELECT MAX(ct.ts) "
            "FROM conversation_turns ct "
            "JOIN conversations c ON c.id = ct.conversation_id "
            "WHERE c.org_id = :org_id"
        ),
        {"org_id": str(org_id)},
    )
    last_ts = last_activity_result.scalar()
    last_activity = last_ts.isoformat() if last_ts else None

    return OrgDetail(
        id=org_row[0],
        name=org_row[1],
        plan_tier=org_row[2],
        user_count=user_count,
        document_count=doc_count,
        last_activity=last_activity,
    )
