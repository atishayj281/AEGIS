"""Org-scoped self-service provisioning routes.

Allows org_admin and team_lead users to manage users/teams within their own
organization, WITHOUT needing a platform_admin token.

Trust boundary
--------------
These routes are gated by ``get_current_user`` (standard Auth0 JWT) and
``get_db`` (RLS-scoped session — NOT a BYPASSRLS session).  Callers are still
subject to row-level security; they can only see rows that RLS exposes for
their ``org_id``.  No route here opens a bypass session.

Permission matrix (enforced by ``_require_org_admin_or_team_lead``)
--------------------------------------------------------------------
Action                              org_admin          team_lead
----------------------------------  -----------------  -------------------------
Create team in own org              ✓ any team         ✗ 403
Provision a user                    ✓ any team         ✓ own team only
Assign an existing role (non admin) ✓ any user/team    ✓ own team only
Promote to org_admin                ✗ 403              ✗ 403
Deactivate a user                   ✓ org-wide         ✓ own team only

Auth0 provisioning
------------------
``POST /api/v1/org/users`` and the role-change branch of
``PATCH /api/v1/org/users/{user_id}`` use the same
``auth0_management.create_auth0_user`` / ``sync_existing_user`` +
``rollback_created_user`` / ``rollback_synced_user`` pattern as
``platform_admin.py``.  The logic is NOT duplicated — the same functions
from ``app.auth.auth0_management`` are imported and called directly.

Org-id resolution
-----------------
``org_id`` for all routes comes from the caller's own JWT context
(``get_current_user``→ ``user.org_id``), NOT from a path parameter.  The
caller can only ever act on their own org.
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.auth import auth0_management
from app.auth.jwt_auth import User
from app.models.provisioning import VALID_ROLES, UserRecord, TeamRecord

router = APIRouter(prefix="/api/v1/org", tags=["org-admin"])

# ---------------------------------------------------------------------------
# Request schemas (local to this module — not shared with platform_admin.py)
# ---------------------------------------------------------------------------

_ASSIGNABLE_ROLES: frozenset[str] = VALID_ROLES - {"org_admin"}
"""Roles that org_admin / team_lead can assign.  org_admin is excluded — only
a platform admin can grant that role via /api/v1/platform/..."""


class CreateTeamRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class OrgProvisionUserRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    display_name: str | None = Field(default=None, max_length=255)
    role: str = Field(
        default="employee",
        description=f"Initial role. Must be one of: {sorted(_ASSIGNABLE_ROLES)}",
    )
    team_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Team to assign the user to.  Required for team_lead callers.  "
            "org_admin callers may omit this to use the org's _org_default team."
        ),
    )


class OrgUpdateUserRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    role: str | None = Field(
        default=None,
        description=f"New RBAC role. Must be one of: {sorted(_ASSIGNABLE_ROLES)}",
    )
    team_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Required when changing role — identifies which team's membership "
            "to update.  team_lead callers must supply their own team."
        ),
    )


# ---------------------------------------------------------------------------
# Role-check helper
# ---------------------------------------------------------------------------

class _CallerCtx:
    """Resolved caller role context for an in-org request."""

    def __init__(
        self,
        is_org_admin: bool,
        led_team_ids: frozenset[uuid.UUID],
        org_id: uuid.UUID,
        user: User,
    ) -> None:
        self.is_org_admin = is_org_admin
        self.led_team_ids = led_team_ids  # teams where caller is team_lead
        self.org_id = org_id
        self.user = user

    def assert_can_act_on_team(self, team_id: uuid.UUID | None) -> None:
        """Raise 403 if the caller is not allowed to act on the given team.

        org_admin → always allowed (org-wide authority).
        team_lead → only allowed if team_id is one of their led teams.
        Neither    → always 403.
        """
        if self.is_org_admin:
            return
        if team_id is not None and team_id in self.led_team_ids:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "org_admin role required for org-wide actions, or "
                "team_lead membership in the target team is required."
            ),
        )

    def assert_can_deactivate(self, user_team_ids: list[uuid.UUID]) -> None:
        """Raise 403 if caller can't deactivate a user that belongs to user_team_ids.

        org_admin → always allowed.
        team_lead → allowed only if caller leads at least one of the user's teams.
        """
        if self.is_org_admin:
            return
        if self.led_team_ids.intersection(user_team_ids):
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be org_admin or team_lead for at least one of this user's teams.",
        )


async def _resolve_caller(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> _CallerCtx:
    """Dependency: resolve whether the caller is org_admin or team_lead.

    Raises 403 immediately if the caller has neither role in their org.
    """
    if not user.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No org_id found in token — platform admin tokens cannot use org-scoped routes.",
        )
    if not user.db_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Caller user record not found in database.",
        )

    org_id = uuid.UUID(user.org_id)
    user_uuid = user.db_id  # already a uuid.UUID from get_current_user

    # Load all team_memberships for this user within their org.
    result = await db.execute(
        text(
            "SELECT team_id, role FROM team_memberships "
            "WHERE user_id = :user_id AND org_id = :org_id"
        ),
        {"user_id": str(user_uuid), "org_id": str(org_id)},
    )
    rows = result.fetchall()

    is_org_admin = any(r[1] == "org_admin" for r in rows)
    led_team_ids = frozenset(r[0] for r in rows if r[1] == "team_lead")

    if not is_org_admin and not led_team_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="org_admin or team_lead role required to use org provisioning routes.",
        )

    return _CallerCtx(
        is_org_admin=is_org_admin,
        led_team_ids=led_team_ids,
        org_id=org_id,
        user=user,
    )


# ---------------------------------------------------------------------------
# Helper: resolve the _org_default team id for an org
# ---------------------------------------------------------------------------

async def _get_default_team_id(db: AsyncSession, org_id: uuid.UUID) -> uuid.UUID:
    """Return the id of the _org_default team, or raise 500 if missing."""
    result = await db.execute(
        text("SELECT id FROM teams WHERE org_id = :org_id AND name = '_org_default'"),
        {"org_id": str(org_id)},
    )
    row = result.fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"Organization {org_id} has no default team. "
                "Run scripts/backfill_default_teams.py to repair."
            ),
        )
    return row[0]


# ---------------------------------------------------------------------------
# Helper: validate that a team_id belongs to the caller's org
# ---------------------------------------------------------------------------

async def _validate_team_in_org(
    db: AsyncSession, team_id: uuid.UUID, org_id: uuid.UUID
) -> None:
    """Raise 404 if team_id does not exist in org_id."""
    result = await db.execute(
        text("SELECT id FROM teams WHERE id = :team_id AND org_id = :org_id"),
        {"team_id": str(team_id), "org_id": str(org_id)},
    )
    if result.fetchone() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Team {team_id} not found in your organization.",
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/teams",
    response_model=TeamRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Create a team within the caller's org (org_admin only)",
)
async def create_team(
    body: CreateTeamRequest,
    caller: _CallerCtx = Depends(_resolve_caller),
    db: AsyncSession = Depends(get_db),
) -> TeamRecord:
    """Create a new team in the caller's organization.

    Only ``org_admin`` users may create teams.  ``team_lead`` callers receive
    403.
    """
    if not caller.is_org_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only org_admin users can create teams.",
        )

    # Pre-check uniqueness for a friendlier error than a raw constraint 409.
    dup = await db.execute(
        text("SELECT id FROM teams WHERE org_id = :org_id AND name = :name"),
        {"org_id": str(caller.org_id), "name": body.name},
    )
    if dup.fetchone():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A team named '{body.name}' already exists in your organization.",
        )

    result = await db.execute(
        text(
            "INSERT INTO teams (org_id, name) VALUES (:org_id, :name) "
            "RETURNING id, org_id, name, created_at"
        ),
        {"org_id": str(caller.org_id), "name": body.name},
    )
    row = result.fetchone()
    return TeamRecord(
        id=row[0],
        org_id=row[1],
        name=row[2],
        created_at=row[3].isoformat() if row[3] else None,
    )


@router.post(
    "/users",
    response_model=UserRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Provision a user into the caller's org",
)
async def provision_user(
    body: OrgProvisionUserRequest,
    caller: _CallerCtx = Depends(_resolve_caller),
    db: AsyncSession = Depends(get_db),
) -> UserRecord:
    """Provision a new user into the caller's organization.

    Permission rules:
    - ``org_admin``: may provision into any team; ``team_id`` is optional
      (defaults to the org's ``_org_default`` team).
    - ``team_lead``: must supply ``team_id``; it must be a team they lead.
    - Neither role may grant ``org_admin`` — 403 if ``body.role == "org_admin"``.
    """
    # Block org_admin self-promotion unconditionally.
    if body.role == "org_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="org_admin cannot be granted via org-scoped provisioning. Use platform admin routes.",
        )
    if body.role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid role '{body.role}'. Valid roles: {sorted(_ASSIGNABLE_ROLES)}",
        )

    # Resolve effective team_id.
    if body.team_id is not None:
        await _validate_team_in_org(db, body.team_id, caller.org_id)
        effective_team_id = body.team_id
    else:
        if not caller.is_org_admin:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="team_lead callers must supply a team_id.",
            )
        effective_team_id = await _get_default_team_id(db, caller.org_id)

    # team_lead: verify they actually lead the target team.
    caller.assert_can_act_on_team(effective_team_id)

    # Uniqueness check on email.
    dup = await db.execute(
        text("SELECT id FROM users WHERE email = :email"),
        {"email": body.email},
    )
    if dup.fetchone():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A user with email '{body.email}' already exists.",
        )

    # ── Auth0 first ───────────────────────────────────────────────────────────
    try:
        auth0_user = await auth0_management.create_auth0_user(
            email=body.email,
            org_id=str(caller.org_id),
            roles={str(effective_team_id): body.role},
            display_name=body.display_name,
        )
        auth0_sub = auth0_user["user_id"]
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Auth0 user creation failed: {exc}",
        ) from exc

    # ── Postgres insert (with rollback on failure) ────────────────────────────
    try:
        result = await db.execute(
            text(
                "INSERT INTO users (org_id, auth0_sub, email, display_name) "
                "VALUES (:org_id, :auth0_sub, :email, :display_name) "
                "RETURNING id, org_id, auth0_sub, email, display_name, is_active, created_at"
            ),
            {
                "org_id": str(caller.org_id),
                "auth0_sub": auth0_sub,
                "email": body.email,
                "display_name": body.display_name,
            },
        )
        user_row = result.fetchone()

        await db.execute(
            text(
                "INSERT INTO team_memberships (org_id, team_id, user_id, role) "
                "VALUES (:org_id, :team_id, :user_id, :role)"
            ),
            {
                "org_id": str(caller.org_id),
                "team_id": str(effective_team_id),
                "user_id": str(user_row[0]),
                "role": body.role,
            },
        )
    except Exception as pg_exc:
        await auth0_management.rollback_created_user(auth0_sub)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database insert failed: {pg_exc}",
        ) from pg_exc

    return UserRecord(
        id=user_row[0],
        org_id=user_row[1],
        auth0_sub=user_row[2],
        email=user_row[3],
        display_name=user_row[4],
        is_active=user_row[5],
        created_at=user_row[6].isoformat() if user_row[6] else None,
        role=body.role,
    )


@router.patch(
    "/users/{user_id}",
    response_model=UserRecord,
    summary="Update a user in the caller's org",
)
async def update_user(
    user_id: uuid.UUID,
    body: OrgUpdateUserRequest,
    caller: _CallerCtx = Depends(_resolve_caller),
    db: AsyncSession = Depends(get_db),
) -> UserRecord:
    """Partial-update a user's display_name, is_active status, or role.

    Permission rules:
    - ``org_admin``: may update any user in the org.
    - ``team_lead``: must supply ``team_id``; user must be in that team;
      caller must lead that team.
    - Neither role may grant ``org_admin`` — 403 unconditionally.
    - Auth0 app_metadata is patched FIRST on role change; Postgres is rolled
      back with a compensating ``rollback_synced_user`` call on DB failure.
    """
    # Block org_admin self-promotion unconditionally.
    if body.role == "org_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="org_admin cannot be granted via org-scoped provisioning. Use platform admin routes.",
        )
    if body.role is not None and body.role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid role '{body.role}'. Valid roles: {sorted(_ASSIGNABLE_ROLES)}",
        )

    users_updates: dict[str, object] = {}
    if body.display_name is not None:
        users_updates["display_name"] = body.display_name
    if body.is_active is not None:
        users_updates["is_active"] = body.is_active

    if not users_updates and body.role is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields to update.",
        )

    # ── Load target user ──────────────────────────────────────────────────────
    existing = await db.execute(
        text(
            "SELECT id, org_id, auth0_sub, email, display_name, is_active, created_at "
            "FROM users WHERE id = :user_id AND org_id = :org_id"
        ),
        {"user_id": str(user_id), "org_id": str(caller.org_id)},
    )
    row = existing.fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found in your organization.",
        )

    auth0_sub: str = row[2]

    # ── Permission check for team_lead ────────────────────────────────────────
    if not caller.is_org_admin:
        # team_lead must supply team_id and must lead that team.
        if body.team_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="team_lead callers must supply team_id to identify the target team.",
            )
        await _validate_team_in_org(db, body.team_id, caller.org_id)
        # Verify the target user is actually in that team.
        membership_check = await db.execute(
            text(
                "SELECT id FROM team_memberships "
                "WHERE user_id = :user_id AND team_id = :team_id"
            ),
            {"user_id": str(user_id), "team_id": str(body.team_id)},
        )
        if membership_check.fetchone() is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User {user_id} is not a member of team {body.team_id}.",
            )
        # Confirm the caller actually leads that team.
        caller.assert_can_act_on_team(body.team_id)

    # ── Step 1: Auth0 role sync ───────────────────────────────────────────────
    previous_metadata: dict | None = None
    _default_team_id: uuid.UUID | None = None

    if body.role is not None:
        # Fetch current memberships to build roles dict.
        memberships = await db.execute(
            text(
                "SELECT team_id, role FROM team_memberships "
                "WHERE user_id = :user_id AND org_id = :org_id"
            ),
            {"user_id": str(user_id), "org_id": str(caller.org_id)},
        )
        membership_rows = memberships.fetchall()

        if membership_rows:
            new_roles_dict = {str(r[0]): body.role for r in membership_rows}
        else:
            # Zero memberships — use _org_default.
            _default_team_id = await _get_default_team_id(db, caller.org_id)
            new_roles_dict = {str(_default_team_id): body.role}

        try:
            previous_metadata = await auth0_management.sync_existing_user(
                auth0_sub=auth0_sub,
                org_id=str(caller.org_id),
                roles=new_roles_dict,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Auth0 metadata sync failed: {exc}",
            ) from exc

    # ── Step 2: Postgres updates ──────────────────────────────────────────────
    try:
        if users_updates:
            set_clause = ", ".join(f"{col} = :{col}" for col in users_updates)
            params = dict(users_updates)
            params["user_id"] = str(user_id)
            params["org_id"] = str(caller.org_id)
            result = await db.execute(
                text(
                    f"UPDATE users SET {set_clause}, updated_at = now() "
                    f"WHERE id = :user_id AND org_id = :org_id "
                    f"RETURNING id, org_id, auth0_sub, email, display_name, is_active, created_at"
                ),
                params,
            )
            row = result.fetchone()

        if body.role is not None:
            if _default_team_id is not None:
                # No existing memberships → INSERT onto default team.
                await db.execute(
                    text(
                        "INSERT INTO team_memberships (org_id, team_id, user_id, role) "
                        "VALUES (:org_id, :team_id, :user_id, :role)"
                    ),
                    {
                        "org_id": str(caller.org_id),
                        "team_id": str(_default_team_id),
                        "user_id": str(user_id),
                        "role": body.role,
                    },
                )
            else:
                # Existing memberships → UPDATE all (org-wide) or the specific team
                # if team_id was supplied (team_lead case).
                if body.team_id is not None:
                    await db.execute(
                        text(
                            "UPDATE team_memberships SET role = :role "
                            "WHERE user_id = :user_id AND team_id = :team_id"
                        ),
                        {
                            "role": body.role,
                            "user_id": str(user_id),
                            "team_id": str(body.team_id),
                        },
                    )
                else:
                    # org_admin updating all memberships at once.
                    await db.execute(
                        text(
                            "UPDATE team_memberships SET role = :role "
                            "WHERE user_id = :user_id AND org_id = :org_id"
                        ),
                        {
                            "role": body.role,
                            "user_id": str(user_id),
                            "org_id": str(caller.org_id),
                        },
                    )
    except Exception as pg_exc:
        if previous_metadata is not None:
            await auth0_management.rollback_synced_user(auth0_sub, previous_metadata)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database update failed: {pg_exc}",
        ) from pg_exc

    # Re-fetch the final role for the response.
    role_row = await db.execute(
        text(
            "SELECT tm.role FROM team_memberships tm "
            "WHERE tm.user_id = :user_id "
            "ORDER BY tm.created_at DESC NULLS LAST LIMIT 1"
        ),
        {"user_id": str(user_id)},
    )
    final_role = role_row.scalar()

    return UserRecord(
        id=row[0],
        org_id=row[1],
        auth0_sub=row[2],
        email=row[3],
        display_name=row[4],
        is_active=row[5],
        created_at=row[6].isoformat() if row[6] else None,
        role=final_role,
    )


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate a user (soft delete) in the caller's org",
)
async def deactivate_user(
    user_id: uuid.UUID,
    caller: _CallerCtx = Depends(_resolve_caller),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Set ``is_active = false`` on the target user.

    Permission rules:
    - ``org_admin``: may deactivate any user in the org.
    - ``team_lead``: may only deactivate users who are members of at least
      one team the caller leads.
    """
    # Verify the user exists in this org.
    existing = await db.execute(
        text("SELECT id FROM users WHERE id = :user_id AND org_id = :org_id"),
        {"user_id": str(user_id), "org_id": str(caller.org_id)},
    )
    if existing.fetchone() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found in your organization.",
        )

    if not caller.is_org_admin:
        # Fetch which teams the target user belongs to.
        team_result = await db.execute(
            text(
                "SELECT team_id FROM team_memberships "
                "WHERE user_id = :user_id AND org_id = :org_id"
            ),
            {"user_id": str(user_id), "org_id": str(caller.org_id)},
        )
        user_team_ids = [r[0] for r in team_result.fetchall()]
        caller.assert_can_deactivate(user_team_ids)

    await db.execute(
        text(
            "UPDATE users SET is_active = false, updated_at = now() "
            "WHERE id = :user_id AND org_id = :org_id"
        ),
        {"user_id": str(user_id), "org_id": str(caller.org_id)},
    )
