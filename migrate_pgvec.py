"""
migrate_pgvec.py
Sets up the embedding column and backfills all users.

    python migrate_pgvec.py           # backfill only users missing embeddings
    python migrate_pgvec.py --reset   # wipe all embeddings and rebuild from scratch

The script is fully self-contained — it creates the pgvector extension,
adds the embedding column, and builds the HNSW index if they don't exist yet.
"""

import argparse
import asyncio
import asyncpg
import os
from dotenv import load_dotenv
from app.encoding.vector import build_candidate_vector, vector_dim
from app.db.pgvector import list_to_pgvec

load_dotenv()

BATCH_SIZE = 100


async def setup_schema(conn: asyncpg.Connection) -> None:
    """Create the pgvector extension, embedding column, and HNSW index if absent."""
    dim = vector_dim()
    print("Setting up schema...")

    await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    await conn.execute(f"""
        ALTER TABLE "Users"
        ADD COLUMN IF NOT EXISTS embedding vector({dim});
    """)

    await conn.execute("""
        CREATE INDEX IF NOT EXISTS users_embedding_hnsw_idx
        ON "Users" USING hnsw (embedding vector_cosine_ops);
    """)
    print(f"  vector({dim}) column and HNSW index ready.\n")


async def migrate(reset: bool = False) -> None:
    raw_url = os.getenv("DATABASE_URL").replace("postgresql+asyncpg://", "postgresql://")

    print("Connecting to Supabase...")
    conn = await asyncpg.connect(raw_url, statement_cache_size=0)

    await setup_schema(conn)

    if reset:
        print("--reset: clearing all existing embeddings...")
        await conn.execute('UPDATE "Users" SET embedding = NULL;')
        print("  Done.\n")

    print("Fetching users with no embedding...")
    rows = await conn.fetch("""
        SELECT
            user_id, commodity, role,
            latitude_raw, longitude_raw,
            min_quantity_mt, max_quantity_mt
        FROM "Users"
        WHERE embedding IS NULL
        ORDER BY user_id
    """)
    print(f"Found {len(rows)} users to backfill.\n")

    if not rows:
        print("Nothing to do — all users already have embeddings.")
        await conn.close()
        return

    succeeded, failed = 0, []

    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start : start + BATCH_SIZE]
        updates = []

        for row in batch:
            try:
                commodity_list = [c.strip() for c in row["commodity"].split(";")]
                vec = build_candidate_vector(
                    commodity_list=commodity_list,
                    role=row["role"],
                    lat=float(row["latitude_raw"]),
                    lon=float(row["longitude_raw"]),
                    qty_min=int(row["min_quantity_mt"]),
                    qty_max=int(row["max_quantity_mt"]),
                )
                updates.append((list_to_pgvec(vec), row["user_id"]))
            except Exception as e:
                print(f"  ⚠ Skipping user {row['user_id']}: {e}")
                failed.append(row["user_id"])

        await conn.executemany(
            'UPDATE "Users" SET embedding = $1::vector WHERE user_id = $2',
            updates,
        )
        succeeded += len(updates)
        print(f"  Updated {min(start + BATCH_SIZE, len(rows))}/{len(rows)}")

    await conn.close()

    print(f"\n✓ Done.")
    print(f"  Backfilled : {succeeded}")
    print(f"  Failed     : {len(failed)}")
    if failed:
        print(f"  Failed IDs : {failed}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Wipe all existing embeddings and rebuild from scratch (use after encoding changes).",
    )
    args = parser.parse_args()
    asyncio.run(migrate(reset=args.reset))
