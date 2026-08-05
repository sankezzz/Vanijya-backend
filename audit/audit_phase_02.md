# Audit Phase 02 — Auth Module

**Status:** Done
**Scope:** `app/modules/auth/**` (models.py, router.py, schemas.py, service.py, service_msg91.py)

---

## Major methodological discovery this phase: a prior audit already exists in the repo

While tracing `service_msg91.py`'s config usage, a grep surfaced `documentation/BACKEND_AUDIT.md` — a **475-line, 37-bug prior audit** of this exact codebase (dated 2026-04-23, with a "Phase 2" fix-update dated 2026-05-12), plus `documentation/gaps.md` (frontend/backend contract gap analysis), `documentation/security.md` (despite the name, this is actually Safety-module — block/report — API documentation, not a security audit), and `documentation/auth_and_access_control.md` (243 lines, dated 2026-05-12, documents the post-fix auth dependency architecture).

**This changes how every remaining phase must work.** From here on, each phase cross-checks `documentation/BACKEND_AUDIT.md`'s "Issue Map by Module" table for that module's `BUG-###` entries and reconciles each as:
- **Fixed** — confirmed resolved in current code
- **Still present** — confirmed still reproducible, code may or may not have changed since
- **Stale reference** — the file/line cited no longer exists in this shape (module renamed/moved), needs re-diagnosis in current terms

This is now recorded as a standing instruction in `AUDIT_PROGRESS.md`. Full list of `documentation/*.md` files and which phase will consume each is also tracked there — not re-listed here to avoid drift between the two files.

**Why this matters, concretely:** the prior audit's own BUG-009 ("JWT has no expiry") is **already fixed** — `jwt_handler.py` issues tokens with a proper `exp` claim (confirmed read in Phase 01) — but the document doesn't mark it fixed. If a future session (or a human) treated `BACKEND_AUDIT.md` as current truth without re-verification, they could waste time "fixing" an already-fixed issue, or worse, miss that some *other* unmark-fixed bug actually is still live. Every claim in that document is being treated as **Plausible, dated, needs re-verification** — same confidence discipline as everywhere else in this audit.

---

## Files inspected

| File | Purpose | Verdict |
|---|---|---|
| `app/modules/auth/router.py` | 4 endpoints: `/auth/dev-token`, `/auth/firebase-verify`, `/auth/refresh`, `/auth/logout` | Live. See P2-F4, P2-F5 |
| `app/modules/auth/service.py` | Firebase token verification, session create/refresh/revoke | Live, correct — except P2-F3 |
| `app/modules/auth/service_msg91.py` | MSG91 SMS-OTP send/verify + dev in-memory OTP store | **Dead (zero callers) and would crash if called.** See P2-F1 |
| `app/modules/auth/models.py` | `UserSession` ORM model | Live, correct, sensible indexes/constraints |
| `app/modules/auth/schemas.py` | Request/response Pydantic models for the 4 router endpoints | Live, correct |
| `app/modules/auth/__init__.py` | empty | Fine |

---

## Findings

### P2-F1 — `service_msg91.py` is dead code that would crash on first use (reconciles BUG-008: Still Present)
**Severity:** High
**Category:** Dead Code / Configuration
**Files:** `app/modules/auth/service_msg91.py:27,35,38,54,70`

**Reason:** `send_otp()` and `verify_otp()` read `settings.DEV_MODE`, `settings.MSG91_AUTH_KEY`, `settings.MSG91_TEMPLATE_ID`. None of these three fields exist on `app/core/config.py`'s `Settings` class (confirmed by the full read of that class in Phase 01 — its fields are `DATABASE_URL, SYNC_DATABASE_URL, REDIS_URL, GOOGLE_SERVICE_ACCOUNT_JSON, ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS, GEMINI_API_KEY, GNEWS_API_KEY, GROQ_API_KEY, SENTRY_DSN, ENVIRONMENT, SENTRY_TRACES_SAMPLE_RATE, SENTRY_PROFILES_SAMPLE_RATE` — no `DEV_MODE`/`MSG91_*`). `Settings.Config.extra = "ignore"` means unknown env vars are silently dropped, not exposed as attributes, so `settings.DEV_MODE` raises `AttributeError` at the first line of either function.

**Confirms prior audit's BUG-008 exactly**, and its own root-cause note ("dead code since auth was migrated to Firebase") — verified independently: `grep -rn "service_msg91|send_otp|verify_otp\b"` across the whole tree matches only the definitions inside the file itself. `auth/router.py` imports exclusively from `auth/service.py` (the Firebase-based path).

**Recommended fix:** Since this is confirmed dead (no callers) and the project has fully committed to Firebase phone-auth (per `service.py`, `documentation/auth_and_access_control.md`), delete `service_msg91.py` rather than fix its config — fixing it would maintain a second, parallel, currently-pointless OTP mechanism. If MSG91 is wanted as a Firebase fallback later, it should be rebuilt against the current `Settings` class deliberately, not patched back to life as-is.
**Risk:** None (no callers).
**Cleanup effort:** Trivial (delete one file).
**Confidence:** Confirmed (own independent grep/read, cross-validated against `BACKEND_AUDIT.md`'s identical finding from 3 months earlier — unchanged since).

---

### P2-F2 — `/auth/firebase-verify` has no rate limiting (reconciles BUG-023: Still Present; resolves Phase 01 open question #5)
**Severity:** Medium
**Category:** Missing Connections / Security
**Files:** `app/modules/auth/router.py:67-126`, `app/core/rate_limiter.py`

**Reason:** `firebase_verify()` has no call to `rate_limiter.check(...)` (or any other throttle) before verifying the Firebase token and querying/creating a session. Phase 01 (P1-F4) found `app/core/rate_limiter.py`'s `RateLimiter` has zero callers anywhere in `app/` and flagged "is this a real gap or just dead code" as an open question for this phase. Answer: **it's a real, shipped gap** — this is exactly the endpoint the limiter's own docstring example was written for, and it's unprotected. This matches the prior audit's BUG-023 (phone-number enumeration via `is_new_user: true/false`, unlimited replay attempts) — still unaddressed 3 months later.

**Recommended fix:** Wire `rate_limiter.check(redis, f"ip:{request.client.host}", limit=..., window=...)` into `firebase_verify`, keyed by IP (already available via the `request: Request` parameter already present in the signature) and/or by the phone number extracted from the verified Firebase token.
**Risk:** Low — additive, no existing behavior changes for callers under the limit.
**Cleanup effort:** Small (~30–45 min incl. picking sane limit/window values).
**Confidence:** Confirmed (read full router; zero rate-limiter references).

---

### P2-F3 — Non-Indian country-code parsing is still a tautological no-op (reconciles BUG-019: Still Present, code changed since original finding)
**Severity:** Medium
**Category:** Correctness / Stale Fix Attempt
**Files:** `app/modules/auth/service.py:59-64`

**Reason:** Current code:
```python
if phone.startswith("+91"):
    country_code = "+91"
    phone_number = phone[3:]
else:
    country_code = phone[:3] if len(phone) > 3 and phone[3:4].isdigit() else phone[:3]
    phone_number = phone[len(country_code):]
```
Both branches of the ternary on line 63 evaluate to `phone[:3]` — the condition (`len(phone) > 3 and phone[3:4].isdigit()`) is checked but its result changes nothing. This is a **different exact condition string than the prior audit recorded** (`phone[2].isdigit() and phone[3:4].isdigit()`) — meaning someone edited this line since the 2026-04-23 audit — but the edit didn't fix the underlying defect, it just changed which unused condition is being ignored. Any non-`+91` number still gets its country code hard-parsed as exactly 3 characters. 2-digit country codes (`+1` US/Canada, `+7` Russia/Kazakhstan, and others) lose their first phone digit into the (wrong) country_code field.

**Failure scenario:** A `+1` (US) user's Firebase-verified phone `+14155552671` → this branch computes `country_code = phone[:3]` = `"+14"` (wrong — should be `"+1"`), `phone_number = phone[3:]` = `"155552671"` (missing the leading `4`). Every subsequent DB lookup by `(country_code, phone_number)` for that user will never match a previously-stored row, so returning users from 2-digit-country-code regions are always treated as brand new (or never found at all) — consistent with the original audit's stated user impact.

**Recommended fix:** Replace with a real E.164 prefix table (or a phone-parsing library, e.g. `phonenumbers`) instead of positional slicing.
**Risk:** Low to fix — the change is isolated to this parsing function, but should be paired with a data-backfill check for any existing non-`+91` rows that may have been mis-parsed already (Not Proven whether any such rows exist — would need a DB query to check, out of scope for a static audit).
**Cleanup effort:** Small (~1 hr with a proper library; the harder part is verifying/fixing already-mis-stored rows).
**Confidence:** Confirmed for the code defect (read directly). Not Proven whether any production rows are currently affected (would require DB access).

---

### P2-F4 — `/auth/dev-token` is a full auth-bypass endpoint gated only by a raw env var (new finding, not in prior audit)
**Severity:** Medium (latent — see likelihood note; would be Critical if triggered)
**Category:** Security / Architecture
**Files:** `app/modules/auth/router.py:36-60`

**Reason:** `GET /auth/dev-token?name=<profile name>` looks up a `Profile` by case-insensitive name match and mints a **real, fully valid** `create_access_token(...)` for that profile — indistinguishable from a legitimately issued token — with no password, OTP, or ownership check of any kind. The only gate is:
```python
if os.getenv("DEBUG", "").lower() != "true":
    raise HTTPException(status_code=404, detail="Not found")
```
No other authentication, rate limit, or audit log applies to this route.

**Likelihood assessment (why this isn't Critical):** the tracked `render.yaml` deploy config does not set `DEBUG` at all and explicitly sets `ENVIRONMENT: production`, so the documented deploy path is safe by default (route 404s). However, `render.yaml` marks `DATABASE_URL` as `sync: false` (i.e., set manually in the Render dashboard, outside this file) — establishing that manual, undocumented env var overrides are already a normal practice for this deployment, which is exactly the kind of channel through which a `DEBUG=true` could get set temporarily for troubleshooting and forgotten. **Not Proven** whether `DEBUG` is actually set anywhere in the live Render dashboard — that's outside what a repo-only audit can see, and would need to be checked directly by whoever has Render access.

**Recommended fix:** At minimum, additionally gate this on `settings.ENVIRONMENT != "production"` (already a real, typed settings field) rather than trusting a single raw env var no other part of the app reads this way — belt-and-suspenders against exactly the "forgot to unset it" scenario. Stronger: remove the route entirely and replace with a fixture/helper used only by the test suite (which needs exactly this capability, per `tests/conftest.py`'s existence).
**Risk of fixing:** None — this is a dev-only convenience route; tightening it doesn't affect any real user flow.
**Cleanup effort:** Trivial (~15 min).
**Confidence:** Confirmed the code has no other gate (full file read). "Is DEBUG actually set in production" is explicitly Not Proven.

---

### P2-F5 — `tokenUrl="/auth/token"` points at an endpoint that doesn't exist; duplicated `OAuth2PasswordBearer` construction
**Severity:** Low
**Category:** Maintainability / Duplicate Utility / Documentation drift
**Files:** `app/modules/auth/router.py:29`, `app/dependencies.py:15`, `documentation/auth_and_access_control.md:38`

**Reason:** Both `app/dependencies.py:15` (`oauth2_scheme`) and `app/modules/auth/router.py:29` (`_bearer`) independently construct `OAuth2PasswordBearer(tokenUrl="/auth/token")`. No route named `/auth/token` exists anywhere — the real token-issuing endpoint is `POST /auth/firebase-verify`. `tokenUrl` only affects the OpenAPI schema (what Swagger UI's "Authorize" popup POSTs to) — it has no effect on runtime Bearer-token extraction/validation, so this is not a functional bug, only a docs/DX one. `documentation/auth_and_access_control.md:38` compounds the confusion by documenting `POST /auth/token → {access_token, refresh_token, ...}` as if it's a real, working endpoint.

**Recommended fix:** Change both `tokenUrl` values to `/auth/firebase-verify` (or whatever the intended login route is), fix the doc to match, and have `auth/router.py`'s `_bearer` just import `oauth2_scheme` from `app.dependencies` instead of constructing a second identical instance.
**Risk:** None (OpenAPI-schema/doc-only change).
**Cleanup effort:** Trivial (~10 min).
**Confidence:** Confirmed (full read of both construction sites; grepped for any `/auth/token` route definition — none found).

---

## What's solid (no action needed)
- `service.py`'s session lifecycle (`create_session`, `refresh_session`, `revoke_session_by_jti`, `revoke_all_sessions`) — refresh tokens are opaque, only SHA-256 hashes persisted, rotation on refresh, proper expiry check. No issues found.
- `models.py`'s `UserSession` — sensible constraints (`refresh_token_hash` unique, cascade delete on user removal, indexed `user_id`).
- The onboarding-token / access-token split (short-lived, no-DB-session onboarding path vs. full session-backed access token) is a clean design with no duplication against the main session path.
- Router error handling is consistent: `ValueError` from the service layer → `HTTPException(401, ...)` at the router boundary in all three places it's needed.

## Reconciliation summary vs. `documentation/BACKEND_AUDIT.md`
| Bug | Status now |
|---|---|
| BUG-008 (service_msg91 crash) | **Still present** — see P2-F1 |
| BUG-023 (no rate limit on firebase-verify) | **Still present** — see P2-F2 |
| BUG-019 (country code parsing, filed under "Infrastructure" in the old doc but the file is `auth/service.py`) | **Still present**, code edited since but defect unchanged — see P2-F3 |

## Unresolved questions handed to later phases
- None new beyond what's already in `AUDIT_PROGRESS.md`. P2-F4/P2-F5 are self-contained findings, not open questions.
- The "is `DEBUG` actually set in the live Render dashboard" question in P2-F4 is out of static-audit scope — flagged as Not Proven, not carried forward as a phase dependency.

## Phase 02 summary
- 5 findings: **1 High (P2-F1), 3 Medium (P2-F2, P2-F3, P2-F4), 1 Low (P2-F5).**
- 3 of 5 reconcile confirmed-still-open bugs from the prior `BACKEND_AUDIT.md`; 2 are new.
- Nothing found blocks moving on to Phase 03.
