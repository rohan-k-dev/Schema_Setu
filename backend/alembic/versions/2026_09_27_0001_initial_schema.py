"""Phase 2 initial schema — all core tables

Revision ID: 0001
Revises: None
Create Date: 2026-09-27

Creates:
  - corpus_versions
  - ingestion_runs
  - schemes
  - scheme_aliases
  - scheme_states
  - scheme_districts
  - scheme_crops
  - scheme_beneficiaries
  - eligibility_rules
  - scheme_documents
  - application_steps
  - scheme_sources
  - scheme_benefits
  - sessions (optional persistence)
  - messages (optional persistence)
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- corpus_versions ----
    op.create_table(
        "corpus_versions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("version", sa.String(50), nullable=False, unique=True),
        sa.Column("schema_version", sa.String(50), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True)),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("source_count", sa.Integer),
        sa.Column("scheme_count", sa.Integer),
        sa.Column("manifest_hash", sa.String(128)),
        sa.Column("notes", sa.Text),
    )

    # ---- ingestion_runs ----
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("corpus_version_id", sa.Integer, sa.ForeignKey("corpus_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), nullable=False, server_default="RUNNING"),
        sa.Column("records_read", sa.Integer, server_default="0"),
        sa.Column("records_inserted", sa.Integer, server_default="0"),
        sa.Column("records_updated", sa.Integer, server_default="0"),
        sa.Column("records_skipped", sa.Integer, server_default="0"),
        sa.Column("errors", sa.Integer, server_default="0"),
        sa.Column("warnings", sa.Integer, server_default="0"),
        sa.Column("error_message", sa.Text),
        sa.Column("source_snapshot", sa.String(255)),
        sa.CheckConstraint("status IN ('RUNNING','SUCCESS','FAILED','PARTIAL')", name="ck_ingestion_status"),
    )

    # ---- schemes ----
    op.create_table(
        "schemes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("scheme_id", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("short_name", sa.String(200)),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("detailed_description", sa.Text),
        sa.Column("ministry", sa.String(500)),
        sa.Column("department", sa.String(500)),
        sa.Column("level", sa.String(50)),
        sa.Column("scheme_type", sa.String(100)),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("eligibility_summary", sa.Text),
        sa.Column("official_url", sa.String(2000)),
        sa.Column("application_url", sa.String(2000)),
        sa.Column("application_mode", postgresql.JSONB),
        sa.Column("aadhaar_requirement", sa.String(30)),
        sa.Column("data_version", sa.String(20), server_default="1.0"),
        sa.Column("last_verified_at", sa.Date),
        sa.Column("possible_duplicate", sa.Boolean, server_default="false"),
        sa.Column("needs_review", sa.Boolean, server_default="false"),
        sa.Column("review_notes", sa.Text),
        sa.Column("corpus_version_id", sa.Integer, sa.ForeignKey("corpus_versions.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('ACTIVE','INACTIVE','SUSPENDED','UNKNOWN')", name="ck_scheme_status"),
        sa.CheckConstraint("level IN ('central','state','district','central_state','unknown') OR level IS NULL", name="ck_scheme_level"),
    )
    op.create_index("ix_schemes_scheme_id", "schemes", ["scheme_id"], unique=True)
    op.create_index("ix_schemes_name", "schemes", ["name"])
    op.create_index("ix_schemes_status", "schemes", ["status"])
    op.create_index("ix_schemes_level", "schemes", ["level"])

    # ---- scheme_aliases ----
    op.create_table(
        "scheme_aliases",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("scheme_id", sa.Integer, sa.ForeignKey("schemes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alias", sa.String(500), nullable=False),
        sa.Column("normalized_alias", sa.String(500), nullable=False),
        sa.UniqueConstraint("scheme_id", "alias", name="uq_scheme_alias"),
    )
    op.create_index("ix_scheme_aliases_normalized", "scheme_aliases", ["normalized_alias"])

    # ---- scheme_states ----
    op.create_table(
        "scheme_states",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("scheme_id", sa.Integer, sa.ForeignKey("schemes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state", sa.String(100), nullable=False),
        sa.Column("is_exclusive", sa.Boolean, server_default="false"),
        sa.UniqueConstraint("scheme_id", "state", name="uq_scheme_state"),
    )
    op.create_index("ix_scheme_states_state", "scheme_states", ["state"])

    # ---- scheme_districts ----
    op.create_table(
        "scheme_districts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("scheme_id", sa.Integer, sa.ForeignKey("schemes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state", sa.String(100), nullable=False),
        sa.Column("district", sa.String(200), nullable=False),
        sa.UniqueConstraint("scheme_id", "state", "district", name="uq_scheme_district"),
    )

    # ---- scheme_crops ----
    op.create_table(
        "scheme_crops",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("scheme_id", sa.Integer, sa.ForeignKey("schemes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("crop", sa.String(200), nullable=False),
        sa.Column("normalized_crop", sa.String(200), nullable=False),
        sa.UniqueConstraint("scheme_id", "crop", name="uq_scheme_crop"),
    )
    op.create_index("ix_scheme_crops_normalized", "scheme_crops", ["normalized_crop"])

    # ---- scheme_beneficiaries ----
    op.create_table(
        "scheme_beneficiaries",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("scheme_id", sa.Integer, sa.ForeignKey("schemes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("beneficiary_type", sa.String(200), nullable=False),
        sa.UniqueConstraint("scheme_id", "beneficiary_type", name="uq_scheme_beneficiary"),
    )

    # ---- scheme_benefits ----
    op.create_table(
        "scheme_benefits",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("scheme_id", sa.Integer, sa.ForeignKey("schemes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("benefit_type", sa.String(50), nullable=False),
        sa.Column("amount", sa.String(500)),
        sa.Column("currency", sa.String(10), server_default="INR"),
        sa.Column("frequency", sa.String(200)),
        sa.Column("condition", sa.Text),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("source_text", sa.Text),
        sa.Column("benefit_order", sa.Integer, server_default="0"),
    )

    # ---- eligibility_rules ----
    op.create_table(
        "eligibility_rules",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("scheme_id", sa.Integer, sa.ForeignKey("schemes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_id", sa.String(100)),
        sa.Column("field_name", sa.String(100), nullable=False),
        sa.Column("operator", sa.String(20), nullable=False),
        sa.Column("value_json", postgresql.JSONB),
        sa.Column("logical_group", sa.String(10), nullable=False, server_default="AND"),
        sa.Column("required", sa.Boolean, server_default="true"),
        sa.Column("source_text", sa.Text),
        sa.Column("unit", sa.String(50)),
        sa.Column("original_value", postgresql.JSONB),
        sa.Column("original_unit", sa.String(50)),
        sa.Column("rule_order", sa.Integer, server_default="0"),
        sa.CheckConstraint(
            "operator IN ('EQ','NEQ','IN','NOT_IN','LT','LTE','GT','GTE','BETWEEN','CONTAINS','BOOLEAN','UNKNOWN')",
            name="ck_rule_operator"
        ),
        sa.CheckConstraint("logical_group IN ('AND','OR')", name="ck_logical_group"),
    )
    op.create_index("ix_eligibility_rules_scheme_id", "eligibility_rules", ["scheme_id"])
    op.create_index("ix_eligibility_rules_field_name", "eligibility_rules", ["field_name"])

    # ---- scheme_documents ----
    op.create_table(
        "scheme_documents",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("scheme_id", sa.Integer, sa.ForeignKey("schemes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("mandatory", sa.Boolean, server_default="true"),
        sa.Column("description", sa.Text),
        sa.Column("source_text", sa.Text),
        sa.Column("document_order", sa.Integer, server_default="0"),
        sa.UniqueConstraint("scheme_id", "name", name="uq_scheme_document"),
    )
    op.create_index("ix_scheme_documents_scheme_id", "scheme_documents", ["scheme_id"])

    # ---- application_steps ----
    op.create_table(
        "application_steps",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("scheme_id", sa.Integer, sa.ForeignKey("schemes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_number", sa.Integer, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("mode", sa.String(30)),
        sa.Column("portal_name", sa.String(500)),
        sa.Column("portal_url", sa.String(2000)),
        sa.Column("office_name", sa.String(500)),
        sa.Column("notes", sa.Text),
        sa.UniqueConstraint("scheme_id", "step_number", name="uq_scheme_step"),
        sa.CheckConstraint("mode IN ('ONLINE','OFFLINE','CSC','OFFICE','HYBRID','UNKNOWN') OR mode IS NULL", name="ck_step_mode"),
    )
    op.create_index("ix_application_steps_scheme_id", "application_steps", ["scheme_id"])

    # ---- scheme_sources ----
    op.create_table(
        "scheme_sources",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("scheme_id", sa.Integer, sa.ForeignKey("schemes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.String(100), nullable=False),
        sa.Column("url", sa.String(2000)),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("source_name", sa.String(500)),
        sa.Column("retrieved_at", sa.Date),
        sa.Column("verified_at", sa.Date),
        sa.Column("content_hash", sa.String(128)),
        sa.Column("reference_text", sa.Text),
        sa.Column("is_primary", sa.Boolean, server_default="false"),
        sa.CheckConstraint(
            "source_type IN ('OFFICIAL_CENTRAL','OFFICIAL_STATE','OFFICIAL_SCHEME_PORTAL','SECONDARY','UNKNOWN')",
            name="ck_source_type"
        ),
    )
    op.create_index("ix_scheme_sources_scheme_id", "scheme_sources", ["scheme_id"])
    op.create_index("ix_scheme_sources_source_type", "scheme_sources", ["source_type"])

    # ---- sessions (optional persistence) ----
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("thread_id", sa.String(200), nullable=False, unique=True),
        sa.Column("language", sa.String(20), server_default="en"),
        sa.Column("profile_json", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ---- messages ----
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Integer, sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('USER','ASSISTANT','SYSTEM','TOOL')", name="ck_message_role"),
    )


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("sessions")
    op.drop_table("scheme_sources")
    op.drop_table("application_steps")
    op.drop_table("scheme_documents")
    op.drop_table("eligibility_rules")
    op.drop_table("scheme_benefits")
    op.drop_table("scheme_beneficiaries")
    op.drop_table("scheme_crops")
    op.drop_table("scheme_districts")
    op.drop_table("scheme_states")
    op.drop_table("scheme_aliases")
    op.drop_table("schemes")
    op.drop_table("ingestion_runs")
    op.drop_table("corpus_versions")
