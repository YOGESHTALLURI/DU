"""
Schema Contracts API Endpoints — Wave 1 Slice 1
"""
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.security import (
    require_analyst_or_engineer,
    require_steward_or_engineer,
    require_any_role,
    CurrentUser,
)
from backend.services.schema_service import SchemaService
from backend.services.drift_service import DriftService
from backend.schemas.schema import (
    SchemaCreateRequest,
    SchemaResponse,
    SchemaVersionResponse,
    SchemaDraftUpdateRequest,
    SchemaPublishRequest,
)
from backend.schemas.drift import (
    SchemaDriftReportResponse,
    SchemaDriftListResponse,
    AcknowledgeDriftRequest,
)
from backend.models.drift import DriftSeverityEnum, DriftStatusEnum

router = APIRouter()


@router.get("/drift", response_model=SchemaDriftListResponse)
def list_drift_reports(
    feed_id: Optional[UUID] = None,
    batch_id: Optional[UUID] = None,
    drift_severity: Optional[DriftSeverityEnum] = None,
    drift_status: Optional[DriftStatusEnum] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """List schema drift reports with optional filters."""
    service = DriftService(db)
    items, total = service.list_reports(
        feed_id=feed_id,
        batch_id=batch_id,
        drift_severity=drift_severity,
        drift_status=drift_status,
        limit=limit,
        offset=offset,
    )
    return {"total": total, "items": items}


@router.get("/drift/{report_id}", response_model=SchemaDriftReportResponse)
def get_drift_report(
    report_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Get detail of a specific schema drift report."""
    service = DriftService(db)
    return service.get_report(report_id)


@router.post("/drift/{report_id}/acknowledge", response_model=SchemaDriftReportResponse)
def acknowledge_drift_report(
    report_id: UUID,
    request: AcknowledgeDriftRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_steward_or_engineer),
):
    """
    Acknowledge a non-breaking schema drift report.
    (DATA_STEWARD or ENGINEER only).
    """
    service = DriftService(db)
    return service.acknowledge_report(
        report_id=report_id,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
        notes=request.notes,
    )


@router.post("", response_model=SchemaResponse, status_code=status.HTTP_201_CREATED)
def create_schema(
    request: SchemaCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """
    Create a new schema contract for a feed.
    Can be seeded from a profiling run to establish explicit lineage.
    (BUSINESS_ANALYST or ENGINEER only).
    """
    service = SchemaService(db)
    return service.create_schema(
        request=request,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
    )


@router.get("/feed/{feed_id}", response_model=List[SchemaResponse])
def list_schemas_for_feed(
    feed_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """List all schemas associated with a feed."""
    service = SchemaService(db)
    return service.list_schemas_for_feed(feed_id)


@router.get("/{schema_id}", response_model=SchemaResponse)
def get_schema(
    schema_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Get single schema details including active and draft versions."""
    service = SchemaService(db)
    return service.get_schema(schema_id)


@router.get("/{schema_id}/versions", response_model=List[SchemaVersionResponse])
def get_schema_version_history(
    schema_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Get version history for a schema."""
    service = SchemaService(db)
    schema = service.get_schema(schema_id)
    return schema.versions


@router.get("/{schema_id}/versions/{version_id}", response_model=SchemaVersionResponse)
def get_schema_version(
    schema_id: UUID,
    version_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Get specific schema version and its field contract."""
    service = SchemaService(db)
    return service.get_schema_version(schema_id, version_id)


@router.put("/{schema_id}/versions/{version_id}", response_model=SchemaVersionResponse)
def update_draft_version(
    schema_id: UUID,
    version_id: UUID,
    request: SchemaDraftUpdateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """
    Update field specifications in a DRAFT version.
    Fails with 400 if version is PUBLISHED (immutability).
    (BUSINESS_ANALYST or ENGINEER only).
    """
    service = SchemaService(db)
    return service.update_draft_version(
        schema_id=schema_id,
        version_id=version_id,
        request=request,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
    )


@router.post("/{schema_id}/versions/{version_id}/publish", response_model=SchemaVersionResponse)
def publish_schema_version(
    schema_id: UUID,
    version_id: UUID,
    request: SchemaPublishRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """
    Publish a schema version. Locks it permanently into immutable state.
    (BUSINESS_ANALYST or ENGINEER only).
    """
    service = SchemaService(db)
    return service.publish_schema_version(
        schema_id=schema_id,
        version_id=version_id,
        change_notes=request.change_notes,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
    )


@router.post("/{schema_id}/versions/{version_id}/new-draft", response_model=SchemaVersionResponse, status_code=status.HTTP_201_CREATED)
def create_new_draft_from_version(
    schema_id: UUID,
    version_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """
    Create a new draft version from an existing version (clones fields and increments version number).
    (BUSINESS_ANALYST or ENGINEER only).
    """
    service = SchemaService(db)
    return service.create_new_draft_version(
        schema_id=schema_id,
        source_version_id=version_id,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
    )
