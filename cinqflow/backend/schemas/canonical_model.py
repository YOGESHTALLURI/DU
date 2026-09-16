"""
Pydantic schemas for Canonical Models and Canonical Fields (Read-Only Reference Data).
"""
import uuid
from typing import List, Optional
from pydantic import BaseModel, ConfigDict
from backend.models.schema import SchemaDataTypeEnum


class CanonicalFieldResponse(BaseModel):
    id: uuid.UUID
    canonical_model_id: uuid.UUID
    field_name: str
    data_type: SchemaDataTypeEnum
    is_required: bool
    is_nullable: bool
    description: Optional[str] = None
    ordinal_position: int

    model_config = ConfigDict(from_attributes=True)


class CanonicalModelSummary(BaseModel):
    id: uuid.UUID
    name: str
    domain: str
    description: Optional[str] = None
    field_count: int

    model_config = ConfigDict(from_attributes=True)


class CanonicalModelDetail(BaseModel):
    id: uuid.UUID
    name: str
    domain: str
    description: Optional[str] = None
    fields: List[CanonicalFieldResponse] = []

    model_config = ConfigDict(from_attributes=True)
