"""Admin operations: audit outcome + correlation id + hash chain; admin jobs

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-25

audit_events gains:
  - outcome            SUCCESS / FAILURE / DENIED (existing ACCESS_DENIED rows → DENIED)
  - correlation_id     the request's X-Request-ID, to tie an event to logs and errors
  - prev_hash, entry_hash
                       tamper-evident hash chain (app/core/audit_chain.py); existing rows are
                       chained here in id order. The append-only trigger is suspended only for
                       this backfill, inside the migration's transaction.

admin_jobs (new): ingestion / graph-rebuild jobs started from the admin dashboard. A partial
unique index allows at most ONE queued or running job at a time.
See docs/ADMIN_OPERATIONS.md.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from app.core.audit_chain import GENESIS, entry_hash

    op.add_column("audit_events", sa.Column("outcome", sa.String(10), nullable=False, server_default="SUCCESS"))
    op.add_column("audit_events", sa.Column("correlation_id", sa.String(64)))
    op.add_column("audit_events", sa.Column("prev_hash", sa.String(64)))
    op.add_column("audit_events", sa.Column("entry_hash", sa.String(64)))
    op.create_check_constraint("ck_audit_outcome", "audit_events", "outcome IN ('SUCCESS', 'FAILURE', 'DENIED')")
    op.create_index("ix_audit_events_correlation", "audit_events", ["correlation_id"])

    bind = op.get_bind()
    op.execute("ALTER TABLE audit_events DISABLE TRIGGER trg_audit_events_append_only")
    op.execute("UPDATE audit_events SET outcome = 'DENIED' WHERE action = 'ACCESS_DENIED'")
    rows = bind.execute(sa.text("SELECT * FROM audit_events ORDER BY id")).mappings().all()
    prev = GENESIS
    for row in rows:
        h = entry_hash(prev, dict(row))
        bind.execute(sa.text("UPDATE audit_events SET prev_hash = :p, entry_hash = :h WHERE id = :id"),
                     {"p": prev, "h": h, "id": row["id"]})
        prev = h
    op.execute("ALTER TABLE audit_events ENABLE TRIGGER trg_audit_events_append_only")
    op.alter_column("audit_events", "prev_hash", nullable=False)
    op.alter_column("audit_events", "entry_hash", nullable=False)

    op.create_table(
        "admin_jobs",
        sa.Column("id", sa.String(36), primary_key=True),                 # UUID
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="QUEUED"),
        sa.Column("dry_run", sa.Boolean, nullable=False),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("requested_by_account_id", sa.Integer),
        sa.Column("requested_by", sa.String(255), nullable=False),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("result", postgresql.JSONB),
        sa.Column("error", sa.Text),
        sa.CheckConstraint("kind IN ('IMPORT_CORPUS', 'REBUILD_GRAPH')", name="ck_job_kind"),
        sa.CheckConstraint("status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')", name="ck_job_status"),
    )
    op.create_index("ix_admin_jobs_created", "admin_jobs", ["created_at"])
    op.execute("CREATE UNIQUE INDEX uq_admin_jobs_one_active ON admin_jobs ((true)) "
               "WHERE status IN ('QUEUED', 'RUNNING')")


def downgrade() -> None:
    op.drop_table("admin_jobs")
    op.drop_index("ix_audit_events_correlation", table_name="audit_events")
    op.drop_constraint("ck_audit_outcome", "audit_events", type_="check")
    for col in ("entry_hash", "prev_hash", "correlation_id", "outcome"):
        op.drop_column("audit_events", col)
