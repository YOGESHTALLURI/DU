"""
Audit Service — records immutable audit events for all Wave 0 state changes.

Every call to emit() creates a new AuditEvent row.
AuditEvent rows are NEVER updated or deleted.
"""
import uuid
from typing import Optional, Any
from sqlalchemy.orm import Session
from backend.models.audit import AuditEvent, AuditActionEnum


class AuditService:
    def __init__(self, db: Session):
        self.db = db

    def emit(
        self,
        action: AuditActionEnum,
        actor_id: str,
        actor_email: Optional[str] = None,
        object_type: Optional[str] = None,
        object_id: Optional[str] = None,
        before_state: Optional[dict] = None,
        after_state: Optional[dict] = None,
        description: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> AuditEvent:
        """Emit an immutable audit event. Returns the created event."""
        event = AuditEvent(
            action=action,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type=object_type or "",
            object_id=str(object_id) if object_id else None,
            before_state=before_state,
            after_state=after_state,
            description=description,
            correlation_id=correlation_id,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(event)
        self.db.flush()  # Get the ID without committing
        return event

    @classmethod
    def log(
        cls,
        db: Session,
        action: AuditActionEnum,
        actor_id: str,
        actor_email: Optional[str] = None,
        object_type: Optional[str] = None,
        object_id: Optional[str] = None,
        before_state: Optional[dict] = None,
        after_state: Optional[dict] = None,
        description: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> AuditEvent:
        """Classmethod convenience helper for logging audit events."""
        return cls(db).emit(
            action=action,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type=object_type,
            object_id=object_id,
            before_state=before_state,
            after_state=after_state,
            description=description,
            correlation_id=correlation_id,
        )
