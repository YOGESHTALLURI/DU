"""
Wave 1 Slice 3 Database Models — Mappings, Mapping Versions, Mapping Lines

Source-to-Canonical mapping entities:
- Mapping: associates Feed + Schema to CanonicalModel with unique(feed_id, canonical_model_id)
- MappingVersion: immutable version snapshot explicitly pinned to schema_version_id
- MappingLine: field-level mapping rules and transform specifications
"""
import uuid
import enum
from datetime import datetime
from sqlalchemy import (
    String,
    Text,
    Integer,
    ForeignKey,
    Enum as SAEnum,
    Index,
    DateTime,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.models.base import Base, AuditMixin


class MappingVersionStatusEnum(str, enum.Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class TransformTypeEnum(str, enum.Enum):
    DIRECT = "DIRECT"
    CONSTANT = "CONSTANT"
    VALUE_MAP = "VALUE_MAP"
    DATE_FORMAT = "DATE_FORMAT"
    CONCAT = "CONCAT"
    STRING_CLEAN = "STRING_CLEAN"
    COALESCE = "COALESCE"
    # Wave 3 Slice 1: Structural Transforms for Complex Formats
    EXPLODE = "EXPLODE"
    FLATTEN = "FLATTEN"
    PATH_EXTRACT = "PATH_EXTRACT"
    ARRAY_MAP = "ARRAY_MAP"
    UNNEST = "UNNEST"


class Mapping(Base, AuditMixin):
    """
    Mapping definition tying a Feed and Schema to a target CanonicalModel.
    Rule: A feed has at most ONE mapping for a given canonical model.
    """
    __tablename__ = "mappings"

    feed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("feeds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    schema_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schemas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    canonical_model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("canonical_models.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    feed: Mapped["backend.models.feed.Feed"] = relationship("Feed")
    schema_obj: Mapped["backend.models.schema.Schema"] = relationship("Schema")
    canonical_model: Mapped["backend.models.canonical_model.CanonicalModel"] = relationship("CanonicalModel")

    versions: Mapped[list["MappingVersion"]] = relationship(
        "MappingVersion",
        back_populates="mapping",
        cascade="all, delete-orphan",
        order_by="MappingVersion.version_number",
    )

    __table_args__ = (
        UniqueConstraint("feed_id", "canonical_model_id", name="uq_mapping_feed_canonical_model"),
    )

    @property
    def active_version(self) -> "MappingVersion | None":
        published = [v for v in self.versions if v.status == MappingVersionStatusEnum.PUBLISHED]
        return published[-1] if published else None

    @property
    def draft_version(self) -> "MappingVersion | None":
        drafts = [v for v in self.versions if v.status == MappingVersionStatusEnum.DRAFT]
        return drafts[-1] if drafts else None


class MappingVersion(Base, AuditMixin):
    """
    Immutable versioned snapshot of a Mapping.
    Explicitly pinned to a specific SchemaVersion.
    """
    __tablename__ = "mapping_versions"

    mapping_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mappings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schema_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[MappingVersionStatusEnum] = mapped_column(
        SAEnum(MappingVersionStatusEnum, name="mapping_version_status_enum"),
        nullable=False,
        default=MappingVersionStatusEnum.DRAFT,
        index=True,
    )
    compiled_spec: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        doc="Deterministic compiled execution plan",
    )
    change_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    mapping: Mapped["Mapping"] = relationship("Mapping", back_populates="versions")
    schema_version: Mapped["backend.models.schema.SchemaVersion"] = relationship("SchemaVersion")
    lines: Mapped[list["MappingLine"]] = relationship(
        "MappingLine",
        back_populates="mapping_version",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("mapping_id", "version_number", name="uq_mapping_version_ver"),
    )


class MappingLine(Base, AuditMixin):
    """
    Individual field-level mapping rule.
    Links a canonical target field to source field(s) via a deterministic transform.
    """
    __tablename__ = "mapping_lines"

    mapping_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mapping_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    canonical_field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("canonical_fields.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_field_names: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        doc="List of source field strings, e.g. ['first_name', 'last_name']",
    )
    transform_type: Mapped[TransformTypeEnum] = mapped_column(
        SAEnum(TransformTypeEnum, name="transform_type_enum"),
        nullable=False,
        default=TransformTypeEnum.DIRECT,
    )
    transform_params: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        doc="Config dictionary for the transform (no sample data values)",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    mapping_version: Mapped["MappingVersion"] = relationship("MappingVersion", back_populates="lines")
    canonical_field: Mapped["backend.models.canonical_model.CanonicalField"] = relationship("CanonicalField")

    __table_args__ = (
        UniqueConstraint("mapping_version_id", "canonical_field_id", name="uq_mapping_line_ver_field"),
    )
