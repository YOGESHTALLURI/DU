"""
Wave 2 Slice 5 API Router — Governance: Variances, Waivers & Batch Data Certification
(CF-V2-E13-03, CF-V2-E13-04)
"""
import uuid
from typing import Optional, List
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.security import (
    CurrentUser,
    get_current_user,
    require_steward_or_engineer,
    require_analyst_steward_or_engineer,
    require_any_role,
)
from backend.models.governance import (
    VarianceStatusEnum,
    WaiverStatusEnum,
)
from backend.schemas.governance import (
    VarianceCreateRequest,
    VarianceResponse,
    WaiverSubmitRequest,
    WaiverReviewRequest,
    WaiverRevokeRequest,
    WaiverResponse,
    CertificationEvaluationResponse,
    BatchCertifyRequest,
    BatchCertificationResponse,
)
from backend.services.variance_waiver_service import VarianceWaiverService
from backend.services.certification_service import CertificationService


router = APIRouter()


# -----------------------------------------------------------------------------
# Variances
# -----------------------------------------------------------------------------

@router.get("/variances", response_model=List[VarianceResponse], tags=["Governance"])
def list_variances(
    feed_id: Optional[uuid.UUID] = Query(None),
    batch_id: Optional[uuid.UUID] = Query(None),
    status: Optional[VarianceStatusEnum] = Query(None),
    control_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    variances = VarianceWaiverService.list_variances(
        db=db,
        feed_id=feed_id,
        batch_id=batch_id,
        status_filter=status,
        control_type=control_type,
    )
    return variances


@router.get("/variances/{id}", response_model=VarianceResponse, tags=["Governance"])
def get_variance(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    return VarianceWaiverService.get_variance(db=db, variance_id=id)


@router.post("/variances", response_model=VarianceResponse, status_code=status.HTTP_201_CREATED, tags=["Governance"])
def record_variance(
    req: VarianceCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_steward_or_engineer),
):
    variance = VarianceWaiverService.record_variance(
        db=db,
        feed_id=req.feed_id,
        batch_id=req.batch_id,
        control_type=req.control_type,
        control_id=req.control_id,
        severity=req.severity,
        title=req.title,
        description=req.description,
        telemetry_snapshot=req.telemetry_snapshot,
        user_id=current_user.user_id,
        user_email=current_user.email,
    )
    db.commit()
    return variance


# -----------------------------------------------------------------------------
# Waivers
# -----------------------------------------------------------------------------

@router.get("/waivers", response_model=List[WaiverResponse], tags=["Governance"])
def list_waivers(
    feed_id: Optional[uuid.UUID] = Query(None),
    batch_id: Optional[uuid.UUID] = Query(None),
    status: Optional[WaiverStatusEnum] = Query(None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    waivers = VarianceWaiverService.list_waivers(
        db=db,
        feed_id=feed_id,
        batch_id=batch_id,
        status_filter=status,
    )
    res = []
    for w in waivers:
        item = WaiverResponse.model_validate(w)
        item.is_active = VarianceWaiverService.is_waiver_active(w)
        res.append(item)
    return res


@router.get("/waivers/{id}", response_model=WaiverResponse, tags=["Governance"])
def get_waiver(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    from backend.models.governance import OperationalWaiver
    from fastapi import HTTPException
    waiver = db.query(OperationalWaiver).filter(OperationalWaiver.id == id).first()
    if not waiver:
        raise HTTPException(status_code=404, detail=f"Waiver '{id}' not found")
    item = WaiverResponse.model_validate(waiver)
    item.is_active = VarianceWaiverService.is_waiver_active(waiver)
    return item


@router.post("/waivers", response_model=WaiverResponse, status_code=status.HTTP_201_CREATED, tags=["Governance"])
def request_waiver(
    req: WaiverSubmitRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_steward_or_engineer),
):
    waiver = VarianceWaiverService.request_waiver(db=db, req=req, current_user=current_user)
    db.commit()
    item = WaiverResponse.model_validate(waiver)
    item.is_active = VarianceWaiverService.is_waiver_active(waiver)
    return item


@router.post("/waivers/{id}/review", response_model=WaiverResponse, tags=["Governance"])
def review_waiver(
    id: uuid.UUID,
    req: WaiverReviewRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_steward_or_engineer),
):
    waiver = VarianceWaiverService.review_waiver(
        db=db,
        waiver_id=id,
        decision=req.decision,
        decision_notes=req.decision_notes,
        current_user=current_user,
    )
    db.commit()
    item = WaiverResponse.model_validate(waiver)
    item.is_active = VarianceWaiverService.is_waiver_active(waiver)
    return item


@router.post("/waivers/{id}/revoke", response_model=WaiverResponse, tags=["Governance"])
def revoke_waiver(
    id: uuid.UUID,
    req: WaiverRevokeRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_steward_or_engineer),
):
    waiver = VarianceWaiverService.revoke_waiver(
        db=db,
        waiver_id=id,
        revocation_reason=req.revocation_reason,
        current_user=current_user,
    )
    db.commit()
    item = WaiverResponse.model_validate(waiver)
    item.is_active = VarianceWaiverService.is_waiver_active(waiver)
    return item


# -----------------------------------------------------------------------------
# Batch Data Certification
# -----------------------------------------------------------------------------

@router.get("/batches/{id}/certification-evaluation", response_model=CertificationEvaluationResponse, tags=["Governance"])
def evaluate_batch_certification(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    evaluation = CertificationService.evaluate_batch_certification(db=db, batch_id=id)
    return evaluation


@router.post("/batches/{id}/certify", response_model=BatchCertificationResponse, status_code=status.HTTP_201_CREATED, tags=["Governance"])
def certify_batch(
    id: uuid.UUID,
    req: BatchCertifyRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_steward_or_engineer),
):
    cert = CertificationService.certify_batch(
        db=db,
        batch_id=id,
        current_user=current_user,
        certification_notes=req.certification_notes,
    )
    db.commit()
    return cert


@router.get("/batches/{id}/certification", response_model=Optional[BatchCertificationResponse], tags=["Governance"])
def get_batch_certification(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    cert = CertificationService.get_batch_certification(db=db, batch_id=id)
    return cert


@router.get("/certifications/{id}", response_model=BatchCertificationResponse, tags=["Governance"])
def get_certification(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    cert = CertificationService.get_certification(db=db, certification_id=id)
    return cert


@router.post("/certifications/{id}/revoke", response_model=BatchCertificationResponse, tags=["Governance"])
def revoke_certification(
    id: uuid.UUID,
    req: WaiverRevokeRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_steward_or_engineer),
):
    cert = CertificationService.revoke_certification(
        db=db,
        certification_id=id,
        current_user=current_user,
        revocation_reason=req.revocation_reason,
    )
    db.commit()
    return cert
