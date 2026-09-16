"""
Canonical Models API — Wave 1 Slice 3

Strictly READ-ONLY reference routes. No mutation endpoints exist for canonical models.
"""
import uuid
from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.core.database import get_db
from backend.core.security import CurrentUser, require_any_role
from backend.schemas.canonical_model import CanonicalModelSummary, CanonicalModelDetail
from backend.services.canonical_model_service import CanonicalModelService

router = APIRouter()


@router.get("", response_model=List[CanonicalModelSummary])
def list_canonical_models(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """
    List all healthcare canonical reference models (Member, Claim, Encounter, Observation).
    Available to all authenticated roles including READ_ONLY.
    """
    service = CanonicalModelService(db)
    return service.list_models()


@router.get("/{id}", response_model=CanonicalModelDetail)
def get_canonical_model(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """
    Get a canonical model by ID including its ordered attribute definitions.
    Available to all authenticated roles including READ_ONLY.
    """
    service = CanonicalModelService(db)
    return service.get_model(id)
