"""remove_soft_delete_from_users

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-04-24

Drops is_deleted and deleted_at from the users table.
User accounts are now hard-deleted — the row is removed and all related
data is cleaned up by the existing ON DELETE CASCADE foreign keys.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("users", "is_deleted")
    op.drop_column("users", "deleted_at")


def downgrade() -> None:
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"))
