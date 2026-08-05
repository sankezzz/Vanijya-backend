# 26 — Deployment

This app deploys to **Render** (render.com), a platform-as-a-service that builds and runs an app directly from a connected GitHub repository — push to the configured branch, Render rebuilds and redeploys automatically. There is no separate CI pipeline, no Dockerfile, and no staging environment defined anywhere in this repository — everything about how this app runs in production is either in one 10-line file, or configured by hand in Render's own dashboard, outside of version control entirely.

## `render.yaml`, in full

```yaml
services:
  - type: web
    name: vanijyaa-backend
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: DATABASE_URL
        sync: false
      - key: ENVIRONMENT
        value: production
```
- **`env: python`** — Render's native Python buildpack, not a custom Docker image. There is no `Dockerfile` anywhere in this repository (confirmed by a direct search) — Render installs Python itself and just runs the build/start commands below.
- **`buildCommand: pip install -r requirements.txt`** — no separate lint step, no type-check step, no test run. Whatever `pip install` can successfully install is what ships.
- **`startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT`** — this is the single line that makes this app's single-worker deployment a deployed *fact*, not just a recommendation. There is no `--workers N` flag, so Uvicorn runs its default of exactly one worker process. Every "this only works because we're single-worker" note elsewhere in this handbook — [Runtime Architecture](06_Runtime_Architecture.md)'s chat presence dict, [Redis](17_Redis.md) and [Event Flows](20_Event_Flows.md)'s Socket.IO room registry — is true in production specifically because this line has never had a `--workers` flag added to it. Adding one without also moving the affected in-memory state to Redis (as `connection_manager.py`'s own docstring recommends) would silently break all of those features, not error out — worth remembering before ever "just" scaling this up for more throughput.
- **`$PORT`** — Render assigns this dynamically per-deploy; the app doesn't choose its own port.

## The `envVars` block only covers two of everything this app actually needs

`render.yaml` declares exactly two environment variables: `DATABASE_URL` (marked `sync: false`, meaning Render expects this to be set by hand in its dashboard rather than auto-populated from a linked resource) and a hardcoded `ENVIRONMENT: production`. [Configuration](24_Configuration.md) catalogs a much longer real list — every `Settings` field plus every raw `os.getenv`/`os.environ` read scattered across the codebase. None of the rest (`SYNC_DATABASE_URL`, `REDIS_URL`, `JWT_SECRET_KEY`, `DATABASE_STORAGE_URL`, `DATABASE_SERVICE_KEY`, the per-bucket overrides, `GNEWS_API_KEY`, `GROQ_API_KEY`, `SUREPASS_TOKEN`, `SENTRY_DSN`, and more) appear in this file at all — they must already be configured directly in Render's dashboard for this specific service, invisibly to anyone who only reads the tracked repository. A new engineer trying to stand up a second Render service from this file alone, expecting it to name everything required, would hit a wall of missing-variable failures the moment the app tried to start — [Configuration](24_Configuration.md)'s full table is the closest thing this repository has to the checklist `render.yaml` doesn't provide. **Not verified from the current implementation:** the actual current values configured in Render's dashboard — this handbook has no access to that, by design (secrets aren't and shouldn't be in the tracked repo).

## No CI, no automated gate before a deploy

There's no `.github/workflows/` directory, no other CI configuration file, and no `Dockerfile` anywhere in this repository. The only thing standing between a `git push` and a live deploy is Render's own build step succeeding — `pip install -r requirements.txt` completing without error, followed by `uvicorn main:app` actually starting. That second half matters more than it might sound: [Startup Process](05_Startup_Process.md) already established that importing `main.py` transitively imports this app's entire `app/modules/` tree, which means a single missing required environment variable (`shared/utils/storage.py`'s Supabase credentials, `Settings`' required `DATABASE_URL`/`SYNC_DATABASE_URL` fields) fails the *whole* app at this exact step — there is no partial deploy, no per-feature rollback, just the entire service failing to come up. Combined with the prior audit's finding that this app's test suite currently can't run at all (P1-F2, `pytest` is not declared in `requirements.txt` — reconfirmed by this handbook: still absent), there is genuinely no automated check of any kind between a commit and it running in production. Whatever confidence exists that a change is safe has to come from manual testing before the push.

## What the root endpoint is actually for

`GET /` (defined directly in `main.py`, per [Startup Process](05_Startup_Process.md)) serves double duty: it's the conventional health-check endpoint a platform like Render can poll to decide whether a deploy succeeded and the service is alive, and it's also the exact URL [Background Jobs](18_Background_Jobs.md)'s `server.keepalive` job pings every 10 minutes from inside the app itself, to keep the service from being treated as idle. Both uses depend on this one route doing nothing more than confirming "the process is up" — it doesn't touch the database, Redis, or any external service, so it stays reliable even if one of those dependencies is degraded.

## `requirements.txt` — a couple of things worth knowing

`uvicorn` is listed with no version pin (just `uvicorn`, no `==x.y.z`) — a fresh deploy today could pick up a newer Uvicorn release than whatever was last tested locally, silently. `pytest` remains absent, as noted above. There's no `requirements-dev.txt` or extras split — whatever's needed to run the app in production and whatever might be needed for local development/testing both would have to live in the same single file, if the latter existed at all.

---
**Previous:** [25 — Error Handling](25_Error_Handling.md) · **Next:** [27 — Glossary](27_Glossary.md)
