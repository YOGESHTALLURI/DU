'''SQLAlchemy model for batch_stage_checkpoint'''

from sqlalchemy import Column, Text, DateTime, func, Index, PrimaryKeyConstraint
from sqlalchemy.dialects.postgresql import UUID
from backend.models.base import Base

class BatchStageCheckpoint(Base):
    __tablename__ = 'batch_stage_checkpoint'

    execution_id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    batch_id = Column(UUID(as_uuid=True), nullable=False)
    stage_name = Column(Text, nullable=False)
    checkpoint_key = Column(Text, nullable=False)
    checkpoint_value = Column(Text, nullable=False)
    execution_state = Column(Text, nullable=False)
    lease_token = Column(UUID(as_uuid=True), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # optional indexes – created via migration
    __table_args__ = (
        Index('ix_batch_stage_checkpoint_lease_token', 'lease_token'),
        Index('ix_batch_stage_checkpoint_lease_expires_at', 'lease_expires_at'),
    )


class OdsOperationHash(Base):
    __tablename__ = 'ods_operation_hashes'

    op_hash = Column(Text, primary_key=True)
    batch_id = Column(UUID(as_uuid=True), nullable=False)
    cinq_id = Column(UUID(as_uuid=True), nullable=False)
    operation = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        PrimaryKeyConstraint('op_hash', name='ods_op_hash_uniq'),
    )
