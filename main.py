from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager
from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler

from app.modules.auth.router import router as auth_router
from app.modules.profile.router import router as profile_router
from app.modules.groups.router import router as groups_router
from app.modules.post.router import router as post_router
from app.modules.post.post_recommendation_module.router import router as post_rec_router
from app.modules.post.post_recommendation_module import jobs as post_rec_jobs
from app.modules.connections.router import (
    connections_router,
    recommendations_router,
)
from app.modules.news.router import router as news_router
from app.modules.feed.router import router as feed_router
from app.modules.chat.presentation.router import router as chat_router
from app.modules.chat.presentation.ws_router import ws_router as chat_ws_router
from app.modules.deeplink.router import router as deeplink_router
from app.modules.news.tasks import ingest, recalc_trending, update_taste, archive_old
from app.core.database.session import SessionLocal


scheduler = BackgroundScheduler(timezone="Asia/Kolkata")


def _run_expiry_job():
    db = SessionLocal()
    try:
        post_rec_jobs.run_expiry_job(db)
    finally:
        db.close()


def _run_popular_sync():
    db = SessionLocal()
    try:
        post_rec_jobs.run_popular_posts_sync(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── News background tasks ────────────────────────────────────────────────
    scheduler.add_job(ingest,          "interval", minutes=20,  id="news.ingest")
    scheduler.add_job(recalc_trending, "interval", minutes=5,   id="news.trending")
    scheduler.add_job(update_taste,    "interval", hours=1,     id="news.taste")
    scheduler.add_job(archive_old,     "cron",     hour=2,      id="news.archive")

    # ── Post recommendation background tasks ─────────────────────────────────
    scheduler.add_job(_run_expiry_job,   "interval", hours=1,    id="posts.expiry")
    scheduler.add_job(_run_popular_sync, "interval", minutes=15, id="posts.popular")

    scheduler.start()

    # Run ingest once immediately so there are articles on first boot
    try:
        ingest()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Startup ingest failed (non-fatal): %s", exc)

    yield

    scheduler.shutdown()


app = FastAPI(title="Vanijyaa API", lifespan=lifespan)

# Auth module
app.include_router(auth_router)

# Profile module
app.include_router(profile_router)

# Groups module (CRUD + recommendations)
app.include_router(groups_router)

# Posts module
app.include_router(post_router)
app.include_router(post_rec_router)

# Connections module
app.include_router(connections_router)
app.include_router(recommendations_router)

# News module
app.include_router(news_router)

# Home Feed module
app.include_router(feed_router)

# Chat module
app.include_router(chat_router)
app.include_router(chat_ws_router)

# Deep link / share module
app.include_router(deeplink_router)
