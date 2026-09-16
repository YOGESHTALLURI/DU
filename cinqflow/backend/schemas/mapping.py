"""
Pydantic schemas for Mappings, Mapping Versions, and Mapping Lines — Wave 1 Slice 3.
"""
import uuid
from typing import List, Optional, Any, Dict
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from backend.models.mapping import MappingVersionStatusEnum, TransformTypeEnum


class MappingLineRequest(BaseModel):
    canonical_field_id: uuid.UUID
    source_field_names: List[str] = Field(default_factory=list)
    transform_type: TransformTypeEnum = TransformTypeEnum.DIRECT
    transform_params: Dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None


class MappingLineResponse(BaseModel):
    id: uuid.UUID
    mapping_version_id: uuid.UUID
    canonical_field_id: uuid.UUID
    canonical_field_name: str
    canonical_data_type: str
    canonical_is_required: bool
    canonical_ordinal_position: int
    source_field_names: List[str]
    transform_type: TransformTypeEnum
    transform_params: Dict[str, Any]
    notes: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class MappingCreateRequest(BaseModel):
    feed_id: uuid.UUID
    canonical_model_id: uuid.UUID
    name: Optional[str] = None
    description: Optional[str] = None


class MappingUpdateLinesRequest(BaseModel):
    lines: List[MappingLineRequest]


class MappingPublishRequest(BaseModel):
    change_notes: Optional[str] = None


class MappingNewVersionRequest(BaseModel):
    schema_version_id: Optional[uuid.UUID] = None
    change_notes: Optional[str] = None


class MappingValidationReport(BaseModel):
    is_valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    unmapped_required_canonical_fields: List[str] = Field(default_factory=list)
    unmapped_optional_canonical_fields: List[str] = Field(default_factory=list)
    unmapped_source_fields: List[str] = Field(default_factory=list)


class MappingVersionSummary(BaseModel):
    id: uuid.UUID
    mapping_id: uuid.UUID
    version_number: int
    schema_version_id: uuid.UUID
    schema_version_number: Optional[int] = None
    status: MappingVersionStatusEnum
    change_notes: Optional[str] = None
    published_by: Optional[str] = None
    published_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class MappingVersionDetail(BaseModel):
    id: uuid.UUID
    mapping_id: uuid.UUID
    version_number: int
    schema_version_id: uuid.UUID
    schema_version_number: Optional[int] = None
    status: MappingVersionStatusEnum
    compiled_spec: Optional[Dict[str, Any]] = None
    change_notes: Optional[str] = None
    published_by: Optional[str] = None
    published_at: Optional[datetime] = None
    lines: List[MappingLineResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class MappingResponse(BaseModel):
    id: uuid.UUID
    feed_id: uuid.UUID
    feed_name: str
    schema_id: uuid.UUID
    canonical_model_id: uuid.UUID
    canonical_model_name: str
    name: str
    description: Optional[str] = None
    active_version: Optional[MappingVersionSummary] = None
    draft_version: Optional[MappingVersionSummary] = None
    versions: List[MappingVersionSummary] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class TestStructuralTransformRequest(BaseModel):
    transform_type: TransformTypeEnum
    transform_params: Dict[str, Any] = Field(default_factory=dict)
    source_fields: List[str] = Field(default_factory=list)
    sample_input: Dict[str, Any] = Field(default_factory=dict)


class TestStructuralTransformResponse(BaseModel):
    success: bool
    transform_type: str
    result: Optional[Any] = None
    result_type: Optional[str] = None
    error: Optional[str] = None
