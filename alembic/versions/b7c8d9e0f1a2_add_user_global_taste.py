"""add user_global_taste table

Revision ID: b7c8d9e0f1a2
Revises: p7q8r9s0t1u2
Create Date: 2026-07-06

New tables
----------
user_global_taste – persistent cross-platform taste (Layer 3), fed by the
                    nightly global-session promotion job. Currently active
                    dimension: commodity. location/quantity are placeholders.

Unique: (profile_id, dimension_type, dimension_key)
Index: ix_user_global_taste_profile_dim on (profile_id, dimension_type)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, None] = 'p7q8r9s0t1u2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_global_taste",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("dimension_type", sa.String(length=50), nullable=False),
        sa.Column("dimension_key", sa.String(length=100), nullable=False),
        sa.Column("positive_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("negative_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profile_id", "dimension_type", "dimension_key",
            name="uq_user_global_taste_profile_dim",
        ),
    )
    op.create_index(
        "ix_user_global_taste_profile_id", "user_global_taste", ["profile_id"],
    )
    op.create_index(
        "ix_user_global_taste_profile_dim",
        "user_global_taste", ["profile_id", "dimension_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_global_taste_profile_dim", table_name="user_global_taste")
    op.drop_index("ix_user_global_taste_profile_id", table_name="user_global_taste")
    op.drop_table("user_global_taste")
