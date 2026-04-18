"""
Background tasks for the news module.

These are plain async functions. Wire them up to your scheduler of choice
(Celery Beat, APScheduler, cron, etc.).

Suggested schedule
──────────────────
ingest()              every 20 min
recalc_trending()     every  5 min
update_taste()        every  1 hour
archive_old()         daily at 02:00 IST  (20:30 UTC)

External requirement: GEMINI_API_KEY in .env (falls back to keyword rules if absent).
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from math import log1p

import google.auth  # used in _get_client via google.auth.default()
from google import genai
from sqlalchemy.orm import Session
import requests

from app.core.database.session import SessionLocal
from app.modules.news.models import (
    NewsArticle,
    NewsEngagement,
    NewsSource,
    NewsTrending,
    UserClusterTaste,
)
from app.modules.news.weights_config import (
    ACTION_WEIGHTS,
    ARCHIVE_AFTER_DAYS,
    DWELL_THRESHOLD_S,
    PUSH_BREAKING_LOOKBACK_H,
    TASTE_LOOKBACK_H,
    TRENDING_LOOKBACK_H,
    TRENDING_MIN_SEVERITY,
    TRENDING_MIN_UNIQUE_USERS,
    BREAKING_CLUSTERS,
    BREAKING_SEVERITY_THRESHOLD,
)

log = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.5-flash-lite"
GEMINI_SA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "service.json",
)
GEMINI_SCOPES = ["https://www.googleapis.com/auth/generative-language"]

_gemini_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        if sa_json:
            # Render / production: credentials stored as env var
            from google.oauth2.service_account import Credentials
            creds = Credentials.from_service_account_info(
                json.loads(sa_json), scopes=GEMINI_SCOPES
            )
        else:
            # Local dev: fall back to service.json file
            os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", GEMINI_SA_PATH)
            creds, _ = google.auth.default(scopes=GEMINI_SCOPES)
        _gemini_client = genai.Client(credentials=creds)
    return _gemini_client

GEMINI_SYSTEM_PROMPT = """
You are a commodity-news classifier for an Indian agricultural trading platform.
Given a news article title and content, return ONLY valid JSON with these fields:
{
  "cluster_id": <int 1-10>,
  "severity": <float 1.0-10.0>,
  "commodities": [<string>, ...],
  "regions": [<string>, ...],
  "scope": "<local|state|national|global>",
  "direction_tags": [<string>, ...],
  "horizon": "<immediate|short|medium|long>",
  "trader_impact": "<one sentence>",
  "broker_impact": "<one sentence>",
  "exporter_impact": "<one sentence>"
}

Clusters:
1=Policy & Regulation, 2=Geopolitical & Macro Shocks, 3=Supply-side Disruptions,
4=Financial & Market Mechanics, 5=Structural & Industrial Shifts,
6=Long-term Demand Trends, 7=Market Participation & Deal Flow,
8=Price Volatility & Sentiment, 9=Local Operational Events, 10=Indirect / General News
""".strip()


# ── Gemini classification ─────────────────────────────────────────────────────

def _keyword_classify(title: str, content: str) -> dict:
    """Fallback when Gemini is unavailable."""
    text = (title + " " + content).lower()
    if re.search(r"\b(ban|msp|tariff|subsidy|policy|regulation)\b", text):
        return {"cluster_id": 1, "severity": 7.0}
    if re.search(r"\b(war|sanction|geopolit|global crisis)\b", text):
        return {"cluster_id": 2, "severity": 7.5}
    if re.search(r"\b(monsoon|flood|drought|pest|supply shortage)\b", text):
        return {"cluster_id": 3, "severity": 7.0}
    if re.search(r"\b(mandi|apmc|price|rate|market)\b", text):
        return {"cluster_id": 8, "severity": 5.0}
    return {"cluster_id": 10, "severity": 3.0}


def classify_article(title: str, content: str) -> dict:
    sentences = ". ".join(content.split(". ")[:3]).strip() if content else ""
    snippet   = sentences[:400] if sentences else ""
    prompt    = f"{GEMINI_SYSTEM_PROMPT}\n\nTitle: {title}\n\nSnippet: {snippet}"

    try:
        client   = _get_client()
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        raw = response.text
        raw = re.sub(r"```(?:json)?", "", raw).strip().strip("`")
        return json.loads(raw)
    except Exception as exc:
        log.warning("Gemini classify failed (%s), using keyword fallback", exc)
        return _keyword_classify(title, content)


# ── RSS fetching ──────────────────────────────────────────────────────────────

def _parse_date(date_str: str | None) -> datetime:
    if not date_str:
        return datetime.now(timezone.utc)
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
    ):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(timezone.utc)


def fetch_rss(rss_url: str) -> list[dict]:
    try:
        resp = requests.get(rss_url, timeout=15, headers={"User-Agent": "VanijyaaBot/1.0"})
        resp.raise_for_status()
        text = resp.text
    except Exception as exc:
        log.warning("RSS fetch failed for %s: %s", rss_url, exc)
        return []

    items = []
    # supports RSS 2.0 and Atom 1.0 via simple regex (no lxml required)
    # RSS 2.0
    for m in re.finditer(r"<item>(.*?)</item>", text, re.S):
        block = m.group(1)
        title   = re.search(r"<title[^>]*><!\[CDATA\[(.*?)\]\]>|<title[^>]*>(.*?)</title>", block, re.S)
        link    = re.search(r"<link>(.*?)</link>|<guid[^>]*>(https?://[^<]+)</guid>", block, re.S)
        pub     = re.search(r"<pubDate>(.*?)</pubDate>", block, re.S)
        desc    = re.search(r"<description[^>]*><!\[CDATA\[(.*?)\]\]>|<description[^>]*>(.*?)</description>", block, re.S)
        if title and link:
            items.append({
                "title":        (title.group(1) or title.group(2) or "").strip(),
                "url":          (link.group(1) or link.group(2) or "").strip(),
                "content":      re.sub(r"<[^>]+>", "", (desc.group(1) or desc.group(2) or "") if desc else ""),
                "published_at": _parse_date(pub.group(1) if pub else None),
            })
    # Atom 1.0
    if not items:
        for m in re.finditer(r"<entry>(.*?)</entry>", text, re.S):
            block = m.group(1)
            title   = re.search(r"<title[^>]*>(.*?)</title>", block, re.S)
            link    = re.search(r'<link[^>]+href="([^"]+)"', block)
            pub     = re.search(r"<published>(.*?)</published>|<updated>(.*?)</updated>", block, re.S)
            summary = re.search(r"<summary[^>]*>(.*?)</summary>", block, re.S)
            if title and link:
                items.append({
                    "title":        re.sub(r"<[^>]+>", "", title.group(1)).strip(),
                    "url":          link.group(1).strip(),
                    "content":      re.sub(r"<[^>]+>", "", (summary.group(1) or "") if summary else ""),
                    "published_at": _parse_date((pub.group(1) or pub.group(2)) if pub else None),
                })
    return items


# ── Task: ingest ──────────────────────────────────────────────────────────────

def ingest() -> dict:
    """Fetch RSS feeds, classify with Gemini, upsert articles. Run every 20 min."""
    db: Session = SessionLocal()
    new_count = skipped = 0
    try:
        sources = (
            db.query(NewsSource).filter(NewsSource.is_active == True).all()  # noqa: E712
        )
        for source in sources:
            items = fetch_rss(source.rss_url)
            for item in items:
                url = item["url"]
                if not url:
                    continue
                if db.query(NewsArticle.id).filter(NewsArticle.url == url).first():
                    skipped += 1
                    continue

                classification = classify_article(item["title"], item["content"])
                time.sleep(6)  # stay under 10 req/min Gemini rate limit
                article = NewsArticle(
                    source_id=source.id,
                    title=item["title"],
                    content=item["content"] or None,
                    summary=(item["content"] or "")[:300] or None,
                    url=url,
                    published_at=item["published_at"].replace(tzinfo=None),
                    cluster_id=classification.get("cluster_id"),
                    severity=classification.get("severity"),
                    commodities=classification.get("commodities") or [],
                    regions=classification.get("regions") or [],
                    scope=classification.get("scope"),
                    direction_tags=classification.get("direction_tags") or [],
                    horizon=classification.get("horizon"),
                    trader_impact=classification.get("trader_impact"),
                    broker_impact=classification.get("broker_impact"),
                    exporter_impact=classification.get("exporter_impact"),
                    is_classified=True,
                )
                db.add(article)
                new_count += 1

        db.commit()
        log.info("ingest: new=%d skipped=%d", new_count, skipped)
        return {"new": new_count, "skipped": skipped}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ── Task: recalc_trending ─────────────────────────────────────────────────────

def recalc_trending() -> int:
    """Recompute velocity scores per segment. Run every 5 min."""
    db: Session = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=TRENDING_LOOKBACK_H)
        rows = (
            db.query(NewsEngagement)
            .join(NewsArticle, NewsEngagement.article_id == NewsArticle.id)
            .filter(
                NewsEngagement.created_at >= cutoff,
                NewsEngagement.segment_id.isnot(None),
                NewsArticle.severity >= TRENDING_MIN_SEVERITY,
            )
            .all()
        )

        # aggregate: {(segment_id, article_id): {users, score}}
        agg: dict[tuple, dict] = {}
        for row in rows:
            key = (row.segment_id, row.article_id)
            if key not in agg:
                agg[key] = {"users": set(), "score": 0.0}
            agg[key]["users"].add(row.user_id)
            weight = ACTION_WEIGHTS.get(row.action_type, 0)
            if row.action_type == "dwell" and (row.dwell_time_s or 0) <= DWELL_THRESHOLD_S:
                weight = 0
            agg[key]["score"] += weight

        # normalise and upsert
        upserted = 0
        for (seg_id, art_id), data in agg.items():
            unique = len(data["users"])
            if unique < TRENDING_MIN_UNIQUE_USERS:
                continue
            velocity = data["score"] / max(log1p(unique), 1.0)

            existing = (
                db.query(NewsTrending)
                .filter(
                    NewsTrending.segment_id == seg_id,
                    NewsTrending.article_id == art_id,
                )
                .first()
            )
            if existing:
                existing.velocity_score = velocity
                existing.unique_users   = unique
                existing.computed_at    = datetime.now(timezone.utc)
            else:
                db.add(
                    NewsTrending(
                        segment_id=seg_id,
                        article_id=art_id,
                        velocity_score=velocity,
                        unique_users=unique,
                    )
                )
            upserted += 1

        db.commit()
        log.info("recalc_trending: upserted=%d", upserted)
        return upserted
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ── Task: update_taste ────────────────────────────────────────────────────────

def update_taste() -> int:
    """Recompute user cluster taste weights from recent engagement. Run every 1 hr."""
    db: Session = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=TASTE_LOOKBACK_H)
        rows = (
            db.query(NewsEngagement)
            .filter(
                NewsEngagement.created_at >= cutoff,
                NewsEngagement.cluster_id.isnot(None),
            )
            .all()
        )

        # {user_id: {cluster_id: score}}
        scores: dict = {}
        for row in rows:
            uid = row.user_id
            cid = row.cluster_id
            weight = ACTION_WEIGHTS.get(row.action_type, 0)
            if row.action_type == "dwell" and (row.dwell_time_s or 0) <= DWELL_THRESHOLD_S:
                weight = 0
            scores.setdefault(uid, {}).setdefault(cid, 0)
            scores[uid][cid] += weight

        updated = 0
        for uid, cluster_scores in scores.items():
            max_score = max(cluster_scores.values()) if cluster_scores else 1.0
            for cid, raw_score in cluster_scores.items():
                normalised = log1p(raw_score) / max(log1p(max_score), 1.0)
                existing = (
                    db.query(UserClusterTaste)
                    .filter(
                        UserClusterTaste.user_id == uid,
                        UserClusterTaste.cluster_id == cid,
                    )
                    .first()
                )
                if existing:
                    existing.taste_weight      = round(normalised, 4)
                    existing.interaction_count = existing.interaction_count + 1
                    existing.is_seeded         = False
                    existing.updated_at        = datetime.now(timezone.utc)
                else:
                    db.add(
                        UserClusterTaste(
                            user_id=uid,
                            cluster_id=cid,
                            taste_weight=round(normalised, 4),
                            interaction_count=1,
                        )
                    )
                updated += 1

        db.commit()
        log.info("update_taste: rows_updated=%d", updated)
        return updated
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ── Task: archive_old ─────────────────────────────────────────────────────────

def archive_old() -> int:
    """Mark articles older than ARCHIVE_AFTER_DAYS as archived. Run daily."""
    db: Session = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=ARCHIVE_AFTER_DAYS)
        count = (
            db.query(NewsArticle)
            .filter(
                NewsArticle.published_at < cutoff,
                NewsArticle.is_archived == False,   # noqa: E712
            )
            .update({"is_archived": True})
        )
        db.commit()
        log.info("archive_old: archived=%d", count)
        return count
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ── Task: push_breaking ───────────────────────────────────────────────────────

def push_breaking() -> list[str]:
    """
    Identify breaking articles for push notification.
    TODO: integrate FCM / APNS once push credentials are available.
    Run every 5 min.
    """
    db: Session = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=PUSH_BREAKING_LOOKBACK_H)
        articles = (
            db.query(NewsArticle)
            .filter(
                NewsArticle.published_at >= cutoff,
                NewsArticle.cluster_id.in_(BREAKING_CLUSTERS),
                NewsArticle.severity >= BREAKING_SEVERITY_THRESHOLD,
                NewsArticle.is_archived == False,   # noqa: E712
            )
            .order_by(NewsArticle.severity.desc())
            .all()
        )
        ids = [str(a.id) for a in articles]
        if ids:
            log.info("push_breaking: %d eligible articles — %s", len(ids), ids)
        return ids
    finally:
        db.close()
