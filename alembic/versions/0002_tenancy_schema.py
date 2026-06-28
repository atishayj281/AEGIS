"""enable_rls

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-27 23:41:55.949485

Enables Row-Level Security on every tenancy table and adds a single
`tenant_isolation` policy per table, scoped to the session-local setting
`app.current_org_id`.

Two things make this fail closed rather than fail open or fail loud:

1. FORCE ROW LEVEL SECURITY (not just ENABLE). By default Postgres exempts
   the table owner from RLS entirely. Since this project's app connection
   and Alembic migrations currently use the same Postgres role (no
   separate restricted app role yet), ENABLE alone would mean RLS looks
   correctly configured but is silently skipped for every real request the
   app makes. FORCE closes that gap by applying the policy to the owner
   role too. (Superusers and roles with BYPASSRLS remain exempt regardless
   of FORCE — if a separate, more restricted app role is introduced later,
   that's the role this protection matters most for; FORCE is what makes
   today's single-role setup safe in the meantime.)

2. current_setting('app.current_org_id', true) — the `true` second
   argument means "missing_ok": if app.current_org_id was never set on
   this session/transaction (e.g. a request that bypassed the tenant
   scoping middleware), this returns NULL instead of raising an error.
   `org_id = NULL` evaluates to NULL (not TRUE) for every row under
   Postgres's three-valued logic, so the row is excluded. Net effect: a
   request that skips scoping sees zero rows, not a 500 and not someone
   else's data.

organizations is a special case: it has no org_id column (its own id IS
the tenant identity), so its policy filters on id = current_org_id
instead. Without this, any session could read every tenant's
organization name/slug regardless of app.current_org_id.

This migration does not set app.current_org_id anywhere. That's the job
of the tenant_scoped_session context manager added in task 2.5
(SET LOCAL app.current_org_id = :org_id per transaction). Until 2.5 lands,
any direct psql session or script touching these tables will see zero
rows for org-scoped tables unless app.current_org_id is set manually:
  SET app.current_org_id = '<uuid>';
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


# (table_name, filter_column) — filter_column is "id" only for organizations
# (it has no org_id column; its own id IS the tenant identity), "org_id"
# for every other tenancy table.
RLS_TABLES = [
    ("organizations", "id"),
    ("teams", "org_id"),
    ("users", "org_id"),
    ("team_memberships", "org_id"),
    ("data_sources", "org_id"),
    ("documents", "org_id"),
    ("conversations", "org_id"),
    ("conversation_turns", "org_id"),
    ("audit_events", "org_id"),
]

CURRENT_ORG_ID_EXPR = "current_setting('app.current_org_id', true)::uuid"


def upgrade() -> None:
    for table_name, filter_column in RLS_TABLES:
        op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table_name}
            USING ({filter_column} = {CURRENT_ORG_ID_EXPR})
            WITH CHECK ({filter_column} = {CURRENT_ORG_ID_EXPR})
            """
        )


def downgrade() -> None:
    # Reverse order isn't FK-driven here (no table is being dropped), but
    # mirroring 0001's reverse order keeps the migration sequence consistent
    # to read.
    for table_name, _ in reversed(RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table_name}")
        op.execute(f"ALTER TABLE {table_name} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")