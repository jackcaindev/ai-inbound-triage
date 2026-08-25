"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-24

Creates all Phase 1 tables in FK-dependency order:
sources -> records -> rules -> classifications -> extractions -> routing_decisions
-> audit_log -> eval_examples.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_sources"),
    )

    op.create_table(
        "records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("external_ref", sa.String(length=255), nullable=False),
        sa.Column("raw_content", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name="fk_records_source_id_sources", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_records"),
        sa.UniqueConstraint("source_id", "external_ref", name="uq_records_source_id_external_ref"),
    )
    op.create_index("ix_records_status", "records", ["status"])

    op.create_table(
        "rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("destination", sa.String(length=128), nullable=False),
        sa.Column("requires_review", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_rules"),
    )
    op.create_index("ix_rules_active_priority", "rules", ["active", "priority"])

    op.create_table(
        "classifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("raw_response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["record_id"], ["records.id"], name="fk_classifications_record_id_records", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_classifications"),
    )
    op.create_index("ix_classifications_record_id", "classifications", ["record_id"])

    op.create_table(
        "extractions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("raw_response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["record_id"], ["records.id"], name="fk_extractions_record_id_records", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_extractions"),
    )
    op.create_index("ix_extractions_record_id", "extractions", ["record_id"])

    op.create_table(
        "routing_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=True),
        sa.Column("destination", sa.String(length=128), nullable=False),
        sa.Column("decided_by", sa.String(length=16), nullable=False),
        sa.Column("reviewer_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["record_id"], ["records.id"], name="fk_routing_decisions_record_id_records", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"], ["rules.id"], name="fk_routing_decisions_rule_id_rules", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_routing_decisions"),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["record_id"], ["records.id"], name="fk_audit_log_record_id_records", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
    )
    op.create_index("ix_audit_log_record_id", "audit_log", ["record_id"])

    op.create_table(
        "eval_examples",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column("expected_category", sa.String(length=64), nullable=False),
        sa.Column("expected_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["record_id"], ["records.id"], name="fk_eval_examples_record_id_records", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_eval_examples"),
    )


def downgrade() -> None:
    op.drop_table("eval_examples")
    op.drop_table("audit_log")
    op.drop_table("routing_decisions")
    op.drop_table("extractions")
    op.drop_table("classifications")
    op.drop_table("rules")
    op.drop_table("records")
    op.drop_table("sources")
