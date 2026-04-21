"""
seed_verified_profiles.py — Marks a random subset of existing profiles as verified.

For each selected profile:
  - Adds a fake identity document (PAN or Aadhaar) with status="verified"
  - Adds a fake business document (GST or Trade License) with status="verified"
  - Sets is_user_verified=True, is_business_verified=True, is_verified=True

Usage:
    python scripts/seed_verified_profiles.py              # verify ~40% of profiles
    python scripts/seed_verified_profiles.py --pct 60    # verify 60%
    python scripts/seed_verified_profiles.py --ids 11 12 15  # verify specific profile IDs
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import random
import string
from datetime import datetime, timezone, timedelta

from app.core.database.session import SessionLocal
from app.modules.profile.models import Profile, Profile_Document


# ─── Fake document number generators ─────────────────────────────────────────

def _pan() -> str:
    """ABCDE1234F format"""
    letters = string.ascii_uppercase
    return (
        "".join(random.choices(letters, k=5))
        + "".join(random.choices(string.digits, k=4))
        + random.choice(letters)
    )


def _aadhaar() -> str:
    """12-digit number, first digit not 0"""
    return str(random.randint(2, 9)) + "".join(random.choices(string.digits, k=11))


def _gst(pan: str) -> str:
    """22AAAAA0000A1Z5 — state code + PAN + entity + Z + check"""
    state_code = str(random.randint(1, 36)).zfill(2)
    return state_code + pan + str(random.randint(1, 9)) + "Z" + random.choice(string.ascii_uppercase)


def _trade_license() -> str:
    """TL-XXXXXXXX format"""
    return "TL-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


def _verified_at() -> datetime:
    """Random date in the past 6 months."""
    days_ago = random.randint(7, 180)
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


# ─── Core logic ───────────────────────────────────────────────────────────────

def verify_profiles(db, profile_ids: list[int]) -> None:
    profiles = db.query(Profile).filter(Profile.id.in_(profile_ids)).all()

    for p in profiles:
        # Skip if already fully verified
        if p.is_verified and p.is_user_verified and p.is_business_verified:
            print(f"  [SKIP] Profile {p.id:>3}  {p.name:<24}  already verified")
            continue

        pan = _pan()
        v_at = _verified_at()

        # Choose identity doc type randomly
        use_pan = random.random() > 0.4  # 60% PAN, 40% Aadhaar
        if use_pan:
            id_type   = "pan_card"
            id_number = pan
        else:
            id_type   = "aadhaar_card"
            id_number = _aadhaar()

        # Choose business doc type randomly
        use_gst = random.random() > 0.35  # 65% GST, 35% Trade License
        if use_gst:
            biz_type   = "gst_certificate"
            biz_number = _gst(pan)
        else:
            biz_type   = "trade_license"
            biz_number = _trade_license()

        # Upsert identity document
        id_doc = db.query(Profile_Document).filter(
            Profile_Document.profile_id == p.id,
            Profile_Document.document_type == id_type,
        ).first()
        if id_doc:
            id_doc.document_number     = id_number
            id_doc.verification_status = "verified"
            id_doc.verified_at         = v_at
        else:
            db.add(Profile_Document(
                profile_id=p.id,
                document_type=id_type,
                document_number=id_number,
                verification_status="verified",
                verified_at=v_at,
            ))

        # Upsert business document
        biz_doc = db.query(Profile_Document).filter(
            Profile_Document.profile_id == p.id,
            Profile_Document.document_type == biz_type,
        ).first()
        if biz_doc:
            biz_doc.document_number     = biz_number
            biz_doc.verification_status = "verified"
            biz_doc.verified_at         = v_at
        else:
            db.add(Profile_Document(
                profile_id=p.id,
                document_type=biz_type,
                document_number=biz_number,
                verification_status="verified",
                verified_at=v_at,
            ))

        # Mark profile as verified
        p.is_user_verified     = True
        p.is_business_verified = True
        p.is_verified          = True

        print(
            f"  [OK]   Profile {p.id:>3}  {p.name:<24}  "
            f"{id_type:<14}  {biz_type}"
        )

    db.commit()


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Mark existing profiles as verified.")
    parser.add_argument("--pct",  type=int,   default=40,  help="Percentage of profiles to verify (default: 40)")
    parser.add_argument("--ids",  type=int,   nargs="+",   help="Verify specific profile IDs instead of random selection")
    args = parser.parse_args()

    print("=" * 65)
    print("  Vanijyaa — Seed Verified Profiles")
    print("=" * 65)

    db = SessionLocal()
    try:
        all_profiles = db.query(Profile).order_by(Profile.id).all()
        if not all_profiles:
            print("\n  No profiles found in DB. Run seed_users_and_posts.py first.\n")
            return

        if args.ids:
            target_ids = args.ids
            print(f"\n  Verifying {len(target_ids)} specified profile(s): {target_ids}\n")
        else:
            count = max(1, round(len(all_profiles) * args.pct / 100))
            selected = random.sample(all_profiles, count)
            target_ids = [p.id for p in selected]
            print(f"\n  Total profiles in DB : {len(all_profiles)}")
            print(f"  Selecting {args.pct}%       : {count} profile(s)\n")

        verify_profiles(db, target_ids)

        verified_count = db.query(Profile).filter(Profile.is_verified == True).count()
        print(f"\n{'=' * 65}")
        print(f"  Done!  Verified profiles in DB: {verified_count} / {len(all_profiles)}")
        print(f"{'=' * 65}\n")

    except Exception as exc:
        db.rollback()
        print(f"\n[FATAL] {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
