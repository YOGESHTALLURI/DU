"""
Wave 2 Slice 4 Service — Recovery Playbook Management & Matching (CF-V2-E12-04)

Manages version-pinned standard operating procedures (SOPs), playbook governance,
and matching to failure fingerprints. Playbooks are advisory and strictly integrate
with the Slice 3 Governed Action Surface.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc
from fastapi import HTTPException, status

from backend.models.incident import (
    RecoveryPlaybook,
    RecoveryPlaybookVersion,
    FingerprintPlaybookBinding,
    FailureFingerprint,
    FailureCategoryEnum,
    PlaybookStatusEnum,
)
from backend.models.ops_action import ActionTypeEnum, ActionRiskLevelEnum
from backend.models.pipeline import Batch, BatchStatusEnum
from backend.models.schedule import FeedSchedule, ScheduleStatusEnum
from backend.models.input_registry import QuarantineRecord, QuarantineStatusEnum
from backend.models.audit import AuditEvent, AuditActionEnum
from backend.services.fingerprint_service import FingerprintService


class PlaybookService:
    """Service layer for recovery playbook lifecycle and matching."""

    @classmethod
    def create_playbook(
        cls,
        db: Session,
        title: str,
        category: FailureCategoryEnum,
        playbook_code: str,
        explanation_template: str,
        suggested_action_type: Optional[ActionTypeEnum] = None,
        action_parameters_template: Optional[Dict[str, Any]] = None,
        manual_steps_markdown: str = "",
        prerequisites: Optional[List[Any]] = None,
        risk_assessment: str = "",
        user_id: str = "system",
    ) -> RecoveryPlaybook:
        """Creates a new playbook with initial version 1 in DRAFT state. Enforces Zero-PHI storage."""
        existing = db.query(RecoveryPlaybook).filter(RecoveryPlaybook.playbook_code == playbook_code).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Playbook with code '{playbook_code}' already exists.",
            )

        clean_title = FingerprintService.sanitize_zero_phi(title)
        clean_explanation = FingerprintService.sanitize_zero_phi(explanation_template)
        clean_steps = FingerprintService.sanitize_zero_phi(manual_steps_markdown)
        clean_risk = FingerprintService.sanitize_zero_phi(risk_assessment)
        clean_params = FingerprintService.sanitize_zero_phi_dict(action_parameters_template or {})
        clean_prereqs = FingerprintService.sanitize_zero_phi_dict(prerequisites or [])

        now_utc = datetime.now(timezone.utc)
        playbook = RecoveryPlaybook(
            title=clean_title,
            category=category,
            playbook_code=playbook_code,
            status=PlaybookStatusEnum.DRAFT,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(playbook)
        db.flush()

        version = RecoveryPlaybookVersion(
            playbook_id=playbook.id,
            version_number=1,
            explanation_template=clean_explanation,
            suggested_action_type=suggested_action_type,
            action_parameters_template=clean_params,
            manual_steps_markdown=clean_steps,
            prerequisites=clean_prereqs,
            risk_assessment=clean_risk,
            status=PlaybookStatusEnum.DRAFT,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(version)
        db.flush()

        playbook.current_version_id = version.id
        db.flush()

        db.add(
            AuditEvent(
                action=AuditActionEnum.OPS_PLAYBOOK_CREATED,
                object_type="recovery_playbook",
                object_id=str(playbook.id),
                actor_id=user_id,
                description=f"Recovery playbook created: {playbook_code}",
                after_state={"playbook_code": playbook_code, "version": 1},
                created_by=user_id,
                updated_by=user_id,
            )
        )
        db.flush()
        return playbook

    @classmethod
    def update_playbook(
        cls,
        db: Session,
        playbook_id: uuid.UUID,
        explanation_template: Optional[str] = None,
        suggested_action_type: Optional[ActionTypeEnum] = None,
        action_parameters_template: Optional[Dict[str, Any]] = None,
        manual_steps_markdown: Optional[str] = None,
        prerequisites: Optional[List[Any]] = None,
        risk_assessment: Optional[str] = None,
        user_id: str = "system",
    ) -> RecoveryPlaybookVersion:
        """
        Creates a new immutable version under the specified playbook.
        Preserves previous versions for historical audit reproducibility.
        Enforces Zero-PHI storage across all fields.
        """
        playbook = db.query(RecoveryPlaybook).filter(RecoveryPlaybook.id == playbook_id).first()
        if not playbook:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playbook not found")

        max_ver = (
            db.query(RecoveryPlaybookVersion.version_number)
            .filter(RecoveryPlaybookVersion.playbook_id == playbook_id)
            .order_by(RecoveryPlaybookVersion.version_number.desc())
            .first()
        )
        next_ver_num = (max_ver[0] + 1) if max_ver else 1

        curr_ver = (
            db.query(RecoveryPlaybookVersion)
            .filter(RecoveryPlaybookVersion.id == playbook.current_version_id)
            .first()
        )

        clean_explanation = (
            FingerprintService.sanitize_zero_phi(explanation_template)
            if explanation_template is not None
            else (curr_ver.explanation_template if curr_ver else "")
        )
        clean_steps = (
            FingerprintService.sanitize_zero_phi(manual_steps_markdown)
            if manual_steps_markdown is not None
            else (curr_ver.manual_steps_markdown if curr_ver else "")
        )
        clean_risk = (
            FingerprintService.sanitize_zero_phi(risk_assessment)
            if risk_assessment is not None
            else (curr_ver.risk_assessment if curr_ver else "")
        )
        clean_params = (
            FingerprintService.sanitize_zero_phi_dict(action_parameters_template)
            if action_parameters_template is not None
            else (curr_ver.action_parameters_template if curr_ver else {})
        )
        clean_prereqs = (
            FingerprintService.sanitize_zero_phi_dict(prerequisites)
            if prerequisites is not None
            else (curr_ver.prerequisites if curr_ver else [])
        )

        new_version = RecoveryPlaybookVersion(
            playbook_id=playbook.id,
            version_number=next_ver_num,
            explanation_template=clean_explanation,
            suggested_action_type=suggested_action_type if suggested_action_type is not None else (curr_ver.suggested_action_type if curr_ver else None),
            action_parameters_template=clean_params,
            manual_steps_markdown=clean_steps,
            prerequisites=clean_prereqs,
            risk_assessment=clean_risk,
            status=PlaybookStatusEnum.DRAFT,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(new_version)
        db.flush()

        db.add(
            AuditEvent(
                action=AuditActionEnum.OPS_PLAYBOOK_UPDATED,
                object_type="recovery_playbook",
                object_id=str(playbook.id),
                actor_id=user_id,
                description=f"Recovery playbook updated to version {next_ver_num}",
                after_state={"version_number": next_ver_num},
                created_by=user_id,
                updated_by=user_id,
            )
        )
        db.flush()
        return new_version

    @classmethod
    def approve_playbook_version(
        cls,
        db: Session,
        version_id: uuid.UUID,
        approved_by: str,
    ) -> RecoveryPlaybook:
        """
        Approves a playbook version, sets it as current active version, and marks playbook APPROVED.
        """
        version = db.query(RecoveryPlaybookVersion).filter(RecoveryPlaybookVersion.id == version_id).first()
        if not version:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playbook version not found")

        playbook = db.query(RecoveryPlaybook).filter(RecoveryPlaybook.id == version.playbook_id).first()
        now_utc = datetime.now(timezone.utc)

        version.status = PlaybookStatusEnum.APPROVED
        version.approved_by = approved_by
        version.approved_at = now_utc
        version.updated_at = now_utc
        version.updated_by = approved_by

        playbook.current_version_id = version.id
        playbook.status = PlaybookStatusEnum.APPROVED
        playbook.updated_at = now_utc
        playbook.updated_by = approved_by

        db.flush()

        db.add(
            AuditEvent(
                action=AuditActionEnum.OPS_PLAYBOOK_APPROVED,
                object_type="recovery_playbook",
                object_id=str(playbook.id),
                actor_id=approved_by,
                description=f"Recovery playbook version {version.version_number} approved",
                after_state={"version_id": str(version.id), "version_number": version.version_number},
                created_by=approved_by,
                updated_by=approved_by,
            )
        )
        db.flush()
        return playbook

    @classmethod
    def deprecate_playbook(
        cls,
        db: Session,
        playbook_id: uuid.UUID,
        user_id: str,
    ) -> RecoveryPlaybook:
        """Marks playbook and current version as DEPRECATED."""
        playbook = db.query(RecoveryPlaybook).filter(RecoveryPlaybook.id == playbook_id).first()
        if not playbook:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playbook not found")

        now_utc = datetime.now(timezone.utc)
        playbook.status = PlaybookStatusEnum.DEPRECATED
        playbook.updated_at = now_utc
        playbook.updated_by = user_id

        if playbook.current_version_id:
            ver = db.query(RecoveryPlaybookVersion).filter(RecoveryPlaybookVersion.id == playbook.current_version_id).first()
            if ver:
                ver.status = PlaybookStatusEnum.DEPRECATED
                ver.updated_at = now_utc
                ver.updated_by = user_id

        db.flush()
        db.add(
            AuditEvent(
                action=AuditActionEnum.OPS_PLAYBOOK_DEPRECATED,
                object_type="recovery_playbook",
                object_id=str(playbook.id),
                actor_id=user_id,
                description="Recovery playbook deprecated",
                after_state={"status": "DEPRECATED"},
                created_by=user_id,
                updated_by=user_id,
            )
        )
        db.flush()
        return playbook

    @classmethod
    def bind_fingerprint(
        cls,
        db: Session,
        fingerprint_id: uuid.UUID,
        playbook_id: uuid.UUID,
        priority: int = 100,
        user_id: str = "system",
    ) -> FingerprintPlaybookBinding:
        """Binds a fingerprint to a playbook with specific priority."""
        existing = (
            db.query(FingerprintPlaybookBinding)
            .filter(
                FingerprintPlaybookBinding.fingerprint_id == fingerprint_id,
                FingerprintPlaybookBinding.playbook_id == playbook_id,
            )
            .first()
        )
        if existing:
            existing.priority = priority
            existing.is_active = True
            existing.updated_by = user_id
            db.flush()
            return existing

        binding = FingerprintPlaybookBinding(
            fingerprint_id=fingerprint_id,
            playbook_id=playbook_id,
            priority=priority,
            is_active=True,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(binding)
        db.flush()
        return binding

    @classmethod
    def find_matching_playbook_version(
        cls,
        db: Session,
        fingerprint: FailureFingerprint,
    ) -> Optional[RecoveryPlaybookVersion]:
        """
        Finds the best matching active playbook version for a given fingerprint.
        1. Checks explicit bindings ordered by priority ASC.
        2. Fallback to category-level default playbook with status APPROVED.
        """
        binding = (
            db.query(FingerprintPlaybookBinding)
            .join(RecoveryPlaybook, FingerprintPlaybookBinding.playbook_id == RecoveryPlaybook.id)
            .filter(
                FingerprintPlaybookBinding.fingerprint_id == fingerprint.id,
                FingerprintPlaybookBinding.is_active == True,
                RecoveryPlaybook.status == PlaybookStatusEnum.APPROVED,
            )
            .order_by(FingerprintPlaybookBinding.priority.asc())
            .first()
        )

        if binding and binding.playbook and binding.playbook.current_version_id:
            ver = (
                db.query(RecoveryPlaybookVersion)
                .filter(
                    RecoveryPlaybookVersion.id == binding.playbook.current_version_id,
                    RecoveryPlaybookVersion.status == PlaybookStatusEnum.APPROVED,
                )
                .first()
            )
            if ver:
                return ver

        # Fallback: category-level playbook
        cat_playbook = (
            db.query(RecoveryPlaybook)
            .filter(
                RecoveryPlaybook.category == fingerprint.category,
                RecoveryPlaybook.status == PlaybookStatusEnum.APPROVED,
            )
            .order_by(RecoveryPlaybook.created_at.asc())
            .first()
        )
        if cat_playbook and cat_playbook.current_version_id:
            return (
                db.query(RecoveryPlaybookVersion)
                .filter(
                    RecoveryPlaybookVersion.id == cat_playbook.current_version_id,
                    RecoveryPlaybookVersion.status == PlaybookStatusEnum.APPROVED,
                )
                .first()
            )

        return None

    @classmethod
    def seed_default_playbooks(cls, db: Session, user_id: str = "system") -> None:
        """Seeds standard operational recovery playbooks if not already present."""
        defaults = [
            {
                "code": "PB-DRIFT-001",
                "title": "Breaking Schema Drift Remediation",
                "category": FailureCategoryEnum.SCHEMA_DRIFT,
                "explanation": "A breaking schema drift event was detected at ingestion. Unregistered columns, missing required fields, or type incompatibilities prevent safe parsing.",
                "action": None,
                "steps": "1. Review schema drift report in Onboarding / Feed Details.\n2. Coordinate with source system data provider or publish a new feed schema version.\n3. Re-trigger batch once updated schema is published.",
                "risk": "High - changing schema impacts downstream tables.",
            },
            {
                "code": "PB-DQ-001",
                "title": "Critical Data Quality Rule Abort",
                "category": FailureCategoryEnum.DATA_QUALITY,
                "explanation": "Batch was aborted due to critical data quality rule violation exceeding acceptable threshold.",
                "action": ActionTypeEnum.REPROCESS_QUARANTINE,
                "steps": "1. Inspect quarantine records for the aborted batch.\n2. If records can be remediated or rule threshold adjusted, reprocess quarantine.\n3. If records are unrecoverable, discard invalid quarantine rows under four-eyes control.",
                "risk": "Medium - quarantine reprocessing writes to Silver Raw.",
            },
            {
                "code": "PB-STAGE-001",
                "title": "Pipeline Stage Transient Error Recovery",
                "category": FailureCategoryEnum.STAGE_EXECUTION,
                "explanation": "Pipeline stage failed due to an execution error. Upstream stages already completed successfully and will not be re-run.",
                "action": ActionTypeEnum.RESTART_BATCH,
                "steps": "1. Check stage execution logs for the failed stage.\n2. Verify network and database resources.\n3. Request batch restart from failed stage boundary.",
                "risk": "Standard - restarts safely from first non-success stage.",
            },
            {
                "code": "PB-RECON-001",
                "title": "Reconciliation Balance Mismatch",
                "category": FailureCategoryEnum.RECONCILIATION,
                "explanation": "Record balance check failed between Landing, Bronze, and Silver Raw records.",
                "action": None,
                "steps": "1. Review reconciliation ledger entries for dropped rows.\n2. Confirm if dropped rows were quarantined or discarded.\n3. Investigate pipeline transformation logic.",
                "risk": "High - potential silent data loss.",
            },
        ]

        for d in defaults:
            existing = db.query(RecoveryPlaybook).filter(RecoveryPlaybook.playbook_code == d["code"]).first()
            if not existing:
                pb = cls.create_playbook(
                    db=db,
                    title=d["title"],
                    category=d["category"],
                    playbook_code=d["code"],
                    explanation_template=d["explanation"],
                    suggested_action_type=d["action"],
                    manual_steps_markdown=d["steps"],
                    risk_assessment=d["risk"],
                    user_id=user_id,
                )
                if pb.current_version_id:
                    cls.approve_playbook_version(db=db, version_id=pb.current_version_id, approved_by=user_id)

    @classmethod
    def evaluate_playbook_preconditions(
        cls,
        db: Session,
        playbook_version: RecoveryPlaybookVersion,
        alert: Any,
    ) -> Dict[str, Any]:
        """
        Derives the governed-action target from the playbook's suggested action type
        and evaluates safety preconditions against real database state.
        (Wave 2 Slice 4 Blockers 1, 2, 6)
        """
        action_type = playbook_version.suggested_action_type
        if not action_type:
            return {
                "action_type": None,
                "target_type": None,
                "target_id": None,
                "parameters": {"alert_id": str(alert.id)},
                "is_executable": False,
                "blocking_reason": "Playbook does not specify an automated action; follow manual steps.",
                "risk_level": None,
            }

        act_type_enum = action_type if isinstance(action_type, ActionTypeEnum) else ActionTypeEnum(str(action_type))
        parameters = dict(playbook_version.action_parameters_template or {})
        parameters["alert_id"] = str(alert.id)

        target_type = None
        target_id = None
        is_executable = True
        blocking_reason = None

        if act_type_enum in [ActionTypeEnum.RESTART_BATCH, ActionTypeEnum.RETRIGGER_BATCH]:
            target_type = "BATCH"
            if not alert.batch_id:
                is_executable = False
                blocking_reason = "No batch associated with this alert."
            else:
                target_id = str(alert.batch_id)
                batch = db.query(Batch).filter(Batch.id == alert.batch_id).first()
                if not batch:
                    is_executable = False
                    blocking_reason = f"Batch {alert.batch_id} not found."
                elif act_type_enum == ActionTypeEnum.RESTART_BATCH:
                    if batch.status not in [BatchStatusEnum.FAILED, BatchStatusEnum.FAILED_RECONCILIATION]:
                        is_executable = False
                        blocking_reason = f"Precondition failed: Batch {batch.id} is in status '{batch.status.value}'; RESTART_BATCH requires FAILED or FAILED_RECONCILIATION."
                elif act_type_enum == ActionTypeEnum.RETRIGGER_BATCH:
                    if batch.status != BatchStatusEnum.SUCCESS:
                        is_executable = False
                        blocking_reason = f"Precondition failed: Batch {batch.id} is in status '{batch.status.value}'; RETRIGGER_BATCH requires SUCCESS."

        elif act_type_enum in [ActionTypeEnum.PAUSE_SCHEDULE, ActionTypeEnum.RESUME_SCHEDULE]:
            target_type = "FEED_SCHEDULE"
            sched = db.query(FeedSchedule).filter(FeedSchedule.feed_id == alert.feed_id).first()
            if not sched:
                is_executable = False
                blocking_reason = f"No feed schedule configured for feed {alert.feed_id}."
            else:
                target_id = str(sched.id)
                if act_type_enum == ActionTypeEnum.PAUSE_SCHEDULE:
                    if sched.status != ScheduleStatusEnum.ACTIVE:
                        is_executable = False
                        blocking_reason = f"Precondition failed: Feed schedule is in status '{sched.status.value}'; PAUSE_SCHEDULE requires ACTIVE."
                elif act_type_enum == ActionTypeEnum.RESUME_SCHEDULE:
                    if sched.status != ScheduleStatusEnum.PAUSED:
                        is_executable = False
                        blocking_reason = f"Precondition failed: Feed schedule is in status '{sched.status.value}'; RESUME_SCHEDULE requires PAUSED."

        elif act_type_enum in [ActionTypeEnum.REPROCESS_QUARANTINE, ActionTypeEnum.BULK_REPROCESS_QUARANTINE, ActionTypeEnum.DISCARD_QUARANTINE]:
            target_type = "QUARANTINE_RECORD"
            # Look up quarantine records for this batch/feed
            q_query = db.query(QuarantineRecord).filter(QuarantineRecord.status == QuarantineStatusEnum.QUARANTINED)
            if alert.batch_id:
                q_records = q_query.filter(QuarantineRecord.batch_id == alert.batch_id).all()
            else:
                q_records = q_query.join(Batch, QuarantineRecord.batch_id == Batch.id).filter(Batch.feed_id == alert.feed_id).all()

            if not q_records:
                is_executable = False
                blocking_reason = "Precondition failed: No active QUARANTINED records found for this batch/feed."
            else:
                target_id = str(q_records[0].id)
                parameters["record_ids"] = [str(r.id) for r in q_records]

        else:
            is_executable = False
            blocking_reason = f"Unsupported playbook action type: {act_type_enum.value}"

        from backend.services.ops_action_service import OpsActionService
        risk_level = OpsActionService.classify_risk(act_type_enum, parameters)

        return {
            "action_type": act_type_enum,
            "target_type": target_type,
            "target_id": target_id,
            "parameters": parameters,
            "is_executable": is_executable,
            "blocking_reason": blocking_reason,
            "risk_level": risk_level.value,
        }

