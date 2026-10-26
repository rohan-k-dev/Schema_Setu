"""Farmer profile module: land unit, income range, residence, versioning, data minimisation

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-25

farmer_profiles gains:
  - land_size_value + land_unit   what the farmer entered (acre / hectare / guntha / cent);
                                  land_size_acres stays the engine's canonical value
  - income_range                  coarse band instead of an exact income
  - residence                     rural / urban (used by the MGNREGA rule)
  - version                       optimistic concurrency: stale edits get HTTP 409

Data minimisation (no eligibility rule uses them):
  - exact annual_income is converted to income_range, then cleared
  - has_aadhaar is cleared (Aadhaar status is not collected; the number never was)
The columns themselves stay (backward compatible); downgrade cannot restore cleared values.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INCOME_RANGES = ("below_1_lakh", "1_to_2.5_lakh", "2.5_to_5_lakh", "5_to_10_lakh", "above_10_lakh")
LAND_UNITS = ("acre", "hectare", "guntha", "cent")


def upgrade() -> None:
    op.add_column("farmer_profiles", sa.Column("land_size_value", sa.Numeric(12, 4)))
    op.add_column("farmer_profiles", sa.Column("land_unit", sa.String(10)))
    op.add_column("farmer_profiles", sa.Column("income_range", sa.String(20)))
    op.add_column("farmer_profiles", sa.Column("residence", sa.String(10)))
    op.add_column("farmer_profiles", sa.Column("version", sa.Integer, nullable=False, server_default="1"))

    op.create_check_constraint(
        "ck_profile_land_unit", "farmer_profiles",
        "land_unit IS NULL OR land_unit IN (" + ", ".join(f"'{u}'" for u in LAND_UNITS) + ")")
    op.create_check_constraint(
        "ck_profile_land_value", "farmer_profiles", "land_size_value IS NULL OR land_size_value >= 0")
    op.create_check_constraint(
        "ck_profile_land_pair", "farmer_profiles",
        "(land_size_value IS NULL) = (land_unit IS NULL)")
    op.create_check_constraint(
        "ck_profile_income_range", "farmer_profiles",
        "income_range IS NULL OR income_range IN (" + ", ".join(f"'{r}'" for r in INCOME_RANGES) + ")")
    op.create_check_constraint(
        "ck_profile_residence", "farmer_profiles", "residence IS NULL OR residence IN ('rural', 'urban')")

    op.execute("""
        UPDATE farmer_profiles
        SET land_size_value = land_size_acres, land_unit = 'acre'
        WHERE land_size_acres IS NOT NULL
    """)
    op.execute("""
        UPDATE farmer_profiles SET income_range = CASE
            WHEN annual_income < 100000 THEN 'below_1_lakh'
            WHEN annual_income < 250000 THEN '1_to_2.5_lakh'
            WHEN annual_income < 500000 THEN '2.5_to_5_lakh'
            WHEN annual_income < 1000000 THEN '5_to_10_lakh'
            ELSE 'above_10_lakh' END
        WHERE annual_income IS NOT NULL
    """)
    op.execute("UPDATE farmer_profiles SET annual_income = NULL, has_aadhaar = NULL")


def downgrade() -> None:
    for name in ("ck_profile_residence", "ck_profile_income_range", "ck_profile_land_pair",
                 "ck_profile_land_value", "ck_profile_land_unit"):
        op.drop_constraint(name, "farmer_profiles", type_="check")
    for col in ("version", "residence", "income_range", "land_unit", "land_size_value"):
        op.drop_column("farmer_profiles", col)
