# 27 — Glossary

Every term used across this handbook, in one place. Domain terms (specific to Vanijyaa's product) and technical terms (general software concepts explained here because the handbook assumes no prior framework knowledge) are mixed together, alphabetically — a new engineer is equally likely to need either kind mid-sentence.

**Access token** — a short-lived JWT proving identity for normal API requests. Carries `user_id`, `profile_id`, and a session ID (`jti`) directly in its claims. See [Authentication](14_Authentication.md).

**ANN (Approximate Nearest Neighbor)** — a search technique that finds vectors "close enough" to a query vector without comparing against every vector in the dataset — the trade-off pgvector's HNSW index makes for speed at scale. See [Recommendation Engine](19_Recommendation_Engine.md).

**APScheduler** — the Python library running this app's [Background Jobs](18_Background_Jobs.md), via its `BackgroundScheduler`, in its own thread pool, separate from the asyncio event loop. See [Runtime Architecture](06_Runtime_Architecture.md).

**Business** — a profile's company/trading-entity record (GST number, IEC code, business name, city, state). Distinct from `Profile` (the person/account) itself. See [Database Guide](09_Database_Guide.md) §1.

**Broker** — one of the three trading roles a profile can declare (alongside Trader and Exporter). A business classification, not a permission level — see [Authorization](15_Authorization.md)'s explicit warning not to confuse this with an admin/permission role.

**Confidence (in the taste system)** — a running score representing how *sure* the system should be about a taste signal, tracked separately from the signal's direction (positive/negative). Gates how much a session layer is allowed to influence a blended weight. See [Recommendation Engine](19_Recommendation_Engine.md).

**Cosine similarity** — a measure of how similar two vectors' *directions* are (not their magnitude), the standard scoring function for embedding-based recommendation. Used throughout [Recommendation Engine](19_Recommendation_Engine.md).

**CROSS_PLATFORM_DIMS** — the frozenset of taste dimension types (`commodity`, `city`, `state`, `trade_intent`) eligible to sync from a module session into the global session. Not the same as which dimensions are actually *blended* — see `_GLOBAL_BLENDED_DIMS` and [Recommendation Engine](19_Recommendation_Engine.md).

**Deal-Requirement** — one of the four post categories, used to advertise or request a specific trade. See [Product Overview](01_Product_Overview.md).

**Decay (taste)** — the exponential reduction of a taste signal's weight over time (`~30-day half-life`), so old behavior matters less than recent behavior without being erased outright. See [Recommendation Engine](19_Recommendation_Engine.md).

**Dependency Injection (DI)** — a pattern where a function declares what it needs (a database session, the current user) as parameters, and a framework supplies them automatically rather than the function constructing them itself. In this app, FastAPI's `Depends(...)`. See [How the System Works](02_How_the_System_Works.md) and [Request Lifecycle](07_Request_Lifecycle.md).

**Embedding** — a numeric vector representation of something (a post, a group, a user's preferences) positioned in space such that similar things end up near each other — the basis for every ANN/cosine-similarity search in this app.

**Enriched article** — a raw news article after an LLM (Groq) has extracted structured fields from it (commodity tags, location, category, sentiment). See [Database Guide](09_Database_Guide.md) §7 and [Recommendation Engine](19_Recommendation_Engine.md).

**Exporter** — one of the three trading roles. See Broker, above.

**FCM (Firebase Cloud Messaging)** — Google's push-notification delivery service. This app stores an FCM token per user but never calls FCM to actually send anything — see [Notifications](23_Notifications.md).

**Firebase** — used in this app for exactly one purpose: verifying a phone-OTP round trip happened, via `firebase_admin.auth`. Not used for push notifications (see FCM) despite being the same vendor. See [Authentication](14_Authentication.md).

**Global session (taste)** — the middle of the three taste layers: a Redis hash (`session:global:{profile_id}`, 1-day TTL) combining signal across every module for one profile. See [Recommendation Engine](19_Recommendation_Engine.md) and [Redis](17_Redis.md).

**GNews** — the third-party news-aggregation API this app's ingestion pipeline fetches raw articles from. See [Feature Guide](10_Feature_Guide.md) and [Background Jobs](18_Background_Jobs.md).

**Groq** — the LLM provider used to enrich raw news articles (extracting tags, location, category). See [Recommendation Engine](19_Recommendation_Engine.md).

**HNSW (Hierarchical Navigable Small World)** — the specific ANN indexing algorithm pgvector uses to make vector similarity search fast at scale.

**Influence (taste)** — the fraction (0.0-1.0) each of the three taste layers (persistent/global/module) contributes to a final blended weight, computed per-dimension-key based on confidence. See [Recommendation Engine](19_Recommendation_Engine.md)'s formula walkthrough.

**JWT (JSON Web Token)** — a signed, tamper-proof piece of data encoding claims and an expiry, verifiable without a database lookup. This app issues two kinds — access tokens and onboarding tokens. See [Authentication](14_Authentication.md).

**KYB (Know Your Business)** — this app's business-verification flow (GST number, IEC code, verified via Surepass). See [Feature Guide](10_Feature_Guide.md).

**KYC (Know Your Customer)** — this app's identity-verification flow (PAN, with Aadhaar planned). See [Feature Guide](10_Feature_Guide.md).

**Module session (taste)** — the fastest-moving of the three taste layers: a Redis hash (`session:{module}:{profile_id}`, 2-hour TTL) scoped to one module only. See [Recommendation Engine](19_Recommendation_Engine.md) and [Redis](17_Redis.md).

**ORM (Object-Relational Mapper)** — a library (SQLAlchemy, here) that lets code work with database rows as Python objects/classes instead of writing raw SQL for every query. See [How the System Works](02_How_the_System_Works.md).

**Onboarding token** — a short-lived (15 min) JWT proving a phone number was just verified, used only to complete account setup before a full access token is issued. See [Authentication](14_Authentication.md).

**pgvector** — a PostgreSQL extension adding a native vector data type and similarity search (including HNSW indexing) directly inside Postgres, rather than needing a separate vector database. See [How the System Works](02_How_the_System_Works.md).

**Persistent (taste)** — the slowest-moving, permanent taste layer: the `user_global_taste` Postgres table, updated only via the nightly promotion job after passing confidence/volume gates. See [Recommendation Engine](19_Recommendation_Engine.md).

**Profile** — the record representing one person's presence on the platform (name, role, avatar, counters). One `User` (the login/auth identity) has exactly one `Profile`. See [Database Guide](09_Database_Guide.md) §1.

**Refresh token** — an opaque (non-JWT) random string used to obtain a new access token without re-authenticating. Only its SHA-256 hash is stored server-side; rotates on every use. See [Authentication](14_Authentication.md).

**Repository pattern** — an architectural pattern where all database access for a concept is pulled into one dedicated class, so business logic never writes a query itself. Genuinely used only in `chat/` and `taste/` in this app. See [Repositories](13_Repositories.md).

**Room (Socket.IO)** — a named group of connected sockets; emitting to a room reaches everyone in it. This app uses `user:{id}` (personal) and `group:{id}` (opt-in) rooms. See [Event Flows](20_Event_Flows.md).

**Service layer** — the pattern of keeping business logic in plain functions (or, in `chat`/`taste`, classes) separate from HTTP-handling router code. See [Service Layer](12_Service_Layer.md).

**Session-scoped taste** — see Module session and Global session, above.

**Signed upload URL** — a short-lived, one-time URL Supabase Storage issues that lets a client upload a file directly to storage, without the file's bytes ever passing through this app's own server. See [Image Uploads](21_Image_Uploads.md).

**Socket.IO** — the real-time, bidirectional communication library this app uses for live chat/group events, layered on top of the same FastAPI app. See [Event Flows](20_Event_Flows.md).

**Supabase** — the hosted service this app uses for file storage (Postgres itself is hosted separately — see [Database Guide](09_Database_Guide.md)'s intro). See [Image Uploads](21_Image_Uploads.md).

**Surepass** — the third-party KYC/KYB verification provider this app calls for PAN/GST/IEC checks. See [Feature Guide](10_Feature_Guide.md).

**Taste** — this handbook's/codebase's term for a profile's inferred preference toward a commodity, city, state, category, or author, computed from behavior rather than declared outright. See [Recommendation Engine](19_Recommendation_Engine.md) for the complete system.

**Trader** — one of the three trading roles. See Broker, above.

**`_GLOBAL_BLENDED_DIMS`** — the narrower frozenset (`commodity`, `city`, `state`) of dimension types that actually get a real 3-layer blend in `MergeWeights`. `trade_intent` is in `CROSS_PLATFORM_DIMS` but deliberately excluded from this set. See [Recommendation Engine](19_Recommendation_Engine.md).

---
**Previous:** [26 — Deployment](26_Deployment.md) · **Next:** [28 — Common Debugging](28_Common_Debugging.md)
