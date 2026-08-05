# Audit Phase 04 — Connections Module

**Status:** Done
**Scope:** `app/modules/connections/**` — `router.py`, `service.py`, `models.py`, `schemas.py`, `weights_config.py`, `encoding/vector.py`, `db/{chromadb,connections,fetch_user,pgvector,postgres}.py`, `routes/{connections,recommendations,users}.py`

---

## Files inspected

| File | Purpose | Verdict |
|---|---|---|
| `app/modules/connections/router.py` | `connections_router` (`/connections`) + `recommendations_router` (`/recommendations`) — the two routers `main.py` actually mounts | **Live, active, correct.** Thin HTTP layer only, as its own docstring claims |
| `app/modules/connections/service.py` | All business logic: follow graph, message requests, search, pgvector recommendations | Live, correct in the main, 2 confirmed-open issues (see findings) |
| `app/modules/connections/models.py` | `UserConnection`, `MessageRequest` (UUID-keyed) | Live, correct |
| `app/modules/connections/schemas.py` | Request bodies for follow/message-request/search/seen | Live. Its own docstring confirms old `UserCreate`/`UserUpdate` (int-ID "Users" table) schemas were **already deliberately removed** — see P4-F1 |
| `app/modules/connections/weights_config.py` | Vector-boost weight constants + fixed commodity/role dimension order | Live, imported by `service.py` and `encoding/vector.py` |
| `app/modules/connections/encoding/vector.py` | `build_query_vector`/`build_candidate_vector` — shared vector encoders | Live — used by `connections/service.py` **and** `profile/service.py` (confirmed cross-module in Phase 03). No duplication found. |
| `app/modules/connections/routes/connections.py` (110 lines) | An entire second `/connections` router, int user_ids | **Dead.** See P4-F1 |
| `app/modules/connections/routes/recommendations.py` (197 lines) | An entire second `/recommendations` router | **Dead.** See P4-F1 |
| `app/modules/connections/routes/users.py` (167 lines) | A `/users` CRUD router against a raw `"Users"` SQL table | **Dead.** See P4-F1 |
| `app/modules/connections/db/postgres.py` (34 lines) | A second, fully independent async SQLAlchemy engine + `declarative_base()` | **Dead**, only imported by the dead `routes/`+`db/` island. See P4-F1 |
| `app/modules/connections/db/connections.py` (286 lines), `pgvector.py` (58), `fetch_user.py` (18), `chromadb.py` (25) | Data-access layer for the old int-ID / ChromaDB-then-pgvector prototype | **Dead** — same island. See P4-F1 |

---

## Reconciliation with `documentation/BACKEND_AUDIT.md` (Connections' bugs: BUG-003, 029, 030)

| Bug | Status now |
|---|---|
| BUG-003 (no auth, path-param identity) | **Fixed**, confirmed — every mutating endpoint in `router.py` uses `Depends(get_current_user)`/`get_current_user_id`; only the two documented-public read endpoints (`/{user_id}/followers`, `/{user_id}/following`) and the two documented-public utility endpoints (`/search/suggestions`, `POST /recommendations/search`) skip auth, matching `auth_and_access_control.md`'s table exactly. |
| BUG-029 (raw dicts instead of `ok()` envelope) | **Fixed** — resolves Phase 02's open question #6. `service.py` functions do return plain `dict`s internally, but every single endpoint in `router.py` wraps the result in `ok(...)` before responding. `auth_and_access_control.md`'s claim ("All responses use `ok()` envelope") was the accurate one; `BACKEND_AUDIT.md`'s BUG-029 is now stale. |
| BUG-030 (no bidirectional uniqueness check on message requests) | **Still present** — see P4-F2 |

---

## Findings

### P4-F1 — `routes/` + `db/` is a complete, isolated, first-generation prototype of this module — 895 lines of dead code (resolves Phase 01/Phase 03's open question #1)
**Severity:** High
**Category:** Dead Code / Duplicate Implementation
**Files:** `app/modules/connections/routes/connections.py` (110), `routes/recommendations.py` (197), `routes/users.py` (167), `db/connections.py` (286), `db/pgvector.py` (58), `db/postgres.py` (34), `db/fetch_user.py` (18), `db/chromadb.py` (25) — **895 lines total**

**Reason:** `main.py` imports only `connections_router`/`recommendations_router` from `app/modules/connections/router.py` (confirmed by direct read). The `routes/` package defines a **second, entirely separate** set of `APIRouter`s with the same URL prefixes (`/connections`, `/recommendations`, plus a `/users` router that doesn't exist at all in the active app) — and they are never imported by `main.py`, by `router.py`, or by anything else reachable from the app's entry point.

**Evidence this is a distinct, superseded generation, not just an unused variant:**
- `routes/users.py` operates on a raw, quoted `"Users"` SQL table with an `int` primary key and a semicolon-separated `commodity` string column (`"rice;cotton"`) — the current schema has none of this; users are UUID-keyed (`app/modules/profile/models.py`'s `User`), and commodities are a normalized many-to-many junction table (`Profile_Commodity`).
- `routes/recommendations.py` contains ~30 lines of commented-out ChromaDB code, including a whole second commented-out copy of `get_recommendations` kept "for reference" to compare Postgres-fetch vs. ChromaDB-search timing — i.e., dead code preserved inside dead code.
- `db/postgres.py` builds its own `create_async_engine(..., echo=True)` and its own `Base = declarative_base()` — a **third** SQLAlchemy declarative base in this codebase (alongside `app/core/database/base.py`'s `Base(DeclarativeBase)` that every live model uses), with SQL statement logging (`echo=True`) left permanently on.
- `connections/schemas.py`'s own module docstring already states: *"Legacy `UserCreate` / `UserUpdate` (old `"Users"` table) have been removed. The acting user is now always identified via JWT."* — confirming the team already started this exact cleanup (removing the legacy Pydantic schemas) and simply never finished deleting the router/db files that went with them.
- Cross-checked against the 80-day-old `feedback_dead_code` memory, which had already flagged `routes/connections.py` specifically as dead (using stale info from a prior session) — this phase **independently re-confirms** that and additionally establishes that `routes/recommendations.py`, `routes/users.py`, and the entire `db/` package are dead too (not previously verified).

**Recommended fix:** Delete `app/modules/connections/routes/` and `app/modules/connections/db/` entirely (both directories, all 8 files). Before deleting, grep the frontend/mobile client for any lingering calls to `POST /users`, `PATCH /users/{id}`, `GET /recommendations/{user_id}/refresh` (paths that only exist in the dead tree) to confirm no client is still pointed at a since-decommissioned deployment of these routes — **Not Proven** from this repo alone whether any external caller still hits these paths; that requires checking the frontend/mobile codebase, out of scope here.
**Risk:** Low from the backend's perspective (zero internal callers, confirmed by exhaustive grep) — the only residual risk is an external client still targeting these URLs, which a repo-only audit cannot rule out.
**Cleanup effort:** Trivial to delete (~10 min); the "confirm no external caller" check is the only part with any real effort, and that's outside this audit's reach.
**Confidence:** Confirmed (exhaustive grep for cross-references between the two trees found only self-references within the dead island; `main.py` read in full in Phase 01 confirms it never touches `routes/` or `db/`).

---

### P4-F2 — Message requests still have no bidirectional uniqueness check (reconciles BUG-030: Still Present)
**Severity:** Medium
**Category:** Data Integrity
**Files:** `app/modules/connections/models.py:52-54` (`MessageRequest.__table_args__`), `app/modules/connections/service.py:310-354` (`send_message_request`)

**Reason:** `UniqueConstraint("sender_id", "receiver_id")` only prevents duplicate requests in one direction. `send_message_request`'s existence check (`service.py:331-334`) also only filters `sender_id == sender_id, receiver_id == receiver_id` — the same one direction. If A has already sent B a request (in any status), B can independently send A a request too, producing two separate `MessageRequest` rows for the same pair that both surface in each side's "received"/"sent" inbox, with no logic anywhere that reconciles them into one accepted connection.
**Recommended fix:** Before creating a new request, also check for an existing request in the reverse direction; if one exists and is `pending`, either auto-accept it (both parties already expressed interest) or surface a clearer "they already messaged you — check your inbox" error instead of allowing a second parallel row.
**Risk:** Low to fix, but needs a product decision (auto-accept vs. block) — flagging as a decision point, not just a code change.
**Cleanup effort:** Small (~1 hr once the desired behavior is decided).
**Confidence:** Confirmed (read the model constraint and the full service function).

---

### P4-F3 — Silent `except Exception: pass` in three places, no logging (same anti-pattern as BUG-024 in a different module)
**Severity:** Low
**Category:** Technical Debt / Observability
**Files:** `app/modules/connections/service.py:636-639` (`clear_recommendations_seen`), `658-660` (`mark_recommendations_seen`), `670-671` (`_get_seen_ids`), `799-800` (`get_recommendations`'s amplify re-rank step)

**Reason:** All four swallow every exception with a bare `pass` and no log line. The first three are explicitly documented as "best-effort" (Redis seen-set bookkeeping — reasonable to not fail the request over), but a Redis outage would then silently disable seen-item deduplication for every user with zero operational visibility. The fourth (amplify re-rank) means a bug anywhere in the taste-weighting path (`get_amplify_weights`, `commodity_boost`, `commodity_ids_for`) silently falls back to unweighted similarity ordering — recommendations quietly stop personalizing with no signal to anyone. `BACKEND_AUDIT.md`'s BUG-024 flagged the identical pattern (five `except Exception: pass` blocks) in `post/service.py` — this is the same anti-pattern recurring in a second module, worth fixing with the same approach in both places rather than treating them as unrelated.
**Recommended fix:** Replace each bare `pass` with `logger.warning(...)` (or `.exception(...)` where a full traceback is warranted) — doesn't need to change the fail-open behavior, just make failures observable.
**Risk:** None (logging-only change).
**Cleanup effort:** Trivial (~15 min for all four).
**Confidence:** Confirmed (all four sites read directly).

---

## What's solid (no action needed) — including one pattern worth copying elsewhere
- **`follow_user`/`unfollow_user`'s counter updates are the correct atomic pattern** — `db.query(Profile).filter(...).update({"following_count": Profile.following_count + 1})` compiles to a server-side `SET following_count = following_count + 1`, which is race-safe under concurrent requests. This is the pattern `BACKEND_AUDIT.md`'s BUG-010/BUG-011 (`post/service.py`'s non-atomic check-then-act like/save counters) should be changed to match — **flagging as a direct model-to-copy for Phase 07**, not just an abstract recommendation.
- `_activate_dm`'s guard against reviving a `BLOCKED` conversation on message-request acceptance (`service.py:453-455`) is a correct, deliberate safety check — an explicit block can't be silently undone.
- The raw-SQL pgvector queries in `get_recommendations`/`custom_recommendation_search` parameterize every user-controlled value via SQLAlchemy bind params (`:uid`, `:vec`, `:lim`, `:off`, `:seen_csv`) — the f-string-built portions of the query are fixed, hardcoded snippets, not user input. Checked specifically for SQL injection risk given the raw `text()` usage; none found.
- `search_users`'s intent-parsing (`_parse_search_intent`) is a nice, contained bit of NLU-lite for free-text search — explicit params always override parsed ones, no ambiguity in precedence.
- `_bulk_statuses`/`_load_profiles_bulk` batch what would otherwise be per-row N+1 queries — the same class of problem flagged as BUG-013/014/015 elsewhere in `BACKEND_AUDIT.md` is already avoided here.

## Unresolved questions handed to later phases
- Open question #10 (from `AUDIT_PROGRESS.md`, "`is_deleted` in `connections/service.py`") is **resolved, not carried forward**: it's not a Connections-module soft-delete — `service.py:418` sets `is_deleted=False` on a `chat.data.models.Message` row it creates directly (`_seed_first_message`, called from `respond_to_request` when a message request is accepted with an opening line). This confirms `Message.is_deleted` is a real, live soft-delete field in the Chat module — Phase 06 should verify chat's own code sets/reads it consistently.
- No new open questions from this phase beyond the external-client-usage caveat noted in P4-F1 (not a phase dependency — flagged as permanently Not Proven from this repo alone).

## Phase 04 summary
- 3 findings: **1 High (P4-F1 — 895 lines of confirmed dead code), 1 Medium (P4-F2), 1 Low (P4-F3).**
- 2 of 3 bugs from the prior audit reconciled (BUG-003 fixed, BUG-030 still present); BUG-029 determined stale/already-fixed.
- This phase fully resolves the oldest open question in this audit (routes/ vs router.py, originally flagged from an 80-day-old memory in Phase 01) with hard evidence rather than inherited assumption.
- Nothing found blocks moving on to Phase 05.
