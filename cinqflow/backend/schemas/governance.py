"""
Wave 2 Slice 5 Pydantic Schemas — Governance: Variances, Waivers & Data Certification
(CF-V2-E13-03, CF-V2-E13-04)
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict
from backend.models.governance import (
    VarianceStatusEnum,
    WaiverStatusEnum,
    WaiverScopeEnum,
    CertificationStatusEnum,
)


class VarianceCreateRequest(BaseModel):
    feed_id: UUID
    batch_id: UUID
    control_type: str = Field(..., description="DQ_RULE, RECONCILIATION, SCHEMA_DRIFT, QUARANTINE_ACCUMULATION, ARRIVAL_SLA")
    control_id: str = Field(..., description="ID of the affected rule version, reconciliation, or drift event")
    severity: str = Field(default="WARNING", description="CRITICAL, WARNING, INFO")
    title: str = Field(..., min_length=3, max_length=255)
    description: str = Field(..., min_length=5)
    telemetry_snapshot: Dict[str, Any] = Field(default_factory=dict)


class VarianceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    feed_id: UUID
    batch_id: UUID
    control_type: str
    control_id: str
    severity: str
    title: str
    description: str
    telemetry_snapshot: Dict[str, Any]
    status: VarianceStatusEnum
    detected_at: datetime
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    created_at: datetime
    created_by: str


class WaiverSubmitRequest(BaseModel):
    variance_id: UUID
    scope: WaiverScopeEnum = Field(default=WaiverScopeEnum.SINGLE_BATCH)
    business_justification: str = Field(..., min_length=10, description="Mandatory business reason for exception")
    risk_assessment: str = Field(..., min_length=10, description="Mandatory evaluation of operational or clinical risk")
    mitigation_notes: str = Field(..., min_length=10, description="Mitigation or downstream handling notes")
    expires_at: datetime = Field(..., description="Explicit future expiration timestamp (max 30 days)")
    valid_from: Optional[datetime] = Field(default=None, description="Optional start time for temporal/time-bounded validity")
    range_start_batch_id: Optional[UUID] = Field(default=None, description="Starting batch ID for BATCH_RANGE scope")
    range_end_batch_id: Optional[UUID] = Field(default=None, description="Ending batch ID for BATCH_RANGE scope")
    target_batch_ids: Optional[List[UUID]] = Field(default=None, description="Explicit batch IDs for BATCH_RANGE scope")
    max_batches: Optional[int] = Field(default=None, description="Optional batch count cap")


class WaiverReviewRequest(BaseModel):
    decision: str = Field(..., description="APPROVE or REJECT")
    decision_notes: str = Field(..., min_length=5, description="Mandatory rationale for approval or rejection")


class WaiverRevokeRequest(BaseModel):
    revocation_reason: str = Field(..., min_length=5, description="Mandatory reason for revoking waiver")


class WaiverResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    variance_id: UUID
    feed_id: UUID
    batch_id: UUID
    scope: WaiverScopeEnum
    affected_control_type: str
    affected_control_id: str
    business_justification: str
    risk_assessment: str
    mitigation_notes: str
    expires_at: datetime
    valid_from: Optional[datetime] = None
    range_start_batch_id: Optional[UUID] = None
    range_end_batch_id: Optional[UUID] = None
    target_batch_ids: Optional[List[UUID]] = None
    max_batches: Optional[int] = None
    batches_applied_count: int
    status: WaiverStatusEnum
    requested_by: str
    requested_by_email: Optional[str] = None
    requested_at: datetime
    reviewed_by: Optional[str] = None
    reviewed_by_email: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    decision_notes: Optional[str] = None
    revoked_by: Optional[str] = None
    revoked_at: Optional[datetime] = None
    revocation_reason: Optional[str] = None
    created_at: datetime
    is_active: bool = False


class ChecklistItem(BaseModel):
    category: str = Field(..., description="BATCH_STATUS, STAGES, SCHEMA, RECONCILIATION, DATA_QUALITY, QUARANTINE, ALERTS")
    title: str
    passed: bool
    details: str
    waived: bool = False
    waiver_id: Optional[UUID] = None


class CertificationEvaluationResponse(BaseModel):
    batch_id: UUID
    feed_id: UUID
    feed_name: str
    is_eligible: bool
    blocking_reasons: List[str]
    checklist: List[ChecklistItem]
    active_waivers: List[Dict[str, Any]]


class BatchCertifyRequest(BaseModel):
    certification_notes: Optional[str] = Field(default=None, description="Optional certifier remarks or attestation notes")


class BatchCertificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_id: UUID
    feed_id: UUID
    feed_version_id: UUID
    status: CertificationStatusEnum
    certified_with_waivers: bool
    applied_waiver_ids: List[Any]
    input_file_fingerprint: str
    input_filename: str
    total_rows: int
    reconciliation_summary: Dict[str, Any]
    dq_summary: Dict[str, Any]
    evidence_snapshot: Dict[str, Any]
    evidence_hash: str
    certified_by: str
    certified_by_email: Optional[str] = None
    certified_at: datetime
    certification_notes: Optional[str] = None
    revoked_by: Optional[str] = None
    revoked_at: Optional[datetime] = None
    revocation_reason: Optional[str] = None
    created_at: datetime
