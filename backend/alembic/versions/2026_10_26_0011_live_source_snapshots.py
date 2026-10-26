"""Provenance of live official-source checks

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-26

  - live_source_snapshots   one row per official page seen at query time (canonical URL): how it was
        retrieved (direct fetch / via Tavily), the last attempt's status, HTTP code and time, the
        fields extracted with their evidence, and the LAST KNOWN-GOOD extraction (+ the one before it).
        A failed or less complete extraction never replaces the last known-good one. change_status
        tells new / unchanged / updated / incomplete / unparseable / missing / failed;
        duplicate_of marks a page whose content is identical to another URL's.
See docs/LIVE_VERIFICATION.md.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHANGE = ("NEW", "UNCHANGED", "UPDATED", "INCOMPLETE", "UNPARSEABLE", "MISSING", "FAILED")


def upgrade() -> None:
    op.create_table(
        "live_source_snapshots",
        sa.Column("canonical_url", sa.String(600), primary_key=True),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("scheme_id", sa.String(100)),
        sa.Column("method", sa.String(20), nullable=False),               # direct / tavily
        sa.Column("last_status", sa.String(30), nullable=False),
        sa.Column("http_status", sa.Integer),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("etag", sa.String(255)),
        sa.Column("last_modified", sa.String(100)),
        sa.Column("attempt_extracted", postgresql.JSONB),                 # what the last attempt found
        sa.Column("attempt_quality", sa.String(12)),
        sa.Column("last_good", postgresql.JSONB),                         # last known-good extraction
        sa.Column("last_good_hash", sa.String(64)),
        sa.Column("last_good_quality", sa.String(12)),
        sa.Column("last_good_at", sa.DateTime(timezone=True)),
        sa.Column("previous_good", postgresql.JSONB),
        sa.Column("previous_good_at", sa.DateTime(timezone=True)),
        sa.Column("change_status", sa.String(12), nullable=False),
        sa.Column("duplicate_of", sa.String(600)),
        sa.Column("error", sa.Text),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("change_status IN (" + ", ".join(f"'{c}'" for c in CHANGE) + ")",
                           name="ck_live_snapshot_change"),
        sa.CheckConstraint("method IN ('direct', 'tavily')", name="ck_live_snapshot_method"),
    )
    op.create_index("ix_live_snapshots_scheme", "live_source_snapshots", ["scheme_id"])
    op.create_index("ix_live_snapshots_change", "live_source_snapshots", ["change_status", "last_attempt_at"])
    op.create_index("ix_live_snapshots_hash", "live_source_snapshots", ["last_good_hash"])


def downgrade() -> None:
    op.drop_table("live_source_snapshots")
