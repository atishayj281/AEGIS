"""create_resource_grants

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-28 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resource_grants",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("data_source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name="fk_resource_grants_org_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_resource_grants_user_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], name="fk_resource_grants_data_source_id", ondelete="CASCADE"),
    )
    op.create_index("ix_resource_grants_org_id", "resource_grants", ["org_id"])
    op.create_index("ix_resource_grants_user_id", "resource_grants", ["user_id"])
    
    # Enable RLS and add tenant isolation policy
    op.execute("ALTER TABLE resource_grants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE resource_grants FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON resource_grants
        USING (org_id = current_setting('app.current_org_id', true)::uuid)
        WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON resource_grants")
    op.execute("ALTER TABLE resource_grants NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE resource_grants DISABLE ROW LEVEL SECURITY")
    
    op.drop_index("ix_resource_grants_user_id", table_name="resource_grants")
    op.drop_index("ix_resource_grants_org_id", table_name="resource_grants")
    op.drop_table("resource_grants")
