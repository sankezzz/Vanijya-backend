"""
Groups service layer — pure business logic, no FastAPI imports.

Verification gate:
  Only users whose profile.is_verified == True may create a group.

Role mapping (matches existing lookup table seeds):
  1 = Trader   → "trader"
  2 = Broker   → "broker"
  3 = Exporter → "exporter"
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session, joinedload

from app.modules.profile.models import Profile, Profile_Commodity, Role
from app.modules.groups.models import (
    Group,
    GroupActivityCache,
    GroupEmbedding,
    GroupMember,
)
from app.modules.groups.schemas import (
    GroupCreate,
    GroupListOut,
    GroupMemberOut,
    GroupOut,
    GroupPermissionsUpdate,
    GroupSuggestionOut,
    GroupUpdate,
    InviteLinkOut,
)
from app.modules.groups.vector import (
    build_group_vector,
    build_match_reasons,
    compute_activity_score,
    compute_final_score,
    cosine_similarity,
)
from app.modules.connections.encoding.vector import build_query_vector

# role_id → string name used in vector encoding
ROLE_ID_TO_NAME = {1: "trader", 2: "broker", 3: "exporter"}
TOP_K = 20

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class GroupNotFoundError(Exception):
    pass

class GroupConflictError(Exception):
    pass

class GroupPermissionError(Exception):
    pass

class GroupValidationError(Exception):
    pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_profile_or_raise(db: Session, user_id: UUID) -> Profile:
    profile = (
        db.query(Profile)
        .options(
            joinedload(Profile.commodities).joinedload(Profile_Commodity.commodity),
        )
        .filter(Profile.users_id == user_id)
        .first()
    )
    if not profile:
        raise GroupNotFoundError("Profile not found — complete onboarding first")
    return profile


def _get_group_or_raise(db: Session, group_id: UUID) -> Group:
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise GroupNotFoundError("Group not found")
    return group


def _get_membership(
    db: Session, group_id: UUID, user_id: UUID
) -> Optional[GroupMember]:
    return (
        db.query(GroupMember)
        .filter(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
        .first()
    )


def _require_admin(db: Session, group_id: UUID, user_id: UUID) -> None:
    membership = _get_membership(db, group_id, user_id)
    if not membership or membership.role != "admin":
        raise GroupPermissionError("Admin access required")


def _build_group_out(group: Group, membership: Optional[GroupMember]) -> GroupOut:
    return GroupOut(
        id=group.id,
        name=group.name,
        description=group.description,
        icon_url=group.icon_url,
        commodity=group.commodity or [],
        target_roles=group.target_roles or [],
        region_market=group.region_market,
        region_lat=group.region_lat,
        region_lon=group.region_lon,
        category=group.category,
        accessibility=group.accessibility,
        posting_perm=group.posting_perm,
        chat_perm=group.chat_perm,
        member_count=group.member_count,
        created_by=group.created_by,
        created_at=group.created_at,
        is_member=membership is not None,
        member_role=membership.role if membership else None,
        is_muted=membership.is_muted if membership else False,
        is_favorite=membership.is_favorite if membership else False,
    )


def _store_embedding(db: Session, group: Group) -> None:
    """Build and persist the group's 11-dim embedding."""
    lat = group.region_lat or 20.5937   # default: centre of India
    lon = group.region_lon or 78.9629
    vec = build_group_vector(
        commodity_list=group.commodity or [],
        target_roles=group.target_roles or [],
        lat=lat,
        lon=lon,
    )
    existing = db.query(GroupEmbedding).filter(
        GroupEmbedding.group_id == group.id
    ).first()
    if existing:
        existing.embedding = vec
        existing.updated_at = datetime.now(timezone.utc)
    else:
        db.add(GroupEmbedding(group_id=group.id, embedding=vec))


# ---------------------------------------------------------------------------
# Group CRUD
# ---------------------------------------------------------------------------

def create_group(db: Session, user_id: UUID, payload: GroupCreate) -> GroupOut:
    """
    Creates a group.  Only verified users (profile.is_verified == True) may create.
    Creator is automatically added as admin.
    """
    profile = _get_profile_or_raise(db, user_id)

    if not profile.is_verified:
        raise GroupPermissionError(
            "Only verified users can create groups. "
            "Complete profile verification first."
        )

    try:
        group = Group(
            name=payload.name.strip(),
            description=payload.description,
            group_rules=payload.group_rules,
            commodity=payload.commodities or [],
            target_roles=payload.target_roles or [],
            region_market=payload.region_market,
            region_lat=payload.region_lat,
            region_lon=payload.region_lon,
            category=payload.category,
            accessibility=payload.accessibility,
            posting_perm=payload.posting_perm,
            chat_perm=payload.chat_perm,
            created_by=user_id,
            member_count=1,
        )
        db.add(group)
        db.flush()  # get group.id

        # Creator is admin
        db.add(GroupMember(group_id=group.id, user_id=user_id, role="admin"))

        # Add initial members if provided (they join as regular members)
        added_ids = {user_id}
        for uid in (payload.initial_member_ids or []):
            if uid not in added_ids:
                db.add(GroupMember(group_id=group.id, user_id=uid, role="member"))
                added_ids.add(uid)

        group.member_count = len(added_ids)

        # Seed activity cache
        db.add(GroupActivityCache(group_id=group.id))

        # Build & store embedding
        _store_embedding(db, group)

        db.commit()
        db.refresh(group)
    except Exception:
        db.rollback()
        raise

    membership = _get_membership(db, group.id, user_id)
    return _build_group_out(group, membership)


def list_groups(
    db: Session,
    user_id: UUID,
    *,
    commodity: Optional[str] = None,
    accessibility: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
) -> GroupListOut:
    query = db.query(Group)

    if commodity:
        # JSONB array containment: commodity @> '["sugar"]'
        query = query.filter(Group.commodity.contains([commodity]))

    if accessibility:
        query = query.filter(Group.accessibility == accessibility)

    total = query.count()
    groups = (
        query.order_by(Group.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    out = []
    for g in groups:
        membership = _get_membership(db, g.id, user_id)
        out.append(_build_group_out(g, membership))

    return GroupListOut(groups=out, total=total, page=page, per_page=per_page)


def get_group(db: Session, group_id: UUID, user_id: UUID) -> GroupOut:
    group = _get_group_or_raise(db, group_id)
    membership = _get_membership(db, group_id, user_id)
    return _build_group_out(group, membership)


def update_group(
    db: Session, group_id: UUID, user_id: UUID, payload: GroupUpdate
) -> GroupOut:
    _require_admin(db, group_id, user_id)
    group = _get_group_or_raise(db, group_id)

    data = payload.model_dump(exclude_unset=True)
    if "commodities" in data:
        group.commodity = data.pop("commodities")
    for field, value in data.items():
        setattr(group, field, value)

    # Rebuild embedding when location or commodity changes
    if any(k in data for k in ("commodities", "region_lat", "region_lon")):
        _store_embedding(db, group)

    db.commit()
    db.refresh(group)
    membership = _get_membership(db, group_id, user_id)
    return _build_group_out(group, membership)


def update_permissions(
    db: Session, group_id: UUID, user_id: UUID, payload: GroupPermissionsUpdate
) -> GroupOut:
    _require_admin(db, group_id, user_id)
    group = _get_group_or_raise(db, group_id)

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(group, field, value)

    db.commit()
    db.refresh(group)
    membership = _get_membership(db, group_id, user_id)
    return _build_group_out(group, membership)


def delete_group(db: Session, group_id: UUID, user_id: UUID) -> None:
    _require_admin(db, group_id, user_id)
    group = _get_group_or_raise(db, group_id)
    try:
        db.delete(group)
        db.commit()
    except Exception:
        db.rollback()
        raise


# ---------------------------------------------------------------------------
# Membership operations
# ---------------------------------------------------------------------------

def join_group(db: Session, group_id: UUID, user_id: UUID) -> dict:
    group = _get_group_or_raise(db, group_id)

    if group.accessibility == "invite_only":
        raise GroupPermissionError("This group is invite-only. Use an invite link.")

    existing = _get_membership(db, group_id, user_id)
    if existing:
        raise GroupConflictError("Already a member of this group")

    try:
        db.add(GroupMember(group_id=group_id, user_id=user_id, role="member"))
        group.member_count += 1
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {"role": "member", "joined_at": datetime.now(timezone.utc).isoformat()}


def leave_group(db: Session, group_id: UUID, user_id: UUID) -> None:
    group = _get_group_or_raise(db, group_id)
    membership = _get_membership(db, group_id, user_id)

    if not membership:
        raise GroupNotFoundError("Not a member of this group")

    if membership.role == "admin":
        # Check if there's another admin
        other_admin = (
            db.query(GroupMember)
            .filter(
                GroupMember.group_id == group_id,
                GroupMember.user_id != user_id,
                GroupMember.role == "admin",
            )
            .first()
        )
        if not other_admin:
            raise GroupPermissionError(
                "You are the sole admin. Assign another admin before leaving."
            )

    try:
        db.delete(membership)
        group.member_count = max(0, group.member_count - 1)
        db.commit()
    except Exception:
        db.rollback()
        raise


def get_members(
    db: Session,
    group_id: UUID,
    user_id: UUID,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    _get_group_or_raise(db, group_id)

    memberships = (
        db.query(GroupMember)
        .filter(GroupMember.group_id == group_id)
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    total = db.query(GroupMember).filter(GroupMember.group_id == group_id).count()

    member_ids = [m.user_id for m in memberships]
    profiles = (
        db.query(Profile)
        .options(joinedload(Profile.role))
        .filter(Profile.users_id.in_(member_ids))
        .all()
    )
    profile_map = {p.users_id: p for p in profiles}

    out: list[GroupMemberOut] = []
    for m in memberships:
        p = profile_map.get(m.user_id)
        out.append(
            GroupMemberOut(
                user_id=m.user_id,
                name=p.name if p else "Unknown",
                role_name=p.role.name if p and p.role else "Unknown",
                photo_url=None,
                is_verified=p.is_verified if p else False,
                member_role=m.role,
                is_frozen=m.is_frozen,
                is_muted=m.is_muted,
                joined_at=m.joined_at,
            )
        )

    return {"members": out, "total": total, "page": page, "per_page": per_page}


def add_members(
    db: Session, group_id: UUID, requester_id: UUID, user_ids: list[UUID]
) -> dict:
    _require_admin(db, group_id, requester_id)
    group = _get_group_or_raise(db, group_id)

    added = []
    for uid in user_ids:
        if not _get_membership(db, group_id, uid):
            db.add(GroupMember(group_id=group_id, user_id=uid, role="member"))
            added.append(str(uid))

    group.member_count += len(added)
    db.commit()
    return {"added": added, "count": len(added)}


def remove_member(
    db: Session, group_id: UUID, requester_id: UUID, target_user_id: UUID
) -> None:
    _require_admin(db, group_id, requester_id)
    membership = _get_membership(db, group_id, target_user_id)
    if not membership:
        raise GroupNotFoundError("User is not a member of this group")

    group = _get_group_or_raise(db, group_id)
    try:
        db.delete(membership)
        group.member_count = max(0, group.member_count - 1)
        db.commit()
    except Exception:
        db.rollback()
        raise


def set_member_frozen(
    db: Session,
    group_id: UUID,
    requester_id: UUID,
    target_user_id: UUID,
    frozen: bool,
) -> dict:
    _require_admin(db, group_id, requester_id)
    membership = _get_membership(db, group_id, target_user_id)
    if not membership:
        raise GroupNotFoundError("User is not a member of this group")

    membership.is_frozen = frozen
    db.commit()
    return {"user_id": str(target_user_id), "is_frozen": frozen}


def toggle_mute(db: Session, group_id: UUID, user_id: UUID) -> dict:
    membership = _get_membership(db, group_id, user_id)
    if not membership:
        raise GroupNotFoundError("Not a member of this group")

    membership.is_muted = not membership.is_muted
    db.commit()
    return {"is_muted": membership.is_muted}


def toggle_favorite(db: Session, group_id: UUID, user_id: UUID) -> dict:
    membership = _get_membership(db, group_id, user_id)
    if not membership:
        raise GroupNotFoundError("Not a member of this group")

    membership.is_favorite = not membership.is_favorite
    db.commit()
    return {"is_favorite": membership.is_favorite}


# ---------------------------------------------------------------------------
# Invite link
# ---------------------------------------------------------------------------

def get_or_create_invite_link(
    db: Session, group_id: UUID, user_id: UUID, base_url: str = "https://api.vanijyaa.com"
) -> InviteLinkOut:
    _require_admin(db, group_id, user_id)
    group = _get_group_or_raise(db, group_id)

    if not group.invite_link_token:
        group.invite_link_token = secrets.token_urlsafe(16)
        db.commit()
        db.refresh(group)

    return InviteLinkOut(
        invite_link_token=group.invite_link_token,
        join_url=f"{base_url}/api/v1/groups/join-by-link/{group.invite_link_token}",
    )


def join_by_invite_link(
    db: Session, token: str, user_id: UUID
) -> dict:
    group = db.query(Group).filter(Group.invite_link_token == token).first()
    if not group:
        raise GroupNotFoundError("Invalid or expired invite link")

    existing = _get_membership(db, group.id, user_id)
    if existing:
        raise GroupConflictError("Already a member of this group")

    try:
        db.add(GroupMember(group_id=group.id, user_id=user_id, role="member"))
        group.member_count += 1
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "group_id": str(group.id),
        "group_name": group.name,
        "role": "member",
        "joined_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Group Recommendation Engine
# ---------------------------------------------------------------------------

def get_group_suggestions(
    db: Session,
    user_id: UUID,
    top_k: int = TOP_K,
) -> list[GroupSuggestionOut]:
    """
    Two-stage group recommendation:
      Stage 1 — in-Python cosine similarity between user's WANT vector
                and each group's IS embedding.
      Stage 2 — activity reranking via group_activity_cache.
      Final    — weighted blend (75 % semantic + 25 % activity).
    """
    # ── 1. Load user profile ────────────────────────────────────────────────
    profile = _get_profile_or_raise(db, user_id)

    user_commodities = [pc.commodity.name.lower() for pc in profile.commodities]
    user_role = ROLE_ID_TO_NAME.get(profile.role_id, "trader")

    want_vec = build_query_vector(
        commodity_list=user_commodities,
        role=user_role,
        lat=float(profile.latitude),
        lon=float(profile.longitude),
        qty_min=int(profile.quantity_min),
        qty_max=int(profile.quantity_max),
    )

    # ── 2. Load groups the user is NOT already a member of ─────────────────
    member_group_ids = [
        row[0]
        for row in db.query(GroupMember.group_id)
        .filter(GroupMember.user_id == user_id)
        .all()
    ]

    embeddings = (
        db.query(GroupEmbedding)
        .filter(GroupEmbedding.embedding.isnot(None))
        .all()
    )
    # Exclude groups user is already in
    member_set = set(member_group_ids)
    embeddings = [e for e in embeddings if e.group_id not in member_set]

    if not embeddings:
        return []

    # ── 3. Load groups + activity caches in bulk ────────────────────────────
    group_ids = [e.group_id for e in embeddings]
    groups = {
        g.id: g
        for g in db.query(Group).filter(Group.id.in_(group_ids)).all()
    }
    activities = {
        a.group_id: a
        for a in db.query(GroupActivityCache)
        .filter(GroupActivityCache.group_id.in_(group_ids))
        .all()
    }

    # ── 4. Score each group ─────────────────────────────────────────────────
    scored: list[tuple[float, Group, float, float]] = []
    for emb in embeddings:
        group = groups.get(emb.group_id)
        if group is None or not emb.embedding:
            continue

        # Skip private groups (user isn't a member and wasn't invited)
        if group.accessibility == "private":
            continue

        sim = cosine_similarity(want_vec, emb.embedding)

        cache = activities.get(group.id)
        act = compute_activity_score(
            messages_24h=cache.messages_24h if cache else 0,
            active_members_7d=cache.active_members_7d if cache else 0,
            member_growth_7d=cache.member_growth_7d if cache else 0,
        )

        final = compute_final_score(sim, act)
        scored.append((final, group, sim, act))

    # ── 5. Sort and return top-K ────────────────────────────────────────────
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]

    results: list[GroupSuggestionOut] = []
    for final_score, group, sim, act in top:
        reasons = build_match_reasons(
            user_commodities=user_commodities,
            user_role=user_role,
            group_commodities=group.commodity or [],
            group_target_roles=group.target_roles or [],
            cosine_sim=sim,
            act_score=act,
        )
        results.append(
            GroupSuggestionOut(
                group=_build_group_out(group, None),
                match_score=final_score,
                match_reasons=reasons,
            )
        )

    return results
