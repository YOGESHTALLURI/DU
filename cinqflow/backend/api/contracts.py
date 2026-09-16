"""
Contract Register API Endpoints — Wave 0
"""
from uuid import UUID
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from backend.core.database import get_db
from backend.core.security import require_engineer, require_any_role, CurrentUser
from backend.services.contract_service import ContractService
from backend.models.contract import ContractStatusEnum
from backend.schemas.contract import (
    ContractCreateRequest,
    ContractUpdateRequest,
    ContractResponse,
    UnknownCreateRequest,
    UnknownResponse,
    ConfirmUnknownRequest,
    RiskViewResponse,
)

router = APIRouter()


@router.get("", response_model=List[ContractResponse])
def list_contracts(
    source_system: Optional[str] = Query(None),
    target_domain: Optional[str] = Query(None),
    status: Optional[ContractStatusEnum] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """List execution-plane contract register entries."""
    service = ContractService(db)
    items, _ = service.list_contracts(
        source_system=source_system,
        target_domain=target_domain,
        status_filter=status,
        limit=limit,
        offset=offset,
    )
    return items


@router.get("/risk-view", response_model=RiskViewResponse)
def get_risk_view(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Return rolled-up risk view of all unconfirmed production assumptions."""
    service = ContractService(db)
    return service.get_risk_view()


@router.post("", response_model=ContractResponse, status_code=status.HTTP_201_CREATED)
def create_contract(
    data: ContractCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """Create a new execution-plane contract register entry (ENGINEER only)."""
    service = ContractService(db)
    return service.create_contract(data, actor_id=current_user.user_id, actor_email=current_user.email)


@router.get("/{id}", response_model=ContractResponse)
def get_contract(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Get single contract entry with its unknowns."""
    service = ContractService(db)
    return service.get_contract_or_404(id)


@router.put("/{id}", response_model=ContractResponse)
def update_contract(
    id: UUID,
    data: ContractUpdateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """Update contract entry (ENGINEER only)."""
    service = ContractService(db)
    return service.update_contract(
        id, data, actor_id=current_user.user_id, actor_email=current_user.email
    )


@router.post("/{id}/unknowns", response_model=UnknownResponse, status_code=status.HTTP_201_CREATED)
def add_contract_unknown(
    id: UUID,
    data: UnknownCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """Record an unconfirmed production assumption for a contract (ENGINEER only)."""
    service = ContractService(db)
    return service.add_unknown(
        id, data, actor_id=current_user.user_id, actor_email=current_user.email
    )


@router.put("/unknowns/{id}/confirm", response_model=UnknownResponse)
def confirm_contract_unknown(
    id: UUID,
    data: ConfirmUnknownRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """Confirm a production assumption (ENGINEER only)."""
    service = ContractService(db)
    return service.confirm_unknown(
        id, data, actor_id=current_user.user_id, actor_email=current_user.email
    )