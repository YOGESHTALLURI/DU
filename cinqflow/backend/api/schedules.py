"""
API Router for Feed Schedules (Wave 1 Slice 6 - CF-V1-E8-03).
"""
import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.security import require_engineer, require_any_role, CurrentUser
from backend.schemas.schedule import (
    FeedScheduleCreateRequest,
    FeedScheduleUpdateRequest,
    FeedScheduleResponse,
)
from backend.services.scheduling_service import SchedulingService

router = APIRouter()


@router.get("/feed/{feed_id}", response_model=FeedScheduleResponse)
def get_feed_schedule(
    feed_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Retrieve operational schedule for a feed (any authenticated user)."""
    service = SchedulingService(db)
    sched = service.get_schedule(feed_id)
    return sched


@router.post("/feed/{feed_id}", response_model=FeedScheduleResponse, status_code=status.HTTP_201_CREATED)
def create_feed_schedule(
    feed_id: uuid.UUID,
    payload: FeedScheduleCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """Explicitly create feed operational schedule (ENGINEER only, 409 if exists)."""
    service = SchedulingService(db)
    sched = service.create_schedule(
        feed_id=feed_id,
        schedule_expression=payload.schedule_expression,
        timezone_str=payload.timezone,
        catchup=payload.catchup,
        current_user=current_user,
    )
    return sched


@router.put("/feed/{feed_id}", response_model=FeedScheduleResponse)
def update_feed_schedule(
    feed_id: uuid.UUID,
    payload: FeedScheduleUpdateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """Idempotent upsert: update feed schedule expression or create if missing (ENGINEER only)."""
    service = SchedulingService(db)
    sched = service.update_schedule(
        feed_id=feed_id,
        schedule_expression=payload.schedule_expression,
        timezone_str=payload.timezone,
        catchup=payload.catchup,
        current_user=current_user,
    )
    return sched


@router.post("/feed/{feed_id}/pause", response_model=FeedScheduleResponse)
def pause_feed_schedule(
    feed_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """Pause operational schedule for a feed (ENGINEER only). Delegated to Governed Action Surface."""
    from backend.services.ops_action_service import OpsActionService
    from backend.schemas.ops_action import OpsActionSubmitRequest
    from backend.models.ops_action import ActionTypeEnum

    action_service = OpsActionService(db)
    action_req = OpsActionSubmitRequest(
        action_type=ActionTypeEnum.PAUSE_SCHEDULE,
        target_type="FEED_SCHEDULE",
        target_id=str(feed_id),
        reason="Manual schedule pause via schedules API endpoint",
    )
    action_service.submit_action(action_req, current_user)
    service = SchedulingService(db)
    return service.get_schedule(feed_id)


@router.post("/feed/{feed_id}/resume", response_model=FeedScheduleResponse)
def resume_feed_schedule(
    feed_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """Resume operational schedule for a feed (ENGINEER only). Delegated to Governed Action Surface."""
    from backend.services.ops_action_service import OpsActionService
    from backend.schemas.ops_action import OpsActionSubmitRequest
    from backend.models.ops_action import ActionTypeEnum

    action_service = OpsActionService(db)
    action_req = OpsActionSubmitRequest(
        action_type=ActionTypeEnum.RESUME_SCHEDULE,
        target_type="FEED_SCHEDULE",
        target_id=str(feed_id),
        reason="Manual schedule resume via schedules API endpoint",
    )
    action_service.submit_action(action_req, current_user)
    service = SchedulingService(db)
    return service.get_schedule(feed_id)


@router.post("/feed/{feed_id}/disable", response_model=FeedScheduleResponse)
def disable_feed_schedule(
    feed_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """Permanently disable operational schedule for a feed (ENGINEER only)."""
    service = SchedulingService(db)
    sched = service.disable_schedule(feed_id, current_user)
    return sched


@router.post("/feed/{feed_id}/enable", response_model=FeedScheduleResponse)
def enable_feed_schedule(
    feed_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """Re-enable a disabled operational schedule for a feed (ENGINEER only)."""
    service = SchedulingService(db)
    sched = service.enable_schedule(feed_id, current_user)
    return sched
