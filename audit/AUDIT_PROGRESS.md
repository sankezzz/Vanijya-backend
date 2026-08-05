# Production Readiness Audit — Progress Tracker

## ✅ AUDIT COMPLETE (2026-07-31) — all 14 phases done, 54 findings, final report at `tests/audit/audit_phase_14_FINAL_REPORT.md`

**Continuation protocol:** this audit is finished. If resuming a *cleanup/fix* pass based on these findings, start from `audit_phase_14_FINAL_REPORT.md`'s §8 (highest-ROI ranking), not from this progress file. If further *audit* phases are ever wanted (e.g. a dedicated frontend-contract re-check against `documentation/gaps.md`, or a deeper look at `dynamic_recommendation_architecture.md`/`dynamic_recommendation_flowcharts.md` per the Not Proven note in the final report), add a new Phase 15+ row below and follow the same process. Say "continue the audit from `tests/audit/AUDIT_PROGRESS.md`" to resume either way. Do not re-audit a `Done` directory unless new evidence surfaces a specific reason to revisit it.

## Ground rules for every phase
- Read-only investigation. Nothing gets deleted, renamed, or "cleaned up" during the audit itself — findings get reviewed by the user first, fixes happen in a separate follow-up pass.
- Every finding must cite file + line evidence. If it can't be proven from the code (or git history), it's logged as **Not Proven**, not asserted as fact.
- Before calling anything dead: grep `main.py` (and any scheduler/job registry) for the import/registration. This project has a history of look-alike dead files sitting next to the real active one — verify, don't assume.
- Confidence scale used throughout: **Confirmed** (traced in code or git history) / **Plausible** (strong circumstantial evidence, not fully traced) / **Not Proven**.

## ⚠️ A prior audit already exists — discovered in Phase 02, mandatory reading
`documentation/BACKEND_AUDIT.md` is a **475-line, 37-bug prior audit of this same codebase** (dated 2026-04-23, "Phase 2" fix-update dated 2026-05-12). It has an "Issue Map by Module" table mapping `BUG-001`..`BUG-037` to modules. **Every phase from 02 onward must, before writing findings, check that table for the current module's bugs and reconcile each as Fixed / Still Present / Stale Reference** (see Phase 02 for the pattern — it reconciled BUG-008, BUG-019, BUG-023). Do not re-discover a bug from scratch that's already catalogued there — verify its current status instead, and note anything the prior audit got right that later drifted (e.g. BUG-009 "no JWT expiry" is already fixed but not marked as such in that doc — always verify current code, never trust the doc's own status marks).

Other pre-existing `documentation/*.md` files relevant to this audit, and when each will be consulted:
| Doc | What it actually is | Consult at |
|---|---|---|
| `BACKEND_AUDIT.md` | 37-bug prior audit, per-module | Every phase (reconcile applicable BUG-###) |
| `gaps.md` | **Frontend contract gap analysis** (missing fields/endpoints vs. UI), not architecture/dead-code — different axis, describes the OLD pre-`news_new` API shape in places (confirmed stale for News/Home Feed sections). Use opportunistically, don't treat as current. | Phases 07/08/09 opportunistically |
| `security.md` | Misleadingly named — this is actually Safety-module (block/report) API documentation, not a security audit | Phase 11 (Safety) |
| `auth_and_access_control.md` | Documents the post-BUG-001/002/003/005-fix auth dependency architecture (2026-05-12). Mostly still accurate (confirmed against Auth in Phase 02) — but its own "Testing" section instructions are now broken, see P1-F2/P2 cross-reference. Its endpoint tables are also worth cross-checking per-module as those phases happen. | Already used in Phase 02; re-check its per-module tables during Phases 03–08 |
| `final_architecture.md` (1877 lines), `news_module_architecture.md`, `session_taste_architecture.md`, `post_recommendation_architecture.md`, `connection_recommendation_docs.md`, `dynamic_recommendation_architecture.md`, `recommendation_taste_architecture.md`, `post_news_parity_audit.md` (1230 lines) | Not yet read by this audit | Read each at its matching phase (see phase table below); flag drift the same way as code |

This entire section is itself a "duplicated audit effort" risk if ignored — treat the existing docs the same way the user asked us to treat duplicated code: verify, reconcile, don't blindly re-derive.

## Phase status

| # | Phase | Scope | Status |
|---|-------|-------|--------|
| 01 | Bootstrap & Core Infra | `main.py`, `app/config.py`, `app/core/**`, `app/dependencies.py`, `app/shared/utils/**`, `tests/conftest.py`, `requirements.txt`, `scripts/` workspace hygiene | ✅ Done |
| 02 | Auth module | `app/modules/auth/**` | ✅ Done |
| 03 | Profile module | `app/modules/profile/**` (+ reconcile BUG-001/017/018/020/027/033, cross-check `auth_and_access_control.md`) | ✅ Done |
| 04 | Connections module | `app/modules/connections/**` (router.py vs routes/ vs db/ vs encoding/) (+ reconcile BUG-003/029/030, resolve open question #1) | ✅ Done |
| 05 | Groups module | `app/modules/groups/**` (+ reconcile BUG-005/015) | ✅ Done |
| 06 | Chat module | `app/modules/chat/**` (clean-architecture layered module) (+ reconcile BUG-004 — note: prior audit cites a `ws_router.py` that appears gone, only a `.pyc` remains — verify current WS auth story fresh) | ✅ Done — found the audit's top finding so far (P6-F1) |
| 07 | Post module | `app/modules/post/**`, `post_recommendation_module/`, `post_user_interaction/` (+ reconcile BUG-002/010/011/013/014/016/021/022/024/031/034/037, read `post_recommendation_architecture.md`) | ✅ Done — best-engineered module so far, most prior bugs already fixed |
| 08 | News_new module | `app/modules/news_new/**` (ingestion, intelligence, news_recommendation_engine, news_user_interaction, feed) (+ reconcile BUG-025/026 — filed against old `app/modules/news/tasks.py`, near-certainly a stale reference post-`news_new` transition, needs fresh diagnosis; read `news_module_architecture.md`) | ✅ Done — found a fully dead parallel recommendation engine with its own orphan DB tables |
| 09 | Top-level Feed module | `app/modules/feed/*` (mixer, pipelines, priority, session_taste) — home feed vs. per-domain recommendation feeds (read `session_taste_architecture.md`; resolve open question #4) | ✅ Done — engagement endpoint confirmed no-op, session_taste.py confirmed dead, block-check absence now confirmed across all 3 relevant modules |
| 10 | Taste module | `app/modules/taste/**` (amplify, global_session, global_taste, session_taste) (read `recommendation_taste_architecture.md`, `dynamic_recommendation_architecture.md`) | ✅ Done — best-verified module, user's own recent bugfix here confirmed genuinely fixed |
| 11 | Safety / Verification / Deeplink | `app/modules/safety/*`, `verification/*`, `deeplink/*` (cross-check `security.md` which is actually Safety docs) | ✅ Done — found a significant Post-visibility bypass (retroactively annotated onto Phase 07) and confirmed post-reporting is structurally broken |
| 12 | Migrations vs. models | `alembic/versions/**` cross-checked against every SQLAlchemy model across all modules | ✅ Done — 5 confirmed orphan tables from the pre-news_new era, zero models missing migrations |
| 13 | Cross-cutting duplication sweep | Recommendation/scoring logic, DTOs, validation, pagination, ownership checks, response envelopes — diffed across ALL modules at once | ✅ Done — found 4 completely unauthenticated job-trigger endpoints (worse than Phase 08's admin-gap), plus response-envelope inconsistency in Chat+Safety |
| 14 | Final synthesis report | Consolidated findings, safe-to-delete lists, ROI ranking, confidence levels | ✅ Done — see `audit_phase_14_FINAL_REPORT.md` |

## Running totals (cumulative — updated after each phase closes)

| Severity | Count | Phases contributing |
|---|---|---|
| Critical | 2 | 01 (P1-F2: test suite can't run), 06 (P6-F1: block feature doesn't work) |
| High | 14 | 01 (P1-F1), 02 (P2-F1), 03 (P3-F4), 04 (P4-F1), 05 (P5-F1), 06 (P6-F2), 07 (P7-F1), 08 (P8-F1, P8-F2), 09 (P9-F1, P9-F2), 11 (P11-F1, P11-F2), 13 (P13-F1) |
| Medium | 23 | 01 (P1-F3, P1-F4, P1-F5), 02 (P2-F2, P2-F3, P2-F4), 03 (P3-F1, P3-F2, P3-F3, P3-F5), 04 (P4-F2), 06 (P6-F6, P6-F7), 07 (P7-F2, P7-F4), 08 (P8-F3, P8-F4), 09 (P9-F3, P9-F4), 10 (P10-F1, P10-F2), 11 (BUG-020 reconciliation), 13 (P13-F2) |
| Low | 12 | 01 (P1-F6), 02 (P2-F5), 04 (P4-F3), 05 (P5-F2), 06 (P6-F3, P6-F4), 07 (P7-F3, P7-F5), 09 (P9-F5), 12 (5 orphan tables), 13 (P13-F3, P13-F4) |
| Nice to Have | 3 | 05 (P5-F3), 06 (P6-F5), 07 (P7-F6) |

Total findings logged so far: 54 (6/5/5/3/3/7/6/4/5/2/3/1/4 across Phases 01–13). **All 14 module/cross-cutting phases are now complete.** Phase 14 (final synthesis) is next — consolidating all findings into the complete report format the user originally requested. **Headline finding to date (P6-F1, Phase 06):** the user-block feature is completely non-functional across all 3 modules Safety's docs claim it protects. **Phase 08 (P8-F2):** a fully dead parallel News recommendation engine with orphan DB tables. **Phase 09 (P9-F1/P9-F2):** Home Feed's session-taste engine is dead code; its engagement endpoint is a no-op. **Phase 11's headline (P11-F1):** Post visibility (`is_public`/`target_roles`) is enforced in only 1 of ~4 read paths — a "followers only" or "role-restricted" post can leak through the main recommendation feed, direct fetch, and a fully unauthenticated public share-link endpoint. Phase 11 also found (P11-F2) that reporting a post is structurally impossible (int ID vs. required UUID) — combined with Phase 05's fake group-report endpoint, only `target_type="user"` reports actually work anywhere in the app.

Full detail always lives in the phase file — this table is a running scoreboard only.

## Carried-forward open questions (apply across phases — check off when resolved)

1. ~~`app/modules/connections/routes/{connections,recommendations,users}.py`...~~ **RESOLVED in Phase 04 (P4-F1):** confirmed dead — 895 lines across `routes/` + `db/`, a complete first-generation prototype (raw int-ID `"Users"` table, ChromaDB, its own SQLAlchemy engine/Base), zero live callers. Safe to delete pending one external check noted in P4-F1 (whether any frontend/mobile client still calls the old paths — Not Proven from this repo).
2. ~~Recommendation/scoring logic duplication...~~ **RESOLVED in Phase 13:** not duplicated in a problematic sense — each module's approach fits its own data shape (ANN vector search for Post/Connections/Groups, rule-based for News by permanent design). The two real instances already flagged (P8-F2, P7-F2) cover the actual duplication found.
3. ~~Verify 3 untracked architecture docs still match code...~~ **PARTIALLY RESOLVED in Phase 13:** `recommendation_taste_architecture.md` spot-checked and confirmed closely matching Phase 10's independent findings — treat as current. `dynamic_recommendation_architecture.md`/`dynamic_recommendation_flowcharts.md` not read — Not Proven, deprioritized given the corroborating signal from the primary doc.
4. ~~`app/modules/feed/session_taste.py` vs `app/modules/taste/session_taste/**`...~~ **RESOLVED in Phase 09 (P9-F1):** neither is used by the Home Feed's type-mix. `feed/session_taste.py` is fully dead code (zero callers, confirmed by exhaustive grep). The dedicated `taste/session_taste/` package's non-use here is a separate, already-established intentional product decision (Home Feed's type-mix is permanently excluded from the dynamic taste system per prior memory), not a bug.
5. ~~**[Phase 02]** `app/core/rate_limiter.py`...~~ **RESOLVED in Phase 02 (P2-F2):** confirmed real, shipped gap — `/auth/firebase-verify` has zero throttling, matches prior audit's BUG-023, still unfixed.
6. ~~`documentation/BACKEND_AUDIT.md` BUG-029 vs `auth_and_access_control.md`...~~ **RESOLVED in Phase 04:** `auth_and_access_control.md` was right — every `connections/router.py` endpoint wraps its service call in `ok(...)`. BUG-029 is stale/already-fixed.
7. ~~BUG-004 / `ws_router.py`...~~ **RESOLVED in Phase 06:** WebSocket layer is now Socket.IO (`connection_manager.py`); its `connect` handler validates the JWT and refuses unauthenticated sockets. Auth/impersonation angle of BUG-004 is fixed — but Phase 06 found a *different*, more severe authorization gap in the same neighborhood (P6-F1: blocking doesn't work).
8. **[Phase 07]** BUG-013/BUG-016 (`post/service.py`'s `_active_profile_ids()`) were originally diagnosed against `User.is_deleted` — Phase 03 confirmed this column was **dropped entirely** (migration `b4c5d6e7f8a9_remove_soft_delete_from_users.py`, users are hard-deleted now with cascade). Re-diagnose `_active_profile_ids()` fresh; do not assume either bug's original description still applies.
9. **[Phase 11]** BUG-020 (plaintext Aadhaar/PAN/GST document numbers) — Phase 03 confirmed `Profile_Document` no longer exists in `profile/models.py`; the functionality moved to `app/modules/verification/models.py`. Re-diagnose there.
10. ~~`is_deleted` in `connections/service.py`...~~ **RESOLVED in Phase 04:** not a Connections entity at all — `service.py:418` sets `is_deleted=False` on a `chat.data.models.Message` row it creates directly when a message request is accepted with an opening line. Confirms `Message.is_deleted` is a live Chat-module field.
11. ~~`is_deleted` in Chat...~~ **RESOLVED in Phase 06:** `Message.is_deleted` is a real, consistently-used soft-delete flag; no inconsistency with Connections' write of it found.
12. ~~Connections' atomic counters vs Post's...~~ **RESOLVED in Phase 07:** Post's `toggle_like`/`toggle_save` already use the same atomic SQL-update pattern — BUG-010/BUG-011 are fixed. One narrower residual issue found instead (P7-F5: missing `IntegrityError` handling on the insert race, not a counter-corruption issue).
13. **[Phase 11]** Groups' `POST /{group_id}/report` (P5-F1) is a confirmed no-op — needs wiring into the Safety module's real report-creation function (now known: `safety.service.submit_report(db, reporter_id, ReportRequest(...))`, confirmed in Phase 06 while investigating P6-F1 — Phase 11 should confirm this is still the right target and check for other modules that should be calling it but aren't).
14. ~~Block-check coverage in Feed...~~ **RESOLVED in Phase 09:** zero matches for `is_blocked`/`either_blocked` in `feed/`. All three surfaces Safety's docs claim blocking protects (Chat/DMs, Post/sharing, Feed/recommendations) are now confirmed to have zero enforcement — see P6-F1.
15. **[Still open — future fix pass, not this audit]** Group deal *creation* is only reachable via `POST /chat/groups/{group_id}/deals` (Chat router), while every other `GroupDeal` operation lives under `/api/v1/groups/{group_id}/deals/...` (P6-F7). Confirmed still true, no new information in Phase 13.
16. ~~BUG-024 except-pass tally...~~ **RESOLVED in Phase 13:** confirmed in 5 modules total (Connections, Post, Groups, News, Taste) — one consistent fix (add logging) applies to all ~20+ call sites; not re-scored as separate findings per module.
17. ~~Confirm news_recommendation_scores/news_feed_ranking_cache exist via migration...~~ **RESOLVED in Phase 12:** confirmed created by `n5o6p7q8r9s0_add_news_new_tables.py` — real, migrated, schema-present tables, definitively populated-nowhere rather than never-migrated. Phase 12 also found 5 more orphan tables independently (pre-news_new: `news_articles`, `news_sources`, `news_engagement`, `news_trending`, `user_cluster_taste`).
18. ~~Post vs News interaction-batch-processing duplication...~~ **RESOLVED in Phase 13:** structurally similar but independently correct in both places, no divergence bug found — worth a shared-base extraction someday, not urgent.
19. ~~Disabled ConvStatus.ACTIVE pattern tally...~~ **RESOLVED in Phase 13:** confirmed at exactly 4 call sites across 3 modules (Chat ×2, Post, News) — fix once, apply to all 4 together as part of resolving P6-F1.

## How to resume
1. Read this file top to bottom.
2. Read the most recent completed `audit_phase_NN.md` for full context on the latest work.
3. Pick the next "Pending" phase from the table.
4. Investigate per the ground rules: purpose → callers → callees → duplication → dead code → architecture.
5. Write `audit_phase_NN.md` using the same finding format as Phase 01.
6. Update this file: flip the phase to ✅ Done, update running totals, add/resolve open questions.
