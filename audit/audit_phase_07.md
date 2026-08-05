# Audit Phase 07 — Post Module (post + post_recommendation_module + post_user_interaction)

**Status:** Done
**⚠️ Addendum from Phase 11:** `Post.is_public`/`target_roles` are stored and serialized throughout this module but are only enforced as an actual read-time filter in one supplementary code path (`_ensure_fresh_in_pool`) — `_get_post_or_raise`, `get_following_feed`, and the main ANN candidate source `_query_partition` all have no visibility filter at all. See `audit_phase_11.md`'s P11-F1 for full evidence; not re-derived here to avoid drift between the two files.

**⚠️ Addendum from Phase 13:** `post_recommendation_module/router.py` and `post_user_interaction/router.py` (not read closely enough in this original pass) each expose job-trigger endpoints (`/jobs/expiry`, `/jobs/popular-sync`, `/jobs/taste-update`, `/jobs/ignore-detect`) with **no authentication dependency at all** — not even "any logged-in user." See `audit_phase_13.md`'s P13-F1.
**Scope:** `app/modules/post/{models,router,schemas,service}.py`, `post_recommendation_module/{service,models,jobs}.py`, `post_user_interaction/{service,taste_service,models,jobs}.py`

---

## Files inspected
All core files read in full: `post/models.py`, `post/router.py`, `post/service.py`, `post/schemas.py`, `post_recommendation_module/service.py`, `post_recommendation_module/models.py`, `post_recommendation_module/jobs.py`, `post_user_interaction/service.py`, `post_user_interaction/taste_service.py`, `post_user_interaction/models.py`, `post_user_interaction/jobs.py`. (`constants.py`/`vector.py`/`schemas.py` files skimmed for names referenced by the above; no independent issues found there.)

This is, overall, **the most mature module audited so far** — real ANN-based candidate pooling with hot/warm/cold partitioning, a genuinely thought-out taste-decay model, batch-oriented background jobs with idempotent `processed_at` markers, and consistent N+1 avoidance. The findings below are real, but they sit on top of a solid foundation, unlike some earlier modules.

---

## Reconciliation with `documentation/BACKEND_AUDIT.md` (Post's bugs: BUG-002, 010, 011, 013, 014, 016, 021, 022, 024, 031, 034, 037)

| Bug | Status now | Evidence |
|---|---|---|
| BUG-002 (no auth) | **Fixed** | Every endpoint uses `Depends(get_current_profile_id)`/`get_current_user_id`. |
| BUG-010 / BUG-011 (non-atomic like/save counters) | **Fixed** | `toggle_like`/`toggle_save` now use `db.query(Post).filter(...).update({Post.like_count: Post.like_count ± 1})` — an atomic SQL-level increment, not a Python read-modify-write. Same pattern already praised in Connections (Phase 04). See P7-F5 for one residual, narrower issue this surfaced. |
| BUG-013 (`_active_profile_ids()` full-table scan on every post op) | **Still present — and now provably pointless, not just slow.** See P7-F1. |
| BUG-014 (N+1 is_liked/is_saved per post in feeds) | **Fixed** | `_batch_post_responses`/`_batch_feed_cards`/`_batch_my_post_cards` all batch via single `IN` queries. |
| BUG-016 (deleted users' posts stay visible) | **Fixed — via Phase 03's hard-delete migration, not a direct patch.** `Post.profile_id` cascades from `Profile`, which cascades from `User`; a hard-deleted user's posts are actually removed from the table now, not just supposed to be filtered. |
| BUG-021 (`PostShare` has no unique constraint) | **Still present**, confirmed — `post/models.py`'s `PostShare` has no `UniqueConstraint`, unlike `PostLike`/`PostSave`/`PostView`. `record_share`/`send_post` both insert unconditionally with no idempotency check. |
| BUG-022 (`delete_comment` non-atomic decrement) | **Partially fixed.** The counter update itself is now atomic SQL (matching the BUG-010/011 fix), but there's still no floor guard and no protection against two truly-concurrent requests both finding the same not-yet-committed-deleted comment row and both decrementing — narrower race window than originally described, same failure class (count can still go negative in that window). |
| BUG-024 (5× silent `except Exception: pass`) | **Still present, and more widespread now** — counted ~10 instances across `post/service.py` alone (`create_post`, `get_post`, `delete_post`, `toggle_like`, `add_comment`, `record_share`, `send_post`, `toggle_save`, `toggle_deal_closed` ×2). Same anti-pattern already flagged in Connections (P4-F3) and implicitly in Groups (Phase 05) — this is now confirmed as a pervasive, cross-module pattern, not a one-off. Consolidating into one cross-cutting recommendation for Phase 13 rather than re-recommending per module. |
| BUG-031 (no existence check for category_id/commodity_id) | **Still present, mechanism now precisely characterized.** `PostCreate.category_id`/`commodity_id` are plain `int`s with no DB-existence validation (contrast with Profile's `_validate_role`/`_validate_ids`, which do check — Phase 03 flagged this as something Profile got right that Post didn't). Confirmed failure mode: `post_recommendation_module/service.py`'s `index_post()` does `CATEGORY_NAMES[category_id]` — a bad `category_id` raises `KeyError`, caught by `create_post`'s surrounding `except Exception: pass` (BUG-024's pattern) — so the post is created successfully but silently never enters the recommendation index. A bad `commodity_id` doesn't even raise — `COMMODITY_ID_TO_IDX.get(commodity_id, 0)` silently maps it to index 0 (cotton), a silent misclassification rather than a crash. |
| BUG-034 (`_profile_location` returns `(0.0, 0.0)` fallback) | **Still present**, verbatim, same lines. |
| BUG-037 (unbounded `limit` query param) | **Still present** — `/mine`, `/following`, `/saved` all take `limit: int = 20` as a plain function parameter with no `Query(le=...)` bound. |

---

## Findings

### P7-F1 — `_active_profile_ids()` no longer serves any purpose but still runs a full-table scan on every single post request
**Severity:** High (raised from the prior audit's characterization as a pure performance issue — it's now also pure waste)
**Category:** Performance / Dead Logic
**Files:** `app/modules/post/service.py:101-102`, called from `_get_post_or_raise` (used by nearly every mutating/reading endpoint) and `get_feed`

**Reason:** `_active_profile_ids()` still does an unbounded `SELECT id FROM profile` with zero filtering, and `_get_post_or_raise` filters `Post.profile_id.in_(_active_profile_ids(db))`. Per Phase 03's finding, `User.is_deleted` was removed entirely (migration `b4c5d6e7f8a9`) and users are now hard-deleted with `ON DELETE CASCADE` all the way through `User → Profile → Post`. That means **a `Post` row can no longer exist with an invalid/deleted-owner `profile_id`** — the FK and cascade already guarantee it. So `Post.profile_id.in_(<every profile id in the database>)` is now a tautology for any post the query already found by `Post.id == post_id` — it can never filter anything out. The helper now costs a full table scan of every profile row, on every single post read/write in the app, to enforce a condition that's already structurally guaranteed.
**Recommended fix:** Delete `_active_profile_ids()` and the `.filter(Post.profile_id.in_(...))` clause entirely; `_get_post_or_raise` only needs `Post.id == post_id`.
**Risk:** Low — removing a no-op filter changes no behavior.
**Cleanup effort:** Trivial (~15 min, touches `_get_post_or_raise` and `get_feed`).
**Confidence:** Confirmed (cascade chain verified across Phase 03's `profile/models.py` read and this phase's `post/models.py` read: `Post.profile_id` → `ForeignKey("profile.id", ondelete="CASCADE")`; `Profile.users_id` → `ForeignKey("users.id", ondelete="CASCADE")`).

---

### P7-F2 — Recommendation feed and Following feed read two different, differently-shaped taste stores, contradicting one of the two store's own docstring
**Severity:** Medium
**Category:** Architecture / Duplicate Logic
**Files:** `app/modules/post/service.py:358-366,984-985` (`_following_taste_counts`, `get_following_feed`) vs. `app/modules/post/post_recommendation_module/service.py:514-516` (`get_recommended_posts`) vs. `app/modules/post/post_user_interaction/taste_service.py:11-13` (module docstring)

**Reason:** `post_user_interaction/taste_service.py`'s own docstring states: *"user_taste_profiles is kept as a write-only legacy table for audit; it is no longer read by the reranker."* The main Recommendation feed (`get_recommended_posts`) honors this — it reads `taste_service.get_taste_weights(...)`, which sources from the newer `UserPostTaste` table with exponential time-decay, a negative-signal discount, and a score floor. But the **Following feed** (`get_following_feed` → `_following_taste_counts`) reads `UserTasteProfile` directly — the same table the docstring calls "legacy" and "no longer read." `record_interaction()` does write both tables on every interaction, so the two don't silently go out of sync in *content*, but they differ in *shape*: `UserTasteProfile`-based Following-feed ranking has no time decay at all (a like from a year ago counts exactly as much as one from an hour ago), while the Recommendation feed's ranking decays old signal away. The same underlying idea — "how much does this user like each post category" — is computed two different ways depending which feed is asking.
**Recommended fix:** Either have `get_following_feed` switch to `taste_service.get_taste_weights(db, profile_id, "category", role_id)` too (unifying both feeds on the decayed store), or, if the lack of decay in Following-feed ranking is intentional (arguably reasonable — you follow someone because you want their content, decay may be undesirable there), update the misleading docstring to say "no longer read by the **recommendation** reranker" rather than implying no reranker reads it.
**Risk:** Low to fix; mostly a decision about intended product behavior, not a code risk.
**Cleanup effort:** Trivial if just fixing the docstring; Small (~30 min) if unifying the read path.
**Confidence:** Confirmed (all three files read in full).

---

### P7-F3 — ~95 lines of commented-out duplicate function kept as ad-hoc profiling code
**Severity:** Low
**Category:** Dead Code / Commented Code
**Files:** `app/modules/post/post_recommendation_module/service.py:644-736`

**Reason:** A full second copy of `get_recommended_posts`, entirely commented out, with `print()`-based stage timing (`time.perf_counter()` deltas at every step) — clearly a debugging tool from a past performance investigation, left in place rather than removed or promoted to real instrumentation.
**Recommended fix:** Delete it. If per-stage timing is still wanted, add it properly (e.g., Sentry spans — this app already has Sentry wired up per Phase 01 — or structured `logger.debug` timing) rather than a parallel commented-out copy of the function that will silently drift from the real one as it's maintained.
**Risk:** None.
**Cleanup effort:** Trivial (delete).
**Confidence:** Confirmed.

---

### P7-F4 — A third instance of the same disabled conversation-status check found in Chat (P6-F1/P6-F4) — post-sharing via DM also bypasses block enforcement
**Severity:** Medium (reinforces P6-F1 rather than standing alone — not double-counted in severity totals as a second Critical)
**Category:** Correctness / Missing Connection
**Files:** `app/modules/post/service.py:795-796` (`send_post`)

**Reason:**
```python
guard = chat_repo.get_conv_send_info(conv_id, user_id)
if guard:  # and guard.status == ConvStatus.ACTIVE:
```
Same pattern as the two disabled checks found in `chat/domain/use_cases.py` (P6-F1, P6-F4): a status check written, then commented out, left in place. This confirms the disabling was applied consistently across at least three call sites (`SendMessageUseCase`, `CreatePersonalDealUseCase`, and here in Post's `send_post`) rather than being an isolated slip in one file — which actually makes it more likely this was one deliberate (if under-documented) change across the codebase, not an accident in a single spot. Practical effect here: sharing a post into a DM also isn't blocked by conversation status, for the same underlying reason P6-F1 already covers in full (nothing sets `BLOCKED` status anyway, and Safety's `is_blocked`/`either_blocked` still have zero callers as of this phase too — confirmed again by grep, no new callers appeared in Post).
**Recommended fix:** Resolve together with P6-F1/P6-F2 — whatever the unified fix ends up being (checking `either_blocked()` directly rather than `Conversation.status`), apply it here too.
**Risk:** None beyond what P6-F1 already covers.
**Cleanup effort:** Folds into P6-F1's estimate — not separate additional effort if fixed as one pass across all three call sites.
**Confidence:** Confirmed (exact line read; grep re-run for `is_blocked`/`either_blocked` across Post found no callers, consistent with Phase 06).

---

### P7-F5 — Like/save/share inserts don't catch the same `IntegrityError` race that view-recording already handles
**Severity:** Low
**Category:** Correctness / Consistency
**Files:** `app/modules/post/service.py:590-602` (`_record_view`, handles it) vs. `609-638` (`toggle_like`), `847-874` (`toggle_save`), `752-767` (`record_share`) (don't)

**Reason:** `_record_view` explicitly catches `IntegrityError` from `PostView`'s unique constraint (two near-simultaneous view-recording requests) and turns it into a graceful revisit-event path instead of a crash. `toggle_like`/`toggle_save` insert into `PostLike`/`PostSave` (both also uniquely constrained) with no equivalent handling — a genuine double-submit race (e.g., a network retry firing the same request twice) would raise an unhandled `IntegrityError`, surfacing as a raw 500 rather than the idempotent toggle response the endpoint is supposed to give. Note this does **not** reopen BUG-010/011 (data corruption) — the counter update is in the same transaction as the failed insert, so it rolls back together; this is purely about the ungraceful error response on the losing side of a rare race, not data integrity.
**Recommended fix:** Wrap the insert branches of `toggle_like`/`toggle_save` in the same `try/except IntegrityError: db.rollback()` pattern `_record_view` already uses, treating a race as "already liked/saved."
**Risk:** None.
**Cleanup effort:** Trivial (~15 min).
**Confidence:** Confirmed (all four functions read directly).

---

### P7-F6 — `GET /posts/` (base feed) is fully commented out in the router; its service function (`get_feed`) still exists and is now only reachable by nothing
**Severity:** Nice to Have
**Category:** Dead Code
**Files:** `app/modules/post/router.py:55-63` (commented endpoint), `post/service.py:552-562` (`get_feed`, now an orphan)

**Reason:** The base feed endpoint is commented out in the router (superseded by the dedicated home-feed module and/or `/posts/following`/`/posts/mine`/`/posts/saved`), but `service.get_feed()` — which still contains the now-pointless `_active_profile_ids()` call from P7-F1 — is left in the module with no caller anywhere (confirmed by the router being its only possible entry point, and that's commented out).
**Recommended fix:** Delete both the commented router block and the now-orphaned `get_feed()` function, unless there's a plan to re-enable this specific endpoint (in which case, uncomment it rather than leaving dead code as a placeholder).
**Risk:** None.
**Cleanup effort:** Trivial.
**Confidence:** Confirmed (router and service both read in full).

---

## What's solid (no action needed)
- The recommendation engine's hot/warm/cold partition scheme with `_ensure_fresh_in_pool`'s explicit guarantee that new posts aren't starved by ANN cutoffs is a genuinely well-designed piece of engineering, with a clear-eyed comment explaining exactly why it's needed.
- `_apply_diversity`'s per-category/per-author capping is a clean, simple, effective anti-monoculture mechanism — no issues found.
- Background jobs (`run_expiry_job`, `run_popular_posts_sync`, `run_taste_update_job`, `run_ignore_detection_job`) are all batch-oriented, idempotent (`processed_at` markers, delete-then-bulk-insert instead of dirty-tracking diffs), and have an explicit comment explaining why `popular_posts` is replaced wholesale rather than diffed (avoiding a race with the concurrent expiry job) — this shows real awareness of concurrent-job interaction, not just single-job correctness.
- `taste_service.py`'s decay/confidence-blend model (`get_taste_weights`) is coherent and well-documented, including the exact reasoning for the confidence blend during cold-start.

## Unresolved questions handed to later phases
- Open question #14 (block-check coverage in Post) is **resolved for Post: confirmed absent**, same as Chat. Feed (Phase 09) still needs its own independent check — do not assume Post's absence implies Feed's.
- Open question #15 (group deal creation split) — no new information from this phase; still pending Phase 13's cross-cutting pass.
- BUG-024's pervasive `except Exception: pass` pattern (now confirmed in Connections, Groups, and Post — three modules) is consolidated as a single cross-cutting item for Phase 13 rather than repeated per-module — noting here so Phase 13 knows to treat it as "fix once, apply everywhere" rather than three separate findings.

## Phase 07 summary
- 6 findings: **1 High (P7-F1), 2 Medium (P7-F2, P7-F4), 2 Low (P7-F3, P7-F5), 1 Nice to Have (P7-F6).**
- 8 of 12 prior-audit bugs assigned to Post are resolved (fully or via a different mechanism than originally suggested); 4 are confirmed still open (BUG-013 downgraded from "slow" to "slow and pointless," BUG-021, BUG-024, BUG-031, BUG-034, BUG-037 — the last four unchanged from original diagnosis, BUG-022 partially fixed).
- This is the strongest-engineered module audited to date; findings here are real but comparatively minor next to Phase 06's.
- Nothing found blocks moving on to Phase 08.
