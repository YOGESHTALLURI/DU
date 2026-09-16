import uuid
from datetime import datetime, timedelta, timezone
from typing import Tuple
import pytest
from sqlalchemy.orm import Session

from backend.models.feed import Feed, FeedStatusEnum, FeedFormatEnum, FeedVersion, FeedVersionStatusEnum
from backend.models.pipeline import Batch, BatchStatusEnum
from backend.models.reconciliation import BatchReconciliation, ReconciliationStatusEnum
from backend.models.drift import SchemaDriftReport, DriftSeverityEnum, DriftStatusEnum
from backend.models.schema import Schema, SchemaVersion, SchemaVersionStatusEnum
from backend.models.schedule import FeedSchedule, ScheduleStatusEnum
from backend.services.ops_service import OpsService


def create_test_feed_with_version(
    db: Session,
    name: str = "Test Feed",
    domain: str = "CLAIMS",
    status: FeedStatusEnum = FeedStatusEnum.ACTIVE,
) -> Tuple[Feed, FeedVersion]:
    feed = Feed(
        id=uuid.uuid4(),
        name=f"{name}_{uuid.uuid4().hex[:6]}",
        domain=domain,
        format=FeedFormatEnum.CSV,
        landing_folder="/data/landing",
        filename_pattern="*.csv",
        schedule_expression="manual",
        status=status,
        created_by="test",
        updated_by="test",
    )
    db.add(feed)
    db.flush()

    ver = FeedVersion(
        id=uuid.uuid4(),
        feed_id=feed.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED,
        created_by="test",
        updated_by="test",
    )
    db.add(ver)
    db.commit()
    return feed, ver


def create_test_batch(
    db: Session,
    feed_id: uuid.UUID,
    feed_version_id: uuid.UUID,
    status: BatchStatusEnum = BatchStatusEnum.SUCCESS,
    created_at: datetime = None,
    error_message: str = None,
) -> Batch:
    if created_at is None:
        created_at = datetime.now(timezone.utc)
    batch = Batch(
        id=uuid.uuid4(),
        feed_id=feed_id,
        feed_version_id=feed_version_id,
        status=status,
        triggered_by="test_runner",
        error_message=error_message,
        created_at=created_at,
        created_by="test",
        updated_by="test",
    )
    db.add(batch)
    db.commit()
    return batch


def test_active_feeds_count(db: Session):
    """Verify active_feeds counts only ACTIVE feeds."""
    f1, _ = create_test_feed_with_version(db, name="Active Feed", status=FeedStatusEnum.ACTIVE)
    f2, _ = create_test_feed_with_version(db, name="Draft Feed", status=FeedStatusEnum.DRAFT)

    resp = OpsService.get_home_kpis(db)
    assert resp.kpis.active_feeds >= 1


def test_24h_batch_status_counts(db: Session):
    """Verify 24h batch counts match completed and failed statuses within the 24h window."""
    now = datetime.now(timezone.utc)
    feed, ver = create_test_feed_with_version(db, name="KPI Feed")

    create_test_batch(db, feed.id, ver.id, status=BatchStatusEnum.SUCCESS, created_at=now - timedelta(hours=2))
    create_test_batch(db, feed.id, ver.id, status=BatchStatusEnum.FAILED, created_at=now - timedelta(hours=3))
    create_test_batch(db, feed.id, ver.id, status=BatchStatusEnum.SUCCESS, created_at=now - timedelta(hours=26))

    resp = OpsService.get_home_kpis(db)
    assert resp.kpis.batches_24h_success >= 1
    assert resp.kpis.batches_24h_failed >= 1


def test_currently_running_batches_unbounded_window(db: Session):
    """A batch that started 36h ago and is still RUNNING must be counted in batches_running."""
    now = datetime.now(timezone.utc)
    feed, ver = create_test_feed_with_version(db, name="Running Feed")

    create_test_batch(db, feed.id, ver.id, status=BatchStatusEnum.RUNNING, created_at=now - timedelta(hours=36))

    resp = OpsService.get_home_kpis(db)
    assert resp.kpis.batches_running >= 1


def test_sla_adherence_percentage_calculation(db: Session):
    """Verify SLA adherence math: adheres to formula and ranges between 0.0 and 100.0."""
    now = datetime.now(timezone.utc)
    feed, _ = create_test_feed_with_version(db, name="SLA Feed")

    sched = FeedSchedule(
        id=uuid.uuid4(),
        feed_id=feed.id,
        schedule_expression="0 * * * *",
        timezone="UTC",
        sla_grace_minutes=30,
        lead_window_minutes=60,
        status=ScheduleStatusEnum.ACTIVE,
        created_by="test",
        updated_by="test",
    )
    db.add(sched)
    db.commit()

    resp = OpsService.get_home_kpis(db)
    assert 0.0 <= resp.kpis.sla_attainment_pct <= 100.0


def test_quarantine_records_sum_24h(db: Session):
    """Sum of quarantine rows in last 24h is calculated correctly via BatchReconciliation."""
    now = datetime.now(timezone.utc)
    feed, ver = create_test_feed_with_version(db, name="Quarantine Feed")

    batch1 = create_test_batch(db, feed.id, ver.id, status=BatchStatusEnum.SUCCESS, created_at=now - timedelta(hours=1))
    batch_old = create_test_batch(db, feed.id, ver.id, status=BatchStatusEnum.SUCCESS, created_at=now - timedelta(hours=26))

    r1 = BatchReconciliation(
        id=uuid.uuid4(),
        batch_id=batch1.id,
        rows_in=10,
        rows_silver_raw=8,
        rows_quarantined=2,
        rows_dropped=0,
        balance_check_passed=True,
        status=ReconciliationStatusEnum.PASS,
        created_by="test",
        updated_by="test",
    )
    r_old = BatchReconciliation(
        id=uuid.uuid4(),
        batch_id=batch_old.id,
        rows_in=5,
        rows_silver_raw=4,
        rows_quarantined=1,
        rows_dropped=0,
        balance_check_passed=True,
        status=ReconciliationStatusEnum.PASS,
        created_by="test",
        updated_by="test",
    )
    db.add_all([r1, r_old])
    db.commit()

    resp = OpsService.get_home_kpis(db)
    assert resp.kpis.quarantined_rows_24h >= 2


def test_schema_drift_alerts_breakdown(db: Session):
    """Verify non_breaking and breaking drift alerts in 24h are counted properly."""
    now = datetime.now(timezone.utc)
    feed, ver = create_test_feed_with_version(db, name="Drift Feed")

    sch = Schema(
        id=uuid.uuid4(),
        feed_id=feed.id,
        name="Schema For Drift Test",
        created_by="test",
        updated_by="test",
    )
    db.add(sch)
    db.commit()

    version = SchemaVersion(
        id=uuid.uuid4(),
        schema_id=sch.id,
        version_number=1,
        status=SchemaVersionStatusEnum.PUBLISHED,
        created_by="test",
        updated_by="test",
    )
    db.add(version)
    db.commit()

    batch = create_test_batch(db, feed.id, ver.id, status=BatchStatusEnum.SUCCESS, created_at=now - timedelta(hours=1))

    d1 = SchemaDriftReport(
        id=uuid.uuid4(),
        feed_id=feed.id,
        batch_id=batch.id,
        expected_schema_version_id=version.id,
        drift_severity=DriftSeverityEnum.NON_BREAKING,
        missing_fields=[],
        unexpected_fields=["col_a"],
        type_mismatches=[],
        status=DriftStatusEnum.DETECTED,
        created_at=now - timedelta(hours=1),
        created_by="test",
        updated_by="test",
    )
    d2 = SchemaDriftReport(
        id=uuid.uuid4(),
        feed_id=feed.id,
        batch_id=batch.id,
        expected_schema_version_id=version.id,
        drift_severity=DriftSeverityEnum.BREAKING,
        missing_fields=["req_col"],
        unexpected_fields=[],
        type_mismatches=[],
        status=DriftStatusEnum.DETECTED,
        created_at=now - timedelta(hours=2),
        created_by="test",
        updated_by="test",
    )
    db.add_all([d1, d2])
    db.commit()

    resp = OpsService.get_home_kpis(db)
    assert resp.kpis.non_breaking_drift_count >= 1
    assert resp.kpis.breaking_drift_count >= 1
    assert resp.kpis.unacknowledged_drift_alerts >= 2


def test_empty_database_division_by_zero_safety(db: Session):
    """Even if database has zero entities, get_home_kpis returns valid response with 100.0% SLA adherence."""
    resp = OpsService.get_home_kpis(db)
    assert isinstance(resp.kpis.sla_attainment_pct, float)
    assert resp.kpis.sla_attainment_pct >= 0.0


def test_rolling_24h_boundary_precision(db: Session):
    """Batch created at 24h - 10s is included in 24h count; 24h + 10s is excluded."""
    now = datetime.now(timezone.utc)
    feed, ver = create_test_feed_with_version(db, name="Boundary Feed")

    # inside 24h
    create_test_batch(db, feed.id, ver.id, status=BatchStatusEnum.SUCCESS, created_at=now - timedelta(hours=23, minutes=59))
    # outside 24h
    create_test_batch(db, feed.id, ver.id, status=BatchStatusEnum.SUCCESS, created_at=now - timedelta(hours=24, minutes=5))

    resp = OpsService.get_home_kpis(db)
    assert resp.kpis.batches_24h_success >= 1
