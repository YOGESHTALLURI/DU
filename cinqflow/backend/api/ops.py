"""
Wave 2 Slice 2 REST API Router — Operations Control Center & File-Arrival Board (CF-V2-E12-01, CF-V2-E12-02)
"""
import uuid
from typing import Optional, List
from fastapi import APIRouter, Depends, Query, status, Response
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.models.user import User
from backend.models.pipeline import BatchStatusEnum, StageStatusEnum
from backend.models.audit import AuditActionEnum
from backend.models.ops_action import (
    OperationalActionRequest,
    ActionTypeEnum,
    ActionStatusEnum,
    ActionRiskLevelEnum,
)
from backend.services.audit_service import AuditService
from backend.services.ops_service import OpsService
from backend.services.ops_action_service import OpsActionService
from backend.schemas.ops import (
    ArrivalStatusEnum,
    OpsHomeResponse,
    OpsArrivalBoardResponse,
    OpsMonitorListResponse,
    OpsBatchDetailResponse,
)
from backend.schemas.ops_action import (
    OpsActionSubmitRequest,
    OpsActionReviewRequest,
    OpsActionResponse,
    OpsActionListResponse,
    QuarantineActionRequest,
)

router = APIRouter()


@router.get("/home", response_model=OpsHomeResponse)
def get_operations_home(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns macro health KPIs for the rolling 24-hour operations window.
    Read-only polling endpoint: zero audit noise generated.
    """
    return OpsService.get_home_kpis(db=db)


@router.get("/arrivals", response_model=OpsArrivalBoardResponse)
def get_file_arrivals_board(
    horizon: Optional[str] = Query("today"),
    window_hours: Optional[int] = Query(None),
    status: Optional[ArrivalStatusEnum] = Query(None),
    feed_id: Optional[uuid.UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns the expected vs actual file arrivals board.
    Calculates expected slots from feed_schedules and matches incoming input_registry files.
    """
    return OpsService.get_arrivals_board(
        db=db,
        horizon=horizon or "today",
        window_hours=window_hours,
        status_filter=status,
        feed_id=feed_id,
    )


@router.get("/monitor", response_model=OpsMonitorListResponse)
def get_batch_stage_monitor(
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    feed_id: Optional[uuid.UUID] = Query(None),
    status: Optional[BatchStatusEnum] = Query(None),
    stage_status: Optional[StageStatusEnum] = Query(None),
    has_violations: Optional[bool] = Query(None),
    time_range: Optional[str] = Query("24h", pattern="^(1h|6h|24h|7d)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns paginated pipeline batches with stage progression, execution duration,
    and DQ/drift indicator summaries.
    """
    return OpsService.get_batch_monitor(
        db=db,
        page=page,
        limit=limit,
        feed_id=feed_id,
        status=status,
        stage_status=stage_status,
        has_violations=has_violations,
        time_range=time_range,
    )


@router.get("/monitor/{batch_id}", response_model=OpsBatchDetailResponse)
def get_batch_stage_detail(
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns deep execution timeline and sanitized error diagnostic detail for a single batch.
    """
    return OpsService.get_batch_detail(db=db, batch_id=batch_id)


@router.post("/session-start", status_code=status.HTTP_200_OK)
def log_operations_dashboard_viewed(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Explicitly logs an ops.dashboard_viewed audit event once per user session
    without flooding the audit trail during periodic REST polling.
    """
    audit = AuditService(db)
    audit.emit(
        action=AuditActionEnum.OPS_DASHBOARD_VIEWED,
        actor_id=str(current_user.user_id),
        actor_email=current_user.email,
        object_type="operations_dashboard",
        object_id="ops_home",
        description=f"Operations dashboard accessed by {current_user.email or current_user.user_id}",
    )
    db.commit()
    return {"status": "ok", "message": "Dashboard view session recorded"}


def _format_action_response(req: OperationalActionRequest) -> OpsActionResponse:
    return OpsActionResponse(
        id=req.id,
        action_type=req.action_type,
        target_type=req.target_type,
        target_id=req.target_id,
        parameters=req.parameters,
        reason=req.reason,
        idempotency_key=req.idempotency_key,
        risk_level=req.risk_level,
        status=req.status,
        requires_approval=(req.status == ActionStatusEnum.PENDING_APPROVAL),
        requested_by=req.requested_by,
        requested_by_email=req.requested_by_email,
        requested_at=req.requested_at,
        reviewed_by=req.reviewed_by,
        reviewed_by_email=req.reviewed_by_email,
        reviewed_at=req.reviewed_at,
        decision_notes=req.decision_notes,
        execution_result=req.execution_result,
        error_message=req.error_message,
    )


@router.post("/actions", response_model=OpsActionResponse)
def submit_operational_action(
    request_data: OpsActionSubmitRequest,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Submit an operational action:
    - Standard actions execute immediately (200 OK).
    - High-risk actions enter PENDING_APPROVAL for Four-Eyes review (202 Accepted).
    """
    action_service = OpsActionService(db)
    action_req = action_service.submit_action(request_data, current_user)
    if action_req.status == ActionStatusEnum.PENDING_APPROVAL:
        response.status_code = status.HTTP_202_ACCEPTED
    else:
        response.status_code = status.HTTP_200_OK
    return _format_action_response(action_req)


@router.get("/actions/pending", response_model=OpsActionListResponse)
def list_pending_operational_actions(
    action_type: Optional[ActionTypeEnum] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List pending high-risk actions awaiting Four-Eyes dual-control approval.
    """
    action_service = OpsActionService(db)
    total, items = action_service.list_pending_actions(
        action_type=action_type,
        limit=limit,
        offset=offset,
    )
    return OpsActionListResponse(
        total=total,
        items=[_format_action_response(item) for item in items],
    )


@router.post("/actions/{id}/approve", response_model=OpsActionResponse)
def approve_operational_action(
    id: uuid.UUID,
    review_data: OpsActionReviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Approve and execute a pending high-risk action.
    Strictly enforces Four-Eyes: requester cannot approve their own action.
    """
    action_service = OpsActionService(db)
    action_req = action_service.approve_action(
        action_id=id,
        decision_notes=review_data.decision_notes,
        current_user=current_user,
    )
    return _format_action_response(action_req)


@router.post("/actions/{id}/reject", response_model=OpsActionResponse)
def reject_operational_action(
    id: uuid.UUID,
    review_data: OpsActionReviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Reject a pending operational action.
    """
    action_service = OpsActionService(db)
    action_req = action_service.reject_action(
        action_id=id,
        decision_notes=review_data.decision_notes,
        current_user=current_user,
    )
    return _format_action_response(action_req)


@router.post("/quarantine/reprocess", response_model=OpsActionResponse)
def reprocess_quarantine_convenience(
    request: QuarantineActionRequest,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Convenience endpoint to reprocess quarantined records.
    Automatically classifies as HIGH_RISK if count > 50.
    """
    action_service = OpsActionService(db)
    action_type = (
        ActionTypeEnum.BULK_REPROCESS_QUARANTINE
        if len(request.record_ids) > 50
        else ActionTypeEnum.REPROCESS_QUARANTINE
    )
    submit_req = OpsActionSubmitRequest(
        action_type=action_type,
        target_type="QUARANTINE_RECORD",
        target_id=str(request.record_ids[0]),
        parameters={"record_ids": [str(rid) for rid in request.record_ids]},
        reason=request.reason,
    )
    action_req = action_service.submit_action(submit_req, current_user)
    if action_req.status == ActionStatusEnum.PENDING_APPROVAL:
        response.status_code = status.HTTP_202_ACCEPTED
    else:
        response.status_code = status.HTTP_200_OK
    return _format_action_response(action_req)


@router.post("/quarantine/discard", response_model=OpsActionResponse)
def discard_quarantine_convenience(
    request: QuarantineActionRequest,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Convenience endpoint to discard quarantined records.
    Always classifies as HIGH_RISK requiring dual-control.
    """
    action_service = OpsActionService(db)
    submit_req = OpsActionSubmitRequest(
        action_type=ActionTypeEnum.DISCARD_QUARANTINE,
        target_type="QUARANTINE_RECORD",
        target_id=str(request.record_ids[0]),
        parameters={"record_ids": [str(rid) for rid in request.record_ids]},
        reason=request.reason,
    )
    action_req = action_service.submit_action(submit_req, current_user)
    if action_req.status == ActionStatusEnum.PENDING_APPROVAL:
        response.status_code = status.HTTP_202_ACCEPTED
    else:
        response.status_code = status.HTTP_200_OK
    return _format_action_response(action_req)
