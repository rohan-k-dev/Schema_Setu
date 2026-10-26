"""Scheme-update pipeline and notifications

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-26

  - scheme_change_batches / scheme_changes   detected differences between a candidate (scraped,
        normalised) corpus and the last verified one, with provenance; each change waits for an
        administrator's decision. A partial unique index on the change fingerprint keeps
        re-detection from creating duplicates while a change is pending or approved.
  - scheme_subscriptions                     explicit "follow this scheme" (saved schemes count too)
  - notification_preferences                 channels, consequential-only, SMS consent / opt-out
  - notifications                            in-app; UNIQUE (account, dedupe_key) — one per change set
  - notification_deliveries                  e-mail / SMS attempts; UNIQUE (notification, channel),
        status, attempts, next attempt, provider message id
  - farmers.phone_verified_at; auth_tokens gains purpose 'verify_phone', attempts, target
  - admin_jobs gains kind PUBLISH_CHANGES and params
See docs/SCHEME_UPDATES.md.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CATEGORIES = ("ELIGIBILITY", "BENEFITS", "STATES", "DOCUMENTS", "STEPS", "URLS", "STATUS",
              "NEW_SCHEME", "MISSING_FROM_SOURCE")
DELIVERY_STATUSES = ("PENDING", "SENDING", "SENT", "DELIVERED", "UNDELIVERED", "FAILED", "GAVE_UP", "SKIPPED")


def _in(values) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    now = sa.func.now()
    op.create_table(
        "scheme_change_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_name", sa.String(120), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("base_version", sa.String(20)),
        sa.Column("candidate_count", sa.Integer, nullable=False),
        sa.Column("invalid_records", postgresql.JSONB),
        sa.Column("warnings", postgresql.JSONB),
        sa.Column("status", sa.String(12), nullable=False, server_default="OPEN"),
        sa.Column("detected_by", sa.String(255), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("published_version", sa.String(20)),
        sa.Column("correlation_id", sa.String(64)),
        sa.CheckConstraint("status IN ('OPEN', 'PUBLISHED', 'DISCARDED')", name="ck_change_batch_status"),
    )
    op.create_table(
        "scheme_changes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("batch_id", sa.String(36), sa.ForeignKey("scheme_change_batches.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("scheme_id", sa.String(100), nullable=False),
        sa.Column("scheme_name", sa.String(500), nullable=False),
        sa.Column("category", sa.String(25), nullable=False),
        sa.Column("consequential", sa.Boolean, nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("before", postgresql.JSONB),
        sa.Column("after", postgresql.JSONB),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("provenance", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="PENDING"),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("reviewed_by", sa.String(255)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("review_note", sa.Text),
        sa.CheckConstraint(f"category IN {_in(CATEGORIES)}", name="ck_change_category"),
        sa.CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED', 'PUBLISHED', 'DISCARDED')",
                           name="ck_change_status"),
        sa.CheckConstraint("status = 'PENDING' OR status = 'DISCARDED' OR reviewed_at IS NOT NULL",
                           name="ck_change_reviewed"),
    )
    op.create_index("ix_scheme_changes_batch", "scheme_changes", ["batch_id"])
    op.execute("CREATE UNIQUE INDEX uq_scheme_change_open_fingerprint ON scheme_changes (fingerprint) "
               "WHERE status IN ('PENDING', 'APPROVED')")

    op.create_table(
        "scheme_subscriptions",
        sa.Column("farmer_id", sa.Integer, sa.ForeignKey("farmers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scheme_id", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.PrimaryKeyConstraint("farmer_id", "scheme_id"),
    )
    op.create_table(
        "notification_preferences",
        sa.Column("farmer_id", sa.Integer, sa.ForeignKey("farmers.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("in_app", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("email", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("sms", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("consequential_only", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("sms_consent_at", sa.DateTime(timezone=True)),
        sa.Column("sms_consent_version", sa.String(20)),
        sa.Column("sms_opted_out_at", sa.DateTime(timezone=True)),
        sa.Column("email_opted_out_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.CheckConstraint("NOT sms OR sms_consent_at IS NOT NULL", name="ck_pref_sms_consent"),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("farmer_id", sa.Integer, sa.ForeignKey("farmers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scheme_id", sa.String(100), nullable=False),
        sa.Column("batch_id", sa.String(36)),
        sa.Column("change_ids", postgresql.JSONB, nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("consequential", sa.Boolean, nullable=False),
        sa.Column("show_in_app", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("dedupe_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("farmer_id", "dedupe_key", name="uq_notification_dedupe"),
    )
    op.create_index("ix_notifications_farmer_created", "notifications", ["farmer_id", "created_at"])
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("notification_id", sa.BigInteger, sa.ForeignKey("notifications.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("farmer_id", sa.Integer, sa.ForeignKey("farmers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("provider_message_id", sa.String(120)),
        sa.Column("last_error", sa.Text),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.UniqueConstraint("notification_id", "channel", name="uq_delivery_once_per_channel"),
        sa.CheckConstraint("channel IN ('EMAIL', 'SMS')", name="ck_delivery_channel"),
        sa.CheckConstraint(f"status IN {_in(DELIVERY_STATUSES)}", name="ck_delivery_status"),
    )
    op.create_index("ix_deliveries_due", "notification_deliveries", ["status", "next_attempt_at"])
    op.create_index("ix_deliveries_provider_id", "notification_deliveries", ["provider_message_id"])

    op.add_column("farmers", sa.Column("phone_verified_at", sa.DateTime(timezone=True)))
    op.add_column("auth_tokens", sa.Column("attempts", sa.Integer, nullable=False, server_default="0"))
    op.add_column("auth_tokens", sa.Column("target", sa.String(32)))
    op.drop_constraint("ck_auth_tokens_purpose", "auth_tokens", type_="check")
    op.create_check_constraint("ck_auth_tokens_purpose", "auth_tokens",
                               "purpose IN ('verify_email', 'reset_password', 'verify_phone')")

    op.add_column("admin_jobs", sa.Column("params", postgresql.JSONB))
    op.drop_constraint("ck_job_kind", "admin_jobs", type_="check")
    op.create_check_constraint("ck_job_kind", "admin_jobs",
                               "kind IN ('IMPORT_CORPUS', 'REBUILD_GRAPH', 'PUBLISH_CHANGES')")


def downgrade() -> None:
    op.execute("DELETE FROM admin_jobs WHERE kind = 'PUBLISH_CHANGES'")
    op.drop_constraint("ck_job_kind", "admin_jobs", type_="check")
    op.create_check_constraint("ck_job_kind", "admin_jobs", "kind IN ('IMPORT_CORPUS', 'REBUILD_GRAPH')")
    op.drop_column("admin_jobs", "params")
    op.execute("DELETE FROM auth_tokens WHERE purpose = 'verify_phone'")
    op.drop_constraint("ck_auth_tokens_purpose", "auth_tokens", type_="check")
    op.create_check_constraint("ck_auth_tokens_purpose", "auth_tokens",
                               "purpose IN ('verify_email', 'reset_password')")
    op.drop_column("auth_tokens", "target")
    op.drop_column("auth_tokens", "attempts")
    op.drop_column("farmers", "phone_verified_at")
    for table in ("notification_deliveries", "notifications", "notification_preferences", "scheme_subscriptions",
                  "scheme_changes", "scheme_change_batches"):
        op.drop_table(table)
