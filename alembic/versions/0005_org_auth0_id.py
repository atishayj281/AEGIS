"""add_auth0_org_id_to_organizations

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-04

Adds `auth0_org_id TEXT UNIQUE NULL` to the `organizations` table.

Rationale
---------
The admin user-provisioning endpoint (POST /admin/users) needs to call the
Auth0 Management API's organization-members endpoint, which requires the
Auth0 Organization ID (e.g. "org_abc123") — a value that Auth0 owns and that
is distinct from the Postgres UUID primary key on this table.

Storing it here (rather than passing it in the request body) keeps Auth0
internal identifiers off the public API surface and lets the backend resolve
the Auth0 org ID from the caller's already-verified Postgres org_id without
leaking implementation details.

Column is:
  - NULLABLE: existing org rows predate Auth0 org linkage; they get populated
    when an org admin links the Auth0 org via the dashboard or a future
    "link org" endpoint. The provisioning endpoint returns a 409 if
    auth0_org_id is NULL so the failure is surfaced clearly at call time.
  - UNIQUE: enforces that each Auth0 org maps to at most one AEGIS org,
    preventing a misconfiguration where two AEGIS orgs both claim the same
    Auth0 org identity.

Down-migration is safe — dropping the column does not affect any FK
relationships and cannot corrupt tenant-isolation logic (the RLS policies in
migration 0002 filter on `organizations.id`, not on `auth0_org_id`).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "auth0_org_id",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.create_unique_constraint(
        "uq_organizations_auth0_org_id",
        "organizations",
        ["auth0_org_id"],
    )
    op.create_index(
        "ix_organizations_auth0_org_id",
        "organizations",
        ["auth0_org_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_organizations_auth0_org_id", table_name="organizations")
    op.drop_constraint("uq_organizations_auth0_org_id", "organizations", type_="unique")
    op.drop_column("organizations", "auth0_org_id")
