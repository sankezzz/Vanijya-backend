# Audit Phase 13 — Cross-Cutting Duplication & Consistency Sweep

**Status:** Done
**Scope:** Response envelopes, pagination conventions, ownership-check patterns, and auth coverage across every router in the app; resolution of open questions #2, #3, #15, #16, #18, #19; consolidation of patterns already spotted piecemeal in Phases 04–11.

**This phase's top finding (P13-F1) required reading two Post-module router files that were missed in Phase 07 — retroactively annotated there, same as Phase 11's findings.**

---

## Findings

### P13-F1 — Four completely unauthenticated endpoints can trigger production background jobs on demand — zero auth dependency, not even "any logged-in user"
**Severity:** High
**Category:** Authorization — **retroactively extends Phase 07 (Post)**
**Files:** `app/modules/post/post_recommendation_module/router.py:55-64` (`POST /posts/recommendation/jobs/expiry`, `POST /posts/recommendation/jobs/popular-sync`), `app/modules/post/post_user_interaction/router.py:46-57` (`POST /posts/interactions/jobs/taste-update`, `POST /posts/interactions/jobs/ignore-detect`)

**Reason:** All four endpoints have exactly one dependency — `db: Session = Depends(get_db)` — and nothing else. No `Depends(get_current_user_id)`, no `Depends(get_current_profile_id)`, no admin check, nothing. Compare to Phase 08's P8-F1 (News' `/news/admin/*` endpoints), which at least required being *some* authenticated user — these four Post endpoints require **no credentials of any kind**. Each one directly invokes a real production background job on the calling request:
```python
@router.post("/jobs/expiry", response_model=JobResult)
def trigger_expiry_job(db: Session = Depends(get_db)):
    result = jobs.run_expiry_job(db)
    return JobResult(status="ok", details=result)
```
…and identically for `run_popular_posts_sync`, `run_taste_update_job`, `run_ignore_detection_job` (all four confirmed real, DB-writing functions in Phase 07's reading of `post_recommendation_module/jobs.py` and `post_user_interaction/jobs.py`). Both routers are mounted in `main.py` (confirmed Phase 01: `post_rec_router`, `post_interaction_router`), so these are live, internet-reachable endpoints today.

**Failure scenario:** Anyone — no account, no token, nothing — can `POST /posts/recommendation/jobs/expiry` (or any of the other three) repeatedly, forcing the app to repeatedly run full-table scans and bulk updates over `post_embeddings`/`popular_posts`/`post_interaction_events` on demand. At minimum this is a resource-exhaustion / cost vector; at worst, repeatedly forcing `run_ignore_detection_job` or `run_taste_update_job` out of their normal cadence could distort the recommendation data these jobs maintain in ways the rest of the system assumes only happen on a fixed schedule.
**Recommended fix:** These look like they were meant purely as manual/ops-triggerable versions of the scheduled jobs (useful for testing/debugging), not public API surface. Gate them behind the same kind of admin check recommended for P8-F1 — at minimum, remove them from the publicly-mounted router and keep them as a CLI/admin-only path, or add real authentication.
**Risk:** Low to fix (additive auth check); the current absence is the risk.
**Cleanup effort:** Small (~30–45 min once an admin-gating approach is decided — same decision as P8-F1, should be solved once and applied to both).
**Confidence:** Confirmed (both router files read in full this phase; function bodies cross-referenced against Phase 07's already-read job implementations).
**Action taken:** `tests/audit/audit_phase_07.md` annotated with a pointer to this finding.

---

### P13-F2 — Two modules never adopted the `ok()` response envelope that every other route-bearing module uses consistently
**Severity:** Medium
**Category:** Duplicate Logic / Architecture / Consistency
**Files:** `app/modules/chat/presentation/router.py` (all 15 endpoints), `app/modules/safety/router.py` (all 6 endpoints) vs. every other router in the app

**Reason:** Grepped every router file for `from app.shared.utils.response import ok`. **12 of 17 router files import it and use it on every response.** Two of the remaining five have no endpoints of their own to check (`news_recommendation_engine/router.py` is empty — P8-F2 — and `connections/routes/connections.py` is confirmed-dead code — P4-F1). The remaining two are real, live, actively-used routers that simply never adopted the convention:
- **Chat** (`presentation/router.py`): every endpoint returns a raw dict or Pydantic model directly — `{"id": ..., "status": ..., "created": ...}`, `{"ok": True}`, the bare `msg`/`deal` object, etc.
- **Safety** (`router.py`): every endpoint does `return service.block_user(...)` etc. directly — the service functions' raw dicts reach the client unwrapped.

`documentation/auth_and_access_control.md` states plainly: *"Every endpoint returns the `ok()` envelope."* That's true for the other 12 routers (confirmed individually across Phases 02–09, 11) but demonstrably not universal — this phase is the first point in the audit with full enough coverage across every module to see the pattern clearly.
**Recommended fix:** Wrap Chat's and Safety's router return values in `ok(...)` for consistency with the rest of the API surface, unless there's a deliberate reason these two are meant to differ (**Not Proven** — no comment anywhere suggests this was intentional).
**Risk:** Medium if any existing client code specifically depends on the current unwrapped shape for these two modules — this is a breaking API change for those two, not purely additive, so needs frontend/mobile coordination before applying.
**Cleanup effort:** Small (~1 hr for the wrapping itself; coordination cost is the bigger unknown).
**Confidence:** Confirmed (grep across all 17 router files; both non-conforming files' full endpoint lists cross-referenced against Phases 06 and 11's already-read content).

---

### P13-F3 — Pagination parameter naming is inconsistent within the Groups module itself
**Severity:** Low
**Category:** Inconsistent Naming
**Files:** `app/modules/groups/router.py` — `list_groups_api` (`per_page`) vs. `get_members_api`/`list_deals_api`/`my_pending_requests_api`/`list_join_requests_api`/`list_group_media_api` (all `limit`)

**Reason:** `GET /api/v1/groups/` takes `page`/`per_page`; every other paginated endpoint in the *same router* takes `page`/`limit` for the identical concept (page size). A client integrating against this one module has to remember which of its own endpoints uses which name. Every other module audited (Connections, Post, News, Safety) is internally consistent — this is specific to Groups.
**Recommended fix:** Rename `list_groups_api`'s `per_page` to `limit` to match the rest of its own router (or, if `per_page` is preferred going forward, rename the majority the other way — either direction is fine, the inconsistency is the problem, not the specific word chosen).
**Risk:** Medium (client-facing param rename — needs frontend coordination like P13-F2, not purely additive).
**Cleanup effort:** Trivial code change (~10 min); coordination is the real cost.
**Confidence:** Confirmed (all six paginated Groups endpoints read directly in Phase 05).

---

### P13-F4 — Ownership checks are duplicated inline instead of reusing each module's own existing helper
**Severity:** Low
**Category:** Duplicate Logic / Maintainability
**Files:** `app/modules/groups/service.py:1389,1413,1439` (`update_group_deal`, `close_group_deal`, `publish_group_deal` — each does `if deal.posted_by != user_id: raise GroupPermissionError(...)` inline) vs. `app/modules/post/service.py:513,531,883` (`update_post`, `delete_post`, `toggle_deal_closed` — each does `if post.profile_id != profile_id: raise PostForbiddenError(...)` inline)

**Reason:** Both modules already have the *pattern* of extracting reusable permission helpers (Groups has `_require_admin`/`_require_member`, used consistently for membership/admin checks elsewhere in the same file — Phase 05 praised this) — but the "am I the author of this specific row" check is repeated inline three times in each module instead of being pulled into a one-line helper (`_require_author(deal, user_id)` / `_require_author(post, profile_id)`). Not a bug — every inline instance is currently correct — but it's the exact "three layers perform the same validation" pattern this audit was asked to identify, and it's the kind of duplication that drifts silently (one call site gets updated with an extra condition later, the other two don't).
**Recommended fix:** Extract a small helper in each module, mirroring the existing `_require_admin`/`_require_member` style already established in Groups.
**Risk:** None (pure refactor, behavior-preserving).
**Cleanup effort:** Trivial (~15–20 min per module).
**Confidence:** Confirmed (all six call sites re-checked directly against Phases 05 and 07's already-read content).

---

## Resolved open questions

**#2 (recommendation/scoring logic duplication across post_recommendation_module, news_recommendation_engine, connections/weights_config.py, taste/*):** Resolved — **not duplicated in the problematic sense.** Each module's scoring approach is a legitimately different technique for a legitimately different data shape: Post and Connections/Groups use pgvector ANN cosine similarity (dense embeddings); News uses rule-based Jaccard/matrix scoring (deliberately no embeddings — Phase 10's memory confirms this is a permanent decision given news content volatility). The *actual* duplication already found and reconciled is narrower and already captured: News' dead recommendation engine reimplementing role-score inline instead of calling its own (unused) `compute_role_score` (P8-F2), and Post's two feeds reading two different taste stores for conceptually the same signal (P7-F2). No further cross-module scoring duplication found beyond what Phases 07/08 already flagged.

**#3 (do the 3 untracked architecture docs still match code):** Spot-checked `documentation/recommendation_taste_architecture.md` (the most detailed of the three) against everything independently found in Phase 10 — **matches closely**, including proactively documenting the exact same two corrections (Posts' `get_amplify_weights` gotcha, News' `UserNewsTaste` dead-persistent-table correction) this audit independently re-verified from code. This is meaningfully more current and accurate than `BACKEND_AUDIT.md`/`gaps.md` (both of which this audit found stale in multiple places). `dynamic_recommendation_architecture.md` and `dynamic_recommendation_flowcharts.md` were not read in full this pass given time constraints and this positive signal from the primary doc — flagging as **Not Proven** for those two specifically, not asserting they're equally current, just deprioritized given the corroborating evidence already gathered.

**#15 (group deal creation split — Chat router vs. Groups router):** No new information beyond Phase 06's P6-F7 — restating as still-open for a future fix pass, not a gap in this audit.

**#16 (BUG-024's silent-except-pass pattern — final tally):** Confirmed present in **five** modules by the end of this audit: Connections (P4-F3), Post (Phase 07 reconciliation, ~10 instances), Groups (noted, not separately scored), News (`news_user_interaction/service.py`, `feed/service.py`'s amplify-boost try/except), and Taste (`amplify.py`'s four write-helpers). One consistent fix (replace `pass` with `logger.warning`/`.exception`) applies everywhere — this was never re-scored per-module after Phase 04 to avoid inflating the finding count for one repeated pattern; treat as one cross-cutting cleanup item touching ~20+ call sites total.

**#18 (Post vs. News interaction-batch-processing duplication):** Confirmed structurally similar (stale-event filtering, dwell classification, signal derivation, same shape of "drop old/unknown, bulk-insert valid, fire-and-forget taste signal") but independently correct in both places — no divergence causing a bug found. Worth a shared-base extraction someday for maintenance-risk reasons, not urgent.

**#19 (disabled `ConvStatus.ACTIVE`/block-check pattern — final tally):** Confirmed at exactly **4 call sites across 3 modules** by the end of the audit: `chat/domain/use_cases.py` (×2: `SendMessageUseCase`, `CreatePersonalDealUseCase`), `post/service.py`'s `send_post`, `news_user_interaction/service.py`'s `send_article`. All four should be resolved together as part of fixing P6-F1 (the block-enforcement gap), not as four separate patches — the underlying decision (how blocking should actually integrate with conversation status) is the same everywhere.

## Phase 13 summary
- 4 findings: **1 High (P13-F1), 1 Medium (P13-F2), 2 Low (P13-F3, P13-F4).**
- Six previously-open cross-cutting questions resolved (2, 3-partial, 15-restated, 16-tallied, 18-resolved, 19-tallied).
- P13-F1 is a genuine, serious finding that slipped past Phase 07's original pass — a reminder that even a thorough per-module audit benefits from a dedicated cross-cutting re-read at the end, which is exactly what this phase is for.
- Nothing found blocks moving on to Phase 14 (final synthesis).
