"""
Wave 2 Slice 1 Database Model — Schema Drift Detection (CF-V2-E5-04)

SchemaDriftReport:
Records deterministic pre-ingestion schema discrepancies between landed files
and active published schema contracts.
ZERO cell/sample patient values are persisted in drift reports.
"""
import uuid
import enum
from datetime import datetime
from sqlalchemy import (
    String,
    Text,
    ForeignKey,
    Enum as SAEnum,
    Index,
    DateTime,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.models.base import Base, AuditMixin


class DriftSeverityEnum(str, enum.Enum):
    NONE = "NONE"
    NON_BREAKING = "NON_BREAKING"
    BREAKING = "BREAKING"


class DriftStatusEnum(str, enum.Enum):
    DETECTED = "DETECTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class SchemaDriftReport(Base, AuditMixin):
    """
    Immutable or acknowledged record of structural deviations between landed file
    and published schema version.
    """
    __tablename__ = "schema_drift_reports"

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
    expected_schema_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schema_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    drift_severity: Mapped[DriftSeverityEnum] = mapped_column(
        SAEnum(DriftSeverityEnum, name="drift_severity_enum", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
    )

    # Zero PHI: Only field names, type names, and discrepancy codes
    missing_fields: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    unexpected_fields: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    type_mismatches: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    detected_delimiter: Mapped[str | None] = mapped_column(String(10), nullable=True)

    status: Mapped[DriftStatusEnum] = mapped_column(
        SAEnum(DriftStatusEnum, name="drift_status_enum", values_callable=lambda x: [e.value for e in x]),
        default=DriftStatusEnum.DETECTED,
        nullable=False,
    )
    acknowledged_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledgement_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    batch: Mapped["backend.models.pipeline.Batch"] = relationship("Batch")
    feed: Mapped["backend.models.feed.Feed"] = relationship("Feed")
    expected_schema_version: Mapped["backend.models.schema.SchemaVersion"] = relationship("SchemaVersion")
