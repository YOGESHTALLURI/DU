"""
Wave 1 Slice 7 Pydantic Schemas — Enterprise Business Glossary & Canonical Semantics
"""
import uuid
from datetime import datetime
from typing import List, Optional, Dict
from pydantic import BaseModel, Field, ConfigDict

from backend.models.glossary import (
    GlossaryTermStatusEnum,
    GlossaryPhiClassificationEnum,
    GlossaryCodeSetEnum,
)


class CanonicalFieldLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    link_id: uuid.UUID
    canonical_field_id: uuid.UUID
    canonical_field_name: str
    canonical_model_id: uuid.UUID
    canonical_model_name: str
    data_type: str
    is_required: bool
    is_nullable: bool


class GlossaryTermBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=255, description="Official business term name")
    acronym: Optional[str] = Field(None, max_length=50, description="Common abbreviation or acronym")
    synonyms: List[str] = Field(default_factory=list, description="Alternative names or aliases")
    domain: str = Field(..., min_length=2, max_length=100, description="Healthcare domain")
    definition: str = Field(..., min_length=5, description="Clear business and clinical definition")
    clinical_context: Optional[str] = Field(None, description="Healthcare/operational context and guidelines")
    data_steward: Optional[str] = Field(None, max_length=255, description="Designated data steward/owner")
    phi_classification: GlossaryPhiClassificationEnum = GlossaryPhiClassificationEnum.NONE
    code_set: GlossaryCodeSetEnum = GlossaryCodeSetEnum.NONE


class GlossaryTermCreate(GlossaryTermBase):
    canonical_field_ids: List[uuid.UUID] = Field(
        default_factory=list,
        description="Optional list of canonical fields to associate at creation time"
    )


class GlossaryTermUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    acronym: Optional[str] = Field(None, max_length=50)
    synonyms: Optional[List[str]] = None
    domain: Optional[str] = Field(None, min_length=2, max_length=100)
    definition: Optional[str] = Field(None, min_length=5)
    clinical_context: Optional[str] = None
    data_steward: Optional[str] = None
    phi_classification: Optional[GlossaryPhiClassificationEnum] = None
    code_set: Optional[GlossaryCodeSetEnum] = None


class GlossaryTermDeprecateRequest(BaseModel):
    deprecation_reason: str = Field(..., min_length=3, description="Mandatory reason for retiring term")
    replaced_by_term_id: Optional[uuid.UUID] = Field(None, description="Optional pointer to replacement term")


class LinkCanonicalFieldRequest(BaseModel):
    canonical_field_id: uuid.UUID = Field(..., description="UUID of the canonical field to link")


class GlossaryTermResponse(GlossaryTermBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    normalized_name: str
    status: GlossaryTermStatusEnum
    deprecation_reason: Optional[str] = None
    replaced_by_term_id: Optional[uuid.UUID] = None
    linked_canonical_fields_count: int = 0
    linked_canonical_fields: List[CanonicalFieldLinkResponse] = Field(default_factory=list)
    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str
    version: int


class GlossarySearchResponse(BaseModel):
    total: int
    items: List[GlossaryTermResponse]
    domains: List[str]
    phi_counts: Dict[str, int]
    status_counts: Dict[str, int]
