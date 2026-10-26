"""Secure accounts: server-managed sessions, single-use tokens, login lockout

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-25

Adds:
  - auth_sessions  server-side sessions behind the HttpOnly session cookie
                   (only the SHA-256 of the cookie value is stored)
  - auth_tokens    single-use e-mail-verification and password-reset tokens (hashed)
  - farmers.failed_login_count / locked_until / password_changed_at

Backward compatible: no existing column or table is removed. The legacy
farmers.password_reset_token columns and the refresh_tokens table are no longer used.
Existing reset tokens are invalidated (the previous API returned them in its response)
and legacy refresh tokens are revoked (they are no longer accepted).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("farmers", sa.Column("failed_login_count", sa.Integer, nullable=False,
                                       server_default="0"))
    op.add_column("farmers", sa.Column("locked_until", sa.DateTime(timezone=True)))
    op.add_column("farmers", sa.Column("password_changed_at", sa.DateTime(timezone=True)))

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("farmer_id", sa.Integer, sa.ForeignKey("farmers.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("session_hash", sa.String(64), nullable=False),
        sa.Column("user_agent_hash", sa.String(64), nullable=False),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_reason", sa.String(40)),
    )
    op.create_index("ix_auth_sessions_session_hash", "auth_sessions", ["session_hash"], unique=True)
    op.create_index("ix_auth_sessions_farmer_id", "auth_sessions", ["farmer_id"])

    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("farmer_id", sa.Integer, sa.ForeignKey("farmers.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("purpose IN ('verify_email', 'reset_password')",
                           name="ck_auth_tokens_purpose"),
    )
    op.create_index("ix_auth_tokens_token_hash", "auth_tokens", ["token_hash"], unique=True)
    op.create_index("ix_auth_tokens_farmer_purpose", "auth_tokens", ["farmer_id", "purpose"])

    op.execute("UPDATE farmers SET password_reset_token = NULL, password_reset_expires_at = NULL")
    op.execute("UPDATE refresh_tokens SET revoked = true, revoked_at = NOW() WHERE revoked = false")


def downgrade() -> None:
    op.drop_table("auth_tokens")
    op.drop_table("auth_sessions")
    op.drop_column("farmers", "password_changed_at")
    op.drop_column("farmers", "locked_until")
    op.drop_column("farmers", "failed_login_count")
