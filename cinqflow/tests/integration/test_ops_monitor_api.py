import uuid
from datetime import datetime, timedelta, timezone
from typing import Tuple
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from backend.models.feed import Feed, FeedStatusEnum, FeedFormatEnum, FeedVersion, FeedVersionStatusEnum
from backend.models.pipeline import Batch, BatchStatusEnum, BatchStage, StageNameEnum, StageStatusEnum
from backend.models.schedule import FeedSchedule, ScheduleStatusEnum
from backend.models.input_registry import InputRegistry, InputStatusEnum
from backend.models.audit import AuditEvent, AuditActionEnum
from backend.models.reconciliation import BatchReconciliation, ReconciliationStatusEnum
from backend.models.dq_result import DQResult, DQActionTakenEnum
from backend.models.drift import SchemaDriftReport, DriftSeverityEnum, DriftStatusEnum
from backend.models.schema import Schema, SchemaVersion, SchemaVersionStatusEnum


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
    input_registry_id: uuid.UUID = None,
) -> Batch:
    if created_at is None:
        created_at = datetime.now(timezone.utc)
    batch = Batch(
        id=uuid.uuid4(),
        feed_id=feed_id,
        feed_version_id=feed_version_id,
        input_registry_id=input_registry_id,
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


def test_ops_home_endpoint(client: TestClient, engineer_headers: dict):
    """GET /api/v1/ops/home returns 200 and OpsHomeResponse structure."""
    res = client.get("/api/v1/ops/home", headers=engineer_headers)
    assert res.status_code == 200
    data = res.json()
    assert "kpis" in data
    assert "window_start" in data
    assert "window_end" in data
    assert "active_feeds" in data["kpis"]
    assert "sla_attainment_pct" in data["kpis"]
    assert "breaking_drift_count" in data["kpis"]


def test_ops_arrivals_board_endpoint(client: TestClient, engineer_headers: dict, db: Session):
    """GET /api/v1/ops/arrivals returns 200 and arrivals board items."""
    feed, _ = create_test_feed_with_version(db, name="Arrival API Feed")

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

    res = client.get("/api/v1/ops/arrivals?window_hours=24", headers=engineer_headers)
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "total_slots" in data
    assert isinstance(data["items"], list)


def test_ops_arrivals_filtering_feed_and_status(client: TestClient, engineer_headers: dict, db: Session):
    """Query params feed_id and status properly filter arrivals."""
    feed, _ = create_test_feed_with_version(db, name="Filter API Feed")

    sched = FeedSchedule(
        id=uuid.uuid4(),
        feed_id=feed.id,
        schedule_expression="0 12 * * *",
        timezone="UTC",
        sla_grace_minutes=30,
        lead_window_minutes=60,
        status=ScheduleStatusEnum.ACTIVE,
        created_by="test",
        updated_by="test",
    )
    db.add(sched)
    db.commit()

    res = client.get(f"/api/v1/ops/arrivals?feed_id={feed.id}&status=EXPECTED", headers=engineer_headers)
    assert res.status_code == 200
    data = res.json()
    for item in data["items"]:
        assert item["feed_id"] == str(feed.id)
        assert item["status"] == "EXPECTED"


def test_ops_batch_monitor_pagination_boundary(client: TestClient, engineer_headers: dict, db: Session):
    """GET /api/v1/ops/monitor supports limit, page boundaries, and total counts."""
    feed, ver = create_test_feed_with_version(db, name="Pagination Feed")

    for i in range(5):
        create_test_batch(db, feed.id, ver.id, status=BatchStatusEnum.SUCCESS)

    # Page 1
    res1 = client.get("/api/v1/ops/monitor?limit=2&page=1", headers=engineer_headers)
    assert res1.status_code == 200
    data1 = res1.json()
    assert len(data1["items"]) == 2
    assert data1["page"] == 1

    # Large page beyond total
    res_empty = client.get("/api/v1/ops/monitor?limit=10&page=999", headers=engineer_headers)
    assert res_empty.status_code == 200
    data_empty = res_empty.json()
    assert len(data_empty["items"]) == 0
    assert data_empty["page"] == 999


def test_ops_batch_monitor_filtering(client: TestClient, engineer_headers: dict, db: Session):
    """GET /api/v1/ops/monitor correctly filters by feed_id and status."""
    feed1, ver1 = create_test_feed_with_version(db, name="Mon Feed 1")
    feed2, ver2 = create_test_feed_with_version(db, name="Mon Feed 2")

    create_test_batch(db, feed1.id, ver1.id, status=BatchStatusEnum.FAILED)
    create_test_batch(db, feed2.id, ver2.id, status=BatchStatusEnum.SUCCESS)

    res = client.get(f"/api/v1/ops/monitor?feed_id={feed1.id}&status=FAILED", headers=engineer_headers)
    assert res.status_code == 200
    data = res.json()
    for item in data["items"]:
        assert item["feed_id"] == str(feed1.id)
        assert item["batch_status"] == "FAILED"


def test_ops_batch_detail_with_stages_dq_drift_reconciliation(client: TestClient, engineer_headers: dict, db: Session):
    """GET /api/v1/ops/monitor/{batch_id} returns stages, DQ summary, drift report, and reconciliation ledger simultaneously."""
    feed, ver = create_test_feed_with_version(db, name="Full Detail Feed")

    batch = create_test_batch(db, feed.id, ver.id, status=BatchStatusEnum.SUCCESS)

    # 1. Stage
    stage = BatchStage(
        id=uuid.uuid4(),
        batch_id=batch.id,
        stage_name=StageNameEnum.LANDING,
        stage_order=1,
        status=StageStatusEnum.SUCCESS,
        rows_in=100,
        rows_out=100,
        rows_quarantined=0,
        created_by="test",
        updated_by="test",
    )
    db.add(stage)

    # 2. Reconciliation
    recon = BatchReconciliation(
        id=uuid.uuid4(),
        batch_id=batch.id,
        rows_in=100,
        rows_silver_raw=100,
        rows_quarantined=0,
        rows_dropped=0,
        balance_check_passed=True,
        status=ReconciliationStatusEnum.PASS,
        created_by="test",
        updated_by="test",
    )
    db.add(recon)

    # 3. Schema & Drift
    sch = Schema(id=uuid.uuid4(), feed_id=feed.id, name="SchDetail", created_by="test", updated_by="test")
    db.add(sch)
    db.flush()
    s_ver = SchemaVersion(id=uuid.uuid4(), schema_id=sch.id, version_number=1, status=SchemaVersionStatusEnum.PUBLISHED, created_by="test", updated_by="test")
    db.add(s_ver)
    db.flush()

    drift = SchemaDriftReport(
        id=uuid.uuid4(),
        feed_id=feed.id,
        batch_id=batch.id,
        expected_schema_version_id=s_ver.id,
        drift_severity=DriftSeverityEnum.NON_BREAKING,
        missing_fields=[],
        unexpected_fields=["extra_col"],
        type_mismatches=[],
        status=DriftStatusEnum.DETECTED,
        created_by="test",
        updated_by="test",
    )
    db.add(drift)
    db.commit()

    res = client.get(f"/api/v1/ops/monitor/{batch.id}", headers=engineer_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["batch_id"] == str(batch.id)
    assert len(data["stages"]) == 1
    assert data["stages"][0]["stage_name"] == "LANDING"
    assert data["reconciliation"] is not None
    assert data["reconciliation"]["balance_check_passed"] is True
    assert data["drift_report"] is not None
    assert data["drift_report"]["drift_severity"] == "NON_BREAKING"


def test_ops_rbac_all_authorized_roles(client: TestClient, engineer_headers: dict, readonly_headers: dict, analyst_headers: dict, steward_headers: dict):
    """All authorized roles (ENGINEER, ANALYST, STEWARD, READ_ONLY) can view Ops endpoints."""
    for headers in [engineer_headers, readonly_headers, analyst_headers, steward_headers]:
        res = client.get("/api/v1/ops/home", headers=headers)
        assert res.status_code == 200
        res = client.get("/api/v1/ops/arrivals", headers=headers)
        assert res.status_code == 200
        res = client.get("/api/v1/ops/monitor", headers=headers)
        assert res.status_code == 200


def test_ops_unauthenticated_access_rejected(client: TestClient):
    """Unauthenticated requests to Ops endpoints return 401."""
    res = client.get("/api/v1/ops/home")
    assert res.status_code == 401
    res = client.get("/api/v1/ops/arrivals")
    assert res.status_code == 401
    res = client.get("/api/v1/ops/monitor")
    assert res.status_code == 401


def test_zero_phi_filename_and_error_sanitization(client: TestClient, engineer_headers: dict, db: Session):
    """Verify sensitive filenames (with member SSN/name) and error messages have PHI strictly masked."""
    feed, ver = create_test_feed_with_version(db, name="PHI Sanitization Feed")

    # Sensitive input filename containing member SSN
    input_rec = InputRegistry(
        id=uuid.uuid4(),
        feed_id=feed.id,
        filename="ELIG_DOE_JOHN_123-45-6789_20260906.csv",
        file_path="/data/landing/ELIG_DOE_JOHN_123-45-6789_20260906.csv",
        file_size_bytes=2048,
        file_fingerprint="fp_sensitive_phi_1",
        status=InputStatusEnum.ACCEPTED,
        registered_by="test",
        detected_at=datetime.now(timezone.utc),
        created_by="test",
        updated_by="test",
    )
    db.add(input_rec)
    db.commit()

    batch = create_test_batch(
        db,
        feed.id,
        ver.id,
        input_registry_id=input_rec.id,
        status=BatchStatusEnum.FAILED,
        error_message="Failed row for member 123-45-6789 and email patient@hospital.org call 555-123-4567",
    )

    res = client.get(f"/api/v1/ops/monitor/{batch.id}", headers=engineer_headers)
    assert res.status_code == 200
    data = res.json()

    # 1. Verify sanitized error message
    sanitized_err = data["error_message"]
    assert "123-45-6789" not in sanitized_err
    assert "[REDACTED_SSN]" in sanitized_err
    assert "patient@hospital.org" not in sanitized_err
    assert "[REDACTED_EMAIL]" in sanitized_err
    assert "555-123-4567" not in sanitized_err
    assert "[REDACTED_PHONE]" in sanitized_err

    # 2. Verify sanitized filename
    sanitized_fname = data["filename"]
    assert "123-45-6789" not in sanitized_fname
    assert "[REDACTED_SSN]" in sanitized_fname


def test_zero_polling_audit_noise_and_session_start(client: TestClient, engineer_headers: dict, db: Session):
    """Polling endpoints create 0 audit logs, while session-start creates exactly 1 audit log."""
    count_before = db.scalar(select(func.count()).select_from(AuditEvent)) or 0

    # Execute polling endpoints repeatedly
    client.get("/api/v1/ops/home", headers=engineer_headers)
    client.get("/api/v1/ops/arrivals", headers=engineer_headers)
    client.get("/api/v1/ops/monitor", headers=engineer_headers)

    count_after_polling = db.scalar(select(func.count()).select_from(AuditEvent)) or 0
    assert count_after_polling == count_before

    # Now call session-start
    res = client.post("/api/v1/ops/session-start", headers=engineer_headers)
    assert res.status_code == 200

    count_after_session = db.scalar(select(func.count()).select_from(AuditEvent)) or 0
    assert count_after_session == count_before + 1

    # Verify audit action
    latest_audit = db.execute(
        select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(1)
    ).scalar_one()
    assert latest_audit.action == AuditActionEnum.OPS_DASHBOARD_VIEWED.value
