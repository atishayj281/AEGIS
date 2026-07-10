"""Platform superuser API routes (Phase 7 + Provisioning).

All routes in this module use get_platform_admin_db as their sole
auth/DB dependency — that dependency enforces two independent guards
(JWT platform_admin claim + active platform_admins row) before the
BYPASSRLS session is yielded.  No other auth dependency is needed here;
adding a second, weaker dependency (e.g. get_current_user) alongside it
would create two disagreeing sources of truth for the access decision.

Read surface (Phase 7 initial)
-------------------------------
  GET  /api/v1/platform/orgs                         — list every org
  GET  /api/v1/platform/orgs/{org_id}/summary        — per-org health metrics
  GET  /api/v1/platform/orgs/{org_id}/users          — list users in an org

Provisioning surface (Phase 7 extension)
-----------------------------------------
  POST   /api/v1/platform/orgs                             — create org
  PATCH  /api/v1/platform/orgs/{org_id}                   — update org
  DELETE /api/v1/platform/orgs/{org_id}                   — deactivate org (soft)
  POST   /api/v1/platform/orgs/{org_id}/users             — provision user
  PATCH  /api/v1/platform/orgs/{org_id}/users/{user_id}   — update user
  DELETE /api/v1/platform/orgs/{org_id}/users/{user_id}   — deactivate user (soft)

Soft-delete semantics: DELETE endpoints set is_active=false rather than
physically removing rows, to preserve audit trail and FK integrity with
documents / conversations. Hard delete (cascade) is a future operation
that requires explicit ?force=true and is not implemented here.

Auth0 sync: user rows are written only to the local Postgres `users` table.
The Auth0 Management API (M2M) is NOT called here because AUTH0_M2M_CLIENT_ID
/ AUTH0_M2M_CLIENT_SECRET are blank in the default dev env. A provisioned user
won't be able to log in until the corresponding Auth0 account is created;
the platform admin must do that out-of-band (or via Auth0 dashboard) in dev.
"""

from __future__ import annotations

import re
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_platform_admin_db

router = APIRouter(prefix="/api/v1/platform", tags=["platform-admin"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(name: str) -> str:
    """Convert a display name to a URL-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:100]


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class OrgSummary(BaseModel):
    """Lightweight org descriptor returned by the list endpoint."""
    id: uuid.UUID
    name: str
    slug: str | None
    is_active: bool
    created_at: str | None


class OrgDetail(BaseModel):
    """Per-org health metrics returned by the summary endpoint."""
    id: uuid.UUID
    name: str
    slug: str | None
    is_active: bool
    retention_days: int | None
    user_count: int
    document_count: int
    last_activity: str | None


class CreateOrgRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    slug: str | None = Field(
        default=None,
        max_length=100,
        description="URL-safe identifier. Auto-generated from name if omitted.",
    )
    retention_days: int | None = Field(
        default=365,
        ge=1,
        le=3650,
        description="Data retention window in days. Defaults to 365.",
    )

    @field_validator("slug", mode="before")
    @classmethod
    def validate_slug(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not re.match(r"^[a-z0-9][a-z0-9\-]{0,98}[a-z0-9]?$", v):
            raise ValueError(
                "slug must be lowercase alphanumeric with hyphens, "
                "2–100 characters, no leading/trailing hyphens"
            )
        return v


class UpdateOrgRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    slug: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None
    retention_days: int | None = Field(default=None, ge=1, le=3650)


class UserRecord(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    auth0_sub: str
    email: str
    display_name: str | None
    is_active: bool
    created_at: str | None


class CreateUserRequest(BaseModel):
    auth0_sub: str = Field(
        ...,
        min_length=5,
        max_length=255,
        description="Auth0 subject identifier, e.g. 'auth0|abc123'.",
    )
    email: str = Field(..., min_length=5, max_length=320)
    display_name: str | None = Field(default=None, max_length=255)


class UpdateUserRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None


# ---------------------------------------------------------------------------
# Routes — Read (existing)
# ---------------------------------------------------------------------------


@router.get(
    "/orgs",
    response_model=list[OrgSummary],
    summary="List all organizations (platform admin only)",
)
async def list_all_orgs(
    db: AsyncSession = Depends(get_platform_admin_db),
) -> list[OrgSummary]:
    """Return every row in the organizations table (RLS bypassed)."""
    result = await db.execute(
        text("SELECT id, name, slug, is_active, created_at FROM organizations ORDER BY name")
    )
    rows = result.fetchall()
    return [
        OrgSummary(
            id=row[0],
            name=row[1],
            slug=row[2],
            is_active=row[3],
            created_at=row[4].isoformat() if row[4] else None,
        )
        for row in rows
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
    """Return basic health metrics for a single org."""
    org_result = await db.execute(
        text("SELECT id, name, slug, is_active, retention_days FROM organizations WHERE id = :org_id"),
        {"org_id": str(org_id)},
    )
    org_row = org_result.fetchone()
    if org_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization {org_id} not found",
        )

    user_count = (await db.execute(
        text("SELECT COUNT(*) FROM users WHERE org_id = :org_id"),
        {"org_id": str(org_id)},
    )).scalar() or 0

    doc_count = (await db.execute(
        text("SELECT COUNT(*) FROM documents WHERE org_id = :org_id"),
        {"org_id": str(org_id)},
    )).scalar() or 0

    last_ts = (await db.execute(
        text(
            "SELECT MAX(ct.created_at) "
            "FROM conversation_turns ct "
            "JOIN conversations c ON c.id = ct.conversation_id "
            "WHERE c.org_id = :org_id"
        ),
        {"org_id": str(org_id)},
    )).scalar()
    last_activity = last_ts.isoformat() if last_ts else None

    return OrgDetail(
        id=org_row[0],
        name=org_row[1],
        slug=org_row[2],
        is_active=org_row[3],
        retention_days=org_row[4],
        user_count=user_count,
        document_count=doc_count,
        last_activity=last_activity,
    )


@router.get(
    "/orgs/{org_id}/users",
    response_model=list[UserRecord],
    summary="List all users in an org (platform admin only)",
)
async def list_org_users(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_platform_admin_db),
) -> list[UserRecord]:
    """Return every user row for a given org (RLS bypassed)."""
    # Confirm org exists first so the caller gets a 404, not an empty list.
    org_check = await db.execute(
        text("SELECT id FROM organizations WHERE id = :org_id"),
        {"org_id": str(org_id)},
    )
    if org_check.fetchone() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Organization {org_id} not found")

    result = await db.execute(
        text(
            "SELECT id, org_id, auth0_sub, email, display_name, is_active, created_at "
            "FROM users WHERE org_id = :org_id ORDER BY email"
        ),
        {"org_id": str(org_id)},
    )
    rows = result.fetchall()
    return [
        UserRecord(
            id=row[0],
            org_id=row[1],
            auth0_sub=row[2],
            email=row[3],
            display_name=row[4],
            is_active=row[5],
            created_at=row[6].isoformat() if row[6] else None,
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Routes — Org Provisioning (new)
# ---------------------------------------------------------------------------


@router.post(
    "/orgs",
    response_model=OrgSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new organization (platform admin only)",
)
async def create_org(
    body: CreateOrgRequest,
    db: AsyncSession = Depends(get_platform_admin_db),
) -> OrgSummary:
    """Insert a new row into the organizations table.

    Slug is auto-generated from name if not provided.  Both name and slug
    are checked for uniqueness; a 409 is returned on conflict rather than
    letting the DB constraint surface a 500.
    """
    slug = body.slug or _slugify(body.name)

    # Uniqueness pre-checks — friendlier than a raw constraint error.
    slug_check = await db.execute(
        text("SELECT id FROM organizations WHERE slug = :slug"),
        {"slug": slug},
    )
    if slug_check.fetchone():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An organization with slug '{slug}' already exists.",
        )

    result = await db.execute(
        text(
            "INSERT INTO organizations (name, slug, retention_days) "
            "VALUES (:name, :slug, :retention_days) "
            "RETURNING id, name, slug, is_active, created_at"
        ),
        {"name": body.name, "slug": slug, "retention_days": body.retention_days},
    )
    row = result.fetchone()
    return OrgSummary(
        id=row[0],
        name=row[1],
        slug=row[2],
        is_active=row[3],
        created_at=row[4].isoformat() if row[4] else None,
    )


@router.patch(
    "/orgs/{org_id}",
    response_model=OrgSummary,
    summary="Update an organization (platform admin only)",
)
async def update_org(
    org_id: uuid.UUID,
    body: UpdateOrgRequest,
    db: AsyncSession = Depends(get_platform_admin_db),
) -> OrgSummary:
    """Partial-update an org row. Only supplied fields are changed."""
    # Confirm org exists.
    existing = await db.execute(
        text("SELECT id FROM organizations WHERE id = :org_id"),
        {"org_id": str(org_id)},
    )
    if existing.fetchone() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Organization {org_id} not found")

    # Build SET clause dynamically from only the fields the caller sent.
    updates: dict[str, object] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.slug is not None:
        updates["slug"] = body.slug
    if body.is_active is not None:
        updates["is_active"] = body.is_active
    if body.retention_days is not None:
        updates["retention_days"] = body.retention_days

    if not updates:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No fields to update.")

    updates["updated_at"] = "now()"
    set_clause = ", ".join(
        f"{col} = now()" if val == "now()" else f"{col} = :{col}"
        for col, val in updates.items()
    )
    params = {k: v for k, v in updates.items() if v != "now()"}
    params["org_id"] = str(org_id)

    result = await db.execute(
        text(
            f"UPDATE organizations SET {set_clause}, updated_at = now() "
            f"WHERE id = :org_id "
            f"RETURNING id, name, slug, is_active, created_at"
        ),
        params,
    )
    row = result.fetchone()
    return OrgSummary(
        id=row[0], name=row[1], slug=row[2], is_active=row[3],
        created_at=row[4].isoformat() if row[4] else None,
    )


@router.delete(
    "/orgs/{org_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate an organization (soft delete, platform admin only)",
)
async def deactivate_org(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_platform_admin_db),
) -> None:
    """Set is_active=false on the org. All its data is preserved."""
    result = await db.execute(
        text("UPDATE organizations SET is_active = false, updated_at = now() WHERE id = :org_id RETURNING id"),
        {"org_id": str(org_id)},
    )
    if result.fetchone() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Organization {org_id} not found")


# ---------------------------------------------------------------------------
# Routes — User Provisioning (new)
# ---------------------------------------------------------------------------


@router.post(
    "/orgs/{org_id}/users",
    response_model=UserRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Provision a user into an org (platform admin only)",
)
async def create_user(
    org_id: uuid.UUID,
    body: CreateUserRequest,
    db: AsyncSession = Depends(get_platform_admin_db),
) -> UserRecord:
    """Insert a user row into the users table for the given org.

    auth0_sub must be globally unique (one Auth0 account can only belong to
    one org in this schema).  A 409 is returned if the sub already exists.
    """
    # Confirm org exists.
    org_check = await db.execute(
        text("SELECT id FROM organizations WHERE id = :org_id"),
        {"org_id": str(org_id)},
    )
    if org_check.fetchone() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Organization {org_id} not found")

    # Uniqueness check on auth0_sub.
    sub_check = await db.execute(
        text("SELECT id FROM users WHERE auth0_sub = :sub"),
        {"sub": body.auth0_sub},
    )
    if sub_check.fetchone():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A user with auth0_sub '{body.auth0_sub}' already exists.",
        )

    result = await db.execute(
        text(
            "INSERT INTO users (org_id, auth0_sub, email, display_name) "
            "VALUES (:org_id, :auth0_sub, :email, :display_name) "
            "RETURNING id, org_id, auth0_sub, email, display_name, is_active, created_at"
        ),
        {
            "org_id": str(org_id),
            "auth0_sub": body.auth0_sub,
            "email": body.email,
            "display_name": body.display_name,
        },
    )
    row = result.fetchone()
    return UserRecord(
        id=row[0], org_id=row[1], auth0_sub=row[2], email=row[3],
        display_name=row[4], is_active=row[5],
        created_at=row[6].isoformat() if row[6] else None,
    )


@router.patch(
    "/orgs/{org_id}/users/{user_id}",
    response_model=UserRecord,
    summary="Update a user in an org (platform admin only)",
)
async def update_user(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    body: UpdateUserRequest,
    db: AsyncSession = Depends(get_platform_admin_db),
) -> UserRecord:
    """Partial-update a user's display_name or is_active status."""
    updates: dict[str, object] = {}
    if body.display_name is not None:
        updates["display_name"] = body.display_name
    if body.is_active is not None:
        updates["is_active"] = body.is_active

    if not updates:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No fields to update.")

    set_clause = ", ".join(f"{col} = :{col}" for col in updates)
    params = dict(updates)
    params["user_id"] = str(user_id)
    params["org_id"] = str(org_id)

    result = await db.execute(
        text(
            f"UPDATE users SET {set_clause}, updated_at = now() "
            f"WHERE id = :user_id AND org_id = :org_id "
            f"RETURNING id, org_id, auth0_sub, email, display_name, is_active, created_at"
        ),
        params,
    )
    row = result.fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User {user_id} not found in org {org_id}")
    return UserRecord(
        id=row[0], org_id=row[1], auth0_sub=row[2], email=row[3],
        display_name=row[4], is_active=row[5],
        created_at=row[6].isoformat() if row[6] else None,
    )


@router.delete(
    "/orgs/{org_id}/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate a user (soft delete, platform admin only)",
)
async def deactivate_user(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_platform_admin_db),
) -> None:
    """Set is_active=false on the user. Row and all linked data are preserved."""
    result = await db.execute(
        text(
            "UPDATE users SET is_active = false, updated_at = now() "
            "WHERE id = :user_id AND org_id = :org_id RETURNING id"
        ),
        {"user_id": str(user_id), "org_id": str(org_id)},
    )
    if result.fetchone() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User {user_id} not found in org {org_id}")
