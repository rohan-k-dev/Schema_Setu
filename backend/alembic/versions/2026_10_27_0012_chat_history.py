"""Chat history per account

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-27

Reuses the conversation tables created in 0001 (never written until now — they held no rows):
  - sessions  one conversation: gains farmer_id (the owning account; ON DELETE CASCADE), title (the first
              question, trimmed), message_count; looked up by (farmer_id, last_activity_at).
  - messages  one turn side (USER / ASSISTANT): gains language, input_mode (text / voice), status (the reply
              status) and schemes (a small snapshot of the schemes shown: id, name, section, eligibility).
  - farmers.chat_history_enabled  the account's choice to keep chat history (default on; turning it off
              stops saving, it doesn't delete).
Conversations of anonymous visitors are not stored. See docs/CHAT_HISTORY.md.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("farmer_id", sa.Integer,
                                        sa.ForeignKey("farmers.id", ondelete="CASCADE"), nullable=True))
    op.add_column("sessions", sa.Column("title", sa.String(200)))
    op.add_column("sessions", sa.Column("message_count", sa.Integer, nullable=False, server_default="0"))
    op.create_index("ix_sessions_farmer_activity", "sessions", ["farmer_id", sa.text("last_activity_at DESC")])

    op.add_column("messages", sa.Column("language", sa.String(10)))
    op.add_column("messages", sa.Column("input_mode", sa.String(10)))
    op.add_column("messages", sa.Column("status", sa.String(40)))
    op.add_column("messages", sa.Column("schemes", postgresql.JSONB))
    op.create_check_constraint("ck_message_input_mode", "messages",
                               "input_mode IS NULL OR input_mode IN ('text', 'voice')")
    op.create_index("ix_messages_session", "messages", ["session_id", "id"])

    op.add_column("farmers", sa.Column("chat_history_enabled", sa.Boolean, nullable=False,
                                       server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("farmers", "chat_history_enabled")
    op.drop_index("ix_messages_session", table_name="messages")
    op.drop_constraint("ck_message_input_mode", "messages", type_="check")
    for col in ("schemes", "status", "input_mode", "language"):
        op.drop_column("messages", col)
    op.drop_index("ix_sessions_farmer_activity", table_name="sessions")
    for col in ("message_count", "title", "farmer_id"):
        op.drop_column("sessions", col)
