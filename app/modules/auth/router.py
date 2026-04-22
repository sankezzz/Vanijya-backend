from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.modules.auth.schemas import FirebaseVerifyRequest, VerifyOTPResponse
from app.modules.auth.service import verify_firebase_token, issue_onboarding_token
from app.modules.profile.models import User
from app.shared.utils.response import ok

router = APIRouter(prefix="/auth", tags=["Auth"])


# ---------------------------------------------------------------------------
# Deprecated — OTP is now sent client-side via the Firebase Auth SDK.
# These endpoints are kept as stubs so existing frontend calls don't break.
# ---------------------------------------------------------------------------

# @router.post("/send-otp", status_code=200)
# def send_otp_api(payload: SendOTPRequest):
#     """DEPRECATED: Firebase Auth SDK sends the OTP directly from the mobile app."""
#     return ok(message="OTP is now sent via Firebase on the client — no server action needed.")


# @router.post("/verify-otp", status_code=200)
# def verify_otp_api(payload: VerifyOTPRequest, db: Session = Depends(get_db)):
#     """DEPRECATED: Use POST /auth/firebase-verify instead."""
#     raise HTTPException(status_code=410, detail="Use POST /auth/firebase-verify")


# ---------------------------------------------------------------------------
# Active endpoint
# ---------------------------------------------------------------------------

@router.post("/firebase-verify", status_code=200)
def firebase_verify(payload: FirebaseVerifyRequest, db: Session = Depends(get_db)):
    """
    Exchange a Firebase ID token (issued after phone OTP verification) for either:
    - an onboarding_token  (new user  → proceed to profile creation)
    - a user_id            (returning user → go straight to the app)
    """
    try:
        phone_number, country_code = verify_firebase_token(payload.firebase_id_token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    existing_user = db.query(User).filter(
        User.country_code == country_code,
        User.phone_number == phone_number,
    ).first()

    is_new_user = existing_user is None

    if is_new_user:
        onboarding_token = issue_onboarding_token(phone_number, country_code)
        return ok(
            VerifyOTPResponse(is_new_user=True, onboarding_token=onboarding_token),
            "OTP verified. Use the onboarding token to complete registration.",
        )

    profile_id = existing_user.profile.id if existing_user.profile else None
    return ok(
        VerifyOTPResponse(is_new_user=False, user_id=str(existing_user.id), profile_id=profile_id),
        "Welcome back. Use your saved user_id to continue.",
    )
