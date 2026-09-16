"""
Feed Registry API Endpoints — Wave 0
"""
from uuid import UUID
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from backend.core.database import get_db
from backend.core.security import require_engineer, require_analyst_or_engineer, require_any_role, CurrentUser
from backend.services.feed_service import FeedService
from backend.models.feed import FeedStatusEnum
from backend.schemas.feed import (
    FeedCreateRequest,
    FeedUpdateRequest,
    FeedCloneRequest,
    FeedStatusUpdateRequest,
    FeedResponse,
    FeedVersionCreateRequest,
    FeedVersionPublishRequest,
    FeedVersionResponse,
    ValidatePatternRequest,
    ValidatePatternResponse,
)

router = APIRouter()


@router.get("", response_model=List[FeedResponse])
def list_feeds(
    domain: Optional[str] = Query(None),
    status: Optional[FeedStatusEnum] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """List configured feeds."""
    service = FeedService(db)
    items, _ = service.list_feeds(
        domain=domain,
        status_filter=status,
        limit=limit,
        offset=offset,
    )
    result = []
    for f in items:
        resp = FeedResponse.model_validate(f)
        active = f.get_active_version()
        if active:
            resp.active_version = FeedVersionResponse.model_validate(active)
        result.append(resp)
    return result


@router.post("", response_model=FeedResponse, status_code=status.HTTP_201_CREATED)
def create_feed(
    data: FeedCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """Create minimal feed record and initial version (ENGINEER only)."""
    service = FeedService(db)
    feed = service.create_feed(data, actor_id=current_user.user_id, actor_email=current_user.email)
    resp = FeedResponse.model_validate(feed)
    active = feed.get_active_version()
    if active:
        resp.active_version = FeedVersionResponse.model_validate(active)
    return resp


@router.get("/{id}", response_model=FeedResponse)
def get_feed(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Get feed by ID with versions."""
    service = FeedService(db)
    feed = service.get_feed_or_404(id)
    resp = FeedResponse.model_validate(feed)
    active = feed.get_active_version()
    if active:
        resp.active_version = FeedVersionResponse.model_validate(active)
    return resp


@router.put("/{id}", response_model=FeedResponse)
def update_feed(
    id: UUID,
    data: FeedUpdateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """Update feed metadata (ENGINEER only)."""
    service = FeedService(db)
    feed = service.update_feed(id, data, actor_id=current_user.user_id, actor_email=current_user.email)
    resp = FeedResponse.model_validate(feed)
    active = feed.get_active_version()
    if active:
        resp.active_version = FeedVersionResponse.model_validate(active)
    return resp


@router.get("/{id}/versions", response_model=List[FeedVersionResponse])
def list_feed_versions(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Get all versions for a feed."""
    service = FeedService(db)
    feed = service.get_feed_or_404(id)
    return [FeedVersionResponse.model_validate(v) for v in feed.versions]


@router.post("/{id}/versions", response_model=FeedVersionResponse, status_code=status.HTTP_201_CREATED)
def create_feed_version(
    id: UUID,
    data: FeedVersionCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """Create a new version for a feed (ENGINEER only)."""
    service = FeedService(db)
    return service.create_feed_version(
        id, data, actor_id=current_user.user_id, actor_email=current_user.email
    )


@router.post("/{id}/versions/{version_id}/publish", response_model=FeedVersionResponse)
def publish_feed_version(
    id: UUID,
    version_id: UUID,
    data: FeedVersionPublishRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """Publish a feed version (ENGINEER only). Makes this version active and supersedes older ones."""
    service = FeedService(db)
    return service.publish_feed_version(
        id, version_id, data, actor_id=current_user.user_id, actor_email=current_user.email
    )


@router.post("/{id}/validate-pattern", response_model=ValidatePatternResponse)
def validate_filename_pattern(
    id: UUID,
    data: ValidatePatternRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Validate whether a sample filename matches the feed's filename pattern."""
    service = FeedService(db)
    feed = service.get_feed_or_404(id)
    matches = service.validate_pattern(id, data.sample_filename)
    return ValidatePatternResponse(
        feed_id=id,
        pattern=feed.filename_pattern,
        sample_filename=data.sample_filename,
        matches=matches,
    )


@router.post("/{id}/clone", response_model=FeedResponse, status_code=status.HTTP_201_CREATED)
def clone_feed(
    id: UUID,
    data: FeedCloneRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """Clone an existing feed into a new independent feed with strict isolation (Analyst or Engineer)."""
    service = FeedService(db)
    cloned_feed = service.clone_feed(
        id, data, actor_id=current_user.user_id, actor_email=current_user.email
    )
    resp = FeedResponse.model_validate(cloned_feed)
    active = cloned_feed.get_active_version()
    if active:
        resp.active_version = FeedVersionResponse.model_validate(active)
    return resp


@router.put("/{id}/status", response_model=FeedResponse)
def update_feed_status(
    id: UUID,
    data: FeedStatusUpdateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """Update feed lifecycle status with server-side activation validation (Analyst or Engineer)."""
    service = FeedService(db)
    feed = service.transition_feed_status(
        id,
        data.status,
        data.reason,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
        require_mapping=bool(data.require_mapping),
    )
    resp = FeedResponse.model_validate(feed)
    active = feed.get_active_version()
    if active:
        resp.active_version = FeedVersionResponse.model_validate(active)
    return resp