"""migrate_embeddings_to_pgvector

Revision ID: a3b4c5d6e7f8
Revises: f6a7b8c9d0e1
Create Date: 2026-04-23

Converts all three embedding columns from JSONB to pgvector VECTOR(11)
and creates HNSW indexes for cosine ANN search.

Tables affected:
  user_embeddings.is_vector    JSONB → vector(11)
  group_embeddings.embedding   JSONB → vector(11)
  post_embeddings.vector       JSONB → vector(11)

The USING clause casts JSONB → text → vector.
JSONB arrays serialise as '[v1,v2,...]' which is exactly the pgvector
input format, so existing data is preserved without a separate backfill.

HNSW index params (defaults):
  m=16             — max connections per node per layer
  ef_construction=64 — candidate list size during index build
  operator=vector_cosine_ops — cosine distance (<=>)
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable the pgvector extension (Supabase has it pre-installed; this is a no-op if already active)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── user_embeddings ────────────────────────────────────────────────────────
    op.execute(
        "ALTER TABLE user_embeddings "
        "ALTER COLUMN is_vector TYPE vector(11) "
        "USING is_vector::text::vector"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_embeddings_hnsw "
        "ON user_embeddings USING hnsw (is_vector vector_cosine_ops)"
    )

    # ── group_embeddings ───────────────────────────────────────────────────────
    op.execute(
        "ALTER TABLE group_embeddings "
        "ALTER COLUMN embedding TYPE vector(11) "
        "USING embedding::text::vector"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_group_embeddings_hnsw "
        "ON group_embeddings USING hnsw (embedding vector_cosine_ops)"
    )

    # ── post_embeddings ────────────────────────────────────────────────────────
    op.execute(
        "ALTER TABLE post_embeddings "
        "ALTER COLUMN vector TYPE vector(11) "
        "USING vector::text::vector"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_post_embeddings_hnsw "
        "ON post_embeddings USING hnsw (vector vector_cosine_ops)"
    )


def downgrade() -> None:
    # ── post_embeddings ────────────────────────────────────────────────────────
    op.execute("DROP INDEX IF EXISTS ix_post_embeddings_hnsw")
    op.execute(
        "ALTER TABLE post_embeddings "
        "ALTER COLUMN vector TYPE jsonb "
        "USING vector::text::jsonb"
    )

    # ── group_embeddings ───────────────────────────────────────────────────────
    op.execute("DROP INDEX IF EXISTS ix_group_embeddings_hnsw")
    op.execute(
        "ALTER TABLE group_embeddings "
        "ALTER COLUMN embedding TYPE jsonb "
        "USING embedding::text::jsonb"
    )

    # ── user_embeddings ────────────────────────────────────────────────────────
    op.execute("DROP INDEX IF EXISTS ix_user_embeddings_hnsw")
    op.execute(
        "ALTER TABLE user_embeddings "
        "ALTER COLUMN is_vector TYPE jsonb "
        "USING is_vector::text::jsonb"
    )
