"""
ODS Certification & Consumer Compatibility Gate Service (CF-V3-E10-03).
Enforces Four-Eyes segregation, prerequisites validation (Identity SUCCESS, published model version),
Zero-PHI audit logging, and certified view gating.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from backend.models.ods import (
    OdsModelVersion,
    OdsModelVersionStatusEnum,
    OdsCertification,
    OdsCertificationStatusEnum,
)
from backend.models.pipeline import Batch, BatchStatusEnum, StageStatusEnum
from backend.models.identity_run_status import IdentityRunStatus
from backend.models.reconciliation import ReconciliationStatusEnum
from backend.models.dq_result import DQResult, DQActionTakenEnum
from backend.models.audit import AuditEvent, AuditActionEnum
from backend.schemas.ods import OdsCertifyBatchRequest
from backend.schemas.identity import validate_decision_notes_non_phi


class OdsCertificationService:
    """Authoritative service for ODS batch certification and consumer compatibility gating."""

    @classmethod
    def evaluate_batch_eligibility(
        cls, db: Session, batch_id: uuid.UUID
    ) -> Dict[str, Any]:
        """
        Evaluates batch prerequisites for ODS certification:
        1. Batch exists and terminal status == SUCCESS
        2. Identity stage status in identity_run_status == SUCCESS
        3. Associated ODS Model Version exists and status == PUBLISHED
        4. All pipeline stages completed successfully
        """
        batch = db.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Batch '{batch_id}' not found.",
            )

        disqualifying_reasons: List[str] = []

        # 1. Batch status check
        if batch.status != BatchStatusEnum.SUCCESS:
            disqualifying_reasons.append(
                f"Batch status is '{batch.status.value}', must be SUCCESS to certify"
            )

        # 2. Pipeline stages check
        for stage in batch.stages:
            if stage.status != StageStatusEnum.SUCCESS and stage.status != StageStatusEnum.SKIPPED:
                disqualifying_reasons.append(
                    f"Pipeline stage '{stage.stage_name.value}' is in status '{stage.status.value}'"
                )

        # 3. Model version check
        model_version = None
        if not batch.ods_model_version_id:
            disqualifying_reasons.append("Batch does not have an associated ODS model version")
        else:
            model_version = (
                db.query(OdsModelVersion)
                .filter(OdsModelVersion.id == batch.ods_model_version_id)
                .first()
            )
            if not model_version:
                disqualifying_reasons.append(
                    f"ODS model version '{batch.ods_model_version_id}' does not exist"
                )
            elif model_version.status != OdsModelVersionStatusEnum.PUBLISHED.value:
                disqualifying_reasons.append(
                    f"ODS model version v{model_version.version_number} is '{model_version.status}', must be PUBLISHED"
                )

        # 4. Identity stage execution status check
        id_run = (
            db.query(IdentityRunStatus)
            .filter(IdentityRunStatus.batch_id == batch_id)
            .order_by(IdentityRunStatus.completed_at.desc())
            .first()
        )
        identity_status_str = id_run.run_status if id_run else "NOT_RUN"
        if not id_run or id_run.run_status != "SUCCESS":
            disqualifying_reasons.append(
                f"Identity stage status is '{identity_status_str}', must be SUCCESS to certify"
            )

        # 5. Reconciliation balance check
        if batch.reconciliation:
            if not batch.reconciliation.balance_check_passed or batch.reconciliation.status == ReconciliationStatusEnum.FAIL:
                disqualifying_reasons.append(
                    f"Reconciliation balance check failed (status: {batch.reconciliation.status.value})"
                )

        # 6. Production DQ rule execution check
        aborted_dq = (
            db.query(DQResult)
            .filter(
                DQResult.batch_id == batch_id,
                DQResult.action_taken == DQActionTakenEnum.BATCH_ABORTED,
            )
            .first()
        )
        dq_readiness_str = "PASSED"
        if aborted_dq:
            dq_readiness_str = "FAILED"
            disqualifying_reasons.append(
                "Batch has aborted DQ rule execution records"
            )

        current_cert = (
            db.query(OdsCertification)
            .filter(OdsCertification.batch_id == batch_id)
            .first()
        )

        eligible = len(disqualifying_reasons) == 0
        checklist_snapshot = {
            "batch_id": str(batch.id),
            "batch_status": batch.status.value,
            "identity_status": identity_status_str,
            "dq_readiness": dq_readiness_str,
            "ods_model_version_id": str(batch.ods_model_version_id) if batch.ods_model_version_id else None,
            "ods_model_version_number": model_version.version_number if model_version else None,
            "ods_model_version_status": model_version.status if model_version else None,
            "eligible": eligible,
            "disqualifying_reasons": disqualifying_reasons,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }

        return {
            "batch_id": batch.id,
            "batch_status": batch.status.value,
            "batch_created_by": batch.created_by,
            "identity_status": identity_status_str,
            "ods_model_version_id": batch.ods_model_version_id,
            "ods_model_version_number": model_version.version_number if model_version else None,
            "ods_model_version_status": model_version.status if model_version else None,
            "eligible_for_certification": eligible,
            "disqualifying_reasons": disqualifying_reasons,
            "checklist_snapshot": checklist_snapshot,
            "current_certification": current_cert,
        }

    @classmethod
    def certify_batch(
        cls, db: Session, request: OdsCertifyBatchRequest, steward_user: str
    ) -> OdsCertification:
        """
        Authoritative steward certification or rejection of a completed ODS batch.
        Enforces Four-Eyes segregation and Zero-PHI compliance.
        """
        target_status = request.status.upper()
        if target_status not in (OdsCertificationStatusEnum.CERTIFIED.value, OdsCertificationStatusEnum.FAILED.value):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid certification status '{request.status}'. Allowed: CERTIFIED, FAILED.",
            )

        # Validate Zero-PHI in notes
        if request.notes:
            try:
                validate_decision_notes_non_phi(request.notes)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Certification notes contain prohibited PHI/PII patterns",
                )

        batch = db.query(Batch).filter(Batch.id == request.batch_id).first()
        if not batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Batch '{request.batch_id}' not found.",
            )

        # Four-Eyes segregation check: Batch author / triggering user cannot certify
        if batch.created_by == steward_user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Four-Eyes segregation violation: The user who created or triggered the batch cannot certify it.",
            )

        eligibility = cls.evaluate_batch_eligibility(db, request.batch_id)

        # Check existing certification record
        existing = (
            db.query(OdsCertification)
            .filter(OdsCertification.batch_id == request.batch_id)
            .first()
        )
        if existing:
            if existing.status == OdsCertificationStatusEnum.CERTIFIED.value:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Batch is already CERTIFIED. Modifying or reverting CERTIFIED status is prohibited.",
                )
            if existing.status == OdsCertificationStatusEnum.FAILED.value:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Batch certification FAILED and cannot be modified.",
                )

        if target_status == OdsCertificationStatusEnum.CERTIFIED.value and not eligibility["eligible_for_certification"]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Batch cannot be certified due to unmet prerequisites: {'; '.join(eligibility['disqualifying_reasons'])}",
            )

        now = datetime.now(timezone.utc)
        if existing:
            existing.status = target_status
            existing.certified_by = steward_user
            existing.certified_at = now
            existing.certification_notes = request.notes
            existing.checklist_snapshot = eligibility["checklist_snapshot"]
            existing.updated_by = steward_user
            existing.updated_at = now
            cert = existing
        else:
            cert = OdsCertification(
                batch_id=request.batch_id,
                ods_model_version_id=batch.ods_model_version_id,
                status=target_status,
                certified_by=steward_user,
                certified_at=now,
                certification_notes=request.notes,
                checklist_snapshot=eligibility["checklist_snapshot"],
                created_by=steward_user,
                updated_by=steward_user,
                created_at=now,
                updated_at=now,
            )
            db.add(cert)

        db.flush()

        audit_action = (
            AuditActionEnum.ODS_BATCH_CERTIFIED
            if target_status == OdsCertificationStatusEnum.CERTIFIED.value
            else AuditActionEnum.ODS_BATCH_CERTIFICATION_FAILED
        )

        db.add(
            AuditEvent(
                action=audit_action,
                object_type="ods_certification",
                object_id=str(cert.id),
                actor_id=steward_user,
                description=f"Batch '{batch.id}' certification {target_status} by steward '{steward_user}'",
                after_state={
                    "batch_id": str(batch.id),
                    "status": target_status,
                    "ods_model_version_id": str(cert.ods_model_version_id),
                    "certified_by": steward_user,
                    "certified_at": now.isoformat(),
                },
                created_by=steward_user,
                updated_by=steward_user,
            )
        )

        db.commit()
        db.refresh(cert)
        return cert

    @classmethod
    def get_certification(cls, db: Session, batch_id: uuid.UUID) -> Optional[OdsCertification]:
        """Retrieves certification details for a batch."""
        return db.query(OdsCertification).filter(OdsCertification.batch_id == batch_id).first()

    @classmethod
    def list_certifications(
        cls, db: Session, status_filter: Optional[str] = None
    ) -> List[OdsCertification]:
        """Lists certification records with optional status filtering."""
        query = db.query(OdsCertification)
        if status_filter:
            query = query.filter(OdsCertification.status == status_filter.upper())
        return query.order_by(OdsCertification.created_at.desc()).all()
