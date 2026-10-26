"""Role-based access control: account roles + append-only audit log

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-25

  - farmers.role          FARMER (default for every account, existing and new) / REVIEWER / ADMIN.
                          Never set from a request body: only an administrator (other than the
                          account itself) or the server-side scripts/set_role.py can change it.
  - audit_events (new)    security-relevant actions: role and account-status changes, scheme
                          curation, review decisions, denied access attempts. Append-only: a
                          trigger rejects UPDATE and DELETE. Actors are stored by value (id +
                          label), not by foreign key, so deleting an account never rewrites history.
See docs/RBAC.md.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLES = ("FARMER", "REVIEWER", "ADMIN")


def upgrade() -> None:
    op.add_column("farmers", sa.Column("role", sa.String(20), nullable=False, server_default="FARMER"))
    op.create_check_constraint("ck_farmer_role", "farmers",
                               "role IN (" + ", ".join(f"'{r}'" for r in ROLES) + ")")
    op.create_index("ix_farmers_role", "farmers", ["role"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("actor_account_id", sa.Integer),          # farmers.id at the time (no FK: history is kept)
        sa.Column("actor_label", sa.String(255), nullable=False),   # e-mail, or "review-key"
        sa.Column("actor_role", sa.String(20)),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("target_type", sa.String(30)),
        sa.Column("target_id", sa.String(100)),
        sa.Column("details", postgresql.JSONB),
        sa.Column("ip_address", sa.String(45)),
    )
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_target", "audit_events", ["target_type", "target_id"])
    op.execute("""
        CREATE FUNCTION audit_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only';
        END $$
    """)
    op.execute("""
        CREATE TRIGGER trg_audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS audit_events_append_only()")
    op.drop_table("audit_events")
    op.drop_index("ix_farmers_role", table_name="farmers")
    op.drop_constraint("ck_farmer_role", "farmers", type_="check")
    op.drop_column("farmers", "role")
