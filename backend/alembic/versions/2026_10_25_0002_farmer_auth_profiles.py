"""Farmer authentication, saved profiles, saved schemes, and search history

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-25

Creates:
  - farmers          (account credentials + session management)
  - farmer_profiles  (persisted eligibility details with consent flag)
  - saved_schemes    (bookmarked schemes per farmer)
  - search_history   (recent search queries per farmer)
  - refresh_tokens   (long-lived tokens for session renewal)
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- farmers (account credentials) ----
    op.create_table(
        "farmers",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("farmer_id", sa.String(36), nullable=False, unique=True),  # UUID
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("phone", sa.String(20), unique=True),
        sa.Column("full_name", sa.String(255)),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("is_verified", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("email_verified_at", sa.DateTime(timezone=True)),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("login_count", sa.Integer, server_default="0"),
        sa.Column("password_reset_token", sa.String(255)),
        sa.Column("password_reset_expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_farmers_farmer_id", "farmers", ["farmer_id"], unique=True)
    op.create_index("ix_farmers_email", "farmers", ["email"], unique=True)
    op.create_index("ix_farmers_phone", "farmers", ["phone"])

    # ---- refresh_tokens (for session renewal) ----
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("farmer_id", sa.Integer, sa.ForeignKey("farmers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("user_agent", sa.String(500)),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_refresh_tokens_farmer_id", "refresh_tokens", ["farmer_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)

    # ---- farmer_profiles (saved eligibility details) ----
    op.create_table(
        "farmer_profiles",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("farmer_id", sa.Integer, sa.ForeignKey("farmers.id", ondelete="CASCADE"), nullable=False, unique=True),
        # Location
        sa.Column("state", sa.String(100)),
        sa.Column("district", sa.String(200)),
        # Farming details
        sa.Column("land_size_acres", sa.Numeric(10, 2)),
        sa.Column("primary_crop", sa.String(200)),
        sa.Column("other_crops", postgresql.JSONB),  # list of additional crops
        sa.Column("farming_type", sa.String(50)),    # subsistence / commercial / mixed
        # Demographics
        sa.Column("age", sa.Integer),
        sa.Column("gender", sa.String(20)),
        sa.Column("category", sa.String(20)),        # General / OBC / SC / ST / EWS
        sa.Column("annual_income", sa.Numeric(15, 2)),
        # Eligibility indicators
        sa.Column("has_aadhaar", sa.Boolean),
        sa.Column("occupation", sa.String(100)),
        # Consent & meta
        sa.Column("consent_given", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("consent_given_at", sa.DateTime(timezone=True)),
        sa.Column("consent_version", sa.String(20), server_default="1.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("age IS NULL OR (age > 0 AND age < 120)", name="ck_profile_age"),
        sa.CheckConstraint("land_size_acres IS NULL OR land_size_acres >= 0", name="ck_profile_land"),
        sa.CheckConstraint(
            "gender IN ('male','female','other') OR gender IS NULL",
            name="ck_profile_gender"
        ),
        sa.CheckConstraint(
            "category IN ('General','OBC','SC','ST','EWS') OR category IS NULL",
            name="ck_profile_category"
        ),
    )
    op.create_index("ix_farmer_profiles_farmer_id", "farmer_profiles", ["farmer_id"], unique=True)
    op.create_index("ix_farmer_profiles_state", "farmer_profiles", ["state"])

    # ---- saved_schemes (bookmarked schemes per farmer) ----
    op.create_table(
        "saved_schemes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("farmer_id", sa.Integer, sa.ForeignKey("farmers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scheme_id", sa.String(100), nullable=False),   # external scheme_id (string)
        sa.Column("scheme_name", sa.String(500), nullable=False),
        sa.Column("notes", sa.Text),
        sa.Column("eligibility_status", sa.String(30)),
        sa.Column("saved_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("farmer_id", "scheme_id", name="uq_saved_scheme"),
    )
    op.create_index("ix_saved_schemes_farmer_id", "saved_schemes", ["farmer_id"])
    op.create_index("ix_saved_schemes_scheme_id", "saved_schemes", ["scheme_id"])

    # ---- search_history (recent queries per farmer) ----
    op.create_table(
        "search_history",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("farmer_id", sa.Integer, sa.ForeignKey("farmers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("results_count", sa.Integer, server_default="0"),
        sa.Column("language", sa.String(10), server_default="en"),
        sa.Column("searched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_search_history_farmer_id", "search_history", ["farmer_id"])
    op.create_index("ix_search_history_searched_at", "search_history", ["searched_at"])


def downgrade() -> None:
    op.drop_table("search_history")
    op.drop_table("saved_schemes")
    op.drop_table("farmer_profiles")
    op.drop_table("refresh_tokens")
    op.drop_table("farmers")
