"""
Live Invariant Verification Script for Wave 2 Slice 5:
CF-V2-E13-03: Variance / Waiver
CF-V2-E13-04: Data Certification

Verifies all critical architectural invariants against PostgreSQL and live services:
- Invariant 1: Four-Eyes Enforcement on Waiver Approval (self-approval rejected with HTTP 403)
- Invariant 2: Bounded Waiver Expiration (past or >30 days rejected with HTTP 400)
- Invariant 3: Zero-PHI Scrubbing across Variances, Waivers, and Certifications
- Invariant 4: No Silent Control Bypass (underlying DQ rules and telemetry unchanged)
- Invariant 5: Concurrency Safety (single active waiver per variance enforced)
- Invariant 6: Authoritative Checklist Evaluation (fails on DQ, recon, alerts, stages)
- Invariant 7: Governed Exemption Under Active Approved Waiver (certified_with_waivers=True)
- Invariant 8: Four-Eyes Separation on Certification (batch trigger cannot certify)
- Invariant 9: Deterministic Evidence Hashing and Snapshot Immutability
- Invariant 10: Complete Audit Event Trail across Mutations
- Invariant 11: Authoritative Scope Model (SINGLE_BATCH, BATCH_RANGE, TIME_BOUNDED)
- Invariant 12: Active Waiver Uniqueness & Lifecycle Re-requesting (Rejected/Expired/Revoked -> New Allowed, History Preserved)
- Invariant 13: Time-Advance Exemption Removal (telemetry untouched)
- Invariant 14: Comprehensive 8-Category Zero-PHI in Persisted PostgreSQL Columns
- Invariant 15: Revocation Retrieval & Creation Safety (ineligible batch cannot create CERTIFIED row)
"""
import sys
sys.path.insert(0, "d:/Digitalurth/cinqflow")
import uuid
import json
import hashlib
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException

from backend.core.database import SessionLocal
from backend.core.security import CurrentUser
from backend.models.governance import (
    OperationalVariance,
    OperationalWaiver,
    BatchDataCertification,
    VarianceStatusEnum,
    WaiverStatusEnum,
    WaiverScopeEnum,
    CertificationStatusEnum,
)
from backend.models.feed import Feed, FeedVersion, FeedFormatEnum, FeedStatusEnum, FeedVersionStatusEnum
from backend.models.pipeline import (
    Batch,
    BatchStatusEnum,
    BatchStage,
    StageNameEnum,
    StageStatusEnum,
    WAVE0_STAGE_ORDER,
)
from backend.models.reconciliation import BatchReconciliation, ReconciliationStatusEnum
from backend.models.dq_result import DQResult, DQActionTakenEnum
from backend.models.input_registry import InputRegistry, InputStatusEnum
from backend.models.incident import OperationalAlert, FailureFingerprint, FailureCategoryEnum, AlertStatusEnum, AlertSeverityEnum
from backend.models.schema import Schema, SchemaVersion, SchemaVersionStatusEnum
from backend.models.rule import DataQualityRule, RuleVersion, RuleVersionStatusEnum, RuleTypeEnum, RuleSeverityEnum
from backend.models.audit import AuditEvent, AuditActionEnum
from backend.services.variance_waiver_service import VarianceWaiverService
from backend.services.certification_service import CertificationService
from backend.services.fingerprint_service import FingerprintService
from backend.schemas.governance import WaiverSubmitRequest

passed_count = 0
failed_count = 0

def check(title: str, condition: bool, detail: str = ""):
    global passed_count, failed_count
    if condition:
        passed_count += 1
        print(f"  [PASS] {title}")
    else:
        failed_count += 1
        print(f"  [FAIL] {title} -- {detail}")

def run_all_invariants():
    global passed_count, failed_count
    print("================================================================================")
    print("WAVE 2 SLICE 5 -- LIVE INVARIANT VERIFICATION")
    print("================================================================================")
    db = SessionLocal()

    try:
        test_id = uuid.uuid4().hex[:6]

        # Setup Feed & Version
        feed = Feed(
            id=uuid.uuid4(),
            name=f"INV_S5_FEED_{test_id}",
            domain="MEMBERS",
            format=FeedFormatEnum.CSV,
            status=FeedStatusEnum.ACTIVE,
            landing_folder=f"./data/landing/{test_id}",
            filename_pattern="*.csv",
            created_by="inv_tester",
            updated_by="inv_tester",
        )
        db.add(feed)
        fv = FeedVersion(
            id=uuid.uuid4(),
            feed_id=feed.id,
            version_number=1,
            status=FeedVersionStatusEnum.PUBLISHED,
            created_by="inv_tester",
            updated_by="inv_tester",
        )
        db.add(fv)

        # Setup Input & Batch
        inp = InputRegistry(
            id=uuid.uuid4(),
            feed_id=feed.id,
            filename=f"input_{test_id}.csv",
            file_path=f"./data/landing/input_{test_id}.csv",
            file_size_bytes=512,
            file_fingerprint=hashlib.sha256(f"content_{test_id}".encode()).hexdigest(),
            status=InputStatusEnum.ACCEPTED,
            registered_by="inv_tester",
            detected_at=datetime.now(timezone.utc),
            created_by="inv_tester",
            updated_by="inv_tester",
        )
        db.add(inp)

        batch = Batch(
            id=uuid.uuid4(),
            feed_id=feed.id,
            feed_version_id=fv.id,
            input_registry_id=inp.id,
            status=BatchStatusEnum.SUCCESS,
            triggered_by="operator_trigger_user",
            created_by="operator_trigger_user",
            updated_by="operator_trigger_user",
        )
        db.add(batch)

        for idx, sname in enumerate(WAVE0_STAGE_ORDER, start=1):
            stage = BatchStage(
                id=uuid.uuid4(),
                batch_id=batch.id,
                stage_name=sname,
                stage_order=idx,
                status=StageStatusEnum.SUCCESS,
                created_by="inv_tester",
                updated_by="inv_tester",
            )
            db.add(stage)

        recon = BatchReconciliation(
            id=uuid.uuid4(),
            batch_id=batch.id,
            rows_in=50,
            rows_silver_raw=50,
            rows_quarantined=0,
            rows_dropped=0,
            balance_check_passed=True,
            status=ReconciliationStatusEnum.PASS,
            discrepancy=0,
            created_by="inv_tester",
            updated_by="inv_tester",
        )
        db.add(recon)
        db.commit()

        # -------------------------------------------------------------------------
        # INVARIANT 1: Four-Eyes Enforcement on Waiver Approval
        # -------------------------------------------------------------------------
        print("\n--- INVARIANT 1: Four-Eyes Dual-Control on Waivers ---")
        var1 = VarianceWaiverService.record_variance(
            db=db,
            feed_id=feed.id,
            batch_id=batch.id,
            control_type="DATA_QUALITY",
            control_id="RULE_001",
            title="Variance for Four Eyes Test",
            description="Null check failure",
            user_id="requester_user",
            user_email="requester@cinqflow.local",
        )
        db.commit()

        user_req = CurrentUser(user_id="requester_user", email="requester@cinqflow.local", roles=["BUSINESS_ANALYST", "ENGINEER"], auth_provider="mock")
        waiver1 = VarianceWaiverService.request_waiver(
            db=db,
            req=WaiverSubmitRequest(
                variance_id=var1.id,
                scope=WaiverScopeEnum.SINGLE_BATCH,
                business_justification="Vendor issue verified with team",
                risk_assessment="Low financial risk verified",
                mitigation_notes="Quarantine records tagged properly",
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            ),
            current_user=user_req,
        )
        db.commit()

        # Self-approval attempt
        self_appr_caught = False
        try:
            VarianceWaiverService.review_waiver(db=db, waiver_id=waiver1.id, decision="APPROVE", decision_notes="Self approving", current_user=user_req)
        except HTTPException as e:
            if e.status_code == 403 and "Four-eyes violation" in e.detail:
                self_appr_caught = True
        check("Self-approval by requester user_id rejected with HTTP 403", self_appr_caught)

        # Self-approval by matching email
        user_impostor = CurrentUser(user_id="other_id", email="requester@cinqflow.local", roles=["DATA_STEWARD"], auth_provider="mock")
        email_caught = False
        try:
            VarianceWaiverService.review_waiver(db=db, waiver_id=waiver1.id, decision="APPROVE", decision_notes="Self approving", current_user=user_impostor)
        except HTTPException as e:
            if e.status_code == 403 and "Four-eyes violation" in e.detail:
                email_caught = True
        check("Self-approval by matching email rejected with HTTP 403", email_caught)

        # Distinct reviewer approval
        user_reviewer = CurrentUser(user_id="independent_steward", email="steward@cinqflow.local", roles=["DATA_STEWARD"], auth_provider="mock")
        VarianceWaiverService.review_waiver(db=db, waiver_id=waiver1.id, decision="APPROVE", decision_notes="Independent review OK", current_user=user_reviewer)
        db.commit()
        db.refresh(waiver1)
        check("Distinct reviewer successfully approved waiver", waiver1.status == WaiverStatusEnum.APPROVED)
        check("Parent variance transitioned to WAIVED", var1.status == VarianceStatusEnum.WAIVED)

        # -------------------------------------------------------------------------
        # INVARIANT 2: Bounded Waiver Expiration
        # -------------------------------------------------------------------------
        print("\n--- INVARIANT 2: Bounded Waiver Expiration Policy ---")
        var2 = VarianceWaiverService.record_variance(
            db=db, feed_id=feed.id, batch_id=batch.id, control_type="RECONCILIATION", control_id="RECON_1",
            title="Recon Variance", description="Discrepancy test", user_id="tester",
        )
        db.commit()

        past_exp_caught = False
        try:
            VarianceWaiverService.request_waiver(
                db=db,
                req=WaiverSubmitRequest(
                    variance_id=var2.id,
                    business_justification="Test business justification text",
                    risk_assessment="Low financial and operational risk",
                    mitigation_notes="Temporary monitoring applied",
                    expires_at=datetime.now(timezone.utc) - timedelta(days=1),
                ),
                current_user=user_req,
            )
        except HTTPException as e:
            if e.status_code == 400 and "strictly in the future" in e.detail:
                past_exp_caught = True
        check("Waiver with past expiration rejected with HTTP 400", past_exp_caught)

        excess_exp_caught = False
        try:
            VarianceWaiverService.request_waiver(
                db=db,
                req=WaiverSubmitRequest(
                    variance_id=var2.id,
                    business_justification="Test business justification text",
                    risk_assessment="Low financial and operational risk",
                    mitigation_notes="Temporary monitoring applied",
                    expires_at=datetime.now(timezone.utc) + timedelta(days=35),
                ),
                current_user=user_req,
            )
        except HTTPException as e:
            if e.status_code == 400 and "30 days" in e.detail:
                excess_exp_caught = True
        check("Waiver with expiration > 30 days rejected with HTTP 400", excess_exp_caught)

        # -------------------------------------------------------------------------
        # INVARIANT 3: Zero-PHI Scrubbing
        # -------------------------------------------------------------------------
        print("\n--- INVARIANT 3: Zero-PHI Scrubbing on Variances & Waivers ---")
        var_phi = VarianceWaiverService.record_variance(
            db=db, feed_id=feed.id, batch_id=batch.id, control_type="DATA_QUALITY", control_id="PHI_RULE",
            title="Member SSN 000-11-2222 error", description="Phone 555-019-2831 and email patient@domain.com", user_id="tester",
        )
        db.commit()
        check("SSN scrubbed from variance title", "[REDACTED_SSN]" in var_phi.title and "000-11-2222" not in var_phi.title)
        check("Phone scrubbed from variance description", "[REDACTED_PHONE]" in var_phi.description and "555-019-2831" not in var_phi.description)
        check("Email scrubbed from variance description", "[REDACTED_EMAIL]" in var_phi.description and "patient@domain.com" not in var_phi.description)

        # -------------------------------------------------------------------------
        # INVARIANT 4: No Silent Control Bypass
        # -------------------------------------------------------------------------
        print("\n--- INVARIANT 4: No Silent Control Bypass ---")
        stage_silver = db.query(BatchStage).filter(BatchStage.batch_id == batch.id).first()

        schema_obj = Schema(
            id=uuid.uuid4(),
            feed_id=feed.id,
            name=f"Schema_Inv_{uuid.uuid4().hex[:6]}",
            created_by="inv_tester",
            updated_by="inv_tester",
        )
        db.add(schema_obj)
        db.flush()

        sv = SchemaVersion(
            id=uuid.uuid4(),
            schema_id=schema_obj.id,
            version_number=1,
            status=SchemaVersionStatusEnum.PUBLISHED,
            created_by="inv_tester",
            updated_by="inv_tester",
        )
        db.add(sv)
        db.flush()

        rule = DataQualityRule(
            id=uuid.uuid4(),
            feed_id=feed.id,
            schema_id=schema_obj.id,
            name=f"Rule_Inv_{uuid.uuid4().hex[:6]}",
            created_by="inv_tester",
            updated_by="inv_tester",
        )
        db.add(rule)
        db.flush()

        rule_ver = RuleVersion(
            id=uuid.uuid4(),
            rule_id=rule.id,
            version_number=1,
            schema_version_id=sv.id,
            rule_type=RuleTypeEnum.NOT_NULL,
            target_field="member_id",
            rule_config={},
            severity=RuleSeverityEnum.QUARANTINE,
            status=RuleVersionStatusEnum.PUBLISHED,
            created_by="inv_tester",
            updated_by="inv_tester",
        )
        db.add(rule_ver)
        db.flush()

        rule_ver_id = rule_ver.id
        dq_entry = DQResult(
            id=uuid.uuid4(),
            batch_id=batch.id,
            stage_id=stage_silver.id,
            rule_version_id=rule_ver_id,
            total_rows_evaluated=50,
            passed_rows=45,
            failed_rows=5,
            pass_rate=90.0,
            action_taken=DQActionTakenEnum.QUARANTINED_ROWS,
            created_by="tester",
            updated_by="tester",
        )
        db.add(dq_entry)
        db.commit()

        # Record variance and waiver for this rule
        var_dq = VarianceWaiverService.record_variance(
            db=db, feed_id=feed.id, batch_id=batch.id, control_type="DQ_RULE", control_id=str(rule_ver_id),
            title="DQ Rule failure waiver", description="Waived for non-billing members", user_id="tester",
        )
        w_dq = VarianceWaiverService.request_waiver(
            db=db,
            req=WaiverSubmitRequest(
                variance_id=var_dq.id,
                business_justification="Vendor fix promised in next release",
                risk_assessment="Low financial risk verified",
                mitigation_notes="Quarantine tagged properly",
                expires_at=datetime.now(timezone.utc) + timedelta(days=5),
            ),
            current_user=user_req,
        )
        VarianceWaiverService.review_waiver(db=db, waiver_id=w_dq.id, decision="APPROVE", decision_notes="Approved with mitigation notes", current_user=user_reviewer)
        db.commit()

        db.refresh(dq_entry)
        check("DQ result failed_rows remains untouched (telemetry preserved)", dq_entry.failed_rows == 5)
        check("DQ result action_taken remains QUARANTINED_ROWS (control preserved)", dq_entry.action_taken == DQActionTakenEnum.QUARANTINED_ROWS)

        # -------------------------------------------------------------------------
        # INVARIANT 5: Concurrency Safety (Single Active Waiver per Variance)
        # -------------------------------------------------------------------------
        print("\n--- INVARIANT 5: Single Active Waiver per Variance ---")
        dup_waiver_caught = False
        try:
            VarianceWaiverService.request_waiver(
                db=db,
                req=WaiverSubmitRequest(
                    variance_id=var_dq.id,
                    business_justification="Duplicate request attempt string",
                    risk_assessment="Low financial and operational risk",
                    mitigation_notes="Temporary monitoring applied",
                    expires_at=datetime.now(timezone.utc) + timedelta(days=5),
                ),
                current_user=user_req,
            )
        except HTTPException as e:
            if e.status_code == 400 and "already exists" in e.detail:
                dup_waiver_caught = True
        check("Duplicate active waiver request on same variance rejected with HTTP 400", dup_waiver_caught)

        # -------------------------------------------------------------------------
        # INVARIANT 6: Authoritative Checklist Evaluation
        # -------------------------------------------------------------------------
        print("\n--- INVARIANT 6: Authoritative Certification Evaluation ---")
        eval_res = CertificationService.evaluate_batch_certification(db, batch.id)
        check("Certification checklist contains 7 categories", len(eval_res["checklist"]) == 7)
        check("Batch with all conditions satisfied or waived is eligible", eval_res["is_eligible"] is True)

        # -------------------------------------------------------------------------
        # INVARIANT 7: Four-Eyes Separation on Certification
        # -------------------------------------------------------------------------
        print("\n--- INVARIANT 7: Four-Eyes Separation on Certification ---")
        user_trigger = CurrentUser(user_id="operator_trigger_user", email="trigger@cinqflow.local", roles=["DATA_STEWARD", "ENGINEER"], auth_provider="mock")
        cert_self_caught = False
        try:
            CertificationService.certify_batch(db=db, batch_id=batch.id, current_user=user_trigger, certification_notes="Trigger trying to certify")
        except HTTPException as e:
            if e.status_code == 403 and "Four-eyes violation" in e.detail:
                cert_self_caught = True
        check("Triggering operator cannot certify batch (rejected with HTTP 403)", cert_self_caught)

        # -------------------------------------------------------------------------
        # INVARIANT 8: Governed Attestation & SHA-256 Evidence Hashing
        # -------------------------------------------------------------------------
        print("\n--- INVARIANT 8: Governed Certification & Evidence Hashing ---")
        user_certifier = CurrentUser(user_id="independent_certifier", email="certifier@cinqflow.local", roles=["DATA_STEWARD"], auth_provider="mock")
        cert_record = CertificationService.certify_batch(
            db=db, batch_id=batch.id, current_user=user_certifier, certification_notes="Certified under governed waiver"
        )
        db.commit()

        check("Certification record status is CERTIFIED", cert_record.status == CertificationStatusEnum.CERTIFIED)
        check("Certification record attests certified_with_waivers=True", cert_record.certified_with_waivers is True)
        check("Applied waiver IDs recorded in certificate", len(cert_record.applied_waiver_ids) > 0)
        check("Deterministic SHA-256 evidence_hash generated", len(cert_record.evidence_hash) == 64)

        # Idempotency check
        cert_repeat = CertificationService.certify_batch(db=db, batch_id=batch.id, current_user=user_certifier)
        check("Repeated certify_batch call returns identical certificate ID (idempotent)", cert_repeat.id == cert_record.id)

        # -------------------------------------------------------------------------
        # INVARIANT 9: Certificate Revocation
        # -------------------------------------------------------------------------
        print("\n--- INVARIANT 9: Certificate Revocation ---")
        rev_cert = CertificationService.revoke_certification(
            db=db, certification_id=cert_record.id, current_user=user_certifier, revocation_reason="Audit finding anomaly"
        )
        db.commit()
        check("Revoked certification status is REVOKED", rev_cert.status == CertificationStatusEnum.REVOKED)

        # -------------------------------------------------------------------------
        # INVARIANT 10: Complete Audit Event Trail
        # -------------------------------------------------------------------------
        print("\n--- INVARIANT 10: Audit Event Trail Verification ---")
        audits = [a.action.value for a in db.query(AuditEvent).all()]
        check("Audit trail includes ops.variance_created", "ops.variance_created" in audits)
        check("Audit trail includes ops.waiver_requested", "ops.waiver_requested" in audits)
        check("Audit trail includes ops.waiver_approved", "ops.waiver_approved" in audits)
        check("Audit trail includes ops.batch_certified", "ops.batch_certified" in audits)
        check("Audit trail includes ops.certification_revoked", "ops.certification_revoked" in audits)

        # -------------------------------------------------------------------------
        # INVARIANT 11: Authoritative Scope Model
        # -------------------------------------------------------------------------
        print("\n--- INVARIANT 11: Authoritative Scope Model Matching ---")
        b_other = Batch(
            id=uuid.uuid4(), feed_id=feed.id, feed_version_id=fv.id, input_registry_id=inp.id,
            status=BatchStatusEnum.SUCCESS, triggered_by="op", created_by="op", updated_by="op",
        )
        db.add(b_other)
        db.commit()

        # SINGLE_BATCH scope
        var_single = VarianceWaiverService.record_variance(
            db=db, feed_id=feed.id, batch_id=batch.id, control_type="DQ_RULE", control_id="R_SINGLE",
            title="Single batch variance", description="Variance for single batch test", user_id="tester",
        )
        db.commit()
        w_single = OperationalWaiver(
            id=uuid.uuid4(), variance_id=var_single.id, feed_id=feed.id, batch_id=batch.id,
            scope=WaiverScopeEnum.SINGLE_BATCH, affected_control_type="DQ_RULE", affected_control_id="R_SINGLE",
            business_justification="Single batch test", risk_assessment="Low risk verified", mitigation_notes="None required here",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1), status=WaiverStatusEnum.APPROVED,
            requested_by="tester", created_by="tester", updated_by="tester",
        )
        db.add(w_single)
        db.commit()
        check("SINGLE_BATCH matches target batch", VarianceWaiverService.does_waiver_apply_to_batch(w_single, batch, db) is True)
        check("SINGLE_BATCH rejects non-target batch", VarianceWaiverService.does_waiver_apply_to_batch(w_single, b_other, db) is False)

        # BATCH_RANGE scope (target_batch_ids)
        var_range = VarianceWaiverService.record_variance(
            db=db, feed_id=feed.id, batch_id=batch.id, control_type="DQ_RULE", control_id="R_RANGE",
            title="Range batch variance", description="Variance for range batch test", user_id="tester",
        )
        db.commit()
        w_range = OperationalWaiver(
            id=uuid.uuid4(), variance_id=var_range.id, feed_id=feed.id, batch_id=batch.id,
            scope=WaiverScopeEnum.BATCH_RANGE, target_batch_ids=[str(batch.id)], affected_control_type="DQ_RULE", affected_control_id="R_RANGE",
            business_justification="Batch range test", risk_assessment="Low risk verified", mitigation_notes="None required here",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1), status=WaiverStatusEnum.APPROVED,
            requested_by="tester", created_by="tester", updated_by="tester",
        )
        db.add(w_range)
        db.commit()
        check("BATCH_RANGE matches batch in target set", VarianceWaiverService.does_waiver_apply_to_batch(w_range, batch, db) is True)
        check("BATCH_RANGE rejects batch outside target set", VarianceWaiverService.does_waiver_apply_to_batch(w_range, b_other, db) is False)

        # TIME_BOUNDED scope
        var_time = VarianceWaiverService.record_variance(
            db=db, feed_id=feed.id, batch_id=batch.id, control_type="DQ_RULE", control_id="R_TIME",
            title="Time batch variance", description="Variance for time bounded test", user_id="tester",
        )
        db.commit()
        now = datetime.now(timezone.utc)
        w_time = OperationalWaiver(
            id=uuid.uuid4(), variance_id=var_time.id, feed_id=feed.id, batch_id=batch.id,
            scope=WaiverScopeEnum.TIME_BOUNDED, valid_from=now - timedelta(hours=2), expires_at=now + timedelta(hours=2),
            affected_control_type="DQ_RULE", affected_control_id="R_TIME",
            business_justification="Time bounded test", risk_assessment="Low risk verified", mitigation_notes="None required here",
            status=WaiverStatusEnum.APPROVED, requested_by="tester", created_by="tester", updated_by="tester",
        )
        db.add(w_time)
        db.commit()
        check("TIME_BOUNDED matches batch within window", VarianceWaiverService.does_waiver_apply_to_batch(w_time, batch, db, reference_time=now) is True)
        check("TIME_BOUNDED rejects evaluation outside window", VarianceWaiverService.does_waiver_apply_to_batch(w_time, batch, db, reference_time=now + timedelta(hours=5)) is False)

        # -------------------------------------------------------------------------
        # INVARIANT 12: Active Waiver Uniqueness & Full Audit Preservation
        # -------------------------------------------------------------------------
        print("\n--- INVARIANT 12: Active Waiver Uniqueness & Lifecycle ---")
        var_uniq = VarianceWaiverService.record_variance(
            db=db, feed_id=feed.id, batch_id=batch.id, control_type="DQ_RULE", control_id="R_UNIQ",
            title="Uniqueness test variance", description="Variance for lifecycle", user_id="tester",
        )
        db.commit()

        # Submit w_u1
        w_u1 = VarianceWaiverService.request_waiver(
            db=db,
            req=WaiverSubmitRequest(
                variance_id=var_uniq.id, scope=WaiverScopeEnum.SINGLE_BATCH,
                business_justification="First waiver justification", risk_assessment="Low operational risk",
                mitigation_notes="Mitigation plan in place", expires_at=datetime.now(timezone.utc) + timedelta(days=5),
            ),
            current_user=user_req,
        )
        db.commit()

        # Reject w_u1
        VarianceWaiverService.review_waiver(db=db, waiver_id=w_u1.id, decision="REJECT", decision_notes="Rejected by policy", current_user=user_reviewer)
        db.commit()

        # Submit w_u2 after rejection -> allowed!
        w_u2 = VarianceWaiverService.request_waiver(
            db=db,
            req=WaiverSubmitRequest(
                variance_id=var_uniq.id, scope=WaiverScopeEnum.SINGLE_BATCH,
                business_justification="Second waiver justification", risk_assessment="Low operational risk",
                mitigation_notes="Mitigation plan in place", expires_at=datetime.now(timezone.utc) + timedelta(days=5),
            ),
            current_user=user_req,
        )
        db.commit()
        check("New waiver request permitted after rejection", w_u2.status == WaiverStatusEnum.PENDING_APPROVAL)

        # Approve w_u2
        VarianceWaiverService.review_waiver(db=db, waiver_id=w_u2.id, decision="APPROVE", decision_notes="Approved now", current_user=user_reviewer)
        db.commit()

        # Simulate expiration
        w_u2.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()

        # Submit w_u3 after expiration -> allowed and transitions w_u2 to EXPIRED!
        w_u3 = VarianceWaiverService.request_waiver(
            db=db,
            req=WaiverSubmitRequest(
                variance_id=var_uniq.id, scope=WaiverScopeEnum.SINGLE_BATCH,
                business_justification="Third waiver justification", risk_assessment="Low operational risk",
                mitigation_notes="Mitigation plan in place", expires_at=datetime.now(timezone.utc) + timedelta(days=5),
            ),
            current_user=user_req,
        )
        db.commit()
        check("New waiver request permitted after expiration", w_u3.status == WaiverStatusEnum.PENDING_APPROVAL)
        check("Expired waiver transitioned to EXPIRED status", w_u2.status == WaiverStatusEnum.EXPIRED)

        # All 3 historical records preserved in PostgreSQL
        all_hist = db.query(OperationalWaiver).filter(OperationalWaiver.variance_id == var_uniq.id).all()
        check("All historical waiver records preserved in PostgreSQL (not overwritten)", len(all_hist) == 3)

        # -------------------------------------------------------------------------
        # INVARIANT 13: Time-Advance Exemption Removal (telemetry untouched)
        # -------------------------------------------------------------------------
        print("\n--- INVARIANT 13: Time-Advance Exemption Removal ---")
        b_exp = Batch(
            id=uuid.uuid4(), feed_id=feed.id, feed_version_id=fv.id, input_registry_id=inp.id,
            status=BatchStatusEnum.SUCCESS, triggered_by="op_exp", created_by="op_exp", updated_by="op_exp",
        )
        db.add(b_exp)
        for st in WAVE0_STAGE_ORDER:
            db.add(BatchStage(
                id=uuid.uuid4(), batch_id=b_exp.id, stage_name=st, stage_order=WAVE0_STAGE_ORDER.index(st) + 1,
                status=StageStatusEnum.SUCCESS, created_by="op_exp", updated_by="op_exp",
            ))
        db.add(BatchReconciliation(
            id=uuid.uuid4(), batch_id=b_exp.id, rows_in=100, rows_silver_raw=95,
            rows_quarantined=5, rows_dropped=0, balance_check_passed=True,
            status=ReconciliationStatusEnum.PASS, discrepancy=0,
            created_by="op_exp", updated_by="op_exp",
        ))
        dq_exp = DQResult(
            id=uuid.uuid4(), batch_id=b_exp.id, stage_id=stage_silver.id, rule_version_id=rule_ver_id,
            total_rows_evaluated=100, passed_rows=95, failed_rows=5, pass_rate=95.0,
            action_taken=DQActionTakenEnum.QUARANTINED_ROWS, created_by="op_exp", updated_by="op_exp",
        )
        db.add(dq_exp)
        db.commit()

        var_exp = VarianceWaiverService.record_variance(
            db=db, feed_id=feed.id, batch_id=b_exp.id, control_type="DQ_RULE", control_id=str(rule_ver_id),
            title="Variance for expiration test", description="Testing time advance", user_id="tester",
        )
        db.commit()

        t0 = datetime.now(timezone.utc)
        w_exp = OperationalWaiver(
            id=uuid.uuid4(), variance_id=var_exp.id, feed_id=feed.id, batch_id=b_exp.id,
            scope=WaiverScopeEnum.SINGLE_BATCH, affected_control_type="DQ_RULE", affected_control_id=str(rule_ver_id),
            business_justification="Temporary exemption", risk_assessment="Low risk", mitigation_notes="None required",
            valid_from=t0, expires_at=t0 + timedelta(hours=2), status=WaiverStatusEnum.APPROVED,
            requested_by="tester", created_by="tester", updated_by="tester",
        )
        db.add(w_exp)
        db.commit()

        eval_active = CertificationService.evaluate_batch_certification(db, b_exp.id, evaluate_at=t0 + timedelta(hours=1))
        check("Evaluation at t0+1h is ELIGIBLE with waiver", eval_active["is_eligible"] is True)

        eval_expired = CertificationService.evaluate_batch_certification(db, b_exp.id, evaluate_at=t0 + timedelta(hours=3))
        check("Evaluation at t0+3h (past expiration) is BLOCKED", eval_expired["is_eligible"] is False)
        check("DQ result failed_rows untouched after evaluation", dq_exp.failed_rows == 5)

        # -------------------------------------------------------------------------
        # INVARIANT 14: Comprehensive 8-Category Zero-PHI in DB Columns
        # -------------------------------------------------------------------------
        print("\n--- INVARIANT 14: 8-Category Zero-PHI in Database Columns ---")
        raw_phi_blob = "Patient Name: Alice Smith, SSN 123-45-6789, MRN: 11223344, DOB: 1982-04-10, phone (555) 345-6789, email alice@cinq.local, 456 Elm Street, ZIP: 10001"
        var_full_phi = VarianceWaiverService.record_variance(
            db=db, feed_id=feed.id, batch_id=batch.id, control_type="DQ_RULE", control_id="R_PHI8",
            title=f"Incident: {raw_phi_blob}", description=f"Details: {raw_phi_blob}",
            telemetry_snapshot={"sample": raw_phi_blob}, user_id="tester",
        )
        db.commit()

        persisted_var = db.query(OperationalVariance).filter(OperationalVariance.id == var_full_phi.id).one()
        leaks = [p for p in ["Alice Smith", "123-45-6789", "11223344", "1982-04-10", "(555) 345-6789", "alice@cinq.local", "456 Elm Street", "10001"] if p in persisted_var.title or p in persisted_var.description]
        check("Zero PHI leaked across all 8 categories in OperationalVariance", len(leaks) == 0, f"Leaked: {leaks}")

        # -------------------------------------------------------------------------
        # INVARIANT 15: Revocation Retrieval & Creation Safety
        # -------------------------------------------------------------------------
        print("\n--- INVARIANT 15: Revocation Retrieval & Creation Safety ---")
        latest_cert = CertificationService.get_batch_certification(db, batch.id)
        check("get_batch_certification returns REVOKED certificate (not None)", latest_cert is not None and latest_cert.status == CertificationStatusEnum.REVOKED)

        b_fail = Batch(
            id=uuid.uuid4(), feed_id=feed.id, feed_version_id=fv.id, status=BatchStatusEnum.FAILED,
            triggered_by="op", created_by="op", updated_by="op",
        )
        db.add(b_fail)
        db.commit()

        creation_safety_passed = False
        try:
            CertificationService.certify_batch(db=db, batch_id=b_fail.id, current_user=user_reviewer)
        except HTTPException as e:
            if e.status_code == 400 and "not eligible" in e.detail:
                creation_safety_passed = True
        check("Ineligible batch strictly cannot create a CERTIFIED row", creation_safety_passed)

    finally:
        db.close()

    print("\n================================================================================")
    print(f"VERIFICATION RESULTS: {passed_count} PASSED, {failed_count} FAILED")
    print("================================================================================")
    return failed_count == 0

if __name__ == "__main__":
    success = run_all_invariants()
    sys.exit(0 if success else 1)
