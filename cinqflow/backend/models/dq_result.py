"""
Wave 2 Slice 1 Database Model — Production Data Quality Execution Results (CF-V2-E7-05)

DQResult:
Records execution metrics and violation counts per rule per batch in production.
ZERO row/cell patient values are persisted in dq_results.
"""
import uuid
import enum
from sqlalchemy import (
    Integer,
    Numeric,
    ForeignKey,
    Enum as SAEnum,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.models.base import Base, AuditMixin


class DQActionTakenEnum(str, enum.Enum):
    PASSED = "PASSED"
    LOGGED_INFO = "LOGGED_INFO"
    LOGGED_WARNING = "LOGGED_WARNING"
    QUARANTINED_ROWS = "QUARANTINED_ROWS"
    BATCH_ABORTED = "BATCH_ABORTED"


class DQResult(Base, AuditMixin):
    """
    Immutable production data quality execution telemetry for a single rule version on a batch.
    """
    __tablename__ = "dq_results"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("batch_stages.id", ondelete="CASCADE"),
        nullable=False,
    )
    rule_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rule_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    total_rows_evaluated: Mapped[int] = mapped_column(Integer, nullable=False)
    passed_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    pass_rate: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    action_taken: Mapped[DQActionTakenEnum] = mapped_column(
        SAEnum(DQActionTakenEnum, name="dq_action_taken_enum", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
    )
    execution_duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    batch: Mapped["backend.models.pipeline.Batch"] = relationship("Batch")
    stage: Mapped["backend.models.pipeline.BatchStage"] = relationship("BatchStage")
    rule_version: Mapped["backend.models.rule.RuleVersion"] = relationship("RuleVersion")

    __table_args__ = (
        UniqueConstraint("batch_id", "rule_version_id", name="uq_dq_results_batch_rule"),
    )
