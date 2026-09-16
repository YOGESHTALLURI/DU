"""
Pydantic Schemas for Identity Merge & Split Proposals (CF-V3-E9-03)
"""
import uuid
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict


class MergeProposalCreateRequest(BaseModel):
    source_cinq_id: uuid.UUID = Field(..., description="Master identity to be merged (will become MERGED)")
    target_cinq_id: uuid.UUID = Field(..., description="Surviving target master identity")
    reason: str = Field(..., min_length=5, max_length=1000, description="Non-PHI operational reason")
    client_key: str = Field(..., min_length=16, max_length=64, description="Idempotency client key")


class SplitProposalCreateRequest(BaseModel):
    source_cinq_id: uuid.UUID = Field(..., description="Master identity containing incorrectly grouped identifier")
    source_system: str = Field(..., min_length=1, max_length=100, description="Source system of identifier")
    source_identifier_hash: str = Field(..., min_length=16, max_length=64, description="HMAC hash of identifier to split")
    target_cinq_id: Optional[uuid.UUID] = Field(None, description="Optional existing identity to attach to; if null, creates new")
    reason: str = Field(..., min_length=5, max_length=1000, description="Non-PHI operational reason")
    client_key: str = Field(..., min_length=16, max_length=64, description="Idempotency client key")


class ProposalActionRequest(BaseModel):
    expected_version: Optional[int] = None
    notes: Optional[str] = Field(None, max_length=1000)


class ProposalRejectRequest(BaseModel):
    reason: str = Field(..., min_length=5, max_length=1000, description="Rejection rationale")


class ProposalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    proposal_id: uuid.UUID
    source_cinq_id: Optional[uuid.UUID] = None
    target_cinq_id: Optional[uuid.UUID] = None
    operation_type: str
    source_system: Optional[str] = None
    source_identifier_hash: Optional[str] = None
    client_key: str
    state: str
    proposer_id: str
    approver_id: Optional[str] = None
    expected_version: Optional[int] = None
    expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: uuid.UUID
    proposal_id: uuid.UUID
    event_type: str
    source_cinq_id: Optional[uuid.UUID] = None
    target_cinq_id: Optional[uuid.UUID] = None
    effective_from: datetime
    effective_to: Optional[datetime] = None
    actor_uuid: uuid.UUID
    created_at: datetime
