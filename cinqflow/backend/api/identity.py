"""
Wave 3 Slice 3 API Router: Identity Resolution & Steward Console
(CF-V3-E9-01, CF-V3-E9-02)
"""
import uuid
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.security import (
    get_current_user,
    require_steward_or_engineer,
    require_steward,
    require_any_role,
    CurrentUser,
)
from backend.models.identity import (
    IdentityException,
    IdentityCrosswalk,
    IdentityExceptionStatusEnum,
)
from backend.schemas.identity import (
    MatchRecordRequest,
    MatchRecordResponse,
    IdentityExceptionOut,
    ClaimExceptionResponse,
    ResolveExceptionRequest,
    ResolveExceptionResponse,
    CrosswalkEntryOut,
)
from backend.services.identity_service import IdentityService

router = APIRouter()


@router.post("/match", response_model=MatchRecordResponse, status_code=status.HTTP_200_OK)
def match_record(
    request: MatchRecordRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_steward_or_engineer),
):
    """
    Test harness & engine endpoint to evaluate deterministic identity matching.
    Authorized: ENGINEER, DATA_STEWARD.
    """
    return IdentityService.match_record(db, request, actor=current_user.email)


@router.get("/exceptions", response_model=List[IdentityExceptionOut])
def list_exceptions(
    status_filter: Optional[str] = Query(None, alias="status"),
    source_system: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """
    List paginated identity exceptions for steward review.
    Authorized: DATA_STEWARD, ENGINEER, READ_ONLY. Zero raw PHI returned.
    """
    query = db.query(IdentityException)
    if status_filter:
        query = query.filter(IdentityException.status == status_filter)
    if source_system:
        query = query.filter(IdentityException.source_system == source_system)

    offset = (page - 1) * page_size
    return query.order_by(IdentityException.created_at.desc()).offset(offset).limit(page_size).all()


@router.get("/exceptions/{exception_id}", response_model=IdentityExceptionOut)
def get_exception(
    exception_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """
    Get detailed candidate breakdown for a single identity exception.
    Zero raw PHI returned.
    """
    exc = db.query(IdentityException).filter(IdentityException.id == exception_id).first()
    if not exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Identity exception not found")
    return exc


@router.post("/exceptions/{exception_id}/claim", response_model=ClaimExceptionResponse)
def claim_exception(
    exception_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_steward),
):
    """
    Claims an identity exception (transitions status from PENDING to UNDER_REVIEW).
    Authorized: DATA_STEWARD only.
    """
    exc = IdentityService.claim_exception(db, exception_id, steward_email=current_user.email)
    return ClaimExceptionResponse(
        exception_id=exc.id,
        assigned_steward=exc.assigned_steward,
        assigned_at=exc.assigned_at,
        status=exc.status,
    )


@router.post("/exceptions/{exception_id}/resolve", response_model=ResolveExceptionResponse)
def resolve_exception(
    exception_id: uuid.UUID,
    request: ResolveExceptionRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_steward),
):
    """
    Authoritative steward resolution (LINK_EXISTING, CREATE_NEW, or DEFER).
    Authorized: DATA_STEWARD only. Enforces Four-Eyes separation against feed author.
    """
    exc, decision = IdentityService.resolve_exception(
        db=db,
        exception_id=exception_id,
        resolution_type=request.resolution_type,
        target_cinq_id=request.target_cinq_id,
        notes=request.notes,
        steward_email=current_user.email,
        expected_version=request.expected_version,
    )
    return ResolveExceptionResponse(
        exception_id=exc.id,
        status=exc.status,
        resolution_type=exc.resolution_type,
        resolved_cinq_id=exc.resolved_cinq_id,
        decision_id=decision.id,
        evidence_hash=decision.evidence_hash,
        resolved_by=exc.resolved_by,
        resolved_at=exc.resolved_at,
    )


@router.get("/crosswalk/{source_system}/{source_identifier_hash}", response_model=CrosswalkEntryOut)
def get_crosswalk_point_in_time(
    source_system: str,
    source_identifier_hash: str,
    as_of: Optional[datetime] = Query(None, description="ISO-8601 timestamp for historical reconstruction"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """
    Point-in-time crosswalk lookup. Returns active mapping as of specified timestamp.
    """
    cw = IdentityService.lookup_crosswalk_point_in_time(
        db, source_system, source_identifier_hash, as_of=as_of
    )
    if not cw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Crosswalk entry not found for specified system and identifier at this point in time",
        )
    return cw
