# app/routes/recommendations.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import time
from app.db.postgres import AsyncSessionLocal
from app.db.chromadb import get_chroma_collection
from app.encoding.vector import build_query_vector, build_candidate_vector
from sqlalchemy import text

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

TOP_K = 20

# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _fetch_user_from_postgres(user_id: int) -> dict:
    """Fetch a user row from Postgres by user_id."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text('SELECT * FROM "Users" WHERE user_id = :uid'),
            {"uid": user_id}
        )
        row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    return dict(row)


async def _fetch_user_from_chromadb(user_id: int) -> dict:
    """Fetch user data from ChromaDB metadata — no Postgres call needed."""
    collection = get_chroma_collection()
    result = collection.get(
        ids=[str(user_id)],
        include=["metadatas"]
    )
    if not result["ids"]:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    return result["metadatas"][0]


def _run_search(query_vec: list[float], exclude_user_id: int, top_k: int) -> list[dict]:
    """
    Queries ChromaDB via HNSW, excludes the searcher,
    converts distance → similarity, returns list of result dicts.
    """
    collection = get_chroma_collection()

    # Fetch top_k + 1 in case searcher appears in results
    results = collection.query(
        query_embeddings=[query_vec],
        n_results=top_k + 1,
        include=["metadatas", "distances"],
    )

    matches = []
    for meta, dist in zip(results["metadatas"][0], results["distances"][0]):
        if meta["user_id"] == exclude_user_id:
            continue
        matches.append({
            "user_id":    meta["user_id"],
            "role":       meta["role"],
            "commodity":  meta["commodity"],
            "city":       meta["city"],
            "state":      meta["state"],
            "qty_range":  f"{meta['qty_min']}–{meta['qty_max']}mt",
            "similarity": round(1 - dist, 4),   # distance → similarity
        })

    return matches[:top_k]


# ─── GET /recommendations/{user_id} ──────────────────────────────────────────

@router.get("/{user_id}")
async def get_recommendations(user_id: int):
    """
    Fetch top 20 matches for a user.
    Pulls user from Postgres, builds WANT vector, queries ChromaDB via HNSW.
    """
    user = await _fetch_user_from_chromadb(user_id)
    print(f"User {user_id} fetched from ChromaDB metadata.")

    commodity_list = [c.strip() for c in user["commodity"].split(";")]
    query_vec = build_query_vector(
        commodity_list=commodity_list,
        role=user["role"],
        lat=float(user["lat"]),
        lon=float(user["lon"]),
    )

    matches = _run_search(query_vec, exclude_user_id=user_id, top_k=TOP_K)

    return {
        "user_id":  user_id,
        "role":     user["role"],
        "commodity":user["commodity"],
        "total":    len(matches),
        "results":  matches,
    }

'''This is the function to calculate which entitiy is taking more time in the recommendation process. We can use this to optimize the code in future.'''

# @router.get("/{user_id}")
# async def get_recommendations(user_id: int):
#     t0 = time.perf_counter()

#     user = await _fetch_user(user_id)
#     t1 = time.perf_counter()
#     print(f"Postgres fetch     : {t1-t0:.3f}s")

#     commodity_list = [c.strip() for c in user["commodity"].split(";")]
#     query_vec = build_query_vector(
#         commodity_list=commodity_list,
#         role=user["role"],
#         lat=float(user["latitude_raw"]),
#         lon=float(user["longitude_raw"]),
#     )
#     t2 = time.perf_counter()
#     print(f"Vector build       : {t2-t1:.3f}s")

#     matches = _run_search(query_vec, exclude_user_id=user_id, top_k=TOP_K)
#     t3 = time.perf_counter()
#     print(f"ChromaDB search    : {t3-t2:.3f}s")

#     print(f"TOTAL              : {t3-t0:.3f}s")

#     return {
#         "user_id":   user_id,
#         "role":      user["role"],
#         "commodity": user["commodity"],
#         "total":     len(matches),
#         "results":   matches,
#     }

# ─── POST /recommendations/search ────────────────────────────────────────────

class SearchPayload(BaseModel):
    commodity:    list[str]   # e.g. ["rice", "cotton"]
    role:         str
    latitude_raw: float
    longitude_raw:float

@router.post("/search")
async def custom_search(payload: SearchPayload):
    """
    Search with a custom payload — no user_id needed.
    Useful for searching before registration or testing.
    """
    query_vec = build_query_vector(
        commodity_list=payload.commodity,
        role=payload.role,
        lat=payload.latitude_raw,
        lon=payload.longitude_raw,
    )

    matches = _run_search(query_vec, exclude_user_id=-1, top_k=TOP_K)

    return {
        "total":   len(matches),
        "results": matches,
    }


# ─── GET /recommendations/{user_id}/refresh ───────────────────────────────────

@router.get("/{user_id}/refresh")
async def refresh_recommendations(user_id: int):
    """
    Recomputes and re-upserts the user's IS vector into ChromaDB,
    then returns fresh recommendations.
    Useful when encoding logic or boost weights change.
    """
    user = await _fetch_user_from_chromadb(user_id)

    commodity_list = [c.strip() for c in user["commodity"].split(";")]

    # Rebuild IS vector and re-upsert
    candidate_vec = build_candidate_vector(
        commodity_list=commodity_list,
        role=user["role"],
        lat=float(user["lat"]),
        lon=float(user["lon"]),
    )
    collection = get_chroma_collection()
    collection.upsert(
        ids=[str(user_id)],
        embeddings=[candidate_vec],
        metadatas=[{
            "user_id":       user_id,
            "role":          user["role"],
            "commodity":     user["commodity"],
            "city":          user["city"],
            "state":         user["state"],
            "latitude_raw":  float(user["lat"]),
            "longitude_raw": float(user["lon"]),
            "qty_min":       int(user["qty_min"]),
            "qty_max":       int(user["qty_max"]),
        }],
    )

    # Now run fresh search
    query_vec = build_query_vector(
        commodity_list=commodity_list,
        role=user["role"],
        lat=float(user["lat"]),
        lon=float(user["lon"]),
    )
    matches = _run_search(query_vec, exclude_user_id=user_id, top_k=TOP_K)

    return {
        "user_id":   user_id,
        "refreshed": True,
        "total":     len(matches),
        "results":   matches,
    }