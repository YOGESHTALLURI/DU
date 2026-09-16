"""
Wave 2 Slice 3 Database Models — Governed Action Surface (CF-V2-E12-03)

Tracks operational action requests, risk evaluation, four-eyes approval state machine,
concurrency locks, idempotency keys, and execution telemetry.
"""
import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import (
    String,
    Text,
    Enum as SAEnum,
    Index,
    DateTime,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from backend.models.base import Base, AuditMixin


class ActionTypeEnum(str, enum.Enum):
    RESTART_BATCH = "RESTART_BATCH"
    RETRIGGER_BATCH = "RETRIGGER_BATCH"
    REPROCESS_QUARANTINE = "REPROCESS_QUARANTINE"
    BULK_REPROCESS_QUARANTINE = "BULK_REPROCESS_QUARANTINE"
    DISCARD_QUARANTINE = "DISCARD_QUARANTINE"
    PAUSE_SCHEDULE = "PAUSE_SCHEDULE"
    RESUME_SCHEDULE = "RESUME_SCHEDULE"


class ActionRiskLevelEnum(str, enum.Enum):
    STANDARD = "STANDARD"
    HIGH_RISK = "HIGH_RISK"


class ActionStatusEnum(str, enum.Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class OperationalActionRequest(Base, AuditMixin):
    """
    Central operational action ledger.
    Governs manual recovery, stage restarts, quarantine resolution, and schedule controls.
    Enforces dual-control (four-eyes) governance on high-risk actions.
    """
    __tablename__ = "operational_action_requests"

    action_type: Mapped[ActionTypeEnum] = mapped_column(
        SAEnum(ActionTypeEnum, name="action_type_enum"),
        nullable=False,
        index=True,
    )
    target_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # BATCH, QUARANTINE_RECORD, FEED_SCHEDULE
    target_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    reason: Mapped[str] = mapped_column(Text, nullable=False)  # Mandatory operator rationale, sanitized zero-PHI
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    
    risk_level: Mapped[ActionRiskLevelEnum] = mapped_column(
        SAEnum(ActionRiskLevelEnum, name="action_risk_level_enum"),
        nullable=False,
        default=ActionRiskLevelEnum.STANDARD,
        index=True,
    )
    status: Mapped[ActionStatusEnum] = mapped_column(
        SAEnum(ActionStatusEnum, name="action_status_enum"),
        nullable=False,
        default=ActionStatusEnum.PENDING_APPROVAL,
        index=True,
    )

    requested_by: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    requested_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    reviewed_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    execution_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_ops_action_status_risk", "status", "risk_level"),
        Index("ix_ops_action_target", "target_type", "target_id"),
        Index("ix_ops_action_requester", "requested_by", "action_type"),
    )
