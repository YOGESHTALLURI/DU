"""
Wave 1 Slice 5 Pydantic Schemas — Review Packet, Sandbox Runs & Governed Activation
"""
from uuid import UUID
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class SandboxTestRunResponse(BaseModel):
    id: UUID
    feed_id: UUID
    sample_file_id: UUID
    schema_version_id: UUID
    mapping_version_id: UUID
    status: str
    total_rows: int
    passed_rows: int
    quarantined_rows: int
    dropped_rows: int
    pass_rate: float
    reconciliation_status: str
    rule_metrics: Dict[str, Any]
    canonical_sample_preview: List[Dict[str, Any]]
    has_reject_file_violation: bool
    error_message: Optional[str] = None
    execution_duration_ms: int
    executed_by: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApprovalSubmitRequest(BaseModel):
    notes: Optional[str] = Field(None, max_length=2000, description="Notes or context for activation approval")


class ApprovalDecisionRequest(BaseModel):
    decision_notes: Optional[str] = Field(None, max_length=2000, description="Approver review notes or sign-off remarks")


class ApprovalRejectRequest(BaseModel):
    decision_notes: str = Field(..., min_length=3, max_length=2000, description="Mandatory reason for rejection")


class ApprovalRequestResponse(BaseModel):
    id: UUID
    feed_id: UUID
    feed_version_id: UUID
    schema_version_id: UUID
    mapping_version_id: UUID
    sandbox_test_run_id: UUID
    status: str
    submitted_by: str
    submitted_by_email: Optional[str] = None
    submitted_at: datetime
    submission_notes: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_by_email: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    decision_notes: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class FeedActivationResponse(BaseModel):
    feed_id: UUID
    status: str
    activation_record_id: UUID
    activated_by: str
    activated_at: datetime
    decision_notes: Optional[str] = None


class FeedMetadataSummary(BaseModel):
    id: UUID
    name: str
    domain: str
    source_system: Optional[str] = None
    data_owner: Optional[str] = None
    sla_expectation: Optional[str] = None
    landing_folder: str
    filename_pattern: str
    schedule_expression: str
    status: str


class ProfilingSummary(BaseModel):
    sample_file_id: Optional[UUID] = None
    sample_file_name: Optional[str] = None
    total_columns: int = 0
    total_rows: int = 0
    profiled_at: Optional[datetime] = None


class SchemaSummary(BaseModel):
    schema_id: Optional[UUID] = None
    schema_version_id: Optional[UUID] = None
    version_number: Optional[int] = None
    status: Optional[str] = None
    total_fields: int = 0
    required_fields_count: int = 0


class MappingSummary(BaseModel):
    mapping_id: Optional[UUID] = None
    mapping_version_id: Optional[UUID] = None
    version_number: Optional[int] = None
    status: Optional[str] = None
    canonical_model_id: Optional[UUID] = None
    canonical_model_name: Optional[str] = None
    mapped_fields_count: int = 0
    unmapped_fields_count: int = 0
    transform_counts: Dict[str, int] = {}


class RulesSummary(BaseModel):
    active_rules_count: int = 0
    published_rules_count: int = 0
    draft_rules_count: int = 0
    severities: Dict[str, int] = {}
    rule_types: Dict[str, int] = {}
    needs_review_count: int = 0


class ReadinessChecklist(BaseModel):
    step1_metadata_valid: bool
    step2_profiling_complete: bool
    step3_schema_published: bool
    step4_mapping_published: bool
    step4_rules_published: bool
    step5_sandbox_passed: bool
    all_prerequisites_met: bool


class UserCapabilities(BaseModel):
    can_run_test: bool
    can_submit: bool
    can_approve: bool
    can_reject: bool
    is_author: bool
    role_name: str


class ReviewPacketResponse(BaseModel):
    feed_metadata: FeedMetadataSummary
    profiling_summary: ProfilingSummary
    schema_summary: SchemaSummary
    mapping_summary: MappingSummary
    rules_summary: RulesSummary
    latest_sandbox_run: Optional[SandboxTestRunResponse] = None
    readiness_checklist: ReadinessChecklist
    approval_status: Optional[ApprovalRequestResponse] = None
    user_capabilities: UserCapabilities
