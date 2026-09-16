"""
Wave 2 Slice 4 Pydantic Schemas — Incidents, Fingerprints, Playbooks & Operational Alerts
(CF-V2-E12-04, CF-V2-E12-05)
"""
from uuid import UUID
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict
from backend.models.incident import (
    FailureCategoryEnum,
    AlertStatusEnum,
    AlertSeverityEnum,
    PlaybookStatusEnum,
)
from backend.models.ops_action import ActionTypeEnum


class FailureFingerprintResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    category: FailureCategoryEnum
    failure_stage: Optional[str] = None
    root_cause_pattern: str
    canonical_signature: str
    fingerprint_hash: str
    total_occurrences: int
    first_seen_at: datetime
    last_seen_at: datetime
    created_at: datetime


class RecoveryPlaybookVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    playbook_id: UUID
    version_number: int
    explanation_template: str
    suggested_action_type: Optional[ActionTypeEnum] = None
    action_parameters_template: Dict[str, Any] = {}
    manual_steps_markdown: str = ""
    prerequisites: List[Any] = []
    risk_assessment: str = ""
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    status: PlaybookStatusEnum
    created_at: datetime


class RecoveryPlaybookResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    category: FailureCategoryEnum
    playbook_code: str
    current_version_id: Optional[UUID] = None
    status: PlaybookStatusEnum
    current_version: Optional[RecoveryPlaybookVersionResponse] = None
    created_at: datetime
    updated_at: datetime


class RecoveryPlaybookCreateRequest(BaseModel):
    title: str
    category: FailureCategoryEnum
    playbook_code: str
    explanation_template: str
    suggested_action_type: Optional[ActionTypeEnum] = None
    action_parameters_template: Dict[str, Any] = {}
    manual_steps_markdown: str = ""
    prerequisites: List[Any] = []
    risk_assessment: str = ""


class RecoveryPlaybookUpdateRequest(BaseModel):
    explanation_template: Optional[str] = None
    suggested_action_type: Optional[ActionTypeEnum] = None
    action_parameters_template: Optional[Dict[str, Any]] = None
    manual_steps_markdown: Optional[str] = None
    prerequisites: Optional[List[Any]] = None
    risk_assessment: Optional[str] = None


class AlertOccurrenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    alert_id: UUID
    batch_id: Optional[UUID] = None
    stage: Optional[str] = None
    error_context: Dict[str, Any] = {}
    occurred_at: datetime


class PlaybookActionProposalResponse(BaseModel):
    action_type: Optional[ActionTypeEnum] = None
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    parameters: Dict[str, Any] = {}
    is_executable: bool = False
    blocking_reason: Optional[str] = None
    risk_level: Optional[str] = None


class OperationalAlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    feed_id: UUID
    feed_name: Optional[str] = None
    batch_id: Optional[UUID] = None
    failure_fingerprint_id: UUID
    recommended_playbook_version_id: Optional[UUID] = None
    title: str
    description: str
    severity: AlertSeverityEnum
    status: AlertStatusEnum
    occurrence_count: int
    first_occurred_at: datetime
    last_occurred_at: datetime
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    resolution_notes: Optional[str] = None
    fingerprint: Optional[FailureFingerprintResponse] = None
    recommended_playbook_version: Optional[RecoveryPlaybookVersionResponse] = None
    occurrences: Optional[List[AlertOccurrenceResponse]] = []
    action_proposal: Optional[PlaybookActionProposalResponse] = None


class PlaybookExecuteResponse(BaseModel):
    alert_id: UUID
    action_id: UUID
    action_type: ActionTypeEnum
    target_type: str
    target_id: str
    risk_level: str
    status: str
    message: str


class AlertAcknowledgeRequest(BaseModel):
    pass


class AlertResolveRequest(BaseModel):
    resolution_notes: Optional[str] = None


class AlertReopenRequest(BaseModel):
    reason: Optional[str] = None

