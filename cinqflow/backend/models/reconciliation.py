"""
Wave 0 Database Models — Reconciliation

Measurable reconciliation at every pipeline stage:
  rows_in = rows_out + rows_quarantined + rows_dropped

No unexplained row loss. Every dropped row must have a named reason
in the ReconciliationLedgerEntry.
"""
import uuid
import enum
from sqlalchemy import String, Integer, Boolean, ForeignKey, Enum as SAEnum, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.models.base import Base, AuditMixin


class ReconciliationStatusEnum(str, enum.Enum):
    PASS = "PASS"       # rows_in == rows_out + quarantined + dropped
    FAIL = "FAIL"       # balance check failed
    PENDING = "PENDING" # not yet computed


class BatchReconciliation(Base, AuditMixin):
    """
    Per-batch reconciliation record.

    Wave 0 guarantee:
        rows_in = rows_silver_raw + rows_quarantined

    Example (from demo feed):
        rows_in=4, rows_silver_raw=3, rows_quarantined=1 → PASS
    """
    __tablename__ = "batch_reconciliation"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True
    )
    rows_in: Mapped[int] = mapped_column(Integer, nullable=False,
        doc="Total rows from the source file")
    rows_silver_raw: Mapped[int] = mapped_column(Integer, nullable=False,
        doc="Rows successfully written to Silver Raw")
    rows_quarantined: Mapped[int] = mapped_column(Integer, nullable=False,
        doc="Rows routed to quarantine with a named reason")
    rows_dropped: Mapped[int] = mapped_column(Integer, nullable=False, default=0,
        doc="Rows dropped for any reason not captured by quarantine (should be 0)")
    balance_check_passed: Mapped[bool] = mapped_column(Boolean, nullable=False,
        doc="True if rows_in == rows_silver_raw + rows_quarantined + rows_dropped")
    status: Mapped[ReconciliationStatusEnum] = mapped_column(
        SAEnum(ReconciliationStatusEnum, name="reconciliation_status_enum"),
        nullable=False,
        default=ReconciliationStatusEnum.PENDING,
    )
    discrepancy: Mapped[int] = mapped_column(Integer, nullable=False, default=0,
        doc="rows_in - (rows_silver_raw + rows_quarantined + rows_dropped). Should be 0.")

    batch: Mapped["Batch"] = relationship("Batch", back_populates="reconciliation")
    ledger_entries: Mapped[list["ReconciliationLedgerEntry"]] = relationship(
        "ReconciliationLedgerEntry", back_populates="reconciliation", cascade="all, delete-orphan"
    )

    @property
    def is_balanced(self) -> bool:
        return self.rows_in == (self.rows_silver_raw + self.rows_quarantined + self.rows_dropped)


class ReconciliationLedgerEntry(Base, AuditMixin):
    """
    Named-reason drop ledger entry.
    Every row that did not make it to Silver Raw must have a named reason here.
    No 'other' or 'unknown' entries permitted.
    """
    __tablename__ = "reconciliation_ledger_entries"

    reconciliation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("batch_reconciliation.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False,
        doc="Named reason code. Must map to a QuarantineReasonEnum value.")
    reason_description: Mapped[str] = mapped_column(Text, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)

    reconciliation: Mapped[BatchReconciliation] = relationship(
        "BatchReconciliation", back_populates="ledger_entries"
    )

    __table_args__ = (
        Index("ix_ledger_recon_reason", "reconciliation_id", "reason_code"),
    )
