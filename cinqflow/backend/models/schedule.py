"""
Wave 1 Database Models — Scheduling, Dependencies and Downstream Protection (CF-V1-E8-03)

Provides operational scheduling and DAG dependency modeling:
- FeedSchedule: Governed cron schedule, timezone, and execution status
- FeedDependency: Directed parent-child relationship (upstream -> downstream) with downstream protection gates
"""
import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import (
    String,
    Text,
    Integer,
    Float,
    Boolean,
    ForeignKey,
    Enum as SAEnum,
    Index,
    DateTime,
    CheckConstraint,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.models.base import Base, AuditMixin


class ScheduleStatusEnum(str, enum.Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DISABLED = "DISABLED"


class DependencyTypeEnum(str, enum.Enum):
    HARD = "HARD"  # Must succeed to allow downstream execution
    SOFT = "SOFT"  # Warns but does not strictly block downstream execution


class FeedSchedule(Base, AuditMixin):
    """
    Governed operational schedule for a Feed.
    Manages recurrence cron expression, timezone, and execution lifecycle.
    """
    __tablename__ = "feed_schedules"

    feed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feeds.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    schedule_expression: Mapped[str] = mapped_column(
        String(100), nullable=False, default="0 0 * * *", doc="Standard 5-part cron expression"
    )
    timezone: Mapped[str] = mapped_column(
        String(50), nullable=False, default="UTC", doc="Timezone string, e.g. UTC, America/New_York"
    )
    status: Mapped[ScheduleStatusEnum] = mapped_column(
        SAEnum(ScheduleStatusEnum, name="schedule_status_enum"),
        nullable=False,
        default=ScheduleStatusEnum.ACTIVE,
        index=True,
    )
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, doc="Calculated next run timestamp"
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, doc="Last recorded run timestamp"
    )
    catchup: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, doc="Whether to run missed intervals upon resumption"
    )
    sla_grace_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60, doc="Minutes after scheduled arrival before SLA is breached"
    )
    lead_window_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=120, doc="Minutes before scheduled arrival where incoming files match this slot"
    )

    # Relationship
    feed = relationship("Feed", foreign_keys=[feed_id])


class FeedDependency(Base, AuditMixin):
    """
    Inter-feed prerequisite dependency (DAG edge).
    Specifies that downstream_feed_id depends on upstream_feed_id meeting health criteria.
    """
    __tablename__ = "feed_dependencies"

    downstream_feed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feeds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    upstream_feed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feeds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dependency_type: Mapped[DependencyTypeEnum] = mapped_column(
        SAEnum(DependencyTypeEnum, name="dependency_type_enum"),
        nullable=False,
        default=DependencyTypeEnum.HARD,
    )

    # Downstream Protection Policy Gates
    max_lag_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, default=24, doc="Maximum allowable elapsed hours since upstream completed"
    )
    block_on_upstream_failure: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, doc="Block downstream if latest upstream batch failed"
    )
    block_on_reject_file: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, doc="Block downstream if upstream had REJECT_FILE DQ violation"
    )
    block_on_unbalanced_reconciliation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, doc="Block downstream if upstream reconciliation was unbalanced"
    )
    max_quarantine_rate_pct: Mapped[float | None] = mapped_column(
        Float, nullable=True, default=5.0, doc="Block downstream if upstream quarantine rate exceeds this percent"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, doc="Whether this dependency edge is currently enforced"
    )

    # Relationships
    downstream_feed = relationship("Feed", foreign_keys=[downstream_feed_id])
    upstream_feed = relationship("Feed", foreign_keys=[upstream_feed_id])

    __table_args__ = (
        CheckConstraint("downstream_feed_id != upstream_feed_id", name="chk_no_self_dependency"),
        UniqueConstraint("downstream_feed_id", "upstream_feed_id", name="uq_downstream_upstream"),
    )
