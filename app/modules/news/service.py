from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.modules.news.models import (
    NewsArticle,
    NewsEngagement,
    NewsSource,
    NewsTrending,
    UserClusterTaste,
)
from app.modules.profile.models import Profile, Profile_Commodity, Commodity, Role
from app.modules.news.schemas import (
    ArticleOut,
    ClusterTasteOut,
    CommentOut,
    EngagementHistoryItem,
    FeedResponse,
    FeedSection,
    LikeToggleOut,
    SaveToggleOut,
    ShareOut,
    TasteProfileOut,
)
from app.modules.news.weights_config import (
    ACTION_WEIGHTS,
    BREAKING_CLUSTERS,
    BREAKING_SEVERITY_THRESHOLD,
    CLUSTER_NAMES,
    CLUSTER_ROLE_WEIGHTS,
    COLD_START_DEFAULTS,
    DWELL_THRESHOLD_S,
    FEED_BREAKING_COUNT,
    FEED_FOR_YOU_COUNT,
    FEED_GOVERNMENT_COUNT,
    FEED_TRENDING_COUNT,
    FEED_WORTH_KNOWING_COUNT,
    RECENCY_CUTOFF_H,
    RECENCY_TIERS,
    SCOPE_MATCH,
)


# ── Custom exceptions ─────────────────────────────────────────────────────────

class NewsNotFoundError(Exception):
    pass


class NewsValidationError(Exception):
    pass


class ProfileNotFoundError(Exception):
    pass


ROLE_MAP = {1: "trader", 2: "broker", 3: "exporter"}


def _get_user_context(db: Session, user_id: UUID) -> tuple[str, list[str]]:
    """Returns (role_name, commodity_names) from the user's profile."""
    profile = (
        db.query(Profile)
        .filter(Profile.users_id == user_id)
        .first()
    )
    if not profile:
        raise ProfileNotFoundError("Profile not found for this user")

    role = ROLE_MAP.get(profile.role_id, "trader")

    commodities = (
        db.query(Commodity.name)
        .join(Profile_Commodity, Commodity.id == Profile_Commodity.commodity_id)
        .filter(Profile_Commodity.profile_id == profile.id)
        .all()
    )
    commodity_names = [c.name.lower() for c in commodities]

    return role, commodity_names


# ── Scoring helpers ───────────────────────────────────────────────────────────

def _recency_mult(published_at: datetime) -> float:
    now = datetime.now(timezone.utc)
    pub = published_at if published_at.tzinfo else published_at.replace(tzinfo=timezone.utc)
    age_h = (now - pub).total_seconds() / 3600
    if age_h >= RECENCY_CUTOFF_H:
        return 0.0
    for max_age, mult in RECENCY_TIERS:
        if age_h < max_age:
            return mult
    return 0.4


def _commodity_mult(article_commodities: list | None, user_commodities: list[str]) -> float:
    if not article_commodities or not user_commodities:
        return 1.0
    overlap = {c.lower() for c in article_commodities} & {c.lower() for c in user_commodities}
    return 1.5 if overlap else 1.0


def _region_mult(article_regions: list | None, user_state: str) -> float:
    if not article_regions or not user_state:
        return 1.0
    return 1.3 if user_state.lower() in {r.lower() for r in article_regions} else 1.0


def _scope_mult(article_scope: str | None, user_scope: str) -> float:
    if not article_scope:
        return 1.0
    return SCOPE_MATCH.get(article_scope, {}).get(user_scope, 1.0)


def _compute_score(
    article: NewsArticle,
    role: str,
    commodities: list[str],
    state: str,
    user_scope: str,
    taste_weights: dict[int, float],
    trending_ids: set,
) -> float:
    recency = _recency_mult(article.published_at)
    if recency == 0.0:
        return 0.0

    cluster_id = article.cluster_id or 10
    severity = article.severity or 5.0
    role_weight = CLUSTER_ROLE_WEIGHTS.get(cluster_id, {}).get(role, 3.0)

    is_breaking = cluster_id in BREAKING_CLUSTERS and severity >= BREAKING_SEVERITY_THRESHOLD

    # Breaking news bypasses geo/commodity filters
    if is_breaking:
        commodity = max(_commodity_mult(article.commodities, commodities), 1.0)
        region    = max(_region_mult(article.regions, state), 1.0)
        scope     = max(_scope_mult(article.scope, user_scope), 1.0)
    else:
        commodity = _commodity_mult(article.commodities, commodities)
        region    = _region_mult(article.regions, state)
        scope     = _scope_mult(article.scope, user_scope)

    credibility  = article.source.credibility_weight if article.source else 1.0
    taste_boost  = min(taste_weights.get(cluster_id, 0.0), 0.3)
    social_boost = 0.2 if article.id in trending_ids else 0.0

    return (
        severity
        * (role_weight / 10.0)
        * commodity
        * scope
        * region
        * recency
        * credibility
        * (1 + taste_boost)
        * (1 + social_boost)
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _ensure_cold_start(db: Session, user_id: UUID, role: str) -> None:
    exists = (
        db.query(UserClusterTaste.id)
        .filter(UserClusterTaste.user_id == user_id)
        .first()
    )
    if exists:
        return
    for cluster_id, weight in COLD_START_DEFAULTS.get(role, {}).items():
        db.add(
            UserClusterTaste(
                user_id=user_id,
                cluster_id=cluster_id,
                taste_weight=weight,
                is_seeded=True,
            )
        )
    db.commit()


def _taste_weights(db: Session, user_id: UUID) -> dict[int, float]:
    rows = (
        db.query(UserClusterTaste)
        .filter(UserClusterTaste.user_id == user_id)
        .all()
    )
    return {r.cluster_id: r.taste_weight for r in rows}


def _article_out(
    article: NewsArticle,
    liked_ids: set,
    saved_ids: set,
    counts: dict | None = None,
) -> ArticleOut:
    c = (counts or {}).get(article.id, {})
    return ArticleOut(
        id=article.id,
        title=article.title,
        summary=article.summary,
        url=article.url,
        image_url=article.image_url,
        published_at=article.published_at,
        cluster_id=article.cluster_id,
        severity=article.severity,
        commodities=article.commodities or [],
        regions=article.regions or [],
        scope=article.scope,
        direction_tags=article.direction_tags or [],
        horizon=article.horizon,
        source_name=article.source.name if article.source else None,
        source_credibility=article.source.credibility_weight if article.source else None,
        source_category=article.source.category if article.source else None,
        trader_impact=article.trader_impact,
        broker_impact=article.broker_impact,
        exporter_impact=article.exporter_impact,
        liked=article.id in liked_ids,
        saved=article.id in saved_ids,
        like_count=c.get("like_count", 0),
        comment_count=c.get("comment_count", 0),
        share_count=c.get("share_count", 0),
    )


def _engagement_ids(db: Session, user_id: UUID, article_ids: list, action: str) -> set:
    if not article_ids:
        return set()
    rows = (
        db.query(NewsEngagement.article_id)
        .filter(
            NewsEngagement.user_id == user_id,
            NewsEngagement.action_type == action,
            NewsEngagement.article_id.in_(article_ids),
        )
        .all()
    )
    return {r.article_id for r in rows}


def _fetch_counts(db: Session, article_ids: list) -> dict[UUID, dict]:
    """Returns {article_id: {like_count, comment_count, share_count}} in one query."""
    if not article_ids:
        return {}
    rows = (
        db.query(
            NewsEngagement.article_id,
            NewsEngagement.action_type,
            func.count().label("cnt"),
        )
        .filter(
            NewsEngagement.article_id.in_(article_ids),
            NewsEngagement.action_type.in_(["like", "comment", "share_out"]),
        )
        .group_by(NewsEngagement.article_id, NewsEngagement.action_type)
        .all()
    )
    counts: dict[UUID, dict] = {}
    for article_id, action_type, cnt in rows:
        if article_id not in counts:
            counts[article_id] = {"like_count": 0, "comment_count": 0, "share_count": 0}
        if action_type == "like":
            counts[article_id]["like_count"] = cnt
        elif action_type == "comment":
            counts[article_id]["comment_count"] = cnt
        elif action_type == "share_out":
            counts[article_id]["share_count"] = cnt
    return counts


# ── Feed ──────────────────────────────────────────────────────────────────────

def get_news_feed(
    db: Session,
    user_id: UUID,
    state: str = "",
    scope: str = "national",
) -> FeedResponse:
    role, commodities = _get_user_context(db, user_id)
    _ensure_cold_start(db, user_id, role)
    weights = _taste_weights(db, user_id)
    cutoff  = datetime.now(timezone.utc) - timedelta(hours=RECENCY_CUTOFF_H)

    candidates = (
        db.query(NewsArticle)
        .options(joinedload(NewsArticle.source))
        .filter(
            NewsArticle.published_at >= cutoff,
            NewsArticle.is_archived == False,       # noqa: E712
            NewsArticle.is_classified == True,      # noqa: E712
        )
        .order_by(NewsArticle.published_at.desc())
        .limit(500)
        .all()
    )

    primary_commodity = commodities[0] if commodities else "general"
    segment_id = f"{role}:{primary_commodity}:{state}"

    trending_rows = (
        db.query(NewsTrending)
        .filter(NewsTrending.segment_id == segment_id)
        .order_by(NewsTrending.velocity_score.desc())
        .limit(20)
        .all()
    )
    trending_ids = {r.article_id for r in trending_rows}

    candidate_ids = [a.id for a in candidates]
    liked_ids = _engagement_ids(db, user_id, candidate_ids, "like")
    saved_ids = _engagement_ids(db, user_id, candidate_ids, "save")
    counts    = _fetch_counts(db, candidate_ids)

    scored = sorted(
        [
            (s, a)
            for a in candidates
            if (s := _compute_score(a, role, commodities, state, scope, weights, trending_ids)) > 0
        ],
        key=lambda x: x[0],
        reverse=True,
    )

    used: set = set()

    def _pick(predicate, limit) -> list[ArticleOut]:
        out = []
        for _, a in scored:
            if len(out) >= limit:
                break
            if a.id not in used and predicate(a):
                out.append(_article_out(a, liked_ids, saved_ids, counts))
                used.add(a.id)
        return out

    breaking = _pick(
        lambda a: (a.cluster_id or 0) in BREAKING_CLUSTERS
        and (a.severity or 0) >= BREAKING_SEVERITY_THRESHOLD,
        FEED_BREAKING_COUNT,
    )
    for_you    = _pick(lambda _: True, FEED_FOR_YOU_COUNT)
    worth      = _pick(lambda a: 4.0 <= (a.severity or 0) <= 7.9, FEED_WORTH_KNOWING_COUNT)

    # Trending section: pull from pre-computed trending table
    trending_out: list[ArticleOut] = []
    article_map = {a.id: a for _, a in scored}
    for row in trending_rows:
        if len(trending_out) >= FEED_TRENDING_COUNT:
            break
        a = article_map.get(row.article_id)
        if a and a.id not in used:
            trending_out.append(_article_out(a, liked_ids, saved_ids, counts))
            used.add(a.id)

    # Government section: separate query so it always has content
    govt_filter = [
        NewsArticle.published_at >= cutoff,
        NewsArticle.is_archived == False,       # noqa: E712
        NewsSource.category == "government",
    ]
    if used:
        govt_filter.append(NewsArticle.id.notin_(used))

    govt_articles = (
        db.query(NewsArticle)
        .options(joinedload(NewsArticle.source))
        .join(NewsSource, NewsArticle.source_id == NewsSource.id)
        .filter(*govt_filter)
        .order_by(NewsArticle.published_at.desc())
        .limit(FEED_GOVERNMENT_COUNT)
        .all()
    )
    govt_out = [_article_out(a, liked_ids, saved_ids, counts) for a in govt_articles]

    return FeedResponse(
        sections=[
            FeedSection(key="right_now",     label="Right Now",                articles=breaking),
            FeedSection(key="for_you_today", label="For You Today",            articles=for_you),
            FeedSection(key="trending",      label="Trending in Your Network", articles=trending_out),
            FeedSection(key="worth_knowing", label="Worth Knowing",            articles=worth),
            FeedSection(key="government",    label="From Government Sources",  articles=govt_out),
        ]
    )


# ── Single article ────────────────────────────────────────────────────────────

def get_article(db: Session, article_id: UUID, user_id: UUID | None) -> ArticleOut:
    article = (
        db.query(NewsArticle)
        .options(joinedload(NewsArticle.source))
        .filter(NewsArticle.id == article_id)
        .first()
    )
    if not article:
        raise NewsNotFoundError("Article not found")

    liked = saved = set()
    if user_id:
        liked = _engagement_ids(db, user_id, [article_id], "like")
        saved = _engagement_ids(db, user_id, [article_id], "save")
    counts = _fetch_counts(db, [article_id])
    return _article_out(article, liked, saved, counts)


# ── Search ────────────────────────────────────────────────────────────────────

def search_news(
    db: Session,
    q: str,
    commodity: str | None,
    page: int,
    per_page: int,
) -> list[ArticleOut]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=RECENCY_CUTOFF_H)
    query  = (
        db.query(NewsArticle)
        .options(joinedload(NewsArticle.source))
        .filter(
            NewsArticle.is_archived == False,   # noqa: E712
            NewsArticle.published_at >= cutoff,
        )
    )
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(
            (NewsArticle.title.ilike(like)) | (NewsArticle.summary.ilike(like))
        )
    if commodity:
        query = query.filter(
            NewsArticle.commodities.any(commodity.lower())
        )
    articles = (
        query.order_by(NewsArticle.published_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return [_article_out(a, set(), set()) for a in articles]


# ── Engagement ────────────────────────────────────────────────────────────────

VALID_ACTIONS = {
    "view", "click", "dwell", "like", "save", "comment",
    "share_in", "share_out", "skip",
}


def record_engagement(
    db: Session,
    user_id: UUID,
    article_id: UUID,
    action_type: str,
    dwell_time_s: int | None,
    comment_text: str | None,
    segment_id: str | None,
) -> None:
    if action_type not in VALID_ACTIONS:
        raise NewsValidationError(f"Invalid action_type: {action_type}")

    article = db.query(NewsArticle).filter(NewsArticle.id == article_id).first()
    if not article:
        raise NewsNotFoundError("Article not found")

    db.add(
        NewsEngagement(
            user_id=user_id,
            article_id=article_id,
            action_type=action_type,
            cluster_id=article.cluster_id,
            segment_id=segment_id,
            dwell_time_s=dwell_time_s,
            comment_text=comment_text if action_type == "comment" else None,
        )
    )
    db.commit()


# ── Like / Save toggles ───────────────────────────────────────────────────────

def _toggle_action(db: Session, user_id: UUID, article_id: UUID, action: str):
    if not db.query(NewsArticle.id).filter(NewsArticle.id == article_id).first():
        raise NewsNotFoundError("Article not found")

    existing = (
        db.query(NewsEngagement)
        .filter(
            NewsEngagement.user_id == user_id,
            NewsEngagement.article_id == article_id,
            NewsEngagement.action_type == action,
        )
        .first()
    )
    if existing:
        db.delete(existing)
        db.commit()
        return False
    db.add(NewsEngagement(user_id=user_id, article_id=article_id, action_type=action))
    db.commit()
    return True


def toggle_like(db: Session, user_id: UUID, article_id: UUID) -> LikeToggleOut:
    liked = _toggle_action(db, user_id, article_id, "like")
    like_count = db.query(func.count()).filter(
        NewsEngagement.article_id == article_id,
        NewsEngagement.action_type == "like",
    ).scalar() or 0
    return LikeToggleOut(liked=liked, like_count=like_count)


def toggle_save(db: Session, user_id: UUID, article_id: UUID) -> SaveToggleOut:
    return SaveToggleOut(saved=_toggle_action(db, user_id, article_id, "save"))


def share_article(db: Session, user_id: UUID, article_id: UUID) -> ShareOut:
    if not db.query(NewsArticle.id).filter(NewsArticle.id == article_id).first():
        raise NewsNotFoundError("Article not found")
    db.add(NewsEngagement(
        user_id=user_id,
        article_id=article_id,
        action_type="share_out",
    ))
    db.commit()
    share_count = db.query(func.count()).filter(
        NewsEngagement.article_id == article_id,
        NewsEngagement.action_type == "share_out",
    ).scalar() or 0
    return ShareOut(share_count=share_count)


# ── Comments ──────────────────────────────────────────────────────────────────

def post_comment(
    db: Session, user_id: UUID, article_id: UUID, text: str
) -> None:
    if not db.query(NewsArticle.id).filter(NewsArticle.id == article_id).first():
        raise NewsNotFoundError("Article not found")
    db.add(
        NewsEngagement(
            user_id=user_id,
            article_id=article_id,
            action_type="comment",
            comment_text=text,
        )
    )
    db.commit()


def get_comments(
    db: Session, article_id: UUID, page: int, per_page: int
) -> list[CommentOut]:
    rows = (
        db.query(NewsEngagement)
        .filter(
            NewsEngagement.article_id == article_id,
            NewsEngagement.action_type == "comment",
        )
        .order_by(NewsEngagement.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return [
        CommentOut(
            id=r.id,
            user_id=r.user_id,
            comment_text=r.comment_text,
            created_at=r.created_at,
        )
        for r in rows
    ]


# ── Taste profile ─────────────────────────────────────────────────────────────

def get_taste_profile(
    db: Session, user_id: UUID
) -> TasteProfileOut:
    role, _ = _get_user_context(db, user_id)
    _ensure_cold_start(db, user_id, role)
    rows = (
        db.query(UserClusterTaste)
        .filter(UserClusterTaste.user_id == user_id)
        .order_by(UserClusterTaste.cluster_id)
        .all()
    )
    clusters = [
        ClusterTasteOut(
            cluster_id=r.cluster_id,
            cluster_name=CLUSTER_NAMES.get(r.cluster_id, "Unknown"),
            taste_weight=r.taste_weight,
            interaction_count=r.interaction_count,
            avg_dwell_time=r.avg_dwell_time,
            is_seeded=r.is_seeded,
        )
        for r in rows
    ]
    return TasteProfileOut(user_id=user_id, clusters=clusters)


# ── Engagement history ────────────────────────────────────────────────────────

def get_engagement_history(
    db: Session,
    user_id: UUID,
    action_type: str | None,
    page: int,
    per_page: int,
) -> list[EngagementHistoryItem]:
    query = db.query(NewsEngagement).filter(NewsEngagement.user_id == user_id)
    if action_type:
        query = query.filter(NewsEngagement.action_type == action_type)
    rows = (
        query.order_by(NewsEngagement.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return [
        EngagementHistoryItem(
            id=r.id,
            article_id=r.article_id,
            action_type=r.action_type,
            segment_id=r.segment_id,
            dwell_time_s=r.dwell_time_s,
            created_at=r.created_at,
        )
        for r in rows
    ]
