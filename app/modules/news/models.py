import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database.base import Base


class NewsSource(Base):
    __tablename__ = "news_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    domain: Mapped[str] = mapped_column(String(200), nullable=False)
    rss_url: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    # 0.8 = low credibility  …  1.3 = government/authoritative
    credibility_weight: Mapped[float] = mapped_column(Float, default=1.0)
    # government | industry | wire | publication
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    articles: Mapped[list["NewsArticle"]] = relationship(
        "NewsArticle", back_populates="source"
    )


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("news_sources.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True)
    image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # ── Gemini classification fields ─────────────────────────────────────────
    cluster_id: Mapped[int | None] = mapped_column(Integer, nullable=True)    # 1–10
    severity: Mapped[float | None] = mapped_column(Float, nullable=True)      # 1–10
    commodities: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    regions: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    # local | state | national | global
    scope: Mapped[str | None] = mapped_column(String(20), nullable=True)
    direction_tags: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    # immediate | short | medium | long
    horizon: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Role-specific impact summaries written by Gemini
    trader_impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    broker_impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    exporter_impact: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Deduplication: same story across multiple sources shares a story_id;
    # when a duplicate arrives we keep the one with higher severity.
    story_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    is_classified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    source: Mapped["NewsSource"] = relationship("NewsSource", back_populates="articles")
    engagements: Mapped[list["NewsEngagement"]] = relationship(
        "NewsEngagement", back_populates="article"
    )
    trending_entries: Mapped[list["NewsTrending"]] = relationship(
        "NewsTrending", back_populates="article"
    )

    __table_args__ = (
        Index("ix_news_articles_published_at", "published_at"),
        Index("ix_news_articles_cluster_id", "cluster_id"),
        Index("ix_news_articles_story_id", "story_id"),
        Index("ix_news_articles_archived", "is_archived"),
    )


class NewsEngagement(Base):
    """
    One row per user interaction.
    action_type: view | click | dwell | like | save | comment | share_in | share_out | skip
    """
    __tablename__ = "news_engagement"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    article_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("news_articles.id"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(20), nullable=False)

    # Denormalised for fast aggregation in taste-update and trending tasks
    cluster_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # format: "role:commodity:state"  e.g. "trader:wheat:punjab"
    segment_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dwell_time_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    article: Mapped["NewsArticle"] = relationship(
        "NewsArticle", back_populates="engagements"
    )

    __table_args__ = (
        Index("ix_news_engagement_user_id", "user_id"),
        Index("ix_news_engagement_article_id", "article_id"),
        Index("ix_news_engagement_created_at", "created_at"),
    )


class UserClusterTaste(Base):
    """
    One row per (user, cluster). taste_weight is log1p-normalised 0–1,
    recalculated every hour by the taste-update background task.
    """
    __tablename__ = "user_cluster_taste"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    cluster_id: Mapped[int] = mapped_column(Integer, nullable=False)
    taste_weight: Mapped[float] = mapped_column(Float, default=0.0)
    interaction_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_dwell_time: Mapped[float] = mapped_column(Float, default=0.0)
    is_seeded: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint("user_id", "cluster_id", name="uq_user_cluster_taste"),
    )


class NewsTrending(Base):
    """
    Velocity-ranked articles per segment, recomputed every 5 min.
    segment_id format: "role:commodity:state"
    """
    __tablename__ = "news_trending"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    segment_id: Mapped[str] = mapped_column(String(100), nullable=False)
    article_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("news_articles.id"), nullable=False
    )
    velocity_score: Mapped[float] = mapped_column(Float, default=0.0)
    unique_users: Mapped[int] = mapped_column(Integer, default=0)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    article: Mapped["NewsArticle"] = relationship(
        "NewsArticle", back_populates="trending_entries"
    )

    __table_args__ = (
        UniqueConstraint(
            "segment_id", "article_id", name="uq_trending_segment_article"
        ),
        Index("ix_news_trending_segment_id", "segment_id"),
    )
