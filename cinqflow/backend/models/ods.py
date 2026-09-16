"""
Wave 3 Slice 2 Models: Canonical ODS, Model Versioning & Consumer Contracts (CF-V3-E10-01, CF-V3-E10-02)
"""
import uuid
import enum
from datetime import datetime, date, timezone
from decimal import Decimal
from typing import Optional, Dict, Any, List
from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    Numeric,
    Date,
    DateTime,
    Boolean,
    ForeignKey,
    CheckConstraint,
    PrimaryKeyConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.models.base import Base, AuditMixin


class OdsModelVersionStatusEnum(str, enum.Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    DEPRECATED = "DEPRECATED"


class ConsumerStatusEnum(str, enum.Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DECOMMISSIONED = "DECOMMISSIONED"


class ConsumerTypeEnum(str, enum.Enum):
    ANALYTICS_SQL = "ANALYTICS_SQL"
    APPLICATION_API = "APPLICATION_API"
    REPORTING = "REPORTING"
    DATA_WAREHOUSE = "DATA_WAREHOUSE"


class OdsModelVersion(Base, AuditMixin):
    """
    Authoritative canonical model contract version.
    Once published, the schema definition is immutable.
    """
    __tablename__ = "ods_model_versions"

    version_number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    domain: Mapped[str] = mapped_column(String(50), nullable=False, default="clinical")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=OdsModelVersionStatusEnum.DRAFT.value)
    schema_definition: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Relationships
    consumer_registrations: Mapped[List["ConsumerRegistration"]] = relationship(
        "ConsumerRegistration", back_populates="ods_model_version"
    )
    batches: Mapped[List["Batch"]] = relationship(
        "Batch", back_populates="ods_model_version"
    )


class ConsumerRegistration(Base, AuditMixin):
    """
    Downstream data contract registration binding a consumer to an ODS model version.
    Direct SQL consumers are mapped to dedicated PostgreSQL database roles.
    """
    __tablename__ = "consumer_registrations"

    consumer_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    consumer_type: Mapped[str] = mapped_column(String(50), nullable=False)
    registered_ods_model_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ods_model_versions.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=ConsumerStatusEnum.ACTIVE.value)
    db_role_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    ods_model_version: Mapped["OdsModelVersion"] = relationship(
        "OdsModelVersion", back_populates="consumer_registrations"
    )


class OdsMemberV1(Base):
    """
    Physical canonical member record in internal_ods schema.
    Grain: (cinq_id, batch_id).
    """
    __tablename__ = "ods_members_v1"
    __table_args__ = (
        PrimaryKeyConstraint("cinq_id", "batch_id", name="pk_ods_members_v1"),
        {"schema": "internal_ods"},
    )

    cinq_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"), nullable=False
    )
    ods_model_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ods_model_versions.id", ondelete="RESTRICT"), nullable=False
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    gender: Mapped[str] = mapped_column(String(20), nullable=False)
    address_line1: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    survivorship_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class OdsClaimV1(Base):
    """
    Physical canonical claim record in internal_ods schema.
    """
    __tablename__ = "ods_claims_v1"
    __table_args__ = {"schema": "internal_ods"}

    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    cinq_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"), nullable=False
    )
    ods_model_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ods_model_versions.id", ondelete="RESTRICT"), nullable=False
    )
    claim_type: Mapped[str] = mapped_column(String(50), nullable=False)
    total_charge_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    claim_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Relationships
    lines: Mapped[List["OdsClaimLineV1"]] = relationship(
        "OdsClaimLineV1", back_populates="claim", cascade="all, delete-orphan"
    )


class OdsClaimLineV1(Base):
    """
    Physical canonical claim line item in internal_ods schema.
    """
    __tablename__ = "ods_claim_lines_v1"
    __table_args__ = {"schema": "internal_ods"}

    claim_line_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("internal_ods.ods_claims_v1.claim_id", ondelete="CASCADE"), nullable=False
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"), nullable=False
    )
    ods_model_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ods_model_versions.id", ondelete="RESTRICT"), nullable=False
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    procedure_code: Mapped[str] = mapped_column(String(50), nullable=False)
    allowed_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0.00"))
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0.00"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Relationships
    claim: Mapped["OdsClaimV1"] = relationship("OdsClaimV1", back_populates="lines")


class OdsMemberProvenanceV1(Base):
    """
    Lineage table tracking contributing raw source records for each canonical member.
    Enforces strict synthetic technical source_row_id format (Zero-PHI).
    """
    __tablename__ = "ods_member_provenance_v1"
    __table_args__ = (
        CheckConstraint(
            "source_row_id ~ '^row_[0-9]+_[0-9a-f]{16}$|^[0-9a-fA-F-]{36}$'",
            name="chk_synthetic_source_row_id",
        ),
        {"schema": "internal_ods"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    cinq_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"), nullable=False
    )
    source_identifier_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_row_id: Mapped[str] = mapped_column(String(64), nullable=False)
    survivorship_winner: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class OdsCertificationStatusEnum(str, enum.Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    FAILED = "FAILED"


class OdsCertification(Base, AuditMixin):
    """
    Authoritative certification of a completed ODS batch (CF-V3-E10-03).
    Gates downstream access via certified views in schema ods_certified.
    """
    __tablename__ = "ods_certifications"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING', 'CERTIFIED', 'FAILED')", name="chk_ods_certification_status"),
    )

    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True
    )
    ods_model_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ods_model_versions.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=OdsCertificationStatusEnum.PENDING.value, index=True
    )
    certified_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    certified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    certification_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    checklist_snapshot: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # Relationships
    batch: Mapped["Batch"] = relationship("Batch")
    ods_model_version: Mapped["OdsModelVersion"] = relationship("OdsModelVersion")
