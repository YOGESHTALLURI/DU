"""
Wave 2 Slice 1 Pydantic Schemas — Production Data Quality Execution (CF-V2-E7-05)
"""
import uuid
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
from backend.models.dq_result import DQActionTakenEnum
from backend.models.rule import RuleSeverityEnum, RuleTypeEnum


class DQResultResponse(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    stage_id: uuid.UUID
    rule_version_id: uuid.UUID
    rule_name: Optional[str] = None
    rule_type: Optional[RuleTypeEnum] = None
    severity: Optional[RuleSeverityEnum] = None
    total_rows_evaluated: int
    passed_rows: int
    failed_rows: int
    pass_rate: float
    action_taken: DQActionTakenEnum
    execution_duration_ms: int
    created_at: datetime

    model_config = {"from_attributes": True}


class DQResultListResponse(BaseModel):
    total: int
    items: List[DQResultResponse]


class DQBatchRuleItem(BaseModel):
    rule_id: uuid.UUID
    rule_version_id: uuid.UUID
    rule_name: str
    rule_type: RuleTypeEnum
    severity: RuleSeverityEnum
    total_rows_evaluated: int
    passed_rows: int
    failed_rows: int
    pass_rate: float
    action_taken: DQActionTakenEnum
    execution_duration_ms: int


class DQBatchSummaryResponse(BaseModel):
    batch_id: uuid.UUID
    total_rules_executed: int
    total_rows_evaluated: int
    total_violations: int
    has_quarantined_rows: bool
    has_reject_file_violation: bool
    batch_action: str
    rules: List[DQBatchRuleItem] = Field(default_factory=list)
