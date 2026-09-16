"""
Wave 1 Slice 5 Database Models — Sandbox Runs, Approval Requests & Governed Feed Activation

Provides:
- SandboxTestRun: isolated execution test on representative sample data
- ApprovalRequest: formal submission for activation review (Four-Eyes governance)
- FeedActivationRecord: permanent immutable ledger of approved version bundle
"""
import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import (
    String,
    Text,
    Integer,
    Numeric,
    Boolean,
    ForeignKey,
    Enum as SAEnum,
    Index,
    DateTime,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.models.base import Base, AuditMixin


class SandboxRunStatusEnum(str, enum.Enum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class ApprovalRequestStatusEnum(str, enum.Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class SandboxTestRun(Base, AuditMixin):
    """
    Isolated execution of feed pipeline on sample data in sandbox mode.
    Guaranteed zero writes to production batch tables or input registry.
    """
    __tablename__ = "sandbox_test_runs"

    feed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feeds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sample_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sample_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    schema_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("schema_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    mapping_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mapping_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    status: Mapped[SandboxRunStatusEnum] = mapped_column(
        SAEnum(SandboxRunStatusEnum, name="sandbox_run_status_enum"),
        nullable=False,
        default=SandboxRunStatusEnum.RUNNING,
        index=True,
    )

    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quarantined_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dropped_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pass_rate: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0.0)

    reconciliation_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="PENDING"
    )  # BALANCED | UNBALANCED | FAILED

    rule_metrics: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )  # Per-rule breakdown (rows evaluated, failed, severities)

    canonical_sample_preview: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
    )  # Max 5 records, sensitive fields masked

    has_reject_file_violation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    executed_by: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Relationships
    feed = relationship("Feed", foreign_keys=[feed_id])
    sample_file = relationship("SampleFile", foreign_keys=[sample_file_id])
    schema_version = relationship("SchemaVersion", foreign_keys=[schema_version_id])
    mapping_version = relationship("MappingVersion", foreign_keys=[mapping_version_id])


class ApprovalRequest(Base, AuditMixin):
    """
    Tracks formal submission for feed activation review.
    Enforces separation of duties (author != approver).
    """
    __tablename__ = "approval_requests"

    feed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feeds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    feed_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feed_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    schema_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("schema_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    mapping_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mapping_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    sandbox_test_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sandbox_test_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    status: Mapped[ApprovalRequestStatusEnum] = mapped_column(
        SAEnum(ApprovalRequestStatusEnum, name="approval_request_status_enum"),
        nullable=False,
        default=ApprovalRequestStatusEnum.PENDING_APPROVAL,
        index=True,
    )

    submitted_by: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    submitted_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    submission_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    reviewed_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    feed = relationship("Feed", foreign_keys=[feed_id])
    feed_version = relationship("FeedVersion", foreign_keys=[feed_version_id])
    schema_version = relationship("SchemaVersion", foreign_keys=[schema_version_id])
    mapping_version = relationship("MappingVersion", foreign_keys=[mapping_version_id])
    sandbox_test_run = relationship("SandboxTestRun", foreign_keys=[sandbox_test_run_id])


class FeedActivationRecord(Base, AuditMixin):
    """
    Immutable ledger of approved feed activation.
    Permanently locks the exact bundle of version UUIDs and approver attribution.
    """
    __tablename__ = "feed_activation_records"

    feed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feeds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    approval_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_requests.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    feed_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feed_versions.id", ondelete="RESTRICT"), nullable=False
    )
    schema_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("schema_versions.id", ondelete="RESTRICT"), nullable=False
    )
    mapping_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mapping_versions.id", ondelete="RESTRICT"), nullable=False
    )
    rule_version_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
    )  # List of stringified UUIDs of published rules active at activation
    sandbox_test_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sandbox_test_runs.id", ondelete="RESTRICT"), nullable=False
    )

    activated_by: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    activated_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    activated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    activation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    feed = relationship("Feed", foreign_keys=[feed_id])
    approval_request = relationship("ApprovalRequest", foreign_keys=[approval_request_id])
