"""
Mappings API — Wave 1 Slice 3: Mapping Studio Foundation

Provides endpoints for creating, editing, validating, publishing, and versioning
source-to-canonical data mappings.
"""
import uuid
from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from backend.core.database import get_db
from backend.core.security import CurrentUser, require_analyst_or_engineer, require_any_role
from backend.schemas.mapping import (
    MappingCreateRequest,
    MappingUpdateLinesRequest,
    MappingPublishRequest,
    MappingNewVersionRequest,
    MappingValidationReport,
    MappingResponse,
    MappingVersionDetail,
    TestStructuralTransformRequest,
    TestStructuralTransformResponse,
)
from backend.services.mapping_service import MappingService

router = APIRouter()


@router.get("/feed/{feed_id}", response_model=List[MappingResponse])
def get_mappings_for_feed(
    feed_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """List all mappings for a specific feed."""
    service = MappingService(db)
    return service.get_mappings_for_feed(feed_id)


@router.post("", response_model=MappingResponse, status_code=status.HTTP_201_CREATED)
def create_mapping(
    data: MappingCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """
    Create a new mapping draft for a feed + canonical model.
    Enforces uniqueness: at most one mapping per (feed_id, canonical_model_id).
    READ_ONLY role is rejected with 403 Forbidden.
    """
    service = MappingService(db)
    return service.create_mapping(
        data=data,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
    )


@router.get("/{id}", response_model=MappingResponse)
def get_mapping(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Get mapping details by ID including version history."""
    service = MappingService(db)
    mapping = service.get_mapping_by_id(id)
    return service._serialize_mapping(mapping)


@router.get("/{id}/versions/{version_id}", response_model=MappingVersionDetail)
def get_mapping_version(
    id: uuid.UUID,
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Get mapping version details with all lines."""
    service = MappingService(db)
    return service.get_version_detail(mapping_id=id, version_id=version_id)


@router.put("/{id}/versions/{version_id}/lines", response_model=MappingVersionDetail)
def update_mapping_lines(
    id: uuid.UUID,
    version_id: uuid.UUID,
    data: MappingUpdateLinesRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """
    Update mapping lines in DRAFT status.
    Returns 400 if the version is already PUBLISHED.
    READ_ONLY role is rejected with 403 Forbidden.
    """
    service = MappingService(db)
    return service.update_draft_lines(
        mapping_id=id,
        version_id=version_id,
        data=data,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
    )


@router.post("/{id}/versions/{version_id}/validate", response_model=MappingValidationReport)
def validate_mapping_version(
    id: uuid.UUID,
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """
    Run server-side validation against all 7 transforms and required canonical completeness.
    Advisory check; callable by all roles including READ_ONLY.
    """
    service = MappingService(db)
    return service.validate_mapping_version(mapping_id=id, version_id=version_id)


@router.post("/{id}/versions/{version_id}/publish", response_model=MappingVersionDetail)
def publish_mapping_version(
    id: uuid.UUID,
    version_id: uuid.UUID,
    data: MappingPublishRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """
    Publish mapping version, compile deterministic spec, and lock immutability.
    Authoritative server-side validation runs before publishing.
    READ_ONLY role is rejected with 403 Forbidden.
    """
    service = MappingService(db)
    return service.publish_mapping_version(
        mapping_id=id,
        version_id=version_id,
        data=data,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
    )


@router.post("/{id}/versions", response_model=MappingVersionDetail, status_code=status.HTTP_201_CREATED)
def spawn_new_mapping_version(
    id: uuid.UUID,
    data: MappingNewVersionRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """
    Spawn a new independent DRAFT version (e.g. v2) inheriting lines from the latest version.
    The previous version remains untouched and immutable.
    READ_ONLY role is rejected with 403 Forbidden.
    """
    service = MappingService(db)
    return service.spawn_new_version(
        mapping_id=id,
        data=data,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
    )


@router.post("/test-structural-transform", response_model=TestStructuralTransformResponse)
def test_structural_transform(
    data: TestStructuralTransformRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """
    Test a structural transform (PATH_EXTRACT, EXPLODE, FLATTEN, ARRAY_MAP, UNNEST)
    against a sample JSON/dict payload in real time.
    (BUSINESS_ANALYST or ENGINEER only).
    """
    service = MappingService(db)
    result = service.test_structural_transform(
        transform_type=data.transform_type,
        transform_params=data.transform_params,
        source_fields=data.source_fields,
        sample_input=data.sample_input,
    )
    return result
