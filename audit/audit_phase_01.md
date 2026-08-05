# Audit Phase 01 — Bootstrap, Core Infrastructure & Shared Utilities

**Status:** Done
**Scope:** `main.py`, `app/config.py`, `app/core/**`, `app/dependencies.py`, `app/shared/utils/**`, `tests/conftest.py`, `requirements.txt`, `scripts/` (workspace hygiene check only)
**Not in scope here:** any `app/modules/**` business logic (each gets its own phase).

---

## Files inspected

| File | Purpose | Verdict |
|---|---|---|
| `main.py` | FastAPI app assembly: Sentry init, router registration, scheduler lifespan, Socket.IO mount | Live, correct, but see P1-F3 |
| `app/config.py` | A `Settings` class (`DATABASE_URL`, `SECRET_KEY`, `ENVIRONMENT`) | **Dead — zero importers.** See P1-F1 |
| `app/core/config.py` | The real `Settings` class actually used app-wide | Live, correct |
| `app/core/database/session.py` | Sync SQLAlchemy engine + `SessionLocal` | Live, correct, standard |
| `app/core/database/base.py` | `Base(DeclarativeBase)` | Live, correct, trivial |
| `app/core/database/__init__.py` | empty | Fine (package marker) |
| `app/core/redis_client.py` | Lazy singleton sync Redis client + FastAPI dep | Live, correct |
| `app/core/rate_limiter.py` | Redis sliding-window `RateLimiter` class + `rate_limiter` singleton | **Built, wired nowhere.** See P1-F4 |
| `app/core/monitoring.py` | Sentry init + a middleware that tags each request's transaction with an owning "module" name based on URL prefix | Live, but stale mapping table. See P1-F3 |
| `app/core/scheduler.py` | APScheduler background jobs (news pipeline, trending recalc, post expiry/popular sync, taste update, ignore-detection, global-taste promotion, keep-alive ping) | Live, correct, single responsibility. Currently shows as modified in git status — imports line up with current module layout (`news_new`, `taste.global_session`, `taste.global_taste`), no stale imports found |
| `app/core/security/jwt_handler.py` | Access-token + onboarding-token issue/decode | Live, correct, consistent error handling — but see P1-F1 (config bypass) |
| `app/core/__init__.py`, `app/core/security/__init__.py` | empty | Fine |
| `app/dependencies.py` | `get_db`, `CurrentUser`, `get_current_user`, `get_current_user_id`, `get_current_profile_id`, `get_onboarding_claims`, `get_onboarding_user_id` | Live, clean, single responsibility, all six symbols independently useful for different endpoint shapes |
| `app/shared/utils/response.py` | `ok(data, message)` response envelope | Live — used by 12+ routers, consistent |
| `app/shared/utils/storage.py` | Supabase storage helpers (signed upload URL, public URL, delete, existence check) | Live (used by profile/groups/post/chat) — reviewed for this phase only at the "is it called and coherent" level; deep correctness review deferred to the modules that call it |
| `tests/conftest.py` | Session-scoped autouse fixture patching scheduler + startup ingest | **Broken — references a symbol that no longer exists.** See P1-F2 |
| `requirements.txt` | Runtime dependency list | Missing test dependencies. See P1-F5 |
| `scripts/news/`, `scripts/news_module/`, `scripts/news_new/` | Not part of the shipped app | Workspace clutter, not dead *shipped* code. See P1-F6 |

---

## Findings

### P1-F1 — Three parallel, inconsistent configuration systems (one fully orphaned)
**Severity:** High
**Category:** Architecture / Dead Code
**Files:** `app/config.py:1-11`, `app/core/config.py:1-37`, `app/core/security/jwt_handler.py:11,19`

**Reason:** There are two separate Pydantic `Settings` classes, plus a third config path that bypasses both.

**Evidence:**
- `app/config.py` defines `Settings(DATABASE_URL, SECRET_KEY, ENVIRONMENT)` and instantiates `settings = Settings()` at import time.
- `app/core/config.py` defines a *different* `Settings` (`DATABASE_URL`, `SYNC_DATABASE_URL`, `REDIS_URL`, JWT lifetimes, Gemini/GNews/Groq/Sentry keys) — this is the one actually consumed.
- `grep -rn "from app.config import"` across the whole tree → **zero matches**. `app/config.py` has no importers anywhere.
- `grep -rn "app.core.config"` → 17 files import it (every router/service that needs settings, plus `alembic/env.py`).
- `SECRET_KEY` (the one field unique to the dead `app/config.py`) is never read anywhere — `grep -rn "SECRET_KEY"` only matches its own declaration.
- Meanwhile `app/core/security/jwt_handler.py` doesn't use *either* `Settings` class for the actual signing secret — it reads `os.getenv("JWT_SECRET_KEY")` directly (line 19) and `os.getenv("JWT_ALGORITHM", "HS256")` (line 11), completely bypassing the settings layer. If `JWT_SECRET_KEY` is unset, this raises `RuntimeError` lazily, the first time a token is decoded/created — not at startup.

**Why it matters:** A new contributor (or an AI assistant autocompleting an import) doing `from app.config import settings` gets a plausible-looking, importable, wrong object — missing `REDIS_URL`, JWT lifetimes, all provider keys. Because Pydantic validates eagerly at instantiation, actually triggering that import for the first time would immediately throw (`SECRET_KEY` / `DATABASE_URL` required, no default) unless a `.env` happens to define them, in which case it silently succeeds with a half-populated, wrong settings object. Separately, the JWT secret's `RuntimeError` fires at first-use instead of app boot, so a misconfigured deploy looks healthy until the first login attempt.

**Recommended fix:**
1. Delete `app/config.py` entirely.
2. Move `JWT_SECRET_KEY` and `JWT_ALGORITHM` into `app/core/config.py`'s `Settings` (as required fields, no default for the secret) so a missing secret fails at process boot, not at first request.
3. Update `jwt_handler.py` to read `settings.JWT_SECRET_KEY` / `settings.JWT_ALGORITHM` instead of `os.getenv`.

**Risk of fixing:** Low — `app/config.py` has no callers to break. The JWT env-var rename needs a deploy-config change (rename or alias the env var) to avoid a startup break in whatever environment sets `JWT_SECRET_KEY`.
**Cleanup effort:** Small (~30 min: delete file, add 2 fields, update 2 read-sites, update deploy env if the var is renamed).
**Confidence:** Confirmed (grep evidence for both "zero importers" and "17 importers" claims; read all three files in full).

---

### P1-F2 — `tests/conftest.py` patches a symbol that no longer exists; the entire test suite currently errors at session setup
**Severity:** Critical
**Category:** Dead Code / Missing Tests / Stale Implementation
**Files:** `tests/conftest.py:16` (`patch("main.ingest", MagicMock())`), `main.py` (no `ingest` symbol anywhere)

**Reason:** The autouse, session-scoped `patch_startup` fixture unconditionally does:
```python
with (
    patch("app.core.scheduler.start",  MagicMock()),
    patch("app.core.scheduler.stop",   MagicMock()),
    patch("main.ingest",               MagicMock()),
):
    yield
```
`unittest.mock.patch` resolves the target eagerly on `__enter__` and raises `AttributeError` if the attribute doesn't exist on the target module (no `create=True` used here). `main.py` currently has no `ingest` import or symbol at all (`grep -n "ingest" main.py` → no matches).

**Evidence this is a regression, not a pre-existing bug — full git trail:**
- `git log -p --all -- main.py` shows `main.py` used to do `from app.modules.news.tasks import ingest` and call `ingest()` at startup (present through many historical commits).
- Commit `54ef7e4` ("Transitioning from old news to new news model") is exactly where the old `app.modules.news` package (and its direct `ingest` import/call in `main.py`) was replaced by the `news_new` pipeline, which runs ingestion via `app.core.scheduler` (`run_news_pipeline`, an interval job) instead of a direct startup call.
- `tests/conftest.py` was last modified 2026-05-12 11:55:43 +0530; `main.py`'s most recent change is 2026-07-06 11:53:04 +0530 — i.e. main.py changed *after* conftest.py was last touched, consistent with the fixture silently going stale rather than ever being written against the current shape.
- `.pytest_cache/v/cache/nodeids` still contains ~100 previously-collected test IDs from `tests/test_security_fixes.py`, proving the suite *did* fully collect and run at some point (before the news transition made this fixture load-bearing-but-broken).

**Failure scenario:** Run `pytest` today (or in CI) → the `patch_startup` fixture's `with` block raises `AttributeError: <module 'main' from '...'> does not have the attribute 'ingest'` the moment the session-scoped fixture is set up, before the first test body executes. Because it's `autouse=True, scope="session"`, this aborts fixture setup for the entire session — every single test in `tests/` errors, not just news-related ones.

**Recommended fix:** Remove the `patch("main.ingest", MagicMock())` line entirely — there's nothing left to patch; `news_new`'s pipeline is already reached only via the scheduler, which the fixture already patches (`app.core.scheduler.start`/`.stop`). If a "don't hit the network on import" guard is still wanted for `run_news_pipeline`, patch that function directly instead.

**Risk of fixing:** None — this only touches test scaffolding.
**Cleanup effort:** Trivial (delete one line, confirm suite collects).
**Confidence:** Confirmed (static: `ingest` doesn't exist in `main.py`, verified by grep and full file read. Historical: git log -p shows the exact commit and mechanism of removal. Not yet re-run end-to-end in this environment — see P1-F5, no working `pytest` install was available in `.venv` to execute the suite directly this session — but the `AttributeError` mechanism doesn't depend on runtime data, only on the two static facts above, so this is as confirmed as static analysis gets).

**Action needed from environment owner:** Run `pytest tests/ -q` once a working pytest install is available, to confirm the exact error text matches and to check whether any other fixture/test has quietly drifted the same way.

---

### P1-F3 — Sentry module-tagging middleware has a stale prefix table; two modules are silently never tagged
**Severity:** Medium
**Category:** Technical Debt / Duplicate Config (magic strings maintained separately from the source of truth)
**Files:** `app/core/monitoring.py:52-66` (`_MODULE_PREFIXES`) vs. actual `APIRouter(prefix=...)` declarations across `app/modules/**`

**Reason:** `_MODULE_PREFIXES` is a hand-maintained list of `(url_prefix, module_tag)` pairs, independent from the actual router prefix strings declared where each router is built. Two entries no longer match any real route:

| `_MODULE_PREFIXES` entry | Assumed real prefix | Actual real prefix | Match? |
|---|---|---|---|
| `("/post", "post")` | `/post` | `app/modules/post/router.py:12` → `/posts` (plural), `post_user_interaction/router.py:22` → `/posts/interactions`, `post_recommendation_module/router.py:25` → `/posts/recommendation` | **No — `/posts/...`.startswith("/post/") is False.** `"/posts"` also isn't `== "/post"`. Rule never fires. |
| `("/deeplink", "deeplink")` | `/deeplink` | `app/modules/deeplink/router.py:9` → `/share` | **No — router is mounted at `/share`, not `/deeplink`, at all.** |

All other entries were verified against their router file and match correctly (`/api/v1/groups`, `/news/admin`, `/news`, `/connections`, `/recommendations`, `/feed`, `/safety`, `/chat`, `/auth`, `/profile`, `/verification`).

**Impact:** `module_for_path()` returns `None` for every request under `/posts/*` and `/share/*`. Since the middleware only sets the Sentry tag when a module is found (`if module: sentry_sdk.set_tag(...)`), Sentry transactions for the post module and the deeplink/share module are silently untagged forever — no error, no log, just missing observability data exactly where the "audit every GET endpoint" Sentry rollout (per recent commit history) presumably wanted coverage.

**Recommended fix:** Change `("/post", "post")` → `("/posts", "post")` and `("/deeplink", "deeplink")` → `("/share", "deeplink")`. Better structural fix: derive this table from the routers' own `prefix` attributes at startup (e.g. build it once from the same list `main.py` already has, `[(r.prefix, tag) for r, tag in ...]`) instead of hand-maintaining a second copy of routing knowledge that can silently drift again.

**Risk of fixing:** None — Sentry tagging is observability-only, no behavior change.
**Cleanup effort:** Trivial for the string fix (2 lines); Small (~30–45 min) for the structural fix that prevents recurrence.
**Confidence:** Confirmed (every prefix cross-checked directly against its `APIRouter(prefix=...)` declaration).

---

### P1-F4 — A complete Redis rate limiter exists and is never called from anywhere
**Severity:** Medium
**Category:** Missing Connections / Dead Code / Security gap (candidate)
**Files:** `app/core/rate_limiter.py:1-84`

**Reason:** `RateLimiter.check()` and `.remaining()` implement a correct Redis sorted-set sliding-window limiter, exported as a ready-to-use singleton (`rate_limiter`, line 83) with a docstring showing exactly how a route should call it. `grep -rn "rate_limiter\.check|from app.core.rate_limiter import|RateLimiter\(\)"` across all of `app/` → the only match is the definition file itself. No router, dependency, or service calls it.

**Why it matters beyond "unused code":** This project's auth flow is OTP-based (`documentation`/memory: Firebase phone OTP). OTP-send endpoints are the textbook case for needing exactly this kind of limiter (prevent SMS-bombing / brute-force of a phone number), and the fact that the limiter exists, fully built, with a docstring aimed at "some endpoint," suggests it was written *for* a specific call site that either never got wired in or was later removed. This needs the Phase 02 (Auth) trace to confirm whether OTP-send currently has *any* throttling (Firebase-side or otherwise) before deciding whether this is "just dead code" or "a shipped security gap with the fix already written and sitting unused."

**Recommended fix:** Do not delete without checking Phase 02 first. If auth endpoints have no other throttling, wire `rate_limiter.check()` into the OTP-send route (per its own docstring pattern) rather than deleting it. If some other mechanism already covers this, delete the file — an unused, untested Redis-dependent class is a maintenance cost with no offsetting benefit.

**Risk:** None to assess now (no behavior depends on it today). Risk is on the *decision*, not the code — deleting a real security control by mistake vs. carrying dead code forward.
**Cleanup effort:** Depends on Phase 02 outcome — Small if wiring in (~1 hr incl. a test), Trivial if deleting.
**Confidence:** Confirmed dead (zero callers, verified by grep). "Is this a security gap" is Plausible, not yet Confirmed — carried to Phase 02 as open question #5 in `AUDIT_PROGRESS.md`.

---

### P1-F5 — Test suite has no declared dependencies; not reproducible from a clean install
**Severity:** Medium
**Category:** Missing Tests / Maintainability
**Files:** `requirements.txt` (full file reviewed), `tests/conftest.py`, `tests/test_security_fixes.py`

**Reason:** `requirements.txt` lists only runtime dependencies (fastapi, uvicorn, sqlalchemy, asyncpg, alembic, redis, supabase, sentry-sdk, etc. — 24 packages total). `pytest` is not among them. Confirmed by attempting to actually run the suite in this session:
```
.venv/Scripts/python.exe -m pytest tests/ -q
→ No module named pytest
```
tried against the project's own `.venv`, a global `pythoncore-3.14`, and the `python3` on PATH — none have `pytest` installed. Yet `.pytest_cache/` contains real prior output (`nodeids` cache lists ~100 collected test IDs, tagged with `pytest-9.0.3` in `__pycache__/*.pyc` filenames), so the suite clearly *has* been run successfully before, from some environment not currently reachable/reconstructable from what's committed.

**Impact:** Anyone (a new dev, CI, or a fresh agent session) who does `pip install -r requirements.txt` cannot run the test suite at all — there's no `requirements-dev.txt` / `pytest` extra / `pyproject.toml` `[test]` group defining what's needed (`httpx` for `TestClient` is present as a runtime dep already, so that part is covered incidentally; `pytest` itself is not).

**Recommended fix:** Add a `requirements-dev.txt` (or a `[test]` extra in a `pyproject.toml`, if the project moves that direction) pinning at minimum `pytest` (and `pytest-asyncio` if any async test paths get added later). Document the install command in a README/CONTRIBUTING note.

**Risk of fixing:** None.
**Cleanup effort:** Trivial (~10 min).
**Confidence:** Confirmed (direct execution attempt failed identically across three interpreters; grep of `requirements.txt` shows no test packages).

---

### P1-F6 — `scripts/news/`, `scripts/news_module/`, `scripts/news_new/`: not dead *shipped* code, but real workspace clutter with a footgun inside
**Severity:** Low
**Category:** Maintainability / Technical Debt (not Dead Code in the "shipped but unreachable" sense)
**Files:** `scripts/news/**` (1,737 LOC), `scripts/news_module/**` (3,889 LOC), `scripts/news_new/**` (mostly stub/comment files, <400 LOC)

**Reason — calibrating severity correctly:** `scripts` is listed in `.gitignore:8`, and `git ls-files scripts/` returns **zero tracked files** — this entire tree has never been committed and is not part of the repository proper. `grep -rn "from scripts\.|import scripts\."` across the whole tree → zero matches; nothing in `app/` imports from it. So this is not "dead code shipped to production" — it's local, git-ignored scratch space, most likely successive planning/prototyping passes at the news feature before it was actually built as `app/modules/news_new/`.

**Evidence of what it actually is:**
- `scripts/news_new/feed/service.py` and `router.py` are ~10-26 lines each, and their content is exclusively comments describing an intended API contract (e.g. `# get_trending_feed(db, user_id, cursor, limit) → FeedPage`) — these read as design notes, not working code.
- `scripts/news_module/` is different in character: real, substantial implementations (e.g. `recommendation/engine.py`, 125 lines, full scoring formula with docstring; `data/repository.py`, 533 lines). Critically, `scripts/news_module/recommendation/engine.py` imports `from app.modules.news.data.models import EnrichedArticle, NewsTrending, RawArticle` — `app.modules.news` **does not exist** anywhere in the current `app/modules/` tree (only `app/modules/news_new/` does). This confirms `scripts/news_module/` is a stale snapshot from before the `news → news_new` transition (the same transition identified in P1-F2) and would not even import successfully today.
- `scripts/news/` (1,737 LOC) appears to be an earlier, even-more-original iteration, going by naming.

**Why it's still worth flagging (Low, not "ignore"):** It's inert for the running application, but it's a real hazard for *future development assisted by grep/AI tools*: a search for "news recommendation engine" or "trending feed service" will surface these look-alike files right alongside the real ones in `app/modules/news_new/`, and nothing marks them as superseded. This is exactly the kind of thing that produced the confusion documented in the `feedback_dead_code` project memory (a prior session fixed a dead file before finding the real active one, in a *different* module).

**Recommended fix:** Since none of it is tracked by git, this is a local housekeeping call for the user, not a code change: either delete the three directories locally (nothing is lost — they're not in any commit), or move them somewhere clearly outside the repo working tree (e.g. a `~/scratch/vanijyaa-news-drafts/` outside the project). Do **not** just leave them where they are and assume `.gitignore` is sufficient protection — it protects the *repository*, not a future grep.

**Risk of fixing:** None (untracked, unimported, deleting loses no git history since none exists for these paths).
**Cleanup effort:** Trivial (a `rm -rf` the user runs themselves, outside of any code change).
**Confidence:** Confirmed (`.gitignore` match verified with `git check-ignore -v`; `git ls-files` returns empty; import-nothing verified by grep; the broken `app.modules.news` import in `scripts/news_module` verified by direct read).

---

## What's solid (no action needed)
Calibration note, not padding: these were checked with the same rigor as the findings above and found clean.
- `app/dependencies.py` — six small, single-purpose dependency functions, no dead ones, no mixed responsibilities, zero DB calls in the JWT-only paths as the docstrings claim.
- `app/core/security/jwt_handler.py`'s actual token issue/decode logic (independent of the config-source complaint in P1-F1) — consistent exception handling, correct claim validation, no gaps.
- `app/core/scheduler.py` — every job it registers resolves to a currently-existing function in currently-existing modules (`news_new`, `post_recommendation_module`, `post_user_interaction`, `taste.global_session`, `taste.global_taste`); despite showing as modified in git status, nothing here is stale.
- `app/shared/utils/response.py`'s `ok()` envelope — one function, used consistently by every router that returns a body (12 routers, single pattern, no competing envelope shape found elsewhere in this phase's scope).
- `alembic/env.py` correctly uses the live `app.core.config.settings`, not the dead `app.config` — no gotcha there.

---

## Unresolved questions handed to later phases
See `AUDIT_PROGRESS.md` → "Carried-forward open questions" for the authoritative list (items 1, 4, 5 originate from this phase). Not duplicating the full text here to avoid the two files drifting apart — update the progress file, not this one, as those resolve.

## Phase 01 summary
- 6 findings: **1 Critical (P1-F2), 1 High (P1-F1), 3 Medium (P1-F3, P1-F4, P1-F5), 1 Low (P1-F6).**
- Highest-priority fix: P1-F2 (test suite currently cannot run at all) — trivial to fix, currently blocking all automated verification for every other phase's eventual fix-up work.
- Second priority: P1-F1 (config consolidation) — small effort, removes a real footgun.
- Nothing found in this phase blocks moving on to Phase 02.
