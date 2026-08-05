# Dynamic Recommendation Architecture — Cross-Module Reference

> Date: 2026-07-03 (updated 2026-07-14)  
> Audience: All module owners — Posts, News, Connections, Groups  
> Status: ✅ Coded · 🔲 Planned · ❓ Open decision

**2026-07-07 update:** Connections & Groups Mechanism-1 (amplify) shipped (`cfb9350`) plus infra follow-ups this session — `app/modules/taste/amplify.py` (the shared `get_amplify_weights`/`commodity_boost`/commodity id↔name map), the `user_global_taste` migration, the nightly promotion scheduler job, and a fix for a real bug where `conf`/`neg` never propagated from module session to global session (global influence was silently always 0% until this was fixed). See §10, §11, and §13 for what's now resolved vs. still open. Posts and News are still fully unwired.

**2026-07-14 update (Posts):** Posts write+read wiring shipped — category + commodity dimensions only (author dimension deliberately deferred). Also caught and corrected an assumption from the previous session: Posts must NOT call `get_amplify_weights` for its commodity dimension, since that helper unconditionally sources "persistent" from `user_global_taste` (sparse, cross-platform) rather than Posts' own mature `user_post_taste` table. Posts calls `sync_module_to_global`/`merge_weights` directly instead — see §8.1, §10, §13.11, §14.

**2026-07-14 update (News):** News write+read wiring shipped the same day — commodity (3-layer, via `get_amplify_weights`) + a new **location** dimension (2-layer, News-only, `MergeWeights` gained a `"location"` branch mirroring category/author). All 5 News interaction endpoints wired. Also corrected: News *does* have its own legacy persistent table (`UserNewsTaste`) — the earlier claim that it didn't was wrong — it just doesn't collide with this wiring since it only ever writes `"category"`. See §4.4, §8.2, §13.11, §14.

**2026-07-14 decision — Home Feed removed from scope, permanently:** Home Feed will **not** be wired to this taste system — not parked, not a future phase, decided out. Its own type-mix mixer (`app/modules/feed/`, static `FEED_WEIGHTS`, the separate `session_taste.py`) continues to exist and evolve independently, but none of it will integrate with `app/modules/taste/`. **This closes out the taste-wiring roadmap: Posts, News, Connections, and Groups are all wired — there is no remaining unwired module.** All prior references to Home Feed as "parked" or "next" throughout this doc are superseded by this decision; see §4.7, §8.5, §11 Gap 5, §13.2/13.9, §14 for the corresponding sections marked cancelled.

**2026-08-05 update — Global session generalized beyond commodity; city+state now full cross-platform dimensions; trade_intent scaffolded.** The global-session layer was structurally hard-wired to commodity only (method names like `write_commodity_delta`, Redis fields like `commodity:{id}:*`). It's now dimension-type-generic — `write_dimension_delta`/`read_dimension_weights`/`read_dimension_score`/`read_all_dimension_data`, Redis fields `{dimension_type}:{key}:*`. `CROSS_PLATFORM_DIMS` expanded to `{commodity, city, state, trade_intent}`. `SyncModuleToGlobal` now loops over all of them internally — **no existing caller anywhere needed to change**, since `sync_module_to_global(rc, profile_id, module)`'s external signature is untouched. Nightly promotion generalized the same way (loops every dimension type present, via a per-type threshold-function registry; `trade_intent` is silently skipped — no promotion logic decided for it yet).

City and state are now real 3-layer (persistent+global+module) dimensions, replacing News' earlier 2-layer, News-local-only "location" dimension entirely (that branch in `MergeWeights._influence` is gone, replaced by proper `city`/`state` branches). Wired for both News (upgraded) and Post (net-new — Post had never touched location before). **Key finding that simplified Post's side:** Post's author `Business` record already has real `city`/`state` fields (independently client-supplied, not geocoded) — Post's location signal is just a join through `post → profile → business`, no schema change needed. News required real schema work: `EnrichedArticle` gained `location_city`/`location_state`/`latitude`/`longitude`, with the LLM prompt extended to name the primary place directly (an entity-recognition task, not asking the model to compute coordinates) — no reverse-geocoding utility was built or needed anywhere.

`trade_intent` is recognized by the infra (syncs, would promote if it had data) but has **no writer anywhere** — the real feature (daily buy/sell/explore declaration + behavioral drift, logarithmic decay if resumed) stays on hold. Connections/Groups reading city/state themselves remains a separate future pass — see §11 Gap 3/4.

---

## 1. Core Philosophy

Three principles govern this system:

**Principle 1 — Recency of intent matters**  
A user's session behavior is a stronger signal of what they want *right now* than months of history. The system gives immediate weight to session signals while protecting long-established preferences from short-term noise.

**Principle 2 — Cross-module coherence**  
What a user engages with on News should gently influence their Posts, Connections, and Groups feeds. The global session taste layer carries this cross-module theme without each module needing to know about the others.

**Principle 3 — Conservative identity change**  
One day of unusual activity does not change who a user is. Persistent taste evolves slowly and deliberately. Session taste is volatile and ephemeral — it responds fast but evaporates. The system is designed so a single trading day's novelty creates gentle ripples, not permanent shifts.

---

## 2. The Three Layers

```
┌──────────────────────────────────────────────────────────────────┐
│                   MODULE SESSION TASTE  (Layer 1)                 │
│  Redis · per module · 2h inactivity TTL                           │
│  "RAM — what you are thinking about right now, in this module"    │
│                                                                    │
│  session:post:{pid}   session:news:{pid}                          │
│  session:connections:{pid}   session:groups:{pid}                 │
│  session:home:{pid}   (type-mix only)                             │
└──────────────────────────┬───────────────────────────────────────┘
                           │  commodity delta sync on each feed request
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                   GLOBAL SESSION TASTE  (Layer 2)                 │
│  Redis · cross-module · 1 day TTL                                 │
│  "Working memory — the theme of today across everything"          │
│                                                                    │
│  session:global:{pid}                                             │
└──────────────────────────┬───────────────────────────────────────┘
                           │  nightly promotion (three-gate filter, 3am IST)
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                   PERSISTENT TASTE  (Layer 3)                     │
│  PostgreSQL · no TTL · decays at 30-day half-life                 │
│  "Long-term memory — who you are as a trader"                     │
│                                                                    │
│  user_post_taste · user_global_taste                              │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. Complete Pipeline — Generic Flow

This flow applies identically across all modules. The only difference is which dimensions each module produces and which it consumes.

```
USER INTERACTION
      │
      ├── DB write (post_interaction_events / news saves / connection events)
      │
      └── SIGNAL TRANSLATION
                │
                ▼
          SessionSignal objects
          (dimension_type, dimension_key, action, occurred_at_unix)
                │
                ▼
          MODULE SESSION TASTE  session:{module}:{pid}
          HINCRBYFLOAT  pos / neg / conf fields
          HINCRBY       cnt field
          HSET          ts field
          EXPIRE        TTL reset (2h inactivity)
                │
          ┌─────┴──────────────────────────────────────┐
          │ Job 1: On each feed request                 │
          │ sync commodity delta → session:global:{pid} │
          └─────────────────────────────────────────────┘
                │
                ▼
          GLOBAL SESSION TASTE  session:global:{pid}
          commodity:{id}:pos / neg / conf / cnt / ts
          (+ location / role_interest / type_mix in Phase 2)
                │
          ┌─────┴─────────────────────────────────────────────┐
          │ Job 2: At feed request time                        │
          │ merge_weights: blend persistent + global + module  │
          └────────────────────────────────────────────────────┘
                │
                ├── AMPLIFY  Re-rank existing candidate pool
                │
                └── DISCOVER  Expand pool (second/third pass)
                              for session-active dimensions
                              not covered by static profile
                │
                ▼
          FEED SERVED TO USER
                │
          ┌─────┴────────────────────────────────────────────────┐
          │ Job 3: Nightly 3am IST                                │
          │ global session → user_global_taste (promotion gates)  │
          └───────────────────────────────────────────────────────┘
```

---

## 4. Module Session Taste — Per Module

### 4.1 Redis Key Structure (all modules)

```
session:{module}:{profile_id}

Hash fields:
{dim_prefix}:{dim_key}:pos     Float  accumulated positive score
{dim_prefix}:{dim_key}:neg     Float  accumulated negative score
{dim_prefix}:{dim_key}:conf    Float  accumulated confidence score
{dim_prefix}:{dim_key}:cnt     Int    event count
{dim_prefix}:{dim_key}:ts      Int    unix timestamp of last event
{dim_prefix}:{dim_key}:synced  Float  pos snapshot at last global sync

_total_events                  Int    total events (all dimensions)
_session_start                 Int    first event timestamp (set once)
_last_event_at                 Int    most recent event timestamp
_last_synced_ts                Int    last module→global sync timestamp
```

Dim prefix: `cat` = category, `com` = commodity, `aut` = author, `cit` = city, `sta` = state, `rol` = role_interest, `tin` = trade_intent (scaffold only, nothing writes it yet)

### 4.2 Per-Module Dimensions

| Module | Dimensions held | Cross-platform (syncs to global) |
|---|---|---|
| Post | category, commodity, author, city, state | commodity, city, state |
| News | commodity, city, state | commodity, city, state |
| Connections | commodity, role_interest | commodity, role_interest |
| Groups | commodity | commodity |
| Home | type_mix only (separate structure) | type_mix |

**Why category and author stay local:**  
"deal_req" is a post concept — meaningless to news or connections. An author's profile_id is a post concept. These have no cross-module significance. Commodity, city, and state are universal across all modules on this platform (`CROSS_PLATFORM_DIMS`); `trade_intent` is reserved in the same set as a scaffold but has no writer yet.

### 4.3 Post Module Session ✅ Wired 2026-07-14 (category + commodity only)

**Signals produced (as actually implemented):**

| Client event | Classified as | Dimensions written |
|---|---|---|
| impression | IMPRESSION | category, commodity |
| dwell < 2s | DWELL_BOUNCE | category (neg), commodity (neg) |
| dwell 2–8s | DWELL_SHORT | category, commodity |
| dwell 8–30s | DWELL_MEDIUM | category, commodity |
| dwell ≥ 30s | DWELL_LONG | category, commodity |
| open_read_more | OPEN_READ_MORE | category, commodity |
| open_carousel | OPEN_CAROUSEL | category, commodity |
| open_comments | OPEN_COMMENTS | category, commodity |
| link_click | LINK_CLICK | category, commodity |
| like / save / comment / share | explicit (via other endpoints, not the batch path) | category, commodity |

🔲 **Author dimension deliberately deferred** — not a gap, a deliberate scope decision for this pass. The batch endpoint (`process_interaction_batch`) only ever handles the passive/implicit events above; like/save/comment/share still flow through the older `record_interaction` path (persistent taste only, unchanged). Add author to session taste later by mirroring `record_interaction`'s existing gate (`pos_delta ≥ 2.0 AND author ≠ viewer`) in `write_post_signals` (`app/modules/taste/amplify.py`).

**Feed effect (✅ live):** Category, commodity, author, city, and state weight dicts blended before `_rerank()`. Author blend still works today — it's just persistent+module with module always empty (session never writes it), a safe no-op degeneration, not a bug.  
**Global contribution (✅ live):** Commodity delta synced on each feed request, via `sync_module_to_global` called directly (not via `get_amplify_weights` — see §13.11 for why).  
**City/state (✅ built 2026-08-05):** Post needed no new schema — the author's `Business.city`/`Business.state` (already populated, used elsewhere) are joined in at write time (`post_user_interaction/service.py`) and read time (`post_recommendation_module/service.py`, via `read_global_taste_weights` since Posts has no legacy per-module persistent table for city/state the way it does for commodity). `_location_multiplier` applies the boost in `_rerank`, city taking priority over state.

### 4.4 News Module Session ✅ Wired (commodity 2026-07-14, city+state upgraded to full cross-platform 2026-08-05)

**Signals produced (as actually implemented, all 5 endpoints):**

| User action | Signal type | Dimensions written |
|---|---|---|
| impression (batch) | IMPRESSION | commodity, city, state |
| dwell (batch, bucketed) | DWELL_BOUNCE/SHORT/MEDIUM/LONG | commodity, city, state |
| open_article (batch) | OPEN_READ_MORE (aliased) | commodity, city, state |
| share_tap (batch) | SHARE (aliased) | commodity, city, state |
| like / save / share / send (explicit endpoints) | LIKE / SAVE / SHARE | commodity, city, state |
| revisit (server-generated) | REVISIT | commodity, city, state |

City/state keys = `EnrichedArticle.location_city`/`location_state` (LLM-extracted directly as text — the single primary place the story is about, not derived from coordinates), lowercased/stripped. **Superseded** the original state_tags-based 2-layer "location" dimension entirely — city/state are now real 3-layer cross-platform dimensions, same as commodity.  
Commodity key = `EnrichedArticle.commodity_tags`, resolved name→id via the shared `commodity_ids_for(db, ...)`.

**Feed effect (✅ live):** Commodity, city, and state boosts multiplied into `get_recommended_feed`'s existing `apply_profile_boost` score, each read via its own `get_amplify_weights(db, rc, profile_id, "news", "city"/"state")` 3-layer call.  
**Global contribution (✅ live):** Commodity, city, and state deltas all sync via `get_amplify_weights` → `sync_module_to_global`, same as Posts/Connections/Groups — city/state are no longer News-local.

✅ **City/state are now real 3-layer, cross-platform dimensions (2026-08-05)**, superseding the old 2-layer News-only "location" dimension. A Mumbai-news reader's location signal now flows into global session the same way commodity does. Connections/Groups reading it themselves is still not built (no location-boost mechanism there today) — separate future pass, see §13.11.

### 4.5 Connections Module Session ✅ Mechanism 1 wired (`cfb9350`)

**Signals produced (as actually implemented in `app/modules/taste/amplify.py` + `connections/service.py`):**

| User action | Signal type | Dimensions written |
|---|---|---|
| Follow a user | connection_follow | commodity (+ role, captured but not yet read by scoring) |
| Send a message request | connection_msg | commodity (+ role) |
| View a profile card | connection_view | commodity (+ role) — dedicated `POST /connections/view`, Redis-only, no DB write |
| Accept / dismiss | connection_accept / connection_dismiss | legacy actions, kept for the feed module — not written by connections' own endpoints |

Search-by-commodity/role signals described in the original design were not built — search intent parsing exists (`_parse_search_intent`) but doesn't feed session taste.

**Feed effect (Mechanism 1 — amplify, ✅ live):** `get_recommendations` re-ranks the already-fetched page via `get_amplify_weights` + `commodity_boost` — no WANT-vector modification yet.  
**Global contribution:** Commodity delta synced via `get_amplify_weights` → `sync_module_to_global`. Role_interest does **not** sync to global — role stays module-local for now (see §13.5).

❌ **Mechanism 2 explicitly excluded for Connections** (user decision, 2026-08-05 — "can connections part be skipped for now?"). Not planned, not in the 2026-08-05 Posts+Groups spec (see §7, §8.3). Role-based boosting captured in signals but not read by any scoring step yet, independent of Mechanism 2.

### 4.6 Groups Module Session ✅ Mechanism 1 wired (`cfb9350`)

**Signals produced (as implemented):**

| User action | Signal type | Dimensions written |
|---|---|---|
| View a group / suggestion | group_view | commodity (of group) — dedicated `POST /api/v1/groups/view`, Redis-only |
| Join a group | group_join | commodity (resolved from the group's own `commodity` field) |
| Dismiss a suggestion | group_dismiss | commodity (neg) — signal weight exists but no dismiss endpoint calls it yet |

**Feed effect (Mechanism 1 — amplify, ✅ live):** `get_group_suggestions` computes `final = compute_final_score(sim × commodity_boost, activity)` — commodity boost applied to the semantic score before the activity blend, exactly as originally planned.  
**Global contribution:** Commodity delta synced via the same `get_amplify_weights` path as Connections.

🔲 **Mechanism 2 (second ANN pass) — spec written 2026-08-05** (`recommendation_taste_architecture.md` §11), not built. See §8.4.

### 4.7 Home Feed Session — ❌ out of scope, will not be wired (decided 2026-07-14)

Home Feed is **not part of this taste system and never will be.** It has its own independent type-mix mixer (`app/modules/feed/`, JSON blob at `session:{profile_id}:{session_id}` in `app/modules/feed/session_taste.py`, static `FEED_WEIGHTS`) that tracks content-type-mix preference — how much of each module to show — and that's a genuinely separate concern from commodity/category/location taste. That file may continue to be developed on its own terms, but it will not integrate with `app/modules/taste/`, will not read or write `session:global:{pid}`, and no `type_mix` global-session dimension will be built.

(The rest of this section previously described a planned integration — struck entirely, not just deferred.)

---

## 5. Global Session Taste — Finalized Dimensions

### 5.1 Redis Key
```
session:global:{profile_id}
TTL: 1 day (explicitly cleared after nightly promotion, not rolling)
```

### 5.2 Dimension Table

| Dimension | Phase | Redis field pattern | Written by | Read by |
|---|---|---|---|---|
| Commodity | 1 ✅ | `commodity:{id}:pos/neg/conf/cnt/ts` | Post, News, Connections, Groups | All modules |
| City | ✅ Done 2026-08-05 | `city:{key}:pos/neg/conf/cnt/ts` | Post, News | Post, News |
| State | ✅ Done 2026-08-05 | `state:{key}:pos/neg/conf/cnt/ts` | Post, News | Post, News |
| Trade intent | 🔲 Scaffolded only, feature on hold | `trade_intent:buying` / `trade_intent:selling` | *(none — no writer built)* | *(none — no reader built)* |
| Role interest | 2 🔲 | `role_interest:{role_id}:pos/neg/conf/cnt/ts` | Connections | Connections, Post |
| Quantity scale | 3 🔲 | `qty_scale:small/medium/large/bulk` | Post (deal sizes) | Post, Connections |
| Content mode | 3 🔲 | `content_mode:transactional/informational` | Post (category dominance) | News |

City/state read by Connections/Groups is not yet built (they have no location-boost mechanism at all today) — separate future pass, see §11 Gap 3/4.

**Type mix — ❌ cancelled 2026-07-14, removed from this table.** Was going to be Home Feed's cross-day type preference; Home Feed will not integrate with global session at all (§4.7).

### 5.3 What Does NOT Belong in Global Session

| Dimension | Why excluded |
|---|---|
| Category (deal_req etc.) | Module-specific — post concept, no cross-module meaning |
| Author affinity | Module-specific — a post author's ID is meaningless to news/connections |
| Raw events | Too granular, no cross-module utility |
| Article-specific metadata | Module-specific |

### 5.4 Cross-Module Examples

1. **Rice trader dwells Sugar news** → `commodity:sugar` accumulates in global → Posts, Connections, Groups all get mild Sugar tint
2. **Vizag user reads Mumbai-datelined articles** → `city:mumbai` accumulates in global → Mumbai connections, Mumbai trade posts surface (Connections/Groups reading it is not yet built — see §11 Gap 3/4)
3. **Cotton exporter searches rice exporters in connections** → `role_interest:exporter + commodity:rice` in global → Rice exporter posts and rice news surface
4. **User engages heavily with buying deal_req posts** → `trade_intent:buying` in global → Connections surfaces sellers, News surfaces supply articles

### 5.5 How Delta Flows Module → Global

On each feed request, `sync_module_to_global` runs, per commodity key:
```
pos_delta  = com:{id}:pos  - com:{id}:synced
neg_delta  = com:{id}:neg  - com:{id}:neg_synced
conf_delta = com:{id}:conf - com:{id}:conf_synced
```
Only the NEW increment since the last sync is pushed for each of the three fields. Prevents double-counting across multiple feed requests in one session. After write: `mark_synced` stores all three current values as the new snapshot. If write fails: snapshot not updated → safe retry.

✅ **Fixed 2026-07-07:** originally only `pos` was tracked this way — `neg`/`conf` were never written to global session at all, meaning global influence in `merge_weights` was silently always 0% and the nightly promotion job's confidence gate (§9) would have failed unconditionally forever. All three fields now sync correctly.

City/state now use this exact same delta-sync pattern as commodity (✅ done 2026-08-05, generalized via `write_dimension_delta`/`get_dimension_delta_and_snapshot`). Phase 2+: same pattern for role_interest once it's read anywhere.

---

## 6. Influence Blend — Read Time

This formula applies at every module's feed request. The module passes its own `module` string — the infrastructure is shared.

```
m_influence = MODULE_MAX(0.31)  × min(m_conf / m_threshold, 1.0)
g_influence = GLOBAL_MAX(0.15)  × min(g_conf / g_threshold, 1.0)
p_influence = max(1.0 - m_inf - g_inf, 0.54)

merged_weight[key] = p_influence × persistent[key]
                   + g_influence × global[key]
                   + m_influence × module[key]
```

**Persistent never drops below 54%. Global never exceeds 15%. Module never exceeds 31%.**

### 6.1 Per-Dimension Blend Rules

| Dimension | Layers blended | Max session influence |
|---|---|---|
| Commodity | persistent + global + module | 46% (31% module + 15% global) |
| Category | persistent + module | 31% |
| Author | persistent + module | 11% (0.31 × 0.35) |
| Location (Phase 2) | persistent + global + module | 46% |
| Role interest (Phase 2) | persistent + global | 15% |

### 6.2 Threshold Scaling (commodity only)

Thresholds scale with persistent score — established traders are harder to shift:

```
Module threshold:  8.0 × (1 + persistent_score / 50)
Global threshold: 12.0 × (1 + persistent_score / 100)
```

New user (persistent=0): module threshold = 8, global = 12  
Active trader (persistent=100): module threshold = 24, global = 24

---

## 7. Pool Expansion — The Two Mechanisms

**Every module's recommendation has two distinct jobs for session taste:**

### Mechanism 1 — Amplify (re-rank existing pool)
Session weights are blended into the scoring function. Items already in the candidate pool that match the user's current session interest surface higher.

**This is what `merge_weights` does.** Already designed and coded. Pending wiring per module.

### Mechanism 2 — Discover (expand the pool)
The candidate pool is built from the user's **registered static profile**. If a user engages with a commodity/role/location NOT in their profile, those candidates will never appear in the pool — there is nothing to re-rank.

**Fix: second (and third) pass with a session-modified query vector.**

```
Pass 1 (always):    Normal query using static profile vector → pool_1
Pass 2 (session):   Modified vector boosting session-active dimensions
                    not in static profile → pool_2
Pass 3 (global):    Modified vector boosting globally-confirmed dimensions
                    not in static profile → pool_3

Final pool = pool_1 + pool_2 + pool_3 (deduplicated)
```

**Trigger conditions:**
- Pass 2 fires when: `session_conf ≥ module_commodity_threshold(persistent_score)` for a commodity NOT in `profile.commodities`
- Pass 3 fires when: `global_conf ≥ global_commodity_threshold(persistent_score)` for a commodity NOT in `profile.commodities`

Of the three modules that use ANN vector search, **this pass is scoped to Posts + Groups only — Connections is explicitly excluded by user decision.** News does not use ANN — session influence there is a scoring boost, not a pool expansion, and never will be a Mechanism 2 candidate.

✅ **Full implementation spec written 2026-08-05** for Posts + Groups — see `documentation/recommendation_taste_architecture.md` §11.1–11.5 for the exact trigger primitives (`read_dim_score`/`read_all_dimension_data`), vector construction (reusing `build_user_feed_vector`/`build_query_vector` with commodity dims substituted, not blended), query/merge mechanics, and one flagged-but-unresolved sub-decision ("stronger cross-module evidence" for the global-session trigger has no quantitative definition yet). Key structural finding baked into that spec: both Posts' and Groups'/Connections' ANN embeddings only encode 3 fixed commodities (cotton/rice/sugar) — Mechanism 2 can only ever discover among those three, not any commodity in the `Commodity` table. Not built yet.

---

## 8. Per-Module Recommendation Architecture

### 8.1 Posts ✅ Mechanism 1 wired 2026-07-14 (category + commodity) · 🔲 Mechanism 2

**Current stack:**  
HNSW pgvector ANN on `post_embeddings` → pool → `_rerank()` → diversity filter → feed cards

**Session taste integration — as built:**
- Write (✅): `process_interaction_batch` → `write_post_signals(rc, profile_id, category, commodity_id, action, city=post_city, state=post_state)` (`app/modules/taste/amplify.py`) — category, commodity, city, state; author deferred. `post_city`/`post_state` come from an outer join to the author's `Business` row, added 2026-08-05, zero new columns.
- Read (✅): persistent weights (`taste_service.get_taste_weights`, unchanged) → `sync_module_to_global` (once) → `merge_weights` × 5 (category/commodity/author/city/state) → `_rerank`. City/state use `read_global_taste_weights` as their persistent floor (Posts has no legacy per-module persistent table for them, unlike commodity's `user_post_taste`). **Does not use `get_amplify_weights`** — see §13.11.
- Expand (🔲): second ANN pass for session-active commodities not in profile — spec written 2026-08-05 (`recommendation_taste_architecture.md` §11), not built.

**Vector dimensions (10D):** cotton(0), rice(1), sugar(2), role_idx(3–5), lat(6), lon(7), is_deal(8), quantity(9)

See `documentation/recommendation_taste_architecture.md` §10 for the full write-up of what was actually built vs. originally planned.

---

### 8.2 News ✅ Mechanism 1 wired 2026-07-14 (commodity), city/state upgraded to full cross-platform 2026-08-05

**Current stack:**  
Time-bucketed candidates → profile boost scoring (`compute_profile_boost`) → sorted by `final_score` → cursor-based pagination

`compute_profile_boost` reads:
- `user_commodities` → boosts articles tagged with matching commodities
- `user_state` → boosts articles from the user's state
- Role-specific score column (`role_trader`, `role_broker`, `role_exporter`)

**No ANN — permanent decision** (§13.8), not a gap. News does not use vector search — ranking is rule-based scoring on enriched article metadata.

**Session taste integration — as built:**

*Write (✅):* All 5 News interaction endpoints (batch + like/save/share/send) call `write_news_signals(rc, profile_id, commodity_ids, location_city, location_state, action)` (`app/modules/taste/amplify.py`) — signature changed 2026-08-05 from a `state_tags` list to the article's single primary `location_city`/`location_state` text fields.

*Read (✅):* Session boost multipliers applied on top of `compute_profile_boost`, exactly as planned:
```python
base = apply_profile_boost(role_score, profile_boost)
final = base * commodity_boost(commodity_weights, ...) * location_boost(city_weights, [enriched.location_city]) * location_boost(state_weights, [enriched.location_state])
```

*Global session contribution (✅):* Commodity, city, and state deltas all sync via `get_amplify_weights` → `sync_module_to_global`, same as Posts/Connections/Groups. City/state are no longer 2-layer/News-local (see §4.4, §13.11).

**Correction from the original plan:** News *does* have its own legacy persistent table (`UserNewsTaste`) — the original "News has no per-module persistent table" claim was wrong. It doesn't collide with this wiring because it only ever writes `dimension_type="category"`, never commodity/city/state — see §13.11.

**No pool expansion needed.** News pool is all enriched articles within 48h — no ANN filter to bypass.

**Accepted risk, not fixed:** News' cursor pagination re-sorts the full candidate pool every request (position-of-last-seen-id, not an encoded score) — session weights changing between page requests can reshuffle not-yet-seen articles across pages. Pre-existing characteristic of the live-rescoring design, just more exposed now that weights change more often. Fixing it would need a ranking snapshot (the already-scaffolded-but-unused `FeedRankingCache` table) — separate, bigger project.

---

### 8.3 Connections ✅ Mechanism 1 · ❌ Mechanism 2 excluded by user decision 2026-08-05

**Current stack:**  
User builds WANT vector → HNSW pgvector ANN on `user_embeddings` → cosine similarity ranked → Redis seen-set exclusion → paginated results

`build_query_vector` uses: role, commodities, lat/lon, qty range from profile.

**Seen-set:** `rec:seen:{user_id}` (Redis Set, 48h TTL) — already-seen connections excluded.

**Session taste integration — as built:**

*Write (✅):* `write_commodity_signals` (in `amplify.py`) on follow/message-request/view → `write_signals(rc, profile_id, "connections", signals)`.

*Read, Mechanism 1 — amplify (✅):* `get_recommendations` calls `get_amplify_weights` then re-ranks the **already-fetched page**:
```python
results.sort(key=lambda r: r["similarity"] * commodity_boost(weights, commodity_ids_for(db, r["commodity"])), reverse=True)
```

*Read, Mechanism 2 — ❌ excluded, not planned:*  
User explicitly excluded Connections from the Mechanism 2 scope ("can connections part be skipped for now?", 2026-08-05). The 2026-08-05 Posts+Groups implementation spec (`recommendation_taste_architecture.md` §11) does not cover Connections — if this is revisited later, the same per-dimension override rule and vector-substitution approach would apply (Connections shares the exact same `build_query_vector`/`ALL_COMMODITIES` encoding as Groups), but nothing here should be built without re-confirming scope first.

*Global session contribution (✅):* Commodity delta synced via `get_amplify_weights`. Role_interest does **not** sync to global (§13.5 — resolved: role stays module-local for now).

**Key difference from posts:** For connections, role is captured per-signal (`dimension_type="role"`) but not yet read by any boost — see §13.5.

---

### 8.4 Groups ✅ Mechanism 1 · 🔲 Mechanism 2

**Current stack:**  
User WANT vector → HNSW pgvector ANN on `group_embeddings` → activity reranking (`compute_activity_score`) → blended 75% semantic + 25% activity → `GroupSuggestionOut`

`build_query_vector` (same as connections): role, commodities, lat/lon, qty from profile.  
`build_match_reasons`: explains why a group was suggested.

**Session taste integration — as built:**

*Write (✅):* `write_commodity_signals` on join (`group_join`, commodities resolved from the group's own record) and view (`group_view`, dedicated `POST /api/v1/groups/view`).

*Read, Mechanism 1 — amplify (✅):* Session commodity boost applied to semantic similarity score before activity blend, exactly as planned:
```
final = compute_final_score(sim × commodity_boost(weights, group.commodity), activity)
```

*Read, Mechanism 2 — expand (🔲 spec written 2026-08-05, not built):*  
Full trigger/vector-construction/query/merge spec in `recommendation_taste_architecture.md` §11.1–11.5 — session-modified `want_vec` via `build_query_vector(commodity_list=[discover_commodity_name], ...)`, substituting the discover candidate for the profile's registered commodities rather than blending. Needs an id→name resolution step (invert `commodity_id_by_name`) since Groups' encoder takes name strings but session/global taste keys commodities by id.

*Global session contribution (✅):* Commodity delta synced via `get_amplify_weights`.

---

### 8.5 Home Feed — ❌ out of scope, will not be wired (decided 2026-07-14)

**Current stack (unaffected by this decision, still real code):**  
`service.py` → parallel fetch from all four module pipelines → `mix_feed` → weighted random slot assignment

Post pipeline (3 sources): following(50%) + popular(30%) + recommendation(20%)  
News pipeline: trending + recommended (deduped, trending first)  
Connection/Group: direct from their recommendation engines

**Static `FEED_WEIGHTS`** currently: `{post:0.45, news:0.25, group:0.15, connection:0.15}` — stays static, or evolves independently. `app/modules/feed/session_taste.py`'s `compute_weights` may still be wired into the mixer someday, but that's a Home-Feed-internal decision, not part of this taste system. No `type_mix` global-session dimension, no `submit_engagement`-to-global-session forwarding, no module-session writes from Home Feed — none of it will be built.

---

## 9. Nightly Promotion — Global → Persistent

Runs at 3am IST. Per commodity key per user.

**Three gates (all must pass):**

| Gate | Condition | Filters out |
|---|---|---|
| Confidence | `conf ≥ 0.70 × global_commodity_threshold(persistent_score)` | Weak passive browsing |
| Quality | `pos - (neg × 0.6) ≥ 20` | Low-engagement days |
| Events | `cnt ≥ 10` | Isolated bursts |

**Promotion formula:**
```
global_delta = pos - (neg × 0.6)
persistent_score += 0.15 × global_delta
```

**Safety order (inviolable):**
1. READ global session from Redis
2. Run gates per key
3. WRITE qualifying deltas to PostgreSQL → COMMIT
4. CLEAR global session → only after DB confirms

✅ **Wired 2026-07-07** as scheduler job `taste.global_promotion` (cron 3:15am IST, staggered 15min after `posts.ignore_detect`). No separate `promotion_flushed_at` idempotency flag was built — clearing the Redis key after a successful commit already prevents double-promotion (if nothing was promoted, the key isn't cleared, so sub-threshold data just keeps accumulating toward a future promotion instead of being lost). Depended on a new `scan_active_profile_ids` method (didn't exist before — nothing could enumerate which profiles have a live `session:global:*` key) added to `IGlobalSessionRepository`.

---

## 10. What Exists in the Codebase Today

### Taste module ✅ (complete, wired into Connections/Groups)
```
app/modules/taste/
├── session_taste/     — RedisModuleSessionRepository, WriteSignals, MergeWeights
├── global_session/    — RedisGlobalSessionRepository, SyncModuleToGlobal, MergeWeights, scan_active_profile_ids
├── global_taste/      — UserGlobalTaste model (migrated ✅), PostgresGlobalTasteRepository, PromoteFromGlobalSession
└── amplify.py         — shared read/write glue for module recommenders —
                          get_amplify_weights, commodity_boost, location_boost, commodity_id_by_name,
                          write_commodity_signals, write_post_signals, write_news_signals. Used by
                          Connections, Groups, Posts, News.
```
All three layers are coded and wired into Connections/Groups/Posts/News. `user_global_taste` migration exists (`b7c8d9e0f1a2`). Nightly promotion job is live. The module→global conf/neg sync bug (§5.5) is fixed.  
Commodity, city, and state are all active cross-platform dimensions as of 2026-08-05 — the global-session infra was generalized from commodity-only to any dimension type (§13.4). `trade_intent` is reserved in `CROSS_PLATFORM_DIMS` as a scaffold, no writer. Role_interest is captured in signals in places but not yet read by any scoring step (see §13.5).

### Posts ✅ (recommendation engine complete, taste Mechanism 1 wired 2026-07-14, city/state added 2026-08-05)
- `post_recommendation_module/service.py` — full ANN + rerank pipeline, now blends session/global commodity/city/state + module category/author via `sync_module_to_global`/`merge_weights` (not `get_amplify_weights` for commodity/category/author — see §13.11; city/state use `read_global_taste_weights` as their persistent floor)
- `post_user_interaction/service.py` — batch endpoint writes category+commodity+city+state session signals via `write_post_signals` after `db.commit()`; city/state come from an outer join to the author's `Business` row (no schema change); author dimension still deferred
- Mechanism 2 (second ANN pass) and popular-posts soft scoring remain unbuilt

### News ✅ (recommendation engine complete, taste Mechanism 1 wired 2026-07-14, city/state upgraded to cross-platform 2026-08-05)
- `news_new/feed/service.py` — `get_recommended_feed` now multiplies `commodity_boost`/`location_boost` (city + state, each its own 3-layer call) into the existing `apply_profile_boost` score
- `news_user_interaction/service.py` — all 5 endpoints (batch + like/save/share/send) write session signals via `write_news_signals`, using `EnrichedArticle.location_city`/`location_state`
- City/state are now real 3-layer cross-platform dimensions, same as commodity — see §4.4, §13.11
- `UserNewsTaste` legacy persistent table exists (contra earlier doc claim) but only ever writes `"category"`, so it doesn't collide with this wiring

### Connections ✅ (recommendation engine complete, taste Mechanism 1 wired)
- `connections/service.py` — `get_recommendations` uses HNSW ANN with static profile WANT vector, re-ranks the fetched page via `get_amplify_weights`/`commodity_boost`
- Redis seen-set already in place
- Search intent parsing (`_parse_search_intent`) extracts role/commodity from free-text but doesn't feed session taste
- Mechanism 2 excluded by user decision 2026-08-05 — not planned

### Groups ✅ (recommendation engine complete, taste Mechanism 1 wired)
- `groups/service.py` — `get_group_suggestions` uses HNSW ANN + activity reranking + commodity boost on the semantic score
- Intent parsing for list/search already exists
- Mechanism 2 (second ANN pass) — spec written 2026-08-05, not built

### Home Feed ✅ (mixer complete, own type-mix system — ❌ will not integrate with this taste system)
- `feed/service.py` — parallel fetch + mix_feed
- `feed/session_taste.py` — type-mix session taste, independent of `app/modules/taste/`, may or may not get wired into the mixer someday — Home-Feed-internal decision
- `feed/router.py` — `POST /feed/engagement` is a stub; will not forward to global session
- `FEED_WEIGHTS` is static
- Out of scope for this taste system, decided 2026-07-14 — see §4.7

---

## 11. Gaps Per Module

### Gap 1 — Posts ✅ 2/4 done
1. ✅ `process_interaction_batch` + router: Redis write after DB commit (category + commodity + city + state; author deferred)
2. ✅ `get_recommended_posts` + router: `sync_module_to_global` + `merge_weights` before `_rerank`
3. 🔲 Second ANN pass for session-active commodities — not built
4. 🔲 Popular posts: remove commodity hard filter, add soft scoring (1.3× / 1.15× / 1.0×) — parked

### Gap 2 — News ✅ done
1. ✅ All 5 interaction endpoints write signals via `write_news_signals`
2. ✅ `get_recommended_feed` multiplies commodity/city/state boost into the score before sort
3. ✅ `get_recommended_feed` + router inject Redis, call `get_amplify_weights` (commodity, city, state — all 3-layer as of 2026-08-05)

### Gap 3 — Connections ✅ 2/3 done, 3rd item excluded
1. ✅ Connection interaction endpoints write signals for follow/message/view (`connection_accept`/`dismiss` remain unwritten legacy actions)
2. ✅ `get_recommendations` re-ranks the fetched page via `get_amplify_weights`/`commodity_boost`
3. ❌ Second ANN pass with session-modified WANT vector — excluded by user decision 2026-08-05, not planned
4. 🔲 Reading city/state itself (no location-boost mechanism exists here at all today) — separate future pass, not scoped by any current decision

### Gap 4 — Groups ✅ 2/3 done
1. ✅ `group_join`/`group_view` write signals (no dismiss endpoint wired yet)
2. ✅ `get_group_suggestions` applies commodity boost to semantic score before activity blend
3. 🔲 Second ANN pass with session-modified WANT vector — full spec written 2026-08-05 (`recommendation_taste_architecture.md` §11.1–11.5), not built
4. 🔲 Reading city/state itself (no location-boost mechanism exists here at all today) — separate future pass, not scoped by any current decision

### Gap 5 — Home Feed — ❌ cancelled 2026-07-14, not a gap
Home Feed will not be wired to this taste system. See §4.7.

### Gap 6 — Scheduler / Infrastructure ✅ done
1. ✅ `user_global_taste` migration (`b7c8d9e0f1a2`), registered in `alembic/env.py`
2. ✅ Nightly promotion scheduler job wired as `taste.global_promotion` (cron 3:15am IST)
3. ✅ `posts.taste_update` moved from 15 min → 12 hours

**Also fixed, not in the original gap list:** the module→global `conf`/`neg` sync bug (§5.5) — found while wiring Gap 6, since the promotion job would have been a permanent no-op without it.

---

## 12. Recommended Implementation Sequence

### Phase 1 — Core wiring (all modules use existing infrastructure)

| Step | What | Owner | Status |
|---|---|---|---|
| 1 | `user_global_taste` migration | Backend core | ✅ Done |
| 2 | Post write path | Posts team | ✅ Done (category+commodity; author deferred) |
| 3 | Post read path | Posts team | ✅ Done |
| 4 | News session write | News team | ✅ Done (commodity + city + state, all 5 endpoints) |
| 5 | News session read | News team | ✅ Done |
| 6 | Connections session write | Connections team | ✅ Done |
| 7 | Connections session read + second pass | Connections team | ✅ read done · ❌ second pass excluded 2026-08-05 |
| 8 | Groups session write | Groups team | ✅ Done |
| 9 | Groups session read + second pass | Groups team | ✅ read done · 🔲 second pass spec written 2026-08-05 |
| 10 | ~~Home feed session wiring~~ | — | ❌ Cancelled 2026-07-14 |
| 11 | ~~Home feed engagement forwarding~~ | — | ❌ Cancelled 2026-07-14 |
| 12 | Nightly promotion job | Backend core | ✅ Done |
| 13 | Move taste_update job 15min → 12h | Posts team | ✅ Done |

### Phase 2 — Global session Phase 2 dimensions
City/state ✅ done 2026-08-05. Remaining: role_interest wired to be read by scoring (currently write-only/dormant), trade_intent's actual feature (currently scaffold-only in `CROSS_PLATFORM_DIMS`, on hold).

### Phase 3 — Quantity scale, content mode, advanced pool expansion

---

## 13. Open Decisions

### 13.1 Session-modified vector construction ✅ Resolved 2026-07-06
**Decision:** Per-dimension override rule, not a formula/blend-ratio choice. For each dimension the ANN vector encodes: if session/global taste has an active score for that dimension, use it; otherwise fall back to the static profile value for that dimension. Not a global α-weighted blend across the whole vector — dimensions are swapped independently.  
**Today:** commodity, city, and state have session data, so in practice this swaps those dims; role/lat/lon/is_deal/quantity fall back to the profile value. When role_interest becomes a tracked, read dimension, it swaps in under the same rule with no redesign.  
**Applies to:** Posts + Groups (Mechanism 2 spec written 2026-08-05, `recommendation_taste_architecture.md` §11, still 🔲 unbuilt). Connections excluded from Mechanism 2 scope by user decision 2026-08-05 — this rule is not being applied there.

### 13.2 Home feed reduced-weight signal multiplier — ❌ moot, cancelled 2026-07-14
Home Feed will not forward signals to global session at all — see §4.7. This question no longer applies.

### 13.3 Second ANN pass trigger threshold ✅ Resolved 2026-07-06
**Decision:** Keep the original design — full threshold (100% of `module_commodity_threshold`/`global_commodity_threshold`), not a lowered percentage. No change from what was originally specified.

### 13.4 Location key format ✅ Resolved 2026-07-06 — ✅ fully built 2026-08-05
**Decision:** Two independent dimension types, not one hierarchical key — `city:{slug}` (primary) and `state:{slug}` (fallback when a candidate/content item has no city-level match). Matches "city importance, then state importance" as a priority/fallback order, not a blended weight.  
**Per-source, as actually built:**
- **Profile/Business** — used as-is: native `city`/`state` columns (`app/modules/profile/models.py`), independently client-supplied, not geocoded from lat/lon.
- **News** — `EnrichedArticle` gained `location_city`/`location_state` (LLM-extracted directly as text, the one primary place the story is about) + supplementary `latitude`/`longitude`. No reverse-geocoding utility needed or built — the LLM names the place directly, the same entity-recognition task it already did for `state_tags`.
- **Post** — turned out to need **no schema change at all**: the post author's `Business` record already has real `city`/`state` — Post's location signal is just a join through `post → profile → business`, not a reverse-geocode of Post's own lat/lon.
- **Global-session infra** — generalized from commodity-only to any dimension type (`write_dimension_delta` etc.), so city/state get the same real 3-layer (persistent+global+module) treatment as commodity, including nightly promotion.
- **Connections/Groups reading city/state** — still not built (separate future pass; they have no location-boost mechanism at all today).

### 13.5 Role interest — source signals ✅ Resolved 2026-07-06
**Decision:** Both (a) and (b). (a) Roles from connections/groups view/follow/join — **already captured** in `write_commodity_signals`' optional `role_id` param (dimension_type `"role"`), shipped in `cfb9350`, but **not yet read by any scoring step** (dormant data). (b) Roles from post authors — piggyback on Posts' existing author-affinity threshold (`pos_delta ≥ 2.0 AND author ≠ viewer`), which already knows the author's role at that point. Not yet built for Posts. Role_interest still does not sync to global session (module-local only, for now).

### 13.6 Trade intent detection mechanism ✅ Resolved 2026-07-06 — on hold indefinitely, infra scaffolded 2026-08-05
**Decision:** Not even collected yet, not just deferred to a later phase. `deal_req` carries no explicit buy/sell direction today, so there's no reliable signal to key off — inferring intent from connection-counterparty role would be a weak heuristic (a Trader connecting with an Exporter could mean either direction). Revisit only if/when an explicit direction field is added to the post schema.  
**2026-08-05 addition:** while generalizing the global-session infra for city/state, `trade_intent` was added to `CROSS_PLATFORM_DIMS` as pure scaffolding — the sync/promotion machinery recognizes it and will pick up data the moment something writes to it, but nothing writes to it, no `MergeWeights` blend branch exists for it, and no promotion threshold is registered for it. Fully inert until the real feature (daily buy/sell/explore declaration blended with behavioral drift, logarithmic decay if resumed) is designed and built.

### 13.7 Global session seeding of module session on cold open ❓ Still open
Not revisited since the original write-up. Current implicit design (merge_weights reads both layers regardless of module session state, no explicit seeding step) stands by default until someone raises it again.

### 13.8 News ANN expansion ✅ Resolved 2026-07-06 — permanently rejected, not just "Phase 1 default"
**Decision:** News will **never** use ANN or vector embeddings, full stop — not a "for now" choice. Reasoning: news source/schema/provider volatility (ingestion pipeline, article schema) would break stored embeddings over time in a way that's costly to detect and re-sync. News stays rule-based (commodity/city/state tag boosting) permanently.

### 13.9 Old feed session taste migration — ❌ moot, cancelled 2026-07-14
`app/modules/feed/session_taste.py` stays exactly what it is — a standalone Home Feed concern. It will never be migrated into `app/modules/taste/`, since Home Feed isn't integrating with this system at all.

### 13.10 Groups — session signals for group content interactions ❓ Still open — parked, low priority
Tentative lean: route to `session:groups:{pid}` only (not `session:post:{pid}`), following the same "discovery-context signals shouldn't carry full weight into a different module's dedicated session" principle used for Home Feed. Not built, not blocking anything — Groups' Mechanism 1 (`cfb9350`) only covers group-level view/join, not content *inside* a group.

### 13.11 Colleague's 4 taste-infra proposals — reconciled against real code 2026-07-06
Discussed as hypothetical design points, then found to already be mostly implemented in `cfb9350`:
- `get_amplify_weights` orchestration helper → ✅ built (`app/modules/taste/amplify.py`). **Correction found 2026-07-14, more severe than originally flagged:** this isn't just a "don't call it 3× per dimension" efficiency note. `get_amplify_weights` unconditionally sources its "persistent" layer from `read_global_taste_weights` (`user_global_taste`, the sparse cross-platform table). That's correct for Connections/Groups, which have no per-module persistent table of their own — but **Posts has its own mature `user_post_taste` table**, and using `get_amplify_weights` for Posts' commodity dimension would silently swap in the wrong, much sparser persistent source. Posts calls `sync_module_to_global` + `merge_weights` directly instead (once for sync, three times for category/commodity/author merge), keeping `taste_service.get_taste_weights` as the correct persistent floor. Any future module with its own legacy persistent store should do the same — `get_amplify_weights` is only safe for modules with no persistent table besides `user_global_taste`.
- `commodity_boost` shared multiplier → ✅ built, matches Connections/Groups/News' planned formula shape. Does **not** fit Posts (which needs full weight-dict blending for `_rerank()`, plus a separate tier-based multiplier for popular posts) — Posts will need its own logic, not this helper.
- Canonical commodity id↔name map → ✅ built as `commodity_id_by_name(db)` in `amplify.py`, DB-backed via the `Commodity` table, cached process-wide. Scoped to the taste/signal-key mapping only — the ANN vector encoder's positional slot convention (`cotton(0), rice(1), sugar(2)` in §8.1) is a **separate, intentionally static** mapping and must stay that way; conflating the two would require re-embedding every stored vector on any commodity-table change.
- Universal `/taste/signal` ingest endpoint → **not built as a single universal endpoint.** Instead: module-specific Redis-only endpoints (`POST /connections/view`, `POST /api/v1/groups/view`) for actions with no existing DB-backed write to piggyback on, plus inline signal-writing added to existing endpoints (follow, message-request, join) for actions that do have one. This matches the resolved principle: modules with an existing validated interaction write (Posts, News) derive signals inline and should **not** be migrated onto a generic endpoint; modules without one (Connections/Groups view actions) get a dedicated endpoint. Home Feed's `/feed/engagement` remains a distinct, separate contract (global-session-direct-write with a reduced-weight discount) — not the same shape as these.
- **Correction found 2026-07-14 while wiring News:** the doc previously claimed "News has no per-module persistent table of its own" as the reason `get_amplify_weights` is safe for its commodity dimension. That claim is factually wrong — `UserNewsTaste` exists (`news_user_interaction/models.py`), migrated, actively written on every like/save/share/revisit via a fully-built `taste_service.get_taste_weights` that's simply never called (dead code on the read side). The *practical* recommendation still holds, for a narrower reason: `UserNewsTaste` only ever writes `dimension_type="category"`, never `"commodity"`/`"city"`/`"state"` — so it doesn't shadow the dimensions `get_amplify_weights` touches. If News' legacy table is ever extended to also persist commodity/city/state rows, it would need the same Posts-style bypass (`sync_module_to_global`/`merge_weights` called directly) rather than `get_amplify_weights`.
- **New dimension added 2026-07-14: `location`, 2-layer (persistent + module), News-only.** `MergeWeights._influence` gained a `location` branch mirroring `category`/`author` exactly (`g_inf` always 0). **Superseded 2026-08-05:** the shared global-session repository/aggregator was generalized to any dimension type (new `write_dimension_delta`/`read_dimension_weights`/etc. methods, `{dimension_type}:{key}:*` Redis fields), and the single `location` dimension was replaced by two real cross-platform dimensions, `city` and `state`, each with its own 3-layer `_influence` branch (`g_inf` now nonzero, same shape as `commodity`'s). The 2-layer News-only `location` dimension_type no longer exists in the codebase.

---

## 14. Handoff Notes for Counterpart Teams

### For Connections team — Mechanism 1 done, Mechanism 2 excluded (not remaining work)
Write path (view/follow/msg) and read path (page re-rank via `get_amplify_weights`/`commodity_boost`) are shipped. The second WANT-vector ANN pass was explicitly excluded from scope by user decision 2026-08-05 ("can connections part be skipped for now?") — this is not outstanding work, don't schedule it without re-confirming scope.

### For Groups team — Mechanism 1 done, Mechanism 2 spec ready to build
Write path (view/join) and read path (commodity boost before the activity blend) are shipped. A full implementation spec for the second-pass ANN work was written 2026-08-05 — see `recommendation_taste_architecture.md` §11.1–11.5 for the exact trigger condition (per-commodity `conf` vs. `module_commodity_threshold`/`global_commodity_threshold`), vector construction (`build_query_vector` with the discover commodity substituted, needs an id→name resolution step since the encoder takes names but taste data is keyed by id), and query/merge mechanics. One sub-decision flagged there, not yet resolved: what counts as "stronger cross-module evidence" for the global-session trigger.

### For Posts team — Mechanism 1 done (category + commodity + city + state), author deferred, Mechanism 2 spec ready to build
Write path (`write_post_signals` in `amplify.py`) and read path (`sync_module_to_global` + `merge_weights` × 5, called directly — **not** `get_amplify_weights`, see §13.11) are shipped for category, commodity, city, and state. City/state (added 2026-08-05) needed zero schema changes — they come from the author's existing `Business.city`/`Business.state` via an outer join, and use `read_global_taste_weights` as their persistent floor since Posts has no legacy per-module table for them. Author dimension was deliberately deferred this pass — add it by mirroring `record_interaction`'s existing gate (`pos_delta ≥ 2.0 AND author ≠ viewer`). The second ANN pass (Mechanism 2) has a full implementation spec as of 2026-08-05 (`recommendation_taste_architecture.md` §11.1–11.5) — same trigger/vector-substitution mechanics as Groups, using `build_user_feed_vector` with the discover commodity id substituted in. Popular-posts soft scoring (§12 of the companion doc) remains separately parked. `commodity_boost` still doesn't fit Posts' `_rerank()` — that hasn't changed.

### For News team — Mechanism 1 done (commodity, city, state — all 3-layer as of 2026-08-05)
Write path (all 5 endpoints via `write_news_signals`, now taking `location_city`/`location_state` instead of the old `state_tags` list) and read path (`get_amplify_weights` for commodity, city, and state — three separate 3-layer calls) are shipped. City/state are no longer 2-layer/News-local — the global-session infra was generalized so they get the same cross-platform treatment as commodity (see §13.4, §13.11). `EnrichedArticle` gained `location_city`/`location_state`/`latitude`/`longitude`, filled by extending the existing LLM enrichment prompt (no geocoding utility — the LLM names the place directly). `UserNewsTaste` exists as a legacy persistent table but doesn't collide (only ever writes `"category"`). Remaining: the cursor-reshuffle risk noted in §8.2 (accepted, not fixed).

### For Home Feed team — not part of this system, decided 2026-07-14
Your mixer and `session_taste.py` are yours to evolve independently — neither will integrate with `app/modules/taste/`. No `type_mix` global dimension, no engagement-forwarding to global session, no taste-module dependency. If you want smarter type-mix weighting, that's a Home-Feed-internal project, not a taste-system one.

### Shared dependency for all teams
`app/core/redis_client.py` → `get_redis()` — plain callable, no DI required, usable from scheduler jobs too (not just FastAPI endpoints).  
`app/modules/taste/session_taste/__init__.py` → `write_signals`, `SessionSignal`, `ActionType`  
`app/modules/taste/global_session/__init__.py` → `sync_module_to_global`, `merge_weights`, `list_active_global_session_profile_ids`  
`app/modules/taste/amplify.py` → `get_amplify_weights`, `commodity_boost`, `location_boost`, `commodity_id_by_name`, `write_commodity_signals`, `write_post_signals`, `write_news_signals` — the higher-level convenience layer every wired module actually uses; see §13.11 for what fits which module.

All taste module APIs are designed to fail silently — wrap calls in `try/except` to ensure Redis outages never break your endpoint.
