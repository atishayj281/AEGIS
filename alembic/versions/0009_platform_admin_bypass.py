"""create_platform_admin_bypass_role_and_table

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-06

Phase 7: Platform Superuser — Postgres BYPASSRLS Role

Creates:
  1. `aegis_platform_admin` Postgres role with LOGIN + BYPASSRLS.
     NOT SUPERUSER — BYPASSRLS is the narrowest grant that lets an operator
     read across every org without requiring changes to any of the
     tenant_isolation policies set in 0002.

  2. `platform_admins` table — the application-level registry of which
     Auth0 subjects have been granted platform-admin access.  No RLS on this
     table: all access paths to it go through the bypass connection anyway,
     so adding RLS would be circular (the bypass role ignores it) and would
     add no isolation value.

Password note
-------------
The role is created WITHOUT a password in this migration.  Set the password
once, manually, out of version control:
    ALTER ROLE aegis_platform_admin WITH PASSWORD '<strong-secret>';
The PLATFORM_ADMIN_DATABASE_URL env var carries those credentials at runtime.

Down-migration
--------------
Revokes grants, drops the role (idempotent), and drops the table — safe to
run repeatedly since each step uses IF EXISTS.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1. Create the bypass role idempotently.                              #
    # ------------------------------------------------------------------ #
    # DO $$ ... END $$ lets us check pg_roles before CREATE, so running
    # the migration twice is safe (no "role already exists" error).
    # BYPASSRLS: skips all row-level security policies.
    # LOGIN: required so the app can connect with this role's credentials.
    # NOT SUPERUSER / NOT CREATEDB / NOT CREATEROLE: principle of least
    #   privilege — BYPASSRLS is the only extra privilege needed.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = 'aegis_platform_admin'
            ) THEN
                CREATE ROLE aegis_platform_admin
                    WITH LOGIN
                         BYPASSRLS
                         NOSUPERUSER
                         NOCREATEDB
                         NOCREATEROLE;
            END IF;
        END
        $$;
        """
    )

    # Grant full access to every existing table in the public schema.
    op.execute(
        "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO aegis_platform_admin;"
    )
    op.execute(
        "GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO aegis_platform_admin;"
    )

    # Grant access to tables/sequences created by future migrations automatically.
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT ALL ON TABLES TO aegis_platform_admin;
        """
    )
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT ALL ON SEQUENCES TO aegis_platform_admin;
        """
    )

    # ------------------------------------------------------------------ #
    # 2. Create the platform_admins registry table.                        #
    # ------------------------------------------------------------------ #
    # Deliberately NO RLS on this table — see module docstring for why.
    # auth0_sub: the Auth0 user's `sub` claim (format: "auth0|<user_id>").
    # is_active: soft-disable without deleting the audit trail row.
    op.create_table(
        "platform_admins",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("auth0_sub", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("auth0_sub", name="uq_platform_admins_auth0_sub"),
    )

    op.create_index(
        "ix_platform_admins_auth0_sub",
        "platform_admins",
        ["auth0_sub"],
        unique=True,
    )


def downgrade() -> None:
    # Drop the registry table first (no FKs point to it so order is safe).
    op.drop_index("ix_platform_admins_auth0_sub", table_name="platform_admins")
    op.drop_table("platform_admins")

    # Revoke grants before dropping the role — Postgres will error if a role
    # still holds privileges when it is dropped.
    op.execute(
        "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM aegis_platform_admin;"
    )
    op.execute(
        "REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM aegis_platform_admin;"
    )
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            REVOKE ALL ON TABLES FROM aegis_platform_admin;
        """
    )
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            REVOKE ALL ON SEQUENCES FROM aegis_platform_admin;
        """
    )
    op.execute("DROP ROLE IF EXISTS aegis_platform_admin;")
