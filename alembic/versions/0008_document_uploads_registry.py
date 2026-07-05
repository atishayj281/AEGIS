"""create_document_uploads_registry

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-06

Creates a `document_uploads` table that records every file uploaded by a
user with its object-storage key.

Rationale
---------
GDPR Article 17 (right to erasure) requires that we can delete all data
associated with a specific data subject.  Pinecone namespaces are per-org,
not per-user, so we cannot target a user's vectors purely from Pinecone
metadata unless we track which filenames they uploaded.

This table provides that mapping:
    org_id + user_id + filename → storage_key

The GDPR erasure endpoint (DELETE /admin/users/{user_id}/data) reads this
table to enumerate the user's documents, then:
  1. Calls `vector_store.delete_by_source(org_id, filename)` for each row.
  2. Calls `object_storage_delete(org_id, ...)` for each row.
  3. Deletes the rows from this table.
  4. Deletes `audit_logs` rows for that username.

RLS: same pattern as all other child tables — org_id filter via
current_setting('app.current_org_id').
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_uploads",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("data_source", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_document_uploads_user_id"),
    )

    op.create_index("ix_document_uploads_org_user", "document_uploads", ["org_id", "user_id"])
    op.create_index("ix_document_uploads_org_filename", "document_uploads", ["org_id", "filename"])

    op.execute("ALTER TABLE document_uploads ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE document_uploads FORCE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE POLICY tenant_isolation ON document_uploads
            USING (org_id::text = current_setting('app.current_org_id', TRUE))
            WITH CHECK (org_id::text = current_setting('app.current_org_id', TRUE))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON document_uploads")
    op.drop_index("ix_document_uploads_org_filename", table_name="document_uploads")
    op.drop_index("ix_document_uploads_org_user", table_name="document_uploads")
    op.drop_table("document_uploads")
