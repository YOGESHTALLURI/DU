"""
Reconciliation Pydantic Schemas — Wave 0
"""
from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from backend.models.reconciliation import ReconciliationStatusEnum


class ReconciliationLedgerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    reconciliation_id: UUID
    reason_code: str
    reason_description: str
    row_count: int
    created_at: datetime


class BatchReconciliationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_id: UUID
    rows_in: int
    rows_silver_raw: int
    rows_quarantined: int
    rows_dropped: int
    balance_check_passed: bool
    status: ReconciliationStatusEnum
    discrepancy: int
    created_at: datetime
    ledger_entries: List[ReconciliationLedgerResponse] = []
