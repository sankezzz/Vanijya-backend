# Recommendation & Taste Architecture — Complete Reference

> Date: 2026-07-03 (updated 2026-07-14)  
> Status: Partially implemented. Sections marked ✅ are coded. Sections marked 🔲 are planned. Sections marked ❓ have open decisions.

**2026-07-07 update:** Connections & Groups shipped Mechanism 1 (amplify) in `cfb9350`, via a new `app/modules/taste/amplify.py`. This session additionally fixed a bug where `conf`/`neg` never reached global session (§4), created the `user_global_taste` migration (§8), and wired the nightly promotion job (§7, §16). Posts (§10) is still the next unwired target — nothing below changes what's written there.

**2026-07-14 update (Posts):** Posts write+read wiring shipped (§3, §10, §11) — category + commodity only, author deferred. Critically, Posts does **not** use `get_amplify_weights` — see §10's rewrite for why (that helper would've silently sourced the wrong, sparser persistent table for Posts' commodity dimension).

**2026-07-14 update (News):** News write+read wiring shipped the same day, across all 5 interaction endpoints — commodity (3-layer, via `get_amplify_weights`) plus a **new `location` dimension** (2-layer, News-only — `MergeWeights` gained a `location` branch mirroring category/author, no global-session sync). Also corrected: News *does* have its own legacy persistent table (`UserNewsTaste`) contrary to an earlier claim in this doc — it just doesn't collide since it only ever writes `"category"`.

**2026-07-14 decision — Home Feed removed from scope, permanently:** §13 and §14 below describe a plan that will **not** be built — Home Feed will never integrate with `app/modules/taste/`. Kept for historical record, marked cancelled rather than deleted. **This closes the taste-wiring roadmap: Posts, News, Connections, and Groups are all wired; there is no remaining module to wire.**

**2026-08-05 update (Mechanism 2 spec written, Posts + Groups, Connections excluded):** §11 now has a full implementation-ready spec for Mechanism 2 — trigger condition, vector construction, query, and merge — grounded in the actual ANN vector code for both modules. Not built yet. One structural finding worth internalizing before touching this: both Posts and Groups/Connections embeddings only encode 3 fixed commodities (cotton/rice/sugar) — Mechanism 2 can only ever discover among those three, regardless of how much commodity data exists elsewhere. **§11.6 bundles everything to implement in the same pass** (by user request, so it's one cohesive unit of work, not scattered separate tickets): the migration prerequisite and its unrelated blast radius (chat message previews, News role-based scoring — both would break if this migration isn't applied before deploy), Mechanism 2's own two unresolved sub-decisions (cap to one discover commodity; what "stronger cross-module evidence" means quantitatively), and parked work in the same files (Posts' deferred author dimension, popular-posts soft scoring, role_interest still never read by any scoring step).

**2026-08-05 update (global session generalized; city + state; trade_intent scaffold):** The global-session infra (§4, §8) was generalized from a commodity-only implementation to any dimension type — repository methods renamed to generic `write_dimension_delta`/`read_dimension_weights`/`read_all_dimension_data`, Redis fields generalized from `commodity:{id}:*` to `{dimension_type}:{key}:*`. `CROSS_PLATFORM_DIMS` expanded to `{"commodity", "city", "state", "trade_intent"}`. News' old 2-layer, News-local `location` dimension (from the 2026-07-14 update above) is **retired** — replaced by two real 3-layer cross-platform dimensions, `city` and `state`, keyed off `EnrichedArticle.location_city`/`location_state` (LLM-extracted text, no reverse-geocoding utility anywhere in the codebase). Post gained the same two dimensions with **zero schema changes** — the post author's existing `Business.city`/`Business.state` are joined in at write and read time. Nightly promotion (§7) now loops over every registered dimension type instead of hardcoding commodity. `trade_intent` was added to `CROSS_PLATFORM_DIMS` as pure scaffolding only — no writer, no `MergeWeights` blend branch, no promotion threshold — fully inert until the real feature (on hold, §13 of the companion doc) is built.

---

## 1. The Problem Being Solved

The existing persistent taste system has a **15-minute lag**. Passive behavioral signals (dwell, open, link_click) sit in `post_interaction_events` with `processed_at = NULL` until the background job processes them. During that window the feed cannot adapt.

Explicit interactions (like, save, comment, share) already update taste synchronously — the lag only affects passive signals.

**Session taste closes this gap** by maintaining a live signal accumulator in Redis that recommendation engines read immediately.

Additionally, the current system has no **cross-module awareness**. A user engaging with Sugar content on news has no influence on their post or connection recommendations. Global session taste solves this.

---

## 2. Three-Layer Architecture

```
┌─────────────────────────────────────────────────────┐
│              Module Session Taste  (Layer 1)         │
│         Redis · per module · 2h inactivity TTL       │
│    What the user is asking for RIGHT NOW             │
│    "RAM — what you are thinking about this moment"   │
└──────────────────────┬──────────────────────────────┘
                       │ sync commodity delta on each feed request
                       ▼
┌─────────────────────────────────────────────────────┐
│              Global Session Taste  (Layer 2)         │
│         Redis · cross-module · 1 day TTL             │
│    The theme of today across all modules             │
│    "Working memory — your mood for the day"          │
└──────────────────────┬──────────────────────────────┘
                       │ nightly promotion at 3am IST (three-gate filter)
                       ▼
┌─────────────────────────────────────────────────────┐
│              Persistent Taste  (Layer 3)             │
│         PostgreSQL · no TTL · decays slowly          │
│    Who the user is as a trader over months           │
│    "Long-term memory — who you are"                  │
└─────────────────────────────────────────────────────┘
```

**Rule: writes only flow downward. No layer writes directly to a layer below its immediate neighbour.**

---

## 3. Layer 1 — Module Session Taste ✅

### Purpose
Immediate feed adaptation. Learns what the user wants right now, within one module, during the active session.

### Redis Key
```
session:{module}:{profile_id}
e.g. session:post:42  |  session:news:42  |  session:connections:42
```

### Hash Field Layout
```
{dim_prefix}:{dim_key}:pos      Float   accumulated positive taste score
{dim_prefix}:{dim_key}:neg      Float   accumulated negative taste score
{dim_prefix}:{dim_key}:conf     Float   accumulated confidence score
{dim_prefix}:{dim_key}:cnt      Int     event count
{dim_prefix}:{dim_key}:ts       Int     unix timestamp of last event
{dim_prefix}:{dim_key}:synced   Float   pos snapshot at last global sync (commodity only)

_total_events                   Int     total events across all dimensions
_session_start                  Int     unix timestamp when session began (HSETNX — set once)
_last_event_at                  Int     unix timestamp of most recent event
_last_synced_ts                 Int     unix timestamp of last module→global sync
```

### Dim Prefix Mapping
| dimension_type | prefix | example key | example full field |
|---|---|---|---|
| category | `cat` | `deal_req` | `cat:deal_req:pos` |
| commodity | `com` | `1` (Rice ID) | `com:1:conf` |
| author | `aut` | `123` (profile_id) | `aut:123:pos` |

### Dimensions Held
- **Category** — deal_req, market_update, discussion, knowledge (post-module only; no cross-module meaning)
- **Commodity** — Rice, Cotton, Sugar etc. (cross-module; syncs to global)
- **Author** — affinity for specific content creators (module-local; no cross-module meaning)

### TTL
2 hours from last interaction. EXPIRE resets on every `write_signals` call. Session loss on Redis restart is acceptable — next interaction starts a fresh session.

### Write Trigger ✅ Wired 2026-07-14
`POST /posts/interactions/batch` → after `db.commit()` → `write_post_signals(rc, profile_id, category, commodity_id, action, city=post_city, state=post_state)` (`app/modules/taste/amplify.py`) — category, commodity, city, state per event (city/state added 2026-08-05, sourced from an outer join to the author's `Business` row, no new columns). See §10 for what changed from the original plan below.

(Unrelated, still true: `submit_engagement` stub in the Home Feed router acknowledges but does not forward signals — that's Home Feed, not Posts, and per the 2026-07-14 decision above, never will.)

### Signal Building — How Batch Events Become SessionSignals
One raw batch event fans out into 2–3 `SessionSignal` objects (one per dimension):

**Step 1 — Classify event into ActionType:**

| Client sends | value_ms | ActionType |
|---|---|---|
| `impression` | — | IMPRESSION |
| `dwell` | < 2000 ms | DWELL_BOUNCE |
| `dwell` | 2000–8000 ms | DWELL_SHORT |
| `dwell` | 8000–30000 ms | DWELL_MEDIUM |
| `dwell` | ≥ 30000 ms | DWELL_LONG |
| `open_read_more` | — | OPEN_READ_MORE |
| `open_carousel` | — | OPEN_CAROUSEL |
| `open_comments` | — | OPEN_COMMENTS |
| `link_click` | — | LINK_CLICK |

**Step 2 — Look up post dimensions:** category_id → category name, commodity_id, author profile_id

**Step 3 — Create signals per dimension (as originally planned):**
- Category signal: always
- Commodity signal: always (if post has commodity_id)
- Author signal: only when `pos_delta ≥ 2.0` AND `author_profile_id ≠ viewer_profile_id`

Actions that write author: DWELL_MEDIUM (pos=2.0), DWELL_LONG (pos=3.5), LINK_CLICK (pos=2.0), LIKE, SAVE, COMMENT, SHARE, REVISIT

🔲 **Author signal deferred in the actual 2026-07-14 build.** `write_post_signals` only implements the first two bullets today — category and commodity, unconditionally. Add author later by porting this exact gate into `write_post_signals` (`app/modules/taste/amplify.py`), mirroring the identical gate that already exists in `record_interaction` for the persistent-taste path.

**Step 4 — Redis repository resolves weights internally:**
Each `SessionSignal` carries only `(dimension_type, dimension_key, action, occurred_at_unix)`. The repo looks up `SIGNAL_WEIGHTS[action]` → `(pos, neg, conf)` and writes `HINCRBYFLOAT` atomically via pipeline.

### Signal Weights ✅
Defined in `app/modules/taste/session_taste/domain/constants.py`:

| Action | pos | neg | conf |
|---|---|---|---|
| impression | 0.1 | 0.0 | 0.0 |
| view | 0.0 | 0.0 | 0.1 |
| dwell_bounce | 0.0 | 0.5 | 0.0 |
| dwell_short | 0.5 | 0.0 | 0.2 |
| dwell_medium | 2.0 | 0.0 | 0.5 |
| dwell_long | 3.5 | 0.0 | 1.0 |
| open_read_more | 1.5 | 0.0 | 0.3 |
| open_carousel | 1.0 | 0.0 | 0.2 |
| open_comments | 1.5 | 0.0 | 0.3 |
| link_click | 2.0 | 0.0 | 0.5 |
| like | 3.0 | 0.0 | 2.0 |
| save | 5.0 | 0.0 | 4.0 |
| comment | 4.0 | 0.0 | 5.0 |
| share | 4.0 | 0.0 | 6.0 |
| revisit | 6.0 | 0.0 | 4.0 |
| connection_view | 0.5 | 0.0 | 0.2 |
| connection_accept | 5.0 | 0.0 | 4.0 |
| connection_dismiss | 0.0 | 2.0 | 0.0 |
| feed_skip | 0.0 | 1.0 | 0.0 |
| feed_pause | 1.0 | 0.0 | 0.3 |

**Confidence ≠ taste.** Taste measures how much a signal shifts the score. Confidence measures how certain we are this is real intent. A comment (conf=5.0) provides more certainty than a long dwell (conf=1.0) because commenting is an explicit, effortful act.

### What is NOT a write gate
**There is no threshold at write time.** Every valid interaction writes to session taste unconditionally. `conf` just keeps accumulating per field via `HINCRBYFLOAT`. Thresholds only control how much influence the score gets at READ time.

---

## 4. Layer 1 → Layer 2 Sync ✅

### Trigger
On every feed/recommendation request that calls `get_amplify_weights` (Connections, Groups, News) or `sync_module_to_global` directly (Posts), before `merge_weights` is called.

### What syncs
**Commodity, city, and state** — `CROSS_PLATFORM_DIMS = frozenset({"commodity", "city", "state", "trade_intent"})` (generalized 2026-08-05; `trade_intent` is a scaffold slot with no writer). Category and author stay module-local.

### How delta is computed
```
pos_delta  = com:{id}:pos  - com:{id}:synced
neg_delta  = com:{id}:neg  - com:{id}:neg_synced
conf_delta = com:{id}:conf - com:{id}:conf_synced
```
Each of `synced`/`neg_synced`/`conf_synced` is a snapshot field storing the raw value at the time of last sync. Only the new increment since last sync is pushed for all three — prevents double-counting across multiple feed requests.

If any delta exceeds a small epsilon → write to global session.  
After write → `mark_synced` updates all three snapshots. If write fails → snapshot not updated → safe retry on next request.

**✅ Bug fixed 2026-07-07:** originally only `pos` was tracked this way — `get_commodity_delta_and_snapshot`/`write_commodity_delta` only ever carried a single pos-delta float per commodity key. `conf` and `neg` were never written to `session:global:{pid}` at all, permanently `0.0`. Two consequences this caused, both silent: (1) `MergeWeights`' global influence (`g_influence`) was always exactly 0% for every user, since it scales off `conf`; the already-shipped Connections/Groups 3-layer blend was actually 2-layer. (2) `PromoteFromGlobalSession`'s Gate 1 (`conf >= 0.70 × threshold`) would have failed unconditionally forever, making the nightly job (§7) a permanent no-op. Fixed by extending the same delta/snapshot pattern already used for `pos` to cover `conf` and `neg` too — `get_commodity_delta_and_snapshot`/`mark_synced`/`write_commodity_delta` now all operate on `dict[str, dict[str, float]]` (`{"pos", "neg", "conf"}` per key) instead of a bare float. No caller-facing signature changes — `sync_module_to_global`/`merge_weights`/`get_amplify_weights` are unaffected.

### Code path ✅
`app/modules/taste/global_session/application/aggregator.py` → `SyncModuleToGlobal.execute()`
`app/modules/taste/amplify.py` → `get_amplify_weights()` (the composition wrapper Connections/Groups actually call — **not** used by Posts, see §10)

✅ **Wired into Connections & Groups** (via `get_amplify_weights`) **and into Posts** (via `sync_module_to_global`/`merge_weights` called directly — different call pattern, same underlying sync, see §10 for why).

---

## 5. Layer 2 — Global Session Taste ✅ (partially)

### Purpose
The theme of today across all modules. Cross-module coherence — whatever the user gravitates toward in any module creates a gentle pull across all modules.

### Redis Key
```
session:global:{profile_id}
```

### Current Hash Fields (generalized to any dimension type 2026-08-05; Commodity/City/State are the three live cross-platform dimensions) ✅
```
{dimension_type}:{key}:pos    Float   accumulated positive score (all modules combined)
{dimension_type}:{key}:neg    Float
{dimension_type}:{key}:conf   Float
{dimension_type}:{key}:cnt    Int
{dimension_type}:{key}:ts     Int
```
e.g. `commodity:{id}:pos`, `city:{slug}:pos`, `state:{slug}:pos`. The repository's `read_all_dimension_data` parses every dimension type present in the hash in one `HGETALL`, not one per type.

### Planned Global Session Dimensions

| Dimension | Phase | Redis field | Source |
|---|---|---|---|
| Commodity | 1 ✅ | `commodity:{id}:*` | All module session syncs |
| City | 2 ✅ Done 2026-08-05 | `city:{slug}:*` | Post (author's `Business.city`), News (`EnrichedArticle.location_city`) |
| State | 2 ✅ Done 2026-08-05 | `state:{slug}:*` | Post (author's `Business.state`), News (`EnrichedArticle.location_state`) |
| Role interest | 2 🔲 | `role_interest:{role_id}:*` | Connection searches by role, post author roles engaged |
| Trade intent | 2 🔲 scaffolded only | `trade_intent:buying / selling` | deal_req type, connection counterparty role — reserved in `CROSS_PLATFORM_DIMS`, no writer yet |
| Type mix | ❌ cancelled 2026-07-14 | `type_mix:post / news / connection / group` | Home Feed will not integrate with global session at all |
| Quantity scale | 3 🔲 | `qty_scale:small / medium / large / bulk` | Deal sizes in posts, news volume movements |
| Content mode | 3 🔲 | `content_mode:transactional / informational` | deal_req heavy = transactional; market_update heavy = informational |

### TTL
1 day. Also explicitly cleared by the nightly promotion job after writing to persistent. Not a rolling TTL.

### Cross-module Examples (the purpose)
1. **Rice trader dwells on Sugar news** → `commodity:sugar` accumulates → slight Sugar boost in posts, connections, all feeds
2. **Vizag user reads Mumbai-datelined news** → `city:mumbai` accumulates → Mumbai post trades get a boost (Connections/Groups don't yet read city/state themselves — separate future pass)
3. **Cotton exporter searches rice exporters in connections** → `role_interest:exporter + commodity:rice` → rice exporter posts and news surface

---

## 6. Influence Blend — How Layers Merge at Read Time ✅

Defined in `app/modules/taste/global_session/application/aggregator.py` → `MergeWeights.execute()`

### Formula
```
m_influence = MODULE_MAX   × min(m_conf / m_threshold, 1.0)   # max 0.31
g_influence = GLOBAL_MAX   × min(g_conf / g_threshold, 1.0)   # max 0.15
p_influence = max(1.0 - g_influence - m_influence, 0.54)       # min 0.54

merged[key] = p_influence × persistent[key]
            + g_influence × global[key]
            + m_influence × module[key]
```

### Influence by Confidence State
| State | Persistent | Global | Module |
|---|---|---|---|
| Session just started | 100% | 0% | 0% |
| Module at 50% confidence | ~85% | 0% | ~15% |
| Both layers at 100% confidence | 54% | 15% | 31% |

### Per-Dimension Rules
| Dimension | Layers blended | Notes |
|---|---|---|
| Category | persistent + module | 2-layer; category has no cross-module meaning |
| Commodity | persistent + global + module | 3-layer; full blend |
| Author | persistent + module | 2-layer; lower ceiling (0.31 × 0.35 = 0.11 max) |

### Confidence Thresholds (scale influence from 0% → max%)
- **Category**: flat 10.0 for all categories
- **Module commodity**: `8.0 × (1 + persistent_score / 50)` — scales up with established taste
- **Global commodity**: `12.0 × (1 + persistent_score / 100)` — harder than module; needs cross-platform evidence
- **Author**: 6.0 — lower because affinity is binary per author

---

## 7. Layer 2 → Layer 3 Promotion (Nightly) ✅

### Trigger
Scheduler job at 3am IST daily. Also triggered on day rollover detection (request arrives with `_day ≠ today`).

### Three Gates (all must pass per commodity key)
| Gate | Condition | Filters out |
|---|---|---|
| Confidence | `conf ≥ 0.70 × global_commodity_threshold(persistent_score)` | Weak passive signals |
| Quality | `pos - (neg × 0.6) ≥ 20` | Low-engagement days |
| Events | `cnt ≥ 10` | Bursts (2 saves then app closed) |

**"Meaningful event"** = any event with `conf_delta > 0`. Impressions and bounces excluded.

### Promotion Formula
```
global_delta = pos - (neg × 0.6)
persistent_score += 0.15 × global_delta
```
Only 15% of one day's delta enters persistent. Identity changes over weeks, not days.

### Safety Order (inviolable)
```
1. READ global session from Redis
2. Check three gates per key
3. WRITE qualifying deltas to PostgreSQL   ← commit first
4. CLEAR global session from Redis         ← only after DB confirms
```
No separate `promotion_flushed_at` idempotency flag was built — the Redis key itself only gets cleared after a successful commit, and if nothing qualified, it isn't cleared at all (sub-threshold data just keeps accumulating for a future promotion attempt rather than being discarded). That's sufficient idempotency without an extra flag.

### Code path ✅ — wired 2026-07-07
`app/modules/taste/global_taste/application/use_cases.py` → `PromoteFromGlobalSession.execute()`  
`app/modules/taste/global_taste/data/repository.py` → `bulk_apply_promotion()`  
`app/core/scheduler.py` → `_run_global_taste_promotion()`, registered as `taste.global_promotion` (cron 3:15am IST, staggered after `posts.ignore_detect`'s 3:00am).

**New dependency this required:** nothing could previously enumerate which profiles have a live `session:global:*` key — `PromoteFromGlobalSession.execute()` only ever operated on one `profile_id` at a time. Added `scan_active_profile_ids()` to `IGlobalSessionRepository`/`RedisGlobalSessionRepository` (via `scan_iter`, not `KEYS`) plus a composition-root wrapper `list_active_global_session_profile_ids()` in `global_session/__init__.py`.

**Depends on the §4 conf/neg sync fix** — without it, Gate 1 would reject every profile/commodity unconditionally and this job would run nightly while promoting nothing.

---

## 8. Layer 3 — Persistent Taste ✅

### Tables
- `user_post_taste` — existing per-module taste (category, commodity, author per user)
- `user_global_taste` — new cross-platform persistent taste (commodity driven by global session promotion)

### `user_global_taste` Schema ✅
```sql
id             Integer PK
profile_id     Integer (indexed)
dimension_type String(50)    -- "commodity" | "city" | "state" | "quantity"
dimension_key  String(100)   -- e.g. "42" (commodity_id as string)
positive_score Float
negative_score Float
event_count    Integer
last_event_at  DateTime(timezone)
updated_at     DateTime(timezone)

UNIQUE (profile_id, dimension_type, dimension_key)  -- uq_user_global_taste_profile_dim
```

✅ **Migration created and verified 2026-07-07** — `alembic/versions/b7c8d9e0f1a2_add_user_global_taste.py`, `UserGlobalTaste` registered in `alembic/env.py`. Written by hand to match the ORM model exactly (not autogenerated) since the model has no FK to `profile.id` (unlike the sibling `user_post_taste` table, which does) — the migration intentionally mirrors that, not a silent fix.

### Decay (applied at read time, never stored)
```
decayed_score = raw_score × exp(-0.023 × days_since_last_event)
```
~30-day half-life. Applied in `PostgresGlobalTasteRepository.get_weights()`.

---

## 9. Current Taste Module File Structure ✅

```
app/modules/taste/
├── __init__.py
├── session_taste/
│   ├── __init__.py                  ← composition root + public API
│   ├── domain/
│   │   ├── constants.py             ← SIGNAL_WEIGHTS, thresholds, TTLs, influence caps
│   │   ├── entities.py              ← ActionType (enum), SessionSignal, DimScore
│   │   ├── interfaces.py            ← IModuleSessionRepository (ABC)
│   │   └── exceptions.py
│   ├── data/
│   │   └── redis_repository.py      ← RedisModuleSessionRepository
│   └── application/
│       └── use_cases.py             ← WriteSignals, ReadDimensionWeights, ReadDimScore,
│                                       GetCommoditySyncDelta, MarkSynced
├── global_session/
│   ├── __init__.py                  ← composition root + public API
│   ├── domain/
│   │   ├── entities.py              ← GlobalDimScore, InfluenceWeights
│   │   ├── interfaces.py            ← IGlobalSessionRepository (ABC)
│   │   └── exceptions.py
│   ├── data/
│   │   └── redis_repository.py      ← RedisGlobalSessionRepository
│   └── application/
│       ├── use_cases.py             ← ReadGlobalWeights, WriteGlobalDelta, ClearGlobalSession
│       └── aggregator.py            ← SyncModuleToGlobal, MergeWeights
├── global_taste/
│   ├── __init__.py                  ← composition root + public API
│   ├── domain/
│   │   ├── entities.py              ← GlobalTasteScore, PromotionCandidate
│   │   ├── interfaces.py            ← IGlobalTasteRepository (ABC)
│   │   └── exceptions.py
│   ├── data/
│   │   ├── models.py                ← UserGlobalTaste (SQLAlchemy) — migrated ✅
│   │   └── repository.py            ← PostgresGlobalTasteRepository
│   └── application/
│       └── use_cases.py             ← ReadGlobalTasteWeights, PromoteFromGlobalSession
└── amplify.py                       ← NEW (cfb9350): get_amplify_weights, commodity_boost,
                                        location_boost, commodity_id_by_name, write_commodity_signals —
                                        the shared read/write glue Connections & Groups
                                        actually call. Not per-layer — sits above all three.
                                        write_post_signals added 2026-07-14 (category +
                                        commodity only) for Posts' write path, gained
                                        optional city/state params 2026-08-05.
```

---

## 10. Post Module — ✅ Wired 2026-07-14 (category + commodity; author deferred), city + state added 2026-08-05

**Note:** Connections and Groups (`cfb9350` + last session) call the higher-level `get_amplify_weights`/`commodity_boost` from `app/modules/taste/amplify.py`. Posts does **not** use that helper — see the correction below. Both patterns are valid; which one applies depends on whether the module has its own legacy persistent table.

### The correction that shaped this implementation

The original plan (kept below, in the "as-built" sections, for reference) assumed Posts' read path would eventually look like Connections/Groups' — call `get_amplify_weights` once per dimension. That would have been a real bug: `get_amplify_weights` unconditionally sources its "persistent" layer from `read_global_taste_weights` (`user_global_taste`, the sparse cross-platform table promoted nightly from global session). That's the *correct* choice for Connections/Groups, which have no per-module persistent store of their own. **Posts already has one — `user_post_taste`, read via `taste_service.get_taste_weights`** — and using `get_amplify_weights` instead would have silently swapped in a much sparser, wrong persistent source for the commodity dimension. Posts calls the lower-level `sync_module_to_global`/`merge_weights` primitives directly instead, keeping `taste_service.get_taste_weights` as the persistent floor for all three dimensions. Any future module that already has its own legacy persistent table should follow the same pattern, not `get_amplify_weights`.

### Touchpoint 1 — Write Path ✅ Done

**File:** `app/modules/post/post_user_interaction/service.py`
1. `process_interaction_batch` gained an `rc: redis.Redis | None = None` parameter.
2. The post-validation query was widened from `Post.id` only to also fetch `category_id`, `commodity_id` (author/`profile_id` intentionally NOT fetched — deferred), and, as of 2026-08-05, `Business.city`/`Business.state` via an outer join to the author's Business row.
3. A new `_classify_action(event_type, value_ms) -> ActionType | None` helper reuses the existing `classify_dwell` bucket boundaries to map each accepted event to a session-taste `ActionType`.
4. After `db.commit()`, loops over accepted events and calls `write_post_signals(rc, profile_id, category, commodity_id, action, city=post_city, state=post_state)` (new helper in `app/modules/taste/amplify.py`) — category name resolved via the same `CATEGORY_NAMES` dict `record_interaction` already uses. Fully fire-and-forget; a Redis outage never raises past the batch endpoint.

**File:** `app/modules/post/post_user_interaction/router.py`
- `rc: redis.Redis = Depends(get_redis)` added to `submit_interaction_batch`, passed through.

### Touchpoint 2 — Read Path ✅ Done

**File:** `app/modules/post/post_recommendation_module/service.py`

```python
cat_weights       = taste_service.get_taste_weights(db, profile_id, "category", profile.role_id)
commodity_weights = taste_service.get_taste_weights(db, profile_id, "commodity")
author_weights    = taste_service.get_taste_weights(db, profile_id, "author")
city_weights      = read_global_taste_weights(db, profile_id, "city")   # added 2026-08-05
state_weights     = read_global_taste_weights(db, profile_id, "state") # added 2026-08-05

# Session-taste blend -- sync once, not per-dimension. Category/author are
# 2-layer (persistent+module only) and need no sync; commodity/city/state are 3-layer.
try:
    sync_module_to_global(rc, profile_id, "post")
    cat_weights       = merge_weights(rc, profile_id, "post", "category",  cat_weights)
    commodity_weights = merge_weights(rc, profile_id, "post", "commodity", commodity_weights)
    author_weights    = merge_weights(rc, profile_id, "post", "author",    author_weights)
    city_weights      = merge_weights(rc, profile_id, "post", "city",      city_weights)
    state_weights     = merge_weights(rc, profile_id, "post", "state",     state_weights)
except Exception:
    pass  # Redis down -- persistent weights already set above
```

Note this is exactly the block originally sketched here before `amplify.py` existed — it turned out to still be the *correct* approach for Posts specifically, not a stale plan. City/state use `read_global_taste_weights` (the cross-platform table) as their persistent floor rather than a Posts-specific table, since — unlike commodity — city/state were never given a legacy per-module persistent store to begin with; there's nothing to shadow. `_rerank()` and everything downstream is untouched — it already consumes plain `dict[str, float]` keyed by dimension_key-as-string, which is exactly what `merge_weights` returns; verified via a behavioral trace (fake Redis) showing commodity/city/state each move off their pure-persistent value while category/author show module-only movement with zero global-session leakage.

**File:** `app/modules/post/post_recommendation_module/router.py`
- `rc: redis.Redis = Depends(get_redis)` added to `get_feed`, passed to `service.get_recommended_posts`.

---

## 11. Recommendation Feed — Two Mechanisms

Session taste has two distinct jobs. They are complementary, not interchangeable.

### Mechanism 1 — Amplify (re-order existing pool) ✅ Wired 2026-07-14
Session taste blends into the weight dicts used by `_rerank()`. Posts already in the pool that match the user's current session interest score higher and surface faster.

**Live for category + commodity + author** (author blend degrades safely to persistent+empty-module until author signals get written — see §10).

### Mechanism 2 — Discover (expand pool) 🔲 Full implementation spec written 2026-08-05, not yet built

The pool is built from the user's **registered profile** commodities. If a user starts engaging with Sugar in-session but their profile says Rice+Cotton, Sugar posts will never enter the pool. Session taste has nothing to re-rank.

**Scope for this pass: Posts + Groups only.** Connections is explicitly excluded (user decision). News is permanently excluded (no ANN, §13.8 of the companion doc — nothing to run a second pass against). Everything below applies to both Posts and Groups unless a subsection says otherwise.

#### 11.1 — Hard constraint: only 3 commodities exist in vector space at all

The ANN embeddings for both Posts (`post_embeddings`/`user_embeddings`, via `COMMODITY_ID_TO_IDX = {1: 1, 2: 0, 3: 2}` in `post_recommendation_module/constants.py`) and Groups/Connections (`group_embeddings`, via `ALL_COMMODITIES = ["cotton", "rice", "sugar"]` in `connections/weights_config.py`, consumed by `encode_commodity()`) reserve exactly **3 fixed commodity dimensions** — this is documented elsewhere (§13.11 of the companion doc) as a frozen, versioned convention that must not be casually extended, since doing so requires re-embedding every stored vector.

**Consequence for Mechanism 2:** no matter how many commodities exist in the `Commodity` table, or how many distinct commodity keys show up in session/global taste, a second ANN pass can only ever discover interest in cotton, rice, or sugar — the only three the embedding space can express. Session-tracked interest in any other commodity has nothing to build a discover-vector dimension for and cannot trigger Mechanism 2. This isn't a gap this task needs to close — it's a pre-existing structural boundary of the current embedding scheme that the spec below must respect, not work around.

#### 11.2 — Trigger condition (per profile, at pool-build time)

Builds directly on resolved decisions — do not re-derive these, just apply them:
- **Construction rule** (§13.1 of the companion doc / §18.3 here): per-dimension override — use the session/global value for a dimension if one is active, else fall back to the profile value. Here that means: commodity dims get overridden for the *discover* pass; role/geo/qty stay exactly as the profile already provides them (they are not session-tracked ANN dimensions today).
- **Trigger bar** (§18.2): full threshold (100%), not the lowered 70% bar nightly promotion uses (§9 Gate 1) — Mechanism 2 is a stricter, rarer trigger than persistence promotion.

For each of the 3 vector-encoded commodities **not already in `profile.commodities`**:
1. Resolve its Redis dimension key — the same commodity_id string `write_commodity_signals`/`write_post_signals` already write (`str(commodity_id)`), not the vector index and not the commodity name.
2. **Module-level check:** `session_taste.read_dim_score(profile_id, module, "commodity", commodity_id_str).conf` — module is `"post"` for Posts, `"group"` for Groups (Groups' own module session, not Posts'). Compare against `module_commodity_threshold(persistent_score_for_that_commodity)` (persistent score sourced the same way the existing Mechanism-1 read path already does per module).
3. **Global-level check:** the commodity's `conf` from `global_session.read_all_dimension_data(profile_id)["commodity"]`. Compare against `global_commodity_threshold(persistent_score)`.
4. If either check clears its bar, the commodity is a **discover candidate** for this request.

**Open sub-decision, not resolved by this spec — flag before building:** the existing doc text says global-level triggering "needs stronger cross-module evidence" than the module-level check, but never defines what that means quantitatively. Do not invent a number silently when implementing — get an explicit answer (candidate options: require global `conf` to clear a stricter multiple of `global_commodity_threshold`, e.g. 1.5×; or require the commodity to show nonzero `conf` in at least one module session *other than* the one currently being read, as corroborating cross-module evidence).

**Recommended cap (not yet confirmed with the user):** if more than one commodity clears its bar in a single request, trigger Mechanism 2 for only the single highest-conf one, not all three-minus-registered. Fanning out to multiple second-pass ANN queries per feed request multiplies query cost for a feature whose whole premise is a rare, high-confidence exception — this should be confirmed, not assumed, before implementation.

#### 11.3 — Vector construction

Reuse the **same vector builder as the normal pass** — do not write a parallel construction path:
- **Posts:** `build_user_feed_vector(commodity_ids=..., role_id=profile.role_id, lat=..., lon=..., commodity_quantity=...)` (`post_recommendation_module/vector.py`), called a second time with `commodity_ids` replaced by `[discover_candidate_commodity_id]` only — not merged with the profile's registered commodities. This is a *discover* vector, not a blend: it should point purely at the new interest so the second ANN pass actually surfaces different content, not a diluted mix that mostly re-finds pass-1 results.
- **Groups:** `build_query_vector(commodity_list=[discover_candidate_name], role=user_role, lat=..., lon=..., qty_min=..., qty_max=...)` (`connections/encoding/vector.py`), same substitution. **Implementation detail to get right:** Groups' `encode_commodity()` takes commodity **name** strings (`"cotton"`, `"rice"`, `"sugar"`), but the trigger check above resolves a commodity **id**. Needs a small id→name reverse lookup — invert the existing `commodity_id_by_name(db)` map (`app/modules/taste/amplify.py`) rather than building a new one.

```
Posts, normal pass:    user_vec = build_user_feed_vector([rice_id, cotton_id], ...)      → pool_1
Posts, discover pass:  user_vec = build_user_feed_vector([sugar_id], ...)                 → pool_2
Final pool:            pool_1 + pool_2 (deduplicated against pool_1 AND seen_posts)

Groups, normal pass:   want_vec = build_query_vector(["rice", "cotton"], ...)              → pool_1
Groups, discover pass: want_vec = build_query_vector(["sugar"], ...)                       → pool_2
```

#### 11.4 — Query + merge

- **Posts:** run `_query_partition(db, "hot", <small limit>, pool_exclude, discover_vec)` — same hot/warm/cold fallback ladder as the primary pass isn't necessary here; a single hot-partition query against the discover vector is enough for a supplementary pass (recommend a small fixed budget, e.g. 15–20 candidates, not `FETCH_TARGET=150` — this is a bonus pass, not the primary pool build). Append results into `pool` before `_rerank()` is called, using `pool_exclude` for dedup exactly as the existing hot/warm/cold/fresh passes already do.
- **Groups:** run the same HNSW query used in `get_group_suggestions` (`group_embeddings <=> vec`), substituting `discover_vec` for `want_vec`, excluding `member_set` plus whatever pass-1 already selected. Append into `candidates` before the activity-blend loop.
- **No special-cased scoring for discover-pass results** — once merged, they flow through the exact same `_rerank()`/activity-blend/diversity pipeline as everything else, scored against the *discover* vector (so they legitimately show high relevance to the new interest, not the profile's registered commodities).
- **Recommended, optional:** tag discover-pass candidates with an internal `source: "discover"` debug marker (not user-facing) so it's possible to verify/measure post-ship how often the second pass actually contributes to the final served feed.

#### 11.5 — No-op case

If no commodity clears either bar, Mechanism 2 does nothing — the pool is exactly what the normal pass already produces. This must be a strict superset behavior: Mechanism 2 can only ever add candidates, never remove or reorder existing ones.

#### 11.6 — Implementation checklist: everything to bundle into this same pass

Mechanism 2 touches Posts' and Groups' recommendation services directly — while that code is open, pick up these related loose ends in the same pass rather than filing them as separate later work. None of these are Mechanism 2 itself; they're either prerequisites, unresolved blockers for it, or parked work in the exact same files.

**Prerequisite — apply before any of this ships (unrelated to Mechanism 2, but blocking):**
- Migration `d1e2f3a4b5c6` (adds `location_city`/`location_state`/`latitude`/`longitude` to `news_enriched_articles`) must be applied to every environment **before** deploying current `main` — not after. `EnrichedArticle` is a full ORM entity, so any full-entity query against it now selects these 4 columns, including two code paths that have nothing to do with taste/location and would otherwise start throwing `UndefinedColumn`:
  - `app/modules/chat/data/repository.py` (`_news_article_snap`, `_news_article_snaps_bulk`, lines ~321/371) — chat message previews for shared news articles.
  - `app/modules/news_new/news_recommendation_engine/service.py:25` (`compute_role_score`) — the *existing* role-based News scoring mechanism, unrelated to this session's work.
  - This isn't Mechanism 2 work, but since it's a live landmine discovered while speccing Mechanism 2, resolve it (confirm migration ran) before merging Mechanism 2 code, not as an afterthought.

**Blockers — must be answered before Mechanism 2's own logic can be written (see §11.2):**
- What "stronger cross-module evidence" means for the global-session trigger, quantitatively — currently just prose. Pick one of the candidate rules in §11.2 (stricter threshold multiple, or corroboration from a second module session) or propose another, but land on something concrete before writing `_query_partition`/HNSW discover-pass code that depends on it.
- Confirm the recommended cap (trigger Mechanism 2 for only the single highest-conf non-profile commodity per request, not all three minus registered) — affects how many extra ANN queries the discover pass costs per feed request.

**Parked work in the same files, worth finishing alongside Mechanism 2 rather than in a separate pass:**
- **Posts' deferred author dimension** (§10 of this doc) — `write_post_signals` only implements category+commodity+city+state today; author was deliberately deferred, gated behind `pos_delta ≥ 2.0 AND author ≠ viewer` (the same gate `record_interaction` already uses for persistent taste). Since Mechanism 2 work means touching `post_recommendation_module/service.py` and `amplify.py` again anyway, this is a natural, small addition to fold in.
- **Popular-posts soft scoring** (§12) — replace `_get_popular_posts()`'s current hard commodity filter with the tiered soft multiplier (1.3×/1.15×/1.0×) already designed there. Same file (`post_recommendation_module/service.py`), same session's worth of work as Mechanism 2's Posts side.
- **Role_interest never read by any scoring step** (§13.5 of the companion doc) — captured on Connections/Groups signals (`dimension_type="role"`) since `cfb9350`, still dormant. Groups' Mechanism 2 work touches `groups/service.py`'s `get_group_suggestions` — if role_interest scoring gets picked up, it's the same function this spec already modifies. Not required for Mechanism 2 to ship, but flagged here so it isn't forgotten as a separate untracked thread once this file is already open.

---

## 12. Popular Posts — Soft Commodity Scoring 🔲

**Current:** `_get_popular_posts()` in `post_recommendation_module/service.py` filters by `commodity_idxs` — hard filter, removes non-matching posts entirely.

**Decided:** Remove the filter. Replace with soft scoring:
```
final_score = velocity_score × commodity_boost
```

| Post commodity | boost |
|---|---|
| Matches user's registered commodities | 1.3× |
| Active in user's current session (not registered) | 1.15× |
| Unrelated to user | 1.0× (still appears) |

A viral unrelated post always survives. The multipliers bias the sort, they do not gate it.

**Not yet implemented.**

---

## 13. Home Feed Architecture ✅ (mixer only) — ❌ taste integration cancelled 2026-07-14

**This whole section describes Home Feed's real, existing mixer code (still accurate) plus a taste-integration plan that will never be built.** Home Feed will not integrate with `app/modules/taste/` — not now, not later. Read this section only for the mixer's current architecture; ignore any "will be wired" framing below.

### What it is
A mixer — no recommendation engine of its own. Calls each module's own recommender and blends the output via weighted random slot assignment.

### Post blend (inside `fetch_post_candidates` in `pipelines.py`)
```
Following     50%  → get_following_feed      (recency of followed users)
Popular       30%  → get_popular_posts       (platform velocity score)
Recommendation 20% → get_recommended_posts  (personalized ANN)
```

### News blend (inside `fetch_news_feed` in `pipelines.py`)
```
Trending news     → get_trending_news       (velocity + latest)
Recommended news  → get_recommended_feed    (role/commodity personalized)
Deduped trending-first, concatenated
```

### Type-mix weights (currently static in `service.py`)
```python
FEED_WEIGHTS = {"post": 0.45, "news": 0.25, "group": 0.15, "connection": 0.15}
```

### Existing feed session taste file (`app/modules/feed/session_taste.py`)
This is a **separate, older implementation** — only tracks type-mix weights (how much post vs news vs connection the user wants). Operates on a JSON blob stored at `session:{profile_id}:{session_id}`. It is NOT connected to the new taste module's Redis hash infrastructure. It only drives `FEED_WEIGHTS` for the mixer.

**❌ Cancelled 2026-07-14 — will NOT be replaced/integrated with a global session `type_mix` dimension.** This file stays exactly what it is, evolving independently of the taste system if at all.

### Engagement endpoint (`POST /feed/engagement`)
**Currently a stub.** `submit_engagement` in `service.py` acknowledges receipt but does not forward signals anywhere:
```python
def submit_engagement(user_id, batch) -> dict:
    return {"acknowledged": True, "signals_processed": len(batch.signals)}
```

`EngagementSignal` already has `item_type: Literal["post", "news", "group", "connection"]` — routing capability exists in the schema.

---

## 14. Home Feed Signal Routing — ❌ cancelled 2026-07-14, will not be built

**None of this section will be implemented.** Kept as historical record of the plan that existed before the decision to exclude Home Feed from this taste system entirely.

### What home feed shows
| Content | Source | Discovery or Personal? |
|---|---|---|
| Posts (50%) | Following + popular + recommendation blend | Mix — following is personal, popular is discovery |
| News | Trending + recommended blend | Mix |
| Connections | Connection recommender | Personal |
| Groups | Group suggestions | Personal |

### Decision on signal weight
Home feed content is **partly discovery-driven** (popular/trending) — engagement is weaker evidence of intent than engagement within a dedicated module feed. Home feed signals should write to global session at **reduced weight**, not to module sessions directly.

### Routing plan
```
item_type=post        → session:global:{pid}   (commodity only, reduced weight)
item_type=news        → session:global:{pid}   (commodity only, reduced weight)
item_type=connection  → session:global:{pid}   (role_interest, reduced weight)
item_type=group       → session:global:{pid}   (commodity, reduced weight)
```

Module sessions stay clean — they only reflect intent within dedicated module feeds.

**Moot as of 2026-07-14** — Home Feed will never forward signals to global session, so the reduced-weight multiplier question no longer needs an answer.

---

## 15. How Global Session Influences Each Module

Global session is read by each module's recommendation engine at feed request time. But what it changes differs per module:

### Posts ✅ (commodity, city, state)
- `merge_weights` blends global commodity/city/state into weight dict → existing pool re-ranked, city/state via `_location_multiplier`
- Second ANN pass for globally-confirmed commodities not in user profile (section 11) — not yet built

### News ✅ (commodity, city, state)
- Commodity filter boost — surface more articles matching global commodity signal, via `get_amplify_weights`
- City/state boost — same treatment, via two separate `get_amplify_weights` calls. **Upgraded 2026-08-05** from a 2-layer, News-only `location` dimension to real 3-layer cross-platform `city`/`state` dimensions — a Mumbai-news reader's location signal now does nudge other modules (Post already reads it; Connections/Groups reading it is still separate, unbuilt work)

### Connections ✅ (commodity only)
- Role interest dimension — captured on signals, not yet read by any boost (dormant)
- City/state — not yet read here (unbuilt, see §11 Gap 3/4 of the companion doc)
- Trade intent (Phase 2) — if user is in buying mode, show sellers — not built

### Groups ✅ (commodity only)
- Commodity match boost — groups related to globally-active commodity score higher
- City/state — not yet read here (unbuilt, same as Connections)

### Home feed — ❌ excluded, not applicable
Not a reader of global session, and never will be — see §13/§14.

**Commodity, city, and state cross-module influence is live for Posts and News.** Connections/Groups still only read commodity — city/state reading there, plus role_interest/trade_intent everywhere, remain module-local, dormant, or unbuilt per the notes above. Home Feed is out of scope entirely.

---

## 16. Scheduler Jobs

| Job | Frequency | Function | Status |
|---|---|---|---|
| `posts.expiry` | Every 1 hour | Partition aging, soft-expire, hard-delete cold | ✅ Unchanged |
| `posts.popular` | Every 15 min | Recompute velocity-based popular pool | ✅ Unchanged |
| `posts.taste_update` | Every 12 hours | Process unprocessed dwell events → `user_post_taste` | ✅ Moved from 15 min 2026-07-07 |
| `posts.ignore_detect` | Daily 3am IST | Repeated-ignore negative signals → `user_post_taste` | ✅ Unchanged |
| `taste.global_promotion` | Daily 3:15am IST | Global Session → Persistent Taste (three-gate promotion) | ✅ Wired 2026-07-07 (job id differs from the originally proposed `posts.global_persist`) |

---

## 17. Redis Persistence Strategy

| Layer | Persistence | Rationale |
|---|---|---|
| Module Session | None | 2h TTL — volatile by design. Loss = fresh session on next interaction. |
| Global Session | RDB snapshots every 5 minutes | Up to 5 min cross-module signals lost on restart. Persistent taste still serves feed. |

### Redis Failure Handling
Both write path and read path fail silently:
- Write: `write_signals` in try/except → batch endpoint returns 200, DB write succeeds
- Read: `merge_weights` in try/except → feed falls back to persistent weights, still serves

---

## 18. Open Decisions

### 18.1 — Home feed signal reduced weight multiplier — ❌ moot, cancelled 2026-07-14
Home Feed will never forward signals to global session — see §14 (cancelled). No multiplier needed.

### 18.2 — Second ANN pass trigger threshold ✅ Resolved 2026-07-06
Full threshold (100%), unchanged from the original proposal — not lowered.

### 18.3 — Session-modified vector construction ✅ Resolved 2026-07-06
Per-dimension override, not a blend formula: use the session/global value for a dimension if one exists, else fall back to the profile value, decided independently per dimension rather than one global α ratio. See §13.1 of the companion doc for the full writeup — same decision, don't duplicate here.

### 18.4 — Global session Phase 2 dimension sourcing — ✅ location fully built 2026-08-05, role interest still partial
- **Location:** ✅ built — dual dimension (`city` primary, `state` fallback), both real 3-layer cross-platform dimensions. Turned out to need no reverse-geocoding utility anywhere: Post uses the author's existing `Business.city`/`Business.state` (zero schema change), and News' `EnrichedArticle` gained `location_city`/`location_state` (plus supplementary `latitude`/`longitude`) filled directly by the LLM enrichment prompt, not derived from coordinates. The interim 2026-07-14 state-only, 2-layer, News-local `location` dimension is retired — superseded by this full build.
- **Role interest:** ✅ resolved — both connection/group interactions (already captured as `role_id` on signals, unused by scoring) and post author roles (piggybacking on the existing author-affinity threshold, not yet built for Posts).

### 18.5 — Trade intent detection ✅ Resolved 2026-07-06 — on hold indefinitely
Not collected at all, not just deferred — `deal_req` has no buy/sell direction field to key off today. Revisit only if that field gets added.

### 18.6 — Global session seeding of module session (cold start) ❓ Still open
Not revisited. Implicit design (as originally written) stands by default.

### 18.7 — Migration for `user_global_taste` ✅ Done 2026-07-07
`UserGlobalTaste` registered in `alembic/env.py`; migration `b7c8d9e0f1a2` created and verified (upgrade/downgrade SQL both checked offline against the Postgres dialect).

### 18.8 — Old feed session taste (`app/modules/feed/session_taste.py`) — ❌ moot, cancelled 2026-07-14
Stays exactly what it is — standalone, Home-Feed-internal, never migrated into `app/modules/taste/`.

### 18.9 — Popular posts soft scoring implementation ✅ Recommended, feature itself still parked
Recommended location: inside `_get_popular_posts()`, where `commodity_idxs` is already in scope — avoids threading profile/session context through a separate downstream step. Not locked in as urgent since the popular-posts feature itself (§12) was explicitly skipped for now; revisit together when that work resumes. Note: this needs its own tiered multiplier (1.3×/1.15×/1.0×), not the continuous-ratio `commodity_boost` from `amplify.py` — see §13.11 of the companion doc.

---

## 19. Implementation Sequence (Recommended)

1. ✅ **Wire post write path** — `process_interaction_batch` + router Redis dep — done 2026-07-14 (category+commodity; author deferred); city+state added 2026-08-05
2. ✅ **Wire post read path** — `get_recommended_posts` + router Redis dep — done 2026-07-14 (via `sync_module_to_global`/`merge_weights` directly, not `get_amplify_weights` — see §10); city+state added 2026-08-05
3. ✅ **Create `user_global_taste` migration** — done 2026-07-07
4. ✅ **Wire nightly promotion scheduler job** — done 2026-07-07 (as `taste.global_promotion`); generalized to loop over all registered dimension types (commodity, city, state) 2026-08-05
5. ✅ **Move taste_update job from 15 min → 12 hours** — done 2026-07-07
6. ❌ ~~Wire feed engagement endpoint~~ — cancelled 2026-07-14, Home Feed excluded permanently
7. 🔲 **Fix popular posts** — remove commodity filter, add soft scoring — explicitly parked, not urgent
8. 🔲 **Implement second ANN pass** — session-driven pool expansion — construction rule + trigger threshold resolved (§18.2/18.3), full implementation spec written 2026-08-05 (§11.1–11.5), scoped to **Posts + Groups only** (Connections explicitly excluded by user decision) — not yet built
9. **Phase 2 global session dimensions** — city/state ✅ done 2026-08-05 (full cross-platform, superseding the old News-local `location` dimension), role_interest (✅ sourcing resolved, scoring not wired), trade_intent (🔲 scaffolded into `CROSS_PLATFORM_DIMS` 2026-08-05, feature itself on hold indefinitely)
10. ✅ **Phase 2 per-module global session reads** — News done 2026-07-14 for commodity, upgraded 2026-08-05 so city/state are also read via `get_amplify_weights` (no longer a News-local `location` dimension); Post gained city/state reads the same day; connections/groups still commodity-only, live since `cfb9350`
11. ❌ ~~Dynamic FEED_WEIGHTS~~ — cancelled 2026-07-14, Home Feed excluded permanently
12. 🔲 **Phase 3 global session dimensions** — quantity scale, content mode

**Also done, not originally on this list:** fixed the module→global `conf`/`neg` sync bug (§4) that would have made step 4 promote nothing (2026-07-07); added Posts' author-dimension deferral and the `get_amplify_weights` persistent-source correction (2026-07-14, see §10); News wiring + the same persistent-source correction applied there too, plus a new News-local `location` dimension (2026-07-14); Home Feed permanently excluded from this system (2026-07-14) — steps 6 and 11 above are cancelled, not pending; **2026-08-05:** the global-session infra was generalized to any dimension type, the News-local `location` dimension was retired in favor of real cross-platform `city`/`state` dimensions, Post gained the same two dimensions with zero schema changes (join to the author's existing `Business.city`/`Business.state`), and `trade_intent` was added to `CROSS_PLATFORM_DIMS` as inert scaffolding.
