"""
Wave 2 Slice 2 Pydantic Schemas — Operations Control Center & File-Arrival Board (CF-V2-E12-01, CF-V2-E12-02)
"""
import uuid
import enum
from datetime import datetime
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field


class ArrivalStatusEnum(str, enum.Enum):
    EXPECTED = "EXPECTED"
    ON_TIME = "ON_TIME"
    LATE = "LATE"
    MISSED_SLA = "MISSED_SLA"
    PAUSED = "PAUSED"
    UNSCHEDULED_ARRIVAL = "UNSCHEDULED_ARRIVAL"


class OpsKpis(BaseModel):
    active_feeds: int
    batches_24h_total: int
    batches_24h_success: int
    batches_24h_failed: int
    batches_running: int
    sla_attainment_pct: float
    quarantined_rows_24h: int
    unacknowledged_drift_alerts: int
    breaking_drift_count: int
    non_breaking_drift_count: int

    model_config = {"from_attributes": True}


class OpsHomeResponse(BaseModel):
    window_start: datetime
    window_end: datetime
    kpis: OpsKpis

    model_config = {"from_attributes": True}


class OpsArrivalSlotItem(BaseModel):
    slot_id: str
    feed_id: uuid.UUID
    feed_name: str
    domain: str
    timezone: str
    cron_expression: str
    expected_at_utc: datetime
    expected_at_local: str
    sla_deadline_utc: datetime
    sla_deadline_local: str
    actual_arrival_at_utc: Optional[datetime] = None
    status: ArrivalStatusEnum
    delay_minutes: int = 0
    input_registry_id: Optional[uuid.UUID] = None
    filename: Optional[str] = None
    file_fingerprint_preview: Optional[str] = None
    batch_id: Optional[uuid.UUID] = None
    batch_status: Optional[str] = None

    model_config = {"from_attributes": True}


class OpsArrivalBoardResponse(BaseModel):
    horizon: str
    total_slots: int
    on_time_count: int
    late_count: int
    missed_count: int
    expected_count: int
    items: List[OpsArrivalSlotItem] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class OpsStageItem(BaseModel):
    stage_name: str
    stage_order: int
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: int = 0
    rows_in: int = 0
    rows_out: int = 0
    rows_quarantined: int = 0
    rows_dropped: int = 0
    error_message: Optional[str] = None

    model_config = {"from_attributes": True}


class OpsBatchMonitorItem(BaseModel):
    batch_id: uuid.UUID
    feed_id: uuid.UUID
    feed_name: str
    domain: str
    filename: Optional[str] = None
    batch_status: str
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    total_duration_ms: int = 0
    stages: List[OpsStageItem] = Field(default_factory=list)
    dq_action: str = "NO_RULES"
    has_quarantined_rows: bool = False
    has_drift: bool = False
    drift_severity: Optional[str] = None
    reconciliation_status: str = "PENDING"
    error_message: Optional[str] = None

    model_config = {"from_attributes": True}


class OpsMonitorListResponse(BaseModel):
    total: int
    page: int
    limit: int
    items: List[OpsBatchMonitorItem] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class OpsBatchDetailResponse(OpsBatchMonitorItem):
    reconciliation: Optional[Dict[str, Any]] = None
    dq_summary: Optional[Dict[str, Any]] = None
    drift_report: Optional[Dict[str, Any]] = None

    model_config = {"from_attributes": True}
