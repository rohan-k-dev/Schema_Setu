"""Reviewer authorization policy

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-26

  - farmers.reviewer_approved_at / reviewer_approved_by   a REVIEWER account can work review cases only
        once an administrator has approved it (the role alone is not enough). Cleared when the role
        changes away from REVIEWER. Existing REVIEWER accounts are NOT approved by this migration.
  - auth_sessions.reauthenticated_at   when the password was last re-entered in this session; sensitive
        actions (final review decisions, assignments, grants, approvals) need a recent authentication.
  - review_case_grants   explicit, expiring permission for one reviewer to read (and comment on) one
        case that isn't assigned to them; revocable; never lets them decide it.
See docs/HUMAN_REVIEW.md (Access policy).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("farmers", sa.Column("reviewer_approved_at", sa.DateTime(timezone=True)))
    op.add_column("farmers", sa.Column("reviewer_approved_by", sa.String(255)))
    op.create_check_constraint("ck_farmers_reviewer_approval", "farmers",
                               "reviewer_approved_at IS NULL OR role = 'REVIEWER'")
    op.add_column("auth_sessions", sa.Column("reauthenticated_at", sa.DateTime(timezone=True)))
    op.create_table(
        "review_case_grants",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("review_cases.case_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("reviewer_id", sa.Integer, sa.ForeignKey("farmers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("granted_by", sa.String(255), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by", sa.String(255)),
        sa.CheckConstraint("expires_at > granted_at", name="ck_review_grant_expiry"),
    )
    op.create_index("ix_review_case_grants_reviewer", "review_case_grants", ["reviewer_id", "case_id"])
    op.execute("CREATE UNIQUE INDEX uq_review_grant_active ON review_case_grants (case_id, reviewer_id) "
               "WHERE revoked_at IS NULL")


def downgrade() -> None:
    op.drop_table("review_case_grants")
    op.drop_column("auth_sessions", "reauthenticated_at")
    op.drop_constraint("ck_farmers_reviewer_approval", "farmers", type_="check")
    op.drop_column("farmers", "reviewer_approved_by")
    op.drop_column("farmers", "reviewer_approved_at")
