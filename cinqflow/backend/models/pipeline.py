"""
Wave 0 Database Models — Pipeline Execution

Batch: one pipeline run for one feed+version+input.
BatchStage: per-stage status tracking (Landing, Bronze, Silver Raw).

Stage restart: when a batch restarts, only stages in FAILED or PENDING state
are re-executed. Stages already in SUCCESS are not re-run.
"""
import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, ForeignKey, Enum as SAEnum, Index, Text, BigInteger
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.models.base import Base, AuditMixin


class BatchStatusEnum(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    FAILED_RECONCILIATION = "FAILED_RECONCILIATION"


class StageNameEnum(str, enum.Enum):
    """
    Wave 0 pipeline stages only.
    Identity and Silver ODS are Wave 3 stages — not included here.
    """
    LANDING = "LANDING"
    BRONZE = "BRONZE"
    SILVER_RAW = "SILVER_RAW"
    IDENTITY = "IDENTITY"
    ODS = "ODS"


class StageStatusEnum(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


# Canonical stage execution order for Wave 0
WAVE0_STAGE_ORDER = [
    StageNameEnum.LANDING,
    StageNameEnum.BRONZE,
    StageNameEnum.SILVER_RAW,
]

WAVE3_STAGE_ORDER = [
    StageNameEnum.LANDING,
    StageNameEnum.BRONZE,
    StageNameEnum.SILVER_RAW,
    StageNameEnum.IDENTITY,
    StageNameEnum.ODS,
]


class Batch(Base, AuditMixin):
    """
    One pipeline run for a specific feed+version+input combination.

    Lifecycle:
    PENDING → RUNNING → SUCCESS | FAILED | FAILED_RECONCILIATION | CANCELLED

    Restart: a FAILED batch can be restarted. Only incomplete stages re-run.
    """
    __tablename__ = "batches"

    feed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feeds.id"), nullable=False, index=True
    )
    feed_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feed_versions.id"), nullable=False
    )
    input_registry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("input_registry.id"), nullable=True, index=True
    )
    parent_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id"), nullable=True, index=True
    )
    status: Mapped[BatchStatusEnum] = mapped_column(
        SAEnum(BatchStatusEnum, name="batch_status_enum"),
        nullable=False,
        default=BatchStatusEnum.PENDING,
        index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(255), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    restart_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ods_model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ods_model_versions.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    feed: Mapped["Feed"] = relationship("Feed", back_populates="batches")
    feed_version: Mapped["FeedVersion"] = relationship("FeedVersion", back_populates="batches")
    input_registry: Mapped["InputRegistry | None"] = relationship("InputRegistry", back_populates="batches")
    ods_model_version: Mapped["OdsModelVersion | None"] = relationship("OdsModelVersion", back_populates="batches")
    stages: Mapped[list["BatchStage"]] = relationship(
        "BatchStage", back_populates="batch",
        order_by="BatchStage.stage_order",
        cascade="all, delete-orphan"
    )
    quarantine_records: Mapped[list["QuarantineRecord"]] = relationship(
        "QuarantineRecord",
        foreign_keys="[QuarantineRecord.batch_id]",
        back_populates="batch",
    )
    reconciliation: Mapped["BatchReconciliation | None"] = relationship(
        "BatchReconciliation", back_populates="batch", uselist=False
    )

    def get_stage(self, stage_name: StageNameEnum) -> "BatchStage | None":
        return next((s for s in self.stages if s.stage_name == stage_name), None)

    def get_last_completed_stage(self) -> "BatchStage | None":
        completed = [s for s in self.stages if s.status == StageStatusEnum.SUCCESS]
        return completed[-1] if completed else None


class BatchStage(Base, AuditMixin):
    """
    Per-stage execution record within a batch.

    On restart: stages with status=SUCCESS are not re-run.
    Stages with status=FAILED or PENDING are re-run from the first non-SUCCESS stage.
    """
    __tablename__ = "batch_stages"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    stage_name: Mapped[StageNameEnum] = mapped_column(
        SAEnum(StageNameEnum, name="stage_name_enum"), nullable=False
    )
    stage_order: Mapped[int] = mapped_column(Integer, nullable=False,
        doc="Execution order: 1=Landing, 2=Bronze, 3=Silver Raw")
    status: Mapped[StageStatusEnum] = mapped_column(
        SAEnum(StageStatusEnum, name="stage_status_enum"),
        nullable=False,
        default=StageStatusEnum.PENDING,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rows_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rows_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rows_quarantined: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rows_dropped: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    stage_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    batch: Mapped[Batch] = relationship("Batch", back_populates="stages")

    __table_args__ = (
        Index("ix_batch_stages_batch_stage", "batch_id", "stage_name", unique=True),
    )
