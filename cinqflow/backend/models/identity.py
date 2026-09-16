"""
Wave 3 Slice 3 Models: Identity Foundation & Identity Exceptions (CF-V3-E9-01, CF-V3-E9-02)
"""
import uuid
import enum
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Dict, Any, List
from sqlalchemy import (
    String,
    Text,
    Integer,
    Numeric,
    DateTime,
    Boolean,
    ForeignKey,
    CheckConstraint,
    Index,
    Computed,
    column,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, TSTZRANGE, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.models.base import Base


class MasterIdentityStatusEnum(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    MERGED = "MERGED"
    EXPIRED = "EXPIRED"
    SPLIT = "SPLIT"


class IdentityTypeEnum(str, enum.Enum):
    INDIVIDUAL = "INDIVIDUAL"


class CrosswalkMatchTypeEnum(str, enum.Enum):
    DETERMINISTIC_HIGH_CONFIDENCE = "DETERMINISTIC_HIGH_CONFIDENCE"
    STEWARD_LINK = "STEWARD_LINK"
    STEWARD_CREATE = "STEWARD_CREATE"


class IdentityExceptionTypeEnum(str, enum.Enum):
    AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"
    NO_VIABLE_CANDIDATE = "NO_VIABLE_CANDIDATE"
    SCORE_TIE = "SCORE_TIE"
    CONFLICTING_DEMOGRAPHICS = "CONFLICTING_DEMOGRAPHICS"


class IdentityExceptionStatusEnum(str, enum.Enum):
    PENDING = "PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    DEFERRED = "DEFERRED"


class StewardResolutionTypeEnum(str, enum.Enum):
    LINK_EXISTING = "LINK_EXISTING"
    CREATE_NEW = "CREATE_NEW"
    DEFER = "DEFER"


class MasterIdentity(Base):
    """
    Authoritative Master Identity registry.
    Assigns and maintains immutable CINQ IDs for real-world patients/members.
    """
    __tablename__ = "master_identities"

    cinq_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=MasterIdentityStatusEnum.ACTIVE.value, index=True
    )
    identity_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default=IdentityTypeEnum.INDIVIDUAL.value
    )
    merged_into_cinq_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("master_identities.cinq_id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Standard audit fields
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False
    )
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

    tokens: Mapped[List["IdentityToken"]] = relationship(
        "IdentityToken", back_populates="master_identity", cascade="all, delete-orphan"
    )
    crosswalk_entries: Mapped[List["IdentityCrosswalk"]] = relationship(
        "IdentityCrosswalk", back_populates="master_identity"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE', 'MERGED')",
            name="chk_master_identity_status",
        ),
    )


class IdentityToken(Base):
    """
    Persisted hashed candidate demographic tokens for deterministic retrieval and matching.
    Guarantees ZERO raw PHI storage.
    """
    __tablename__ = "identity_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    cinq_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("master_identities.cinq_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    ssn_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    dob_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    last_name_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    first_name_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    gender_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    postal_code_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    pepper_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    effective_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_period: Mapped[Any] = mapped_column(
        TSTZRANGE,
        Computed("tstzrange(effective_from, effective_to, '[)')", persisted=True),
        nullable=True,
    )
    source_feed_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feeds.id", ondelete="SET NULL"), nullable=True
    )
    source_batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="SET NULL"), nullable=True
    )

    # Standard audit fields
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

    master_identity: Mapped["MasterIdentity"] = relationship(
        "MasterIdentity", back_populates="tokens"
    )

    __table_args__ = (
        CheckConstraint(
            "(is_current = TRUE AND effective_to IS NULL) OR "
            "(is_current = FALSE AND effective_to IS NOT NULL AND effective_to > effective_from)",
            name="chk_identity_tokens_temporal",
        ),
        ExcludeConstraint(
            (column("cinq_id"), "="),
            (column("effective_period"), "&&"),
            name="excl_identity_tokens_temporal_overlap",
            using="gist",
        ),
        Index("uq_identity_tokens_cinq_id_current", "cinq_id", unique=True, postgresql_where=(column("is_current") == True)),
        Index("ix_identity_tokens_name_dob_current", "last_name_hash", "dob_hash"),
    )


class IdentityCrosswalk(Base):
    """
    Source-to-CINQ Crosswalk mapping external identifiers to internal CINQ IDs.
    Enforces temporal validity and non-overlapping interval exclusion.
    """
    __tablename__ = "identity_crosswalk"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    cinq_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("master_identities.cinq_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_system: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source_identifier_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_period: Mapped[Any] = mapped_column(
        TSTZRANGE,
        Computed("tstzrange(valid_from, valid_to, '[)')", persisted=True),
        nullable=True,
    )
    match_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    match_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_feed_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feeds.id", ondelete="SET NULL"), nullable=True
    )
    source_batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="SET NULL"), nullable=True
    )

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

    master_identity: Mapped["MasterIdentity"] = relationship(
        "MasterIdentity", back_populates="crosswalk_entries"
    )

    __table_args__ = (
        CheckConstraint(
            "(is_active = TRUE AND valid_to IS NULL) OR "
            "(is_active = FALSE AND valid_to IS NOT NULL AND valid_to > valid_from)",
            name="chk_crosswalk_active_temporal_consistency",
        ),
        ExcludeConstraint(
            (column("source_system"), "="),
            (column("source_identifier_hash"), "="),
            (column("valid_period"), "&&"),
            name="excl_crosswalk_temporal_overlap",
            using="gist",
        ),
        Index("ix_crosswalk_source_composite", "source_system", "source_identifier_hash"),
    )


class IdentityException(Base):
    """
    Queue for ambiguous identity candidates and score ties requiring Data Steward review.
    """
    __tablename__ = "identity_exceptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    feed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feeds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_system: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source_identifier_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    record_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    candidate_matches_json: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    highest_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0.00"))
    exception_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default=IdentityExceptionTypeEnum.AMBIGUOUS_MATCH.value, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=IdentityExceptionStatusEnum.PENDING.value, index=True
    )
    assigned_steward: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    resolved_cinq_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("master_identities.cinq_id", ondelete="SET NULL"), nullable=True, index=True
    )
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

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

    decisions: Mapped[List["IdentityDecision"]] = relationship(
        "IdentityDecision", back_populates="exception", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "(status = 'RESOLVED' AND resolution_type IS NOT NULL AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL) OR "
            "(status != 'RESOLVED')",
            name="chk_exception_resolution_consistency",
        ),
        Index("ix_exceptions_batch_status", "batch_id", "status"),
        Index("ix_exceptions_feed_status", "feed_id", "status"),
    )


class IdentityDecision(Base):
    """
    Append-only, immutable audit ledger of every Data Steward resolution.
    Protected by PostgreSQL trigger prohibiting UPDATE and DELETE.
    """
    __tablename__ = "identity_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    exception_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity_exceptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    decision_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    cinq_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("master_identities.cinq_id", ondelete="RESTRICT"), nullable=True, index=True
    )
    decided_by: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    decision_notes: Mapped[str] = mapped_column(Text, nullable=False)
    pre_resolution_state: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    post_resolution_state: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)

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

    exception: Mapped["IdentityException"] = relationship(
        "IdentityException", back_populates="decisions"
    )

    __table_args__ = (
        CheckConstraint(
            "decision_type IN ('LINK_EXISTING', 'CREATE_NEW', 'DEFER')",
            name="chk_decision_type_valid",
        ),
        CheckConstraint(
            "(decision_type IN ('LINK_EXISTING', 'CREATE_NEW') AND cinq_id IS NOT NULL) OR "
            "(decision_type = 'DEFER' AND cinq_id IS NULL)",
            name="chk_decision_cinq_id_semantics",
        ),
        Index("ix_decisions_decided_at", "decided_at"),
    )
