"""
Wave 0 Database Models — Contract Register

Stores the execution-plane contract: which system reads/writes which data.
Records unconfirmed production assumptions as 'unknowns'.
"""
import uuid
import enum
from sqlalchemy import String, Text, ForeignKey, Enum as SAEnum, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.models.base import Base, AuditMixin


class ContractStatusEnum(str, enum.Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    RETIRED = "RETIRED"


class UnknownStatusEnum(str, enum.Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    WONT_FIX = "WONT_FIX"


class RiskLevelEnum(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ContractRegisterEntry(Base, AuditMixin):
    """
    Execution-plane contract register entry.
    Documents which system reads from / writes to which data domain.
    """
    __tablename__ = "contract_register_entries"

    source_system: Mapped[str] = mapped_column(String(255), nullable=False)
    target_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    data_owner: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ContractStatusEnum] = mapped_column(
        SAEnum(ContractStatusEnum, name="contract_status_enum"),
        nullable=False,
        default=ContractStatusEnum.DRAFT,
    )
    # Story or epic this contract entry belongs to
    story_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    unknowns: Mapped[list["ContractUnknown"]] = relationship(
        "ContractUnknown", back_populates="contract_entry", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_contract_source_domain", "source_system", "target_domain"),
    )


class ContractUnknown(Base, AuditMixin):
    """
    Unconfirmed production assumption tied to a contract register entry.
    Represents a known unknown that must be resolved before production.
    """
    __tablename__ = "contract_unknowns"

    contract_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contract_register_entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[RiskLevelEnum] = mapped_column(
        SAEnum(RiskLevelEnum, name="risk_level_enum"),
        nullable=False,
        default=RiskLevelEnum.MEDIUM,
    )
    status: Mapped[UnknownStatusEnum] = mapped_column(
        SAEnum(UnknownStatusEnum, name="unknown_status_enum"),
        nullable=False,
        default=UnknownStatusEnum.OPEN,
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    contract_entry: Mapped[ContractRegisterEntry] = relationship(
        "ContractRegisterEntry", back_populates="unknowns"
    )
