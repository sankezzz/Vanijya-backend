"""
app/db/migrate.py
Run once: python -m app.db.migrate
"""

import os
import asyncio
import asyncpg
import numpy as np
from dotenv import load_dotenv
from app.weights_config import (
    ALL_COMMODITIES, COMMODITY_BOOST,
    ROLE_DIMS, ROLE_BOOST, ROLE_OFFERS,
    GEO_BOOST
)
from app.encoding.vector import build_candidate_vector
from app.db.chromadb import get_chroma_collection

load_dotenv()

BATCH_SIZE = 100

async def migrate():
    # 1. Connect to Supabase
    print("Connecting to Supabase...")
    conn = await asyncpg.connect(
    os.getenv("DATABASE_URL").replace("postgresql+asyncpg://", "postgresql://"),
    statement_cache_size=0
    )

    # 2. Fetch all users
    print("Fetching users...")
    rows = await conn.fetch("""
        SELECT
            user_id, commodity, role,
            city, state,
            latitude_raw, longitude_raw,
            min_quantity_mt, max_quantity_mt
        FROM "Users"
        ORDER BY user_id
    """)
    await conn.close()
    print(f"Found {len(rows)} users.\n")

    # 3. Connect to ChromaDB
    print("Connecting to ChromaDB...")
    collection = get_chroma_collection()
    print(f"Collection ready. Current count: {collection.count()}\n")

    # 4. Build vectors
    ids, embeddings, metadatas, failed = [], [], [], []

    for row in rows:
        try:
            commodity_list = [c.strip() for c in row["commodity"].split(";")]

            vector = build_candidate_vector(
                commodity_list=commodity_list,
                role=row["role"],
                lat=float(row["latitude_raw"]),
                lon=float(row["longitude_raw"]),
            )

            ids.append(str(row["user_id"]))
            embeddings.append(vector)
            metadatas.append({
                "user_id":   int(row["user_id"]),
                "role":      row["role"],
                "commodity": row["commodity"],
                "city":      row["city"],
                "state":     row["state"],
                "lat":       float(row["latitude_raw"]),
                "lon":       float(row["longitude_raw"]),
                "qty_min":   int(row["min_quantity_mt"]),
                "qty_max":   int(row["max_quantity_mt"]),
            })

        except Exception as e:
            print(f"  ⚠ Skipping user {row['user_id']}: {e}")
            failed.append(row["user_id"])

    # 5. Batch upsert
    print(f"Upserting {len(ids)} vectors in batches of {BATCH_SIZE}...")
    for start in range(0, len(ids), BATCH_SIZE):
        end = start + BATCH_SIZE
        collection.upsert(
            ids=ids[start:end],
            embeddings=embeddings[start:end],
            metadatas=metadatas[start:end],
        )
        print(f"  Upserted {min(end, len(ids))}/{len(ids)}")

    # 6. Verify
    print(f"\n✓ Done.")
    print(f"  Vectors in ChromaDB : {collection.count()}")
    print(f"  Processed           : {len(ids)}")
    print(f"  Failed              : {len(failed)}")
    if failed:
        print(f"  Failed IDs          : {failed}")


if __name__ == "__main__":
    asyncio.run(migrate())