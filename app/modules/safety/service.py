"""
Safety service — block and report logic, zero FastAPI imports.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.modules.safety.models import UserBlock, UserReport
from app.modules.safety.schemas import ReportRequest


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------

def block_user(db: Session, blocker_id: UUID, blocked_id: UUID) -> dict:
    if blocker_id == blocked_id:
        raise HTTPException(status_code=400, detail="Cannot block yourself.")
    existing = db.query(UserBlock).filter(
        UserBlock.blocker_id == blocker_id,
        UserBlock.blocked_id == blocked_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="User is already blocked.")
    db.add(UserBlock(blocker_id=blocker_id, blocked_id=blocked_id))
    db.commit()
    return {"status": "blocked", "blocked_id": str(blocked_id)}


def unblock_user(db: Session, blocker_id: UUID, blocked_id: UUID) -> dict:
    row = db.query(UserBlock).filter(
        UserBlock.blocker_id == blocker_id,
        UserBlock.blocked_id == blocked_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Block not found.")
    db.delete(row)
    db.commit()
    return {"status": "unblocked", "blocked_id": str(blocked_id)}


def list_blocked(db: Session, blocker_id: UUID) -> list[dict]:
    rows = (
        db.query(UserBlock)
        .filter(UserBlock.blocker_id == blocker_id)
        .order_by(UserBlock.blocked_at.desc())
        .all()
    )
    return [{"blocked_id": str(r.blocked_id), "blocked_at": r.blocked_at} for r in rows]


def block_status(db: Session, blocker_id: UUID, blocked_id: UUID) -> dict:
    exists = db.query(UserBlock).filter(
        UserBlock.blocker_id == blocker_id,
        UserBlock.blocked_id == blocked_id,
    ).first() is not None
    return {"blocker_id": str(blocker_id), "blocked_id": str(blocked_id), "is_blocked": exists}


def is_blocked(db: Session, blocker_id: UUID, blocked_id: UUID) -> bool:
    """True if blocker_id has blocked blocked_id. Used by other modules."""
    return db.query(UserBlock).filter(
        UserBlock.blocker_id == blocker_id,
        UserBlock.blocked_id == blocked_id,
    ).first() is not None


def either_blocked(db: Session, user_a: UUID, user_b: UUID) -> bool:
    """True if either user has blocked the other. Useful for DM / feed guards."""
    return db.query(UserBlock).filter(
        (
            (UserBlock.blocker_id == user_a) & (UserBlock.blocked_id == user_b)
        ) | (
            (UserBlock.blocker_id == user_b) & (UserBlock.blocked_id == user_a)
        )
    ).first() is not None


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def submit_report(db: Session, reporter_id: UUID, payload: ReportRequest) -> dict:
    if payload.target_type == "user" and reporter_id == payload.target_id:
        raise HTTPException(status_code=400, detail="Cannot report yourself.")
    existing = db.query(UserReport).filter(
        UserReport.reporter_id == reporter_id,
        UserReport.target_type == payload.target_type,
        UserReport.target_id == payload.target_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="You have already reported this.")
    report = UserReport(
        reporter_id=reporter_id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        reason=payload.reason,
        description=payload.description,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return {
        "id": report.id,
        "target_type": report.target_type,
        "target_id": str(report.target_id),
        "reason": report.reason,
        "status": report.status,
        "created_at": report.created_at,
    }


def list_my_reports(db: Session, reporter_id: UUID) -> list[dict]:
    rows = (
        db.query(UserReport)
        .filter(UserReport.reporter_id == reporter_id)
        .order_by(UserReport.created_at.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "target_type": r.target_type,
            "target_id": str(r.target_id),
            "reason": r.reason,
            "status": r.status,
            "created_at": r.created_at,
        }
        for r in rows
    ]
