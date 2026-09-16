"""
Wave 0 Database Models — Input Registry

Records every file arrival with a SHA-256 fingerprint.
Duplicate detection: if the same fingerprint is submitted twice,
the second submission is rejected without creating a new batch.

This implements IDEMPOTENT INPUT PROCESSING:
  "Repeated submission of the same input fingerprint must not create
   duplicate processing or duplicate results."
"""
import uuid
import enum
from datetime import datetime
from sqlalchemy import String, BigInteger, ForeignKey, Enum as SAEnum, Index, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.models.base import Base, AuditMixin


class InputStatusEnum(str, enum.Enum):
    ACCEPTED = "ACCEPTED"       # Valid file, batch will be created
    DUPLICATE = "DUPLICATE"     # Same fingerprint already processed — skipped
    REJECTED = "REJECTED"       # Invalid filename, structure, or size


class QuarantineReasonEnum(str, enum.Enum):
    """Named reasons for quarantine. No 'other' or 'unknown' allowed."""
    INVALID_FIELD_TYPE = "INVALID_FIELD_TYPE"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    FUTURE_DATE = "FUTURE_DATE"
    INVALID_DATE_FORMAT = "INVALID_DATE_FORMAT"
    INVALID_ENUM_VALUE = "INVALID_ENUM_VALUE"
    VALUE_OUT_OF_RANGE = "VALUE_OUT_OF_RANGE"
    DUPLICATE_RECORD = "DUPLICATE_RECORD"
    REFERENTIAL_INTEGRITY = "REFERENTIAL_INTEGRITY"
    REGEX_MISMATCH = "REGEX_MISMATCH"
    RECORD_TOO_LONG = "RECORD_TOO_LONG"
    ENCODING_ERROR = "ENCODING_ERROR"


class InputRegistry(Base, AuditMixin):
    """
    File input registration record.

    Every incoming file is fingerprinted (SHA-256) before processing.
    The fingerprint is stored with a UNIQUE constraint — attempting to
    insert the same fingerprint twice raises an IntegrityError which
    is caught and results in a DUPLICATE status response.

    This is the primary mechanism for idempotent input processing.
    """
    __tablename__ = "input_registry"

    feed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feeds.id"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # SHA-256 fingerprint — UNIQUE ensures idempotent processing
    file_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    status: Mapped[InputStatusEnum] = mapped_column(
        SAEnum(InputStatusEnum, name="input_status_enum"),
        nullable=False,
        default=InputStatusEnum.ACCEPTED,
        index=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    registered_by: Mapped[str] = mapped_column(String(255), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    feed: Mapped["Feed"] = relationship("Feed")
    batches: Mapped[list["Batch"]] = relationship("Batch", back_populates="input_registry")

    __table_args__ = (
        Index("ix_input_registry_feed_filename", "feed_id", "filename"),
    )


class QuarantineStatusEnum(str, enum.Enum):
    QUARANTINED = "QUARANTINED"
    REPROCESSED = "REPROCESSED"
    DISCARDED = "DISCARDED"


class QuarantineRecord(Base, AuditMixin):
    """
    A single record that failed validation and was routed to quarantine.

    Contains enough information to answer:
    - which feed? (feed_id via batch)
    - which input? (input_registry_id via batch)
    - which batch? (batch_id)
    - which stage? (stage_name)
    - which record? (source_row_number, source_record_raw)
    - what failed? (field_name)
    - why? (reason — named, no 'unknown')
    - when? (created_at from AuditMixin)
    - status? (QUARANTINED, REPROCESSED, DISCARDED)
    - resolution? (resolution_batch_id, resolved_at, resolved_by)
    """
    __tablename__ = "quarantine_records"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    stage_name: Mapped[str] = mapped_column(String(50), nullable=False)
    source_row_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Raw original record preserved unchanged
    source_record_raw: Mapped[str | None] = mapped_column(Text, nullable=True,
        doc="Original record exactly as it appeared in the source file")
    field_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    field_value: Mapped[str | None] = mapped_column(Text, nullable=True,
        doc="Value that caused the failure. PHI masked if applicable.")
    reason: Mapped[QuarantineReasonEnum] = mapped_column(
        SAEnum(QuarantineReasonEnum, name="quarantine_reason_enum"),
        nullable=False,
    )
    reason_detail: Mapped[str | None] = mapped_column(Text, nullable=True,
        doc="Human-readable explanation of why this record was quarantined")

    # Resolution tracking (Wave 2 Slice 3)
    status: Mapped[QuarantineStatusEnum] = mapped_column(
        SAEnum(QuarantineStatusEnum, name="quarantine_status_enum"),
        nullable=False,
        default=QuarantineStatusEnum.QUARANTINED,
        index=True,
    )
    resolution_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    batch: Mapped["Batch"] = relationship("Batch", foreign_keys=[batch_id], back_populates="quarantine_records")
    resolution_batch: Mapped["Batch | None"] = relationship("Batch", foreign_keys=[resolution_batch_id])

    __table_args__ = (
        Index("ix_quarantine_batch_stage", "batch_id", "stage_name"),
        Index("ix_quarantine_status", "status"),
    )
