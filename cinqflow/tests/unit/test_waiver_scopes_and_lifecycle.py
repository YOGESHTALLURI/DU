"""
Wave 2 Slice 5 — Authoritative Waiver Scopes, Dynamic Expiration,
Revocation, and Active Waiver Uniqueness Tests.
Addresses Blockers 1, 2, 3, and 5.
"""
import uuid
from datetime import datetime, timezone, timedelta
import pytest
from fastapi import HTTPException

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
from backend.models.dq_result import DQResult, DQActionTakenEnum
from backend.models.schema import Schema, SchemaVersion, SchemaVersionStatusEnum
from backend.models.rule import DataQualityRule, RuleVersion, RuleVersionStatusEnum, RuleTypeEnum, RuleSeverityEnum
from backend.core.security import CurrentUser
from backend.services.variance_waiver_service import VarianceWaiverService
from backend.services.certification_service import CertificationService
from backend.schemas.governance import WaiverSubmitRequest


@pytest.fixture
def gov_feed(db):
    feed = Feed(
        id=uuid.uuid4(),
        name=f"FEED_GOV_{uuid.uuid4().hex[:6]}",
        domain="CLAIMS",
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
    db.commit()
    return feed


@pytest.fixture
def gov_batch(db, gov_feed):
    fv = db.query(FeedVersion).filter(FeedVersion.feed_id == gov_feed.id).first()
    batch = Batch(
        id=uuid.uuid4(),
        feed_id=gov_feed.id,
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
    return batch


# =============================================================================
# BLOCKER 1: ALL WAIVER SCOPES (SINGLE_BATCH, BATCH_RANGE, TIME_BOUNDED)
# =============================================================================

def test_scope_single_batch_matching(db, gov_feed, gov_batch):
    """SINGLE_BATCH matches only its specific batch; rejects other batches in the feed."""
    fv = db.query(FeedVersion).filter(FeedVersion.feed_id == gov_feed.id).first()
    other_batch = Batch(
        id=uuid.uuid4(),
        feed_id=gov_feed.id,
        feed_version_id=fv.id,
        status=BatchStatusEnum.SUCCESS,
        triggered_by="operator_a",
        created_by="operator_a",
        updated_by="operator_a",
    )
    db.add(other_batch)
    db.commit()

    now = datetime.now(timezone.utc)
    v1 = VarianceWaiverService.record_variance(
        db=db,
        feed_id=gov_feed.id,
        batch_id=gov_batch.id,
        control_type="DQ_RULE",
        control_id="RULE_001",
        title="Variance for single batch test",
        description="Testing single batch scope",
        user_id="approver",
    )
    db.commit()

    waiver = OperationalWaiver(
        id=uuid.uuid4(),
        variance_id=v1.id,
        feed_id=gov_feed.id,
        batch_id=gov_batch.id,
        scope=WaiverScopeEnum.SINGLE_BATCH,
        affected_control_type="DQ_RULE",
        affected_control_id="RULE_001",
        business_justification="Test justification",
        risk_assessment="Low risk",
        mitigation_notes="None required",
        valid_from=now - timedelta(hours=1),
        expires_at=now + timedelta(days=1),
        status=WaiverStatusEnum.APPROVED,
        requested_by="approver",
        created_by="approver",
        updated_by="approver",
    )
    db.add(waiver)
    db.commit()

    # Targets gov_batch -> True
    assert VarianceWaiverService.does_waiver_apply_to_batch(waiver, gov_batch, db) is True
    # Targets other_batch -> False
    assert VarianceWaiverService.does_waiver_apply_to_batch(waiver, other_batch, db) is False


def test_scope_batch_range_target_ids(db, gov_feed):
    """BATCH_RANGE matches batches included in target_batch_ids, rejects batches outside."""
    fv = db.query(FeedVersion).filter(FeedVersion.feed_id == gov_feed.id).first()
    b1 = Batch(id=uuid.uuid4(), feed_id=gov_feed.id, feed_version_id=fv.id, status=BatchStatusEnum.SUCCESS, triggered_by="op", created_by="op", updated_by="op")
    b2 = Batch(id=uuid.uuid4(), feed_id=gov_feed.id, feed_version_id=fv.id, status=BatchStatusEnum.SUCCESS, triggered_by="op", created_by="op", updated_by="op")
    b3 = Batch(id=uuid.uuid4(), feed_id=gov_feed.id, feed_version_id=fv.id, status=BatchStatusEnum.SUCCESS, triggered_by="op", created_by="op", updated_by="op")
    db.add_all([b1, b2, b3])
    db.commit()

    now = datetime.now(timezone.utc)
    v2 = VarianceWaiverService.record_variance(
        db=db,
        feed_id=gov_feed.id,
        batch_id=b1.id,
        control_type="DQ_RULE",
        control_id="RULE_001",
        title="Variance for batch range test",
        description="Testing batch range target ids scope",
        user_id="approver",
    )
    db.commit()

    waiver = OperationalWaiver(
        id=uuid.uuid4(),
        variance_id=v2.id,
        feed_id=gov_feed.id,
        batch_id=b1.id,
        scope=WaiverScopeEnum.BATCH_RANGE,
        target_batch_ids=[str(b1.id), str(b2.id)],
        affected_control_type="DQ_RULE",
        affected_control_id="RULE_001",
        business_justification="Test justification",
        risk_assessment="Low risk",
        mitigation_notes="None required",
        valid_from=now - timedelta(hours=1),
        expires_at=now + timedelta(days=1),
        status=WaiverStatusEnum.APPROVED,
        requested_by="approver",
        created_by="approver",
        updated_by="approver",
    )
    db.add(waiver)
    db.commit()

    assert VarianceWaiverService.does_waiver_apply_to_batch(waiver, b1, db) is True
    assert VarianceWaiverService.does_waiver_apply_to_batch(waiver, b2, db) is True
    assert VarianceWaiverService.does_waiver_apply_to_batch(waiver, b3, db) is False


def test_scope_batch_range_start_end(db, gov_feed):
    """BATCH_RANGE bounded by start and end batches matches batches executed within that range."""
    fv = db.query(FeedVersion).filter(FeedVersion.feed_id == gov_feed.id).first()
    t0 = datetime.now(timezone.utc) - timedelta(hours=5)
    b_start = Batch(id=uuid.uuid4(), feed_id=gov_feed.id, feed_version_id=fv.id, status=BatchStatusEnum.SUCCESS, triggered_by="op", created_by="op", updated_by="op", created_at=t0)
    b_mid = Batch(id=uuid.uuid4(), feed_id=gov_feed.id, feed_version_id=fv.id, status=BatchStatusEnum.SUCCESS, triggered_by="op", created_by="op", updated_by="op", created_at=t0 + timedelta(hours=1))
    b_end = Batch(id=uuid.uuid4(), feed_id=gov_feed.id, feed_version_id=fv.id, status=BatchStatusEnum.SUCCESS, triggered_by="op", created_by="op", updated_by="op", created_at=t0 + timedelta(hours=2))
    b_outside = Batch(id=uuid.uuid4(), feed_id=gov_feed.id, feed_version_id=fv.id, status=BatchStatusEnum.SUCCESS, triggered_by="op", created_by="op", updated_by="op", created_at=t0 + timedelta(hours=4))
    db.add_all([b_start, b_mid, b_end, b_outside])
    db.commit()

    now = datetime.now(timezone.utc)
    v3 = VarianceWaiverService.record_variance(
        db=db,
        feed_id=gov_feed.id,
        batch_id=b_start.id,
        control_type="DQ_RULE",
        control_id="RULE_001",
        title="Variance for batch range start-end test",
        description="Testing batch range start end scope",
        user_id="approver",
    )
    db.commit()

    waiver = OperationalWaiver(
        id=uuid.uuid4(),
        variance_id=v3.id,
        feed_id=gov_feed.id,
        batch_id=b_start.id,
        scope=WaiverScopeEnum.BATCH_RANGE,
        range_start_batch_id=b_start.id,
        range_end_batch_id=b_end.id,
        affected_control_type="DQ_RULE",
        affected_control_id="RULE_001",
        business_justification="Test justification",
        risk_assessment="Low risk",
        mitigation_notes="None required",
        valid_from=now - timedelta(hours=1),
        expires_at=now + timedelta(days=1),
        status=WaiverStatusEnum.APPROVED,
        requested_by="approver",
        created_by="approver",
        updated_by="approver",
    )
    db.add(waiver)
    db.commit()

    assert VarianceWaiverService.does_waiver_apply_to_batch(waiver, b_start, db) is True
    assert VarianceWaiverService.does_waiver_apply_to_batch(waiver, b_mid, db) is True
    assert VarianceWaiverService.does_waiver_apply_to_batch(waiver, b_end, db) is True
    assert VarianceWaiverService.does_waiver_apply_to_batch(waiver, b_outside, db) is False


def test_scope_time_bounded_window(db, gov_feed):
    """TIME_BOUNDED matches batches executed within the time window, rejects outside batches."""
    fv = db.query(FeedVersion).filter(FeedVersion.feed_id == gov_feed.id).first()
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=3)
    window_end = now + timedelta(hours=3)

    b_inside = Batch(id=uuid.uuid4(), feed_id=gov_feed.id, feed_version_id=fv.id, status=BatchStatusEnum.SUCCESS, triggered_by="op", created_by="op", updated_by="op", created_at=now)
    b_before = Batch(id=uuid.uuid4(), feed_id=gov_feed.id, feed_version_id=fv.id, status=BatchStatusEnum.SUCCESS, triggered_by="op", created_by="op", updated_by="op", created_at=window_start - timedelta(minutes=10))
    b_after = Batch(id=uuid.uuid4(), feed_id=gov_feed.id, feed_version_id=fv.id, status=BatchStatusEnum.SUCCESS, triggered_by="op", created_by="op", updated_by="op", created_at=window_end + timedelta(minutes=10))
    db.add_all([b_inside, b_before, b_after])
    db.commit()

    v4 = VarianceWaiverService.record_variance(
        db=db,
        feed_id=gov_feed.id,
        batch_id=b_inside.id,
        control_type="DQ_RULE",
        control_id="RULE_001",
        title="Variance for time bounded test",
        description="Testing time bounded scope",
        user_id="approver",
    )
    db.commit()

    waiver = OperationalWaiver(
        id=uuid.uuid4(),
        variance_id=v4.id,
        feed_id=gov_feed.id,
        batch_id=b_inside.id,
        scope=WaiverScopeEnum.TIME_BOUNDED,
        valid_from=window_start,
        expires_at=window_end,
        affected_control_type="DQ_RULE",
        affected_control_id="RULE_001",
        business_justification="Test justification",
        risk_assessment="Low risk",
        mitigation_notes="None required",
        status=WaiverStatusEnum.APPROVED,
        requested_by="approver",
        created_by="approver",
        updated_by="approver",
    )
    db.add(waiver)
    db.commit()

    assert VarianceWaiverService.does_waiver_apply_to_batch(waiver, b_inside, db, reference_time=now) is True
    assert VarianceWaiverService.does_waiver_apply_to_batch(waiver, b_before, db, reference_time=now) is False
    assert VarianceWaiverService.does_waiver_apply_to_batch(waiver, b_after, db, reference_time=now) is False


# =============================================================================
# BLOCKER 2: "ACTIVE WAIVER" UNIQUENESS & AUDIT PRESERVATION
# =============================================================================

def test_active_waiver_uniqueness_lifecycle(db, gov_feed, gov_batch):
    """
    Proves:
    1. Only 1 pending or approved waiver allowed at a time for a variance.
    2. Rejected waiver allows a new waiver request.
    3. Expired approved waiver allows a new waiver request.
    4. Revoked approved waiver allows a new waiver request.
    5. Full historical audit records are preserved (never overwritten).
    """
    variance = VarianceWaiverService.record_variance(
        db=db,
        feed_id=gov_feed.id,
        batch_id=gov_batch.id,
        control_type="DQ_RULE",
        control_id="RULE_TEST_UNIQ",
        title="Test Variance Uniqueness",
        description="Testing uniqueness of active waivers",
        user_id="analyst_1",
    )
    db.commit()

    now = datetime.now(timezone.utc)
    u_req = CurrentUser(user_id="analyst_1", email="analyst_1@cinqflow.com", roles=["ANALYST"], auth_provider="mock")
    u_rev = CurrentUser(user_id="steward_1", email="steward_1@cinqflow.com", roles=["DATA_STEWARD"], auth_provider="mock")

    # 1. Request first waiver
    w1 = VarianceWaiverService.request_waiver(
        db=db,
        req=WaiverSubmitRequest(
            variance_id=variance.id,
            scope=WaiverScopeEnum.SINGLE_BATCH,
            business_justification="First waiver detailed justification",
            risk_assessment="Low risk operational impact assessment",
            mitigation_notes="Temporary monitoring mitigation plan",
            expires_at=now + timedelta(days=5),
        ),
        current_user=u_req,
    )
    db.commit()
    assert w1.status == WaiverStatusEnum.PENDING_APPROVAL

    # Duplicate pending request must fail
    with pytest.raises(HTTPException) as exc:
        VarianceWaiverService.request_waiver(
            db=db,
            req=WaiverSubmitRequest(
                variance_id=variance.id,
                scope=WaiverScopeEnum.SINGLE_BATCH,
                business_justification="Duplicate pending waiver request",
                risk_assessment="Low risk operational impact assessment",
                mitigation_notes="Temporary monitoring mitigation plan",
                expires_at=now + timedelta(days=5),
            ),
            current_user=u_req,
        )
    assert exc.value.status_code == 400
    assert "already pending review" in exc.value.detail

    # 2. Reject w1 -> now a new request should be allowed
    VarianceWaiverService.review_waiver(
        db=db,
        waiver_id=w1.id,
        decision="REJECT",
        decision_notes="Not justified by current operational policy",
        current_user=u_rev,
    )
    db.commit()
    assert w1.status == WaiverStatusEnum.REJECTED

    # Request new waiver after rejection -> succeeds!
    w2 = VarianceWaiverService.request_waiver(
        db=db,
        req=WaiverSubmitRequest(
            variance_id=variance.id,
            scope=WaiverScopeEnum.SINGLE_BATCH,
            business_justification="Second waiver with more comprehensive detail",
            risk_assessment="Low risk operational impact assessment",
            mitigation_notes="Temporary monitoring mitigation plan",
            expires_at=now + timedelta(days=2),
        ),
        current_user=u_req,
    )
    db.commit()
    assert w2.status == WaiverStatusEnum.PENDING_APPROVAL

    # Approve w2
    VarianceWaiverService.review_waiver(
        db=db,
        waiver_id=w2.id,
        decision="APPROVE",
        decision_notes="Approved under operational variance exception",
        current_user=u_rev,
    )
    db.commit()
    assert w2.status == WaiverStatusEnum.APPROVED

    # Duplicate while approved & active must fail
    with pytest.raises(HTTPException) as exc:
        VarianceWaiverService.request_waiver(
            db=db,
            req=WaiverSubmitRequest(
                variance_id=variance.id,
                scope=WaiverScopeEnum.SINGLE_BATCH,
                business_justification="Third waiver while second active",
                risk_assessment="Low risk operational impact assessment",
                mitigation_notes="Temporary monitoring mitigation plan",
                expires_at=now + timedelta(days=5),
            ),
            current_user=u_req,
        )
    assert exc.value.status_code == 400
    assert "already exists" in exc.value.detail

    # 3. Simulate w2 expiration (by setting its expires_at in the past)
    w2.expires_at = now - timedelta(minutes=1)
    db.commit()

    # Requesting waiver when previous approved waiver is expired -> should transition w2 to EXPIRED and allow new waiver!
    w3 = VarianceWaiverService.request_waiver(
        db=db,
        req=WaiverSubmitRequest(
            variance_id=variance.id,
            scope=WaiverScopeEnum.SINGLE_BATCH,
            business_justification="Third waiver after second expired",
            risk_assessment="Low risk operational impact assessment",
            mitigation_notes="Temporary monitoring mitigation plan",
            expires_at=now + timedelta(days=5),
        ),
        current_user=u_req,
    )
    db.commit()
    assert w2.status == WaiverStatusEnum.EXPIRED
    assert w3.status == WaiverStatusEnum.PENDING_APPROVAL

    # Approve w3
    VarianceWaiverService.review_waiver(
        db=db,
        waiver_id=w3.id,
        decision="APPROVE",
        decision_notes="Approved again under governance policy",
        current_user=u_rev,
    )
    db.commit()
    assert w3.status == WaiverStatusEnum.APPROVED

    # 4. Revoke w3
    VarianceWaiverService.revoke_waiver(
        db=db,
        waiver_id=w3.id,
        revocation_reason="Revoked by operational policy",
        current_user=u_rev,
    )
    db.commit()
    assert w3.status == WaiverStatusEnum.REVOKED

    # Requesting waiver after revocation -> should be allowed!
    w4 = VarianceWaiverService.request_waiver(
        db=db,
        req=WaiverSubmitRequest(
            variance_id=variance.id,
            scope=WaiverScopeEnum.SINGLE_BATCH,
            business_justification="Fourth waiver after revocation",
            risk_assessment="Low risk operational impact assessment",
            mitigation_notes="Temporary monitoring mitigation plan",
            expires_at=now + timedelta(days=5),
        ),
        current_user=u_req,
    )
    db.commit()
    assert w4.status == WaiverStatusEnum.PENDING_APPROVAL

    # 5. Verify ALL historical waiver records are preserved in the DB
    all_waivers = db.query(OperationalWaiver).filter(OperationalWaiver.variance_id == variance.id).all()
    assert len(all_waivers) == 4
    statuses = {w.status for w in all_waivers}
    assert WaiverStatusEnum.REJECTED in statuses
    assert WaiverStatusEnum.EXPIRED in statuses
    assert WaiverStatusEnum.REVOKED in statuses
    assert WaiverStatusEnum.PENDING_APPROVAL in statuses


# =============================================================================
# BLOCKER 3: PROVE EXPIRATION ACTUALLY REMOVES EXEMPTION (TIME ADVANCE)
# =============================================================================

def test_expiration_removes_exemption_without_mutating_telemetry(db, gov_feed, gov_batch):
    """
    1. Batch has a DQ violation that blocks certification.
    2. Approve waiver with future expiration (expires in 2 hours).
    3. Evaluate certification at t0 + 1 hour -> ELIGIBLE.
    4. Advance reference time to t0 + 3 hours -> BLOCKED.
    5. Underlying DQ failure telemetry remains completely untouched.
    """
    schema_obj = Schema(
        id=uuid.uuid4(),
        feed_id=gov_feed.id,
        name=f"SCHEMA_{uuid.uuid4().hex[:6]}",
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
        feed_id=gov_feed.id,
        schema_id=schema_obj.id,
        name=f"RULE_{uuid.uuid4().hex[:6]}",
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
    rule_id = rule_ver.id

    stage = gov_batch.stages[0]
    dq = DQResult(
        id=uuid.uuid4(),
        batch_id=gov_batch.id,
        stage_id=stage.id,
        rule_version_id=rule_id,
        total_rows_evaluated=100,
        passed_rows=90,
        failed_rows=10,
        pass_rate=90.0,
        action_taken=DQActionTakenEnum.QUARANTINED_ROWS,
        created_by="system",
        updated_by="system",
    )
    db.add(dq)
    db.commit()

    # Step 1: Initial evaluation is BLOCKED due to DQ violation
    initial_eval = CertificationService.evaluate_batch_certification(db, gov_batch.id)
    assert initial_eval["is_eligible"] is False
    assert any("Data Quality" in r for r in initial_eval["blocking_reasons"])

    # Step 2: Create variance and approve waiver valid for 2 hours
    variance = VarianceWaiverService.record_variance(
        db=db,
        feed_id=gov_feed.id,
        batch_id=gov_batch.id,
        control_type="DQ_RULE",
        control_id=str(rule_id),
        title="Rule failure on batch",
        description="Failing rows on rule",
        user_id="steward",
    )
    db.commit()

    t0 = datetime.now(timezone.utc)
    waiver = OperationalWaiver(
        id=uuid.uuid4(),
        variance_id=variance.id,
        feed_id=gov_feed.id,
        batch_id=gov_batch.id,
        scope=WaiverScopeEnum.SINGLE_BATCH,
        affected_control_type="DQ_RULE",
        affected_control_id=str(rule_id),
        business_justification="Accept temporary 10 row failure",
        risk_assessment="Low impact",
        mitigation_notes="Manual review completed",
        valid_from=t0,
        expires_at=t0 + timedelta(hours=2),
        status=WaiverStatusEnum.APPROVED,
        requested_by="steward",
        created_by="steward",
        updated_by="steward",
    )
    db.add(waiver)
    db.commit()

    # Step 3: Evaluate at t0 + 1 hour -> ELIGIBLE
    t_mid = t0 + timedelta(hours=1)
    mid_eval = CertificationService.evaluate_batch_certification(db, gov_batch.id, evaluate_at=t_mid)
    assert mid_eval["is_eligible"] is True
    assert len(mid_eval["active_waivers"]) == 1
    assert mid_eval["active_waivers"][0]["waiver_id"] == str(waiver.id)

    # Step 4: Evaluate at t0 + 3 hours (past expiration) -> BLOCKED
    t_after = t0 + timedelta(hours=3)
    post_eval = CertificationService.evaluate_batch_certification(db, gov_batch.id, evaluate_at=t_after)
    assert post_eval["is_eligible"] is False
    assert len(post_eval["active_waivers"]) == 0
    assert any("Data Quality violations without waiver" in r for r in post_eval["blocking_reasons"])

    # Step 5: Verify underlying DQ result telemetry was NOT mutated
    persisted_dq = db.query(DQResult).filter(DQResult.id == dq.id).first()
    assert persisted_dq.failed_rows == 10
    assert persisted_dq.action_taken == DQActionTakenEnum.QUARANTINED_ROWS
    assert persisted_dq.passed_rows == 90


# =============================================================================
# BLOCKER 5 & DESIGN CHECK: REVOCATION RETRIEVAL & CREATION SAFETY
# =============================================================================

def test_revocation_retrieval_and_recertification(db, gov_feed, gov_batch):
    """
    1. Certify an eligible batch.
    2. Revoke the certification.
    3. Verify get_batch_certification returns status REVOKED (not None).
    4. Verify get_certification by ID returns the revoked record.
    5. Re-certify the batch: issues a new active CERTIFIED record.
    """
    certifier = CurrentUser(user_id="steward_1", email="steward_1@cinqflow.com", roles=["DATA_STEWARD"], auth_provider="mock")

    # Step 1: Certify
    cert1 = CertificationService.certify_batch(
        db=db,
        batch_id=gov_batch.id,
        current_user=certifier,
        certification_notes="Certified v1",
    )
    db.commit()
    assert cert1.status == CertificationStatusEnum.CERTIFIED

    # Step 2: Revoke
    revoked_cert = CertificationService.revoke_certification(
        db=db,
        certification_id=cert1.id,
        current_user=certifier,
        revocation_reason="Discovered latent issue in source feed",
    )
    db.commit()
    assert revoked_cert.status == CertificationStatusEnum.REVOKED
    assert revoked_cert.revocation_reason == "Discovered latent issue in source feed"

    # Step 3: get_batch_certification retrieves the REVOKED certificate
    latest_cert = CertificationService.get_batch_certification(db, gov_batch.id)
    assert latest_cert is not None
    assert latest_cert.id == cert1.id
    assert latest_cert.status == CertificationStatusEnum.REVOKED

    # Step 4: get_certification by ID retrieves the certificate
    byId_cert = CertificationService.get_certification(db, cert1.id)
    assert byId_cert.id == cert1.id
    assert byId_cert.status == CertificationStatusEnum.REVOKED

    # Step 5: Re-certification is permitted and issues new CERTIFIED record
    cert2 = CertificationService.certify_batch(
        db=db,
        batch_id=gov_batch.id,
        current_user=certifier,
        certification_notes="Re-certified after verification",
    )
    db.commit()
    assert cert2.id != cert1.id
    assert cert2.status == CertificationStatusEnum.CERTIFIED

    # Latest certificate is now the active cert2
    current_active = CertificationService.get_batch_certification(db, gov_batch.id)
    assert current_active.id == cert2.id
    assert current_active.status == CertificationStatusEnum.CERTIFIED


def test_creation_safety_ineligible_batch_cannot_create_certified_row(db, gov_feed):
    """
    Prove that an ineligible batch (e.g. batch with FAILED status or active DQ failure)
    strictly cannot create a BatchDataCertification record via certify_batch.
    """
    fv = db.query(FeedVersion).filter(FeedVersion.feed_id == gov_feed.id).first()
    failed_batch = Batch(
        id=uuid.uuid4(),
        feed_id=gov_feed.id,
        feed_version_id=fv.id,
        status=BatchStatusEnum.FAILED,
        triggered_by="operator_a",
        created_by="operator_a",
        updated_by="operator_a",
    )
    db.add(failed_batch)
    db.commit()

    certifier = CurrentUser(user_id="steward_1", email="steward_1@cinqflow.com", roles=["DATA_STEWARD"], auth_provider="mock")

    with pytest.raises(HTTPException) as exc:
        CertificationService.certify_batch(
            db=db,
            batch_id=failed_batch.id,
            current_user=certifier,
        )
    assert exc.value.status_code == 400
    assert "not eligible for certification" in exc.value.detail

    # Verify no row was inserted
    count = db.query(BatchDataCertification).filter(BatchDataCertification.batch_id == failed_batch.id).count()
    assert count == 0
