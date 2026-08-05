# Audit Phase 08 — News_new Module

**Status:** Done
**Scope:** `app/modules/news_new/{config,__init__}.py`, `ingestion/{models,service,jobs,router}.py`, `intelligence/{service,models,providers/groq}.py`, `news_recommendation_engine/{service,router,profile_scorer,models}.py`, `news_user_interaction/{router,service}.py`, `feed/service.py`

---

## Reconciliation with `documentation/BACKEND_AUDIT.md` (News' bugs: BUG-025, BUG-026)
Both were filed against `app/modules/news/tasks.py`, which — per Phase 01/02's established timeline (commit `54ef7e4`, "Transitioning from old news to new news model") — no longer exists. Neither is a simple "fixed" or "still present":

| Bug | Status now |
|---|---|
| BUG-025 (synchronous `time.sleep()` inside a scheduled job blocks the shared APScheduler thread pool) | **Stale reference, but the identical architectural pattern was independently reintroduced in the rewrite.** See P8-F4. |
| BUG-026 (`push_breaking()` built but never scheduled — breaking-news push silently never fires) | **Stale reference, feature not carried over.** No breaking-news detection/push code was found anywhere in `news_new/**`. **Not Proven** whether this was a deliberate drop or is planned for a later phase — nothing in the code says either way. |

---

## Findings

### P8-F1 — News "admin" endpoints are only gated by "is logged in," not by any admin check — because the app has no admin-role concept at all
**Severity:** High
**Category:** Authorization / Architecture
**Files:** `app/modules/news_new/ingestion/router.py:24-62` (`/news/admin/ingest`, `/news/admin/enrich`, `/news/admin/stats`)

**Reason:** All three endpoints under the `/news/admin` prefix depend only on `Depends(get_current_user_id)` — the exact same dependency every regular, non-privileged endpoint in the app uses. The decoded user ID isn't even used (`_user_id`, underscore-prefixed, confirming it's fetched only to satisfy the dependency and never checked against anything). There is no admin flag on `User`/`Profile` anywhere in the schema audited so far (Phases 02/03: `Role` table is `Trader | Broker | Exporter` only), no allowlist, no separate admin auth path — meaning **any authenticated user of the app**, not just operators, can:
- `POST /news/admin/ingest` — trigger a live fetch against the GNews API (repeatable, no rate limit of its own beyond GNews' own daily cap)
- `POST /news/admin/enrich` — trigger up to 100 Groq LLM calls per request (`limit: ... le=100`), a real, metered cost
- `GET /news/admin/stats` — view internal pipeline counts

**Recommended fix:** At minimum, gate these behind an actual admin check — even a simple env-var-configured allowlist of admin user IDs would be better than none. This needs a broader decision (does the app want an admin role at all, given none exists yet?) — flagging as a decision point, not just a code patch.
**Risk:** Low to add a check; the current absence is the actual risk (potential API cost abuse and unauthorized pipeline triggering by any user).
**Cleanup effort:** Small (~1 hr for an env-var allowlist) to Medium (if building a proper role/permission system).
**Confidence:** Confirmed (full router read; grepped for any admin/role check anywhere near these three routes — none found).

---

### P8-F2 — `news_recommendation_engine` is a fully-built, fully dead module; the live feed duplicates its logic inline instead of using it, and two DB tables it owns are never read or written by anything
**Severity:** High
**Category:** Duplicate Logic / Dead Code / Missing Connection
**Files:** `news_recommendation_engine/service.py` (whole file), `news_recommendation_engine/router.py` (whole file — literally zero endpoints), `news_recommendation_engine/models.py` (`ArticleRecommendationScore`, `FeedRankingCache`) vs. `news_new/feed/service.py:222-241` (`get_recommended_feed`)

**Reason:** `news_recommendation_engine/router.py` is mounted (via `news_new/__init__.py`'s router aggregation, confirmed reaching `main.py`) but contains nothing but a comment: *"Personalized feed endpoint will live here once mechanisms 2 and 3 are wired in."* Its `service.py` has real, working functions — `compute_role_score`, `upsert_recommendation_score`, `get_recommendation_scores`, `get_feed_ranking_cache`, `upsert_feed_ranking_cache`, `invalidate_feed_ranking_cache` — backed by two real tables with real indexes and constraints (`ArticleRecommendationScore` with a per-profile/article unique constraint, `FeedRankingCache` with a 2-hour TTL specifically built to avoid recomputing rankings on every request). Grepped every reference to these names across the whole `news_new` tree: **the only callers are the module's own router/service files and `__init__.py`'s aggregation.** Nothing in the actually-live feed code calls any of them.

Instead, `news_new/feed/service.py`'s `get_recommended_feed()` — the function that really serves `GET /news/feed` — **recomputes `role_score` inline** (`role_score = float(getattr(enriched, col, 0.0))`, `feed/service.py:229`), which is character-for-character what `news_recommendation_engine/service.py`'s `compute_role_score()` already does via a DB lookup. It also never touches `FeedRankingCache` — every single feed request re-scores the entire candidate pool from scratch, even though a purpose-built cache table for exactly this exists, unused, one module over.

**Why this matters beyond "unused code":** `ArticleRecommendationScore`/`FeedRankingCache` are real tables, created by a real migration, that will sit permanently empty in production — exactly the "migration created something unused" / "table written but never queried" pattern this audit was asked to find. And the duplicated role-score logic is a maintenance hazard: if the role-relevance formula ever changes, there are now two places it could be defined, only one of which is live, and nothing stops someone from "fixing" the dead one and wondering why nothing changed.

**Recommended fix:** Two honest options, not a hidden third: (a) delete `news_recommendation_engine` entirely (router, service, models, and drop the two tables in a migration) since Phase 1/2/3 of its own docstring roadmap was superseded by `feed/service.py`'s different approach, or (b) actually wire it in — have `feed/service.py` call `compute_role_score`/`upsert_recommendation_score` instead of reimplementing the lookup, and use `FeedRankingCache` to avoid the full rescore on every request (real perf win once article/candidate volume grows). **Not Proven** which direction the team intended — the module's own comments read like an abandoned in-progress plan, not a deliberate keep-both decision.
**Risk:** Low for option (a) once confirmed nothing external depends on the two tables; Medium effort for option (b) (integrating a cache invalidation story with taste/session changes).
**Cleanup effort:** Small (~30 min) for option (a); Medium (~half a day) for option (b).
**Confidence:** Confirmed (exhaustive grep across the whole `news_new` tree for every relevant symbol; both the dead and live scoring code paths read in full).

---

### P8-F3 — News article stats have the same non-atomic counter race that Post's like/save counters already had fixed (BUG-010/011-class bug, previously unaudited module)
**Severity:** Medium
**Category:** Data Integrity
**Files:** `app/modules/news_new/news_user_interaction/service.py:294-303` (`_adjust_stats`)

**Reason:**
```python
def _adjust_stats(db, article_id, field, delta):
    stats = get_article_stats(db, article_id)
    if stats is None:
        stats = NewsArticleStats(article_id=article_id)
        db.add(stats); db.flush()
    current = getattr(stats, field, 0) or 0
    setattr(stats, field, max(0, current + delta))
    ...
```
This reads the counter's current value into Python, computes the new value, and writes it back — the exact read-modify-write pattern Phase 07 confirmed was already fixed for `Post.like_count`/`save_count` (now using atomic `SET x = x + 1` SQL updates). News' `like_count`/`save_count`/`share_count`/`view_count` (all funneled through this one shared helper) never got the same fix. Two concurrent likes on the same article can still result in only +1 recorded instead of +2 — a lost update. The `max(0, ...)` floor at least prevents the count from going negative, which is better than Post's `comment_count` decrement (P7 reconciliation, BUG-022) — so this isn't the worst version of the bug, but the core race is real and unaddressed.
**Recommended fix:** Same fix as already applied elsewhere: `db.query(NewsArticleStats).filter(...).update({field: NewsArticleStats.__table__.c[field] + delta})` (or per-field explicit atomic updates) instead of read-then-write.
**Risk:** Low to fix.
**Cleanup effort:** Small (~30 min, touches one shared helper used by all four counters).
**Confidence:** Confirmed (function read in full).

---

### P8-F4 — Reconciles BUG-025: the same synchronous-sleep-in-a-shared-thread-pool pattern was reintroduced in the news_new rewrite, now via two independent rate limiters
**Severity:** Medium
**Category:** Performance / Architecture
**Files:** `app/modules/news_new/ingestion/service.py:96-97` (`ingest_rotation`'s `time.sleep(GNEWS_INTER_QUERY_DELAY_S)`), `app/modules/news_new/intelligence/providers/groq.py:36-40,74-77` (`RateLimiter.wait()`'s `time.sleep`, and the 429-backoff `time.sleep(retry)`)

**Reason:** `run_news_pipeline()` (`ingestion/jobs.py`, confirmed in Phase 01 to be registered via `scheduler.add_job(run_news_pipeline, "interval", minutes=30, ...)` on the shared `BackgroundScheduler` thread pool) calls `ingest_rotation` (which sleeps between each of several GNews queries) and then `enrich_pending` (which, per article, calls into `GroqEnricher.enrich()`, which sleeps via its own `RateLimiter` before every call, plus an additional backoff sleep on any 429). All of this blocking sleep happens synchronously inside one thread of the same pool that also runs `news_new.trending` (every 5 min), `posts.popular` (every 15 min), and several other jobs (Phase 01's `app/core/scheduler.py`). This is exactly BUG-025's architectural concern (a long, sleep-heavy job monopolizing a thread other scheduled jobs need), independently reintroduced — not fixed, not literally "still present" at the old location, but the same design carried into new code.
**Recommended fix:** Not urgent given current job count and interval spacing (**Not Proven** that thread starvation is actually occurring — would need to check APScheduler's configured pool size, which wasn't set explicitly in `scheduler.py`, so it's using apscheduler's default), but worth the same fix path BUG-025 originally suggested: move the paced HTTP calls to an async task or a dedicated worker rather than sleeping inline in a shared scheduler thread.
**Risk:** None to flag now; risk is in this compounding as more scheduled jobs get added over time without anyone noticing the shared pool is real.
**Cleanup effort:** Medium (~half a day) if actually converting to async/dedicated-worker; Trivial to at least explicitly size the thread pool (`BackgroundScheduler(executors={'default': ThreadPoolExecutor(N)}`) as a stopgap so this and other jobs aren't fighting over apscheduler's default.
**Confidence:** Confirmed (all sleep call sites read directly; job registration re-confirmed against Phase 01's reading of `scheduler.py`).

---

### P8-F5 — Fourth confirmed instance of the disabled `ConvStatus.ACTIVE`/block check pattern
**Severity:** Not separately scored (reinforces P6-F1; not double-counted)
**Category:** Correctness / Missing Connection
**Files:** `app/modules/news_new/news_user_interaction/service.py:343` (`send_article`)

**Reason:** `if guard:  # and guard.status == ConvStatus.ACTIVE:` — identical pattern to Chat's two instances (P6-F1, P6-F4) and Post's `send_post` (P7-F4). This is now confirmed in **four** call sites across **three** modules (Chat, Post, News), all sharing the exact same commented-out condition text. This is strong evidence of one deliberate, sweeping (if under-documented) change across the codebase at some point, rather than isolated mistakes — reinforcing that the eventual fix (P6-F1's recommendation) should be applied as one consistent pass across all four sites, not four separate patches.
**Confidence:** Confirmed (exact line read).

---

## What's solid (no action needed)
- The ingestion pipeline's dedup (`external_id` uniqueness, checked both in-batch and against the DB before insert) and its rotating query-pool selection (`select_queries_for_run`, time-derived slot index — survives restarts with no extra state table) are both clean, well-reasoned designs.
- `enrich_article`'s per-article commit ("crash-safe progress" per its own comment) and its one-retry-then-fail-cleanly behavior on bad LLM output are correct and match the module's own stated design goals.
- `role_relevance` being computed from a fixed matrix rather than trusted from the LLM (`intelligence/service.py`'s docstring: *"role_relevance is COMPUTED from RELEVANCY_MATRIX, never from the LLM"*) is a sound design choice — keeps a potentially-hallucinating LLM out of a scoring dimension that should be deterministic.
- `feed/service.py`'s four feed variants (`get_recommended_feed`, `get_trending_news`, `get_saved_feed`, `get_filtered_feed`) all correctly batch enriched/stats/liked/saved lookups via `_build_feed_page` or equivalent inline batching — no N+1 patterns found, consistent with the discipline seen in Post and Chat.
- `process_interaction_batch` (news_user_interaction) mirrors Post's batch-event-processing design closely (stale-event dropping, unknown-article dropping, dwell value capping) — a legitimate shared pattern between the two modules, not flagged as duplication since interaction-batch processing is conceptually the same problem in both domains and the two implementations aren't drifting in a way that causes bugs (see Phase 13 note below).

## Unresolved questions handed to later phases
- **[Phase 13]** Post's `post_user_interaction/service.py` and News' `news_user_interaction/service.py` implement near-identical interaction-batch-processing logic (stale-event filtering, dwell classification, signal derivation) independently, once per module. Not flagged as a defect here (no divergence found that causes incorrect behavior), but worth a Phase 13 look at whether a shared base implementation would reduce future-maintenance risk — two copies of the same logic is exactly the kind of thing that silently drifts over time.
- **[Phase 12]** Confirm `news_recommendation_scores` and `news_feed_ranking_cache` tables (P8-F2) actually exist via migration, to state definitively (not just "very likely") that they're populated-nowhere orphan tables.

## Phase 08 summary
- 4 scored findings: **2 High (P8-F1, P8-F2), 2 Medium (P8-F3, P8-F4)**, plus P8-F5 as reinforcing evidence for an already-counted issue (not added to totals separately).
- Both prior-audit bugs assigned to News are stale references to deleted code; one (BUG-025) has its underlying architectural issue confirmed reintroduced in the rewrite.
- This phase's most consequential finding (P8-F2) is a clean example of exactly what the audit was commissioned to find: a fully-built parallel implementation, complete with its own database tables, sitting completely unused next to the code that actually runs.
- Nothing found blocks moving on to Phase 09.
