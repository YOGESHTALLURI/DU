"""
Wave 2 Slice 5 — Comprehensive Zero-PHI Verification across all 8 HIPAA Safe Harbor Categories.
Addresses Blocker 4.
Directly inspects PostgreSQL persisted database columns for:
- OperationalVariance: title, description, telemetry_snapshot
- OperationalWaiver: business_justification, risk_assessment, mitigation_notes, decision_notes, revocation_reason
- BatchDataCertification: certification_notes, revocation_reason, evidence_snapshot
- AuditEvent: after_state, description
"""
import uuid
import json
from datetime import datetime, timezone, timedelta
import pytest

from backend.models.governance import (
    OperationalVariance,
    OperationalWaiver,
    BatchDataCertification,
    VarianceStatusEnum,
    WaiverStatusEnum,
    WaiverScopeEnum,
    CertificationStatusEnum,
)
from backend.models.feed import Feed, FeedFormatEnum, FeedStatusEnum, FeedVersion, FeedVersionStatusEnum
from backend.models.pipeline import Batch, BatchStatusEnum, BatchStage, StageNameEnum, StageStatusEnum
from backend.models.reconciliation import BatchReconciliation, ReconciliationStatusEnum
from backend.models.audit import AuditEvent
from backend.core.security import CurrentUser
from backend.services.variance_waiver_service import VarianceWaiverService
from backend.services.certification_service import CertificationService
from backend.services.fingerprint_service import FingerprintService
from backend.schemas.governance import WaiverSubmitRequest


PHI_RAW_SAMPLES = {
    "name": "Patient Name: Eleanor Vance",
    "ssn": "123-45-6789",
    "mrn": "MRN: 987654321",
    "dob": "DOB: 1974-08-15",
    "phone": "(555) 234-5678",
    "email": "eleanor.vance@saintjude-hospital.org",
    "address": "742 Evergreen Terrace",
    "zip": "ZIP: 97477",
}

PHI_BLOB = (
    f"{PHI_RAW_SAMPLES['name']} with SSN {PHI_RAW_SAMPLES['ssn']}, "
    f"{PHI_RAW_SAMPLES['mrn']}, {PHI_RAW_SAMPLES['dob']}, "
    f"phone {PHI_RAW_SAMPLES['phone']}, email {PHI_RAW_SAMPLES['email']}, "
    f"living at {PHI_RAW_SAMPLES['address']}, {PHI_RAW_SAMPLES['zip']}."
)


def assert_zero_phi_in_text_or_json(raw_target: str, context: str = ""):
    """Helper asserting none of the raw PHI values appear in the target text/json."""
    for key, val in PHI_RAW_SAMPLES.items():
        assert val not in raw_target, f"PHI LEAK [{key}]: '{val}' found in {context}: {raw_target}"
    assert "Eleanor Vance" not in raw_target, f"Patient name leaked in {context}"
    assert "123-45-6789" not in raw_target, f"SSN leaked in {context}"
    assert "987654321" not in raw_target, f"MRN leaked in {context}"
    assert "1974-08-15" not in raw_target, f"DOB leaked in {context}"
    assert "(555) 234-5678" not in raw_target, f"Phone leaked in {context}"
    assert "eleanor.vance@saintjude-hospital.org" not in raw_target, f"Email leaked in {context}"
    assert "742 Evergreen Terrace" not in raw_target, f"Address leaked in {context}"
    assert "97477" not in raw_target, f"ZIP leaked in {context}"


def test_sanitizer_covers_all_eight_hipaa_categories():
    """Verify FingerprintService.sanitize_zero_phi redacts every one of the 8 HIPAA categories."""
    sanitized = FingerprintService.sanitize_zero_phi(PHI_BLOB)

    assert "[REDACTED_NAME]" in sanitized
    assert "[REDACTED_SSN]" in sanitized
    assert "[REDACTED_MRN]" in sanitized
    assert "[REDACTED_DOB]" in sanitized
    assert "[REDACTED_PHONE]" in sanitized
    assert "[REDACTED_EMAIL]" in sanitized
    assert "[REDACTED_ADDRESS]" in sanitized
    assert "[REDACTED_ZIP]" in sanitized

    assert_zero_phi_in_text_or_json(sanitized, "sanitizer unit output")


def test_zero_phi_persisted_in_database(db):
    """
    End-to-end verification of zero-PHI in PostgreSQL persisted columns for:
    - OperationalVariance: title, description, telemetry_snapshot
    - OperationalWaiver: business_justification, risk_assessment, mitigation_notes, decision_notes, revocation_reason
    - BatchDataCertification: certification_notes, revocation_reason, evidence_snapshot
    - AuditEvent: after_state, description
    """
    # 1. Setup Feed & Batch
    feed = Feed(
        id=uuid.uuid4(),
        name=f"FEED_PHI_{uuid.uuid4().hex[:6]}",
        domain="MEMBERS",
        format=FeedFormatEnum.CSV,
        status=FeedStatusEnum.ACTIVE,
        landing_folder="./data/landing",
        filename_pattern="*.csv",
        created_by="system",
        updated_by="system",
    )
    db.add(feed)
    fv = FeedVersion(
        id=uuid.uuid4(),
        feed_id=feed.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED,
        created_by="system",
        updated_by="system",
    )
    db.add(fv)
    batch = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=fv.id,
        status=BatchStatusEnum.SUCCESS,
        triggered_by="operator_a",
        created_by="operator_a",
        updated_by="operator_a",
    )
    db.add(batch)
    for idx, stg in enumerate([StageNameEnum.LANDING, StageNameEnum.BRONZE, StageNameEnum.SILVER_RAW], start=1):
        db.add(BatchStage(
            id=uuid.uuid4(),
            batch_id=batch.id,
            stage_name=stg,
            stage_order=idx,
            status=StageStatusEnum.SUCCESS,
            created_by="operator_a",
            updated_by="operator_a",
        ))
    recon = BatchReconciliation(
        id=uuid.uuid4(),
        batch_id=batch.id,
        status=ReconciliationStatusEnum.PASS,
        rows_in=100,
        rows_silver_raw=100,
        rows_quarantined=0,
        rows_dropped=0,
        discrepancy=0,
        balance_check_passed=True,
        created_by="operator_a",
        updated_by="operator_a",
    )
    db.add(recon)
    db.commit()

    u_req = CurrentUser(user_id="analyst_1", email="analyst_1@cinqflow.com", roles=["ANALYST"], auth_provider="mock")
    u_rev = CurrentUser(user_id="steward_1", email="steward_1@cinqflow.com", roles=["DATA_STEWARD"], auth_provider="mock")

    # 2. Record Variance with PHI in title, description, and telemetry_snapshot
    variance = VarianceWaiverService.record_variance(
        db=db,
        feed_id=feed.id,
        batch_id=batch.id,
        control_type="DQ_RULE",
        control_id="RULE_PHI_CHECK",
        title=f"Failure for {PHI_BLOB}",
        description=f"Detailed incident on {PHI_BLOB}",
        severity="WARNING",
        telemetry_snapshot={"sample_failure": PHI_BLOB, "row_context": {"patient_info": PHI_BLOB}},
        user_id=u_req.user_id,
        user_email=u_req.email,
    )
    db.commit()

    # Query directly from DB to verify persisted state
    db_variance = db.query(OperationalVariance).filter(OperationalVariance.id == variance.id).one()
    assert_zero_phi_in_text_or_json(db_variance.title, "OperationalVariance.title")
    assert_zero_phi_in_text_or_json(db_variance.description, "OperationalVariance.description")
    assert_zero_phi_in_text_or_json(json.dumps(db_variance.telemetry_snapshot), "OperationalVariance.telemetry_snapshot")

    # 3. Request Waiver with PHI in justification, risk, mitigation
    now = datetime.now(timezone.utc)
    waiver = VarianceWaiverService.request_waiver(
        db=db,
        req=WaiverSubmitRequest(
            variance_id=variance.id,
            scope=WaiverScopeEnum.SINGLE_BATCH,
            business_justification=f"Justification referencing {PHI_BLOB}",
            risk_assessment=f"Risk assessment mentioning {PHI_BLOB}",
            mitigation_notes=f"Mitigation plan involving {PHI_BLOB}",
            expires_at=now + timedelta(days=7),
        ),
        current_user=u_req,
    )
    db.commit()

    db_waiver = db.query(OperationalWaiver).filter(OperationalWaiver.id == waiver.id).one()
    assert_zero_phi_in_text_or_json(db_waiver.business_justification, "OperationalWaiver.business_justification")
    assert_zero_phi_in_text_or_json(db_waiver.risk_assessment, "OperationalWaiver.risk_assessment")
    assert_zero_phi_in_text_or_json(db_waiver.mitigation_notes, "OperationalWaiver.mitigation_notes")

    # 4. Review Waiver with PHI in decision_notes
    VarianceWaiverService.review_waiver(
        db=db,
        waiver_id=waiver.id,
        decision="APPROVE",
        decision_notes=f"Approving based on notes: {PHI_BLOB}",
        current_user=u_rev,
    )
    db.commit()

    db.refresh(db_waiver)
    assert_zero_phi_in_text_or_json(db_waiver.decision_notes, "OperationalWaiver.decision_notes")

    # 5. Revoke Waiver with PHI in revocation_reason
    VarianceWaiverService.revoke_waiver(
        db=db,
        waiver_id=waiver.id,
        revocation_reason=f"Revoking waiver due to: {PHI_BLOB}",
        current_user=u_rev,
    )
    db.commit()

    db.refresh(db_waiver)
    assert_zero_phi_in_text_or_json(db_waiver.revocation_reason, "OperationalWaiver.revocation_reason")

    # 6. Certify Batch with PHI in certification_notes
    cert = CertificationService.certify_batch(
        db=db,
        batch_id=batch.id,
        current_user=u_rev,
        certification_notes=f"Certifying batch notes: {PHI_BLOB}",
    )
    db.commit()

    db_cert = db.query(BatchDataCertification).filter(BatchDataCertification.id == cert.id).one()
    assert_zero_phi_in_text_or_json(db_cert.certification_notes, "BatchDataCertification.certification_notes")
    assert_zero_phi_in_text_or_json(json.dumps(db_cert.evidence_snapshot), "BatchDataCertification.evidence_snapshot")

    # 7. Revoke Certification with PHI in revocation_reason
    CertificationService.revoke_certification(
        db=db,
        certification_id=cert.id,
        current_user=u_rev,
        revocation_reason=f"Revoking batch cert reason: {PHI_BLOB}",
    )
    db.commit()

    db.refresh(db_cert)
    assert_zero_phi_in_text_or_json(db_cert.revocation_reason, "BatchDataCertification.revocation_reason")

    # 8. Verify AuditEvent table records for these governance actions
    gov_audit_events = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.object_id.in_([str(variance.id), str(waiver.id), str(cert.id)])
        )
        .all()
    )
    assert len(gov_audit_events) >= 5
    for evt in gov_audit_events:
        assert_zero_phi_in_text_or_json(json.dumps(evt.after_state or {}), f"AuditEvent.after_state [{evt.action.value}]")
        assert_zero_phi_in_text_or_json(evt.description or "", f"AuditEvent.description [{evt.action.value}]")
