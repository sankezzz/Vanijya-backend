# 30 — Known Limitations

An honest, consolidated list of what this app currently does not do correctly or completely, gathered from two sources with different methodologies — worth telling apart:

- **The prior architectural audit** (`audit/audit_phase_01.md` through `audit_phase_14_FINAL_REPORT.md`) was a systematic, 14-phase, evidence-based pass across the *entire* repository, specifically looking for this category of problem. Its 54 findings (2 Critical, 14 High, 23 Medium, 12 Low, 3 Nice-to-Have) are the authoritative, exhaustive source — this chapter summarizes and cross-references them, but `audit/audit_phase_14_FINAL_REPORT.md` has the full evidence, ROI ranking, and code-reduction estimate, and isn't fully reproduced here.
- **New items this handbook found incidentally**, while verifying claims for other chapters — not from a dedicated search for problems, so this list should not be read as exhaustive the way the audit's is. Each is marked as such below.

## Critical (from the audit — fix first)

| Finding | What | Where discussed here |
|---|---|---|
| P1-F2 | The test suite cannot run at all — `conftest.py` patches a symbol removed during the News module rewrite | [Deployment](26_Deployment.md), [Common Debugging](28_Common_Debugging.md) |
| P6-F1 | The block feature is completely non-functional — enforcement check commented out, nothing sets the status it checks | [Authorization](15_Authorization.md), [Event Flows](20_Event_Flows.md) — this handbook independently re-confirmed the chat side of this gap while researching Authorization |

## High (from the audit)

| Finding | What | Where discussed here |
|---|---|---|
| P1-F1 | Three parallel config-loading strategies; one `Settings` class is fully dead | [Configuration](24_Configuration.md) — this handbook independently re-verified and extended this with the `GOOGLE_SERVICE_ACCOUNT_JSON` double-read example |
| P3-F4 | A hard `os.environ[...]` subscript in `shared/utils/storage.py` crashes the entire app at boot if unset | [Startup Process](05_Startup_Process.md), [Image Uploads](21_Image_Uploads.md) |
| P4-F1 | ~895 lines of dead first-generation Connections prototype (raw int IDs, its own ChromaDB/Postgres setup) | [Modules](11_Modules.md) |
| P5-F1 | Reporting a group is a complete no-op returning a fake success | [Feature Guide](10_Feature_Guide.md) |
| P6-F2 | Two DM-creation implementations exist; the live one bypasses the message-request consent gate | [Feature Guide](10_Feature_Guide.md) |
| P8-F1 | News "admin" endpoints gated only by "is logged in" — no admin-role concept exists anywhere in the app | [Authorization](15_Authorization.md) |
| P8-F2 | An entire parallel News recommendation engine is fully built and mostly dead — **with one correction**: `profile_scorer.py` inside that same package is live and actively used by the real feed, contrary to this finding's original "zero live callers" framing at the file level | [Recommendation Engine](19_Recommendation_Engine.md), [Modules](11_Modules.md) |
| P9-F1, P9-F2 | Feed's own session-taste engine is fully dead code; the feed engagement-submission endpoint is a confirmed no-op | [Feature Guide](10_Feature_Guide.md) |
| P11-F1 | Post visibility (`is_public`/`target_roles`) is enforced in only one of ~4 read paths, including zero enforcement on the public unauthenticated share-link endpoint | [Authorization](15_Authorization.md) |
| P11-F2 | Reporting a post is structurally impossible — post IDs are integers, the report schema requires a UUID | [Feature Guide](10_Feature_Guide.md) |
| P13-F1 | Four background-job-triggering endpoints have **zero** auth dependency — not even login required | [Authorization](15_Authorization.md), [Background Jobs](18_Background_Jobs.md) |

## Medium (from the audit — condensed; see the audit's own report for the full 23)

Rate limiter fully built, wired into zero endpoints (P1-F4, see [Caching](16_Caching.md)/[Redis](17_Redis.md)) · No rate limiting on Firebase OTP verification (P2-F2, see [Authentication](14_Authentication.md)) · `/auth/dev-token` full-auth-bypass gated only by a raw env var (P2-F4, see [Authentication](14_Authentication.md)) · Commodity name→ID cache has no invalidation (P10-F1, see [Caching](16_Caching.md) — re-verified unchanged) · News' own persistent per-category taste table has a dead read path (P10-F2, see [Recommendation Engine](19_Recommendation_Engine.md) — re-verified still accurate) · Plaintext KYC document numbers + full raw provider response stored (BUG-020) · Real-time layer is explicitly single-worker-only, self-documented (P6-F6, see [Runtime Architecture](06_Runtime_Architecture.md)/[Event Flows](20_Event_Flows.md)) · Two routers never adopted the `ok()` response envelope (P13-F2).

## New limitations found while writing this handbook (not from a dedicated audit pass)

| What | Severity (this handbook's own judgment) | Where |
|---|---|---|
| `GroupActivityCache` rows are written once at creation (all zero) and never refreshed by anything — the "activity" half of group-suggestion ranking (nominally 25% of the score) is mathematically always exactly `0.0` in the current code | Medium — a real, silent ranking-quality gap, not a crash | [Caching](16_Caching.md), [Recommendation Engine](19_Recommendation_Engine.md) |
| `ACCESS_TOKEN_EXPIRE_MINUTES = 600` in `app/core/config.py` has an inline comment reading `# 1 hour` — 600 minutes is 10 hours. The value (not the comment) is what's actually used | Low — a misleading comment, not a functional bug, but worth fixing so nobody sizes a security decision off the comment | [Authentication](14_Authentication.md) |
| Logging out flips a session's `is_active` flag (blocking future refresh) but does **not** invalidate the access token already issued for that session — `decode_access_token` never queries the database, by design. Combined with the 10-hour token lifetime above, a "logged out" session's last access token remains fully usable for up to 10 hours afterward | Medium — a real security-relevant timing window, not previously called out this precisely | [Authentication](14_Authentication.md) |
| `app/core/redis_client.py`'s own module docstring claims it's used for "session taste + seen-sets" — the seen-sets half is stale; post-seen tracking is a real Postgres table plus an in-memory per-request set, not Redis | Low — a stale comment | [Redis](17_Redis.md) |
| `search_suggestions`'s docstring says "prefix suggestions"; the actual query is a substring `ILIKE '%q%'` | Low — a stale comment, minor behavioral surprise | [Search](22_Search.md) |
| Both `ILIKE` substring searches (Connections' name/business-name search) run with no supporting `GIN`/trigram index in any tracked migration — a leading-wildcard pattern can't use a normal index, so these are sequential scans today | Low today, worth watching as the `profile`/`business` tables grow | [Search](22_Search.md) |
| An FCM device token is collected and stored (`User.fcm_token`) but nothing anywhere calls Firebase Cloud Messaging to actually send a push notification, and there's no in-app notification inbox either | Medium — a fully one-sided pipeline; likely to surprise anyone who assumes "the token is collected" implies "push works" | [Notifications](23_Notifications.md) |
| `render.yaml` declares only 2 of the roughly 15 environment variables this app actually reads; everything else must already be configured by hand in Render's dashboard, invisibly to the tracked repository | Low — an operational/onboarding friction point, not a runtime bug | [Deployment](26_Deployment.md) |
| No CI pipeline and no `Dockerfile` exist anywhere in the repository — the only gate between a push and a live deploy is Render's own build step succeeding, with no automated test run (compounded by the test suite being unable to run at all — P1-F2 above) | Medium — a real process gap, not a code defect | [Deployment](26_Deployment.md) |

## What was explicitly checked and found solid (worth stating, so this list doesn't read as universally bleak)

The prior audit's own summary is worth repeating here: **nothing found suggests systemic incompetence.** Several areas hold up well under close reading — Post's atomic counter updates, the taste system's confidence-gated multi-layer blend and its genuine repository-pattern discipline, Groups' shared `_handle` error-translation dispatcher, the signed-upload-URL pattern's careful three-way `object_exists` result handling, and the deliberate fire-and-forget design of every taste-signal write (a Redis outage degrades a boost, it never breaks the action that triggered it). The problems catalogued in this chapter are real and worth fixing, but they sit alongside code that was built carefully — see [Architecture Decisions](31_Architecture_Decisions.md) for the reasoning behind the choices that worked out well, not only the ones that didn't.

---
**Previous:** [29 — FAQs](29_FAQs.md) · **Next:** [31 — Architecture Decisions](31_Architecture_Decisions.md)
