"""
Unit tests for AlertService (CF-V2-E12-05)
Alert storm suppression, active deduplication, lifecycle transitions, and flapping detection.
"""
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from fastapi import HTTPException
from backend.services.alert_service import AlertService
from backend.models.incident import (
    OperationalAlert,
    AlertOccurrence,
    FailureCategoryEnum,
    AlertStatusEnum,
    AlertSeverityEnum,
)
from backend.models.feed import Feed, FeedFormatEnum, FeedStatusEnum


@pytest.fixture
def sample_feed(db):
    feed = Feed(
        name=f"test-feed-{uuid.uuid4().hex[:8]}",
        domain="CLAIMS",
        format=FeedFormatEnum.CSV,
        landing_folder="/landing/claims",
        filename_pattern="claims_*.csv",
        schedule_expression="0 6 * * *",
        status=FeedStatusEnum.ACTIVE,
        created_by="test-setup",
        updated_by="test-setup",
    )
    db.add(feed)
    db.commit()
    db.refresh(feed)
    return feed


def test_record_failure_creates_new_alert(db, sample_feed):
    """Initial failure creates an OPEN operational alert with 1 occurrence."""
    alert = AlertService.record_failure(
        db=db,
        feed_id=sample_feed.id,
        category=FailureCategoryEnum.DATA_QUALITY,
        failure_stage="SILVER_RAW",
        root_cause_pattern="Missing mandatory field: member_id",
        severity=AlertSeverityEnum.CRITICAL,
        user_id="test-operator",
    )
    assert alert.id is not None
    assert alert.status == AlertStatusEnum.OPEN
    assert alert.occurrence_count == 1
    assert alert.severity == AlertSeverityEnum.CRITICAL

    occurrences = db.query(AlertOccurrence).filter(AlertOccurrence.alert_id == alert.id).all()
    assert len(occurrences) == 1
    assert occurrences[0].stage == "SILVER_RAW"


def test_record_failure_storm_suppression_deduplication(db, sample_feed):
    """Repeated failures on the same feed and fingerprint increment occurrence count without creating duplicate alerts."""
    alert1 = AlertService.record_failure(
        db=db,
        feed_id=sample_feed.id,
        batch_id=None,
        category=FailureCategoryEnum.STAGE_EXECUTION,
        failure_stage="BRONZE",
        root_cause_pattern="Corrupt header in file batch",
        user_id="test-operator",
    )
    initial_id = alert1.id

    # Second failure with identical root cause pattern
    alert2 = AlertService.record_failure(
        db=db,
        feed_id=sample_feed.id,
        batch_id=None,
        category=FailureCategoryEnum.STAGE_EXECUTION,
        failure_stage="BRONZE",
        root_cause_pattern="Corrupt header in file batch",
        user_id="test-operator",
    )

    assert alert2.id == initial_id
    assert alert2.occurrence_count == 2

    # Total active alerts for this feed is exactly 1 (storm suppressed)
    count = db.query(OperationalAlert).filter(OperationalAlert.feed_id == sample_feed.id).count()
    assert count == 1

    # But 2 occurrences are recorded in timeline
    occurrences = db.query(AlertOccurrence).filter(AlertOccurrence.alert_id == initial_id).all()
    assert len(occurrences) == 2


def test_record_failure_different_feeds_independent_alerts(db, sample_feed):
    """Identical failure pattern across two distinct feeds produces two separate alerts."""
    feed2 = Feed(
        name=f"test-feed2-{uuid.uuid4().hex[:8]}",
        domain="ENROLLMENT",
        format=FeedFormatEnum.CSV,
        landing_folder="/landing/enrollment",
        filename_pattern="enrollment_*.csv",
        schedule_expression="0 8 * * *",
        status=FeedStatusEnum.ACTIVE,
        created_by="test-setup",
        updated_by="test-setup",
    )
    db.add(feed2)
    db.commit()

    alert1 = AlertService.record_failure(
        db=db,
        feed_id=sample_feed.id,
        category=FailureCategoryEnum.SCHEMA_DRIFT,
        failure_stage="LANDING",
        root_cause_pattern="Unexpected column 'ssn_extra' in feed",
    )
    alert2 = AlertService.record_failure(
        db=db,
        feed_id=feed2.id,
        category=FailureCategoryEnum.SCHEMA_DRIFT,
        failure_stage="LANDING",
        root_cause_pattern="Unexpected column 'ssn_extra' in feed",
    )

    assert alert1.id != alert2.id
    assert alert1.failure_fingerprint_id == alert2.failure_fingerprint_id


def test_record_failure_different_fingerprints_independent_alerts(db, sample_feed):
    """Two different failure types on the same feed produce two distinct alerts."""
    alert1 = AlertService.record_failure(
        db=db,
        feed_id=sample_feed.id,
        category=FailureCategoryEnum.DATA_QUALITY,
        failure_stage="SILVER_RAW",
        root_cause_pattern="Invalid date_of_birth format",
    )
    alert2 = AlertService.record_failure(
        db=db,
        feed_id=sample_feed.id,
        category=FailureCategoryEnum.RECONCILIATION,
        failure_stage="RECONCILIATION",
        root_cause_pattern="Balance discrepancy: 5 rows missing",
    )

    assert alert1.id != alert2.id
    assert alert1.failure_fingerprint_id != alert2.failure_fingerprint_id


def test_alert_acknowledge_lifecycle(db, sample_feed):
    """Alert can transition from OPEN to ACKNOWLEDGED."""
    alert = AlertService.record_failure(
        db=db,
        feed_id=sample_feed.id,
        category=FailureCategoryEnum.STAGE_EXECUTION,
        failure_stage="LANDING",
        root_cause_pattern="I/O error reading input file",
    )

    ack_alert = AlertService.acknowledge_alert(db=db, alert_id=alert.id, user_id="lead-steward@cinqflow.local")
    assert ack_alert.status == AlertStatusEnum.ACKNOWLEDGED
    assert ack_alert.acknowledged_by == "lead-steward@cinqflow.local"
    assert ack_alert.acknowledged_at is not None


def test_alert_resolve_lifecycle(db, sample_feed):
    """Alert can transition to RESOLVED with resolution explanation notes."""
    alert = AlertService.record_failure(
        db=db,
        feed_id=sample_feed.id,
        category=FailureCategoryEnum.STAGE_EXECUTION,
        failure_stage="LANDING",
        root_cause_pattern="I/O error reading input file",
    )

    res_alert = AlertService.resolve_alert(
        db=db,
        alert_id=alert.id,
        resolution_notes="Storage volume remounted and tested",
        user_id="lead-engineer@cinqflow.local",
    )
    assert res_alert.status == AlertStatusEnum.RESOLVED
    assert res_alert.resolved_by == "lead-engineer@cinqflow.local"
    assert res_alert.resolved_at is not None
    assert "Storage volume remounted" in res_alert.resolution_notes


def test_alert_flapping_reopen_within_2h(db, sample_feed):
    """Recurring failure within 2 hours of resolution triggers flapping detection: reopens the alert."""
    alert = AlertService.record_failure(
        db=db,
        feed_id=sample_feed.id,
        category=FailureCategoryEnum.DATA_QUALITY,
        failure_stage="SILVER_RAW",
        root_cause_pattern="Gender code 'U' rejected",
    )

    # Resolve alert
    AlertService.resolve_alert(
        db=db,
        alert_id=alert.id,
        resolution_notes="Mapping updated",
        user_id="steward",
    )
    db.commit()

    # Recurrence occurs 10 minutes later
    reopened = AlertService.record_failure(
        db=db,
        feed_id=sample_feed.id,
        category=FailureCategoryEnum.DATA_QUALITY,
        failure_stage="SILVER_RAW",
        root_cause_pattern="Gender code 'U' rejected",
        user_id="system",
    )

    assert reopened.id == alert.id
    assert reopened.status == AlertStatusEnum.REOPENED
    assert reopened.occurrence_count == 2
    assert "FLAPPING REOPENED" in reopened.resolution_notes


def test_alert_reopen_explicit_operator(db, sample_feed):
    """Operator can explicitly reopen a resolved alert."""
    alert = AlertService.record_failure(
        db=db,
        feed_id=sample_feed.id,
        category=FailureCategoryEnum.STAGE_EXECUTION,
        failure_stage="BRONZE",
        root_cause_pattern="Parser crash on empty lines",
    )
    AlertService.resolve_alert(db=db, alert_id=alert.id, resolution_notes="Done", user_id="operator")

    reopened = AlertService.reopen_alert(db=db, alert_id=alert.id, reason="Issue recurred in nightly run", user_id="operator2")
    assert reopened.status == AlertStatusEnum.REOPENED
    assert "Issue recurred" in reopened.resolution_notes


def test_alert_plain_english_translation(db, sample_feed):
    """Alert title and description must be human-readable plain English."""
    alert = AlertService.record_failure(
        db=db,
        feed_id=sample_feed.id,
        category=FailureCategoryEnum.SCHEMA_DRIFT,
        failure_stage="LANDING",
        root_cause_pattern="Missing column 'first_name'",
    )
    assert "Breaking Schema Drift" in alert.title
    assert sample_feed.name in alert.title
    assert "does not conform to the active published schema" in alert.description


def test_alert_zero_phi_in_occurrences(db, sample_feed):
    """Error context dictionary stored in occurrences must have PHI sanitized."""
    raw_ctx = {
        "error": "Record with SSN 123-45-6789 and patient.smith@clinic.com rejected",
        "sample_val": "555-456-7890",
    }
    alert = AlertService.record_failure(
        db=db,
        feed_id=sample_feed.id,
        category=FailureCategoryEnum.DATA_QUALITY,
        failure_stage="SILVER_RAW",
        root_cause_pattern="Invalid contact information",
        error_context=raw_ctx,
    )

    occ = db.query(AlertOccurrence).filter(AlertOccurrence.alert_id == alert.id).first()
    ctx_str = str(occ.error_context)
    assert "123-45-6789" not in ctx_str
    assert "patient.smith@clinic.com" not in ctx_str
    assert "[REDACTED_SSN]" in ctx_str
    assert "[REDACTED_EMAIL]" in ctx_str
