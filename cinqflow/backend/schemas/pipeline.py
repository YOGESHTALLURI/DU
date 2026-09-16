"""
Pipeline & Input Pydantic Schemas — Wave 0
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Any, Dict
from uuid import UUID
from datetime import datetime
from backend.models.pipeline import BatchStatusEnum, StageNameEnum, StageStatusEnum
from backend.models.input_registry import InputStatusEnum, QuarantineReasonEnum


class BatchStageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_id: UUID
    stage_name: StageNameEnum
    stage_order: int
    status: StageStatusEnum
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    rows_in: Optional[int] = None
    rows_out: Optional[int] = None
    rows_quarantined: Optional[int] = None
    rows_dropped: Optional[int] = None
    output_path: Optional[str] = None
    error_message: Optional[str] = None


class BatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    feed_id: UUID
    feed_version_id: UUID
    input_registry_id: Optional[UUID] = None
    status: BatchStatusEnum
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    triggered_by: str
    error_message: Optional[str] = None
    restart_count: int
    created_at: datetime
    stages: List[BatchStageResponse] = []


class InputRegisterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[UUID] = None
    feed_id: Optional[UUID] = None
    filename: str
    file_size_bytes: int
    file_fingerprint: str
    status: InputStatusEnum
    rejection_reason: Optional[str] = None
    is_duplicate: bool = False
    batch: Optional[BatchResponse] = None


class QuarantineRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_id: UUID
    stage_name: str
    source_row_number: Optional[int] = None
    source_record_raw: Optional[str] = None
    field_name: Optional[str] = None
    field_value: Optional[str] = None
    reason: QuarantineReasonEnum
    reason_detail: Optional[str] = None
    created_at: datetime
