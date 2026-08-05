# Audit Phase 09 — Top-level Feed Module (Home Feed)

**Status:** Done
**Scope:** `app/modules/feed/{service,mixer,pipelines,priority,router,schemas,session_taste}.py`

---

## Findings

### P9-F1 — `feed/session_taste.py` is a complete, well-built, entirely dead module — resolves the long-standing open question about it vs. `taste/session_taste/`
**Severity:** High
**Category:** Dead Code
**Files:** `app/modules/feed/session_taste.py` (whole file — `get_session_taste`, `update_session_taste`, `compute_weights`, `ACTION_WEIGHTS`, `PAGE_LEVEL_DEFAULTS`)

**Reason:** `feed/service.py`'s `get_home_feed()` uses a hardcoded, module-level `FEED_WEIGHTS` constant — never `session_taste.py`'s `compute_weights()`. Grepped every file in the app for any import of `feed.session_taste`: **zero matches anywhere**, including within `feed/` itself (`router.py`/`service.py`/`mixer.py`/`pipelines.py` don't touch it). This resolves Phase 01's open question #4 (whether this is sequential with or parallel to `app/modules/taste/session_taste/`) — the answer is neither, cleanly: it's simply an orphaned first-draft implementation of session-based type-mix weighting that was written, then abandoned in favor of static weights, and never deleted. (For the record: the dedicated `taste/session_taste/` package, audited in Phase 10, is also not used by the Home Feed's type-mix — consistent with this audit's own memory record that the Home Feed's type-mix was a deliberate, permanent exclusion from the dynamic taste system, not an oversight. That's a separate, confirmed-intentional design decision from *this* file's dead-code status.)
**Recommended fix:** Delete `feed/session_taste.py`. If session-aware type-mix weighting is wanted again later, it should be rebuilt deliberately against the current `taste/` architecture rather than resurrecting this orphaned parallel implementation.
**Risk:** None (zero callers, confirmed by exhaustive grep).
**Cleanup effort:** Trivial (delete one file).
**Confidence:** Confirmed.

---

### P9-F2 — `POST /feed/engagement` is a confirmed no-op; client-submitted engagement data is acknowledged and discarded
**Severity:** High
**Category:** Missing Connection / Correctness
**Files:** `app/modules/feed/service.py:143-149` (`submit_engagement`)

**Reason:**
```python
def submit_engagement(user_id, batch):
    # Signals are not yet forwarded to source modules — taste/forwarding is a
    # later step. The endpoint acknowledges receipt so the client can batch.
    return {"acknowledged": True, "signals_processed": len(batch.signals)}
```
This is self-documented as incomplete (unlike Groups' fake-report endpoint, P5-F1, which had no such acknowledgment) — but it's still a real, currently-shipping gap: the client sends real dwell/like/save/skip signals believing they'll refine future feed pages, gets back `{"acknowledged": true, ...}`, and every signal is discarded with no logging, no storage, no forwarding anywhere. This matches `documentation/gaps.md`'s Home Feed Gap #8(c) exactly, confirming it's still true today.
**Recommended fix:** Either wire this into `feed/session_taste.py`'s intended design (if resurrected) or into the existing `taste/` module's session mechanisms (more consistent with the rest of the app's current architecture) — or, if the product no longer wants per-session feed-weight adaptation, remove the client-facing implication that this endpoint does anything beyond acknowledging.
**Risk:** Low to fix in either direction; a product decision on which taste system this should feed into.
**Cleanup effort:** Medium (~half a day) to wire in properly.
**Confidence:** Confirmed (function read in full; cross-checked against `gaps.md`'s independent, older claim of the same gap).

---

### P9-F3 — Breaking news pins are hardcoded to always return empty, while two other docstrings in the same module still describe them as a working feature
**Severity:** Medium
**Category:** Correctness / Stale Documentation
**Files:** `app/modules/feed/priority.py:1-9` (module docstring), `26,28` (`BREAKING_SEVERITY_THRESHOLD`, `MAX_BREAKING_PINS` constants), `111-119` (`_breaking_news`, the actual implementation), `app/modules/feed/router.py:38-43` (router docstring)

**Reason:** `priority.py`'s own header docstring claims: *"Surfaces two categories of time-critical content: 1. Unseen posts from followed users... 2. Breaking news (severity ≥ 8, last 3h, user's commodities, max 2). Total max priority items: 7."* `router.py`'s docstring likewise says *"breaking-news pins are prepended"* on first load. But `_breaking_news()`'s entire body is:
```python
def _breaking_news(db, profile_id, user_id, commodity_names, role_name):
    # Breaking news is omitted from news_new by design.
    return []
```
This directly extends Phase 08's reconciliation of BUG-026 (the old `push_breaking()` function was never scheduled as a background job) — here, breaking news is *also* explicitly stubbed out of the feed's priority-pin source, not merely missing a scheduler entry. That's likely a deliberate, reasonable interim decision (news_new's enrichment doesn't appear to compute a "breaking" flag anywhere audited so far), but the surrounding docstrings and constants (`BREAKING_SEVERITY_THRESHOLD = 8.0`, `MAX_BREAKING_PINS = 2`) still describe and configure a feature that cannot currently produce any output — actively misleading to a future reader (including a future AI-assisted session) who trusts the comments over the one-line function body underneath them.
**Recommended fix:** Update both docstrings to state plainly that breaking-news pins are currently disabled pending a "breaking" signal in the news_new enrichment pipeline, or remove the now-unused constants, so the comments match what the code does.
**Risk:** None (documentation-only fix).
**Cleanup effort:** Trivial (~10 min).
**Confidence:** Confirmed (all three references read directly).

---

### P9-F4 — Priority-pin posts and regular-pipeline posts produce the same `item_type` with two different data shapes — priority pins are missing all author info
**Severity:** Medium
**Category:** Duplicate Logic / Correctness
**Files:** `app/modules/feed/priority.py:58-105` (`_unseen_followed_posts`) vs. `app/modules/feed/pipelines.py:146-154` (`fetch_post_candidates`'s `FeedItem` construction, which wraps a full `FeedPostCard`)

**Reason:** Both produce `FeedItem(item_type="post", ...)`, but `_unseen_followed_posts` builds its `data` dict by hand from a raw `SELECT p.*` query — `id, profile_id, caption, image_urls, category_id, commodity_id, like_count, comment_count, save_count, share_count, view_count, is_liked, is_saved, created_at, allow_comments` — with **no author fields at all** (no `author_name`, `author_avatar_url`, `author_role`, `author_company`, `is_following`, `title`, `source_url`, `location_*` — all present on the regular pipeline's `FeedPostCard`). Since `FeedItem.data` is typed as an untyped `dict[str, Any]` (schemas.py), Pydantic won't catch this at the API layer — the client receives structurally different payloads for the exact same `item_type` depending on whether a given post arrived as a priority pin or a normal mixed item. This is the concrete, still-current mechanism behind `documentation/gaps.md`'s Home Feed Gap #1 ("Post FeedItems missing author info... every post card header needs author_name, author_role...") — true for this one path even where the regular post pipeline already fixed it.
**Recommended fix:** Have `_unseen_followed_posts` reuse `post/service.py`'s `_batch_feed_cards` (already batches author info correctly) instead of hand-rolling a second, incomplete post-card shape from raw SQL.
**Risk:** Low — this is a straightforward call-site fix, no schema migration needed.
**Cleanup effort:** Small (~30–45 min).
**Confidence:** Confirmed (both code paths read and compared field-by-field).

---

### P9-F5 — Seen-post deduplication for priority pins is disabled, confirmed still current
**Severity:** Low
**Category:** Correctness
**Files:** `app/modules/feed/priority.py:51-54`

**Reason:**
```python
# seen_ids from Redis disabled — using empty set for now
# seen_key = f"seen:posts:{profile_id}"
# seen_ids = {...}
seen_ids: set[str] = set()
```
`seen_ids` is always empty, so the "unseen posts from followed users" priority-pin source can resurface the same post on every page load within its 6-hour window. Matches `documentation/gaps.md`'s Home Feed Gap #8(a) — confirmed still true today, same as P9-F2 for engagement processing.
**Recommended fix:** Re-enable the commented-out Redis seen-set read once Redis-backed seen-tracking is available for this path (the `connections` and `post_recommendation_module` modules both already have working seen-set patterns to model this on — `connections/service.py`'s `_get_seen_ids`/`mark_recommendations_seen`, `post_recommendation_module/service.py`'s `_seen_post_ids`/`SeenPost` table).
**Risk:** None.
**Cleanup effort:** Small (~30–45 min, following an existing pattern rather than inventing one).
**Confidence:** Confirmed.

---

## Resolved open questions
- **Open question #4** (feed/session_taste.py vs taste/session_taste) — resolved by P9-F1: neither is used by the Home Feed's type-mix; the former is dead, the latter's non-use here is a separate, already-confirmed-intentional product decision.
- **Open question #14** (block-check coverage) — Feed is the third and final module Safety's own docs claim blocking should protect (DMs, feeds, recommendations). Grepped `is_blocked`/`either_blocked` across the entire `feed/` module: zero matches. **Fully resolved across all three surfaces now: Chat (Phase 06), Post (Phase 07), and Feed (this phase) all confirmed to have zero block-enforcement.** The block feature (P6-F1) is non-functional everywhere the shipped documentation claims it should work, not just in DMs.

## What's solid (no action needed)
- `get_home_feed`'s parallel source-pipeline fetching (`ThreadPoolExecutor`, one dedicated DB session per thread) is correctly reasoned and explicitly commented on the SQLAlchemy-Session-isn't-thread-safe constraint that motivates it — no shared-session bugs found.
- Every pipeline (`fetch_post_candidates`, `fetch_news_feed`, `fetch_connection_candidates`, `fetch_group_candidates`) is defensively wrapped so one failing source degrades to `[]` instead of breaking the whole feed — consistently applied, not just in one spot.
- `mixer.py`'s weighted-random slot algorithm with consecutive-type caps and automatic weight redistribution on pool exhaustion is a clean, self-contained, well-commented piece of logic — no issues found.
- `fetch_post_candidates`'s three-source quota blend (following/popular/recommendation) with a dedup-then-backfill pass is a sensible design, correctly reusing each source module's own real recommender rather than reimplementing ranking here (consistent with `pipelines.py`'s own stated design principle in its header docstring).

## Phase 09 summary
- 5 findings: **2 High (P9-F1, P9-F2), 2 Medium (P9-F3, P9-F4), 1 Low (P9-F5).**
- No prior-audit bugs were directly assigned to the Feed module (`BACKEND_AUDIT.md` predates its current form), but this phase independently confirmed 3 of `documentation/gaps.md`'s Home Feed gaps are still current (engagement no-op, seen-dedup disabled, missing author info on one path) and closed out a question standing since Phase 01.
- Nothing found blocks moving on to Phase 10.
