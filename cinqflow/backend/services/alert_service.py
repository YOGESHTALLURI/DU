"""
Wave 2 Slice 4 Service — Self-Explaining Alerts & Storm Suppression (CF-V2-E12-05)

Deduplicates operational alerts at the database level to suppress alert storms,
maintains alert lifecycle state machine (OPEN -> ACKNOWLEDGED -> RECOVERY_IN_PROGRESS -> RESOLVED -> REOPENED),
generates human-readable explanations, and links failure occurrences.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy import desc, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload
from fastapi import HTTPException, status

from backend.models.incident import (
    OperationalAlert,
    AlertOccurrence,
    FailureFingerprint,
    FailureCategoryEnum,
    AlertStatusEnum,
    AlertSeverityEnum,
)
from backend.models.feed import Feed
from backend.models.pipeline import Batch
from backend.models.audit import AuditEvent, AuditActionEnum
from backend.services.fingerprint_service import FingerprintService
from backend.services.playbook_service import PlaybookService
from backend.engine.arrival_engine import ArrivalEngine


class AlertService:
    """Service layer for operational alert ingestion, storm control, and lifecycle."""

    @classmethod
    def generate_plain_english_explanation(
        cls,
        category: FailureCategoryEnum,
        failure_stage: Optional[str],
        normalized_pattern: str,
        feed_name: str,
    ) -> Tuple[str, str]:
        """
        Translates raw technical failure signatures into clear, non-cryptic plain English.
        Zero PHI exposure guaranteed.
        """
        stg_text = f"stage {failure_stage}" if failure_stage else "ingestion pipeline"
        if category == FailureCategoryEnum.SCHEMA_DRIFT:
            title = f"Breaking Schema Drift on feed '{feed_name}'"
            desc = (
                f"Feed '{feed_name}' failed at {stg_text} due to schema drift: {normalized_pattern}. "
                "The incoming file structure does not conform to the active published schema."
            )
        elif category == FailureCategoryEnum.DATA_QUALITY:
            title = f"Data Quality Rule Violation on feed '{feed_name}'"
            desc = (
                f"Feed '{feed_name}' failed data quality validation in {stg_text}: {normalized_pattern}. "
                "Records violating critical rules were quarantined or caused the batch to abort."
            )
        elif category == FailureCategoryEnum.STAGE_EXECUTION:
            title = f"Pipeline Execution Error in {stg_text} for '{feed_name}'"
            desc = (
                f"Execution error occurred while processing feed '{feed_name}' in {stg_text}: {normalized_pattern}. "
                "Prior stages completed safely."
            )
        elif category == FailureCategoryEnum.RECONCILIATION:
            title = f"Reconciliation Balance Failure for '{feed_name}'"
            desc = (
                f"Record count balance check failed for feed '{feed_name}': {normalized_pattern}. "
                "Records may have dropped unexpectedly between transformation stages."
            )
        elif category == FailureCategoryEnum.DEPENDENCY_GATE:
            title = f"Upstream Dependency Gate Blocked for '{feed_name}'"
            desc = (
                f"Feed '{feed_name}' cannot run because a required upstream dependency failed or has not arrived: {normalized_pattern}."
            )
        else:
            title = f"Operational Failure in {stg_text} for '{feed_name}'"
            desc = f"Failure occurred on feed '{feed_name}' during {stg_text}: {normalized_pattern}."

        return title[:255], desc

    @classmethod
    def record_failure(
        cls,
        db: Session,
        feed_id: uuid.UUID,
        category: FailureCategoryEnum,
        failure_stage: Optional[str],
        root_cause_pattern: str,
        batch_id: Optional[uuid.UUID] = None,
        error_context: Optional[Dict[str, Any]] = None,
        severity: AlertSeverityEnum = AlertSeverityEnum.CRITICAL,
        user_id: str = "system",
    ) -> OperationalAlert:
        """
        Ingests a failure event, fingerprints it deterministically, and suppresses alert storms.
        If an active alert exists for (feed_id, fingerprint), updates occurrence count without creating duplicates.
        Detects flapping: if resolved within 2 hours, transitions back to REOPENED.
        """
        now_utc = datetime.now(timezone.utc)

        # 1. Resolve or create deterministic failure fingerprint
        fingerprint = FingerprintService.get_or_create_fingerprint(
            db=db,
            category=category,
            failure_stage=failure_stage,
            root_cause_pattern=root_cause_pattern,
            user_id=user_id,
        )

        # 2. Sanitize context for zero-PHI storage
        sanitized_context = {}
        if error_context:
            for k, v in error_context.items():
                if isinstance(v, str):
                    sanitized_context[k] = FingerprintService.sanitize_and_normalize(v)
                else:
                    sanitized_context[k] = v

        # 3. Check for active alert (OPEN, ACKNOWLEDGED, RECOVERY_IN_PROGRESS, REOPENED)
        active_statuses = [
            AlertStatusEnum.OPEN,
            AlertStatusEnum.ACKNOWLEDGED,
            AlertStatusEnum.RECOVERY_IN_PROGRESS,
            AlertStatusEnum.REOPENED,
        ]

        active_alert = (
            db.query(OperationalAlert)
            .filter(
                OperationalAlert.feed_id == feed_id,
                OperationalAlert.failure_fingerprint_id == fingerprint.id,
                OperationalAlert.status.in_(active_statuses),
            )
            .with_for_update()
            .first()
        )

        if active_alert:
            # DEDUPLICATION: Alert storm suppression in action
            active_alert.occurrence_count += 1
            active_alert.last_occurred_at = now_utc
            if batch_id:
                active_alert.batch_id = batch_id
            active_alert.updated_at = now_utc
            active_alert.updated_by = user_id

            # Append occurrence
            occurrence = AlertOccurrence(
                alert_id=active_alert.id,
                batch_id=batch_id,
                stage=failure_stage,
                error_context=sanitized_context,
                occurred_at=now_utc,
                created_by=user_id,
                updated_by=user_id,
            )
            db.add(occurrence)
            db.flush()
            return active_alert

        # 4. Check for flapping: recently resolved within 2 hours
        two_hours_ago = now_utc - timedelta(hours=2)
        recently_resolved = (
            db.query(OperationalAlert)
            .filter(
                OperationalAlert.feed_id == feed_id,
                OperationalAlert.failure_fingerprint_id == fingerprint.id,
                OperationalAlert.status == AlertStatusEnum.RESOLVED,
                OperationalAlert.resolved_at >= two_hours_ago,
            )
            .order_by(OperationalAlert.resolved_at.desc())
            .with_for_update()
            .first()
        )

        if recently_resolved:
            # Flapping detection: reopen the alert
            recently_resolved.status = AlertStatusEnum.REOPENED
            recently_resolved.occurrence_count += 1
            recently_resolved.last_occurred_at = now_utc
            if batch_id:
                recently_resolved.batch_id = batch_id
            recently_resolved.resolution_notes = (
                f"[FLAPPING REOPENED at {now_utc.isoformat()}]: Recurred within 2-hour resolution window. "
                + (recently_resolved.resolution_notes or "")
            )
            recently_resolved.updated_at = now_utc
            recently_resolved.updated_by = user_id

            occurrence = AlertOccurrence(
                alert_id=recently_resolved.id,
                batch_id=batch_id,
                stage=failure_stage,
                error_context=sanitized_context,
                occurred_at=now_utc,
                created_by=user_id,
                updated_by=user_id,
            )
            db.add(occurrence)
            db.flush()

            db.add(
                AuditEvent(
                    action=AuditActionEnum.OPS_ALERT_REOPENED,
                    object_type="operational_alert",
                    object_id=str(recently_resolved.id),
                    actor_id=user_id,
                    description="Operational alert reopened due to flapping failure",
                    after_state={"reason": "Flapping: recurring failure within 2 hours of resolution"},
                    created_by=user_id,
                    updated_by=user_id,
                )
            )
            db.flush()
            return recently_resolved

        # 5. Create brand new alert with concurrency conflict protection (Blocker 8)
        feed = db.query(Feed).filter(Feed.id == feed_id).first()
        feed_name = feed.name if feed else str(feed_id)

        title, desc = cls.generate_plain_english_explanation(
            category=category,
            failure_stage=failure_stage,
            normalized_pattern=fingerprint.root_cause_pattern,
            feed_name=feed_name,
        )

        # Match recommended playbook version
        matching_version = PlaybookService.find_matching_playbook_version(db=db, fingerprint=fingerprint)
        matching_ver_id = matching_version.id if matching_version else None

        new_alert = OperationalAlert(
            feed_id=feed_id,
            batch_id=batch_id,
            failure_fingerprint_id=fingerprint.id,
            recommended_playbook_version_id=matching_ver_id,
            title=title,
            description=desc,
            severity=severity,
            status=AlertStatusEnum.OPEN,
            occurrence_count=1,
            first_occurred_at=now_utc,
            last_occurred_at=now_utc,
            created_by=user_id,
            updated_by=user_id,
        )

        try:
            with db.begin_nested():
                db.add(new_alert)
                db.flush()

                occurrence = AlertOccurrence(
                    alert_id=new_alert.id,
                    batch_id=batch_id,
                    stage=failure_stage,
                    error_context=sanitized_context,
                    occurred_at=now_utc,
                    created_by=user_id,
                    updated_by=user_id,
                )
                db.add(occurrence)
                db.flush()

                db.add(
                    AuditEvent(
                        action=AuditActionEnum.OPS_ALERT_CREATED,
                        object_type="operational_alert",
                        object_id=str(new_alert.id),
                        actor_id=user_id,
                        description=f"Operational alert created: {new_alert.title}",
                        after_state={
                            "feed_id": str(feed_id),
                            "fingerprint_hash": fingerprint.fingerprint_hash,
                            "category": category.value if hasattr(category, "value") else str(category),
                            "severity": severity.value if hasattr(severity, "value") else str(severity),
                        },
                        created_by=user_id,
                        updated_by=user_id,
                    )
                )
                db.flush()
                return new_alert

        except IntegrityError:
            # Concurrent worker created an active alert on the partial unique index
            active_alert = (
                db.query(OperationalAlert)
                .filter(
                    OperationalAlert.feed_id == feed_id,
                    OperationalAlert.failure_fingerprint_id == fingerprint.id,
                    OperationalAlert.status.in_(active_statuses),
                )
                .with_for_update()
                .first()
            )
            if active_alert:
                active_alert.occurrence_count += 1
                active_alert.last_occurred_at = now_utc
                if batch_id:
                    active_alert.batch_id = batch_id
                active_alert.updated_at = now_utc
                active_alert.updated_by = user_id

                occurrence = AlertOccurrence(
                    alert_id=active_alert.id,
                    batch_id=batch_id,
                    stage=failure_stage,
                    error_context=sanitized_context,
                    occurred_at=now_utc,
                    created_by=user_id,
                    updated_by=user_id,
                )
                db.add(occurrence)
                db.flush()
                return active_alert
            raise

    @classmethod
    def start_recovery(cls, db: Session, alert_id: uuid.UUID, user_id: str) -> OperationalAlert:
        """Transitions an alert to RECOVERY_IN_PROGRESS."""
        alert = db.query(OperationalAlert).filter(OperationalAlert.id == alert_id).with_for_update().first()
        if not alert:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")

        if alert.status == AlertStatusEnum.RESOLVED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot start recovery on an already RESOLVED alert. Reopen it first.",
            )

        now_utc = datetime.now(timezone.utc)
        alert.status = AlertStatusEnum.RECOVERY_IN_PROGRESS
        alert.updated_at = now_utc
        alert.updated_by = user_id
        db.flush()

        db.add(
            AuditEvent(
                action=AuditActionEnum.OPS_ALERT_ACKNOWLEDGED,
                object_type="operational_alert",
                object_id=str(alert.id),
                actor_id=user_id,
                description=f"Operational alert recovery started by {user_id}",
                after_state={"status": "RECOVERY_IN_PROGRESS"},
                created_by=user_id,
                updated_by=user_id,
            )
        )
        db.flush()
        return alert

    @classmethod
    def acknowledge_alert(cls, db: Session, alert_id: uuid.UUID, user_id: str) -> OperationalAlert:
        """Transitions an alert from OPEN or REOPENED to ACKNOWLEDGED."""
        alert = db.query(OperationalAlert).filter(OperationalAlert.id == alert_id).with_for_update().first()
        if not alert:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")

        if alert.status in [AlertStatusEnum.RESOLVED]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot acknowledge a resolved alert (current status: {alert.status.value}).",
            )

        now_utc = datetime.now(timezone.utc)
        alert.status = AlertStatusEnum.ACKNOWLEDGED
        alert.acknowledged_at = now_utc
        alert.acknowledged_by = user_id
        alert.updated_at = now_utc
        alert.updated_by = user_id
        db.flush()

        db.add(
            AuditEvent(
                action=AuditActionEnum.OPS_ALERT_ACKNOWLEDGED,
                object_type="operational_alert",
                object_id=str(alert.id),
                actor_id=user_id,
                description=f"Operational alert acknowledged by {user_id}",
                after_state={"status": "ACKNOWLEDGED"},
                created_by=user_id,
                updated_by=user_id,
            )
        )
        db.flush()
        return alert

    @classmethod
    def resolve_alert(
        cls,
        db: Session,
        alert_id: uuid.UUID,
        resolution_notes: Optional[str],
        user_id: str,
    ) -> OperationalAlert:
        """Transitions an alert to RESOLVED with explanation notes."""
        alert = db.query(OperationalAlert).filter(OperationalAlert.id == alert_id).with_for_update().first()
        if not alert:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")

        if alert.status == AlertStatusEnum.RESOLVED:
            return alert

        now_utc = datetime.now(timezone.utc)
        alert.status = AlertStatusEnum.RESOLVED
        alert.resolved_at = now_utc
        alert.resolved_by = user_id
        alert.resolution_notes = resolution_notes or "Resolved by operator."
        alert.updated_at = now_utc
        alert.updated_by = user_id
        db.flush()

        db.add(
            AuditEvent(
                action=AuditActionEnum.OPS_ALERT_RESOLVED,
                object_type="operational_alert",
                object_id=str(alert.id),
                actor_id=user_id,
                description=f"Operational alert resolved by {user_id}",
                after_state={"resolution_notes": alert.resolution_notes},
                created_by=user_id,
                updated_by=user_id,
            )
        )
        db.flush()
        return alert

    @classmethod
    def reopen_alert(
        cls,
        db: Session,
        alert_id: uuid.UUID,
        reason: Optional[str],
        user_id: str,
    ) -> OperationalAlert:
        """Explicitly reopens a RESOLVED alert."""
        alert = db.query(OperationalAlert).filter(OperationalAlert.id == alert_id).with_for_update().first()
        if not alert:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")

        now_utc = datetime.now(timezone.utc)
        alert.status = AlertStatusEnum.REOPENED
        alert.resolution_notes = (alert.resolution_notes or "") + f" [Reopened: {reason or 'Operator intervention'}]"
        alert.updated_at = now_utc
        alert.updated_by = user_id
        db.flush()

        db.add(
            AuditEvent(
                action=AuditActionEnum.OPS_ALERT_REOPENED,
                object_type="operational_alert",
                object_id=str(alert.id),
                actor_id=user_id,
                description=f"Operational alert reopened: {reason}",
                after_state={"reason": reason},
                created_by=user_id,
                updated_by=user_id,
            )
        )
        db.flush()
        return alert

    @classmethod
    def list_alerts(
        cls,
        db: Session,
        status_filter: Optional[AlertStatusEnum] = None,
        severity_filter: Optional[AlertSeverityEnum] = None,
        feed_id: Optional[uuid.UUID] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[OperationalAlert]:
        """Lists alerts with rich preloaded relationships."""
        q = (
            db.query(OperationalAlert)
            .options(
                joinedload(OperationalAlert.feed),
                joinedload(OperationalAlert.fingerprint),
                joinedload(OperationalAlert.recommended_playbook_version),
                selectinload(OperationalAlert.occurrences),
            )
            .order_by(desc(OperationalAlert.last_occurred_at))
        )

        if status_filter:
            q = q.filter(OperationalAlert.status == status_filter)
        if severity_filter:
            q = q.filter(OperationalAlert.severity == severity_filter)
        if feed_id:
            q = q.filter(OperationalAlert.feed_id == feed_id)

        return q.offset(offset).limit(limit).all()

    @classmethod
    def get_alert_detail(cls, db: Session, alert_id: uuid.UUID) -> OperationalAlert:
        """Retrieves an alert with full detail, occurrences, fingerprint, and playbook."""
        alert = (
            db.query(OperationalAlert)
            .options(
                joinedload(OperationalAlert.feed),
                joinedload(OperationalAlert.fingerprint),
                joinedload(OperationalAlert.recommended_playbook_version),
                selectinload(OperationalAlert.occurrences),
            )
            .filter(OperationalAlert.id == alert_id)
            .first()
        )
        if not alert:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
        return alert
