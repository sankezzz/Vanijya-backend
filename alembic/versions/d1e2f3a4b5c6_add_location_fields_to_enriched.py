"""add location_city, location_state, latitude, longitude to news_enriched_articles

Revision ID: d1e2f3a4b5c6
Revises: b7c8d9e0f1a2
Create Date: 2026-08-05

Global session taste expansion (city + state as cross-platform dimensions) needs
News to name the single primary place each article is about, extracted directly
by the LLM enrichment prompt as text -- not derived from coordinates. location_city
and location_state are the fields actually read by the taste write path; latitude
and longitude are supplementary, best-effort coordinates for that same place, not
used to derive the text fields. Existing rows get NULL (treated as no signal in
the taste write path); new enrichments populate all four. Additive, non-destructive.
"""
from __future__ import annotations

from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "news_enriched_articles",
        sa.Column("location_city", sa.String(100), nullable=True),
    )
    op.add_column(
        "news_enriched_articles",
        sa.Column("location_state", sa.String(100), nullable=True),
    )
    op.add_column(
        "news_enriched_articles",
        sa.Column("latitude", sa.Float(), nullable=True),
    )
    op.add_column(
        "news_enriched_articles",
        sa.Column("longitude", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("news_enriched_articles", "longitude")
    op.drop_column("news_enriched_articles", "latitude")
    op.drop_column("news_enriched_articles", "location_state")
    op.drop_column("news_enriched_articles", "location_city")
