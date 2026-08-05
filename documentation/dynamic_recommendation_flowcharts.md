# Dynamic Recommendation System — Flowcharts

Companion visual reference to `dynamic_recommendation_architecture.md` and
`recommendation_taste_architecture.md`. Renders as diagrams in GitHub/VSCode
markdown preview (Mermaid). Current as of 2026-07-14.

---

## 1. Overall three-layer data flow

```mermaid
flowchart TB
    A[User interacts in a module\nlike / save / dwell / follow / join / view] --> B[DB write\npost_interaction_events, etc.]
    B --> C["write_signals(rc, profile_id, module, signals)"]
    C --> D["Layer 1 — Module Session\nsession:{module}:{profile_id}\n2h inactivity TTL"]

    D -- "on next amplify read,\ncommodity dims only" --> E["sync_module_to_global()\ndelta = current - synced snapshot"]
    E --> F["Layer 2 — Global Session\nsession:global:{profile_id}\n1 day TTL"]

    D -- "read_dimension_scores" --> G["merge_weights()\nblend persistent + global + module"]
    F -- "read_commodity_weights /\nread_commodity_score" --> G
    H["Layer 3 — Persistent\nuser_post_taste (Posts)\nuser_global_taste (cross-platform)"] -- "persistent floor" --> G
    G --> I[Feed / recommendation scoring\n_rerank, commodity_boost, etc.]

    F -- "nightly 3:15am IST\nthree-gate filter" --> J["PromoteFromGlobalSession\npersistent += 0.15 x global_delta"]
    J --> H
    J -- "only if candidates promoted" --> K["clear_global_session()"]
    K -.-> F
```

---

## 2. Write path — generic `write_signals` internals

```mermaid
flowchart TB
    A["SessionSignal(dimension_type, dimension_key, action, occurred_at_unix)"] --> B["SIGNAL_WEIGHTS[action] lookup\n(pos_delta, neg_delta, conf_delta)"]
    B --> C{Any delta nonzero?}
    C -- no --> Z[Skip this signal]
    C -- yes --> D["Redis pipeline (one round trip per batch):"]
    D --> D1["HINCRBYFLOAT {pfx}:{key}:pos"]
    D --> D2["HINCRBYFLOAT {pfx}:{key}:neg"]
    D --> D3["HINCRBYFLOAT {pfx}:{key}:conf"]
    D --> D4["HINCRBY {pfx}:{key}:cnt +1"]
    D --> D5["HSET {pfx}:{key}:ts = now"]
    D --> E["HINCRBY _total_events\nHSETNX _session_start\nHSET _last_event_at\nEXPIRE 7200 (reset 2h TTL)"]
    E --> F[pipe.execute — atomic]
```

---

## 3. Posts write path (the concrete, currently-shipped example)

```mermaid
flowchart TB
    A["POST /posts/interactions/batch\nprocess_interaction_batch(db, profile_id, events, rc)"] --> B["Bulk fetch category_id, commodity_id\nfor all referenced post_ids"]
    B --> C[Validate / drop stale or unknown posts\nCap dwell value_ms]
    C --> D["Bulk insert PostInteractionEvent rows\nUpsert seen_posts for dwell >= 3000ms"]
    D --> E[db.commit]
    E --> F{For each accepted event}
    F --> G["_classify_action(event_type, value_ms)\nreuses classify_dwell bucket boundaries"]
    G -- "None (unrecognized type)" --> F
    G -- ActionType --> H["write_post_signals(rc, profile_id,\ncategory_name, commodity_id, action)"]
    H --> I["write_signals(rc, profile_id, 'post', signals)\n-- category always, commodity if present\n-- author NOT written (deferred)"]
    I --> F
    F -- done --> J[Return accepted/dropped counts]

    style H fill:#333,color:#fff
```

---

## 4. Module → Global sync — the delta/snapshot mechanism (detail)

```mermaid
flowchart TB
    A["sync_module_to_global(rc, profile_id, module)"] --> B["get_commodity_delta_and_snapshot()\nHGETALL session:{module}:{profile_id}"]
    B --> C{For each commodity key present}
    C --> D["pos_d = pos - synced\nneg_d = neg - neg_synced\nconf_d = conf - conf_synced"]
    D --> E{"Any delta > 0.01?"}
    E -- no --> F[Key excluded from delta dict\n-- cheap no-op, e.g. repeated pagination reads]
    E -- yes --> G["delta[key] = {pos: pos_d, neg: neg_d, conf: conf_d}\nsnapshot[key] = {pos, neg, conf} (current values)"]
    F --> H{delta dict empty?}
    G --> H
    H -- yes --> I[Return — nothing to sync]
    H -- no --> J["write_commodity_delta(profile_id, delta)\nHINCRBYFLOAT into session:global:{pid}\nfor pos / neg / conf per key"]
    J --> K{Write succeeded?}
    K -- yes --> L["mark_synced(profile_id, module, snapshot)\nHSET the three *_synced fields to current values"]
    K -- no / exception --> M["Snapshot NOT updated\nsame delta will be recomputed and retried next call"]
```

---

## 5. Read path — the blend formula (`merge_weights`)

```mermaid
flowchart TB
    A["merge_weights(rc, profile_id, module, dimension_type, persistent_weights)"] --> B["module_scores = read_dimension_scores(...)\ndecay-adjusted net score per key"]
    B --> C{dimension_type == 'commodity'?}
    C -- yes --> D["global_scores = read_commodity_weights(...)\n(decay-adjusted, from session:global)"]
    C -- no (category/author) --> E["global_scores = {} — 2-layer only"]
    D --> F[all_keys = union of persistent/module/global keys]
    E --> F
    F --> G{For each key}
    G --> H["_influence(profile_id, module, dim_type, key, persistent_val)"]
    H --> H1{dimension_type?}
    H1 -- category --> I1["m_inf = 0.31 x min(m_conf/10.0, 1)\ng_inf = 0"]
    H1 -- commodity --> I2["m_thresh = 8 x (1+persistent/50)\ng_thresh = 12 x (1+persistent/100)\nm_inf = 0.31 x min(m_conf/m_thresh,1)\ng_inf = 0.15 x min(g_conf/g_thresh,1)"]
    H1 -- author --> I3["m_inf = (0.31x0.35) x min(m_conf/6.0,1)\ng_inf = 0"]
    I1 --> J["p_inf = max(1 - m_inf - g_inf, 0.54)"]
    I2 --> J
    I3 --> J
    J --> K["merged[key] = p_inf x persistent[key]\n+ g_inf x global[key] + m_inf x module[key]"]
    K --> G
    G -- done --> L[Return merged dict str to float]
```

---

## 6. Nightly promotion (3:15am IST)

```mermaid
flowchart TB
    A["Scheduler cron 3:15am IST\ntaste.global_promotion"] --> B["scan_active_profile_ids()\nSCAN session:global:* (non-blocking cursor)"]
    B --> C{For each profile_id}
    C --> D["promote_from_global_session(db, rc, profile_id)"]
    D --> E["read_all_commodity_data(profile_id)\nraw pos/neg/conf/cnt per commodity key"]
    E --> F{Raw data empty?}
    F -- yes --> G[Return no candidates] --> C
    F -- no --> H{For each commodity key}
    H --> I["Gate 1 — Confidence\nconf >= 0.70 x global_threshold(persistent_score)"]
    I -- fail --> H
    I -- pass --> J["Gate 2 — Quality\npos - neg*0.6 >= 20"]
    J -- fail --> H
    J -- pass --> K["Gate 3 — Events\ncnt >= 10 (sync operations, not raw signals)"]
    K -- fail --> H
    K -- pass --> L["candidate: delta = 0.15 x (pos - neg*0.6)"]
    L --> H
    H -- done --> M{Any candidates qualified?}
    M -- no --> N["Do nothing further for this profile\n-- Redis key NOT cleared, data keeps accumulating"]
    M -- yes --> O["bulk_apply_promotion()\nPostgres upsert into user_global_taste"]
    O --> P[db.commit]
    P --> Q["clear_global_session(rc, profile_id)\n-- ONLY after commit confirmed"]
    N --> C
    Q --> C
```

---

## 7. Per-module wiring status (at a glance)

```mermaid
flowchart LR
    subgraph Posts["Posts ✅ Mechanism 1 (category+commodity, author deferred)"]
        P1[write_post_signals] --> P2[sync_module_to_global once]
        P2 --> P3["merge_weights x3\n(direct, NOT get_amplify_weights)"]
    end
    subgraph Connections["Connections ✅ Mechanism 1"]
        C1[write_commodity_signals] --> C2[get_amplify_weights]
        C2 --> C3[commodity_boost re-ranks fetched page]
    end
    subgraph Groups["Groups ✅ Mechanism 1"]
        G1[write_commodity_signals] --> G2[get_amplify_weights]
        G2 --> G3[commodity_boost before activity blend]
    end
    subgraph News["News 🔲 not wired"]
        N1[Planned: write_signals] -.-> N2[Planned: get_amplify_weights safe here]
    end
    subgraph HomeFeed["Home Feed 🔲 parked"]
        H1[Separate type-mix system,\nnot the taste module at all]
    end
```

**Why Posts looks different from Connections/Groups:** `get_amplify_weights` unconditionally sources "persistent" from `user_global_taste` (sparse, cross-platform) — correct for Connections/Groups since they have no legacy per-module table of their own, wrong for Posts which already has a mature `user_post_taste`. News has no legacy table either, so once built it can safely use `get_amplify_weights` like Connections/Groups do.
