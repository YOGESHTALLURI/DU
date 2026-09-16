"""
Wave 2 Slice 5 Service — Batch Data Certification (CF-V2-E13-04)
Evaluates authoritative checklist conditions, incorporates active governed waivers,
enforces four-eyes governance on certification, and writes immutable evidence-backed certificates.
"""
import uuid
import json
import hashlib
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from backend.models.pipeline import Batch, BatchStatusEnum, StageStatusEnum
from backend.models.feed import Feed, FeedVersion
from backend.models.reconciliation import BatchReconciliation, ReconciliationStatusEnum
from backend.models.dq_result import DQResult, DQActionTakenEnum
from backend.models.input_registry import InputRegistry, QuarantineRecord, QuarantineStatusEnum
from backend.models.incident import OperationalAlert, AlertStatusEnum
from backend.models.drift import SchemaDriftReport, DriftSeverityEnum, DriftStatusEnum
from backend.models.governance import (
    BatchDataCertification,
    CertificationStatusEnum,
    OperationalWaiver,
    WaiverStatusEnum,
)
from backend.models.audit import AuditActionEnum
from backend.core.security import CurrentUser
from backend.services.audit_service import AuditService
from backend.services.fingerprint_service import FingerprintService
from backend.services.variance_waiver_service import VarianceWaiverService


class CertificationService:
    @staticmethod
    def evaluate_batch_certification(
        db: Session,
        batch_id: uuid.UUID,
        evaluate_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Dynamically evaluate the complete authoritative checklist for batch data certification.
        Returns eligibility, checklist results, blocking reasons, and applied active waivers.
        """
        batch = db.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Batch '{batch_id}' not found",
            )

        feed = db.query(Feed).filter(Feed.id == batch.feed_id).first()
        feed_name = feed.name if feed else "UNKNOWN"

        checklist: List[Dict[str, Any]] = []
        blocking_reasons: List[str] = []
        applied_waivers: List[Dict[str, Any]] = []

        # Find all active approved waivers applicable to this batch
        ref_time = evaluate_at or datetime.now(timezone.utc)
        candidate_waivers = (
            db.query(OperationalWaiver)
            .filter(
                OperationalWaiver.feed_id == batch.feed_id,
                OperationalWaiver.status == WaiverStatusEnum.APPROVED,
                OperationalWaiver.expires_at > ref_time,
            )
            .all()
        )
        applicable_waivers = [
            w for w in candidate_waivers
            if VarianceWaiverService.does_waiver_apply_to_batch(w, batch, db, reference_time=ref_time)
        ]
        active_waiver_map: Dict[str, OperationalWaiver] = {}
        for w in applicable_waivers:
            if w.affected_control_id:
                active_waiver_map[w.affected_control_id] = w
            if w.affected_control_type:
                active_waiver_map[w.affected_control_type] = w

        # 1. BATCH_STATUS Check
        batch_passed = (batch.status == BatchStatusEnum.SUCCESS)
        if not batch_passed:
            blocking_reasons.append(f"Batch status is '{batch.status.value}', must be SUCCESS to certify")
        checklist.append({
            "category": "BATCH_STATUS",
            "title": "Batch Terminal Success",
            "passed": batch_passed,
            "details": f"Batch status is {batch.status.value}",
        })

        # 2. STAGES Check
        stages_passed = True
        failed_stage_names = []
        for stage in batch.stages:
            if stage.status != StageStatusEnum.SUCCESS:
                stages_passed = False
                failed_stage_names.append(f"{stage.stage_name.value} ({stage.status.value})")
        if not stages_passed:
            blocking_reasons.append(f"Pipeline stages incomplete or failed: {', '.join(failed_stage_names)}")
        checklist.append({
            "category": "STAGES",
            "title": "Pipeline Stage Completion",
            "passed": stages_passed,
            "details": "All stages SUCCESS" if stages_passed else f"Incomplete stages: {', '.join(failed_stage_names)}",
        })

        # 3. SCHEMA & DRIFT Check
        drift_passed = True
        drift_waived = False
        drift_waiver_id = None
        unack_drifts = (
            db.query(SchemaDriftReport)
            .filter(
                SchemaDriftReport.feed_id == batch.feed_id,
                SchemaDriftReport.status == DriftStatusEnum.DETECTED,
                SchemaDriftReport.drift_severity == DriftSeverityEnum.BREAKING,
            )
            .all()
        )
        if unack_drifts:
            # Check if waived
            drift_waiver = active_waiver_map.get("SCHEMA_DRIFT")
            if drift_waiver:
                drift_waived = True
                drift_waiver_id = drift_waiver.id
                applied_waivers.append({
                    "waiver_id": str(drift_waiver.id),
                    "control_type": "SCHEMA_DRIFT",
                    "reason": drift_waiver.business_justification,
                })
            else:
                drift_passed = False
                blocking_reasons.append(f"Active unacknowledged breaking schema drift detected on feed ({len(unack_drifts)} events)")
        checklist.append({
            "category": "SCHEMA",
            "title": "Schema Contract & Drift Validation",
            "passed": drift_passed,
            "details": "Schema valid with zero unacknowledged breaking drift" if drift_passed and not drift_waived else ("Waived under approved waiver" if drift_waived else "Active unacknowledged drift"),
            "waived": drift_waived,
            "waiver_id": drift_waiver_id,
        })

        # 4. RECONCILIATION Check
        recon = db.query(BatchReconciliation).filter(BatchReconciliation.batch_id == batch_id).first()
        recon_passed = True
        recon_waived = False
        recon_waiver_id = None
        if not recon or recon.status != ReconciliationStatusEnum.PASS or recon.discrepancy != 0:
            recon_waiver = active_waiver_map.get(str(recon.id) if recon else "RECONCILIATION")
            if recon_waiver:
                recon_waived = True
                recon_waiver_id = recon_waiver.id
                applied_waivers.append({
                    "waiver_id": str(recon_waiver.id),
                    "control_type": "RECONCILIATION",
                    "reason": recon_waiver.business_justification,
                })
            else:
                recon_passed = False
                disc = recon.discrepancy if recon else "Missing"
                blocking_reasons.append(f"Reconciliation check failed: discrepancy = {disc}")
        checklist.append({
            "category": "RECONCILIATION",
            "title": "Row Count Reconciliation Balance",
            "passed": recon_passed,
            "details": f"Reconciliation balanced (0 discrepancy)" if recon_passed and not recon_waived else ("Waived under approved waiver" if recon_waived else f"Discrepancy: {recon.discrepancy if recon else 'None'}"),
            "waived": recon_waived,
            "waiver_id": recon_waiver_id,
        })

        # 5. DATA QUALITY Check
        dq_results = db.query(DQResult).filter(DQResult.batch_id == batch_id).all()
        dq_passed = True
        dq_waived = False
        unwaived_dq_violations = []
        for dq in dq_results:
            if dq.failed_rows > 0 and dq.action_taken in [DQActionTakenEnum.QUARANTINED_ROWS, DQActionTakenEnum.BATCH_ABORTED]:
                waiver = active_waiver_map.get(str(dq.rule_version_id))
                if waiver:
                    dq_waived = True
                    applied_waivers.append({
                        "waiver_id": str(waiver.id),
                        "control_type": "DQ_RULE",
                        "control_id": str(dq.rule_version_id),
                        "reason": waiver.business_justification,
                    })
                else:
                    dq_passed = False
                    unwaived_dq_violations.append(f"Rule version {str(dq.rule_version_id)[:8]} failed on {dq.failed_rows} rows")
        if not dq_passed:
            blocking_reasons.append(f"Data Quality violations without waiver: {', '.join(unwaived_dq_violations)}")
        checklist.append({
            "category": "DATA_QUALITY",
            "title": "Data Quality Rule Executions",
            "passed": dq_passed,
            "details": f"Evaluated {len(dq_results)} rules; all passed or waived" if dq_passed else f"Violations: {', '.join(unwaived_dq_violations)}",
            "waived": dq_waived,
        })

        # 6. QUARANTINE DISPOSITION Check
        unhandled_quarantine = (
            db.query(QuarantineRecord)
            .filter(
                QuarantineRecord.batch_id == batch_id,
                QuarantineRecord.status == QuarantineStatusEnum.QUARANTINED,
            )
            .count()
        )
        quarantine_passed = True
        quarantine_waived = False
        quarantine_waiver_id = None
        if unhandled_quarantine > 0:
            q_waiver = active_waiver_map.get("QUARANTINE_ACCUMULATION")
            if q_waiver:
                quarantine_waived = True
                quarantine_waiver_id = q_waiver.id
                applied_waivers.append({
                    "waiver_id": str(q_waiver.id),
                    "control_type": "QUARANTINE_ACCUMULATION",
                    "reason": q_waiver.business_justification,
                })
            else:
                quarantine_passed = False
                blocking_reasons.append(f"{unhandled_quarantine} quarantine records remain in QUARANTINED status without resolution or waiver")
        checklist.append({
            "category": "QUARANTINE",
            "title": "Quarantine Records Disposition",
            "passed": quarantine_passed,
            "details": "0 unhandled quarantined records" if unhandled_quarantine == 0 else (f"Waived {unhandled_quarantine} records under approved waiver" if quarantine_waived else f"{unhandled_quarantine} unhandled records"),
            "waived": quarantine_waived,
            "waiver_id": quarantine_waiver_id,
        })

        # 7. OPERATIONAL ALERTS Check
        active_alerts = (
            db.query(OperationalAlert)
            .filter(
                OperationalAlert.batch_id == batch_id,
                OperationalAlert.status.in_([AlertStatusEnum.OPEN, AlertStatusEnum.RECOVERY_IN_PROGRESS]),
            )
            .all()
        )
        alerts_passed = (len(active_alerts) == 0)
        if not alerts_passed:
            alert_titles = [f"Alert {str(a.id)[:8]} ({a.title})" for a in active_alerts]
            blocking_reasons.append(f"Active operational alerts on batch: {', '.join(alert_titles)}")
        checklist.append({
            "category": "ALERTS",
            "title": "Operational Alerts State",
            "passed": alerts_passed,
            "details": "Zero active alerts" if alerts_passed else f"{len(active_alerts)} active alerts pending resolution",
        })

        is_eligible = (len(blocking_reasons) == 0)
        return {
            "batch_id": batch.id,
            "feed_id": batch.feed_id,
            "feed_name": feed_name,
            "is_eligible": is_eligible,
            "blocking_reasons": blocking_reasons,
            "checklist": checklist,
            "active_waivers": applied_waivers,
        }

    @staticmethod
    def certify_batch(
        db: Session,
        batch_id: uuid.UUID,
        current_user: CurrentUser,
        certification_notes: Optional[str] = None,
    ) -> BatchDataCertification:
        """
        Certify an eligible batch.
        Strictly enforces:
        - Pessimistic locking (with_for_update)
        - Server-side re-evaluation of all 7 prerequisites
        - Four-eyes governance: the operator who triggered the batch cannot certify it
        - Snapshotting of immutable evidence bundle and SHA-256 hash
        - Idempotent return of existing active certification
        """
        batch = (
            db.query(Batch)
            .filter(Batch.id == batch_id)
            .with_for_update()
            .first()
        )
        if not batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Batch '{batch_id}' not found",
            )

        # Idempotency check: if already certified and active, return existing record
        existing_cert = (
            db.query(BatchDataCertification)
            .filter(
                BatchDataCertification.batch_id == batch_id,
                BatchDataCertification.status == CertificationStatusEnum.CERTIFIED,
            )
            .first()
        )
        if existing_cert:
            return existing_cert

        # Four-Eyes Governance Check
        trigger_user = (batch.triggered_by or "").strip().lower()
        certifier_user = (current_user.user_id or "").strip().lower()
        certifier_email = (current_user.email or "").strip().lower()

        if certifier_user == trigger_user or (certifier_email and certifier_email == trigger_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Four-eyes violation: The operator who triggered the batch cannot certify it",
            )

        # Authoritative Checklist Re-evaluation
        evaluation = CertificationService.evaluate_batch_certification(db, batch_id)
        if not evaluation["is_eligible"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Batch is not eligible for certification: {'; '.join(evaluation['blocking_reasons'])}",
            )

        now = datetime.now(timezone.utc)
        clean_notes = FingerprintService.sanitize_zero_phi(certification_notes or "")

        # Build comprehensive evidence snapshot
        input_rec = db.query(InputRegistry).filter(InputRegistry.id == batch.input_registry_id).first() if batch.input_registry_id else None
        recon = db.query(BatchReconciliation).filter(BatchReconciliation.batch_id == batch_id).first()
        dq_results = db.query(DQResult).filter(DQResult.batch_id == batch_id).all()

        applied_waiver_ids = [w["waiver_id"] for w in evaluation["active_waivers"]]

        recon_summary = {
            "rows_in": recon.rows_in if recon else 0,
            "rows_silver_raw": recon.rows_silver_raw if recon else 0,
            "rows_quarantined": recon.rows_quarantined if recon else 0,
            "rows_dropped": recon.rows_dropped if recon else 0,
            "discrepancy": recon.discrepancy if recon else 0,
            "balance_check_passed": recon.balance_check_passed if recon else False,
        }

        dq_summary = {
            "total_rules_evaluated": len(dq_results),
            "rules_passed": sum(1 for d in dq_results if d.failed_rows == 0),
            "rules_failed": sum(1 for d in dq_results if d.failed_rows > 0),
            "evaluations": [
                {
                    "rule_version_id": str(d.rule_version_id),
                    "failed_rows": d.failed_rows,
                    "action_taken": d.action_taken.value,
                    "pass_rate": float(d.pass_rate),
                }
                for d in dq_results
            ],
        }

        evidence_snapshot = {
            "batch_id": str(batch.id),
            "feed_id": str(batch.feed_id),
            "feed_version_id": str(batch.feed_version_id),
            "input_filename": input_rec.filename if input_rec else "UNKNOWN",
            "input_file_fingerprint": input_rec.file_fingerprint if input_rec else "UNKNOWN",
            "total_rows": recon.rows_in if recon else 0,
            "checklist": evaluation["checklist"],
            "applied_waivers": evaluation["active_waivers"],
            "reconciliation_summary": recon_summary,
            "dq_summary": dq_summary,
            "certified_at": now.isoformat(),
            "certified_by": current_user.user_id,
        }

        # Zero-PHI sanitization of evidence snapshot
        evidence_snapshot = FingerprintService.sanitize_zero_phi_dict(evidence_snapshot)

        # Deterministic evidence hash
        canonical_evidence_bytes = json.dumps(evidence_snapshot, sort_keys=True).encode("utf-8")
        evidence_hash = hashlib.sha256(canonical_evidence_bytes).hexdigest()

        cert = BatchDataCertification(
            id=uuid.uuid4(),
            batch_id=batch.id,
            feed_id=batch.feed_id,
            feed_version_id=batch.feed_version_id,
            status=CertificationStatusEnum.CERTIFIED,
            certified_with_waivers=(len(applied_waiver_ids) > 0),
            applied_waiver_ids=applied_waiver_ids,
            input_file_fingerprint=input_rec.file_fingerprint if input_rec else "UNKNOWN",
            input_filename=input_rec.filename if input_rec else "UNKNOWN",
            total_rows=recon.rows_in if recon else 0,
            reconciliation_summary=recon_summary,
            dq_summary=dq_summary,
            evidence_snapshot=evidence_snapshot,
            evidence_hash=evidence_hash,
            certified_by=current_user.user_id,
            certified_by_email=current_user.email,
            certified_at=now,
            certification_notes=clean_notes,
            created_by=current_user.user_id,
            updated_by=current_user.user_id,
        )
        db.add(cert)

        # Update batch application count on applied waivers
        if applied_waiver_ids:
            waivers_to_update = db.query(OperationalWaiver).filter(OperationalWaiver.id.in_([uuid.UUID(wid) for wid in applied_waiver_ids])).all()
            for w in waivers_to_update:
                w.batches_applied_count += 1
                w.updated_at = now
                w.updated_by = current_user.user_id

        db.flush()

        AuditService.log(
            db=db,
            action=AuditActionEnum.OPS_BATCH_CERTIFIED,
            actor_id=current_user.user_id,
            actor_email=current_user.email,
            object_type="batch_data_certification",
            object_id=str(cert.id),
            after_state={
                "certification_id": str(cert.id),
                "batch_id": str(batch.id),
                "feed_id": str(batch.feed_id),
                "certified_with_waivers": cert.certified_with_waivers,
                "applied_waiver_ids": applied_waiver_ids,
                "evidence_hash": evidence_hash,
                "certified_by": current_user.user_id,
            },
            description=f"Batch {batch.id} formally certified by {current_user.user_id} (hash: {evidence_hash[:12]}...)",
        )
        return cert

    @staticmethod
    def get_batch_certification(db: Session, batch_id: uuid.UUID) -> Optional[BatchDataCertification]:
        return (
            db.query(BatchDataCertification)
            .filter(BatchDataCertification.batch_id == batch_id)
            .order_by(BatchDataCertification.created_at.desc())
            .first()
        )

    @staticmethod
    def get_certification(db: Session, certification_id: uuid.UUID) -> BatchDataCertification:
        cert = db.query(BatchDataCertification).filter(BatchDataCertification.id == certification_id).first()
        if not cert:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Certification '{certification_id}' not found",
            )
        return cert

    @staticmethod
    def revoke_certification(
        db: Session,
        certification_id: uuid.UUID,
        current_user: CurrentUser,
        revocation_reason: str,
    ) -> BatchDataCertification:
        cert = (
            db.query(BatchDataCertification)
            .filter(BatchDataCertification.id == certification_id)
            .with_for_update()
            .first()
        )
        if not cert:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Certification '{certification_id}' not found",
            )

        if cert.status != CertificationStatusEnum.CERTIFIED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only CERTIFIED records can be revoked (currently {cert.status.value})",
            )

        clean_reason = FingerprintService.sanitize_zero_phi(revocation_reason)
        now = datetime.now(timezone.utc)

        cert.status = CertificationStatusEnum.REVOKED
        cert.revoked_by = current_user.user_id
        cert.revoked_at = now
        cert.revocation_reason = clean_reason
        cert.updated_at = now
        cert.updated_by = current_user.user_id
        db.flush()

        AuditService.log(
            db=db,
            action=AuditActionEnum.OPS_CERTIFICATION_REVOKED,
            actor_id=current_user.user_id,
            actor_email=current_user.email,
            object_type="batch_data_certification",
            object_id=str(cert.id),
            after_state={
                "certification_id": str(cert.id),
                "status": cert.status.value,
                "revoked_by": current_user.user_id,
                "revocation_reason": clean_reason,
            },
            description=f"Batch certification {cert.id} revoked by {current_user.user_id}",
        )
        return cert
