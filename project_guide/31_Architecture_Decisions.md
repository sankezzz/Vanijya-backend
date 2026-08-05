# 31 — Architecture Decisions

This app has no `docs/adr/` folder or any written decision log — every entry below is **reconstructed from evidence**: code, comments, migration history, and (in the dead-prototype case) what was tried and abandoned. Where the reconstruction is a confident reading of an explicit code comment, that's noted. Where it's this handbook's own inference from an observed pattern with no comment explaining the "why," that's noted too — treat those as informed hypotheses, not confirmed history.

---

### ADR-1: Vector search lives inside Postgres (pgvector), not in a separate vector database

**Decision:** Every embedding-based similarity search (Post recommendations, Group suggestions, Connections' custom search) uses pgvector's native vector type and HNSW indexing, directly in the same PostgreSQL database as everything else.

**Evidence this was a considered choice, not just "the only thing anyone tried":** the dead Connections prototype (`connections/db/chromadb.py`, part of the ~895 dead lines documented in [Modules](11_Modules.md)) contains a `ChromaDB` client configuration — a genuine standalone vector database — with every line of the actual client construction commented out. A separate vector store was tried, at minimum scaffolded, and abandoned before the live rewrite, which uses pgvector exclusively.

**Reconstructed reasoning (not stated anywhere in code):** running vector search inside the same database as the rest of the app's relational data avoids operating, securing, and keeping a second database system in sync with the first — at the cost of Postgres-native vector search being less specialized than a dedicated vector database at very large scale. For this app's current size, that trade-off reads as a reasonable one.

**Status:** Settled — every live recommendation surface uses this approach consistently.

---

### ADR-2: Sync SQLAlchemy throughout, despite FastAPI being async-native

**Decision:** Every database interaction in this app — request-time and background-job — uses a synchronous SQLAlchemy `Session`, not the async engine/session SQLAlchemy also supports.

**Evidence:** `app/core/database/session.py`'s `SessionLocal` is a plain sync session factory; `get_db` (the FastAPI dependency almost every endpoint uses) yields one directly; every background job in [Background Jobs](18_Background_Jobs.md) calls `SessionLocal()` synchronously. `Settings.DATABASE_URL`'s own comment names an `asyncpg` driver — suggesting an async path may have been considered or partially started — but that field's only real consumer is the dead Connections prototype ([Configuration](24_Configuration.md)); the live app never uses it.

**Consequence, independently verified:** some `async def` route handlers call this synchronous, blocking database code directly, without FastAPI's automatic thread-pool offloading that a plain `def` handler gets for free — a detail [Runtime Architecture](06_Runtime_Architecture.md) flags with an explicit "not verified" caveat about its real-world performance impact, since this handbook has no access to production latency data.

**Reconstructed reasoning:** sync SQLAlchemy has a simpler mental model and, especially at the time much of this app was likely written, broader library/tooling support than the async variant. This is inference, not something any code comment confirms.

**Status:** Settled by consistency (100% of the codebase follows it) even though it was never revisited for the mixed `async def`-with-sync-DB-calls pattern that resulted.

---

### ADR-3: Two architectural styles coexist — flat by default, layered for `chat`/`taste`

**Decision:** Twelve of fourteen `app/modules/` packages use a flat `router.py`/`service.py`/`models.py` shape. Two — `chat/` and `taste/` — use a layered `domain/`/`application/`/`data/`/`presentation/` structure with genuine repository-pattern abstraction underneath.

**Evidence:** direct structure comparison across every module, detailed in [Modules](11_Modules.md), [Service Layer](12_Service_Layer.md), and [Repositories](13_Repositories.md).

**Reconstructed reasoning:** both `chat` and `taste` have a shape of complexity the other modules don't share as strongly — `chat` genuinely has multiple related but distinct operations (send, deliver, read-receipt, typing) sharing a lot of common data access, and `taste` genuinely has three swappable storage backends (module Redis, global Redis, persistent Postgres) behind one conceptual operation. The extra structure plausibly earns its cost specifically in those two cases; the audit's own Phase 10 read of `taste/` independently reached a similar conclusion, calling it "the most rigorously engineered and most rigorously self-verified module in the codebase."

**Status:** Settled as a working inconsistency — not something either style is expected to displace the other for, per [Service Layer](12_Service_Layer.md)'s explicit guidance to match whichever style a given module already uses.

---

### ADR-4: A three-layer, confidence-gated blend for personalization, instead of one taste score

**Decision:** A profile's inferred preference for a commodity/city/state is never one number — it's blended at read time from a fast/volatile Redis layer (module-scoped, 2h), a medium Redis layer (cross-module, 1 day), and a slow, permanent Postgres layer, weighted by how confidently each layer's evidence supports the value.

**Evidence this reasoning is explicit, not reconstructed:** the module-session repository's own docstring states the trade-off directly — module session loss on restart is "acceptable" specifically because it's meant to be volatile; `MergeWeights`' docstring names the exact formula and caps (persistent never below 54%, global never above 15%, module never above 31%). This is one of the few decisions in this codebase with its reasoning written down at the point of implementation, not just inferable from behavior.

**Status:** Settled, and actively extended — the city/state generalization this handbook verified during its own writing (see [Recommendation Engine](19_Recommendation_Engine.md)) is evidence the underlying architecture was built to accommodate new dimensions without a redesign, and that extension has already happened once.

---

### ADR-5: Direct-to-storage signed uploads, never proxying file bytes through the API

**Decision:** Every image/media upload (Profile, Post, Groups, Chat) issues a short-lived signed URL and lets the client upload directly to Supabase Storage — this app's own server never receives the file's bytes.

**Evidence:** the complete, consistent pattern documented in [Image Uploads](21_Image_Uploads.md), applied identically across all four modules that need file upload.

**Reconstructed reasoning:** proxying file bytes through an API server costs that server's own memory and bandwidth for every upload; a signed-URL approach avoids that cost entirely, at the price of a second request (fetch a URL, then upload) and the extra verification step (`object_exists`) needed because the server can no longer just observe the bytes arriving itself. The consistency of the pattern across four independently-implemented modules suggests this was a deliberate, copied convention, not four separate teams independently landing on the same idea by coincidence.

**Status:** Settled — no module uses a different upload strategy.

---

### ADR-6: Single-worker deployment, as a documented, temporary trade-off

**Decision:** This app runs as exactly one Uvicorn worker process (no `--workers` flag in `render.yaml`'s start command), and several features — chat presence, Socket.IO room membership — depend on that being true.

**Evidence this was a conscious, acknowledged trade-off rather than an oversight:** `connection_manager.py`'s own module docstring states the constraint explicitly (*"SINGLE-WORKER ONLY"*) **and** names the exact upgrade path if it's ever outgrown (`socketio.AsyncRedisManager`, moving `_sid_user` into Redis) — a level of self-documentation that reads as "we know, and here's how to fix it later," not "we didn't realize." See [Runtime Architecture](06_Runtime_Architecture.md) and [Event Flows](20_Event_Flows.md).

**Status:** Live in production as of this handbook's writing (`render.yaml` confirmed, no `--workers` flag) — the documented upgrade path has not yet been taken.

---

### ADR-7: Fire-and-forget for every secondary-system write

**Decision:** Every write to Redis for taste signals, and every real-time push over Socket.IO, is wrapped so its own failure can never break the primary action that triggered it (a like, a follow, a message send all succeed and commit to Postgres regardless of whether the accompanying Redis/socket call worked).

**Evidence:** `taste/amplify.py`'s three signal-writing functions are each wrapped in `try/except Exception: pass`, with the module's own docstring stating the intent (*"a Redis outage must never break the calling action"*); every `emit_to_user`/`emit_to_group` call in [Event Flows](20_Event_Flows.md) is scheduled via `BackgroundTasks`, after the primary database write and HTTP response are already underway.

**Consequence, also worth stating plainly:** this consistent choice trades observability for resilience — the audit noted the exception-swallowing side of this pattern happens without any logging in several places (part of a broader, cross-cutting pattern it flagged, not unique to taste). The *behavior* (never let this fail the main action) looks like a deliberate, good choice; the *lack of any log line when it does silently fail* looks more like an oversight than a considered trade-off.

**Status:** Settled and consistently applied for its primary goal; the missing-logging side has not been addressed.

---

### ADR-8: No admin/permission system — a decision by omission, not by design

**Decision, or rather the absence of one:** this app has never built a concept of "an operator-level user," distinct from a regular authenticated profile.

**Evidence this is an omission rather than a considered "we don't need this":** two live endpoints (News's `/news/admin/*`, four Post-module job-trigger routes) read as though they were meant to be operator-only — named `/admin`, or clearly intended as manual ops triggers for scheduled jobs — but ship gated by nothing stronger than "is logged in" or, in four cases, nothing at all (audit P8-F1, P13-F1; see [Authorization](15_Authorization.md)). If a real admin concept had been deliberately deferred as a known gap, it would be unusual for code to be written *as if* that concept already existed (naming a route `/admin`) without it actually being checked.

**Status:** Open. [Authorization](15_Authorization.md) and [Known Limitations](30_Known_Limitations.md) both flag this as a decision worth making deliberately — even a simple env-var-configured allowlist would close the most severe instances — rather than continuing to patch each endpoint independently as it's noticed.

---
**Previous:** [30 — Known Limitations](30_Known_Limitations.md) · **This is the final chapter.** Return to [00 — Project Introduction](00_Project_Introduction.md) or the [PROGRESS tracker](PROGRESS.md).
