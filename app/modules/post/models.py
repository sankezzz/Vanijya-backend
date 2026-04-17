from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import ARRAY, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database.base import Base


# ---------------------------------------------------------------------------
# Fixed category IDs – seeded in migration
# ---------------------------------------------------------------------------
# 1 = Market Update
# 2 = Knowledge
# 3 = Discussion
# 4 = Deal / Requirement
# 5 = Other

CATEGORY_DEAL = 4
CATEGORY_OTHER = 5


class PostCategory(Base):
    __tablename__ = "post_categories"

    # No autoincrement – IDs are fixed and seeded (1-5)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)

    posts: Mapped[list["Post"]] = relationship("Post", back_populates="post_category")


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("profile.id", ondelete="CASCADE"))
    category_id: Mapped[int] = mapped_column(Integer, ForeignKey("post_categories.id"))
    commodity_id: Mapped[int] = mapped_column(Integer, ForeignKey("commodities.id"))

    # Content
    image_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    caption: Mapped[str] = mapped_column(Text)

    # Visibility
    is_public: Mapped[bool] = mapped_column(default=True)
    target_roles: Mapped[Optional[list[int]]] = mapped_column(ARRAY(Integer), nullable=True)

    # Interaction controls
    allow_comments: Mapped[bool] = mapped_column(default=True)

    # Deal / Requirement fields (only used when category_id == CATEGORY_DEAL)
    grain_type_size: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    commodity_quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # 'fixed' | 'negotiable'

    # Other category (only used when category_id == CATEGORY_OTHER)
    other_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Counters
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
    share_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    post_category: Mapped["PostCategory"] = relationship("PostCategory", back_populates="posts")
    views: Mapped[list["PostView"]] = relationship("PostView", back_populates="post", cascade="all, delete-orphan")
    likes: Mapped[list["PostLike"]] = relationship("PostLike", back_populates="post", cascade="all, delete-orphan")
    comments: Mapped[list["PostComment"]] = relationship("PostComment", back_populates="post", cascade="all, delete-orphan")
    shares: Mapped[list["PostShare"]] = relationship("PostShare", back_populates="post", cascade="all, delete-orphan")
    saves: Mapped[list["PostSave"]] = relationship("PostSave", back_populates="post", cascade="all, delete-orphan")


class PostView(Base):
    __tablename__ = "post_views"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(Integer, ForeignKey("posts.id", ondelete="CASCADE"))
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("profile.id", ondelete="CASCADE"))
    viewed_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("post_id", "profile_id", name="uq_post_view"),
    )

    post: Mapped["Post"] = relationship("Post", back_populates="views")


class PostLike(Base):
    __tablename__ = "post_likes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(Integer, ForeignKey("posts.id", ondelete="CASCADE"))
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("profile.id", ondelete="CASCADE"))
    liked_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("post_id", "profile_id", name="uq_post_like"),
    )

    post: Mapped["Post"] = relationship("Post", back_populates="likes")


class PostComment(Base):
    __tablename__ = "post_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(Integer, ForeignKey("posts.id", ondelete="CASCADE"))
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("profile.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    post: Mapped["Post"] = relationship("Post", back_populates="comments")


class PostShare(Base):
    __tablename__ = "post_shares"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(Integer, ForeignKey("posts.id", ondelete="CASCADE"))
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("profile.id", ondelete="CASCADE"))
    shared_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    post: Mapped["Post"] = relationship("Post", back_populates="shares")


class PostSave(Base):
    __tablename__ = "post_saves"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(Integer, ForeignKey("posts.id", ondelete="CASCADE"))
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("profile.id", ondelete="CASCADE"))
    saved_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("post_id", "profile_id", name="uq_post_save"),
    )

    post: Mapped["Post"] = relationship("Post", back_populates="saves")
