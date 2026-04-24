from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str          # postgresql+asyncpg://...
    SYNC_DATABASE_URL: str     # postgresql+psycopg2://...
    REDIS_URL: str = "redis://localhost:6379/0"

    # Auth — Firebase Phone Auth (OTP sent client-side, backend only verifies ID token)
    GOOGLE_SERVICE_ACCOUNT_JSON: Optional[str] = None  # set in production; dev falls back to service.json

    # Gemini
    GEMINI_API_KEY: Optional[str] = None

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
