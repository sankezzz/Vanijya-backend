import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.modules.auth.schemas import SendOTPRequest, VerifyOTPRequest, VerifyOTPResponse
from app.modules.auth.service import send_otp, verify_otp, issue_onboarding_token
from app.modules.profile.models import User
from app.shared.utils.response import ok

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/send-otp", status_code=200)
def send_otp_api(payload: SendOTPRequest):
    try:
        send_otp(payload.phone_number, payload.country_code)
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Failed to reach SMS gateway")
    return ok(message="OTP sent successfully")


@router.post("/verify-otp", status_code=200)
def verify_otp_api(payload: VerifyOTPRequest, db: Session = Depends(get_db)):
    try:
        verify_otp(payload.phone_number, payload.country_code, payload.otp_code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Failed to reach SMS gateway")

    existing_user = db.query(User).filter(
        User.country_code == payload.country_code,
        User.phone_number == payload.phone_number,
    ).first()

    is_new_user = existing_user is None

    if is_new_user:
        onboarding_token = issue_onboarding_token(payload.phone_number, payload.country_code)
        return ok(
            VerifyOTPResponse(is_new_user=True, onboarding_token=onboarding_token),
            "OTP verified. Use the onboarding token to complete registration.",
        )

    return ok(
        VerifyOTPResponse(is_new_user=False, user_id=str(existing_user.id)),
        "Welcome back. Use your saved user_id to continue.",
    )
