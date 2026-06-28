"""tenancy_schema

Revision ID: 0001
Revises:
Create Date: 2026-06-26

Creates the nine core tenancy/RAG tables for AEGIS Phase 2 multi-tenancy:
organizations, teams, users, team_memberships, data_sources, documents,
conversations, conversation_turns, audit_events.

All tenant-scoped tables carry an org_id column (denormalized onto child
tables where needed) so that the RLS policies added in migration 0002 can
filter on org_id directly without requiring a join. This is deliberate:
RLS policies that need a join to enforce isolation are both slower and a
common source of policy bugs.

UUIDs are server-generated via gen_random_uuid() (pgcrypto-free as of
Postgres 13+, built into core). No application code should generate these
client-side, to avoid collision/ordering issues across services.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


DOCUMENT_STATUS_ENUM = postgresql.ENUM(
    "pending",
    "queued",
    "chunking",
    "embedding",
    "indexed",
    "failed",
    name="document_status",
)

# Used on the documents.status column with create_type=False because the
# type itself is created explicitly via DOCUMENT_STATUS_ENUM.create() in
# upgrade(); without this, SQLAlchemy emits a second CREATE TYPE the moment
# it sees the enum used as a column type, which fails on a real Postgres
# run with "type already exists".
DOCUMENT_STATUS_COLUMN_TYPE = postgresql.ENUM(
    "pending",
    "queued",
    "chunking",
    "embedding",
    "indexed",
    "failed",
    name="document_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    DOCUMENT_STATUS_ENUM.create(bind, checkfirst=True)

    # --- organizations ---------------------------------------------------
    op.create_table(
        "organizations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
    )

    # --- teams -------------------------------------------------------------
    op.create_table(
        "teams",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name="fk_teams_org_id", ondelete="CASCADE"),
        sa.UniqueConstraint("org_id", "name", name="uq_teams_org_id_name"),
    )
    op.create_index("ix_teams_org_id", "teams", ["org_id"])

    # --- users ---------------------------------------------------------
    # Durable profile row keyed to Auth0's `sub` claim. Auth0 owns
    # credentials; this table is a lookup/profile cache, not an identity
    # store. org_id here is the user's *home* org (their primary tenant);
    # cross-org access for a single human is out of scope unless a future
    # table is added for that.
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("auth0_sub", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name="fk_users_org_id", ondelete="CASCADE"),
        sa.UniqueConstraint("auth0_sub", name="uq_users_auth0_sub"),
    )
    op.create_index("ix_users_org_id", "users", ["org_id"])

    # --- team_memberships ----------------------------------------------
    # org_id is denormalized here (also derivable via team_id -> teams.org_id)
    # specifically so RLS in 0002 can filter this table on org_id without a
    # join.
    op.create_table(
        "team_memberships",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False, server_default="member"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name="fk_team_memberships_org_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], name="fk_team_memberships_team_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_team_memberships_user_id", ondelete="CASCADE"),
        sa.UniqueConstraint("team_id", "user_id", name="uq_team_memberships_team_id_user_id"),
    )
    op.create_index("ix_team_memberships_org_id", "team_memberships", ["org_id"])
    op.create_index("ix_team_memberships_user_id", "team_memberships", ["user_id"])

    # --- data_sources ----------------------------------------------------
    op.create_table(
        "data_sources",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name="fk_data_sources_org_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], name="fk_data_sources_team_id", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_data_sources_created_by", ondelete="SET NULL"),
    )
    op.create_index("ix_data_sources_org_id", "data_sources", ["org_id"])

    # --- documents -------------------------------------------------------
    op.create_table(
        "documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("data_source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("status", DOCUMENT_STATUS_COLUMN_TYPE, nullable=False, server_default="pending"),
        sa.Column("qdrant_point_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name="fk_documents_org_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], name="fk_documents_data_source_id", ondelete="CASCADE"),
    )
    op.create_index("ix_documents_org_id", "documents", ["org_id"])
    op.create_index("ix_documents_data_source_id", "documents", ["data_source_id"])

    # --- conversations -----------------------------------------------------
    op.create_table(
        "conversations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name="fk_conversations_org_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], name="fk_conversations_team_id", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_conversations_user_id", ondelete="CASCADE"),
    )
    op.create_index("ix_conversations_org_id", "conversations", ["org_id"])
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])

    # --- conversation_turns -----------------------------------------------
    # org_id denormalized here too (derivable via conversation_id), again so
    # RLS can filter without a join on the highest-volume table in the schema.
    op.create_table(
        "conversation_turns",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("retrieved_chunks", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name="fk_conversation_turns_org_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], name="fk_conversation_turns_conversation_id", ondelete="CASCADE"),
        sa.CheckConstraint("role IN ('user', 'assistant', 'system')", name="ck_conversation_turns_role"),
    )
    op.create_index("ix_conversation_turns_org_id", "conversation_turns", ["org_id"])
    op.create_index("ix_conversation_turns_conversation_id", "conversation_turns", ["conversation_id"])

    # --- audit_events -----------------------------------------------------
    op.create_table(
        "audit_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name="fk_audit_events_org_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name="fk_audit_events_actor_user_id", ondelete="SET NULL"),
    )
    op.create_index("ix_audit_events_org_id", "audit_events", ["org_id"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])


def downgrade() -> None:
    # Reverse FK order: drop dependents before the tables they reference.
    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_index("ix_audit_events_org_id", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index("ix_conversation_turns_conversation_id", table_name="conversation_turns")
    op.drop_index("ix_conversation_turns_org_id", table_name="conversation_turns")
    op.drop_table("conversation_turns")

    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_index("ix_conversations_org_id", table_name="conversations")
    op.drop_table("conversations")

    op.drop_index("ix_documents_data_source_id", table_name="documents")
    op.drop_index("ix_documents_org_id", table_name="documents")
    op.drop_table("documents")

    op.drop_index("ix_data_sources_org_id", table_name="data_sources")
    op.drop_table("data_sources")

    op.drop_index("ix_team_memberships_user_id", table_name="team_memberships")
    op.drop_index("ix_team_memberships_org_id", table_name="team_memberships")
    op.drop_table("team_memberships")

    op.drop_index("ix_users_org_id", table_name="users")
    op.drop_table("users")

    op.drop_index("ix_teams_org_id", table_name="teams")
    op.drop_table("teams")

    op.drop_table("organizations")

    bind = op.get_bind()
    DOCUMENT_STATUS_ENUM.drop(bind, checkfirst=True)