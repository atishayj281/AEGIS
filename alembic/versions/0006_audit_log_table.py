"""create_audit_logs_table

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-06

Creates the `audit_logs` table that supersedes the flat-file audit log
introduced in the original AuditLogger.  Every query processed by the
RAG pipeline (success, access-denied, security-blocked, or error) is
INSERTed here, providing a centralised, queryable, and tamper-evident
record for SOC-2 / ISO-27001 / GDPR audit trails.

Design notes
------------
- `org_id` is denormalized (same pattern as all child tables) so that the
  RLS tenant-isolation policy can filter on it without a JOIN.
- `metadata` is JSONB so that caller-supplied extra context (source lists,
  confidence scores, denial reasons) can be stored without schema changes.
- RLS policy mirrors `0002_tenancy_schema.py`:
    - Force-enabled so even the app role cannot bypass it.
    - Policy condition: `org_id = current_setting('app.current_org_id')`.
    - A *permissive* SELECT/INSERT policy — the app role never DELETEs
      individual rows; bulk purges for retention are performed by the
      Celery sweep task which temporarily sets the org context.
- Index on `(org_id, timestamp)` supports the common "recent events for
  my org sorted by time" query.
- Index on `(org_id, username)` supports GDPR erasure lookup.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("query_id", sa.Text(), nullable=True),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("intent", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("rbac_violation", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("security_violation", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("response_time_ms", sa.Float(), nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # Composite indexes for common query patterns
    op.create_index("ix_audit_logs_org_timestamp", "audit_logs", ["org_id", sa.text("timestamp DESC")])
    op.create_index("ix_audit_logs_org_username", "audit_logs", ["org_id", "username"])

    # Enable row-level security — FORCE ensures even the app role cannot
    # bypass it accidentally.
    op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE POLICY tenant_isolation ON audit_logs
            USING (org_id::text = current_setting('app.current_org_id', TRUE))
            WITH CHECK (org_id::text = current_setting('app.current_org_id', TRUE))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON audit_logs")
    op.drop_index("ix_audit_logs_org_username", table_name="audit_logs")
    op.drop_index("ix_audit_logs_org_timestamp", table_name="audit_logs")
    op.drop_table("audit_logs")
