# ── Cluster definitions ──────────────────────────────────────────────────────

CLUSTER_NAMES: dict[int, str] = {
    1:  "Policy & Regulation",
    2:  "Geopolitical & Macro Shocks",
    3:  "Supply-side Disruptions",
    4:  "Financial & Market Mechanics",
    5:  "Structural & Industrial Shifts",
    6:  "Long-term Demand Trends",
    7:  "Market Participation & Deal Flow",
    8:  "Price Volatility & Sentiment",
    9:  "Local Operational Events",
    10: "Indirect / General News",
}

# Per-role importance weight per cluster (scale 1–10, used in feed scoring)
CLUSTER_ROLE_WEIGHTS: dict[int, dict[str, float]] = {
    1:  {"trader": 9.0, "broker": 8.5,  "exporter": 9.8},
    2:  {"trader": 7.5, "broker": 7.0,  "exporter": 9.5},
    3:  {"trader": 9.5, "broker": 8.0,  "exporter": 8.5},
    4:  {"trader": 8.0, "broker": 9.5,  "exporter": 8.0},
    5:  {"trader": 6.0, "broker": 7.5,  "exporter": 8.0},
    6:  {"trader": 5.5, "broker": 6.5,  "exporter": 8.5},
    7:  {"trader": 9.0, "broker": 9.8,  "exporter": 7.0},
    8:  {"trader": 9.5, "broker": 8.5,  "exporter": 7.5},
    9:  {"trader": 8.5, "broker": 7.0,  "exporter": 5.5},
    10: {"trader": 3.0, "broker": 3.0,  "exporter": 3.0},
}

# Cold-start taste weights seeded on first feed request (cluster_id → taste_weight)
COLD_START_DEFAULTS: dict[str, dict[int, float]] = {
    "trader":   {1: 0.6, 3: 0.5, 7: 0.7, 8: 0.9, 9: 0.6},
    "broker":   {1: 0.7, 3: 0.7, 7: 0.9, 8: 0.8, 9: 0.7},
    "exporter": {1: 0.9, 2: 0.9, 4: 0.7, 6: 0.6},
}

# ── Engagement action weights (used in hourly taste update) ──────────────────

ACTION_WEIGHTS: dict[str, int] = {
    "share_in":  8,
    "comment":   5,
    "share_out": 5,
    "save":      4,
    "dwell":     3,   # counted only when dwell_time_s > DWELL_THRESHOLD_S
    "like":      2,
    "click":     1,
    "skip":     -1,
}

DWELL_THRESHOLD_S = 12

# ── Recency multipliers: list of (max_age_hours, multiplier) ─────────────────

RECENCY_TIERS: list[tuple[float, float]] = [
    (2,  1.5),
    (6,  1.3),
    (12, 1.1),
    (24, 1.0),
    (48, 0.7),
    (72, 0.4),
]

RECENCY_CUTOFF_H = 72  # articles older than this are excluded entirely

# ── Scope match matrix [article_scope][user_scope] ───────────────────────────

SCOPE_MATCH: dict[str, dict[str, float]] = {
    "local":    {"local": 1.5, "state": 1.2, "national": 1.0, "global": 0.8},
    "state":    {"local": 1.2, "state": 1.5, "national": 1.1, "global": 0.9},
    "national": {"local": 1.0, "state": 1.1, "national": 1.5, "global": 1.1},
    "global":   {"local": 0.8, "state": 0.9, "national": 1.1, "global": 1.5},
}

# ── Breaking news bypass ──────────────────────────────────────────────────────

BREAKING_CLUSTERS = {1, 2}
BREAKING_SEVERITY_THRESHOLD = 8.0

# ── Feed section sizes ────────────────────────────────────────────────────────

FEED_BREAKING_COUNT      = 3
FEED_FOR_YOU_COUNT       = 12
FEED_TRENDING_COUNT      = 5
FEED_WORTH_KNOWING_COUNT = 5
FEED_GOVERNMENT_COUNT    = 3

# ── Background task settings ──────────────────────────────────────────────────

TRENDING_LOOKBACK_H        = 12
TRENDING_MIN_UNIQUE_USERS  = 5
TRENDING_MIN_SEVERITY      = 4.0

TASTE_LOOKBACK_H           = 72

ARCHIVE_AFTER_DAYS         = 30

PUSH_BREAKING_LOOKBACK_H   = 6
