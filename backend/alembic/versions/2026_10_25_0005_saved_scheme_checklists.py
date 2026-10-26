"""Saved schemes: scheme version tracking + user-reported application checklists

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-25

saved_schemes gains:
  - scheme_version / saved_scheme_version   content hash of the scheme (name, URLs, documents,
                                            application steps) the checklist is synced to / was
                                            first saved with
  - scheme_data_version                     the corpus data_version at that time
  - previous_scheme_version, scheme_changed_at, scheme_update_seen
                                            set when the scheme changed after it was saved
  - application_reference (+ _updated_at)   optional, only if the farmer chooses to record one
  - updated_at
  - UNIQUE (id, farmer_id)                  target of the checklist's composite foreign key

saved_scheme_checklist_items (new): one row per checklist item. The composite foreign key
(saved_scheme_id, farmer_id) → saved_schemes(id, farmer_id) guarantees that every item
belongs to the same farmer as its saved scheme. Items are deleted with the saved scheme
(unsave) and with the account. Existing saved schemes get their checklist on first read.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CATEGORIES = ("DOCUMENT", "PREPARATION", "APPLICATION", "SUBMISSION", "ACKNOWLEDGEMENT", "MILESTONE")


def upgrade() -> None:
    for col in (
        sa.Column("scheme_version", sa.String(64)),
        sa.Column("saved_scheme_version", sa.String(64)),
        sa.Column("scheme_data_version", sa.String(20)),
        sa.Column("previous_scheme_version", sa.String(64)),
        sa.Column("scheme_changed_at", sa.DateTime(timezone=True)),
        sa.Column("scheme_update_seen", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("application_reference", sa.String(64)),
        sa.Column("application_reference_updated_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    ):
        op.add_column("saved_schemes", col)
    # The old API had no length limit on notes; keep the first 1000 characters of any longer one.
    op.execute("UPDATE saved_schemes SET notes = left(notes, 1000) WHERE char_length(notes) > 1000")
    op.create_check_constraint(
        "ck_saved_scheme_notes_len", "saved_schemes", "notes IS NULL OR char_length(notes) <= 1000")
    op.create_unique_constraint("uq_saved_scheme_owner", "saved_schemes", ["id", "farmer_id"])

    op.create_table(
        "saved_scheme_checklist_items",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("saved_scheme_id", sa.Integer, nullable=False),
        sa.Column("farmer_id", sa.Integer, sa.ForeignKey("farmers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_key", sa.String(80), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),          # SCHEME (from scheme data) / USER
        sa.Column("label", sa.String(300), nullable=False),
        sa.Column("detail", sa.Text),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("completed", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("note", sa.Text),
        sa.Column("introduced_in_version", sa.String(64)),
        sa.Column("removed_in_version", sa.String(64)),            # set when a scheme update dropped it
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["saved_scheme_id", "farmer_id"], ["saved_schemes.id", "saved_schemes.farmer_id"],
                                name="fk_checklist_saved_scheme_owner", ondelete="CASCADE"),
        sa.UniqueConstraint("saved_scheme_id", "item_key", name="uq_checklist_item_key"),
        sa.CheckConstraint("category IN (" + ", ".join(f"'{c}'" for c in CATEGORIES) + ")",
                           name="ck_checklist_category"),
        sa.CheckConstraint("(source = 'USER' AND category = 'MILESTONE') OR "
                           "(source = 'SCHEME' AND category <> 'MILESTONE')", name="ck_checklist_source"),
        sa.CheckConstraint("note IS NULL OR char_length(note) <= 500", name="ck_checklist_note_len"),
        sa.CheckConstraint("completed OR completed_at IS NULL", name="ck_checklist_completed_at"),
    )
    op.create_index("ix_checklist_items_saved_scheme", "saved_scheme_checklist_items", ["saved_scheme_id"])
    op.create_index("ix_checklist_items_farmer", "saved_scheme_checklist_items", ["farmer_id"])


def downgrade() -> None:
    op.drop_table("saved_scheme_checklist_items")
    op.drop_constraint("uq_saved_scheme_owner", "saved_schemes", type_="unique")
    op.drop_constraint("ck_saved_scheme_notes_len", "saved_schemes", type_="check")
    for col in ("updated_at", "application_reference_updated_at", "application_reference",
                "scheme_update_seen", "scheme_changed_at", "previous_scheme_version",
                "scheme_data_version", "saved_scheme_version", "scheme_version"):
        op.drop_column("saved_schemes", col)
