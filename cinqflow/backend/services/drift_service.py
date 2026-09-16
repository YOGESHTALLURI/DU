"""
Wave 2 Slice 1 Service — Schema Drift Service (CF-V2-E5-04)
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from backend.models.drift import (
    SchemaDriftReport,
    DriftSeverityEnum,
    DriftStatusEnum,
)
from backend.models.audit import AuditActionEnum
from backend.services.audit_service import AuditService


class DriftService:
    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditService(db)

    def list_reports(
        self,
        feed_id: Optional[uuid.UUID] = None,
        batch_id: Optional[uuid.UUID] = None,
        drift_severity: Optional[DriftSeverityEnum] = None,
        drift_status: Optional[DriftStatusEnum] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[SchemaDriftReport], int]:
        query = self.db.query(SchemaDriftReport)

        if feed_id:
            query = query.filter(SchemaDriftReport.feed_id == feed_id)
        if batch_id:
            query = query.filter(SchemaDriftReport.batch_id == batch_id)
        if drift_severity:
            query = query.filter(SchemaDriftReport.drift_severity == drift_severity)
        if drift_status:
            query = query.filter(SchemaDriftReport.status == drift_status)

        total = query.count()
        items = (
            query.order_by(SchemaDriftReport.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return items, total

    def get_report(self, report_id: uuid.UUID) -> SchemaDriftReport:
        report = (
            self.db.query(SchemaDriftReport)
            .filter(SchemaDriftReport.id == report_id)
            .first()
        )
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Schema drift report {report_id} not found",
            )
        return report

    def acknowledge_report(
        self,
        report_id: uuid.UUID,
        actor_id: str,
        actor_email: Optional[str],
        notes: str,
    ) -> SchemaDriftReport:
        report = self.get_report(report_id)

        if report.drift_severity == DriftSeverityEnum.BREAKING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Breaking drift reports cannot be acknowledged; the schema contract must be updated or source file re-delivered",
            )

        report.status = DriftStatusEnum.ACKNOWLEDGED
        report.acknowledged_by = actor_email or actor_id
        report.acknowledged_at = datetime.now(timezone.utc)
        report.acknowledgement_notes = notes
        report.updated_by = actor_email or actor_id

        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.SCHEMA_DRIFT_ACKNOWLEDGED,
            actor_id=actor_id,
            actor_email=actor_email,
            object_type="schema_drift_reports",
            object_id=str(report.id),
            before_state={"status": DriftStatusEnum.DETECTED.value},
            after_state={"status": DriftStatusEnum.ACKNOWLEDGED.value, "notes": notes},
            description=f"Schema drift report {report.id} acknowledged by {actor_email or actor_id}",
        )

        self.db.commit()
        self.db.refresh(report)
        return report
