import uuid
import math
import random
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone

random.seed(42)
np.random.seed(42)

# ─── Config ───────────────────────────────────────────────────────────────────
CUTOFF      = datetime(2026, 4, 3, 10, 0, 0, tzinfo=timezone.utc)  # Apr 3 10am
HOT_WINDOW  = CUTOFF - timedelta(hours=72)   # last 72 hrs  → 2000 posts
WARM_WINDOW = CUTOFF - timedelta(days=30)    # 30 days ago  → 3000 posts
# remaining 5000 spread across full 30-day window

TOTAL       = 10_000
HOT_COUNT   = 2_000
WARM_COUNT  = 3_000
COLD_COUNT  = TOTAL - HOT_COUNT - WARM_COUNT  # 5000

# ─── Lookup tables ────────────────────────────────────────────────────────────
COMMODITIES = ["rice", "wheat", "cotton", "sugar", "soybean",
               "maize", "spices", "pulses", "groundnut", "mustard"]

CATEGORIES  = ["market_update", "deal_req", "knowledge", "discussion"]

ROLES       = ["trader", "exporter", "broker"]

# category distribution weights (deal_req most common, knowledge least)
CAT_WEIGHTS = [0.30, 0.40, 0.15, 0.15]

# realistic Indian states + cities with lat/lon
LOCATIONS = [
    ("Maharashtra",  "Mumbai",       19.0760,  72.8777),
    ("Maharashtra",  "Pune",         18.5204,  73.8567),
    ("Maharashtra",  "Nagpur",       21.1458,  79.0882),
    ("Punjab",       "Ludhiana",     30.9010,  75.8573),
    ("Punjab",       "Amritsar",     31.6340,  74.8723),
    ("Punjab",       "Chandigarh",   30.7333,  76.7794),
    ("Uttar Pradesh","Lucknow",      26.8467,  80.9462),
    ("Uttar Pradesh","Kanpur",       26.4499,  80.3319),
    ("Uttar Pradesh","Agra",         27.1767,  78.0081),
    ("Gujarat",      "Ahmedabad",    23.0225,  72.5714),
    ("Gujarat",      "Surat",        21.1702,  72.8311),
    ("Gujarat",      "Rajkot",       22.3039,  70.8022),
    ("Rajasthan",    "Jaipur",       26.9124,  75.7873),
    ("Rajasthan",    "Jodhpur",      26.2389,  73.0243),
    ("Madhya Pradesh","Indore",      22.7196,  75.8577),
    ("Madhya Pradesh","Bhopal",      23.2599,  77.4126),
    ("Karnataka",    "Bengaluru",    12.9716,  77.5946),
    ("Karnataka",    "Hubli",        15.3647,  75.1240),
    ("Andhra Pradesh","Hyderabad",   17.3850,  78.4867),
    ("Andhra Pradesh","Visakhapatnam",17.6868, 83.2185),
    ("Tamil Nadu",   "Chennai",      13.0827,  80.2707),
    ("Tamil Nadu",   "Coimbatore",   11.0168,  76.9558),
    ("West Bengal",  "Kolkata",      22.5726,  88.3639),
    ("Haryana",      "Gurugram",     28.4595,  77.0266),
    ("Haryana",      "Hisar",        29.1492,  75.7217),
    ("Odisha",       "Bhubaneswar",  20.2961,  85.8245),
    ("Bihar",        "Patna",        25.5941,  85.1376),
    ("Telangana",    "Warangal",     17.9689,  79.5941),
    ("Kerala",       "Kochi",        9.9312,   76.2673),
    ("Chhattisgarh", "Raipur",       21.2514,  81.6296),
]

# commodity distribution per category — realistic
COMMODITY_BY_CAT = {
    "market_update": ["rice", "wheat", "cotton", "sugar", "soybean", "maize", "mustard"],
    "deal_req":      ["rice", "wheat", "cotton", "sugar", "soybean", "maize",
                      "groundnut", "pulses", "mustard", "spices"],
    "knowledge":     COMMODITIES,
    "discussion":    COMMODITIES,
}

# qty ranges in MT per commodity (realistic trade volumes)
QTY_RANGES = {
    "rice":       (20, 500),
    "wheat":      (50, 1000),
    "cotton":     (10, 200),
    "sugar":      (100, 2000),
    "soybean":    (50, 500),
    "maize":      (30, 800),
    "spices":     (1, 50),
    "pulses":     (20, 400),
    "groundnut":  (10, 300),
    "mustard":    (20, 500),
}

# price per MT per commodity (INR)
PRICE_RANGES = {
    "rice":       (25000, 45000),
    "wheat":      (20000, 30000),
    "cotton":     (55000, 75000),
    "sugar":      (35000, 42000),
    "soybean":    (40000, 55000),
    "maize":      (18000, 25000),
    "spices":     (80000, 500000),
    "pulses":     (60000, 100000),
    "groundnut":  (45000, 65000),
    "mustard":    (50000, 65000),
}

# expires_at per category
EXPIRY_DAYS = {
    "market_update": 2,
    "deal_req":      7,
    "knowledge":     90,
    "discussion":    14,
}

# ─── Geo encoding ─────────────────────────────────────────────────────────────
def geo_to_3d(lat, lon):
    """Convert lat/lon to unit sphere 3D cartesian."""
    lat_r = math.radians(lat)
    lon_r = math.radians(lon)
    return (
        round(math.cos(lat_r) * math.cos(lon_r), 6),
        round(math.cos(lat_r) * math.sin(lon_r), 6),
        round(math.sin(lat_r), 6),
    )

# ─── Qty normalisation (0-1 over 0–5000 MT scale) ────────────────────────────
def norm_qty(val):
    return round(min(val / 5000.0, 1.0), 4)

# ─── Recency score (Reddit-style decay) ───────────────────────────────────────
def recency_score(created_at, category):
    hours_ago = (CUTOFF - created_at).total_seconds() / 3600
    decay = {
        "market_update": 0.8,
        "deal_req":      0.4,
        "knowledge":     0.1,
        "discussion":    0.5,
    }[category]
    return round(1.0 / (hours_ago + 1) ** decay, 6)

# ─── Random timestamp helpers ─────────────────────────────────────────────────
def rand_ts(start, end):
    delta = (end - start).total_seconds()
    return start + timedelta(seconds=random.uniform(0, delta))

# ─── Generate one post ────────────────────────────────────────────────────────
def make_post(created_at):
    post_id  = str(uuid.uuid4())
    category = random.choices(CATEGORIES, weights=CAT_WEIGHTS, k=1)[0]
    commodity_pool = COMMODITY_BY_CAT[category]
    commodity = random.choice(commodity_pool)

    # target roles — one or many
    n_roles  = random.choices([1, 2, 3], weights=[0.55, 0.30, 0.15], k=1)[0]
    t_roles  = sorted(random.sample(ROLES, n_roles))

    loc = random.choice(LOCATIONS)
    state, city, lat, lon = loc
    geo_x, geo_y, geo_z = geo_to_3d(lat, lon)

    # qty and price only for deal_req
    qty_min = qty_max = price = None
    vec_qty_min = vec_qty_max = 0.0
    if category == "deal_req":
        qmin, qmax = QTY_RANGES[commodity]
        qty_min = random.randint(qmin, int(qmin + (qmax - qmin) * 0.4))
        qty_max = random.randint(qty_min, qmax)
        pmin, pmax = PRICE_RANGES[commodity]
        price   = round(random.uniform(pmin, pmax), 2)
        vec_qty_min = norm_qty(qty_min)
        vec_qty_max = norm_qty(qty_max)

    expires_at = created_at + timedelta(days=EXPIRY_DAYS[category])
    is_active  = expires_at > CUTOFF

    rec_score  = recency_score(created_at, category)

    # ── commodity one-hot ──
    com_vec = {f"vec_commodity_{c}": int(c == commodity) for c in COMMODITIES}

    # ── role multi-hot ──
    role_vec = {f"vec_role_{r}": int(r in t_roles) for r in ROLES}

    row = {
        "post_id":          post_id,
        "category":         category,
        "commodity":        commodity,
        "target_roles":     "|".join(t_roles),
        "location_state":   state,
        "location_city":    city,
        "latitude":         lat,
        "longitude":        lon,
        "qty_min_mt":       qty_min,
        "qty_max_mt":       qty_max,
        "price_per_unit_inr": price,
        "created_at":       created_at.isoformat(),
        "expires_at":       expires_at.isoformat(),
        "is_active":        is_active,
        # ── vector dims ──
        **com_vec,
        **role_vec,
        "vec_geo_x":        geo_x,
        "vec_geo_y":        geo_y,
        "vec_geo_z":        geo_z,
        "vec_qty_min_norm": vec_qty_min,
        "vec_qty_max_norm": vec_qty_max,
        "recency_score":    rec_score,
    }
    return row

# ─── Generate all posts ───────────────────────────────────────────────────────
print("Generating posts...")

posts = []

# HOT — last 72 hrs
for _ in range(HOT_COUNT):
    ts = rand_ts(HOT_WINDOW, CUTOFF)
    posts.append(make_post(ts))

# WARM — 72 hrs to 30 days ago
for _ in range(WARM_COUNT):
    ts = rand_ts(WARM_WINDOW, HOT_WINDOW)
    posts.append(make_post(ts))

# COLD — spread across full 30-day window
for _ in range(COLD_COUNT):
    ts = rand_ts(WARM_WINDOW, CUTOFF)
    posts.append(make_post(ts))

# shuffle so hot/warm/cold are mixed
random.shuffle(posts)

df = pd.DataFrame(posts)

# ─── Print stats ──────────────────────────────────────────────────────────────
print(f"\nTotal posts       : {len(df)}")
print(f"Active posts      : {df['is_active'].sum()}")
print(f"\nCategory split:")
print(df['category'].value_counts().to_string())
print(f"\nCommodity split (top 5):")
print(df['commodity'].value_counts().head().to_string())
print(f"\nIs_active by category:")
print(df.groupby('category')['is_active'].mean().round(2).to_string())
print(f"\nHot posts (last 72h) : {(pd.to_datetime(df['created_at']) >= HOT_WINDOW.isoformat()).sum()}")
print(f"Warm posts (3-30d)   : {((pd.to_datetime(df['created_at']) >= WARM_WINDOW.isoformat()) & (pd.to_datetime(df['created_at']) < HOT_WINDOW.isoformat())).sum()}")

out = "/mnt/user-data/outputs/posts_vector_db.csv"
df.to_csv(out, index=False)
print(f"\nSaved → {out}")
print(f"Shape  : {df.shape}")
print(f"\nColumns:\n{list(df.columns)}")
