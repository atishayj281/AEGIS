"""add_retention_policy_to_organizations

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-06

Adds `retention_days INTEGER DEFAULT 365` to the `organizations` table.

Rationale
---------
GDPR Article 5(1)(e) and SOC-2 CC6.5 require that personal data not be
kept longer than necessary.  Storing a per-org retention window in Postgres
lets the Celery retention sweep task read the policy for each org and issue
a targeted DELETE on audit_logs rows older than the threshold.

Default of 365 days is deliberately conservative (covers most regulatory
minima).  Operators can override per org via:
    UPDATE organizations SET retention_days = 90 WHERE id = '...';

NULL means "no automatic purge" (opt-out), which is safe for orgs that
have contractual reasons to keep logs indefinitely.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "retention_days",
            sa.Integer(),
            nullable=True,
            server_default="365",
            comment="Days to retain audit logs; NULL disables automatic purge.",
        ),
    )


def downgrade() -> None:
    op.drop_column("organizations", "retention_days")
