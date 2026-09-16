"""
Reconciliation API Endpoints — Wave 0
"""
from uuid import UUID
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend.core.database import get_db
from backend.core.security import require_any_role, CurrentUser
from backend.models.reconciliation import BatchReconciliation, ReconciliationLedgerEntry
from backend.schemas.reconciliation import BatchReconciliationResponse, ReconciliationLedgerResponse

router = APIRouter()


@router.get("/batches/{batch_id}", response_model=BatchReconciliationResponse)
def get_batch_reconciliation(
    batch_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Get measurable row count balance for a batch."""
    recon = (
        db.query(BatchReconciliation)
        .filter(BatchReconciliation.batch_id == batch_id)
        .first()
    )
    if not recon:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reconciliation record for batch {batch_id} not found",
        )
    return BatchReconciliationResponse.model_validate(recon)


@router.get("/batches/{batch_id}/ledger", response_model=List[ReconciliationLedgerResponse])
def get_batch_reconciliation_ledger(
    batch_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Get named-reason drop ledger entries for a batch."""
    recon = (
        db.query(BatchReconciliation)
        .filter(BatchReconciliation.batch_id == batch_id)
        .first()
    )
    if not recon:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reconciliation record for batch {batch_id} not found",
        )
    return [ReconciliationLedgerResponse.model_validate(le) for le in recon.ledger_entries]