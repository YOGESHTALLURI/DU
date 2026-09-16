"""
Wave 1 Slice 4 Database Models — Data Quality Rules, Rule Versions, Rule Test Runs

Deterministic Data Quality Rules Engine:
- DataQualityRule: associates Feed + Schema with Unique(feed_id, name) where is_deleted=FALSE, plus soft-delete flags
- RuleVersion: immutable version snapshot explicitly pinned to schema_version_id
- RuleTestRun: test execution results against sample data with ZERO actual sample/cell values persisted
"""
import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import (
    String,
    Text,
    Integer,
    Numeric,
    Boolean,
    ForeignKey,
    Enum as SAEnum,
    Index,
    DateTime,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.models.base import Base, AuditMixin


class RuleVersionStatusEnum(str, enum.Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class RuleTypeEnum(str, enum.Enum):
    """Exactly 7 supported rule types. CUSTOM_SQL is strictly excluded."""
    NOT_NULL = "NOT_NULL"
    RANGE = "RANGE"
    REGEX = "REGEX"
    ENUM = "ENUM"
    LENGTH = "LENGTH"
    DATE_RANGE = "DATE_RANGE"
    CROSS_FIELD = "CROSS_FIELD"


class RuleSeverityEnum(str, enum.Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    QUARANTINE = "QUARANTINE"
    REJECT_FILE = "REJECT_FILE"


class TestRunStatusEnum(str, enum.Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DataQualityRule(Base, AuditMixin):
    """
    Data Quality Rule entity scoped to a feed and schema.
    Supports soft-delete with is_deleted, deleted_at, deleted_by.
    """
    __tablename__ = "data_quality_rules"

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
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Soft-delete tracking
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    feed: Mapped["backend.models.feed.Feed"] = relationship("Feed")
    schema_obj: Mapped["backend.models.schema.Schema"] = relationship("Schema")
    versions: Mapped[list["RuleVersion"]] = relationship(
        "RuleVersion",
        back_populates="rule",
        cascade="all, delete-orphan",
        order_by="RuleVersion.version_number.desc()",
    )

    __table_args__ = (
        Index("ix_dq_rule_feed_name_active", "feed_id", "name", unique=True, postgresql_where=(is_deleted.is_(False))),
    )


class RuleVersion(Base, AuditMixin):
    """
    Version snapshot of a rule.
    Immutably pinned to schema_version_id upon creation.
    Published versions are strictly immutable.
    """
    __tablename__ = "rule_versions"

    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("data_quality_rules.id", ondelete="CASCADE"),
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
    status: Mapped[RuleVersionStatusEnum] = mapped_column(
        SAEnum(RuleVersionStatusEnum, name="rule_version_status_enum", values_callable=lambda x: [e.value for e in x]),
        default=RuleVersionStatusEnum.DRAFT,
        nullable=False,
        index=True,
    )
    rule_type: Mapped[RuleTypeEnum] = mapped_column(
        SAEnum(RuleTypeEnum, name="rule_type_enum", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    target_field: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[RuleSeverityEnum] = mapped_column(
        SAEnum(RuleSeverityEnum, name="rule_severity_enum", values_callable=lambda x: [e.value for e in x]),
        default=RuleSeverityEnum.QUARANTINE,
        nullable=False,
    )
    rule_config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    error_message_template: Mapped[str | None] = mapped_column(String(500), nullable=True)
    change_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    compiled_spec: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    published_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Flag for manual technical review, set by BA
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    rule: Mapped["DataQualityRule"] = relationship("DataQualityRule", back_populates="versions")
    schema_version: Mapped["backend.models.schema.SchemaVersion"] = relationship("SchemaVersion")
    test_runs: Mapped[list["RuleTestRun"]] = relationship(
        "RuleTestRun",
        back_populates="rule_version",
        cascade="all, delete-orphan",
        order_by="RuleTestRun.executed_at.desc()",
    )

    __table_args__ = (
        UniqueConstraint("rule_id", "version_number", name="uq_rule_version_number"),
    )


class RuleTestRun(Base, AuditMixin):
    """
    Test execution record against sample data.
    ZERO actual sample/cell values are persisted.
    failed_row_details contains ONLY row_number, field_name, and reason.
    """
    __tablename__ = "rule_test_runs"

    rule_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rule_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sample_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sample_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    passed_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    pass_rate: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    status: Mapped[TestRunStatusEnum] = mapped_column(
        SAEnum(TestRunStatusEnum, name="test_run_status_enum", values_callable=lambda x: [e.value for e in x]),
        default=TestRunStatusEnum.COMPLETED,
        nullable=False,
    )
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Persisted details: ONLY row_number, field_name, reason — NEVER cell/sample values
    failed_row_details: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    executed_by: Mapped[str] = mapped_column(String(255), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    rule_version: Mapped["RuleVersion"] = relationship("RuleVersion", back_populates="test_runs")
    sample_file: Mapped["backend.models.schema.SampleFile"] = relationship("SampleFile")
