"""
Feed Registry Pydantic Schemas — Wave 0
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Any, Dict
from uuid import UUID
from datetime import datetime
from backend.models.feed import FeedFormatEnum, FeedStatusEnum, FeedVersionStatusEnum


class FeedCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255, description="Unique feed identifier, e.g. 'MEMBER_DEMO_FEED'")
    domain: str = Field(..., min_length=2, max_length=255, description="Domain, e.g. 'MEMBERSHIP'")
    description: Optional[str] = None
    format: FeedFormatEnum = Field(default=FeedFormatEnum.CSV)
    landing_folder: str = Field(..., min_length=1, description="Relative or absolute landing folder path")
    filename_pattern: str = Field(..., min_length=1, description="Glob pattern, e.g. 'MEMBER_*.csv'")
    schedule_expression: str = Field(default="manual", description="Cron schedule or 'manual'")
    source_system: Optional[str] = None
    data_owner: Optional[str] = None
    sla_expectation: Optional[str] = None
    initial_config: Optional[Dict[str, Any]] = None


class FeedUpdateRequest(BaseModel):
    description: Optional[str] = None
    format: Optional[FeedFormatEnum] = None
    landing_folder: Optional[str] = None
    filename_pattern: Optional[str] = None
    schedule_expression: Optional[str] = None
    source_system: Optional[str] = None
    data_owner: Optional[str] = None
    sla_expectation: Optional[str] = None
    status: Optional[FeedStatusEnum] = None


class FeedCloneRequest(BaseModel):
    new_name: str = Field(..., min_length=2, max_length=255, description="Unique name for the cloned feed")
    new_filename_pattern: Optional[str] = Field(None, min_length=1, description="Optional new pattern; defaults to source feed pattern")
    description: Optional[str] = None


class FeedStatusUpdateRequest(BaseModel):
    status: FeedStatusEnum = Field(..., description="Target lifecycle status")
    reason: Optional[str] = Field(None, description="Optional reason for status change")
    require_mapping: Optional[bool] = Field(False, description="Whether to require a published canonical mapping contract")


class FeedVersionCreateRequest(BaseModel):
    config_snapshot: Dict[str, Any] = Field(..., description="Configuration metadata snapshot")
    change_notes: Optional[str] = None


class FeedVersionPublishRequest(BaseModel):
    change_notes: Optional[str] = None


class FeedVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    feed_id: UUID
    version_number: int
    status: FeedVersionStatusEnum
    config_snapshot: Optional[Dict[str, Any]] = None
    change_notes: Optional[str] = None
    published_by: Optional[str] = None
    created_at: datetime
    created_by: str


class FeedResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    domain: str
    description: Optional[str] = None
    format: FeedFormatEnum
    landing_folder: str
    filename_pattern: str
    schedule_expression: str
    source_system: Optional[str] = None
    data_owner: Optional[str] = None
    sla_expectation: Optional[str] = None
    cloned_from_feed_id: Optional[UUID] = None
    status: FeedStatusEnum
    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str
    version: int
    active_version: Optional[FeedVersionResponse] = None
    versions: List[FeedVersionResponse] = []


class ValidatePatternRequest(BaseModel):
    sample_filename: str = Field(..., min_length=1)


class ValidatePatternResponse(BaseModel):
    feed_id: UUID
    pattern: str
    sample_filename: str
    matches: bool


# === Onboarding Schemas ===
class OnboardingStepUpdateRequest(BaseModel):
    current_step: int = Field(..., ge=1, le=5)
    mark_step_completed: Optional[int] = Field(None, ge=1, le=5)


class OnboardingSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    feed_id: UUID
    current_step: int
    completed_steps: List[int]
    sample_file_id: Optional[UUID] = None
    profiling_run_id: Optional[UUID] = None
    schema_id: Optional[UUID] = None
    status: str
    created_at: datetime
    updated_at: datetime

