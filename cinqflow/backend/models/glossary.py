"""
Wave 1 Slice 7 Database Models — Enterprise Business Glossary & Canonical Semantics

Defines:
- GlossaryTerm: Authoritative business term definition with domain, PHI, code-set, and lifecycle status.
- GlossaryCanonicalLink: Association between a glossary term and a canonical reference field.
- GlossaryTermStatusEnum: DRAFT, APPROVED, DEPRECATED
- GlossaryPhiClassificationEnum: NONE, POTENTIAL_PHI, CONFIRMED_PHI
- GlossaryCodeSetEnum: NONE, ICD_10, CPT, HCPCS, LOINC, SNOMED_CT, NDC, NPI
"""
import uuid
import enum
from sqlalchemy import (
    String,
    Text,
    ForeignKey,
    Enum as SAEnum,
    Index,
    UniqueConstraint,
    CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.models.base import Base, AuditMixin


class GlossaryTermStatusEnum(str, enum.Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    DEPRECATED = "DEPRECATED"


class GlossaryPhiClassificationEnum(str, enum.Enum):
    NONE = "NONE"
    POTENTIAL_PHI = "POTENTIAL_PHI"
    CONFIRMED_PHI = "CONFIRMED_PHI"


class GlossaryCodeSetEnum(str, enum.Enum):
    NONE = "NONE"
    ICD_10 = "ICD_10"
    CPT = "CPT"
    HCPCS = "HCPCS"
    LOINC = "LOINC"
    SNOMED_CT = "SNOMED_CT"
    NDC = "NDC"
    NPI = "NPI"


class GlossaryTerm(Base, AuditMixin):
    """
    Authoritative enterprise healthcare business term definition.
    Linked to canonical models to provide semantic metadata, code-set context, and PHI classifications.
    """
    __tablename__ = "glossary_terms"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    acronym: Mapped[str | None] = mapped_column(String(50), nullable=True)
    synonyms: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    domain: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    clinical_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_steward: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[GlossaryTermStatusEnum] = mapped_column(
        SAEnum(GlossaryTermStatusEnum, name="glossary_term_status_enum", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=GlossaryTermStatusEnum.DRAFT,
        index=True,
    )
    phi_classification: Mapped[GlossaryPhiClassificationEnum] = mapped_column(
        SAEnum(GlossaryPhiClassificationEnum, name="glossary_phi_classification_enum", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=GlossaryPhiClassificationEnum.NONE,
        index=True,
    )
    code_set: Mapped[GlossaryCodeSetEnum] = mapped_column(
        SAEnum(GlossaryCodeSetEnum, name="glossary_code_set_enum", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=GlossaryCodeSetEnum.NONE,
        index=True,
    )

    deprecation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    replaced_by_term_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("glossary_terms.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    canonical_links: Mapped[list["GlossaryCanonicalLink"]] = relationship(
        "GlossaryCanonicalLink",
        back_populates="glossary_term",
        cascade="all, delete-orphan",
    )
    replaced_by_term: Mapped["GlossaryTerm | None"] = relationship(
        "GlossaryTerm",
        remote_side="GlossaryTerm.id",
    )

    __table_args__ = (
        CheckConstraint(
            "(status != 'DEPRECATED') OR (deprecation_reason IS NOT NULL AND length(trim(deprecation_reason)) > 0)",
            name="chk_term_deprecated_reason",
        ),
    )


class GlossaryCanonicalLink(Base, AuditMixin):
    """
    Bidirectional link between a GlossaryTerm and a CanonicalField.
    Allows one glossary term to associate with multiple fields across canonical models
    (e.g., Member ID associated with Member.member_id and Claim.member_id).
    """
    __tablename__ = "glossary_canonical_links"

    glossary_term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("glossary_terms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    canonical_field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("canonical_fields.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Relationships
    glossary_term: Mapped["GlossaryTerm"] = relationship(
        "GlossaryTerm",
        back_populates="canonical_links",
    )
    canonical_field: Mapped["CanonicalField"] = relationship(
        "backend.models.canonical_model.CanonicalField",
    )

    __table_args__ = (
        UniqueConstraint("glossary_term_id", "canonical_field_id", name="uq_term_canonical_field"),
    )
