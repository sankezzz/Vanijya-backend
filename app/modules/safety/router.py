"""
Safety module — block and report endpoints.

URL convention (matches rest of the codebase):
  {user_id}   — the acting user
  {target_id} — the user being blocked / reported
"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.modules.safety import service
from app.modules.safety.schemas import ReportRequest

router = APIRouter(prefix="/safety", tags=["safety"])


# ── Block ─────────────────────────────────────────────────────────────────────

@router.post("/{user_id}/block/{target_id}")
def block(user_id: UUID, target_id: UUID, db: Session = Depends(get_db)):
    """Block target_id as user_id. Returns 409 if already blocked."""
    return service.block_user(db, blocker_id=user_id, blocked_id=target_id)


@router.delete("/{user_id}/block/{target_id}")
def unblock(user_id: UUID, target_id: UUID, db: Session = Depends(get_db)):
    """Remove a block. Returns 404 if no block exists."""
    return service.unblock_user(db, blocker_id=user_id, blocked_id=target_id)


@router.get("/{user_id}/blocked")
def list_blocked(user_id: UUID, db: Session = Depends(get_db)):
    """All users that user_id has blocked, newest first."""
    blocked = service.list_blocked(db, blocker_id=user_id)
    return {"user_id": str(user_id), "total": len(blocked), "blocked": blocked}


@router.get("/{user_id}/block/status/{target_id}")
def check_block_status(user_id: UUID, target_id: UUID, db: Session = Depends(get_db)):
    """Has user_id blocked target_id? Drives block/unblock button state."""
    return service.block_status(db, blocker_id=user_id, blocked_id=target_id)


# ── Report ────────────────────────────────────────────────────────────────────

@router.post("/{user_id}/report")
def report(user_id: UUID, payload: ReportRequest, db: Session = Depends(get_db)):
    """
    Submit a report for a user, group, or post.
    Returns 409 if you've already reported this target.
    """
    return service.submit_report(db, reporter_id=user_id, payload=payload)


@router.get("/{user_id}/reports")
def my_reports(user_id: UUID, db: Session = Depends(get_db)):
    """All reports submitted by user_id, newest first."""
    reports = service.list_my_reports(db, reporter_id=user_id)
    return {"user_id": str(user_id), "total": len(reports), "reports": reports}
