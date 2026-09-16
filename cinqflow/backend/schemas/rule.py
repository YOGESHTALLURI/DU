"""
Pydantic schemas for Data Quality Rules, Rule Versions, and Test Runs — Wave 1 Slice 4.
Strictly 7 rule types, CUSTOM_SQL is completely excluded.
"""
import uuid
from typing import List, Optional, Any, Dict
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from backend.models.rule import (
    RuleVersionStatusEnum,
    RuleTypeEnum,
    RuleSeverityEnum,
    TestRunStatusEnum,
)


class RuleCreateRequest(BaseModel):
    feed_id: uuid.UUID
    name: str
    target_field: str
    rule_type: RuleTypeEnum
    severity: RuleSeverityEnum = RuleSeverityEnum.QUARANTINE
    rule_config: Dict[str, Any] = Field(default_factory=dict)
    error_message_template: Optional[str] = None
    description: Optional[str] = None
    needs_review: bool = False
    schema_version_id: Optional[uuid.UUID] = None


class RuleVersionUpdateRequest(BaseModel):
    rule_type: Optional[RuleTypeEnum] = None
    target_field: Optional[str] = None
    severity: Optional[RuleSeverityEnum] = None
    rule_config: Optional[Dict[str, Any]] = None
    error_message_template: Optional[str] = None
    change_notes: Optional[str] = None
    needs_review: Optional[bool] = None


class RulePublishRequest(BaseModel):
    change_notes: Optional[str] = None


class RuleNewVersionRequest(BaseModel):
    schema_version_id: Optional[uuid.UUID] = None
    change_notes: Optional[str] = None


class RuleValidationReport(BaseModel):
    is_valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    rule_id: uuid.UUID
    version_id: uuid.UUID
    rule_type: RuleTypeEnum
    target_field: str


class FailedRowDetail(BaseModel):
    row_number: int
    field_name: str
    reason: str


class RuleTestRunResponse(BaseModel):
    id: uuid.UUID
    rule_version_id: uuid.UUID
    sample_id: uuid.UUID
    total_rows: int
    passed_rows: int
    failed_rows: int
    pass_rate: float
    status: TestRunStatusEnum
    error_detail: Optional[str] = None
    failed_row_details: List[FailedRowDetail] = Field(default_factory=list)
    executed_by: str
    executed_at: datetime

    # Transient list populated ONLY for HTTP response with sample preview, never in DB
    transient_sample_failures: Optional[List[Dict[str, Any]]] = None

    model_config = ConfigDict(from_attributes=True)


class RuleVersionSummary(BaseModel):
    id: uuid.UUID
    rule_id: uuid.UUID
    version_number: int
    schema_version_id: uuid.UUID
    schema_version_number: Optional[int] = None
    status: RuleVersionStatusEnum
    rule_type: RuleTypeEnum
    target_field: str
    severity: RuleSeverityEnum
    needs_review: bool
    change_notes: Optional[str] = None
    published_by: Optional[str] = None
    published_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class RuleVersionDetail(BaseModel):
    id: uuid.UUID
    rule_id: uuid.UUID
    version_number: int
    schema_version_id: uuid.UUID
    schema_version_number: Optional[int] = None
    status: RuleVersionStatusEnum
    rule_type: RuleTypeEnum
    target_field: str
    severity: RuleSeverityEnum
    rule_config: Dict[str, Any]
    error_message_template: Optional[str] = None
    change_notes: Optional[str] = None
    compiled_spec: Optional[Dict[str, Any]] = None
    published_by: Optional[str] = None
    published_at: Optional[datetime] = None
    needs_review: bool
    latest_test_run: Optional[RuleTestRunResponse] = None

    model_config = ConfigDict(from_attributes=True)


class RuleResponse(BaseModel):
    id: uuid.UUID
    feed_id: uuid.UUID
    feed_name: Optional[str] = None
    schema_id: uuid.UUID
    name: str
    description: Optional[str] = None
    is_deleted: bool = False
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[str] = None
    active_version: Optional[RuleVersionSummary] = None
    draft_version: Optional[RuleVersionSummary] = None
    versions: List[RuleVersionSummary] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
