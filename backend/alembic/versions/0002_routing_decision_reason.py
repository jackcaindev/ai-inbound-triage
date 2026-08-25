"""add reason to routing_decisions

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-25

routing_decisions previously only recorded the destination and matched rule, not
why the decision was made. The rules/confidence engine now writes a row for every
processed record, including ones sent to review, so `reason` records the actual
trigger (low_classification_confidence / missing_required_field:<field> / rule /
auto) instead of leaving reviewers to reverse-engineer it from audit_log.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("routing_decisions", sa.Column("reason", sa.String(length=64), nullable=True))
    op.execute("UPDATE routing_decisions SET reason = 'unspecified' WHERE reason IS NULL")
    op.alter_column("routing_decisions", "reason", nullable=False)


def downgrade() -> None:
    op.drop_column("routing_decisions", "reason")
