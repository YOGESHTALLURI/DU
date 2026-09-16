"""
Contract Register Pydantic Schemas — Wave 0
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from backend.models.contract import ContractStatusEnum, UnknownStatusEnum, RiskLevelEnum


class UnknownCreateRequest(BaseModel):
    description: str = Field(..., min_length=5, description="Description of the unconfirmed production assumption")
    risk_level: RiskLevelEnum = Field(default=RiskLevelEnum.MEDIUM)
    resolution_notes: Optional[str] = None


class UnknownUpdateRequest(BaseModel):
    description: Optional[str] = None
    risk_level: Optional[RiskLevelEnum] = None
    status: Optional[UnknownStatusEnum] = None
    resolution_notes: Optional[str] = None


class ConfirmUnknownRequest(BaseModel):
    resolution_notes: str = Field(..., min_length=3, description="Details of how this unknown was confirmed")


class UnknownResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    contract_entry_id: UUID
    description: str
    risk_level: RiskLevelEnum
    status: UnknownStatusEnum
    resolution_notes: Optional[str] = None
    confirmed_by: Optional[str] = None
    created_at: datetime
    created_by: str


class ContractCreateRequest(BaseModel):
    source_system: str = Field(..., min_length=2, description="Source system name, e.g. 'HEALTH_PLAN_SOURCE'")
    target_domain: str = Field(..., min_length=2, description="Target domain, e.g. 'MEMBERSHIP'")
    description: str = Field(..., min_length=5)
    data_owner: str = Field(..., min_length=2)
    story_id: Optional[str] = None
    notes: Optional[str] = None


class ContractUpdateRequest(BaseModel):
    description: Optional[str] = None
    data_owner: Optional[str] = None
    status: Optional[ContractStatusEnum] = None
    story_id: Optional[str] = None
    notes: Optional[str] = None


class ContractResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_system: str
    target_domain: str
    description: str
    data_owner: str
    status: ContractStatusEnum
    story_id: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str
    version: int
    unknowns: List[UnknownResponse] = []


class RiskViewUnknownItem(BaseModel):
    id: UUID
    contract_id: UUID
    source_system: str
    target_domain: str
    description: str
    risk_level: RiskLevelEnum
    status: UnknownStatusEnum


class RiskViewResponse(BaseModel):
    total_unknowns: int
    open_unknowns: int
    by_risk_level: dict
    unknowns: List[RiskViewUnknownItem]
