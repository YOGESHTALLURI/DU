"""
Wave 2 Slice 3 Pydantic Schemas — Governed Action Surface & Recovery Operations (CF-V2-E8-04, CF-V2-E12-03)
"""
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from backend.models.ops_action import ActionTypeEnum, ActionRiskLevelEnum, ActionStatusEnum
from backend.models.input_registry import QuarantineStatusEnum


class OpsActionSubmitRequest(BaseModel):
    action_type: ActionTypeEnum
    target_type: str = Field(..., description="Entity type: BATCH, QUARANTINE_RECORD, FEED_SCHEDULE")
    target_id: str = Field(..., description="Target entity ID / UUID")
    reason: str = Field(..., min_length=5, description="Mandatory operator rationale for audit logging")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Action parameters")
    idempotency_key: Optional[str] = Field(None, max_length=64, description="Client-generated key to prevent duplicate execution")


class OpsActionReviewRequest(BaseModel):
    decision_notes: Optional[str] = Field(None, description="Operator decision notes / rationale")


class OpsActionResponse(BaseModel):
    id: uuid.UUID
    action_type: ActionTypeEnum
    target_type: str
    target_id: str
    parameters: Dict[str, Any]
    reason: str
    idempotency_key: Optional[str]
    risk_level: ActionRiskLevelEnum
    status: ActionStatusEnum
    requires_approval: bool
    requested_by: str
    requested_by_email: Optional[str]
    requested_at: datetime
    reviewed_by: Optional[str]
    reviewed_by_email: Optional[str]
    reviewed_at: Optional[datetime]
    decision_notes: Optional[str]
    execution_result: Optional[Dict[str, Any]]
    error_message: Optional[str]

    model_config = {"from_attributes": True}


class OpsActionListResponse(BaseModel):
    total: int
    items: List[OpsActionResponse]


class QuarantineActionRequest(BaseModel):
    record_ids: List[uuid.UUID] = Field(..., min_length=1, description="Quarantine record IDs to process")
    reason: str = Field(..., min_length=5, description="Mandatory operator reason")
