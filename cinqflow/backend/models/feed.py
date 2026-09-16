"""
Wave 0 Database Models — Feed Registry

Feed = a source data feed (e.g., a health plan member file).
FeedVersion = an immutable, versioned snapshot of feed configuration.

The pipeline compiler consumes ONLY feed metadata. No feed-specific code branching.
"""
import uuid
import enum
import re
from sqlalchemy import String, Text, ForeignKey, Enum as SAEnum, Index, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from backend.models.base import Base, AuditMixin


class FeedFormatEnum(str, enum.Enum):
    CSV = "CSV"
    JSON = "JSON"
    PARQUET = "PARQUET"
    XML = "XML"
    HL7 = "HL7"
    X12 = "X12"


class FeedStatusEnum(str, enum.Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    RETIRED = "RETIRED"


class FeedVersionStatusEnum(str, enum.Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class Feed(Base, AuditMixin):
    """
    Feed definition — metadata only. The pipeline compiler uses this to build an
    execution plan without any feed-specific code.

    Wave 0 requires 6 minimum fields:
    1. name
    2. domain
    3. format
    4. landing_folder
    5. filename_pattern
    6. schedule_expression (cron or 'manual')
    """
    __tablename__ = "feeds"

    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    format: Mapped[FeedFormatEnum] = mapped_column(
        SAEnum(FeedFormatEnum, name="feed_format_enum"), nullable=False
    )
    landing_folder: Mapped[str] = mapped_column(String(500), nullable=False)
    filename_pattern: Mapped[str] = mapped_column(String(255), nullable=False,
        doc="Glob or regex pattern for matching incoming filenames, e.g. 'MEMBER_*.csv'")
    schedule_expression: Mapped[str] = mapped_column(String(100), nullable=False, default="manual",
        doc="Cron expression or 'manual'")
    source_system: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    data_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sla_expectation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cloned_from_feed_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feeds.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[FeedStatusEnum] = mapped_column(
        SAEnum(FeedStatusEnum, name="feed_status_enum"),
        nullable=False,
        default=FeedStatusEnum.DRAFT,
    )

    versions: Mapped[list["FeedVersion"]] = relationship(
        "FeedVersion", back_populates="feed",
        order_by="FeedVersion.version_number",
        cascade="all, delete-orphan"
    )
    batches: Mapped[list["Batch"]] = relationship("Batch", back_populates="feed")

    def get_active_version(self) -> "FeedVersion | None":
        published = [v for v in self.versions if v.status == FeedVersionStatusEnum.PUBLISHED]
        return published[-1] if published else None

    def matches_filename(self, filename: str) -> bool:
        """Check if a filename matches this feed's pattern."""
        import fnmatch
        return fnmatch.fnmatch(filename, self.filename_pattern)


class FeedVersion(Base, AuditMixin):
    """
    Immutable versioned configuration for a feed.
    Once published, a FeedVersion cannot be modified.
    All pipeline runs reference a specific version.
    """
    __tablename__ = "feed_versions"

    feed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feeds.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[FeedVersionStatusEnum] = mapped_column(
        SAEnum(FeedVersionStatusEnum, name="feed_version_status_enum"),
        nullable=False,
        default=FeedVersionStatusEnum.DRAFT,
    )
    # Configuration snapshot — immutable once published
    config_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True,
        doc="Full metadata snapshot taken at publish time")
    change_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    feed: Mapped[Feed] = relationship("Feed", back_populates="versions")
    batches: Mapped[list["Batch"]] = relationship("Batch", back_populates="feed_version")

    __table_args__ = (
        Index("ix_feed_versions_feed_version", "feed_id", "version_number", unique=True),
    )
