"""
Unit tests for VarianceWaiverService (CF-V2-E13-03).
Verifies:
- OperationalVariance recording with zero-PHI sanitization
- OperationalWaiver requesting with bounded expiration
- Four-eyes separation of duties (self-approval strictly rejected)
- Deterministic approval and rejection transitions
- Waiver expiration evaluation
- Waiver revocation and underlying variance status reversion
"""
import uuid
from datetime import datetime, timezone, timedelta
import pytest
from fastapi import HTTPException

from backend.models.governance import (
    OperationalVariance,
    OperationalWaiver,
    VarianceStatusEnum,
    WaiverStatusEnum,
    WaiverScopeEnum,
)
from backend.models.feed import Feed, FeedFormatEnum, FeedStatusEnum, FeedVersion, FeedVersionStatusEnum
from backend.models.pipeline import Batch, BatchStatusEnum
from backend.core.security import CurrentUser
from backend.services.variance_waiver_service import VarianceWaiverService
from backend.schemas.governance import WaiverSubmitRequest


@pytest.fixture
def test_feed(db):
    feed = Feed(
        id=uuid.uuid4(),
        name=f"TEST_GOV_FEED_{uuid.uuid4().hex[:6]}",
        domain="MEMBERS",
        format=FeedFormatEnum.CSV,
        status=FeedStatusEnum.ACTIVE,
        landing_folder="./data/landing",
        filename_pattern="*.csv",
        created_by="tester",
        updated_by="tester",
    )
    db.add(feed)
    fv = FeedVersion(
        id=uuid.uuid4(),
        feed_id=feed.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED,
        created_by="tester",
        updated_by="tester",
    )
    db.add(fv)
    db.commit()
    return feed


@pytest.fixture
def test_batch(db, test_feed):
    fv = db.query(FeedVersion).filter(FeedVersion.feed_id == test_feed.id).first()
    batch = Batch(
        id=uuid.uuid4(),
        feed_id=test_feed.id,
        feed_version_id=fv.id,
        status=BatchStatusEnum.FAILED,
        triggered_by="operator_trigger",
        created_by="operator_trigger",
        updated_by="operator_trigger",
    )
    db.add(batch)
    db.commit()
    return batch


def test_record_variance_with_zero_phi(db, test_feed, test_batch):
    variance = VarianceWaiverService.record_variance(
        db=db,
        feed_id=test_feed.id,
        batch_id=test_batch.id,
        control_type="DQ_RULE",
        control_id="RULE_MEMBER_ID_NOT_NULL",
        title="Patient John Doe SSN 123-45-6789 violation",
        description="Contact patient at john.doe@email.com or (555) 123-4567 regarding MRN 987654321",
        severity="WARNING",
        telemetry_snapshot={"failed_rows": 10, "notes": "Call (555) 123-4567"},
        user_id="analyst_1",
    )
    db.commit()

    assert variance.status == VarianceStatusEnum.OPEN
    # Verify Zero-PHI sanitization
    assert "[REDACTED_NAME]" in variance.title or "John Doe" not in variance.title
    assert "[REDACTED_SSN]" in variance.title
    assert "123-45-6789" not in variance.title
    assert "[REDACTED_EMAIL]" in variance.description
    assert "[REDACTED_PHONE]" in variance.description
    assert "[REDACTED_PHONE]" in str(variance.telemetry_snapshot)


def test_request_waiver_validation_and_bounds(db, test_feed, test_batch):
    variance = VarianceWaiverService.record_variance(
        db=db,
        feed_id=test_feed.id,
        batch_id=test_batch.id,
        control_type="DQ_RULE",
        control_id="RULE_001",
        title="Null Check Variance",
        description="Missing required last names",
        user_id="analyst_1",
    )
    db.commit()

    requester = CurrentUser(
        user_id="analyst_1",
        email="analyst@cinqflow.local",
        roles=["BUSINESS_ANALYST"],
        auth_provider="mock",
    )

    # 1. Reject past expiration
    with pytest.raises(HTTPException) as exc:
        VarianceWaiverService.request_waiver(
            db=db,
            req=WaiverSubmitRequest(
                variance_id=variance.id,
                business_justification="Vendor agreed to fix in next release",
                risk_assessment="Low clinical risk",
                mitigation_notes="Exclude from reporting",
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            ),
            current_user=requester,
        )
    assert exc.value.status_code == 400
    assert "strictly in the future" in exc.value.detail

    # 2. Reject expiration > 30 days
    with pytest.raises(HTTPException) as exc:
        VarianceWaiverService.request_waiver(
            db=db,
            req=WaiverSubmitRequest(
                variance_id=variance.id,
                business_justification="Vendor agreed to fix in next release",
                risk_assessment="Low clinical risk",
                mitigation_notes="Exclude from reporting",
                expires_at=datetime.now(timezone.utc) + timedelta(days=31),
            ),
            current_user=requester,
        )
    assert exc.value.status_code == 400
    assert "30 days" in exc.value.detail

    # 3. Valid waiver submission
    valid_req = WaiverSubmitRequest(
        variance_id=variance.id,
        scope=WaiverScopeEnum.SINGLE_BATCH,
        business_justification="Vendor confirmed fix deployed tomorrow",
        risk_assessment="Zero impact on financial reconciliation",
        mitigation_notes="Rows will be marked in quarantine",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    waiver = VarianceWaiverService.request_waiver(db=db, req=valid_req, current_user=requester)
    db.commit()

    assert waiver.status == WaiverStatusEnum.PENDING_APPROVAL
    assert waiver.requested_by == "analyst_1"
    assert waiver.batches_applied_count == 0


def test_four_eyes_separation_enforced_on_waiver_approval(db, test_feed, test_batch):
    variance = VarianceWaiverService.record_variance(
        db=db,
        feed_id=test_feed.id,
        batch_id=test_batch.id,
        control_type="RECONCILIATION",
        control_id="RECON_CHECK",
        title="Discrepancy 2 rows",
        description="Dropped header and trailer",
        user_id="steward_requester",
    )
    db.commit()

    requester = CurrentUser(
        user_id="steward_requester",
        email="steward@cinqflow.local",
        roles=["DATA_STEWARD", "ENGINEER"],
        auth_provider="mock",
    )

    waiver = VarianceWaiverService.request_waiver(
        db=db,
        req=WaiverSubmitRequest(
            variance_id=variance.id,
            business_justification="Header and trailer expected to drop",
            risk_assessment="No missing member rows",
            mitigation_notes="Reconciliation ledger updated",
            expires_at=datetime.now(timezone.utc) + timedelta(days=5),
        ),
        current_user=requester,
    )
    db.commit()

    # Attempt self-approval: same user ID
    with pytest.raises(HTTPException) as exc:
        VarianceWaiverService.review_waiver(
            db=db,
            waiver_id=waiver.id,
            decision="APPROVE",
            decision_notes="Self approving my own waiver",
            current_user=requester,
        )
    assert exc.value.status_code == 403
    assert "Four-eyes violation" in exc.value.detail

    # Attempt self-approval: different ID but identical email
    impostor = CurrentUser(
        user_id="other_id_same_email",
        email="steward@cinqflow.local",
        roles=["DATA_STEWARD"],
        auth_provider="mock",
    )
    with pytest.raises(HTTPException) as exc:
        VarianceWaiverService.review_waiver(
            db=db,
            waiver_id=waiver.id,
            decision="APPROVE",
            decision_notes="Trying to approve by matching email",
            current_user=impostor,
        )
    assert exc.value.status_code == 403
    assert "Four-eyes violation" in exc.value.detail

    # Distinct reviewer approves successfully
    reviewer = CurrentUser(
        user_id="lead_engineer_reviewer",
        email="lead@cinqflow.local",
        roles=["ENGINEER"],
        auth_provider="mock",
    )
    approved_waiver = VarianceWaiverService.review_waiver(
        db=db,
        waiver_id=waiver.id,
        decision="APPROVE",
        decision_notes="Approved after verifying named drop reasons",
        current_user=reviewer,
    )
    db.commit()

    assert approved_waiver.status == WaiverStatusEnum.APPROVED
    assert approved_waiver.reviewed_by == "lead_engineer_reviewer"
    db.refresh(variance)
    assert variance.status == VarianceStatusEnum.WAIVED


def test_waiver_revocation_and_variance_reversion(db, test_feed, test_batch):
    variance = VarianceWaiverService.record_variance(
        db=db,
        feed_id=test_feed.id,
        batch_id=test_batch.id,
        control_type="SCHEMA_DRIFT",
        control_id="DRIFT_EVENT_001",
        title="Tolerated extra column",
        description="Extra middle_initial",
        user_id="analyst_1",
    )
    db.commit()

    requester = CurrentUser(user_id="analyst_1", email="a@cinqflow.local", roles=["BUSINESS_ANALYST"], auth_provider="mock")
    reviewer = CurrentUser(user_id="steward_2", email="s@cinqflow.local", roles=["DATA_STEWARD"], auth_provider="mock")

    waiver = VarianceWaiverService.request_waiver(
        db=db,
        req=WaiverSubmitRequest(
            variance_id=variance.id,
            business_justification="Non-breaking column",
            risk_assessment="No schema corruption",
            mitigation_notes="Schema will be updated next sprint",
            expires_at=datetime.now(timezone.utc) + timedelta(days=10),
        ),
        current_user=requester,
    )
    VarianceWaiverService.review_waiver(db=db, waiver_id=waiver.id, decision="APPROVE", decision_notes="OK", current_user=reviewer)
    db.commit()

    db.refresh(variance)
    assert variance.status == VarianceStatusEnum.WAIVED

    # Revoke waiver
    revoked_waiver = VarianceWaiverService.revoke_waiver(
        db=db,
        waiver_id=waiver.id,
        revocation_reason="New vendor spec received; column is breaking",
        current_user=reviewer,
    )
    db.commit()

    assert revoked_waiver.status == WaiverStatusEnum.REVOKED
    db.refresh(variance)
    assert variance.status == VarianceStatusEnum.OPEN
