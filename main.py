from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from app.modules.auth.router import router as auth_router
from app.modules.profile.router import router as profile_router
from app.modules.groups.router import router as groups_router
from app.modules.post.router import router as post_router
from app.modules.connections.router import (
    connections_router,
    recommendations_router,
)

app = FastAPI(title="Vanijyaa API")

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
