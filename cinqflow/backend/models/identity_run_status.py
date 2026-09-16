'''SQLAlchemy model for identity_run_status'''

from sqlalchemy import Column, Text, DateTime, func, CheckConstraint, PrimaryKeyConstraint
from sqlalchemy.dialects.postgresql import UUID
from backend.models.base import Base

class IdentityRunStatus(Base):
    __tablename__ = 'identity_run_status'

    batch_id = Column(UUID(as_uuid=True), nullable=False)
    identity_run_id = Column(UUID(as_uuid=True), nullable=False)
    run_status = Column(Text, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        PrimaryKeyConstraint('batch_id', 'identity_run_id', name='pk_identity_run_status'),
        CheckConstraint(
            "(run_status = 'SUCCESS' AND completed_at IS NOT NULL) OR (run_status = 'FAILURE' AND completed_at IS NULL)",
            name='chk_identity_run_status_completed'
        ),
    )
