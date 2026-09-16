"""
Pydantic Schemas for Canonical ODS, Model Versions, and Consumer Registrations (CF-V3-E10-01, CF-V3-E10-02)
"""
import uuid
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, EmailStr, ConfigDict


class OdsModelVersionCreate(BaseModel):
    version_number: int = Field(..., ge=1, description="Sequential version number of the ODS canonical model")
    name: str = Field(..., min_length=1, max_length=100, description="Model version title")
    domain: str = Field("clinical", max_length=50, description="Healthcare domain (clinical, financial, rx)")
    description: Optional[str] = Field(None, description="Detailed change notes or specification description")
    schema_definition: Dict[str, Any] = Field(..., description="Canonical entity and field specifications")


class OdsModelVersionPublish(BaseModel):
    change_notes: Optional[str] = Field(None, description="Formal publication release notes")


class OdsModelVersionResponse(BaseModel):
    id: uuid.UUID
    version_number: int
    name: str
    domain: str
    description: Optional[str] = None
    status: str
    schema_definition: Dict[str, Any]
    published_at: Optional[datetime] = None
    published_by: Optional[str] = None
    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str
    version: int

    model_config = ConfigDict(from_attributes=True)


class ConsumerRegistrationCreate(BaseModel):
    consumer_name: str = Field(..., min_length=1, max_length=100, description="Unique downstream application/system name")
    consumer_type: str = Field(..., description="ANALYTICS_SQL, APPLICATION_API, REPORTING, DATA_WAREHOUSE")
    registered_ods_model_version_id: uuid.UUID = Field(..., description="ODS Model Version ID bound to this consumer")
    contact_email: EmailStr = Field(..., description="Technical or business owner email")
    purpose: Optional[str] = Field(None, description="Business purpose or analytical use case")


class ConsumerRegistrationUpdate(BaseModel):
    status: Optional[str] = Field(None, description="ACTIVE, SUSPENDED, DECOMMISSIONED")
    contact_email: Optional[EmailStr] = None
    purpose: Optional[str] = None


class ConsumerRegistrationResponse(BaseModel):
    id: uuid.UUID
    consumer_name: str
    consumer_type: str
    registered_ods_model_version_id: uuid.UUID
    status: str
    db_role_name: Optional[str] = None
    contact_email: str
    purpose: Optional[str] = None
    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str
    version: int

    model_config = ConfigDict(from_attributes=True)


class OdsMemberResponse(BaseModel):
    cinq_id: uuid.UUID
    batch_id: uuid.UUID
    ods_model_version_id: uuid.UUID
    first_name: str
    last_name: str
    date_of_birth: date
    gender: str
    address_line1: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    survivorship_applied: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OdsClaimLineResponse(BaseModel):
    claim_line_id: uuid.UUID
    claim_id: uuid.UUID
    batch_id: uuid.UUID
    line_number: int
    service_date: date
    procedure_code: str
    allowed_amount: Decimal
    paid_amount: Decimal

    model_config = ConfigDict(from_attributes=True)


class OdsClaimResponse(BaseModel):
    claim_id: uuid.UUID
    cinq_id: uuid.UUID
    batch_id: uuid.UUID
    ods_model_version_id: uuid.UUID
    claim_type: str
    total_charge_amount: Decimal
    claim_date: date
    lines: List[OdsClaimLineResponse] = []

    model_config = ConfigDict(from_attributes=True)


class OdsMemberProvenanceResponse(BaseModel):
    id: uuid.UUID
    cinq_id: uuid.UUID
    batch_id: uuid.UUID
    source_identifier_hash: str
    source_row_id: str
    survivorship_winner: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OdsCertifyBatchRequest(BaseModel):
    batch_id: uuid.UUID = Field(..., description="ID of the batch to certify")
    status: str = Field(..., description="CERTIFIED or FAILED")
    notes: Optional[str] = Field(None, description="Non-PHI certification rationale or steward sign-off notes")


class OdsCertificationResponse(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    ods_model_version_id: uuid.UUID
    status: str
    certified_by: Optional[str] = None
    certified_at: Optional[datetime] = None
    certification_notes: Optional[str] = None
    checklist_snapshot: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str

    model_config = ConfigDict(from_attributes=True)


class OdsBatchEligibilityResponse(BaseModel):
    batch_id: uuid.UUID
    batch_status: str
    batch_created_by: str
    identity_status: Optional[str] = None
    ods_model_version_id: Optional[uuid.UUID] = None
    ods_model_version_number: Optional[int] = None
    ods_model_version_status: Optional[str] = None
    eligible_for_certification: bool
    disqualifying_reasons: List[str] = Field(default_factory=list)
    current_certification: Optional[OdsCertificationResponse] = None
