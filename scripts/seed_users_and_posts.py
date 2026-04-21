"""
seed_users_and_posts.py — Creates random seed data: users, profiles, and posts.

Idempotent: safely skips duplicate phone numbers and existing profiles.
Embeddings are built automatically via the profile service layer.

Reference data (fixed IDs, matches DB seed):
  Roles       — 1=Trader  2=Broker  3=Exporter
  Commodities — 1=Rice    2=Cotton  3=Sugar
  Interests   — 1=Connections  2=Leads  3=News
  Categories  — 1=Market Update  2=Knowledge  3=Discussion  4=Deal/Req  5=Other

Usage:
    python scripts/seed_users_and_posts.py
    python scripts/seed_users_and_posts.py --users 30 --posts 8
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import random
import uuid

from app.core.database.session import SessionLocal
from app.modules.profile import service as profile_svc
from app.modules.profile.schemas import ProfileCreate, UserCreate
from app.modules.profile.service import UserConflictError, ProfileConflictError
from app.modules.post import service as post_svc
from app.modules.post.schemas import PostCreate

# ─── Fixed reference data ─────────────────────────────────────────────────────
ROLE_IDS      = [1, 2, 3]        # 1=Trader  2=Broker  3=Exporter
COMMODITY_IDS = [1, 2, 3]        # 1=Rice    2=Cotton  3=Sugar
INTEREST_IDS  = [1, 2, 3]        # 1=Connections  2=Leads  3=News
CATEGORY_IDS  = [1, 2, 3, 4, 5]  # 1=Market Update  2=Knowledge  3=Discussion  4=Deal  5=Other

COMMODITY_NAMES = {1: "rice", 2: "cotton", 3: "sugar"}

LOCATIONS = [
    ("Mumbai",      19.0760,  72.8777),
    ("Nagpur",      21.1458,  79.0882),
    ("Vizag",       17.6868,  83.2185),
    ("Hyderabad",   17.3850,  78.4867),
    ("Pune",        18.5204,  73.8567),
    ("Chennai",     13.0827,  80.2707),
    ("Ahmedabad",   23.0225,  72.5714),
    ("Kolkata",     22.5726,  88.3639),
    ("Lucknow",     26.8467,  80.9462),
    ("Jaipur",      26.9124,  75.7873),
    ("Ludhiana",    30.9010,  75.8573),
    ("Indore",      22.7196,  75.8577),
    ("Bengaluru",   12.9716,  77.5946),
    ("Patna",       25.5941,  85.1376),
    ("Bhubaneswar", 20.2961,  85.8245),
]

FIRST_NAMES = [
    "Rajesh", "Priya", "Amit", "Sunita", "Vijay", "Meena", "Suresh", "Lakshmi",
    "Ramesh", "Deepa", "Arun", "Kavita", "Mohan", "Anita", "Ganesh", "Pooja",
    "Sanjay", "Rekha", "Dinesh", "Usha", "Harish", "Padma", "Naresh", "Savita",
    "Kiran", "Ravi", "Lata", "Manoj", "Neha", "Vikram", "Arjun", "Swati",
    "Pramod", "Geeta", "Shyam", "Durga", "Balu", "Radha", "Girish", "Poonam",
]
LAST_NAMES = [
    "Kumar", "Sharma", "Patel", "Singh", "Reddy", "Nair", "Joshi", "Mehta",
    "Gupta", "Verma", "Rao", "Shah", "Agarwal", "Chauhan", "Tiwari", "Yadav",
    "Mishra", "Kulkarni", "Desai", "Pillai", "Iyer", "Naidu", "Hegde", "Shetty",
]
BUSINESS_SUFFIXES = [
    "Traders", "Exports", "Enterprises", "Commodities", "Agro", "Foods",
    "Industries", "Corp", "Associates", "International", "Brothers", "Co.",
]
GRAIN_TYPES = ["FAQ", "Grade A", "Grade B", "SQ", "Premium", "Steam", "Raw", "Refined"]
PRICE_TYPES = ["fixed", "negotiable"]


# ─── Caption generators ───────────────────────────────────────────────────────

def _market_caption(commodity: str, city: str) -> str:
    price = random.randint(20000, 80000)
    return random.choice([
        f"{commodity.title()} prices firm at ₹{price}/MT in {city} mandis. Good buying opportunity.",
        f"Export demand for {commodity} picking up. Gulf buyers active at ₹{price}/MT.",
        f"Bumper {commodity} crop expected this season. Prices may correct 8-10%. Watch arrivals.",
        f"{commodity.title()} prices up 3% this week on lower mandi arrivals and strong export interest.",
        f"New season {commodity} arriving in {city} mandis. Quality better than last year.",
        f"Prices under pressure in {city} — {commodity} at ₹{price}/MT. Good selling window.",
    ])


def _deal_caption(commodity: str, city: str) -> tuple[str, float, float, str, str]:
    qty_min = float(random.choice([10, 20, 50, 100, 200, 500]))
    qty_max = float(qty_min * random.choice([2, 5, 10]))
    price   = random.randint(20000, 80000)
    grain   = random.choice(GRAIN_TYPES)
    ptype   = random.choice(PRICE_TYPES)
    caption = random.choice([
        f"BUYING {int(qty_min)} MT {commodity.title()}. Grade: {grain}. Location: {city}. Serious sellers only.",
        f"SELLING {int(qty_min)} MT {commodity.title()}. {grain} quality. Immediate delivery. ₹{price}/MT.",
        f"URGENT REQUIREMENT: {int(qty_min)}–{int(qty_max)} MT {commodity.title()}. Advance payment. {city}.",
        f"Available: {int(qty_min)} MT {commodity.title()} for export. FOB Mumbai. Price {ptype}.",
        f"Buying {commodity.title()} in bulk — min {int(qty_min)} MT. {grain}. Price: ₹{price}/MT. {city}.",
    ])
    return caption, qty_min, qty_max, grain, ptype


def _knowledge_caption(commodity: str) -> str:
    return random.choice([
        f"Understanding futures trading: How to hedge your {commodity} trade risk effectively.",
        f"GST implications for agro-commodity traders in FY25. Key updates every trader must know.",
        f"Export documentation checklist for {commodity} shipments to Gulf markets.",
        f"How to read mandi arrival data for better {commodity} price prediction.",
        f"Quality grading parameters for {commodity} in Indian commodity markets.",
        f"APMC market reforms and their impact on {commodity} price discovery in 2025.",
    ])


def _discussion_caption(commodity: str, city: str) -> str:
    return random.choice([
        f"What are fellow traders seeing for {commodity} prices next month? Share your view.",
        f"Anyone facing quality issues with {commodity} arrivals from {city} region this season?",
        f"Best mandis for {commodity} procurement in South India — recommendations welcome.",
        f"Warehouse charges in {city} are too high. Anyone know good alternatives for {commodity} storage?",
        f"Government MSP for {commodity} — is it helping or distorting the market? Let's discuss.",
        f"Monsoon forecast looking weak this year. How are you planning your {commodity} inventory?",
    ])


def _other_caption_and_desc(commodity: str, city: str) -> tuple[str, str]:
    pairs = [
        (
            f"Looking for a reliable customs broker for {commodity} exports — any recommendations?",
            f"Need an experienced customs broker who handles {commodity} export documentation for Gulf and EU markets. Based in {city}. Please share contacts.",
        ),
        (
            f"Seeking transportation partners for bulk {commodity} movement from {city} to ports.",
            f"Looking for road transport contractors with experience moving bulk {commodity} from {city} to JNPT or Mundra. 20-50 MT loads. Regular business available.",
        ),
        (
            f"Need quality inspector for {commodity} pre-shipment checks in {city}.",
            f"Require a certified {commodity} quality inspector for pre-shipment survey in {city}. Must have experience with export quality norms.",
        ),
        (
            f"Warehouse space needed for bulk {commodity} storage in {city} area.",
            f"Looking for climate-controlled warehouse space for {commodity} storage near {city}. Min 500 MT capacity. Short-term lease preferred.",
        ),
    ]
    return random.choice(pairs)


# ─── Random data generators ───────────────────────────────────────────────────

def _random_phone() -> str:
    return str(random.randint(7000000000, 9999999999))


def _random_name() -> str:
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def _random_business(name: str) -> str | None:
    if random.random() < 0.65:
        last = name.split()[-1]
        return f"{last} {random.choice(BUSINESS_SUFFIXES)}"
    return None


def _random_commodities() -> list[int]:
    k = random.choices([1, 2, 3], weights=[0.50, 0.35, 0.15], k=1)[0]
    return random.sample(COMMODITY_IDS, k)


def _random_interests() -> list[int]:
    k = random.choices([1, 2, 3], weights=[0.30, 0.50, 0.20], k=1)[0]
    return random.sample(INTEREST_IDS, k)


def _random_qty_range() -> tuple[float, float]:
    qmin = float(random.choice([10, 20, 50, 100, 200, 500]))
    qmax = qmin * float(random.choice([2, 5, 10, 20]))
    return qmin, qmax


# ─── Seed logic ───────────────────────────────────────────────────────────────

def seed_users(db, count: int) -> list[tuple[uuid.UUID, int]]:
    """Create `count` users + profiles. Returns list of (user_id, profile_id) pairs."""
    results = []

    for i in range(count):
        user_id       = uuid.uuid4()
        phone         = _random_phone()
        name          = _random_name()
        city, lat, lon = random.choice(LOCATIONS)
        role_id       = random.choice(ROLE_IDS)
        commodities   = _random_commodities()
        interests     = _random_interests()
        qty_min, qty_max = _random_qty_range()
        business_name = _random_business(name)

        # Step 1 — User row
        try:
            profile_svc.create_user(
                db,
                user_id,
                UserCreate(phone_number=phone, country_code="+91"),
            )
        except UserConflictError:
            print(f"  [SKIP] Phone {phone} already registered — skipping user {i + 1}")
            continue
        except Exception as exc:
            print(f"  [ERR]  User creation failed (phone={phone}): {exc}")
            continue

        # Step 2 — Profile row + embedding
        try:
            profile = profile_svc.create_profile(
                db,
                user_id,
                ProfileCreate(
                    role_id=role_id,
                    name=name,
                    commodities=commodities,
                    interests=interests,
                    quantity_min=qty_min,
                    quantity_max=qty_max,
                    business_name=business_name,
                    latitude=lat,
                    longitude=lon,
                ),
            )
            results.append((user_id, profile.id))
            role_label = {1: "Trader", 2: "Broker", 3: "Exporter"}[role_id]
            print(
                f"  [OK]   {i + 1:>2}/{count}  {name:<24}  "
                f"{role_label:<8}  {city:<14}  commodities={commodities}"
            )
        except ProfileConflictError:
            print(f"  [SKIP] Profile already exists for user {user_id}")
        except Exception as exc:
            print(f"  [ERR]  Profile creation failed for {name}: {exc}")

    return results


def seed_posts(db, profile_ids: list[int], posts_per_user: int) -> int:
    """Create `posts_per_user` posts for each profile. Returns total count created."""
    total = 0
    # Weights: Market Update, Knowledge, Discussion, Deal, Other
    cat_weights = [0.25, 0.20, 0.20, 0.25, 0.10]

    for idx, pid in enumerate(profile_ids, 1):
        for _ in range(posts_per_user):
            cat_id    = random.choices(CATEGORY_IDS, weights=cat_weights, k=1)[0]
            com_id    = random.choice(COMMODITY_IDS)
            commodity = COMMODITY_NAMES[com_id]
            city, _, _ = random.choice(LOCATIONS)
            target_roles = random.choice([None, None, [1], [2], [3], [1, 2], [2, 3]])
            is_public    = random.random() > 0.15  # 85% public

            try:
                if cat_id == 4:
                    caption, qty_min, qty_max, grain, ptype = _deal_caption(commodity, city)
                    payload = PostCreate(
                        category_id=cat_id,
                        commodity_id=com_id,
                        caption=caption,
                        is_public=is_public,
                        target_roles=target_roles,
                        grain_type_size=grain,
                        commodity_quantity_min=qty_min,
                        commodity_quantity_max=qty_max,
                        price_type=ptype,
                    )
                elif cat_id == 5:
                    caption, desc = _other_caption_and_desc(commodity, city)
                    payload = PostCreate(
                        category_id=cat_id,
                        commodity_id=com_id,
                        caption=caption,
                        is_public=is_public,
                        target_roles=target_roles,
                        other_description=desc,
                    )
                elif cat_id == 1:
                    payload = PostCreate(
                        category_id=cat_id,
                        commodity_id=com_id,
                        caption=_market_caption(commodity, city),
                        is_public=is_public,
                        target_roles=target_roles,
                    )
                elif cat_id == 2:
                    payload = PostCreate(
                        category_id=cat_id,
                        commodity_id=com_id,
                        caption=_knowledge_caption(commodity),
                        is_public=is_public,
                        target_roles=target_roles,
                    )
                else:  # cat_id == 3
                    payload = PostCreate(
                        category_id=cat_id,
                        commodity_id=com_id,
                        caption=_discussion_caption(commodity, city),
                        is_public=is_public,
                        target_roles=target_roles,
                    )

                post_svc.create_post(db, pid, payload)
                total += 1

            except Exception as exc:
                print(f"  [ERR]  Post creation failed (profile={pid}, cat={cat_id}): {exc}")

        print(f"  [OK]   Profile {idx:>3}/{len(profile_ids)}  (id={pid})  — {posts_per_user} posts created")

    return total


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Seed random users, profiles, and posts into Vanijyaa DB."
    )
    parser.add_argument("--users", type=int, default=20, help="Number of users to create (default: 20)")
    parser.add_argument("--posts", type=int, default=5,  help="Posts per user (default: 5)")
    args = parser.parse_args()

    print("=" * 65)
    print("  Vanijyaa — Seed Users, Profiles & Posts")
    print("=" * 65)

    db = SessionLocal()
    try:
        print(f"\n[1/2] Creating {args.users} users + profiles...\n")
        pairs = seed_users(db, args.users)
        profile_ids = [pid for _, pid in pairs]
        print(f"\n  Created: {len(pairs)} users / {len(profile_ids)} profiles")

        if not profile_ids:
            print("\n  No profiles created — skipping posts.")
            return

        total_expected = len(profile_ids) * args.posts
        print(f"\n[2/2] Creating {args.posts} posts × {len(profile_ids)} profiles "
              f"({total_expected} total)...\n")
        total_posts = seed_posts(db, profile_ids, args.posts)

        print(f"\n{'=' * 65}")
        print(f"  Done!  Users/Profiles: {len(pairs)}   Posts: {total_posts}")
        print(f"{'=' * 65}\n")

    except Exception as exc:
        db.rollback()
        print(f"\n[FATAL] {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
