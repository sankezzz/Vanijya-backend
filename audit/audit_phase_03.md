# Audit Phase 03 — Profile Module

**Status:** Done
**Scope:** `app/modules/profile/**` (models.py, router.py, schemas.py, service.py)

---

## Files inspected

| File | Purpose | Verdict |
|---|---|---|
| `app/modules/profile/models.py` | `User`, `Role`, `Commodity`, `Interest`, `Profile`, `Business`, `Profile_Commodity`, `Profile_Interest`, `UserEmbedding` | Live, correct. `User` no longer has `is_deleted`/`deleted_at` (see reconciliation) |
| `app/modules/profile/router.py` | 11 endpoints: onboarding (user/profile create), me, update, fcm-token, avatar upload flow, delete profile/user, public view by profile_id or user_id | Live, correctly JWT-gated throughout — matches `auth_and_access_control.md`. See P3-F5 |
| `app/modules/profile/service.py` | All profile/user business logic + embedding rebuild + Supabase avatar flow | Live — 3 confirmed-still-open bugs, see P3-F1/F2/F3 |
| `app/modules/profile/schemas.py` | Request/response models | Live, correct, no duplication with other modules' schemas found |

---

## Reconciliation with `documentation/BACKEND_AUDIT.md` (Profile's bugs: BUG-001, 017, 018, 020, 027, 033)

| Bug | Status now | Evidence |
|---|---|---|
| BUG-001 (no auth, `Query(user_id)` everywhere) | **Fixed**, confirmed | Every endpoint in `router.py` uses `Depends(get_current_user)` / `get_onboarding_user_id` / `get_onboarding_claims` — zero `Query(user_id)` patterns remain. |
| BUG-012 *(filed under Profile in the old doc's body, though the Issue Map table doesn't list it under Profile — it's `create_profile`'s two-commit issue)* | **Still present**, refined — see P3-F1 | Structural issue unchanged; the specific originally-cited trigger (`int(None)` from a null `quantity_min`) no longer applies since `ProfileCreate.quantity_min/quantity_max` are required `float` fields — but the general risk (any exception between the two commits leaves a profile durably saved with no embedding) is still real for other failure modes inside `_upsert_user_embedding`. |
| BUG-017 (truthiness bug: `if qmin and qmax and qmin > qmax`) | **Still present**, exact line match | `service.py:344`, character-for-character the same defect. |
| BUG-018 (bare `assert profile_resp is not None`) | **Still present**, exact line match | `service.py:390`. |
| BUG-020 (plaintext Aadhaar/PAN/GST in `Profile_Document`) | **Stale reference** — moved, not fixed or disproven | `Profile_Document` no longer exists in `profile/models.py` at all. Document storage now lives in `app/modules/verification/models.py` (confirmed via grep: `document_number`/`Profile_Document`-style fields only appear under `verification/`). Whether the plaintext-storage defect itself persists in the new location is **carried to Phase 11**, not resolved here. |
| BUG-027 (`os.environ[]` hard subscript crashes app at import) | **Stale reference, defect persists, blast radius increased** — see P3-F4 | The exact hard-subscript code (`os.environ["DATABASE_STORAGE_URL"]`, `os.environ["DATABASE_SERVICE_KEY"]`) is no longer at `profile/service.py:14-16` — profile's own line 21 now correctly uses `os.environ.get(..., "avatars")` with a default. The hard subscript moved (or was always partly) to the shared `app/shared/utils/storage.py:28-31`, which Phase 01 already read but deliberately deferred correctness review on (see Phase 01's files-inspected table). Since that module is now imported by **profile, groups, post, and chat** (Phase 01 grep), a missing env var crashes the whole app at startup via any of those four import chains — a larger blast radius than the original single-module diagnosis. |
| BUG-033 (`delete_user` doesn't clear `access_token`/`fcm_token`) | **Fixed — architecturally, not via the doc's suggested patch** | Migration `alembic/versions/b4c5d6e7f8a9_remove_soft_delete_from_users.py` (2026-04-24, one day after the original audit) dropped `is_deleted`/`deleted_at` from `users` entirely: *"User accounts are now hard-deleted — the row is removed and all related data is cleaned up by the existing ON DELETE CASCADE foreign keys."* `delete_user()` now does a real `db.delete(user)` (service.py:409-418). There is no `access_token`/`fcm_token` left to "not clear" — the whole row is gone. **This also means BUG-013 and BUG-016 (both about `_active_profile_ids()` filtering on `User.is_deleted`) reference a column that no longer exists** — flagging as a required fresh-diagnosis item for Phase 07 (Post module), not assuming either bug's original description still applies. |

Also cross-checked `documentation/gaps.md`'s Profile section (3 of its 5 listed gaps) against current schemas: gap #1 ("`ProfileResponse` missing `posts_count`") and gap #2 ("`ProfilePublicResponse` missing `followers_count`") and gap #3 ("`GET /profile/me` missing `phone_number`/`country_code`") are **all already fixed** — `ProfileResponse` (schemas.py:81-102) and `ProfilePublicResponse` (schemas.py:105-127) both carry all of these fields now. Further evidence that `gaps.md` reflects an older snapshot of the code than what's on disk today — treat it as historical, not current, consistent with the caution already recorded in `AUDIT_PROGRESS.md`.

---

## Findings

### P3-F1 — `create_profile` still has the two-commit non-atomicity (reconciles prior "BUG-012"-style finding: Still Present, narrower trigger)
**Severity:** Medium (downgraded from the prior audit's High, given the originally-cited exact trigger no longer applies)
**Category:** Transaction Integrity
**Files:** `app/modules/profile/service.py:271-314` (`create_profile`)

**Reason:** `db.commit()` at line 302 durably saves the profile/business/commodities/interests. `_upsert_user_embedding(db, user_id)` runs after, followed by a second `db.commit()` at line 306. Both are inside one `try/except Exception: db.rollback(); raise` block — but `rollback()` after the first `commit()` has already landed cannot undo it. If `_upsert_user_embedding` (or the second commit itself) raises for any reason, the profile exists but has no `UserEmbedding` row, and the caller sees a 500 with no indication the profile was actually created.

**What changed since the original finding:** `ProfileCreate.quantity_min`/`quantity_max` (schemas.py:66-67) are required, non-optional `float` fields, so the specific `int(None)` `TypeError` the original bug cited can no longer happen via that path. The structural risk remains for other failure modes inside `build_candidate_vector`/`build_user_feed_vector` (e.g. a future commodity list edge case) or a transient DB error on the second commit.

**Recommended fix:** Merge into a single transaction — compute the embedding vectors before the first `db.commit()`, add the `UserEmbedding` row alongside the profile/business/junction rows, and commit once.
**Risk:** Low to fix (single-transaction refactor, no external contract change).
**Cleanup effort:** Small (~30–45 min).
**Confidence:** Confirmed (read the full function).

---

### P3-F2 — Truthiness bug in quantity-range validation lets `quantity_max=0` bypass the check (reconciles BUG-017: Still Present)
**Severity:** Medium
**Category:** Validation
**Files:** `app/modules/profile/service.py:344`

**Reason:** `if qmin and qmax and qmin > qmax: raise ProfileValidationError(...)`. In Python, `0` is falsy, so `quantity_min=5, quantity_max=0` short-circuits the condition to `False` before the `>` comparison ever runs, and the invalid range is persisted silently. Identical defect to the prior audit's BUG-017, unchanged.
**Recommended fix:** `if qmin is not None and qmax is not None and qmin > qmax:`.
**Risk:** None to fix.
**Cleanup effort:** Trivial (one-line change).
**Confidence:** Confirmed (exact line read).

---

### P3-F3 — Bare `assert` in a production code path (reconciles BUG-018: Still Present)
**Severity:** Medium
**Category:** Crash / Unhandled Exception
**Files:** `app/modules/profile/service.py:390`

**Reason:** `assert profile_resp is not None` inside `update_profile`, after re-fetching the just-updated profile. Python's `assert` is (a) stripped entirely under `-O`, and (b) raises a bare `AssertionError` rather than one of this module's own typed exceptions (`ProfileNotFoundError` etc.), so FastAPI returns an opaque 500 with no detail instead of a clean 404/409.
**Recommended fix:** `if profile_resp is None: raise ProfileNotFoundError("Profile not found after update")`.
**Risk:** None.
**Cleanup effort:** Trivial.
**Confidence:** Confirmed (exact line read).

---

### P3-F4 — Shared storage module still hard-crashes the whole app on a missing env var, now with 4x the blast radius (reconciles BUG-027: Still Present, relocated, worse)
**Severity:** High (raised from the original Medium, given confirmed blast-radius increase)
**Category:** Configuration / Crash / Architecture
**Files:** `app/shared/utils/storage.py:28-31`

**Reason:** 
```python
_client: Client = create_client(
    os.environ["DATABASE_STORAGE_URL"],
    os.environ["DATABASE_SERVICE_KEY"],
)
```
This executes at **module import time** (module-level statement, not inside a function). `os.environ[...]` (vs. `.get()`) raises `KeyError` immediately if either var is unset — and because this is a shared utility, it's now transitively imported by **profile, groups, post, and chat** (confirmed via Phase 01's grep of `shared.utils.storage` importers: `chat/service.py`, `groups/service.py`, `profile/service.py`, `post/service.py`, `chat/data/repository.py`). Since `main.py` imports all of those routers at module load, a missing `DATABASE_STORAGE_URL` or `DATABASE_SERVICE_KEY` crashes the **entire application** before any route is registered — not just profile's avatar upload, which is where the original audit scoped the impact.
**Recommended fix:** `os.environ.get("DATABASE_STORAGE_URL")` with an explicit, clear startup-time check (e.g. in `app/core/config.py`'s `Settings`, following the same consolidation recommended in Phase 01's P1-F1), so a missing var fails with one clear message instead of a raw `KeyError` traceback from deep inside an import chain.
**Risk:** Low to fix — this only changes *how* a misconfiguration is reported, not any success-path behavior.
**Cleanup effort:** Small (~20–30 min).
**Confidence:** Confirmed (re-read the exact lines; cross-referenced Phase 01's importer list).

---

### P3-F5 — `get_profile_by_id` and `get_profile_by_user_id` are ~80 lines of near-verbatim duplicated logic
**Severity:** Medium
**Category:** Duplicate Logic / Maintainability
**Files:** `app/modules/profile/service.py:421-499` (`get_profile_by_id`) vs. `502-580` (`get_profile_by_user_id`)

**Reason:** The two functions are identical except for which column resolves the target profile (`Profile.id == profile_id` vs. `Profile.users_id == user_id`). Everything after that — the post-page query + cursor logic, the `is_following` check, the `message_request_status` lookup (including the same bidirectional `MessageRequest` OR-query), the `_batch_feed_cards` call, and the full `ProfilePublicResponse(...)` construction (14 fields) — is copy-pasted line for line between the two functions. Both are called from two correspondingly near-duplicate router endpoints (`GET /profile/{profile_id}` and `GET /profile/by-user/{user_id}`, `router.py:224-268`), each with its own copy of the "redirect to /profile/me if viewing self" check.

**Why it matters:** Any future change to how a public profile is assembled (the exact bug class this audit is hunting for) has to be made twice, correctly, in sync, or the two lookup paths silently diverge — one of the two `ProfilePublicResponse` construction sites will drift from the other exactly the way BUG-029-style envelope drift happened elsewhere in this codebase.

**Recommended fix:** Have `get_profile_by_user_id` resolve `user_id` → `profile_id` with a single-column lookup (`db.query(Profile.id).filter(Profile.users_id == user_id).first()`, already a pattern used elsewhere in this same file as `get_profile_id_for_user`) and then delegate to `get_profile_by_id` for everything else. Same consolidation at the router layer.
**Risk:** Low — behavior-preserving refactor, both endpoints keep their current external contract.
**Cleanup effort:** Small (~45 min incl. testing both routes still 404 correctly for a nonexistent target).
**Confidence:** Confirmed (both full function bodies read and compared line by line).

---

## What's solid (no action needed)
- Onboarding flow (`create_user` → `create_profile` → session issuance) is coherent and correctly sequenced; `create_profile`'s response bakes a fresh access/refresh token pair using the newly created `profile.id`, avoiding a chicken-and-egg identity problem.
- `_validate_role` / `_validate_ids` give real DB-existence validation for `role_id`/`commodities`/`interests` at the service layer — notably, this is validation the Post module's `BUG-031` (category_id/commodity_id accepted without existence check) explicitly lacks; Profile got this right and Post didn't, worth a direct comparison note in Phase 07.
- `update_profile`'s commodities/interests diffing (`current - requested` / `requested - current`) is a clean, correct set-diff pattern — no wasted delete-then-reinsert-everything.
- Avatar upload/save flow has sensible retry-with-backoff on the storage-existence check and correctly distinguishes infra failure (`None` → 503) from a genuinely missing file (`False` → 400) — no issues found.

## Unresolved questions handed to later phases
1. **[Phase 07]** BUG-013/BUG-016 (`post/service.py`'s `_active_profile_ids()`) were originally diagnosed against `User.is_deleted`, a column confirmed **removed** in this phase (migration `b4c5d6e7f8a9`). Phase 07 must re-diagnose `_active_profile_ids()` fresh against current code — do not assume either bug's original description still applies.
2. **[Phase 11]** BUG-020 (plaintext Aadhaar/PAN/GST) — re-diagnose against `app/modules/verification/models.py`, where this functionality now actually lives.
3. **[Phase 04]** `is_deleted` still appears in `connections/service.py` — unrelated to the User-table removal in this phase (likely a different entity's soft-delete, e.g. a connection/follow row) — confirm what it's soft-deleting when Phase 04 runs.
4. **[Phase 06]** `is_deleted` also appears in `chat/domain/entities.py`, `chat/data/repository.py`, `chat/data/models.py` — same as above, confirm scope in Phase 06.

## Phase 03 summary
- 5 findings: **1 High (P3-F4, raised from the prior audit's Medium due to confirmed larger blast radius), 4 Medium (P3-F1, P3-F2, P3-F3, P3-F5).**
- 4 of 5 reconcile the prior audit (BUG-012-style two-commit issue, BUG-017, BUG-018, BUG-027); one is new (P3-F5, duplicated public-profile logic).
- One bug (BUG-033) fully resolved by an architectural decision (hard-delete migration) rather than the doc's suggested patch — worth knowing so nobody re-applies a now-irrelevant fix.
- One bug (BUG-020) confirmed moved to a different module, not yet re-verified.
- Nothing found blocks moving on to Phase 04.
