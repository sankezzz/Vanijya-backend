from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from uuid import UUID

from app.dependencies import get_db, get_onboarding_user_id, get_onboarding_claims
from app.core.security.jwt_handler import OnboardingClaims, create_access_token
from app.modules.profile.schemas import (
    ProfileCreate,
    ProfileUpdate,
    UserCreate,
    VerifyProfileRequest,
    FcmTokenUpdate,
)
from app.modules.profile.service import (
    create_user,
    create_profile,
    get_my_profile,
    get_profile_by_id,
    delete_profile,
    delete_user,
    update_profile,
    get_avatar_upload_url,
    save_avatar_url,
    update_fcm_token,
    store_access_token,
    submit_verification,
    ProfileConflictError,
    ProfileNotFoundError,
    ProfileValidationError,
    UserConflictError,
)
from app.shared.utils.response import ok

router = APIRouter(prefix="/profile", tags=["Profile"])


# ---------------------------------------------------------------------------
# Step 1 — create user row (called right after OTP verification)
# Onboarding token still required here — it carries phone + country code.
# ---------------------------------------------------------------------------

@router.post("/user", status_code=201)
def create_user_api(
    db: Session = Depends(get_db),
    claims: OnboardingClaims = Depends(get_onboarding_claims),
):
    payload = UserCreate(phone_number=claims.phone_number, country_code=claims.country_code)
    try:
        result = create_user(db, claims.user_id, payload)
        return ok(result, "User created successfully")
    except UserConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))


# ---------------------------------------------------------------------------
# Step 2 — create profile (screens 3 + 4 + 5 combined)
# Onboarding token still required here — it identifies the user being registered.
# ---------------------------------------------------------------------------

@router.post("/")
def create_profile_api(
    payload: ProfileCreate,
    db: Session = Depends(get_db),
    current_user_id: UUID = Depends(get_onboarding_user_id),
):
    try:
        result = create_profile(db, current_user_id, payload)
        return ok({"profile": result}, "Profile created successfully")
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ProfileConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ProfileValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# FCM token — no auth required, user_id passed as query param
# ---------------------------------------------------------------------------

@router.patch("/user/fcm-token")
def update_fcm_token_api(
    payload: FcmTokenUpdate,
    user_id: UUID = Query(..., description="Acting user's UUID"),
    db: Session = Depends(get_db),
):
    try:
        update_fcm_token(db, user_id, payload.fcm_token)
        return ok(message="FCM token updated")
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------------------------
# Verification — no auth required, user_id passed as query param
# ---------------------------------------------------------------------------

@router.post("/verify")
def verify_profile_api(
    payload: VerifyProfileRequest,
    user_id: UUID = Query(..., description="Acting user's UUID"),
    db: Session = Depends(get_db),
):
    try:
        result = submit_verification(db, user_id, payload)
        return ok(result, "Documents submitted for verification")
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ProfileValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# My profile — no auth, user_id as query param
# ---------------------------------------------------------------------------

@router.get("/me")
def get_my_profile_api(
    user_id: UUID = Query(..., description="Acting user's UUID"),
    db: Session = Depends(get_db),
):
    try:
        result = get_my_profile(db, user_id)
        return ok(result, "Profile fetched successfully")
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/avatar-upload-url")
async def get_avatar_upload_url_api(
    user_id: UUID = Query(..., description="Acting user's UUID"),
    content_type: str = Query(..., description="image/jpeg | image/png | image/webp"),
    db: Session = Depends(get_db),
):
    try:
        result = await get_avatar_upload_url(db, user_id, content_type)
        return ok(result, "Upload URL generated")
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ProfileValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/avatar")
def save_avatar_url_api(
    user_id: UUID = Query(..., description="Acting user's UUID"),
    avatar_url: str = Body(..., embed=True, description="Public URL from Supabase after upload"),
    db: Session = Depends(get_db),
):
    try:
        result = save_avatar_url(db, user_id, avatar_url)
        return ok(result, "Avatar updated successfully")
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/")
def update_profile_api(
    payload: ProfileUpdate,
    user_id: UUID = Query(..., description="Acting user's UUID"),
    db: Session = Depends(get_db),
):
    try:
        result = update_profile(db, user_id, payload)
        return ok(result, "Profile updated successfully")
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ProfileValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/user")
def delete_user_api(
    user_id: UUID = Query(..., description="Acting user's UUID"),
    db: Session = Depends(get_db),
):
    try:
        delete_user(db, user_id)
        return ok(message="User and all associated data deleted successfully")
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/")
def delete_profile_api(
    user_id: UUID = Query(..., description="Acting user's UUID"),
    db: Session = Depends(get_db),
):
    try:
        delete_profile(db, user_id)
        return ok(message="Profile deleted successfully")
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------------------------
# Public profile view — no auth required
# ---------------------------------------------------------------------------

@router.get("/{profile_id}")
def get_profile_api(
    profile_id: int,
    db: Session = Depends(get_db),
):
    try:
        result = get_profile_by_id(db, profile_id)
        return ok(result, "Profile fetched successfully")
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
