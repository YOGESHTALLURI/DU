"""
Wave 2 Slice 4 Database Models — Incidents, Failure Fingerprints, Playbooks & Operational Alerts
(CF-V2-E12-04, CF-V2-E12-05)

Tracks normalized, zero-PHI failure signatures, advisory recovery playbooks,
active-alert deduplication to suppress alert storms, and occurrence telemetry.
"""
import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import (
    String,
    Text,
    Integer,
    Boolean,
    ForeignKey,
    DateTime,
    Enum as SAEnum,
    UniqueConstraint,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.models.base import Base, AuditMixin
from backend.models.ops_action import ActionTypeEnum


class FailureCategoryEnum(str, enum.Enum):
    SCHEMA_DRIFT = "SCHEMA_DRIFT"
    DATA_QUALITY = "DATA_QUALITY"
    STAGE_EXECUTION = "STAGE_EXECUTION"
    RECONCILIATION = "RECONCILIATION"
    DEPENDENCY_GATE = "DEPENDENCY_GATE"
    NETWORK_STORAGE = "NETWORK_STORAGE"
    SYSTEM_TIMEOUT = "SYSTEM_TIMEOUT"


class AlertStatusEnum(str, enum.Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RECOVERY_IN_PROGRESS = "RECOVERY_IN_PROGRESS"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"


class AlertSeverityEnum(str, enum.Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


class PlaybookStatusEnum(str, enum.Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    DEPRECATED = "DEPRECATED"


class FailureFingerprint(Base, AuditMixin):
    """
    Deterministic, normalized failure signature.
    Identical root-cause failures produce identical SHA-256 hashes.
    Guaranteed zero-PHI.
    """
    __tablename__ = "failure_fingerprints"

    category: Mapped[FailureCategoryEnum] = mapped_column(
        SAEnum(FailureCategoryEnum, name="failure_category_enum", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
    )
    failure_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    root_cause_pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_signature: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    total_occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    alerts = relationship("OperationalAlert", back_populates="fingerprint")
    playbook_bindings = relationship("FingerprintPlaybookBinding", back_populates="fingerprint", cascade="all, delete-orphan")


class RecoveryPlaybook(Base, AuditMixin):
    """
    Standard Operating Procedure (SOP) providing advisory recovery steps for failure modes.
    Has versioned, immutable instruction records.
    """
    __tablename__ = "recovery_playbooks"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[FailureCategoryEnum] = mapped_column(
        SAEnum(FailureCategoryEnum, name="failure_category_enum", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
    )
    playbook_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    status: Mapped[PlaybookStatusEnum] = mapped_column(
        SAEnum(PlaybookStatusEnum, name="playbook_status_enum", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=PlaybookStatusEnum.DRAFT,
    )

    versions = relationship(
        "RecoveryPlaybookVersion",
        back_populates="playbook",
        foreign_keys="[RecoveryPlaybookVersion.playbook_id]",
        cascade="all, delete-orphan",
    )
    current_version = relationship(
        "RecoveryPlaybookVersion",
        foreign_keys=[current_version_id],
        primaryjoin="RecoveryPlaybook.current_version_id == RecoveryPlaybookVersion.id",
        post_update=True,
    )


class RecoveryPlaybookVersion(Base, AuditMixin):
    """
    Immutable versioned snapshot of recovery playbook procedures, suggested action type,
    parameter templates, and safety prerequisites.
    """
    __tablename__ = "recovery_playbook_versions"
    __table_args__ = (
        UniqueConstraint("playbook_id", "version_number", name="uq_playbook_version"),
    )

    playbook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recovery_playbooks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    explanation_template: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_action_type: Mapped[ActionTypeEnum | None] = mapped_column(
        SAEnum(ActionTypeEnum, name="action_type_enum", values_callable=lambda x: [e.value for e in x]),
        nullable=True,
    )
    action_parameters_template: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    manual_steps_markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    prerequisites: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    risk_assessment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[PlaybookStatusEnum] = mapped_column(
        SAEnum(PlaybookStatusEnum, name="playbook_status_enum", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=PlaybookStatusEnum.DRAFT,
    )

    playbook = relationship(
        "RecoveryPlaybook",
        foreign_keys=[playbook_id],
        back_populates="versions",
    )


class FingerprintPlaybookBinding(Base, AuditMixin):
    """
    Links a failure fingerprint to one or more recovery playbooks by priority.
    """
    __tablename__ = "fingerprint_playbook_bindings"
    __table_args__ = (
        UniqueConstraint("fingerprint_id", "playbook_id", name="uq_fingerprint_playbook_binding"),
    )

    fingerprint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("failure_fingerprints.id", ondelete="CASCADE"),
        nullable=False,
    )
    playbook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recovery_playbooks.id", ondelete="CASCADE"),
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    fingerprint = relationship("FailureFingerprint", back_populates="playbook_bindings")
    playbook = relationship("RecoveryPlaybook")


class OperationalAlert(Base, AuditMixin):
    """
    Self-explaining operational alert.
    Deduplicated per active feed and fingerprint to suppress alert storms.
    """
    __tablename__ = "operational_alerts"

    feed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("feeds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("batches.id", ondelete="SET NULL"),
        nullable=True,
    )
    failure_fingerprint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("failure_fingerprints.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    recommended_playbook_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recovery_playbook_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[AlertSeverityEnum] = mapped_column(
        SAEnum(AlertSeverityEnum, name="alert_severity_enum", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
    )
    status: Mapped[AlertStatusEnum] = mapped_column(
        SAEnum(AlertStatusEnum, name="alert_status_enum", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=AlertStatusEnum.OPEN,
        index=True,
    )
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    last_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    feed = relationship("Feed")
    batch = relationship("Batch")
    fingerprint = relationship("FailureFingerprint", back_populates="alerts")
    recommended_playbook_version = relationship("RecoveryPlaybookVersion")
    occurrences = relationship("AlertOccurrence", back_populates="alert", cascade="all, delete-orphan", order_by="desc(AlertOccurrence.occurred_at)")


class AlertOccurrence(Base, AuditMixin):
    """
    Individual failure event tied to an operational alert.
    Tracks chronological timeline of recurring errors under storm suppression.
    """
    __tablename__ = "alert_occurrences"

    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("operational_alerts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("batches.id", ondelete="SET NULL"),
        nullable=True,
    )
    stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    alert = relationship("OperationalAlert", back_populates="occurrences")
