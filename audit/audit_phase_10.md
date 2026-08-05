# Audit Phase 10 — Taste Module (amplify, global_session, global_taste, session_taste)

**Status:** Done
**Scope:** `app/modules/taste/amplify.py`, `global_session/{__init__,application/aggregator,application/use_cases,data/redis_repository}.py`, `global_taste/{application/use_cases,data/repository}.py`, `session_taste/data/redis_repository.py`, `news_new/news_user_interaction/taste_service.py` (cross-check)

---

## Note on method for this phase
Unlike prior phases, this module has **current, accurate, recently-verified project memory** (`project_dynamic_taste_architecture.md`, last updated 14 days before this audit, itself citing two in-repo docs updated 2026-07-14) describing exactly this system's state, including two real bugs already found and fixed by the user in a prior session. Per this audit's own confidence rules, that memory was **not** taken on faith — every claim in it that could be checked against current code was independently re-verified this phase (see below). This is also the one module in the repo with **uncommitted, in-progress changes** (`git diff --stat` shows exactly the 12 files this phase covers, all under `app/modules/taste/`, +241/-40 lines) — meaning the user was mid-edit on this exact module when this audit began. Findings below reflect the code as it stands right now, including those in-progress edits.

**Verified against current code, not just trusted from memory:**
- The pos/neg/conf sync bug memory describes as "found and fixed this session" — **confirmed genuinely fixed**, on both sides: `session_taste/data/redis_repository.py`'s `get_commodity_delta_and_snapshot`/`mark_synced` now compute and persist `neg_synced`/`conf_synced` snapshots (not just `pos`), and `global_session/data/redis_repository.py`'s `write_commodity_delta` writes all three fields to the global hash. Read both files in full to confirm this end-to-end, not just one side.
- The "Posts must not use `get_amplify_weights` (would silently swap in the wrong persistent source)" rule — **confirmed followed**: Phase 07's read of `post_recommendation_module/service.py` already showed it calling `sync_module_to_global`/`merge_weights` directly, never `get_amplify_weights`.
- The nightly promotion job's "write DB first, clear Redis only after commit confirms" safety order — **confirmed correctly implemented** in `app/core/scheduler.py`'s `_run_global_taste_promotion` (re-examined this phase specifically for this check): `db.commit()` executes before `clear_global_session(rc, pid)`, inside the same per-profile try block.
- Memory's claim that News' `UserNewsTaste` has "a fully-built but never-called `get_taste_weights`, dead code on the read side" — **independently re-confirmed** this phase via a fresh grep (not just re-reading the memory): every `get_taste_weights` call in the codebase resolves to either `post_user_interaction.taste_service` (Post's own, different module) or the function's own definition — zero external callers of `news_user_interaction.taste_service.get_taste_weights`. See P10-F2.

This is, on balance, the **most rigorously engineered and most rigorously self-verified module in the codebase** — clean domain/application/data layering genuinely respected (no data-layer imports found leaking into application/domain), confidence-gated multi-layer blending with real, documented gate formulas, and evidence the user already caught and fixed a subtle bug here without this audit's help.

---

## Findings

### P10-F1 — Commodity name→id lookup is cached process-wide with no invalidation
**Severity:** Medium
**Category:** Caching / Correctness
**Files:** `app/modules/taste/amplify.py:45-55` (`commodity_id_by_name`)

**Reason:**
```python
_commodity_id_by_name: dict[str, int] | None = None

def commodity_id_by_name(db: Session) -> dict[str, int]:
    global _commodity_id_by_name
    if _commodity_id_by_name is None:
        rows = db.query(Commodity).all()
        _commodity_id_by_name = {r.name.lower(): r.id for r in rows}
    return _commodity_id_by_name
```
This loads once per process and is never refreshed. `connections/weights_config.py` (Phase 04) explicitly documents that new commodities get appended over time (*"add new commodities here at the bottom only"*), implying the `commodities` table is expected to grow post-launch. If a commodity is added to the DB after a worker process has already populated this cache, `commodity_ids_for()` (which depends on it) will silently drop that commodity from every taste-signal write/read until the process restarts — with no error, just quietly-missing personalization for that commodity across every module that calls into amplify (Connections, Groups, Post, News).
**Recommended fix:** Either give the cache a TTL (even a generous one, e.g. re-check every hour) or invalidate it explicitly wherever a commodity is added (if that's ever done through the app rather than only via migration/seed — **Not Proven** whether commodities are ever added outside a migration, which would make this a much lower-probability issue in practice).
**Risk:** Low to fix; the current risk is silent, not crashing.
**Cleanup effort:** Small (~20–30 min).
**Confidence:** Confirmed (function read directly; cross-referenced against Phase 04's finding that the commodity list is documented as append-only-over-time).

---

### P10-F2 — News' persistent taste table has a fully-built, dead read path (independently confirmed, extends Phase 08's orphan-table pattern to a third table)
**Severity:** Medium
**Category:** Dead Code
**Files:** `app/modules/news_new/news_user_interaction/taste_service.py:57-100` (`get_taste_weights`), `models.py` (`UserNewsTaste`)

**Reason:** `update_taste()` (write side) is live — called from `news_user_interaction/service.py`'s `_taste_from_article` on every like/save/share/revisit (confirmed in Phase 08). But `get_taste_weights()` (read side) — a complete, correctly-implemented mirror of Post's own `taste_service.get_taste_weights` (decay + floor + role-default confidence blend) — has **zero callers anywhere**, confirmed by grep: the only `get_taste_weights(...)` call sites in the whole app resolve to `post_user_interaction.taste_service` (a different module entirely) or this function's own body. `UserNewsTaste` is therefore a write-only table in practice — every interaction pays the cost of upserting into it, and nothing ever reads the result. This is the same pattern as Phase 08's P8-F2 (dead recommendation-engine tables), now confirmed for a third table this audit has found in this state.
**Recommended fix:** Either wire `get_taste_weights` into `news_new/feed/service.py`'s scoring (it currently only uses `compute_profile_boost`'s commodity/state Jaccard match plus the session-taste `amplify` boost — this persistent per-category taste signal is a distinct, currently-unused input that could improve ranking), or remove the read path (and consider whether the writes are worth keeping at all if nothing will ever read them).
**Risk:** Low to wire in (additive); needs a decision on whether it's still wanted before removing.
**Cleanup effort:** Small (~30 min) either direction.
**Confidence:** Confirmed (grep re-run fresh this phase, not inherited from memory without verification).

---

## What's solid (no action needed)
- The three-layer blend formula (`MergeWeights._influence`) is exactly as documented, with named, sensible constants (`PERSISTENT_MIN_INFLUENCE`, `GLOBAL_SESSION_MAX_INFLUENCE`, `MODULE_SESSION_MAX_INFLUENCE`) and per-dimension-type branches (category/commodity/author/location) that correctly reflect which layers apply to which dimension — no logic drift found between the code and its own docstring.
- Domain/application/data layering is genuinely respected: `aggregator.py`/`use_cases.py` files import only from `domain/interfaces` and never reach into a `data/` module directly — confirmed by reading the actual import statements, not just trusting the header comments that say so.
- `RedisGlobalSessionRepository`/`RedisModuleSessionRepository` both use Redis pipelining for their multi-field writes (`pipeline(transaction=False)`) — efficient, and the non-transactional choice is reasonable for taste signals where losing one field update to a race is low-stakes.
- Fire-and-forget exception handling (`except Exception: pass` around every Redis-touching call in `amplify.py`) is the same no-logging anti-pattern flagged repeatedly elsewhere (BUG-024's pattern, now confirmed in a fifth location) — not re-scored as a new finding here, folded into the existing cross-cutting note for Phase 13.

## Phase 10 summary
- 2 findings: **2 Medium (P10-F1, P10-F2).**
- No prior-audit bugs were assigned to this module (it postdates `BACKEND_AUDIT.md` entirely).
- This phase's main value was independent verification of the user's own recent work here, not new problem-finding — the module is in genuinely good shape, and the one thing worth calling attention to (P10-F2) extends a pattern (dead persistent-taste read paths) already established in Phase 08.
- Nothing found blocks moving on to Phase 11.
