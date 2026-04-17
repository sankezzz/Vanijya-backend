from typing import Optional
from pydantic import BaseModel


class SendOTPRequest(BaseModel):
    phone_number: str
    country_code: str  # e.g. "+91"


class VerifyOTPRequest(BaseModel):
    phone_number: str
    country_code: str
    otp_code: str


class OnboardingTokenResponse(BaseModel):
    onboarding_token: str
    token_type: str = "bearer"
    expires_in: int = 900  # 15 minutes in seconds


class VerifyOTPResponse(BaseModel):
    is_new_user: bool
    onboarding_token: Optional[str] = None  # only for new users — use for registration steps
    user_id: Optional[str] = None           # only for returning users — already completed onboarding
    token_type: str = "bearer"
