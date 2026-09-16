"""
Wave 1 Slice 7 API Router — Enterprise Business Glossary & Canonical Semantics (CF-V1-E14-01)
"""
import uuid
from typing import Optional, List
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.security import (
    require_any_role,
    require_analyst_steward_or_engineer,
    require_steward_or_engineer,
    CurrentUser,
)
from backend.models.glossary import (
    GlossaryTermStatusEnum,
    GlossaryPhiClassificationEnum,
    GlossaryCodeSetEnum,
)
from backend.schemas.glossary import (
    GlossarySearchResponse,
    GlossaryTermResponse,
    GlossaryTermCreate,
    GlossaryTermUpdate,
    GlossaryTermDeprecateRequest,
    LinkCanonicalFieldRequest,
    CanonicalFieldLinkResponse,
)
from backend.services.glossary_service import GlossaryService

router = APIRouter()


@router.get("", response_model=GlossarySearchResponse)
def search_glossary_terms(
    query: Optional[str] = Query(None, description="Search across term name, acronym, and definition"),
    domain: Optional[str] = Query(None, description="Filter by healthcare domain"),
    term_status: Optional[GlossaryTermStatusEnum] = Query(None, alias="status", description="Filter by status (DRAFT, APPROVED, DEPRECATED)"),
    phi_classification: Optional[GlossaryPhiClassificationEnum] = Query(None, alias="phi", description="Filter by PHI category"),
    code_set: Optional[GlossaryCodeSetEnum] = Query(None, description="Filter by standard code set"),
    canonical_model_id: Optional[uuid.UUID] = Query(None, description="Filter by associated canonical model"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """
    Search and filter business glossary terms.
    Accessible to all authenticated roles (ENGINEER, DATA_STEWARD, BUSINESS_ANALYST, READ_ONLY).
    """
    service = GlossaryService(db)
    return service.search_terms(
        query=query,
        domain=domain,
        status=term_status,
        phi_classification=phi_classification,
        code_set=code_set,
        canonical_model_id=canonical_model_id,
        skip=skip,
        limit=limit,
    )


@router.get("/canonical/models/{model_id}", response_model=List[GlossaryTermResponse])
def get_terms_for_canonical_model(
    model_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Retrieves all business glossary terms associated with fields in a given canonical reference model."""
    service = GlossaryService(db)
    return service.get_terms_for_canonical_model(model_id)


@router.get("/{term_id}", response_model=GlossaryTermResponse)
def get_glossary_term(
    term_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Retrieves a single business glossary term with all linked canonical fields."""
    service = GlossaryService(db)
    return service.get_term(term_id)


@router.post("", response_model=GlossaryTermResponse, status_code=status.HTTP_201_CREATED)
def create_glossary_term(
    payload: GlossaryTermCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_steward_or_engineer),
):
    """
    Creates a new business glossary term. Defaults to DRAFT status.
    Permitted for ENGINEER, DATA_STEWARD, and BUSINESS_ANALYST.
    """
    service = GlossaryService(db)
    return service.create_term(payload, current_user)


@router.put("/{term_id}", response_model=GlossaryTermResponse)
def update_glossary_term(
    term_id: uuid.UUID,
    payload: GlossaryTermUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_steward_or_engineer),
):
    """
    Updates a glossary term. Modifying approved terms increments version and logs audit state.
    Business analysts are restricted to editing DRAFT terms.
    """
    service = GlossaryService(db)
    return service.update_term(term_id, payload, current_user)


@router.post("/{term_id}/approve", response_model=GlossaryTermResponse)
def approve_glossary_term(
    term_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_steward_or_engineer),
):
    """
    Transitions a glossary term from DRAFT to APPROVED.
    Strictly restricted to DATA_STEWARD and ENGINEER roles.
    """
    service = GlossaryService(db)
    return service.approve_term(term_id, current_user)


@router.post("/{term_id}/deprecate", response_model=GlossaryTermResponse)
def deprecate_glossary_term(
    term_id: uuid.UUID,
    payload: GlossaryTermDeprecateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_steward_or_engineer),
):
    """
    Retires an active glossary term with a mandatory deprecation reason.
    Strictly restricted to DATA_STEWARD and ENGINEER roles.
    """
    service = GlossaryService(db)
    return service.deprecate_term(term_id, payload, current_user)


@router.delete("/{term_id}")
def delete_draft_glossary_term(
    term_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_steward_or_engineer),
):
    """
    Permanently deletes a glossary term ONLY if in DRAFT status.
    Approved terms must be deprecated.
    """
    service = GlossaryService(db)
    return service.delete_draft_term(term_id, current_user)


@router.post("/{term_id}/links", response_model=CanonicalFieldLinkResponse, status_code=status.HTTP_201_CREATED)
def link_canonical_field(
    term_id: uuid.UUID,
    payload: LinkCanonicalFieldRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_steward_or_engineer),
):
    """Links a glossary term to a canonical reference field."""
    service = GlossaryService(db)
    return service.link_canonical_field(term_id, payload.canonical_field_id, current_user)


@router.delete("/{term_id}/links/{canonical_field_id}")
def unlink_canonical_field(
    term_id: uuid.UUID,
    canonical_field_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_steward_or_engineer),
):
    """Removes an association between a glossary term and a canonical reference field."""
    service = GlossaryService(db)
    return service.unlink_canonical_field(term_id, canonical_field_id, current_user)


@router.post("/seed/bootstrap", status_code=status.HTTP_200_OK)
def seed_default_glossary(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_steward_or_engineer),
):
    """Seeds standard healthcare glossary terms and automatically associates them with canonical reference fields."""
    service = GlossaryService(db)
    count = service.seed_default_terms_if_needed()
    return {"message": f"Seeded {count} core healthcare glossary terms", "count": count}
