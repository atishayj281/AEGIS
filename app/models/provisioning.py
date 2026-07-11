"""Shared Pydantic models for user/team provisioning.

Kept here (not in platform_admin.py or org_admin.py) so that both route
modules can import them without creating a circular dependency between the
two route files.

Only provisioning-related schemas live here.  General API schemas that
pre-date the provisioning surface (QueryRequest, AuditLogEntry, …) remain
in app/models/schemas.py.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Role constants — single source of truth for both route modules.
# Must stay in sync with ROLE_PERMISSIONS_V2 in app/auth/rbac.py.
# ---------------------------------------------------------------------------

VALID_ROLES: frozenset[str] = frozenset({
    "org_admin",
    "team_lead",
    "compliance_officer",
    "finance_analyst",
    "operations_engineer",
    "employee",
    "guest",
})

# ---------------------------------------------------------------------------
# Shared response models
# ---------------------------------------------------------------------------


class UserRecord(BaseModel):
    """User row representation returned by provisioning endpoints."""

    id: uuid.UUID
    org_id: uuid.UUID
    auth0_sub: str
    email: str
    display_name: str | None
    is_active: bool
    role: str | None
    created_at: str | None


class TeamRecord(BaseModel):
    """Team row representation."""

    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    created_at: str | None
