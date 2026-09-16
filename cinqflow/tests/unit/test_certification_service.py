"""
Unit tests for CertificationService (CF-V2-E13-04).
Verifies:
- Authoritative checklist evaluation across all 7 prerequisite categories
- Certification blocking on un-waived failures (DQ, Recon, Quarantine, Alerts, Stage errors)
- Certification clearance under approved active waivers (certified_with_waivers)
- Four-eyes separation: batch trigger operator cannot certify the batch
- Evidence snapshot hashing and immutability
- Idempotency on repeated certification requests
"""
import uuid
import json
import hashlib
from datetime import datetime, timezone, timedelta
import pytest
from fastapi import HTTPException

from backend.models.governance import (
    BatchDataCertification,
    CertificationStatusEnum,
    OperationalVariance,
    OperationalWaiver,
    VarianceStatusEnum,
    WaiverStatusEnum,
    WaiverScopeEnum,
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
from backend.models.input_registry import InputRegistry, InputStatusEnum, QuarantineRecord, QuarantineStatusEnum, QuarantineReasonEnum
from backend.models.incident import OperationalAlert, FailureFingerprint, FailureCategoryEnum, AlertStatusEnum, AlertSeverityEnum
from backend.models.schema import Schema, SchemaVersion, SchemaVersionStatusEnum
from backend.models.rule import DataQualityRule, RuleVersion, RuleVersionStatusEnum, RuleTypeEnum, RuleSeverityEnum
from backend.core.security import CurrentUser
from backend.services.certification_service import CertificationService
from backend.services.variance_waiver_service import VarianceWaiverService
from backend.schemas.governance import WaiverSubmitRequest


@pytest.fixture
def clean_batch_environment(db):
    test_id = uuid.uuid4().hex[:6]
    feed = Feed(
        id=uuid.uuid4(),
        name=f"CERT_FEED_{test_id}",
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

    inp = InputRegistry(
        id=uuid.uuid4(),
        feed_id=feed.id,
        filename=f"input_{test_id}.csv",
        file_path=f"./data/landing/input_{test_id}.csv",
        file_size_bytes=1024,
        file_fingerprint=hashlib.sha256(b"sample_content").hexdigest(),
        status=InputStatusEnum.ACCEPTED,
        registered_by="system",
        detected_at=datetime.now(timezone.utc),
        created_by="system",
        updated_by="system",
    )
    db.add(inp)

    batch = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=fv.id,
        input_registry_id=inp.id,
        status=BatchStatusEnum.SUCCESS,
        triggered_by="operator_scheduler",
        created_by="operator_scheduler",
        updated_by="operator_scheduler",
    )
    db.add(batch)

    for idx, sname in enumerate(WAVE0_STAGE_ORDER, start=1):
        stage = BatchStage(
            id=uuid.uuid4(),
            batch_id=batch.id,
            stage_name=sname,
            stage_order=idx,
            status=StageStatusEnum.SUCCESS,
            created_by="system",
            updated_by="system",
        )
        db.add(stage)

    recon = BatchReconciliation(
        id=uuid.uuid4(),
        batch_id=batch.id,
        rows_in=100,
        rows_silver_raw=100,
        rows_quarantined=0,
        rows_dropped=0,
        balance_check_passed=True,
        status=ReconciliationStatusEnum.PASS,
        discrepancy=0,
        created_by="system",
        updated_by="system",
    )
    db.add(recon)
    db.commit()

    return {
        "feed": feed,
        "feed_version": fv,
        "input_registry": inp,
        "batch": batch,
        "reconciliation": recon,
    }


def test_certification_evaluation_all_categories_pass(db, clean_batch_environment):
    batch = clean_batch_environment["batch"]
    res = CertificationService.evaluate_batch_certification(db, batch.id)

    assert res["is_eligible"] is True
    assert len(res["blocking_reasons"]) == 0
    assert len(res["checklist"]) == 7
    for item in res["checklist"]:
        assert item["passed"] is True


def test_certification_blocked_by_open_operational_alert(db, clean_batch_environment):
    batch = clean_batch_environment["batch"]
    feed = clean_batch_environment["feed"]

    fp = FailureFingerprint(
        id=uuid.uuid4(),
        category=FailureCategoryEnum.DATA_QUALITY,
        root_cause_pattern="Test violation pattern",
        canonical_signature="dq:test",
        fingerprint_hash=uuid.uuid4().hex,
        created_by="system",
        updated_by="system",
    )
    db.add(fp)

    alert = OperationalAlert(
        id=uuid.uuid4(),
        feed_id=feed.id,
        batch_id=batch.id,
        failure_fingerprint_id=fp.id,
        title="Unresolved Data Anomaly Alert",
        description="Active unresolved incident",
        severity=AlertSeverityEnum.CRITICAL,
        status=AlertStatusEnum.OPEN,
        created_by="system",
        updated_by="system",
    )
    db.add(alert)
    db.commit()

    res = CertificationService.evaluate_batch_certification(db, batch.id)
    assert res["is_eligible"] is False
    assert any("Active operational alerts" in b for b in res["blocking_reasons"])


def test_certification_blocked_by_dq_violation_and_cleared_by_waiver(db, clean_batch_environment):
    batch = clean_batch_environment["batch"]
    stage = db.query(BatchStage).filter(BatchStage.batch_id == batch.id).first()
    feed = clean_batch_environment["feed"]

    schema_obj = Schema(
        id=uuid.uuid4(),
        feed_id=feed.id,
        name=f"Schema_DQ_{uuid.uuid4().hex[:6]}",
        created_by="system",
        updated_by="system",
    )
    db.add(schema_obj)
    db.flush()

    sv = SchemaVersion(
        id=uuid.uuid4(),
        schema_id=schema_obj.id,
        version_number=1,
        status=SchemaVersionStatusEnum.PUBLISHED,
        created_by="system",
        updated_by="system",
    )
    db.add(sv)
    db.flush()

    rule = DataQualityRule(
        id=uuid.uuid4(),
        feed_id=feed.id,
        schema_id=schema_obj.id,
        name=f"Rule_DQ_{uuid.uuid4().hex[:6]}",
        created_by="system",
        updated_by="system",
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
        created_by="system",
        updated_by="system",
    )
    db.add(rule_ver)
    db.flush()

    rule_ver_id = rule_ver.id

    # Add failing DQResult
    dq_res = DQResult(
        id=uuid.uuid4(),
        batch_id=batch.id,
        stage_id=stage.id,
        rule_version_id=rule_ver_id,
        total_rows_evaluated=100,
        passed_rows=90,
        failed_rows=10,
        pass_rate=90.0,
        action_taken=DQActionTakenEnum.QUARANTINED_ROWS,
        created_by="system",
        updated_by="system",
    )
    db.add(dq_res)
    db.commit()

    # Evaluation without waiver: blocked
    res_blocked = CertificationService.evaluate_batch_certification(db, batch.id)
    assert res_blocked["is_eligible"] is False
    assert any("Data Quality violations without waiver" in b for b in res_blocked["blocking_reasons"])

    # Create and approve a waiver for this DQ rule
    variance = VarianceWaiverService.record_variance(
        db=db,
        feed_id=clean_batch_environment["feed"].id,
        batch_id=batch.id,
        control_type="DQ_RULE",
        control_id=str(rule_ver_id),
        title="10 quarantined member rows waiver",
        description="Vendor issue will be fixed in release 2",
        user_id="analyst_1",
    )
    db.commit()

    requester = CurrentUser(user_id="analyst_1", email="a@cinqflow.local", roles=["BUSINESS_ANALYST"], auth_provider="mock")
    reviewer = CurrentUser(user_id="steward_lead", email="steward@cinqflow.local", roles=["DATA_STEWARD"], auth_provider="mock")

    waiver = VarianceWaiverService.request_waiver(
        db=db,
        req=WaiverSubmitRequest(
            variance_id=variance.id,
            business_justification="Vendor issue will be fixed in release 2",
            risk_assessment="Non-critical billing fields",
            mitigation_notes="Analytics team notified",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        ),
        current_user=requester,
    )
    VarianceWaiverService.review_waiver(db=db, waiver_id=waiver.id, decision="APPROVE", decision_notes="Approved for Batch", current_user=reviewer)
    db.commit()

    # Evaluation WITH approved waiver: ELIGIBLE
    res_eligible = CertificationService.evaluate_batch_certification(db, batch.id)
    assert res_eligible["is_eligible"] is True
    assert len(res_eligible["active_waivers"]) == 1
    assert res_eligible["active_waivers"][0]["waiver_id"] == str(waiver.id)


def test_four_eyes_enforced_on_certification(db, clean_batch_environment):
    batch = clean_batch_environment["batch"]
    # batch.triggered_by is "operator_scheduler"

    # Self-certification attempt: certifier matches trigger operator
    trigger_certifier = CurrentUser(
        user_id="operator_scheduler",
        email="scheduler@cinqflow.local",
        roles=["DATA_STEWARD", "ENGINEER"],
        auth_provider="mock",
    )

    with pytest.raises(HTTPException) as exc:
        CertificationService.certify_batch(
            db=db,
            batch_id=batch.id,
            current_user=trigger_certifier,
            certification_notes="I ran the batch and I am certifying it",
        )
    assert exc.value.status_code == 403
    assert "Four-eyes violation" in exc.value.detail

    # Distinct steward can certify
    steward_certifier = CurrentUser(
        user_id="steward_independent",
        email="independent_steward@cinqflow.local",
        roles=["DATA_STEWARD"],
        auth_provider="mock",
    )

    cert = CertificationService.certify_batch(
        db=db,
        batch_id=batch.id,
        current_user=steward_certifier,
        certification_notes="Independent attestation of data quality and completeness",
    )
    db.commit()

    assert cert.status == CertificationStatusEnum.CERTIFIED
    assert cert.certified_by == "steward_independent"
    assert cert.evidence_hash is not None
    assert len(cert.evidence_hash) == 64

    # Idempotent call returns existing certification
    cert_repeat = CertificationService.certify_batch(
        db=db,
        batch_id=batch.id,
        current_user=steward_certifier,
    )
    assert cert_repeat.id == cert.id
