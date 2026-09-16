"""
Wave 2 Slice 5 Database Models — Governance: Variances, Waivers & Data Certification
(CF-V2-E13-03, CF-V2-E13-04)

Tracks:
- OperationalVariance: factual deviation from defined controls (DQ, Recon, Drift, Quarantine, SLA).
- OperationalWaiver: formal four-eyes governed administrative exception with mandatory expiration.
- BatchDataCertification: immutable evidence-backed attestation of production batch readiness.
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


class VarianceStatusEnum(str, enum.Enum):
    OPEN = "OPEN"
    WAIVED = "WAIVED"
    RESOLVED = "RESOLVED"


class WaiverStatusEnum(str, enum.Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class WaiverScopeEnum(str, enum.Enum):
    SINGLE_BATCH = "SINGLE_BATCH"
    BATCH_RANGE = "BATCH_RANGE"
    TIME_BOUNDED = "TIME_BOUNDED"


class CertificationStatusEnum(str, enum.Enum):
    CERTIFIED = "CERTIFIED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class OperationalVariance(Base, AuditMixin):
    """
    Factual deviation from an expected operational or data contract/control.
    Recorded when DQ fails, reconciliation fails, schema drift is detected,
    or quarantine records accumulate without resolution.
    """
    __tablename__ = "operational_variances"

    feed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("feeds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    control_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # 'DQ_RULE', 'RECONCILIATION', 'SCHEMA_DRIFT', 'QUARANTINE_ACCUMULATION', 'ARRIVAL_SLA'
    control_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )  # rule_version_id, reconciliation_id, drift_event_id, etc.
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, default="WARNING"
    )  # 'CRITICAL', 'WARNING', 'INFO'
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    telemetry_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    status: Mapped[VarianceStatusEnum] = mapped_column(
        SAEnum(VarianceStatusEnum, name="variance_status_enum", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=VarianceStatusEnum.OPEN,
        index=True,
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Relationships
    feed = relationship("Feed")
    batch = relationship("Batch")
    waivers = relationship("OperationalWaiver", back_populates="variance", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_variances_batch_control", "batch_id", "control_type", "control_id"),
        Index("ix_variances_feed_status", "feed_id", "status"),
    )


class OperationalWaiver(Base, AuditMixin):
    """
    Formal administrative exception granted through dual-control (four-eyes) governance.
    Applies to a specific variance on a batch, strictly bounded in duration and scope.
    Guaranteed zero-PHI.
    """
    __tablename__ = "operational_waivers"

    variance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("operational_variances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    feed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("feeds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scope: Mapped[WaiverScopeEnum] = mapped_column(
        SAEnum(WaiverScopeEnum, name="waiver_scope_enum", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=WaiverScopeEnum.SINGLE_BATCH,
    )
    affected_control_type: Mapped[str] = mapped_column(String(50), nullable=False)
    affected_control_id: Mapped[str] = mapped_column(String(255), nullable=False)

    business_justification: Mapped[str] = mapped_column(Text, nullable=False)
    risk_assessment: Mapped[str] = mapped_column(Text, nullable=False)
    mitigation_notes: Mapped[str] = mapped_column(Text, nullable=False)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    range_start_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("batches.id", ondelete="SET NULL"),
        nullable=True,
    )
    range_end_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("batches.id", ondelete="SET NULL"),
        nullable=True,
    )
    target_batch_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    max_batches: Mapped[int | None] = mapped_column(Integer, nullable=True)
    batches_applied_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[WaiverStatusEnum] = mapped_column(
        SAEnum(WaiverStatusEnum, name="waiver_status_enum", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=WaiverStatusEnum.PENDING_APPROVAL,
        index=True,
    )

    requested_by: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    requested_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    reviewed_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    revoked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    variance = relationship("OperationalVariance", back_populates="waivers")
    feed = relationship("Feed")
    batch = relationship("Batch", foreign_keys=[batch_id])
    range_start_batch = relationship("Batch", foreign_keys=[range_start_batch_id])
    range_end_batch = relationship("Batch", foreign_keys=[range_end_batch_id])

    __table_args__ = (
        Index("ix_waivers_batch_status", "batch_id", "status"),
        Index("ix_waivers_feed_expires", "feed_id", "expires_at"),
        Index(
            "uq_waiver_active_variance",
            "variance_id",
            unique=True,
            postgresql_where=(
                status.in_([WaiverStatusEnum.PENDING_APPROVAL, WaiverStatusEnum.APPROVED])
            ),
        ),
    )


class BatchDataCertification(Base, AuditMixin):
    """
    Immutable attestation of production batch readiness.
    Permanently locks runtime version references, evidence snapshot, and SHA-256 evidence hash.
    Created only after authoritative eligibility evaluation, four-eyes check, and evidence hashing.
    """
    __tablename__ = "batch_data_certifications"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    feed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("feeds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    feed_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("feed_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )

    status: Mapped[CertificationStatusEnum] = mapped_column(
        SAEnum(CertificationStatusEnum, name="certification_status_enum", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
    )
    certified_with_waivers: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    applied_waiver_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    input_file_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    input_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    reconciliation_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    dq_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    evidence_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    certified_by: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    certified_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    certified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    certification_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    revoked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    batch = relationship("Batch")
    feed = relationship("Feed")
    feed_version = relationship("FeedVersion")

    __table_args__ = (
        Index("ix_certifications_feed_batch", "feed_id", "batch_id"),
        Index("ix_certifications_fingerprint", "input_file_fingerprint"),
    )
