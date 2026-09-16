"""
Pydantic Schemas for Wave 1 Slice 6: Scheduling, Dependencies & Downstream Protection (CF-V1-E8-03).
"""
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict
from backend.models.schedule import ScheduleStatusEnum, DependencyTypeEnum


# ---------------------------------------------------------------------------
# Schedule Schemas
# ---------------------------------------------------------------------------

class FeedScheduleCreateRequest(BaseModel):
    schedule_expression: str = Field(default="0 0 * * *", description="Standard 5-part cron expression (e.g. '0 0 * * *')")
    timezone: str = Field(default="UTC", description="Timezone name, e.g. 'UTC', 'America/New_York'")
    catchup: bool = Field(default=False, description="Whether to run missed intervals upon resumption")


class FeedScheduleUpdateRequest(BaseModel):
    schedule_expression: str = Field(..., description="Standard 5-part cron expression (e.g. '0 0 * * *')")
    timezone: str = Field(default="UTC", description="Timezone name, e.g. 'UTC', 'America/New_York'")
    catchup: bool = Field(default=False, description="Whether to run missed intervals upon resumption")


class FeedScheduleResponse(BaseModel):
    id: uuid.UUID
    feed_id: uuid.UUID
    schedule_expression: str
    timezone: str
    status: ScheduleStatusEnum
    next_run_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    catchup: bool
    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str
    version: int

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Dependency Schemas
# ---------------------------------------------------------------------------

class FeedDependencyCreateRequest(BaseModel):
    downstream_feed_id: uuid.UUID = Field(..., description="The dependent feed (child)")
    upstream_feed_id: uuid.UUID = Field(..., description="The prerequisite feed (parent)")
    dependency_type: DependencyTypeEnum = Field(default=DependencyTypeEnum.HARD)
    max_lag_hours: int = Field(default=24, ge=1, le=8760, description="Max allowable hours since upstream completed")
    block_on_upstream_failure: bool = Field(default=True, description="Block downstream if upstream latest batch failed")
    block_on_reject_file: bool = Field(default=True, description="Block downstream if upstream triggered REJECT_FILE DQ violation")
    block_on_unbalanced_reconciliation: bool = Field(default=True, description="Block downstream if upstream reconciliation is unbalanced")
    max_quarantine_rate_pct: Optional[float] = Field(default=5.0, ge=0.0, le=100.0, description="Max quarantine rate percent threshold")
    is_active: bool = Field(default=True)

    @field_validator("upstream_feed_id")
    @classmethod
    def validate_not_self(cls, v, info):
        if "downstream_feed_id" in info.data and v == info.data["downstream_feed_id"]:
            raise ValueError("A feed cannot depend on itself (self-dependency prohibited)")
        return v


class FeedDependencyUpdateRequest(BaseModel):
    dependency_type: Optional[DependencyTypeEnum] = None
    max_lag_hours: Optional[int] = Field(default=None, ge=1, le=8760)
    block_on_upstream_failure: Optional[bool] = None
    block_on_reject_file: Optional[bool] = None
    block_on_unbalanced_reconciliation: Optional[bool] = None
    max_quarantine_rate_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    is_active: Optional[bool] = None


class FeedDependencyResponse(BaseModel):
    id: uuid.UUID
    downstream_feed_id: uuid.UUID
    upstream_feed_id: uuid.UUID
    downstream_feed_name: Optional[str] = None
    upstream_feed_name: Optional[str] = None
    dependency_type: DependencyTypeEnum
    max_lag_hours: int
    block_on_upstream_failure: bool
    block_on_reject_file: bool
    block_on_unbalanced_reconciliation: bool
    max_quarantine_rate_pct: Optional[float] = None
    is_active: bool
    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str
    version: int

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Downstream Protection Gate Check & DAG Schemas
# ---------------------------------------------------------------------------

class DependencyGateItem(BaseModel):
    dependency_id: uuid.UUID
    upstream_feed_id: uuid.UUID
    upstream_feed_name: str
    dependency_type: DependencyTypeEnum
    is_satisfied: bool
    blocking_reason: Optional[str] = None
    warning_reason: Optional[str] = None
    last_upstream_batch_id: Optional[uuid.UUID] = None
    last_upstream_batch_status: Optional[str] = None
    last_upstream_completed_at: Optional[datetime] = None
    quarantine_rate_pct: Optional[float] = None
    reconciliation_status: Optional[str] = None


class GateCheckResult(BaseModel):
    feed_id: uuid.UUID
    feed_name: str
    is_allowed: bool
    evaluated_at: datetime
    blocking_reasons: List[str] = []
    warnings: List[str] = []
    dependencies_evaluated: List[DependencyGateItem] = []


class DAGNode(BaseModel):
    id: str
    feed_id: uuid.UUID
    name: str
    domain: str
    status: str
    schedule_expression: Optional[str] = None
    schedule_status: Optional[str] = None
    next_run_at: Optional[datetime] = None
    is_gate_cleared: bool


class DAGEdge(BaseModel):
    id: str
    source_feed_id: uuid.UUID  # Upstream
    target_feed_id: uuid.UUID  # Downstream
    dependency_type: DependencyTypeEnum
    is_active: bool
    max_lag_hours: int


class DAGGraphResponse(BaseModel):
    nodes: List[DAGNode] = []
    edges: List[DAGEdge] = []
    total_feeds: int
    total_dependencies: int
    is_acyclic: bool = True
