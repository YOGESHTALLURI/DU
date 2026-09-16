"""
Canonical ODS API — Wave 3 Slice 2 (CF-V3-E10-01, CF-V3-E10-02)

Provides endpoints for managing ODS canonical model versions, publication immutability,
and downstream consumer data contract registrations.
"""
import uuid
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from backend.core.database import get_db
from backend.core.security import CurrentUser, require_analyst_or_engineer, require_any_role, require_steward
from backend.schemas.ods import (
    OdsModelVersionCreate,
    OdsModelVersionPublish,
    OdsModelVersionResponse,
    ConsumerRegistrationCreate,
    ConsumerRegistrationUpdate,
    ConsumerRegistrationResponse,
    OdsCertifyBatchRequest,
    OdsCertificationResponse,
    OdsBatchEligibilityResponse,
)
from backend.services.ods_service import OdsService
from backend.services.ods_certification_service import OdsCertificationService

router = APIRouter()


# ---------------------------------------------------------------------------
# ODS Model Versions Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/model-versions",
    response_model=OdsModelVersionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create ODS Model Version Draft",
)
def create_ods_model_version(
    data: OdsModelVersionCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """Creates a new draft ODS canonical model specification."""
    return OdsService.create_model_version(db=db, data=data, user_id=current_user.email)


@router.get(
    "/model-versions",
    response_model=List[OdsModelVersionResponse],
    summary="List ODS Model Versions",
)
def list_ods_model_versions(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Lists all ODS canonical model versions ordered by version_number descending."""
    return OdsService.get_model_versions(db=db)


@router.get(
    "/model-versions/{version_id}",
    response_model=OdsModelVersionResponse,
    summary="Get ODS Model Version Details",
)
def get_ods_model_version(
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Retrieves full details of a specific ODS model version by ID."""
    return OdsService.get_model_version(db=db, version_id=version_id)


@router.post(
    "/model-versions/{version_id}/publish",
    response_model=OdsModelVersionResponse,
    summary="Publish ODS Model Version",
)
def publish_ods_model_version(
    version_id: uuid.UUID,
    data: Optional[OdsModelVersionPublish] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """
    Publishes an ODS model version.
    Once published, the schema definition becomes immutable.
    """
    change_notes = data.change_notes if data else None
    return OdsService.publish_model_version(
        db=db, version_id=version_id, user_id=current_user.email, change_notes=change_notes
    )


# ---------------------------------------------------------------------------
# Downstream Consumer Registrations Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/consumers",
    response_model=ConsumerRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register Downstream Consumer",
)
def register_consumer(
    data: ConsumerRegistrationCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """Registers a downstream consumer application or analytics persona for an ODS model version."""
    return OdsService.register_consumer(db=db, data=data, user_id=current_user.email)


@router.get(
    "/consumers",
    response_model=List[ConsumerRegistrationResponse],
    summary="List Registered Consumers",
)
def list_consumers(
    status: Optional[str] = Query(None, description="Optional status filter: ACTIVE, SUSPENDED, DECOMMISSIONED"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Lists all registered downstream consumers with optional status filtering."""
    return OdsService.list_consumers(db=db, status_filter=status)


@router.get(
    "/consumers/{consumer_id}",
    response_model=ConsumerRegistrationResponse,
    summary="Get Consumer Registration Details",
)
def get_consumer(
    consumer_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Retrieves a single downstream consumer contract registration."""
    return OdsService.get_consumer(db=db, consumer_id=consumer_id)


@router.put(
    "/consumers/{consumer_id}",
    response_model=ConsumerRegistrationResponse,
    summary="Update Consumer Registration",
)
@router.patch(
    "/consumers/{consumer_id}",
    response_model=ConsumerRegistrationResponse,
    summary="Update Consumer Registration",
)
def update_consumer(
    consumer_id: uuid.UUID,
    data: ConsumerRegistrationUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """Updates contact or status for a downstream consumer registration."""
    return OdsService.update_consumer(
        db=db, consumer_id=consumer_id, data=data, user_id=current_user.email
    )


@router.post(
    "/consumer-gate/{consumer_name}/batches/{batch_id}",
    summary="Evaluate Consumer Gate Compatibility",
)
def check_consumer_gate(
    consumer_name: str,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """
    Evaluates whether a registered consumer is authorized to read a materialized batch.
    Enforces that consumer.registered_ods_model_version_id == batch.ods_model_version_id.
    """
    return OdsService.validate_consumer_gate(db=db, consumer_name=consumer_name, batch_id=batch_id)


# ---------------------------------------------------------------------------
# ODS Batch Certification Endpoints (CF-V3-E10-03)
# ---------------------------------------------------------------------------

@router.post(
    "/certify",
    response_model=OdsCertificationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Certify or Reject ODS Batch",
)
def certify_batch(
    request: OdsCertifyBatchRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_steward),
):
    """
    Authoritative Data Steward certification or rejection of a completed ODS batch.
    Enforces Four-Eyes segregation (batch creator cannot certify) and Zero-PHI notes.
    """
    return OdsCertificationService.certify_batch(
        db=db, request=request, steward_user=current_user.email
    )


@router.get(
    "/certifications",
    response_model=List[OdsCertificationResponse],
    summary="List ODS Batch Certifications",
)
def list_certifications(
    status: Optional[str] = Query(None, description="Optional status filter: PENDING, CERTIFIED, FAILED"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Lists all ODS batch certifications with optional status filtering."""
    return OdsCertificationService.list_certifications(db=db, status_filter=status)


@router.get(
    "/certifications/{batch_id}",
    response_model=OdsCertificationResponse,
    summary="Get ODS Batch Certification",
)
def get_certification(
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Retrieves ODS certification details for a specific batch."""
    cert = OdsCertificationService.get_certification(db=db, batch_id=batch_id)
    if not cert:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Certification for batch {batch_id} not found.",
        )
    return cert


@router.get(
    "/batches/{batch_id}/eligibility",
    response_model=OdsBatchEligibilityResponse,
    summary="Get ODS Batch Certification Eligibility",
)
def get_batch_eligibility(
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """
    Evaluates prerequisites for ODS batch certification (Identity SUCCESS, published model version, etc.).
    """
    return OdsCertificationService.evaluate_batch_eligibility(db=db, batch_id=batch_id)
