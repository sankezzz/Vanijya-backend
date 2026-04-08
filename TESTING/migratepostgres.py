"""
Run once:
python -m app.db.upload_engagement_csv
"""

import os
import asyncio
import asyncpg
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

CSV_FILE = "users_with_engagement.csv"

async def upload_csv():
    print("Reading CSV...")
    df = pd.read_csv(CSV_FILE)

    print("Connecting to Supabase...")
    conn = await asyncpg.connect(
        os.getenv("DATABASE_URL").replace("postgresql+asyncpg://", "postgresql://"),
        statement_cache_size=0
    )

    # Make sure columns exist
    print("Adding columns if not exists...")
    await conn.execute("""
        ALTER TABLE "Users"
        ADD COLUMN IF NOT EXISTS followers INTEGER,
        ADD COLUMN IF NOT EXISTS like_count INTEGER,
        ADD COLUMN IF NOT EXISTS comment_count INTEGER,
        ADD COLUMN IF NOT EXISTS share_count INTEGER,
        ADD COLUMN IF NOT EXISTS screentime_hours FLOAT;
    """)

    print("Updating rows from CSV...")

    for _, row in df.iterrows():
        await conn.execute("""
            UPDATE "Users"
            SET
                followers = $1,
                like_count = $2,
                comment_count = $3,
                share_count = $4,
                screentime_hours = $5
            WHERE user_id = $6
        """,
        int(row["followers"]),
        int(row["like_count"]),
        int(row["comment_count"]),
        int(row["share_count"]),
        float(row["screentime_hours"]),
        int(row["user_id"])
        )

    await conn.close()
    print("✓ CSV data uploaded successfully.")

if __name__ == "__main__":
    asyncio.run(upload_csv())