"""
Wave 3 Slice 4 Models: Identity Merge and Split Decisions (CF-V3-E9-03)
Maps to migrations 018_wave4_merge_split_proposal and 019_wave4_merge_split_event.
"""
import uuid
import enum
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import (
    String,
    Integer,
    DateTime,
    ForeignKey,
    CheckConstraint,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.models.base import Base


class ProposalStateEnum(str, enum.Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"


class OperationTypeEnum(str, enum.Enum):
    MERGE = "MERGE"
    SPLIT = "SPLIT"


class IdentityMergeSplitProposal(Base):
    """
    Proposal ledger for identity merge and split decisions.
    Enforces four-eyes approval workflow and client_key idempotency.
    """
    __tablename__ = "identity_merge_split_proposal"

    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    source_cinq_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("master_identities.cinq_id", ondelete="SET NULL"), nullable=True
    )
    target_cinq_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("master_identities.cinq_id", ondelete="SET NULL"), nullable=True
    )
    operation_type: Mapped[str] = mapped_column(String(10), nullable=False)
    source_system: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source_identifier_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    client_key: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ProposalStateEnum.PENDING_APPROVAL.value, server_default="PENDING_APPROVAL"
    )
    proposer_id: Mapped[str] = mapped_column(String(255), nullable=False)
    approver_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    expected_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        nullable=False,
    )

    events: Mapped[List["IdentityMergeSplitEvent"]] = relationship(
        "IdentityMergeSplitEvent", back_populates="proposal", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("state IN ('PENDING_APPROVAL','APPROVED','REJECTED','EXECUTED','FAILED')", name="chk_proposal_state"),
        CheckConstraint("operation_type IN ('MERGE','SPLIT')", name="chk_proposal_operation"),
        Index(
            "uq_active_proposal_client_key",
            "client_key",
            "operation_type",
            unique=True,
            postgresql_where=text("state = 'PENDING_APPROVAL'"),
        ),
    )


class IdentityMergeSplitEvent(Base):
    """
    Append-only temporal ledger of executed merge and split events.
    """
    __tablename__ = "identity_merge_split_event"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity_merge_split_proposal.proposal_id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(10), nullable=False)
    source_cinq_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("master_identities.cinq_id", ondelete="SET NULL"), nullable=True
    )
    target_cinq_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("master_identities.cinq_id", ondelete="SET NULL"), nullable=True
    )
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=text("now()"), nullable=False
    )
    effective_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    actor_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=text("now()"), nullable=False
    )

    proposal: Mapped["IdentityMergeSplitProposal"] = relationship(
        "IdentityMergeSplitProposal", back_populates="events"
    )

    __table_args__ = (
        CheckConstraint("event_type IN ('MERGE','SPLIT')", name="chk_event_type"),
        CheckConstraint("effective_to IS NULL OR effective_to > effective_from", name="chk_event_temporal"),
        Index("ix_event_source", "source_cinq_id"),
        Index("ix_event_target", "target_cinq_id"),
    )
