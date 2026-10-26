"""Persistent human-review queue

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-26

  - review_cases         cases escalated by the deterministic triggers (uncertain / unverifiable results,
        rule or source conflicts, failed retrieval channels). Holds the evidence, conflicting values and a
        MINIMAL profile snapshot (only the fields the triggering rules use). Assignment, the decision and a
        version number (optimistic locking: every change needs the version the reviewer saw).
        A partial unique index keeps one open case per (session, reason).
        farmer_id links a case to the signed-in farmer who triggered it (so they can see its status);
        it is never shown to reviewers and becomes NULL when the account is deleted.
  - review_case_events   append-only history: creation, assignment, comments, verification requests,
        decisions, dismissals — actor, from/to status, note, time. A trigger rejects UPDATE and DELETE.
Review decisions never change eligibility results or scheme rules (docs/HUMAN_REVIEW.md).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

REASONS = ("UNVERIFIABLE", "RULE_CONFLICT", "SOURCE_CONFLICT", "INSUFFICIENT_DATA", "SYSTEM_ERROR",
           "AMBIGUOUS_QUERY", "OTHER")
STATUSES = ("PENDING", "IN_REVIEW", "RESOLVED", "DISMISSED")
DECISIONS = ("APPROVE", "REJECT", "MARK_UNVERIFIABLE", "RESOLVE")
EVENTS = ("CREATED", "ASSIGNED", "UNASSIGNED", "COMMENT", "VERIFICATION_REQUESTED", "APPROVE", "REJECT",
          "MARK_UNVERIFIABLE", "RESOLVE", "DISMISSED")


def _in(values) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    now = sa.func.now()
    op.create_table(
        "review_cases",
        sa.Column("case_id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(100), nullable=False),
        sa.Column("reason", sa.String(20), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="PENDING"),
        sa.Column("query", sa.Text, nullable=False, server_default=""),
        sa.Column("profile_snapshot", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("scheme_ids", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("schemes", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("eligibility_results", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("evidence", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("rule_conflicts", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("source_conflicts", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("failed_channels", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("farmer_id", sa.Integer, sa.ForeignKey("farmers.id", ondelete="SET NULL")),
        sa.Column("assignee", sa.String(255)),
        sa.Column("assigned_at", sa.DateTime(timezone=True)),
        sa.Column("awaiting_verification", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("decision", sa.String(20)),
        sa.Column("data_correction_needed", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("reviewer_id", sa.String(255)),          # last reviewer action (who / what / note / when)
        sa.Column("reviewer_action", sa.String(30)),
        sa.Column("reviewer_note", sa.Text),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.CheckConstraint(f"reason IN {_in(REASONS)}", name="ck_review_reason"),
        sa.CheckConstraint(f"status IN {_in(STATUSES)}", name="ck_review_status"),
        sa.CheckConstraint(f"decision IS NULL OR decision IN {_in(DECISIONS)}", name="ck_review_decision"),
        sa.CheckConstraint("(status = 'RESOLVED') = (decision IS NOT NULL)", name="ck_review_resolved_decision"),
        sa.CheckConstraint("status <> 'IN_REVIEW' OR assignee IS NOT NULL", name="ck_review_in_review_assigned"),
    )
    op.create_index("ix_review_cases_status_created", "review_cases", ["status", "created_at"])
    op.create_index("ix_review_cases_farmer", "review_cases", ["farmer_id"])
    op.execute("CREATE UNIQUE INDEX uq_review_open_session_reason ON review_cases (session_id, reason) "
               "WHERE status IN ('PENDING', 'IN_REVIEW')")

    op.create_table(
        "review_case_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("review_cases.case_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("event", sa.String(30), nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("from_status", sa.String(12)),
        sa.Column("to_status", sa.String(12)),
        sa.Column("note", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.CheckConstraint(f"event IN {_in(EVENTS)}", name="ck_review_event"),
    )
    op.create_index("ix_review_case_events_case", "review_case_events", ["case_id", "id"])
    op.execute("""
        CREATE FUNCTION review_case_events_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'review_case_events is append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("CREATE TRIGGER trg_review_case_events_append_only BEFORE UPDATE OR DELETE ON review_case_events "
               "FOR EACH ROW WHEN (pg_trigger_depth() = 0) EXECUTE FUNCTION review_case_events_append_only()")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_review_case_events_append_only ON review_case_events")
    op.execute("DROP FUNCTION IF EXISTS review_case_events_append_only()")
    op.drop_table("review_case_events")
    op.drop_table("review_cases")
