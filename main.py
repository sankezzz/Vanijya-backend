from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager
from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler

from app.modules.auth.router import router as auth_router
from app.modules.profile.router import router as profile_router
from app.modules.groups.router import router as groups_router
from app.modules.post.router import router as post_router
from app.modules.connections.router import (
    connections_router,
    recommendations_router,
)
from app.modules.news.router import router as news_router
from app.modules.news.tasks import ingest, recalc_trending, update_taste, archive_old


scheduler = BackgroundScheduler(timezone="Asia/Kolkata")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── News background tasks ────────────────────────────────────────────────
    scheduler.add_job(ingest,          "interval", minutes=20,  id="news.ingest")
    scheduler.add_job(recalc_trending, "interval", minutes=5,   id="news.trending")
    scheduler.add_job(update_taste,    "interval", hours=1,     id="news.taste")
    scheduler.add_job(archive_old,     "cron",     hour=2,      id="news.archive")

    scheduler.start()

    # Run ingest once immediately so there are articles on first boot
    ingest()

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

# Connections module
app.include_router(connections_router)
app.include_router(recommendations_router)

# News module
app.include_router(news_router)
