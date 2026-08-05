# 04 — Folder Structure

A dense, scannable reference tree. For the narrated, explained version of this same information, read [Repository Tour](03_Repository_Tour.md) first — this page assumes you already have that context and just want to look something up quickly.

## Full `app/` tree, annotated

```text
app/
├── config.py                          # DEAD — orphaned Settings class, zero importers. Do not use. (audit P1-F1)
├── dependencies.py                    # Shared FastAPI dependencies: get_db, get_current_user, get_current_user_id,
│                                       #   get_current_profile_id, get_onboarding_user_id, get_onboarding_claims
│
├── core/                              # Infrastructure every feature depends on
│   ├── config.py                      # THE real Settings class (env vars) — see Configuration
│   ├── database/
│   │   ├── base.py                    # SQLAlchemy declarative Base — every model inherits from this
│   │   └── session.py                 # Sync engine + SessionLocal (session factory)
│   ├── security/
│   │   └── jwt_handler.py             # Create/decode access + onboarding JWTs
│   ├── redis_client.py                # Shared Redis client (lazy singleton)
│   ├── rate_limiter.py                # Sliding-window limiter — built, but zero call sites anywhere (audit P1-F4)
│   ├── scheduler.py                   # APScheduler job registration — see Background Jobs
│   └── monitoring.py                  # Sentry init + per-module tagging middleware
│
├── shared/
│   └── utils/
│       ├── response.py                # ok(data, message) — the standard response envelope
│       └── storage.py                 # Shared Supabase Storage helpers (signed URLs, delete, exists-check)
│
└── modules/                            # One folder per feature — see Modules for full detail on each
    ├── auth/                          # Phone OTP verification, session/token issuance
    │   ├── router.py                  # /auth/*
    │   ├── service.py                 # Firebase verification, session create/refresh/revoke
    │   ├── service_msg91.py           # DEAD — alternate SMS-OTP path, would crash if called (audit P2-F1)
    │   ├── models.py                  # UserSession
    │   └── schemas.py
    │
    ├── profile/                       # User + Profile + Business + reference data (Role/Commodity/Interest)
    │   ├── router.py                  # /profile/*
    │   ├── service.py
    │   ├── models.py                  # User, Profile, Business, Role, Commodity, Interest, junction tables,
    │   │                               #   UserEmbedding (pgvector)
    │   └── schemas.py
    │
    ├── connections/                   # Follow graph, message requests, user search, pgvector recommendations
    │   ├── router.py                  # THE live router — /connections/*, /recommendations/*
    │   ├── service.py                 # THE live service
    │   ├── models.py                  # UserConnection, MessageRequest
    │   ├── schemas.py
    │   ├── weights_config.py          # Vector-encoding weight constants, shared with profile/groups
    │   ├── encoding/vector.py         # build_query_vector / build_candidate_vector — shared vector encoders
    │   ├── routes/                    # DEAD — first-generation prototype, int IDs, never mounted (audit P4-F1)
    │   └── db/                        # DEAD — own DB engine + ChromaDB code, only used by routes/ above
    │
    ├── groups/                        # Communities: membership, deals, join requests, invite links, suggestions
    │   ├── router.py                  # /api/v1/groups/*
    │   ├── service.py
    │   ├── models.py                  # Group, GroupMember, GroupActivityCache, GroupEmbedding, GroupMedia,
    │   │                               #   GroupDeal, GroupJoinRequest, PersonalDeal
    │   ├── schemas.py
    │   └── vector.py                  # Group embedding + activity-blended scoring
    │
    ├── chat/                          # Direct + group messaging (layered/"clean architecture" style)
    │   ├── presentation/
    │   │   ├── router.py              # /chat/* (does NOT use the ok() envelope — see Known Limitations)
    │   │   ├── connection_manager.py  # Socket.IO server + real-time emit helpers (single-worker only, self-documented)
    │   │   ├── dependencies.py        # DI wiring for use cases
    │   │   └── schema.py
    │   ├── domain/
    │   │   ├── entities.py            # Pure dataclasses — Conversation/Message/Snap shapes
    │   │   └── use_cases.py           # Business rules — contains disabled block-check, see Authorization
    │   ├── data/
    │   │   ├── models.py              # Conversation, ConversationMember, Message, ChatAttachment
    │   │   └── repository.py          # ChatRepository — all DB access
    │   └── service.py                 # Media upload/delete (Supabase)
    │
    ├── post/                          # Posts, feeds, and two nested sub-features
    │   ├── router.py                  # /posts/*
    │   ├── service.py
    │   ├── models.py                  # Post, PostCategory, PostDealDetails, PostView/Like/Comment/Share/Save
    │   ├── schemas.py
    │   ├── post_recommendation_module/   # pgvector ANN recommendation feed for posts
    │   │   ├── router.py              # /posts/recommendation/* — includes UNAUTHENTICATED job-trigger endpoints
    │   │   │                          #   (audit P13-F1 — treat as a real gap, not a documentation nitpick)
    │   │   ├── service.py, models.py, jobs.py, vector.py, constants.py
    │   └── post_user_interaction/        # Interaction-event batching + persistent taste storage
    │       ├── router.py              # /posts/interactions/* — same unauthenticated-job-endpoint issue
    │       └── service.py, taste_service.py, models.py, jobs.py, constants.py
    │
    ├── news_new/                      # News ingestion, AI enrichment, and news feeds
    │   ├── config.py                  # Category/status constants, role-relevance matrix
    │   ├── ingestion/                 # Fetch from GNews, normalize, store as RawArticle
    │   │   └── router.py              # /news/admin/* — "admin" endpoints gated only by login, no real admin check (audit P8-F1)
    │   ├── intelligence/              # Groq LLM enrichment → EnrichedArticle
    │   ├── news_recommendation_engine/   # MOSTLY DEAD (audit P8-F2: service.py/router.py/models.py unused, 2 orphan DB tables) — EXCEPT profile_scorer.py, which feed/service.py imports and actively uses (verified post-audit; see Recommendation Engine doc)
    │   ├── news_user_interaction/     # Likes/saves/shares/views + persistent taste (read path also dead, audit P10-F2)
    │   └── feed/                      # THE live feed-serving code — /news/feed, /news/trending, etc.
    │
    ├── feed/                          # The Home Feed — blends posts + news + groups + connections into one feed
    │   ├── router.py                  # /feed/home, /feed/engagement (a confirmed no-op — audit P9-F2)
    │   ├── service.py                 # Orchestrates the 4 source pipelines + the mixer
    │   ├── pipelines.py                # Thin adapters calling each feature's own recommender
    │   ├── mixer.py                    # Weighted-random slot assignment with per-type consecutive caps
    │   ├── priority.py                 # "Priority pins" (unseen followed posts; breaking news is a stub)
    │   └── session_taste.py           # DEAD — a full session-taste engine with zero callers (audit P9-F1)
    │
    ├── taste/                         # The cross-module recommendation "taste" system (see Recommendation Engine)
    │   ├── amplify.py                 # Public glue API other modules call into
    │   ├── global_session/            # Layer 2 — Redis, cross-module, 1-day TTL
    │   ├── global_taste/              # Layer 3 — PostgreSQL, no TTL, slow decay
    │   └── session_taste/             # Layer 1 — Redis, per-module, 2h TTL
    │
    ├── safety/                        # Block + report
    │   └── router.py                  # /safety/* (does NOT use the ok() envelope — see Known Limitations)
    │
    ├── verification/                  # KYC (PAN) / KYB (GST, IEC) via Surepass
    │   └── router.py                  # /verification/*
    │
    └── deeplink/                      # Public, unauthenticated shareable-link generation
        └── router.py                  # /share/*
```

## Everything outside `app/`

```text
backend/
├── main.py                 # Entry point — builds the FastAPI app, mounts every router + Socket.IO
├── alembic/                # Database migration history (see Database Guide)
│   ├── env.py
│   └── versions/           # ~47 migration files, one per schema change
├── alembic.ini
├── requirements.txt        # Python dependencies (pytest is NOT listed — see Known Limitations)
├── render.yaml             # Deployment config for Render.com (see Deployment)
├── .env                    # Local secrets/config — gitignored, never committed
├── service.json            # Firebase service-account credentials (local-dev fallback) — gitignored
├── tests/                  # Automated test suite — see Known Limitations for its current broken state
├── scripts/                 # Gitignored — mix of real one-off maintenance scripts and 3 dead news-feature prototypes
├── TESTING/                 # Gitignored — a couple of manual, ad-hoc upload test scripts
├── uploads/avatars/          # Vestigial — not referenced by any current code path
├── documentation/           # Large pre-existing doc set — use with caution, drifts from current code in places
├── upgraded_documentation/   # A second pre-existing doc set — same caution
├── audit/                   # The completed architectural audit (14 phases + final report)
└── audits/                  # This handbook (you are here)
```

## Quick answers to "where is...?"

| I'm looking for... | Go to |
|---|---|
| An HTTP endpoint | `app/modules/<feature>/router.py` (or `presentation/router.py` for Chat) |
| The business logic behind an endpoint | `app/modules/<feature>/service.py` |
| A database table definition | `app/modules/<feature>/models.py` — full index in [Database Guide](09_Database_Guide.md) |
| Request/response validation shapes | `app/modules/<feature>/schemas.py` |
| How login/tokens work | `app/core/security/jwt_handler.py`, `app/modules/auth/` |
| How a background job is scheduled | `app/core/scheduler.py` |
| Redis usage for a specific feature | `app/modules/taste/` (recommendations), `app/modules/connections/service.py` (seen-sets), `app/modules/chat/presentation/connection_manager.py` (presence) |
| Environment variables / settings | `app/core/config.py`, and [Configuration](24_Configuration.md) |

---
**Previous:** [03 — Repository Tour](03_Repository_Tour.md) · **Next:** [05 — Startup Process](05_Startup_Process.md)
