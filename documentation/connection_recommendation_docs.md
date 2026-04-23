# Recommendation System — Developer Guide

A concise reference for anyone working on the vector-based matching engine.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Vector Architecture](#2-vector-architecture)
3. [Encoding Details](#3-encoding-details)
4. [IS vs WANT Vectors](#4-is-vs-want-vectors)
5. [Boost Weights](#5-boost-weights)
6. [Database Layer](#6-database-layer)
7. [API Endpoints](#7-api-endpoints)
8. [Migration Script](#8-migration-script)
9. [Extending the System](#9-extending-the-system)
10. [Tuning Guide](#10-tuning-guide)

---

## 1. System Overview

Users are matched by encoding their profile into a fixed-size floating-point vector and running a cosine similarity search against all stored vectors using the **pgvector HNSW index** on Supabase (Postgres).

```
User profile  ──encode──►  vector(11)  ──stored in──►  "Users".embedding
                                                              │
Search request ──encode──►  query vector  ──ANN search──────►│
                                                              ▼
                                                     ranked matches
```

Every user has **two logical vectors**:

| Name | Purpose | Stored? |
|---|---|---|
| **IS vector** (candidate) | What the user *is* — their profile | ✅ Yes, in `embedding` column |
| **WANT vector** (query) | What the user *wants* — built at query time | ❌ Never stored |

---

## 2. Vector Architecture

The embedding is `vector(11)` — 11 floats in a fixed layout. **Never reorder or remove dimensions** — doing so invalidates every stored embedding.

```
Index  Dims  Component     Notes
─────  ────  ───────────   ──────────────────────────────────────
0–2      3   Commodity     One-hot, boosted by COMMODITY_BOOST
3–5      3   Role          Soft scores, boosted by ROLE_BOOST
6–8      3   Geo           3D Cartesian (unit sphere), boosted by GEO_BOOST
9–10     2   Quantity      log1p-normalised, boosted by QTY_BOOST
─────  ────
Total   11
```

To verify the dimension count at runtime:

```python
from app.encoding.vector import vector_dim   # returns 11
from app.encoding.vector import vector_layout  # returns a labelled breakdown
```

---

## 3. Encoding Details

### 3.1 Commodity (`dims 0–2`)

One-hot encoding against `ALL_COMMODITIES` in `app/config.py`.

```python
# Example: user trades cotton and rice
encode_commodity(["cotton", "rice"])
# → [0.9, 0.9, 0.0]   (COMMODITY_BOOST = 0.9 applied)
```

- Unknown commodities are **silently ignored**.
- To add a commodity, append it to `ALL_COMMODITIES` — **never insert in the middle**.

### 3.2 Role (`dims 3–5`)

Soft-score encoding. Two variants exist:

| Variant | Function | Used in |
|---|---|---|
| IS (`ROLE_OFFERS`) | What this role *provides* | Candidate / stored vector |
| WANT (`ROLE_AFFINITY`) | What this role *looks for* | Query / search vector |

```python
# IS example: a trader
encode_role_candidate("trader")   # → [0.0, 0.0, 1.5]  (broker, exporter, trader)

# WANT example: a trader looking for partners
encode_role_searcher("trader")    # → [0.825, 0.45, 0.30]
```

Affinity and offers tables live in `app/config.py` under `ROLE_AFFINITY` and `ROLE_OFFERS`.

### 3.3 Geo (`dims 6–8`)

Lat/lon is projected onto a **3D unit sphere** (Cartesian coordinates). Cosine similarity on unit-sphere vectors is equivalent to great-circle proximity.

```python
encode_geo(lat, lon)
# → [cos(lat)cos(lon),  cos(lat)sin(lon),  sin(lat)]
# multiplied by GEO_BOOST (3.0) during assembly
```

`GEO_BOOST = 3.0` is the strongest signal by design — location is the primary matching factor.

### 3.4 Quantity (`dims 9–10`)

**Why log-normalise?** Raw values like `50 000 MT` have a vector magnitude ~50 000. The geo component has magnitude ~3.0. Raw quantity would completely dominate cosine similarity, overriding every other boost.

Log normalisation compresses the range and keeps quantity in the same ballpark as the other components:

```python
log_ref = log1p(QTY_REF_MAX)          # log1p(1_000_000) ≈ 13.8
encoded = log1p([qty_min, qty_max]) / log_ref * QTY_BOOST
```

Approximate output values:

| Quantity (MT) | Encoded value (`QTY_BOOST=1.0`) |
|---|---|
| 0 | 0.00 |
| 100 | 0.33 |
| 500 | 0.45 |
| 5 000 | 0.61 |
| 50 000 | 0.78 |
| 1 000 000 | 1.00 |

Small traders (`[100, 500]`) and large traders (`[5 000, 50 000]`) now point in meaningfully different directions — cosine similarity will distinguish them.

---

## 4. IS vs WANT Vectors

This is the core design decision. Users stored in the DB have an IS vector (what they offer). When searching, a WANT vector is built from the same user (what they're looking for).

```
build_candidate_vector(...)   →  IS vector   →  stored in "Users".embedding
build_query_vector(...)       →  WANT vector →  used as ANN query, never stored
```

The role encoding differs between them (`ROLE_OFFERS` vs `ROLE_AFFINITY`). Commodity, geo, and quantity use the same encoding in both.

```python
# Both functions share the same signature:
build_candidate_vector(commodity_list, role, lat, lon, qty_min, qty_max)
build_query_vector(commodity_list, role, lat, lon, qty_min, qty_max)
```

---

## 5. Boost Weights

All weights live in `app/config.py`. Changing any of them **invalidates all stored embeddings** — run `python migrate_pgvec.py --reset` afterwards.

| Constant | Value | Effect |
|---|---|---|
| `GEO_BOOST` | 3.0 | Strongest signal — prioritises nearby users |
| `ROLE_BOOST` | 1.5 | Mid-weight — role compatibility |
| `COMMODITY_BOOST` | 0.9 | Slightly subdued — commodity overlap |
| `QTY_BOOST` | 1.0 | Tune to increase/decrease quantity scale importance |
| `QTY_REF_MAX` | 1 000 000 | Reference ceiling for log normalisation (MT) |

**Tuning rule of thumb:** The effective influence of a component is roughly `boost × average_component_magnitude`. Geo wins at 3.0 × 1.0 (unit sphere). To make quantity more influential, raise `QTY_BOOST` toward 2.0–3.0.

---

## 6. Database Layer

### Schema

```sql
CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE "Users"
    ADD COLUMN IF NOT EXISTS embedding vector(11);

CREATE INDEX IF NOT EXISTS users_embedding_hnsw_idx
    ON "Users" USING hnsw (embedding vector_cosine_ops);
```

The migration script (`migrate_pgvec.py`) runs these automatically — no manual SQL needed.

### Key files

| File | Responsibility |
|---|---|
| `app/db/postgres.py` | SQLAlchemy async engine + session factory |
| `app/db/pgvector.py` | `fetch_user`, `vector_search`, `update_embedding`, `list_to_pgvec` |

### `vector_search` query

```sql
SELECT user_id, role, commodity, city, state,
       min_quantity_mt, max_quantity_mt,
       1 - (embedding <=> CAST(:vec AS vector)) AS similarity
FROM "Users"
WHERE user_id != :exclude_id
  AND embedding IS NOT NULL
ORDER BY embedding <=> CAST(:vec AS vector)
LIMIT :k
```

`<=>` is pgvector's cosine distance operator. `1 - distance = similarity`. Results are ordered best-first.

---

## 7. API Endpoints

All endpoints are under the `APIRouter` with prefix `/recommendations`.

### `GET /recommendations/{user_id}`

Fetch top 20 matches for an existing user.

1. Loads the user's full profile from Postgres.
2. Builds their WANT vector.
3. Runs ANN cosine search, excluding the user themselves.

**Response:**
```json
{
  "user_id": 42,
  "role": "trader",
  "commodity": "rice; cotton",
  "qty_range": "100–500mt",
  "total": 20,
  "results": [
    {
      "user_id": 7,
      "role": "exporter",
      "commodity": "rice",
      "city": "Mumbai",
      "state": "Maharashtra",
      "qty_range": "200–800mt",
      "similarity": 0.9312
    }
  ]
}
```

---

### `GET /recommendations/{user_id}/refresh`

Recomputes and **persists** the user's IS vector, then returns fresh recommendations. Use this after:
- Encoding logic changes (`vector.py`)
- Boost weight changes (`config.py`)
- A user's profile is updated in the DB

---

### `POST /recommendations/search`

Ad-hoc search without needing an existing `user_id`. Useful for previewing matches before registration.

**Request body:**
```json
{
  "commodity": ["rice", "cotton"],
  "role": "trader",
  "latitude_raw": 19.076,
  "longitude_raw": 72.877,
  "qty_min_mt": 100,
  "qty_max_mt": 500
}
```

**Response:** same `results` format as above (no `user_id` in the outer wrapper).

---

## 8. Migration Script

`migrate_pgvec.py` is the single tool for setting up and backfilling the embedding column.

```bash
# First time setup, or backfill only users missing embeddings:
python migrate_pgvec.py

# After changing encoding logic or boost weights — wipe and rebuild everything:
python migrate_pgvec.py --reset
```

What it does in order:
1. Connects to Supabase via `DATABASE_URL` from `.env`
2. Runs the schema setup (`CREATE EXTENSION`, `ADD COLUMN`, `CREATE INDEX`) — all idempotent
3. If `--reset`: sets all `embedding` columns to `NULL`
4. Fetches all users where `embedding IS NULL`
5. Builds the IS vector for each user via `build_candidate_vector`
6. Batch-writes vectors in groups of 100 using `executemany`

---

## 9. Extending the System

### Adding a new commodity

1. Append to `ALL_COMMODITIES` in `app/config.py` — **only at the end, never in the middle**.
2. The vector dimension increases by 1 — update the Supabase column: `ALTER TABLE "Users" ALTER COLUMN embedding TYPE vector(N)`.
3. Re-run `python migrate_pgvec.py --reset` to rebuild all embeddings.

### Adding a new role

1. Add the role to `ROLE_AFFINITY` and `ROLE_OFFERS` in `app/config.py`.
2. If you're adding a new *dimension* (e.g. a fourth role type), `ROLE_DIMS` grows, the vector dimension increases, and you need to follow the same column + reset steps as above.
3. If the new role fits within existing dimensions (just new affinity/offers weights), no dimension change is needed — just re-run `--reset`.

### Changing boost weights

Edit the constants in `app/config.py`, then run `python migrate_pgvec.py --reset`. No schema changes needed.

---

## 10. Tuning Guide

| Goal | What to change |
|---|---|
| Prioritise geographic proximity more | Increase `GEO_BOOST` |
| Make role compatibility matter more | Increase `ROLE_BOOST` |
| Make quantity scale-matching matter more | Increase `QTY_BOOST` toward 2.0–3.0 |
| Adjust how role types seek each other | Edit `ROLE_AFFINITY` in `config.py` |
| Change what each role signals it offers | Edit `ROLE_OFFERS` in `config.py` |

**After any config change:** `python migrate_pgvec.py --reset`

**Testing a change without a full reset:** call `GET /recommendations/{user_id}/refresh` on a handful of representative users and compare similarity scores before and after.
