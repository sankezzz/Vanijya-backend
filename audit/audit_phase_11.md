# Audit Phase 11 — Safety, Verification, Deeplink Modules

**Status:** Done
**Scope:** `app/modules/safety/{router,service,models,schemas}.py`, `app/modules/verification/{router,service,models}.py`, `app/modules/deeplink/{router,service}.py`

**This phase found two findings significant enough to reach back into already-closed phases (Post, Groups) — flagged clearly below, and both source phase files have been annotated.**

---

## Findings

### P11-F1 — Post visibility (`is_public`, `target_roles`) is a real column but not a real access control — enforced in only one of at least four read paths, and completely absent from the unauthenticated share-link endpoint
**Severity:** High
**Category:** Correctness / Authorization / Missing Connection — **retroactively extends Phase 07 (Post) and touches Deeplink**
**Files:** `app/modules/deeplink/service.py:21-44` (`get_post_share_link`) · `app/modules/post/service.py` (`_get_post_or_raise`, `get_following_feed` — both re-verified this phase, confirmed already read in full in Phase 07) · `app/modules/post/post_recommendation_module/service.py:147-183` (`_query_partition`, no filter) vs. `:410-468` (`_ensure_fresh_in_pool`, the only filtered path)

**Reason:** `Post.is_public` (schema comment: *"True=all users, False=followers only"*) and `Post.target_roles` (*"null=all roles, [1/2/3]=specific roles"*) exist specifically to restrict who can see a post. Grepped every reference to both fields across the Post module to find every place they're actually used, not just stored/serialized:
- `_get_post_or_raise` (used by `GET /posts/{post_id}`, likes, comments, saves, shares, close/reopen — nearly every single-post operation): filters only `Post.id == post_id` (plus the now-pointless `_active_profile_ids` call, P7-F1). **No `is_public`/`target_roles` check at all.**
- `get_following_feed`: filters by `Post.profile_id.in_(followed_profile_ids)` and a date cutoff. **No `target_roles` check** — a post the author marked "Broker only" still appears in a Trader follower's following feed.
- `post_recommendation_module/service.py`'s `_query_partition` — the **main** candidate source for the personalized recommendation feed (hot/warm/cold ANN pool, the bulk of what `get_recommended_posts` serves): filters only `partition`/`is_active`/`exclude_ids`. **No `is_public` filter.** `target_roles` is baked into the post's *vector* (a soft multi-hot similarity signal per `vector.py`'s own comment) — that nudges ranking, it does not exclude a mismatched-role viewer.
- The **only** place either field is used as a hard `WHERE` filter anywhere in Post is `_ensure_fresh_in_pool` (the supplementary "guarantee new posts aren't ANN-starved" path) — `AND p.is_public = true`, plus a Python-side `if target and viewer_role_id not in target: continue`.
- `deeplink/service.py`'s `get_post_share_link` (backing the **fully unauthenticated** `GET /share/post/{post_id}`, no `Depends` at all) fetches `db.query(Post).filter(Post.id == post_id).first()` with **zero visibility check of any kind** and returns the post's title, caption, and image straight back to anyone on the internet who has (or guesses/enumerates — post IDs are sequential integers) a post ID.

**Failure scenario:** A user posts a Deal/Requirement with `is_public=False` (intending "followers only") or `target_roles=[2]` (intending "Brokers only"). Any other logged-in user can still open it directly via `GET /posts/{id}`; it can surface in their personalized recommendation feed regardless of role or follow relationship; and anyone at all — logged in or not — can retrieve its title/caption/image via the public share-link endpoint by guessing a nearby integer ID.

**Recommended fix:** Add an explicit visibility filter everywhere a post can be read by someone who isn't its author: `_get_post_or_raise` should 403/404 when `is_public=False` and the viewer doesn't follow the author (or isn't the author), and when `target_roles` is set and the viewer's role isn't in it; `_query_partition` needs the same `is_public`/`target_roles` filter `_ensure_fresh_in_pool` already has (bringing the two candidate sources in line with each other); `get_following_feed` needs the `target_roles` check; `deeplink/get_post_share_link` needs to decide (product question, not just code) whether a private post should even be shareable via a public link at all, or should require the recipient to be authenticated and eligible.
**Risk:** Low to fix technically; the main cost is deciding the exact intended semantics for the deeplink case (can a followers-only post be "shared" publicly by its own author at all?) before writing the fix.
**Cleanup effort:** Medium (~half a day across the ~4 call sites plus tests).
**Confidence:** Confirmed — every claim above is from a direct grep of every `is_public`/`target_roles` reference in the Post module, cross-checked against the full function bodies already read in Phase 07, not from memory of what those functions "probably" do.
**Action taken:** `tests/audit/audit_phase_07.md` has been annotated with a pointer to this finding, since it reveals a gap in territory that phase already covered.

---

### P11-F2 — The polymorphic report system is structurally broken for `target_type="post"` — post IDs are integers, but `ReportRequest`/`UserReport` both require a UUID
**Severity:** High
**Category:** Correctness / Data Integrity — **touches Post (Phase 07) and compounds Phase 05's group-report finding**
**Files:** `app/modules/safety/schemas.py:11-12` (`ReportRequest.target_id: UUID`), `app/modules/safety/models.py:42` (`UserReport.target_id: Mapped[uuid.UUID]`) vs. `app/modules/post/models.py:34` (`Post.id: Mapped[int]`, plain autoincrement integer, confirmed Phase 07)

**Reason:** `VALID_TARGET_TYPES = {"user", "group", "post"}` and the schema's own regex accepts `target_type="post"`. `User.id` and `Group.id` are both UUIDs (confirmed Phases 02/05), so reporting those works. But `Post.id` is a plain autoincrementing integer — there is no way to construct a valid `ReportRequest` with `target_type="post"` and a real post's actual ID, because Pydantic's `UUID` field type will reject an integer like `42` before the request ever reaches `submit_report()`. Every attempt to report a post via `POST /safety/report` fails with a 422 validation error, regardless of which post ID is supplied.

**Why this is worth flagging alongside P5-F1 (Groups' fake report endpoint):** two of the three documented report target types are now confirmed broken in two different ways — Groups' own `/report` endpoint doesn't call Safety at all and fakes success (P5-F1); Post has no dedicated report endpoint of its own, so it can only be reported through Safety's polymorphic one, which cannot represent a post's ID at all. **Only `target_type="user"` reporting is confirmed to actually work end-to-end.** This is a significant gap in a moderation/trust-and-safety feature for a marketplace app.
**Recommended fix:** Either change `Post.id` to a UUID (a real migration, breaking change, likely overkill just for this) or change `UserReport.target_id`/`ReportRequest.target_id` to a more permissive type (e.g., `str`) that can hold either a UUID string or an integer string, with `target_type`-conditional validation. The latter is much less invasive.
**Risk:** Low to fix (schema/model change, no data migration needed if choosing the `str` route — existing rows are all UUIDs already and remain valid strings).
**Cleanup effort:** Small (~1 hr for the schema fix; needs a decision on which approach first).
**Confidence:** Confirmed (`Post.id`'s type re-verified directly against Phase 07's model read; `ReportRequest`/`UserReport`'s `UUID` typing read directly this phase).
**Action taken:** Noting here rather than reopening Phase 05/07 with a new finding number there — this is fundamentally a Safety-module schema decision, just evidenced by Post's model shape.

---

### Reconciliation — BUG-020 (plaintext Aadhaar/PAN/GST/IEC), resolved location from Phase 03
**Severity:** Medium (unchanged from original)
**Category:** Security — Sensitive Data Storage
**Files:** `app/modules/verification/models.py:18` (`VerificationRecord.document_number`), `:30` (`api_response`), `service.py:171,174`

**Reason:** Phase 03 confirmed the old `Profile_Document` model no longer exists and that this functionality moved to `app/modules/verification/`. Confirmed here: `VerificationRecord.document_number` is a plain `String(100)`, and `service.py`'s `verify_document()` does `record.document_number = document_number` — no hashing, masking, or encryption at any point. **Additionally** (beyond the original bug's scope): `api_response: Mapped[Optional[dict]] = mapped_column(JSON, ...)` stores the **entire raw response** from the third-party KYC provider (Surepass) — for PAN verification this plausibly includes full name, DOB, and other identity data beyond just the number itself, compounding the exposure the original bug described.
**Recommended fix:** Same as originally suggested (BUG-020's own priority list: "Encrypt document numbers at rest"), extended to also consider whether the full `api_response` payload needs the same treatment or should be trimmed to only what's needed for audit.
**Risk:** Medium to fix — needs a key-management decision (app-level encryption key, KMS, etc.), not just a code change.
**Cleanup effort:** Medium (~1 day incl. picking an encryption approach and a migration for existing rows).
**Confidence:** Confirmed (both fields read directly, write-site read directly).

---

## Reinforcing evidence for already-established cross-cutting patterns (not re-scored as new findings)
- **Config-loading inconsistency (P1-F1):** `verification/service.py:14,19` reads `SUREPASS_BASE_URL`/`SUREPASS_TOKEN` via raw `os.getenv()`, a fourth-plus instance of bypassing the `Settings` class — tallying for Phase 13, not re-flagged individually here.
- **Missing rate limiting on cost-incurring third-party calls (P2-F2, P8-F1):** `POST /verification/kyc/*` proxies to Surepass (a paid API) with no throttling and no dedupe-cooldown on resubmission of the same document — same unaddressed class of issue as the Auth and News-admin findings, not re-scored separately.

## What's solid (no action needed)
- Safety's block/report endpoints are all correctly JWT-gated, with no path/query-param identity — clean, matches the rest of the post-remediation codebase.
- `verify_document`'s KYB-requires-KYC-first rule and role-based document-type enforcement (`_ROLE_KYB_DOC`) are sensible, correctly-ordered business rules with clear error messages.
- Deeplink's actual link/text-generation logic (truncation, fallback text for missing fields) is simple and correct — the only issue found here is the missing visibility check (P11-F1), not the linking logic itself.

## Phase 11 summary
- 3 scored findings: **2 High (P11-F1, P11-F2), 1 Medium (reconciled BUG-020).**
- Both High findings required reopening already-closed phases (07, 05) with new evidence — both source phase files annotated with pointers rather than duplicating full detail there.
- Nothing found blocks moving on to Phase 12.
