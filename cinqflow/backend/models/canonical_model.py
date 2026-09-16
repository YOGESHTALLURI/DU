"""
Wave 1 Slice 3 Database Models — Canonical Models & Canonical Fields

Reference healthcare canonical data models (Member, Claim, Encounter, Observation).
These represent platform standard definitions and are strictly READ-ONLY reference data.
"""
import uuid
from sqlalchemy import (
    String,
    Text,
    Integer,
    Boolean,
    ForeignKey,
    Enum as SAEnum,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.models.base import Base, AuditMixin
from backend.models.schema import SchemaDataTypeEnum


class CanonicalModel(Base, AuditMixin):
    """
    Standard healthcare target model (e.g., Member, Claim, Encounter, Observation).
    Read-only reference entity in Wave 1.
    """
    __tablename__ = "canonical_models"

    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    domain: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    fields: Mapped[list["CanonicalField"]] = relationship(
        "CanonicalField",
        back_populates="canonical_model",
        cascade="all, delete-orphan",
        order_by="CanonicalField.ordinal_position",
    )


class CanonicalField(Base, AuditMixin):
    """
    Field / attribute definition for a CanonicalModel.
    Specifies expected data type, required status, and clinical description.
    """
    __tablename__ = "canonical_fields"

    canonical_model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("canonical_models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    field_name: Mapped[str] = mapped_column(String(255), nullable=False)
    data_type: Mapped[SchemaDataTypeEnum] = mapped_column(
        SAEnum(SchemaDataTypeEnum, name="schema_data_type_enum"),
        nullable=False,
    )
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_nullable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ordinal_position: Mapped[int] = mapped_column(Integer, nullable=False)

    canonical_model: Mapped["CanonicalModel"] = relationship(
        "CanonicalModel", back_populates="fields"
    )

    __table_args__ = (
        UniqueConstraint("canonical_model_id", "field_name", name="uq_canonical_field_model_name"),
        Index("ix_canonical_field_model_ord", "canonical_model_id", "ordinal_position"),
    )
