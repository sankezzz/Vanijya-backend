"""
migrate_connections.py
Run once to create the follow and message-request tables.

    python migrate_connections.py

Safe to re-run — all statements are idempotent (IF NOT EXISTS).
"""

import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()


async def migrate():
    raw_url = os.getenv("DATABASE_URL").replace("postgresql+asyncpg://", "postgresql://")

    print("Connecting to Supabase...")
    conn = await asyncpg.connect(raw_url, statement_cache_size=0)

    print("Setting up connections schema...\n")

    # ── pg_trgm for fuzzy search ───────────────────────────────────────────────
    await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    print("  pg_trgm extension ready.")

    # ── user_connections (follows) ─────────────────────────────────────────────
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_connections (
            id              BIGSERIAL PRIMARY KEY,
            follower_id     INTEGER NOT NULL REFERENCES "Users"(user_id) ON DELETE CASCADE,
            following_id    INTEGER NOT NULL REFERENCES "Users"(user_id) ON DELETE CASCADE,
            followed_at     TIMESTAMPTZ DEFAULT NOW(),

            UNIQUE (follower_id, following_id),
            CHECK  (follower_id != following_id)
        );
    """)
    print("  user_connections table ready.")

    # ── message_requests ──────────────────────────────────────────────────────
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS message_requests (
            id              BIGSERIAL PRIMARY KEY,
            sender_id       INTEGER NOT NULL REFERENCES "Users"(user_id) ON DELETE CASCADE,
            receiver_id     INTEGER NOT NULL REFERENCES "Users"(user_id) ON DELETE CASCADE,
            status          VARCHAR(20) DEFAULT 'pending'
                            CHECK (status IN ('pending', 'accepted', 'declined')),
            sent_at         TIMESTAMPTZ DEFAULT NOW(),
            acted_at        TIMESTAMPTZ,   -- set when accepted or declined

            UNIQUE (sender_id, receiver_id),
            CHECK  (sender_id != receiver_id)
        );
    """)
    print("  message_requests table ready.")

    # ── indexes ───────────────────────────────────────────────────────────────
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_uc_follower   ON user_connections(follower_id);")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_uc_following  ON user_connections(following_id);")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_mr_sender     ON message_requests(sender_id);")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_mr_receiver   ON message_requests(receiver_id, status);")

    # trigram indexes for search/suggestions
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_city_trgm      ON \"Users\" USING GIN (city gin_trgm_ops);")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_commodity_trgm ON \"Users\" USING GIN (commodity gin_trgm_ops);")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_role_trgm      ON \"Users\" USING GIN (role gin_trgm_ops);")
    print("  Indexes ready.\n")

    await conn.close()
    print("✓ Done.")


if __name__ == "__main__":
    asyncio.run(migrate())
