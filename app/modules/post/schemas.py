from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, field_validator, model_validator

# Fixed category IDs (matches DB seed)
CATEGORY_DEAL = 4
CATEGORY_OTHER = 5

VALID_PRICE_TYPES = {"fixed", "negotiable"}


# ----------------------------------------------------------------------------
# Post create / update
# ----------------------------------------------------------------------------

class PostCreate(BaseModel):
    # Required
    category_id: int        # 1=Market Update 2=Knowledge 3=Discussion 4=Deal/Requirement 5=Other
    commodity_id: int       # 1=Rice 2=Cotton 3=Sugar
    caption: str

    # Visibility
    is_public: bool = True                      # True=all users, False=followers only
    target_roles: Optional[List[int]] = None    # null=all roles, [1/2/3]=specific roles

    # Interaction
    allow_comments: bool = True

    # Optional media
    image_url: Optional[str] = None

    # --- Deal / Requirement fields (required when category_id == 4) ----------
    grain_type_size: Optional[str] = None
    commodity_quantity: Optional[float] = None
    price_type: Optional[str] = None

    # --- Other category (required when category_id == 5) --------------------
    other_description: Optional[str] = None

    @field_validator("price_type")
    @classmethod
    def price_type_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_PRICE_TYPES:
            raise ValueError(f"price_type must be one of: {', '.join(VALID_PRICE_TYPES)}")
        return v

    @field_validator("caption")
    @classmethod
    def caption_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Caption cannot be empty")
        return v.strip()

    @model_validator(mode="after")
    def validate_category_fields(self) -> "PostCreate":
        if self.category_id == CATEGORY_DEAL:
            missing = [
                f for f, v in [
                    ("grain_type_size", self.grain_type_size),
                    ("commodity_quantity", self.commodity_quantity),
                    ("price_type", self.price_type),
                ]
                if not v
            ]
            if missing:
                raise ValueError(
                    f"Deal/Requirement posts require: {', '.join(missing)}"
                )

        if self.category_id == CATEGORY_OTHER:
            if not self.other_description or not self.other_description.strip():
                raise ValueError("other_description is required when category is 'Other'")
            self.other_description = self.other_description.strip()

        return self


# ----------------------------------------------------------------------------
# Post update (PATCH – all fields optional)
# ----------------------------------------------------------------------------

class PostUpdate(BaseModel):
    caption: Optional[str] = None
    image_url: Optional[str] = None
    is_public: Optional[bool] = None
    target_roles: Optional[List[int]] = None
    allow_comments: Optional[bool] = None
    grain_type_size: Optional[str] = None
    commodity_quantity: Optional[float] = None
    price_type: Optional[str] = None
    other_description: Optional[str] = None

    @field_validator("caption")
    @classmethod
    def caption_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("Caption cannot be empty")
        return v.strip() if v else v

    @field_validator("price_type")
    @classmethod
    def price_type_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_PRICE_TYPES:
            raise ValueError(f"price_type must be one of: {', '.join(VALID_PRICE_TYPES)}")
        return v


# ----------------------------------------------------------------------------
# Post response
# ----------------------------------------------------------------------------

class PostResponse(BaseModel):
    id: int
    profile_id: int
    category_id: int
    commodity_id: int
    caption: str
    image_url: Optional[str]
    is_public: bool
    target_roles: Optional[List[int]]
    allow_comments: bool

    # Deal / Requirement
    grain_type_size: Optional[str]
    commodity_quantity: Optional[float]
    price_type: Optional[str]

    # Other
    other_description: Optional[str]

    # Counters + viewer state
    view_count: int
    like_count: int
    comment_count: int
    share_count: int
    is_liked: bool
    is_saved: bool

    created_at: datetime

    class Config:
        from_attributes = True


# ----------------------------------------------------------------------------
# Comments
# ----------------------------------------------------------------------------

class CommentCreate(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def content_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Comment content cannot be empty")
        return v.strip()


class CommentResponse(BaseModel):
    id: int
    post_id: int
    profile_id: int
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


# ----------------------------------------------------------------------------
# Interaction responses
# ----------------------------------------------------------------------------

class LikeResponse(BaseModel):
    liked: bool
    like_count: int


class SaveResponse(BaseModel):
    saved: bool


class ShareResponse(BaseModel):
    share_count: int
