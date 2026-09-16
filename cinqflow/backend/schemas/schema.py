from typing import List, Optional, Any
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from backend.models.schema import (
    SchemaDataTypeEnum,
    SchemaVersionStatusEnum,
    ProfilingRunStatusEnum,
)


# === Sample Files ===
class SampleFileUploadResponse(BaseModel):
    id: UUID
    feed_id: UUID
    filename: str
    storage_path: str
    file_size_bytes: int
    file_fingerprint: str
    mime_type: str
    uploaded_by: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class SampleFileListResponse(BaseModel):
    items: List[SampleFileUploadResponse]
    total: int


# === Profiling Runs ===
class ProfilingColumnStatResponse(BaseModel):
    id: UUID
    column_name: str
    ordinal_position: int
    inferred_type: SchemaDataTypeEnum
    null_count: int
    null_percentage: float
    distinct_count: int
    distinct_percentage: float
    min_value: Optional[str] = None
    max_value: Optional[str] = None
    sample_values: Optional[List[Any]] = None
    detected_date_patterns: Optional[List[Any]] = None
    model_config = ConfigDict(from_attributes=True)


class ProfilingRunResponse(BaseModel):
    id: UUID
    feed_id: UUID
    sample_file_id: UUID
    status: ProfilingRunStatusEnum
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    row_count: Optional[int] = None
    column_count: Optional[int] = None
    profiling_summary: Optional[dict] = None
    error_message: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ProfilingRunDetailResponse(ProfilingRunResponse):
    column_stats: List[ProfilingColumnStatResponse] = []


# === Schema Contracts & Fields ===
class SchemaFieldBase(BaseModel):
    field_name: str
    ordinal_position: int
    data_type: SchemaDataTypeEnum
    is_nullable: bool = True
    is_required: bool = False
    format_pattern: Optional[str] = None
    description: Optional[str] = None
    source_metadata: Optional[dict] = None


class SchemaFieldCreate(SchemaFieldBase):
    pass


class SchemaFieldResponse(SchemaFieldBase):
    id: UUID
    schema_version_id: UUID
    model_config = ConfigDict(from_attributes=True)


class SchemaCreateRequest(BaseModel):
    feed_id: UUID
    name: str
    description: Optional[str] = None
    source_profiling_run_id: Optional[UUID] = None
    initial_fields: Optional[List[SchemaFieldCreate]] = None


class SchemaVersionResponse(BaseModel):
    id: UUID
    schema_id: UUID
    version_number: int
    status: SchemaVersionStatusEnum
    change_notes: Optional[str] = None
    source_profiling_run_id: Optional[UUID] = None
    source_sample_file_id: Optional[UUID] = None
    published_by: Optional[str] = None
    published_at: Optional[datetime] = None
    created_at: datetime
    fields: List[SchemaFieldResponse] = []
    model_config = ConfigDict(from_attributes=True)


class SchemaResponse(BaseModel):
    id: UUID
    feed_id: UUID
    name: str
    description: Optional[str] = None
    created_at: datetime
    active_version: Optional[SchemaVersionResponse] = None
    draft_version: Optional[SchemaVersionResponse] = None
    model_config = ConfigDict(from_attributes=True)


class SchemaDraftUpdateRequest(BaseModel):
    change_notes: Optional[str] = None
    fields: List[SchemaFieldCreate]


class SchemaPublishRequest(BaseModel):
    change_notes: Optional[str] = None
