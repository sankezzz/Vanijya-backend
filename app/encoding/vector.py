import numpy as np
from app.config import (
    ALL_COMMODITIES, COMMODITY_BOOST,
    ROLE_DIMS, ROLE_AFFINITY, ROLE_OFFERS, ROLE_BOOST,
    GEO_BOOST
)


# ─── Commodity ────────────────────────────────────────────────────────────────

def encode_commodity(commodity_list: list[str]) -> np.ndarray:
    """
    One-hot encodes a list of commodities against ALL_COMMODITIES.
    Unknown commodities are silently ignored.
    Returns a boosted vector of shape (len(ALL_COMMODITIES),).
    """
    vec = np.zeros(len(ALL_COMMODITIES))
    for c in commodity_list:
        if c in ALL_COMMODITIES:
            vec[ALL_COMMODITIES.index(c)] = 1.0
    return vec * COMMODITY_BOOST


# ─── Role ─────────────────────────────────────────────────────────────────────

def encode_role_candidate(role: str) -> np.ndarray:
    """
    IS encoding — what this user offers.
    Stored in ChromaDB. Used as the indexed vector.
    Returns a boosted vector of shape (len(ROLE_DIMS),).
    """
    offers = ROLE_OFFERS[role]
    vec = np.array([offers[d] for d in ROLE_DIMS])
    return vec * ROLE_BOOST


def encode_role_searcher(role: str) -> np.ndarray:
    """
    WANT encoding — what this user is looking for.
    Never stored. Only used at query time.
    Returns a boosted vector of shape (len(ROLE_DIMS),).
    """
    affinity = ROLE_AFFINITY[role]
    vec = np.array([affinity[d] for d in ROLE_DIMS])
    return vec * ROLE_BOOST


# ─── Geo ──────────────────────────────────────────────────────────────────────

def encode_geo(lat: float, lon: float) -> np.ndarray:
    """
    Projects lat/lon to a 3D unit sphere (Cartesian coordinates).
    Pure function — no boost applied here.
    Returns a unit vector of shape (3,).
    """
    lat_rad = np.radians(lat)
    lon_rad = np.radians(lon)
    x = np.cos(lat_rad) * np.cos(lon_rad)
    y = np.cos(lat_rad) * np.sin(lon_rad)
    z = np.sin(lat_rad)
    return np.array([x, y, z])


def encode_quantity(qty_min: int, qty_max: int) -> np.ndarray:
    """
    Encodes quantity range as a 2D vector: [qty_min, qty_max].
    This is a simple encoding and may not capture all nuances of quantity preferences.
    Returns a vector of shape (2,).
    """

    return  np.array([qty_min, qty_max])

# ─── Final Vector Assembly ────────────────────────────────────────────────────

def build_candidate_vector(
    commodity_list: list[str],
    role: str,
    lat: float,
    lon: float,
    qty_min: int,
    qty_max: int,
) -> list[float]:
    """
    Builds the IS vector for a user.
    This is what gets stored in ChromaDB.

    Layout: [commodity_dims | role_is_dims | geo_dims]
    """
    vec = np.hstack([
        encode_commodity(commodity_list),
        encode_role_candidate(role),
        encode_geo(lat, lon) * GEO_BOOST,
        encode_quantity(qty_min, qty_max)
    ])
    return vec.tolist()


def build_query_vector(
    commodity_list: list[str],
    role: str,
    lat: float,
    lon: float
) -> list[float]:
    """
    Builds the WANT vector for a user.
    This is what gets passed to ChromaDB at query time.
    Never stored.

    Layout: [commodity_dims | role_want_dims | geo_dims]
    """
    vec = np.hstack([
        encode_commodity(commodity_list),
        encode_role_searcher(role),
        encode_geo(lat, lon) * GEO_BOOST,
        encode_quantity(0, 0)  # Placeholder for quantity in query vector
    ])
    return vec.tolist()


# ─── Dimension Info (useful for debugging) ────────────────────────────────────

def vector_dim() -> int:
    return len(ALL_COMMODITIES) + len(ROLE_DIMS) + 3


def vector_layout() -> dict:
    n_comm = len(ALL_COMMODITIES)
    n_role = len(ROLE_DIMS)
    return {
        "total_dims":  vector_dim(),
        "commodity":   {"range": f"[0:{n_comm}]",              "dims": [f"has_{c}" for c in ALL_COMMODITIES]},
        "role":        {"range": f"[{n_comm}:{n_comm+n_role}]","dims": ROLE_DIMS},
        "geo":         {"range": f"[{n_comm+n_role}:{vector_dim()}]", "dims": ["x", "y", "z"]},
    }