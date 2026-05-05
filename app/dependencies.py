from uuid import UUID

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from app.core.database.session import SessionLocal
from app.core.security.jwt_handler import (
    OnboardingClaims,
    decode_access_token,
    decode_onboarding_claims,
    decode_onboarding_token,
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user_id(token: str = Depends(oauth2_scheme)) -> UUID:
    """JWT-only validation — signature + expiry checked by PyJWT, no DB round trip."""
    user_id, _ = decode_access_token(token)
    return user_id


def get_onboarding_claims(token: str = Depends(oauth2_scheme)) -> OnboardingClaims:
    return decode_onboarding_claims(token)


def get_onboarding_user_id(token: str = Depends(oauth2_scheme)) -> UUID:
    return decode_onboarding_token(token)
