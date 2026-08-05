# 24 — Configuration

This app reads configuration — API keys, database URLs, feature toggles — from environment variables, loaded from a local `.env` file in development (never committed; see [Repository Tour](03_Repository_Tour.md)) and from the hosting platform's own environment variable settings in production ([Deployment](26_Deployment.md)). **How that reading actually happens is inconsistent across the codebase — three different mechanisms coexist**, and this chapter is the complete map of which config value goes through which one, verified directly rather than assumed, since getting this wrong is exactly the kind of thing that produces a confusing, hard-to-diagnose failure the first time someone forgets a value in a new environment.

## Strategy 1 — the real `Settings` class (the correct, intended way)

`app/core/config.py` defines a `pydantic-settings` `BaseSettings` subclass — a typed, validated config object, populated automatically from environment variables (falling back to `.env` if a variable isn't already set in the process environment) and instantiated once at import time as the module-level `settings` object:
```python
class Settings(BaseSettings):
    DATABASE_URL: str          # required — no default, Settings() raises if missing
    SYNC_DATABASE_URL: str     # required
    REDIS_URL: str = "redis://localhost:6379/0"
    GOOGLE_SERVICE_ACCOUNT_JSON: Optional[str] = None
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 600
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    GEMINI_API_KEY: Optional[str] = None
    GNEWS_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    SENTRY_DSN: Optional[str] = None
    ENVIRONMENT: str = "development"
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1
    SENTRY_PROFILES_SAMPLE_RATE: float = 0.1

    class Config:
        env_file = ".env"
        extra = "ignore"
```
This is the pattern to use for any new configuration value: add a typed field here, import `settings` where it's needed, get validation (a `str`-typed required field with no default fails loudly, at startup, if unset) and a single source of truth for free. **`extra = "ignore"`** is worth knowing about specifically: an environment variable that doesn't match any declared field name is silently ignored rather than raising — so a typo in a `.env` key name (meant to satisfy a field that *does* exist) fails as "field is missing" rather than "did you mean...", with no hint pointing at the typo itself.

**A field declared here whose only real consumer is dead code:** `DATABASE_URL` (the `asyncpg`-flavored one, per its own comment) is a required field — `Settings()` will refuse to start without it — but the only place in the entire codebase that reads `settings`-equivalent value for it is `app/modules/connections/db/postgres.py`, part of the dead Connections prototype package the audit identified (P4-F1, not reachable from `main.py` — see [Modules](11_Modules.md)). Every live database access in this app goes through `SYNC_DATABASE_URL` instead (`app/core/database/session.py:7`). This means a real `.env` value is required for something nothing running actually uses — removing it would be safe today, but only because the thing that used to need it is already dead, not because the field was ever cleaned up alongside it.

## Strategy 2 — raw `os.getenv()` / `os.environ[...]`, bypassing `Settings` entirely

Nine live files read configuration directly from the process environment, never touching the `Settings` class at all:

| Variable | File | Default if unset | Consequence if unset |
|---|---|---|---|
| `DATABASE_STORAGE_URL`, `DATABASE_SERVICE_KEY` | `shared/utils/storage.py` | None — bracket access (`os.environ[...]`) | **Raises immediately at import time** — see [Startup Process](05_Startup_Process.md)'s P3-F4 |
| `JWT_SECRET_KEY` | `core/security/jwt_handler.py` | None | Fails the first time a token is created or decoded, not at startup |
| `JWT_ALGORITHM` | same file | `"HS256"` | Silently uses the default |
| `SUREPASS_TOKEN` | `verification/service.py` | None | Fails the first time a KYC/KYB call is made |
| `SUREPASS_BASE_URL` | same file | sandbox URL | Silently talks to Surepass's sandbox instead of production if forgotten |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | `auth/service.py` | None | See below — **this one is also a declared `Settings` field, read a second, different way** |
| `DEBUG` | `auth/router.py` | `""` (falsy) | Governs whether `/auth/dev-token` is reachable — see [Authentication](14_Authentication.md) |
| `DATABASE_STORAGE_BUCKET` | `profile/service.py` | `"avatars"` | Silent fallback |
| `POST_STORAGE_BUCKET` | `post/service.py` | `"posts"` | Silent fallback |
| `GROUP_IMAGE_BUCKET`, `GROUP_MEDIA_BUCKET` | `groups/service.py` | `"group-image"`, `"group-media"` | Silent fallback |
| `CHAT_STORAGE_BUCKET` | `chat/service.py` **and, separately,** `chat/data/repository.py` | `"chat"` (both places) | Silent fallback — and read independently in two files with the identical hardcoded default, rather than once |

**The cleanest single illustration of why having two strategies is a real problem, not just a style inconsistency:** `GOOGLE_SERVICE_ACCOUNT_JSON` is declared as a proper, typed, optional field on `Settings` (`core/config.py:12`) — and also read directly via `os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")` in `auth/service.py:27`, completely independently of the `Settings` object. Both read the same underlying environment variable today, so this happens not to have caused a live bug — but it means there are two separate places in the codebase that would need to be found and changed if this value's handling ever needed to change (a default, a validation rule, a rename), and nothing enforces that they'd be changed together.

## Strategy 3 — a second, entirely dead `Settings` class

`app/config.py` (top-level, **not** inside `app/core/`) defines its own, completely separate `class Settings(BaseSettings)`, with its own smaller set of fields (`DATABASE_URL`, `SECRET_KEY`, `ENVIRONMENT`) and its own module-level `settings = Settings()`. This handbook confirmed, by grepping the entire `app/` tree for any import of `app.config` or `from app import config`, that **nothing imports this file at all.** It has no functional effect on the running app — but it's a real navigation hazard: searching the codebase for `class Settings` returns two matches in two similarly-purposed-sounding files (`app/config.py` and `app/core/config.py`), and only one of them is the one actually wired into everything else. If you're ever tracing a configuration value and land in `app/config.py`, that's the wrong file — the real one is one directory level deeper, under `core/`.

## Three different failure modes when a value is missing — worth telling apart

Not every missing environment variable fails the same way, and knowing which category a given value falls into changes how you'd debug it:

1. **Hard, at startup, whole app down** — a required `Settings` field (`DATABASE_URL`, `SYNC_DATABASE_URL`) or a bracket-accessed `os.environ[...]` read at module level (`storage.py`'s Supabase credentials). Both fail the instant the relevant module is imported, which — per [Startup Process](05_Startup_Process.md) — happens transitively for *all* of these the moment `main.py` starts, regardless of whether the request that would have needed that value ever arrives.
2. **Soft, on first use, one feature down** — `os.getenv(...)` with no default, read inside a function body rather than at module level (`JWT_SECRET_KEY`, `SUREPASS_TOKEN`). The app starts fine; the failure only surfaces the first time someone tries to log in, or the first time a KYC call is attempted.
3. **Silent, wrong environment, nothing visibly fails** — any `os.getenv(...)`/`os.environ.get(...)` call with a default value. The app starts, the feature works, but possibly against the wrong backend entirely (Surepass's sandbox instead of production being the clearest example) — this category produces no error at all, which makes it the hardest of the three to catch.

If you're adding a new required piece of configuration, prefer category 1 via a real `Settings` field with no default — it's the loudest, earliest, and most consistent failure mode, and it's the one this codebase already has a working, typed mechanism for.

---
**Previous:** [23 — Notifications](23_Notifications.md) · **Next:** [25 — Error Handling](25_Error_Handling.md)
