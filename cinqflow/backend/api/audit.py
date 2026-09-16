"""
Audit API Endpoints — Wave 0
"""
from uuid import UUID
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from backend.core.database import get_db
from backend.core.security import require_any_role, CurrentUser
from backend.models.audit import AuditEvent, AuditActionEnum
from backend.schemas.audit import AuditEventResponse

router = APIRouter()


@router.get("/events", response_model=List[AuditEventResponse])
def list_audit_events(
    action: Optional[AuditActionEnum] = Query(None),
    actor_id: Optional[str] = Query(None),
    object_type: Optional[str] = Query(None),
    object_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """
    Search immutable, append-only audit trail.
    Filterable by action, actor, object type, and object ID.
    """
    query = db.query(AuditEvent)
    if action:
        query = query.filter(AuditEvent.action == action)
    if actor_id:
        query = query.filter(AuditEvent.actor_id == actor_id)
    if object_type:
        query = query.filter(AuditEvent.object_type == object_type)
    if object_id:
        query = query.filter(AuditEvent.object_id == object_id)

    events = query.order_by(AuditEvent.created_at.desc()).offset(offset).limit(limit).all()
    return [AuditEventResponse.model_validate(e) for e in events]


@router.get("/events/{id}", response_model=AuditEventResponse)
def get_audit_event(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Get single immutable audit event."""
    event = db.query(AuditEvent).filter(AuditEvent.id == id).first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit event {id} not found",
        )
    return AuditEventResponse.model_validate(event)