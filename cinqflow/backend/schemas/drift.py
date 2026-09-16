"""
Wave 2 Slice 1 Pydantic Schemas — Schema Drift Detection (CF-V2-E5-04)
"""
import uuid
from datetime import datetime
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field
from backend.models.drift import DriftSeverityEnum, DriftStatusEnum


class SchemaDriftReportResponse(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    feed_id: uuid.UUID
    expected_schema_version_id: uuid.UUID
    drift_severity: DriftSeverityEnum
    missing_fields: List[str] = Field(default_factory=list)
    unexpected_fields: List[str] = Field(default_factory=list)
    type_mismatches: List[Dict[str, Any]] = Field(default_factory=list)
    detected_delimiter: Optional[str] = None
    status: DriftStatusEnum
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    acknowledgement_notes: Optional[str] = None
    created_at: datetime
    created_by: str

    model_config = {"from_attributes": True}


class SchemaDriftListResponse(BaseModel):
    total: int
    items: List[SchemaDriftReportResponse]


class AcknowledgeDriftRequest(BaseModel):
    notes: str = Field(..., min_length=3, max_length=2000, description="Mandatory justification notes for acknowledging drift")
