"""
Input Registration API Endpoints — Wave 0
"""
from uuid import UUID
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, UploadFile, File, Form, HTTPException, status
from sqlalchemy.orm import Session
from backend.core.database import get_db
from backend.core.security import require_engineer, require_any_role, CurrentUser
from backend.services.input_service import InputService
from backend.models.input_registry import InputStatusEnum
from backend.schemas.pipeline import InputRegisterResponse, BatchResponse, BatchStageResponse

router = APIRouter()


@router.get("", response_model=List[InputRegisterResponse])
def list_inputs(
    feed_id: Optional[UUID] = Query(None),
    status: Optional[InputStatusEnum] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """List registered inputs with status and fingerprint."""
    service = InputService(db)
    items, _ = service.list_inputs(feed_id=feed_id, status_filter=status, limit=limit, offset=offset)
    return [
        InputRegisterResponse(
            id=item.id,
            feed_id=item.feed_id,
            filename=item.filename,
            file_size_bytes=item.file_size_bytes,
            file_fingerprint=item.file_fingerprint,
            status=item.status,
            rejection_reason=item.rejection_reason,
            is_duplicate=False,
        )
        for item in items
    ]


@router.get("/{id}", response_model=InputRegisterResponse)
def get_input(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Get single input registry record."""
    from backend.models.input_registry import InputRegistry
    item = db.query(InputRegistry).filter(InputRegistry.id == id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Input {id} not found")
    return InputRegisterResponse(
        id=item.id,
        feed_id=item.feed_id,
        filename=item.filename,
        file_size_bytes=item.file_size_bytes,
        file_fingerprint=item.file_fingerprint,
        status=item.status,
        rejection_reason=item.rejection_reason,
        is_duplicate=False,
    )


@router.post("/register", response_model=InputRegisterResponse, status_code=status.HTTP_200_OK)
async def register_input_file(
    file: UploadFile = File(...),
    feed_id: Optional[UUID] = Form(None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """
    Register an arriving file with full landing controls:
    fingerprint, duplicate detection, structure validation, batch creation.
    (ENGINEER only).
    """
    service = InputService(db)
    content = await file.read()
    input_entry, batch, is_duplicate = service.register_file(
        filename=file.filename or "unknown.csv",
        content=content,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
        forced_feed_id=feed_id,
    )

    batch_resp = None
    if batch:
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
        batch_resp = BatchResponse(
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

    return InputRegisterResponse(
        id=input_entry.id,
        feed_id=input_entry.feed_id,
        filename=input_entry.filename,
        file_size_bytes=input_entry.file_size_bytes,
        file_fingerprint=input_entry.file_fingerprint,
        status=input_entry.status,
        rejection_reason=input_entry.rejection_reason,
        is_duplicate=is_duplicate,
        batch=batch_resp,
    )