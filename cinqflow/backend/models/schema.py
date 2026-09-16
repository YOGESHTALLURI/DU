"""
Wave 1 Database Models — Schemas, Schema Versions, Schema Fields, Sample Files, Profiling Runs

Provides the foundational domain for Business Analysts:
- Sample file tracking per feed
- Deterministic profiling runs & column-level statistics (PROFILING FACT)
- Versioned schema contracts & fields (SCHEMA DECISION)
- Lineage linking schema version back to source profiling run and sample file
"""
import uuid
import enum
from datetime import datetime
from sqlalchemy import (
    String,
    Text,
    BigInteger,
    Integer,
    Boolean,
    ForeignKey,
    Enum as SAEnum,
    Index,
    DateTime,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.models.base import Base, AuditMixin


class SchemaDataTypeEnum(str, enum.Enum):
    STRING = "STRING"
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    TIMESTAMP = "TIMESTAMP"


class SchemaVersionStatusEnum(str, enum.Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class ProfilingRunStatusEnum(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SampleFile(Base, AuditMixin):
    """
    Representative sample files uploaded for a feed by Business Analysts.
    Bytes are persisted via StorageAdapter.
    """
    __tablename__ = "sample_files"

    feed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feeds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False, default="text/csv")
    row_count_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_by: Mapped[str] = mapped_column(String(255), nullable=False)

    profiling_runs: Mapped[list["ProfilingRun"]] = relationship(
        "ProfilingRun", back_populates="sample_file", cascade="all, delete-orphan"
    )


class ProfilingRun(Base, AuditMixin):
    """
    Execution record of deterministic profiling over a SampleFile.
    """
    __tablename__ = "profiling_runs"

    feed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feeds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sample_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sample_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[ProfilingRunStatusEnum] = mapped_column(
        SAEnum(ProfilingRunStatusEnum, name="profiling_run_status_enum"),
        nullable=False,
        default=ProfilingRunStatusEnum.PENDING,
        index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    column_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    profiling_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    sample_file: Mapped["SampleFile"] = relationship("SampleFile", back_populates="profiling_runs")
    column_stats: Mapped[list["ProfilingColumnStat"]] = relationship(
        "ProfilingColumnStat", back_populates="profiling_run", cascade="all, delete-orphan", order_by="ProfilingColumnStat.ordinal_position"
    )
    schema_versions: Mapped[list["SchemaVersion"]] = relationship("SchemaVersion", back_populates="source_profiling_run")


class ProfilingColumnStat(Base, AuditMixin):
    """
    PROFILING FACT: Observation from actual sample data.
    Strictly reports facts without making schema decisions.
    """
    __tablename__ = "profiling_column_stats"

    profiling_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiling_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    column_name: Mapped[str] = mapped_column(String(255), nullable=False)
    ordinal_position: Mapped[int] = mapped_column(Integer, nullable=False)
    inferred_type: Mapped[SchemaDataTypeEnum] = mapped_column(
        SAEnum(SchemaDataTypeEnum, name="schema_data_type_enum"), nullable=False
    )
    null_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    null_percentage: Mapped[float] = mapped_column(nullable=False, default=0.0)
    distinct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    distinct_percentage: Mapped[float] = mapped_column(nullable=False, default=0.0)
    min_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    max_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sample_values: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    detected_date_patterns: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    profiling_run: Mapped["ProfilingRun"] = relationship("ProfilingRun", back_populates="column_stats")

    __table_args__ = (
        Index("ix_profiling_col_run_ord", "profiling_run_id", "ordinal_position"),
    )


class Schema(Base, AuditMixin):
    """
    Schema entity representing the contract definition for a Feed.
    Contains immutable versions.
    """
    __tablename__ = "schemas"

    feed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feeds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    versions: Mapped[list["SchemaVersion"]] = relationship(
        "SchemaVersion", back_populates="schema_obj", cascade="all, delete-orphan", order_by="SchemaVersion.version_number"
    )

    @property
    def active_version(self) -> "SchemaVersion | None":
        published = [v for v in self.versions if v.status == SchemaVersionStatusEnum.PUBLISHED]
        return published[-1] if published else None

    @property
    def draft_version(self) -> "SchemaVersion | None":
        drafts = [v for v in self.versions if v.status == SchemaVersionStatusEnum.DRAFT]
        return drafts[-1] if drafts else None



class SchemaVersion(Base, AuditMixin):
    """
    Version snapshot of a Schema contract.
    If status == DRAFT, fields may be edited.
    If status == PUBLISHED, the version and all its fields are strictly immutable.
    Lineage is retained via source_profiling_run_id and source_sample_file_id.
    """
    __tablename__ = "schema_versions"

    schema_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("schemas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[SchemaVersionStatusEnum] = mapped_column(
        SAEnum(SchemaVersionStatusEnum, name="schema_version_status_enum"),
        nullable=False,
        default=SchemaVersionStatusEnum.DRAFT,
        index=True,
    )
    change_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Profiling lineage
    source_profiling_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiling_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_sample_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sample_files.id", ondelete="SET NULL"), nullable=True, index=True
    )

    published_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    schema_obj: Mapped["Schema"] = relationship("Schema", back_populates="versions")
    fields: Mapped[list["SchemaField"]] = relationship(
        "SchemaField", back_populates="schema_version", cascade="all, delete-orphan", order_by="SchemaField.ordinal_position"
    )
    source_profiling_run: Mapped["ProfilingRun | None"] = relationship("ProfilingRun", back_populates="schema_versions")

    __table_args__ = (
        Index("ix_schema_version_schema_id_ver", "schema_id", "version_number", unique=True),
    )


class SchemaField(Base, AuditMixin):
    """
    SCHEMA DECISION: Recorded expectations and constraints for a schema field.
    Distinguished from ProfilingColumnStat (which is observational fact).
    """
    __tablename__ = "schema_fields"

    schema_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("schema_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field_name: Mapped[str] = mapped_column(String(255), nullable=False)
    ordinal_position: Mapped[int] = mapped_column(Integer, nullable=False)
    data_type: Mapped[SchemaDataTypeEnum] = mapped_column(
        SAEnum(SchemaDataTypeEnum, name="schema_data_type_enum"), nullable=False
    )
    is_nullable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    format_pattern: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    schema_version: Mapped["SchemaVersion"] = relationship("SchemaVersion", back_populates="fields")

    __table_args__ = (
        Index("ix_schema_field_ver_ord", "schema_version_id", "ordinal_position"),
        Index("ix_schema_field_ver_name", "schema_version_id", "field_name", unique=True),
    )


class OnboardingStatusEnum(str, enum.Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class OnboardingSession(Base, AuditMixin):
    """
    Session tracking a Business Analyst's journey through the 5-step onboarding wizard.
    Step 1: Feed Setup
    Step 2: Sample & Profiling
    Step 3: Schema Contract
    Step 4: Mapping (Preview / Placeholder)
    Step 5: Review & Activate
    """
    __tablename__ = "onboarding_sessions"

    feed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feeds.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    completed_steps: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    sample_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sample_files.id", ondelete="SET NULL"), nullable=True
    )
    profiling_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiling_runs.id", ondelete="SET NULL"), nullable=True
    )
    schema_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("schemas.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[OnboardingStatusEnum] = mapped_column(
        SAEnum(OnboardingStatusEnum, name="onboarding_status_enum"),
        nullable=False,
        default=OnboardingStatusEnum.IN_PROGRESS,
        index=True,
    )

    feed: Mapped["Feed"] = relationship("Feed")
    sample_file: Mapped["SampleFile | None"] = relationship("SampleFile")
    profiling_run: Mapped["ProfilingRun | None"] = relationship("ProfilingRun")
    schema_obj: Mapped["Schema | None"] = relationship("Schema")

