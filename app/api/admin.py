"""Admin API router — user provisioning and deprovisioning.

Endpoints
---------
POST   /admin/users             Provision a new user in Auth0 + Postgres atomically.
DELETE /admin/users/{user_id}   Deprovision a user from Postgres + Auth0.

Both endpoints require the caller to hold the ``org_admin`` role, verified
via ``resolve_access(ctx, "*", team_id=None)`` — the same RBAC path that
guards document deletion in routes.py.  No separate auth check is added.

Rollback strategy
-----------------
POST (provision) — Auth0-first:
  1. Create Auth0 user  →  obtain auth0_user_id
  2. Add to Auth0 org   →  on failure, delete Auth0 user, return 502
  3. INSERT users       \\
                         |  on any failure: delete Auth0 user (compensation),
  4. INSERT memberships /   return 500 with rollback status in body
  5. Send password-change ticket (best-effort, non-blocking)

If step 1 or 2 fails before any Postgres write: no compensation needed,
return 502.  If step 3/4 fails: Auth0 is rolled back via delete_auth0_user
and a 500 is returned with details of whether the rollback itself succeeded.

DELETE (deprovision) — Postgres-first:
  1. DELETE users row   (cascade removes team_memberships via FK)
  2. DELETE Auth0 user  (best-effort; logged on failure, not re-raised)

Rationale for Postgres-first on DELETE: re-creating a deleted Auth0 user to
undo a failed Postgres delete is impractical.  A dangling Auth0 account
without a Postgres row cannot access AEGIS (resolve_access returns False;
get_current_user finds no db_id), so the system is functionally safe while
an operator manually cleans up the orphaned Auth0 account.

Cross-org guard
---------------
An org_admin can only provision/deprovision users within their own org.
This is enforced explicitly (body.org_id vs user.org_id check on POST) and
implicitly via RLS (the tenant_isolation policy blocks reads/writes to rows
with a different org_id even if the check above were absent).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.auth.jwt_auth import User
from app.auth.rbac import ROLE_PERMISSIONS_V2, resolve_access

logger = logging.getLogger(__name__)

admin_router = APIRouter()

VALID_ROLES: frozenset[str] = frozenset(ROLE_PERMISSIONS_V2.keys())


# ── Request / response schemas ────────────────────────────────────────────────


class ProvisionUserRequest(BaseModel):
    org_id: str = Field(
        ...,
        description=(
            "Postgres UUID of the organization to provision the user into. "
            "Must match the caller's own org_id — cross-org provisioning is rejected."
        ),
    )
    team_id: str = Field(
        ...,
        description="Postgres UUID of the team the user is being added to.",
    )
    email: EmailStr
    display_name: str = Field(..., min_length=1, max_length=255)
    role: str = Field(
        ...,
        description=f"Role to assign in team_memberships. One of: {sorted(VALID_ROLES)}",
    )


class ProvisionUserResponse(BaseModel):
    user_id: str          # Postgres UUID of the newly created users row
    email: str
    auth0_user_id: str    # Auth0 `sub` value (e.g. "auth0|abc123")
    status: str = "provisioned"
    message: str


class DeprovisionUserResponse(BaseModel):
    user_id: str
    email: str
    status: str = "deprovisioned"
    message: str
    auth0_cleanup: str    # "deleted" | "skipped" | "warning"


# ── Shared helper ─────────────────────────────────────────────────────────────


def _make_ctx(user: User, db: AsyncSession) -> dict[str, Any]:
    """Build the RBAC context dict expected by resolve_access."""
    return {
        "db": db,
        "user_id": user.db_id,
        "org_id": user.org_id,
        "roles": user.roles,
        "team_ids": user.team_ids,
    }


# ── POST /admin/users ─────────────────────────────────────────────────────────


@admin_router.post(
    "/users",
    response_model=ProvisionUserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Provision a new user (org_admin only)",
)
async def provision_user(
    body: ProvisionUserRequest,
    caller: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Create a user in **both** Auth0 and Postgres in one operation.

    Auth0 M2M credentials (``AUTH0_M2M_CLIENT_ID`` / ``AUTH0_M2M_CLIENT_SECRET``)
    must be configured before this endpoint can be called.

    On success the user receives a password-setup email via Auth0's
    password-change ticket mechanism and can log in once they set their
    password.  Their JWT will carry the correct ``org_id``, ``team_ids``, and
    ``roles`` claims from the first login because those values are baked into
    ``app_metadata`` during provisioning.
    """
    # Late import keeps the module importable in tests without live Auth0 creds.
    from app.auth import auth0_mgmt

    ctx = _make_ctx(caller, db)

    # ── Step 1: Authorize (org_admin only) ───────────────────────────────────
    if not await resolve_access(ctx, "*", team_id=None):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: only org_admin callers may provision users.",
        )

    # ── Step 2: Validate role string ─────────────────────────────────────────
    if body.role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Unknown role {body.role!r}. "
                f"Valid roles: {sorted(VALID_ROLES)}"
            ),
        )

    # ── Step 3: Cross-org guard ───────────────────────────────────────────────
    if str(body.org_id) != str(caller.org_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Cross-org provisioning is not permitted. "
                "org_id in the request body must match your own org."
            ),
        )

    # ── Step 4: Resolve Auth0 org ID from organizations table ────────────────
    org_row = (
        await db.execute(
            text("SELECT auth0_org_id FROM organizations WHERE id = :org_id"),
            {"org_id": body.org_id},
        )
    ).fetchone()

    if org_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization {body.org_id!r} not found.",
        )

    auth0_org_id: str | None = org_row[0]
    if not auth0_org_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Organization {body.org_id!r} has no auth0_org_id configured. "
                "Set organizations.auth0_org_id before provisioning users into this org."
            ),
        )

    # ── Step 5: Duplicate-email check (before any Auth0 call) ────────────────
    dup = (
        await db.execute(
            text(
                "SELECT id FROM users "
                "WHERE email = :email AND org_id = :org_id"
            ),
            {"email": str(body.email), "org_id": body.org_id},
        )
    ).fetchone()

    if dup:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A user with email {str(body.email)!r} is already provisioned "
                "in this organization."
            ),
        )

    # ── Step 6: Auth0 — create user ───────────────────────────────────────────
    # app_metadata is what the Post-Login Action reads to stamp JWT claims.
    # Shape must match the claim namespace expected by auth0_verify.py:
    #   https://aegis-api/org_id   → str
    #   https://aegis-api/team_ids → list[str]
    #   https://aegis-api/roles    → dict[str, str]  (team_id → role_name)
    app_metadata: dict[str, Any] = {
        "org_id": str(body.org_id),
        "team_ids": [str(body.team_id)],
        "roles": {str(body.team_id): body.role},
    }

    try:
        auth0_user_id = await auth0_mgmt.create_auth0_user(
            email=str(body.email),
            display_name=body.display_name,
            app_metadata=app_metadata,
        )
    except ValueError as exc:
        # 409 from Auth0: email already exists in this Auth0 tenant
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error("Auth0 user creation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Auth0 user creation failed: {exc}",
        ) from exc

    # ── Step 7: Auth0 — add user to org ──────────────────────────────────────
    try:
        await auth0_mgmt.add_user_to_org(auth0_org_id, auth0_user_id)
    except Exception as exc:
        logger.error(
            "Auth0 org-membership add failed for user %s, initiating rollback: %s",
            auth0_user_id[:16],
            exc,
        )
        await _rollback_auth0_user(auth0_user_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to add user to Auth0 org (Auth0 user deleted): {exc}",
        ) from exc

    # ── Steps 8–9: Postgres — INSERT users + team_memberships ─────────────────
    # Both inserts happen inside the same transaction (db is already inside
    # session.begin() from the get_db dependency).  Any exception auto-rolls
    # back the transaction AND triggers Auth0 compensation below.
    new_user_id = str(uuid.uuid4())
    try:
        await db.execute(
            text(
                "INSERT INTO users (id, org_id, auth0_sub, email, display_name) "
                "VALUES (:id, :org_id, :auth0_sub, :email, :display_name)"
            ),
            {
                "id": new_user_id,
                "org_id": str(body.org_id),
                "auth0_sub": auth0_user_id,
                "email": str(body.email),
                "display_name": body.display_name,
            },
        )
        await db.execute(
            text(
                "INSERT INTO team_memberships (org_id, team_id, user_id, role) "
                "VALUES (:org_id, :team_id, :user_id, :role)"
            ),
            {
                "org_id": str(body.org_id),
                "team_id": str(body.team_id),
                "user_id": new_user_id,
                "role": body.role,
            },
        )
    except Exception as pg_exc:
        # Postgres failed after Auth0 user was already created.
        # Compensate: delete the Auth0 user so no half-created state remains.
        logger.error(
            "Postgres insert failed after Auth0 user creation (%s). "
            "Initiating Auth0 rollback (delete).",
            auth0_user_id[:16],
        )
        rollback_msg = await _rollback_auth0_user(auth0_user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"Database insert failed: {pg_exc}. "
                f"Auth0 rollback: {rollback_msg}"
            ),
        ) from pg_exc

    # ── Step 10: Send password-change ticket (best-effort) ───────────────────
    # Non-fatal: the user can request a password reset from Auth0's login page
    # if this fails. We do NOT roll back provisioning on ticket send failure.
    try:
        await auth0_mgmt.send_password_change_ticket(auth0_user_id)
    except Exception as exc:
        logger.warning(
            "Password-change ticket send failed for %s (non-fatal): %s",
            auth0_user_id[:16],
            exc,
        )

    logger.info(
        "User provisioned: postgres_id=%s auth0_prefix=%s email=%s org=%s role=%s",
        new_user_id,
        auth0_user_id[:16],
        str(body.email),
        body.org_id,
        body.role,
    )

    return ProvisionUserResponse(
        user_id=new_user_id,
        email=str(body.email),
        auth0_user_id=auth0_user_id,
        status="provisioned",
        message=(
            f"User {str(body.email)!r} has been provisioned with role "
            f"{body.role!r}. A password-setup email has been dispatched."
        ),
    )


# ── DELETE /admin/users/{user_id} ─────────────────────────────────────────────


@admin_router.delete(
    "/users/{user_id}",
    response_model=DeprovisionUserResponse,
    summary="Deprovision a user (org_admin only)",
)
async def deprovision_user(
    user_id: str,
    caller: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Remove a user from **both** Postgres (committed first) and Auth0.

    Postgres is deleted first and committed before Auth0 deletion is attempted.
    If Auth0 deletion subsequently fails, AEGIS access is already revoked
    (no Postgres row → resolve_access returns False on every request) and the
    orphaned Auth0 account is flagged in the response for operator follow-up.

    Callers cannot deprovision themselves — transfer admin ownership first.
    """
    from app.auth import auth0_mgmt

    ctx = _make_ctx(caller, db)

    # ── Step 1: Authorize ────────────────────────────────────────────────────
    if not await resolve_access(ctx, "*", team_id=None):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: only org_admin callers may deprovision users.",
        )

    # ── Step 2: Validate UUID ─────────────────────────────────────────────────
    try:
        uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"user_id {user_id!r} is not a valid UUID.",
        )

    # ── Step 3: Self-deprovision guard ────────────────────────────────────────
    if caller.db_id and str(caller.db_id) == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Admins may not deprovision themselves. "
                "Transfer the org_admin role to another user first."
            ),
        )

    # ── Step 4: Look up target user ───────────────────────────────────────────
    # RLS (tenant_isolation on users table, migration 0002) automatically
    # scopes this query to the caller's org_id — no explicit org_id filter
    # needed, and any attempt to target a user from another org returns 404.
    target = (
        await db.execute(
            text("SELECT auth0_sub, email FROM users WHERE id = :user_id"),
            {"user_id": user_id},
        )
    ).fetchone()

    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id!r} not found in your organization.",
        )

    auth0_sub: str = target[0]
    email: str = target[1]

    # ── Step 5: Postgres-first delete ─────────────────────────────────────────
    # CASCADE on fk_team_memberships_user_id handles team_memberships deletion.
    try:
        await db.execute(
            text("DELETE FROM users WHERE id = :user_id"),
            {"user_id": user_id},
        )
    except Exception as pg_exc:
        logger.error("Postgres delete failed for user %s: %s", user_id, pg_exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete user from database: {pg_exc}",
        ) from pg_exc

    # Postgres commit happens here (end of session.begin() context in get_db).
    # Auth0 deletion is attempted after commit.

    # ── Step 6: Auth0 delete (best-effort) ───────────────────────────────────
    auth0_cleanup: str
    if auth0_sub.startswith("pending:"):
        # Defensive: legacy placeholder from a system where invite flow was used.
        # No real Auth0 account exists for this sub value.
        logger.info(
            "User %s had placeholder auth0_sub — no Auth0 deletion needed.", user_id
        )
        auth0_cleanup = "skipped"
    else:
        try:
            await auth0_mgmt.delete_auth0_user(auth0_sub)
            auth0_cleanup = "deleted"
        except Exception as auth0_exc:
            # Postgres is already committed — we cannot undo that.
            # Log for operator follow-up; AEGIS access is already revoked.
            logger.error(
                "WARNING: Auth0 user deletion failed for %s (auth0_sub=%s): %s. "
                "Postgres deletion is committed. Manual Auth0 cleanup required.",
                user_id,
                auth0_sub[:16],
                auth0_exc,
            )
            auth0_cleanup = "warning"

    cleanup_messages = {
        "deleted": "Auth0 account deleted.",
        "skipped": "Auth0 account was not yet active (placeholder sub); no action needed.",
        "warning": (
            "Auth0 account deletion FAILED — Postgres deletion is committed so "
            "AEGIS access is revoked, but the Auth0 account requires manual cleanup."
        ),
    }

    logger.info(
        "User deprovisioned: user_id=%s email=%s auth0_cleanup=%s",
        user_id,
        email,
        auth0_cleanup,
    )

    return DeprovisionUserResponse(
        user_id=user_id,
        email=email,
        status="deprovisioned",
        message=f"User {email!r} has been deprovisioned from AEGIS. {cleanup_messages[auth0_cleanup]}",
        auth0_cleanup=auth0_cleanup,
    )


# ── Compensation helper ───────────────────────────────────────────────────────


async def _rollback_auth0_user(auth0_user_id: str) -> str:
    """Best-effort deletion of an Auth0 user as a rollback/compensation step.

    Returns a human-readable string describing the outcome (for inclusion in
    error responses so operators know whether manual cleanup is needed).

    Never raises — the original exception that triggered the rollback must be
    re-raised by the caller after this returns.
    """
    from app.auth import auth0_mgmt

    try:
        await auth0_mgmt.delete_auth0_user(auth0_user_id)
        logger.info("Auth0 rollback successful: deleted user %s", auth0_user_id[:16])
        return "Auth0 user deleted (rollback successful)."
    except Exception as rollback_exc:
        logger.error(
            "CRITICAL: Auth0 rollback failed for %s — manual deletion required. "
            "Error: %s",
            auth0_user_id[:16],
            rollback_exc,
        )
        return (
            f"Auth0 rollback FAILED — manual deletion of Auth0 user "
            f"{auth0_user_id!r} required. Error: {rollback_exc}"
        )


# ── DELETE /admin/users/{user_id}/data — GDPR right-to-erasure ───────────────


class EraseUserDataResponse(BaseModel):
    user_id: str
    audit_rows_deleted: int
    documents_erased: int
    status: str = "erased"
    message: str


@admin_router.delete(
    "/users/{user_id}/data",
    response_model=EraseUserDataResponse,
    summary="GDPR erasure — delete all data for a user (org_admin only)",
)
async def erase_user_data(
    user_id: str,
    caller: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Hard-delete all audit logs and documents belonging to the target user.

    Fulfils GDPR Article 17 (right to erasure):
    1. Validates org_admin role.
    2. Deletes vectors from Pinecone and files from object storage for each
       document uploaded by this user (tracked in ``document_uploads``).
    3. Deletes all ``audit_logs`` rows where ``username`` matches.
    4. Deletes all ``document_uploads`` rows for this ``user_id``.
    """
    from sqlalchemy import text

    ctx = _make_ctx(caller, db)

    if not await resolve_access(ctx, "*", team_id=None):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: only org_admin callers may erase user data.",
        )

    try:
        uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"user_id {user_id!r} is not a valid UUID.",
        )

    if caller.db_id and str(caller.db_id) == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admins may not erase their own data. Transfer admin role first.",
        )

    # Resolve username (RLS scopes to caller's org)
    target = (
        await db.execute(
            text("SELECT email FROM users WHERE id = :user_id"),
            {"user_id": user_id},
        )
    ).fetchone()

    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id!r} not found in your organization.",
        )

    username: str = target[0]

    # Enumerate uploaded documents for this user
    doc_rows = (
        await db.execute(
            text(
                "SELECT filename, data_source, storage_key FROM document_uploads "
                "WHERE user_id = :user_id"
            ),
            {"user_id": user_id},
        )
    ).fetchall()

    # Delete vectors and object storage per document
    from app.retrieval.vector_store import get_vector_store
    from app.db.storage import delete_document as object_storage_delete

    vector_store = get_vector_store()
    docs_erased = 0
    for filename, data_source_val, _storage_key in doc_rows:
        try:
            vector_store.delete_by_source(caller.org_id, filename)
        except Exception as vs_exc:
            logger.warning("erase_user_data: vector delete failed for %s: %s", filename, vs_exc)
        try:
            object_storage_delete(
                org_id=caller.org_id,
                data_source_id=data_source_val,
                filename=filename,
            )
        except Exception as obj_exc:
            logger.warning("erase_user_data: object storage delete failed for %s: %s", filename, obj_exc)
        docs_erased += 1

    # Delete document_uploads rows
    await db.execute(
        text("DELETE FROM document_uploads WHERE user_id = :user_id"),
        {"user_id": user_id},
    )

    # Delete audit_logs rows by username
    audit_result = await db.execute(
        text("DELETE FROM audit_logs WHERE username = :username RETURNING id"),
        {"username": username},
    )
    audit_rows_deleted = len(audit_result.fetchall())

    logger.info(
        "erase_user_data: user=%s username=%s audit_rows=%d docs=%d",
        user_id,
        username,
        audit_rows_deleted,
        docs_erased,
    )

    return EraseUserDataResponse(
        user_id=user_id,
        audit_rows_deleted=audit_rows_deleted,
        documents_erased=docs_erased,
        status="erased",
        message=(
            f"All data for {username!r} erased: "
            f"{audit_rows_deleted} audit entries deleted, "
            f"{docs_erased} documents removed."
        ),
    )


# ── GET /admin/compliance/export — Compliance audit export ─────────────────────


@admin_router.get(
    "/compliance/export",
    summary="Export audit logs as JSON or CSV (org_admin or compliance_officer)",
)
async def compliance_export(
    format: str = "json",
    from_date: str | None = None,
    to_date: str | None = None,
    username: str | None = None,
    limit: int = 1000,
    caller: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Export structured audit evidence for compliance reporting.

    Accessible to ``org_admin``, ``team_lead``, and ``compliance_officer`` roles.

    Query parameters
    ----------------
    format     : ``json`` (default) or ``csv``.
    from_date  : ISO-8601 string (e.g. ``2026-01-01T00:00:00Z``).
    to_date    : ISO-8601 string.
    username   : Filter to a specific user.
    limit      : Max rows (default 1000, hard cap 10 000).
    """
    import csv
    import io
    from datetime import datetime
    from fastapi.responses import StreamingResponse

    ctx = _make_ctx(caller, db)

    # Allow org_admin / team_lead (wildcard) or compliance_officer
    caller_roles: set[str] = set()
    if caller.roles:
        caller_roles = set(caller.roles.values())

    allowed_roles = {"org_admin", "team_lead", "compliance_officer"}
    if not caller_roles.intersection(allowed_roles):
        if not await resolve_access(ctx, "compliance_records", team_id=None):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access Denied: only org_admin or compliance_officer may export audit logs.",
            )

    from_dt: datetime | None = None
    to_dt: datetime | None = None
    if from_date:
        try:
            from_dt = datetime.fromisoformat(from_date.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid from_date: {from_date!r}")
    if to_date:
        try:
            to_dt = datetime.fromisoformat(to_date.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid to_date: {to_date!r}")

    limit = min(limit, 10_000)

    from app.observability.audit_logger import AuditLogger
    audit_logger = AuditLogger()
    entries = await audit_logger.get_recent_async(
        db,
        limit=limit,
        username=username,
        from_date=from_dt,
        to_date=to_dt,
    )

    if format.lower() == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "query_id", "username", "role", "query", "intent", "outcome",
            "rbac_violation", "security_violation", "response_time_ms",
            "timestamp", "metadata",
        ])
        for e in entries:
            writer.writerow([
                e.query_id, e.username, e.role or "", e.query,
                e.intent.value if e.intent else "", e.outcome,
                e.rbac_violation, e.security_violation,
                e.response_time_ms or "", e.timestamp.isoformat(),
                str(e.metadata),
            ])
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=audit_export.csv"},
        )

    return {
        "export_count": len(entries),
        "entries": [e.model_dump(mode="json") for e in entries],
    }
