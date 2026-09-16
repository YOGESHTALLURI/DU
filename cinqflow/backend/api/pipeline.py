"""
Pipeline Execution API Endpoints — Wave 0
"""
from uuid import UUID
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from backend.core.database import get_db
from backend.core.security import require_engineer, require_any_role, CurrentUser
from backend.models.pipeline import Batch, BatchStage, BatchStatusEnum, StageNameEnum
from backend.schemas.pipeline import BatchResponse, BatchStageResponse
from backend.engine.executor import PipelineExecutor

router = APIRouter()


def _format_batch(batch: Batch) -> BatchResponse:
    stages_resp = [
        BatchStageResponse(
            id=s.id,
            batch_id=s.batch_id,
            stage_name=s.stage_name,
            stage_order=s.stage_order,
            status=s.status,
            started_at=s.started_at,
            completed_at=s.completed_at,
            rows_in=s.rows_in,
            rows_out=s.rows_out,
            rows_quarantined=s.rows_quarantined,
            rows_dropped=s.rows_dropped,
            output_path=s.output_path,
            error_message=s.error_message,
        )
        for s in batch.stages
    ]
    return BatchResponse(
        id=batch.id,
        feed_id=batch.feed_id,
        feed_version_id=batch.feed_version_id,
        input_registry_id=batch.input_registry_id,
        status=batch.status,
        started_at=batch.started_at,
        completed_at=batch.completed_at,
        triggered_by=batch.triggered_by,
        error_message=batch.error_message,
        restart_count=batch.restart_count,
        created_at=batch.created_at,
        stages=stages_resp,
    )


@router.get("/batches", response_model=List[BatchResponse])
def list_batches(
    feed_id: Optional[UUID] = Query(None),
    status: Optional[BatchStatusEnum] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """List execution batches with filters."""
    query = db.query(Batch)
    if feed_id:
        query = query.filter(Batch.feed_id == feed_id)
    if status:
        query = query.filter(Batch.status == status)

    batches = query.order_by(Batch.created_at.desc()).offset(offset).limit(limit).all()
    return [_format_batch(b) for b in batches]


@router.get("/batches/{id}", response_model=BatchResponse)
def get_batch(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Get single batch with stage statuses."""
    batch = db.query(Batch).filter(Batch.id == id).first()
    if not batch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Batch {id} not found")
    return _format_batch(batch)


@router.get("/batches/{id}/stages", response_model=List[BatchStageResponse])
def get_batch_stages(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Get all stage execution records for a batch."""
    stages = (
        db.query(BatchStage)
        .filter(BatchStage.batch_id == id)
        .order_by(BatchStage.stage_order.asc())
        .all()
    )
    return [
        BatchStageResponse(
            id=s.id,
            batch_id=s.batch_id,
            stage_name=s.stage_name,
            stage_order=s.stage_order,
            status=s.status,
            started_at=s.started_at,
            completed_at=s.completed_at,
            rows_in=s.rows_in,
            rows_out=s.rows_out,
            rows_quarantined=s.rows_quarantined,
            rows_dropped=s.rows_dropped,
            output_path=s.output_path,
            error_message=s.error_message,
        )
        for s in stages
    ]


@router.post("/batches/{id}/execute", response_model=BatchResponse)
def execute_batch_endpoint(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """Execute pipeline batch (ENGINEER only)."""
    batch = db.query(Batch).filter(Batch.id == id).first()
    if not batch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Batch {id} not found")

    # Downstream Protection Pre-flight Gate Check (Wave 1 Slice 6)
    from backend.services.dependency_service import DependencyService
    dep_service = DependencyService(db)
    gate_result = dep_service.evaluate_execution_gate(
        feed_id=batch.feed_id,
        audit_on_block=True,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
    )
    if not gate_result.is_allowed:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail=f"Downstream protection gate blocked execution: {'; '.join(gate_result.blocking_reasons)}",
        )

    executor = PipelineExecutor(db)
    batch = executor.execute_batch(
        batch_id=id,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
    )
    return _format_batch(batch)


@router.post("/batches/{id}/restart", response_model=BatchResponse)
def restart_batch_endpoint(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """
    Restart a failed batch from the first non-completed stage (ENGINEER only).
    Delegates to the Governed Action Surface (CF-V2-E12-03, CF-V2-E8-04).
    """
    from backend.services.ops_action_service import OpsActionService
    from backend.schemas.ops_action import OpsActionSubmitRequest
    from backend.models.ops_action import ActionTypeEnum

    action_service = OpsActionService(db)
    action_req = OpsActionSubmitRequest(
        action_type=ActionTypeEnum.RESTART_BATCH,
        target_type="BATCH",
        target_id=str(id),
        reason="Manual operational restart via pipeline endpoint",
    )
    action_service.submit_action(action_req, current_user)
    batch = db.query(Batch).filter(Batch.id == id).first()
    return _format_batch(batch)