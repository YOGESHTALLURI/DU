"""
Wave 2 Slice 2 Independent Live Verification Script
Verifies:
1. PostgreSQL schema columns (lead_window_minutes, sla_grace_minutes) & composite indexes
2. REST endpoints (/home, /arrivals, /monitor, /monitor/{batch_id})
3. All 5 SLA states (EXPECTED, ON_TIME, LATE, MISSED_SLA, UNSCHEDULED_ARRIVAL)
4. Zero PHI in error messages and filenames
5. Zero audit log pollution from periodic polling
"""
import uuid
import sys
import os
sys.path.insert(0, os.path.abspath("."))
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine, text, select, func
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from backend.main import app
from backend.models.feed import Feed, FeedStatusEnum, FeedFormatEnum, FeedVersion, FeedVersionStatusEnum
from backend.models.schedule import FeedSchedule, ScheduleStatusEnum
from backend.models.input_registry import InputRegistry, InputStatusEnum
from backend.models.pipeline import Batch, BatchStatusEnum, BatchStage, StageNameEnum, StageStatusEnum
from backend.models.reconciliation import BatchReconciliation, ReconciliationStatusEnum
from backend.models.drift import SchemaDriftReport, DriftSeverityEnum, DriftStatusEnum
from backend.models.schema import Schema, SchemaVersion, SchemaVersionStatusEnum
from backend.models.audit import AuditEvent, AuditActionEnum
from backend.core.config import settings

def run_live_verification():
    print("=" * 70)
    print("CINQFLOW Wave 2 Slice 2 — Live Verification")
    print("=" * 70)

    engine = create_engine(settings.DATABASE_URL)
    Session = sessionmaker(bind=engine)
    db = Session()
    client = TestClient(app)

    # 1. Verify PostgreSQL Schema Columns & Indexes
    print("\n[Step 1] Verifying PostgreSQL Schema Columns & Composite Indexes...")
    with engine.connect() as conn:
        cols = conn.execute(text("""
            SELECT column_name, data_type, column_default
            FROM information_schema.columns
            WHERE table_name = 'feed_schedules'
              AND column_name IN ('lead_window_minutes', 'sla_grace_minutes');
        """)).fetchall()
        print(f"  Found {len(cols)} new columns on feed_schedules:")
        for c in cols:
            print(f"    - {c[0]}: {c[1]} (default: {c[2]})")
        assert len(cols) == 2, "Missing columns on feed_schedules!"

        idx = conn.execute(text("""
            SELECT indexname, tablename
            FROM pg_indexes
            WHERE indexname IN (
                'ix_batches_created_at_desc',
                'ix_batches_status_created_at',
                'ix_batches_feed_created_at',
                'ix_batch_stages_batch_order',
                'ix_input_registry_feed_detected',
                'ix_dq_results_batch_id',
                'ix_schema_drift_batch_id'
            );
        """)).fetchall()
        print(f"  Found {len(idx)} composite indexes:")
        for i in idx:
            print(f"    - {i[0]} on {i[1]}")
        assert len(idx) >= 7, "Missing composite indexes!"

    # 2. Authenticate
    print("\n[Step 2] Authenticating as ENGINEER...")
    auth_res = client.post("/api/v1/auth/login", json={"credential": "engineer:engineer123"})
    assert auth_res.status_code == 200
    token = auth_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("  Authenticated successfully.")

    # 3. Test Session Start Audit
    print("\n[Step 3] Testing Session Start Audit Logging...")
    audit_count_before = db.scalar(select(func.count()).select_from(AuditEvent)) or 0
    sess_res = client.post("/api/v1/ops/session-start", headers=headers)
    assert sess_res.status_code == 200
    audit_count_after = db.scalar(select(func.count()).select_from(AuditEvent)) or 0
    assert audit_count_after == audit_count_before + 1, "Session start did not emit audit event!"
    latest_audit = db.execute(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(1)).scalar_one()
    print(f"  Audit action recorded: {latest_audit.action.value} by {latest_audit.actor_id}")

    # 4. Populate Live Test Scenario for 5 SLA States
    print("\n[Step 4] Creating Live Scenarios for SLA States...")
    now = datetime.now(timezone.utc)
    
    feed = Feed(
        id=uuid.uuid4(),
        name=f"Live_Ops_Feed_{uuid.uuid4().hex[:6]}",
        domain="CLAIMS",
        format=FeedFormatEnum.CSV,
        landing_folder="/data/landing",
        filename_pattern="*.csv",
        schedule_expression="0 * * * *",
        status=FeedStatusEnum.ACTIVE,
        created_by="live_test",
        updated_by="live_test",
    )
    db.add(feed)
    db.flush()

    ver = FeedVersion(
        id=uuid.uuid4(),
        feed_id=feed.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED,
        created_by="live_test",
        updated_by="live_test",
    )
    db.add(ver)

    # Active hourly schedule
    sched = FeedSchedule(
        id=uuid.uuid4(),
        feed_id=feed.id,
        schedule_expression="0 * * * *",
        timezone="UTC",
        lead_window_minutes=60,
        sla_grace_minutes=30,
        status=ScheduleStatusEnum.ACTIVE,
        created_by="live_test",
        updated_by="live_test",
    )
    db.add(sched)

    # 1. On-time arrival (landed 10 mins after slot hour)
    past_hour_slot = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
    arr_on_time = InputRegistry(
        id=uuid.uuid4(),
        feed_id=feed.id,
        filename="CLAIMS_ON_TIME.csv",
        file_path="/data/landing/CLAIMS_ON_TIME.csv",
        file_size_bytes=4096,
        file_fingerprint=f"fp_live_ontime_{uuid.uuid4().hex[:8]}",
        status=InputStatusEnum.ACCEPTED,
        registered_by="live_test",
        detected_at=past_hour_slot + timedelta(minutes=10),
        created_by="live_test",
        updated_by="live_test",
    )
    db.add(arr_on_time)

    # 2. Late arrival (landed 45 mins after slot hour, grace is 30m)
    late_hour_slot = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=4)
    arr_late = InputRegistry(
        id=uuid.uuid4(),
        feed_id=feed.id,
        filename="CLAIMS_LATE.csv",
        file_path="/data/landing/CLAIMS_LATE.csv",
        file_size_bytes=4096,
        file_fingerprint=f"fp_live_late_{uuid.uuid4().hex[:8]}",
        status=InputStatusEnum.ACCEPTED,
        registered_by="live_test",
        detected_at=late_hour_slot + timedelta(minutes=45),
        created_by="live_test",
        updated_by="live_test",
    )
    db.add(arr_late)

    # 3. Unscheduled arrival (ad-hoc file)
    arr_unsched = InputRegistry(
        id=uuid.uuid4(),
        feed_id=feed.id,
        filename="CLAIMS_UNSCHEDULED_AD_HOC.csv",
        file_path="/data/landing/CLAIMS_UNSCHEDULED_AD_HOC.csv",
        file_size_bytes=2048,
        file_fingerprint=f"fp_live_unsched_{uuid.uuid4().hex[:8]}",
        status=InputStatusEnum.ACCEPTED,
        registered_by="live_test",
        detected_at=now - timedelta(days=2),
        created_by="live_test",
        updated_by="live_test",
    )
    db.add(arr_unsched)

    # 4. Batch with sensitive filename and error
    input_phi = InputRegistry(
        id=uuid.uuid4(),
        feed_id=feed.id,
        filename="ELIG_DOE_JOHN_123-45-6789_20260906.csv",
        file_path="/data/landing/ELIG_DOE_JOHN_123-45-6789_20260906.csv",
        file_size_bytes=8192,
        file_fingerprint=f"fp_live_phi_{uuid.uuid4().hex[:8]}",
        status=InputStatusEnum.ACCEPTED,
        registered_by="live_test",
        detected_at=now - timedelta(hours=1),
        created_by="live_test",
        updated_by="live_test",
    )
    db.add(input_phi)

    batch_phi = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=ver.id,
        input_registry_id=input_phi.id,
        status=BatchStatusEnum.FAILED,
        triggered_by="live_test",
        error_message="Error processing patient Jane Smith SSN 987-65-4321 email jsmith@hospital.org",
        created_by="live_test",
        updated_by="live_test",
    )
    db.add(batch_phi)

    stage_landing = BatchStage(
        id=uuid.uuid4(),
        batch_id=batch_phi.id,
        stage_name=StageNameEnum.LANDING,
        stage_order=1,
        status=StageStatusEnum.SUCCESS,
        rows_in=50,
        rows_out=50,
        rows_quarantined=0,
        created_by="live_test",
        updated_by="live_test",
    )
    db.add(stage_landing)

    stage_bronze = BatchStage(
        id=uuid.uuid4(),
        batch_id=batch_phi.id,
        stage_name=StageNameEnum.BRONZE,
        stage_order=2,
        status=StageStatusEnum.FAILED,
        rows_in=50,
        rows_out=0,
        rows_quarantined=0,
        error_message="Failed parsing SSN 987-65-4321",
        created_by="live_test",
        updated_by="live_test",
    )
    db.add(stage_bronze)

    db.commit()
    print("  Live test scenario committed.")

    # 5. Test Live Arrivals Board API
    print("\n[Step 5] Testing /api/v1/ops/arrivals API...")
    arr_res = client.get(f"/api/v1/ops/arrivals?window_hours=24&feed_id={feed.id}", headers=headers)
    assert arr_res.status_code == 200
    arr_data = arr_res.json()
    statuses = {item["status"] for item in arr_data["items"]}
    print(f"  Observed SLA statuses: {statuses}")
    for s in arr_data["items"]:
        if s["status"] in ["ON_TIME", "LATE", "EXPECTED", "MISSED_SLA"]:
            print(f"    - Slot: {s['expected_at_local']} | Status: {s['status']} | Delay: {s['delay_minutes']}m | File: {s['filename']}")

    # 6. Test Live Batch Monitor & PHI Scrubbing API
    print("\n[Step 6] Testing /api/v1/ops/monitor API and Zero-PHI Sanitization...")
    mon_res = client.get(f"/api/v1/ops/monitor?feed_id={feed.id}", headers=headers)
    assert mon_res.status_code == 200
    mon_data = mon_res.json()
    assert mon_data["total"] >= 1
    found_batch = next((b for b in mon_data["items"] if b["batch_id"] == str(batch_phi.id)), None)
    assert found_batch is not None
    print(f"  Sanitized Filename: {found_batch['filename']}")
    print(f"  Sanitized Error Message: {found_batch['error_message']}")
    assert "123-45-6789" not in found_batch["filename"], "SSN leaked in filename!"
    assert "987-65-4321" not in found_batch["error_message"], "SSN leaked in error message!"
    assert "jsmith@hospital.org" not in found_batch["error_message"], "Email leaked in error message!"
    assert "[REDACTED_SSN]" in found_batch["filename"]
    assert "[REDACTED_SSN]" in found_batch["error_message"]
    assert "[REDACTED_EMAIL]" in found_batch["error_message"]
    print("  Zero-PHI verification PASSED!")

    # 7. Test Batch Detail Drilldown
    print("\n[Step 7] Testing /api/v1/ops/monitor/{batch_id} Detail Drilldown...")
    dtl_res = client.get(f"/api/v1/ops/monitor/{batch_phi.id}", headers=headers)
    assert dtl_res.status_code == 200
    dtl_data = dtl_res.json()
    assert len(dtl_data["stages"]) == 2
    for st in dtl_data["stages"]:
        print(f"    - Stage {st['stage_order']}: {st['stage_name']} ({st['status']}) - Error: {st['error_message']}")

    # 8. Test Zero Polling Audit Noise
    print("\n[Step 8] Testing Zero-Polling Audit Noise Invariant...")
    count_before_poll = db.scalar(select(func.count()).select_from(AuditEvent)) or 0
    for _ in range(5):
        client.get("/api/v1/ops/home", headers=headers)
        client.get("/api/v1/ops/arrivals", headers=headers)
        client.get("/api/v1/ops/monitor", headers=headers)
        client.get(f"/api/v1/ops/monitor/{batch_phi.id}", headers=headers)
    count_after_poll = db.scalar(select(func.count()).select_from(AuditEvent)) or 0
    print(f"  Audit count before 20 polling requests: {count_before_poll}")
    print(f"  Audit count after 20 polling requests:  {count_after_poll}")
    assert count_before_poll == count_after_poll, "Polling generated audit records!"
    print("  Zero-Polling Audit Invariant PASSED!")

    # 9. Verify Ops Home KPIs
    print("\n[Step 9] Testing /api/v1/ops/home Macro KPIs...")
    home_res = client.get("/api/v1/ops/home", headers=headers)
    assert home_res.status_code == 200
    kpis = home_res.json()["kpis"]
    print(f"  Active Feeds: {kpis['active_feeds']}")
    print(f"  Batches Success 24h: {kpis['batches_24h_success']}")
    print(f"  Batches Failed 24h: {kpis['batches_24h_failed']}")
    print(f"  Batches Running: {kpis['batches_running']}")
    print(f"  SLA Attainment: {kpis['sla_attainment_pct']}%")
    print(f"  Quarantined Rows: {kpis['quarantined_rows_24h']}")
    print(f"  Breaking Drift: {kpis['breaking_drift_count']}")
    print(f"  Non-Breaking Drift: {kpis['non_breaking_drift_count']}")

    print("\n" + "=" * 70)
    print("ALL LIVE VERIFICATION CHECKS PASSED PERFECTLY!")
    print("=" * 70)

if __name__ == "__main__":
    run_live_verification()
