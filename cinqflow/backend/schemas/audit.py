"""
Audit Pydantic Schemas — Wave 0
"""
from pydantic import BaseModel, ConfigDict
from typing import Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from backend.models.audit import AuditActionEnum


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    action: AuditActionEnum
    actor_id: str
    actor_email: Optional[str] = None
    object_type: str
    object_id: Optional[str] = None
    before_state: Optional[Dict[str, Any]] = None
    after_state: Optional[Dict[str, Any]] = None
    description: Optional[str] = None
    correlation_id: Optional[str] = None
    created_at: datetime
