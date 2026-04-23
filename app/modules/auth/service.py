import hashlib
import json
import os
from pathlib import Path
from uuid import UUID

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials

from app.core.security.jwt_handler import create_onboarding_token

# ---------------------------------------------------------------------------
# Firebase Admin SDK initialisation (reuse if already initialised)
# ---------------------------------------------------------------------------

def _get_firebase_app() -> firebase_admin.App:
    try:
        return firebase_admin.get_app()
    except ValueError:
        pass  # not yet initialised

    # Production: service account JSON provided as env var string
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if sa_json:
        cred = credentials.Certificate(json.loads(sa_json))
    else:
        # Development: load from service.json next to this repo
        service_json_path = Path(__file__).resolve().parents[4] / "backend" / "service.json"
        cred = credentials.Certificate(str(service_json_path))

    return firebase_admin.initialize_app(cred)


_firebase_app = _get_firebase_app()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def verify_firebase_token(firebase_id_token: str) -> tuple[str, str]:
    """
    Verify a Firebase ID token issued after phone OTP verification.

    Returns (phone_number, country_code) extracted from the token.
    Raises ValueError on invalid / expired tokens.
    """
    try:
        decoded = firebase_auth.verify_id_token(firebase_id_token, app=_firebase_app)
    except Exception as exc:
        raise ValueError(f"Invalid Firebase token: {exc}") from exc

    phone = decoded.get("phone_number")
    if not phone:
        raise ValueError("Token does not contain a phone number — wrong sign-in method?")

    # Firebase stores phone as E.164: +919876543210
    # Split into country_code (+91) and phone_number (9876543210)
    if phone.startswith("+91"):
        country_code = "+91"
        phone_number = phone[3:]
    else:
        # Generic split: first 2–3 chars are the country code
        # For non-Indian numbers the frontend should send the split explicitly if needed
        country_code = phone[:3] if phone[2].isdigit() and phone[3:4].isdigit() else phone[:3]
        phone_number = phone[len(country_code):]

    return phone_number, country_code


def _stable_uuid_for_phone(phone_number: str, country_code: str) -> UUID:
    """Derive a deterministic UUID from the phone number so repeated firebase-verify
    calls before the user row is created always produce the same UUID."""
    digest = hashlib.sha256(f"{country_code}{phone_number}".encode()).digest()
    return UUID(bytes=digest[:16])


def issue_onboarding_token(phone_number: str, country_code: str) -> str:
    """Create a short-lived onboarding token for new user registration."""
    user_id = _stable_uuid_for_phone(phone_number, country_code)
    return create_onboarding_token(user_id, phone_number, country_code)
