"""
Quarantine API Endpoints — Wave 0
"""
from uuid import UUID
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from backend.core.database import get_db
from backend.core.security import require_any_role, CurrentUser
from backend.models.input_registry import QuarantineRecord, QuarantineReasonEnum
from backend.schemas.pipeline import QuarantineRecordResponse

router = APIRouter()


@router.get("", response_model=List[QuarantineRecordResponse])
def list_quarantine_records(
    batch_id: Optional[UUID] = Query(None),
    stage_name: Optional[str] = Query(None),
    reason: Optional[QuarantineReasonEnum] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """List quarantined records with detailed named reasons and raw source values."""
    query = db.query(QuarantineRecord)
    if batch_id:
        query = query.filter(QuarantineRecord.batch_id == batch_id)
    if stage_name:
        query = query.filter(QuarantineRecord.stage_name == stage_name)
    if reason:
        query = query.filter(QuarantineRecord.reason == reason)

    records = query.order_by(QuarantineRecord.created_at.desc()).offset(offset).limit(limit).all()
    return [QuarantineRecordResponse.model_validate(r) for r in records]


@router.get("/{id}", response_model=QuarantineRecordResponse)
def get_quarantine_record(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Get single quarantined record."""
    record = db.query(QuarantineRecord).filter(QuarantineRecord.id == id).first()
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Quarantine record {id} not found",
        )
    return QuarantineRecordResponse.model_validate(record)