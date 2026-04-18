from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ── Inbound ───────────────────────────────────────────────────────────────────

class EngageRequest(BaseModel):
    action_type: str = Field(
        ...,
        description="view | click | dwell | like | save | comment | share_in | share_out | skip",
    )
    dwell_time_s: Optional[int] = None
    comment_text: Optional[str] = Field(None, max_length=1000)
    segment_id: Optional[str] = Field(
        None,
        description="role:commodity:state  e.g. trader:wheat:punjab",
    )


class CommentRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)


# ── Article out ───────────────────────────────────────────────────────────────

class ArticleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    summary: Optional[str] = None
    url: str
    image_url: Optional[str] = None
    published_at: datetime

    cluster_id: Optional[int] = None
    severity: Optional[float] = None
    commodities: list[str] = []
    regions: list[str] = []
    scope: Optional[str] = None
    direction_tags: list[str] = []
    horizon: Optional[str] = None

    source_name: Optional[str] = None
    source_credibility: Optional[float] = None
    source_category: Optional[str] = None

    trader_impact: Optional[str] = None
    broker_impact: Optional[str] = None
    exporter_impact: Optional[str] = None

    liked: bool = False
    saved: bool = False
    like_count: int = 0
    comment_count: int = 0
    share_count: int = 0


# ── Feed ──────────────────────────────────────────────────────────────────────

class FeedSection(BaseModel):
    key: str
    label: str
    articles: list[ArticleOut]


class FeedResponse(BaseModel):
    sections: list[FeedSection]


# ── Taste profile ─────────────────────────────────────────────────────────────

class ClusterTasteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cluster_id: int
    cluster_name: str
    taste_weight: float
    interaction_count: int
    avg_dwell_time: float
    is_seeded: bool


class TasteProfileOut(BaseModel):
    user_id: UUID
    clusters: list[ClusterTasteOut]


# ── Engagement history ────────────────────────────────────────────────────────

class EngagementHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    article_id: UUID
    action_type: str
    segment_id: Optional[str] = None
    dwell_time_s: Optional[int] = None
    created_at: datetime


# ── Interactions ──────────────────────────────────────────────────────────────

class LikeToggleOut(BaseModel):
    liked: bool
    like_count: int = 0


class SaveToggleOut(BaseModel):
    saved: bool


class ShareOut(BaseModel):
    share_count: int


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    comment_text: Optional[str] = None
    created_at: datetime
