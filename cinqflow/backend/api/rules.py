"""
Data Quality Rules API — Wave 1 Slice 4: Deterministic Data Quality Rules Engine

Provides endpoints for creating, editing, validating, testing, publishing,
versioning, and soft-deleting data quality rules.
"""
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from backend.core.database import get_db
from backend.core.security import CurrentUser, require_analyst_or_engineer, require_any_role
from backend.schemas.rule import (
    RuleCreateRequest,
    RuleVersionUpdateRequest,
    RulePublishRequest,
    RuleNewVersionRequest,
    RuleValidationReport,
    RuleResponse,
    RuleVersionDetail,
    RuleTestRunResponse,
)
from backend.services.rule_service import RuleService
from backend.services.dq_service import DQService
from backend.schemas.dq_result import DQResultListResponse, DQBatchSummaryResponse
from backend.models.dq_result import DQActionTakenEnum

router = APIRouter()


@router.get("/executions", response_model=DQResultListResponse)
def list_rule_executions(
    batch_id: Optional[uuid.UUID] = None,
    rule_version_id: Optional[uuid.UUID] = None,
    action_taken: Optional[DQActionTakenEnum] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """List production data quality execution results."""
    service = DQService(db)
    items, total = service.list_executions(
        batch_id=batch_id,
        rule_version_id=rule_version_id,
        action_taken=action_taken,
        limit=limit,
        offset=offset,
    )
    return {"total": total, "items": items}


@router.get("/executions/batch/{batch_id}", response_model=DQBatchSummaryResponse)
def get_batch_dq_summary(
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Get aggregate summary of all DQ rule executions on a batch."""
    service = DQService(db)
    return service.get_batch_summary(batch_id)


@router.get("/feed/{feed_id}", response_model=List[RuleResponse])
def get_rules_for_feed(
    feed_id: uuid.UUID,
    include_deleted: bool = Query(False, description="Include soft-deleted rules"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """List all data quality rules for a specific feed (soft-deleted excluded by default)."""
    service = RuleService(db)
    return service.get_rules_for_feed(feed_id, include_deleted=include_deleted)


@router.post("", response_model=RuleResponse, status_code=status.HTTP_201_CREATED)
def create_rule(
    data: RuleCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """
    Create a new data quality rule and initial v1 DRAFT version.
    Enforces unique name per feed among non-deleted rules.
    READ_ONLY role is rejected with 403 Forbidden.
    """
    service = RuleService(db)
    return service.create_rule(
        data=data,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
    )


@router.get("/{id}", response_model=RuleResponse)
def get_rule(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Get rule details by ID including version history."""
    service = RuleService(db)
    return service.get_rule_detail(id)


@router.get("/{id}/versions/{version_id}", response_model=RuleVersionDetail)
def get_rule_version(
    id: uuid.UUID,
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Get rule version details with rule configuration and latest test run."""
    service = RuleService(db)
    return service.get_version_detail(rule_id=id, version_id=version_id)


@router.put("/{id}/versions/{version_id}", response_model=RuleVersionDetail)
def update_rule_version(
    id: uuid.UUID,
    version_id: uuid.UUID,
    data: RuleVersionUpdateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """
    Update rule version in DRAFT status.
    Returns 400 if version is PUBLISHED or rule is deleted.
    READ_ONLY role is rejected with 403 Forbidden.
    """
    service = RuleService(db)
    return service.update_draft_version(
        rule_id=id,
        version_id=version_id,
        data=data,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
    )


@router.post("/{id}/versions/{version_id}/validate", response_model=RuleValidationReport)
def validate_rule_version(
    id: uuid.UUID,
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """
    Run server-side validation against all 7 rule types and configuration constraints.
    Advisory check; callable by all roles including READ_ONLY.
    """
    service = RuleService(db)
    return service.validate_rule_version(rule_id=id, version_id=version_id)


@router.post("/{id}/versions/{version_id}/test", response_model=RuleTestRunResponse)
def test_rule_version(
    id: uuid.UUID,
    version_id: uuid.UUID,
    sample_id: Optional[uuid.UUID] = Query(None, description="Optional specific sample file ID"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """
    Execute rule against sample CSV rows (up to 10,000 rows).
    ZERO sample/cell values are persisted in database or audit logs.
    READ_ONLY role is rejected with 403 Forbidden.
    """
    service = RuleService(db)
    return service.test_rule_version(
        rule_id=id,
        version_id=version_id,
        sample_id=sample_id,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
    )


@router.post("/{id}/versions/{version_id}/publish", response_model=RuleVersionDetail)
def publish_rule_version(
    id: uuid.UUID,
    version_id: uuid.UUID,
    data: RulePublishRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """
    Publish rule version, compile deterministic spec, and lock immutability.
    Authoritative server-side validation runs before publishing.
    READ_ONLY role is rejected with 403 Forbidden.
    """
    service = RuleService(db)
    return service.publish_rule_version(
        rule_id=id,
        version_id=version_id,
        data=data,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
    )


@router.post("/{id}/versions", response_model=RuleVersionDetail, status_code=status.HTTP_201_CREATED)
def spawn_new_rule_version(
    id: uuid.UUID,
    data: RuleNewVersionRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """
    Spawn a new independent DRAFT version (e.g. v2) inheriting config from the latest version.
    The previous version remains untouched and immutable.
    READ_ONLY role is rejected with 403 Forbidden.
    """
    service = RuleService(db)
    return service.spawn_new_version(
        rule_id=id,
        data=data,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
    )


@router.delete("/{id}", response_model=RuleResponse)
def delete_rule(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """
    Soft-delete a rule (sets is_deleted=TRUE, deleted_at, deleted_by).
    Only permitted if all versions are in DRAFT status.
    READ_ONLY role is rejected with 403 Forbidden.
    """
    service = RuleService(db)
    return service.soft_delete_rule(
        rule_id=id,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
    )
