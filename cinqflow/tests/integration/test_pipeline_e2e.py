"""
End-to-End Pipeline Integration Tests — Wave 0

Covers Phases 7 through 14:
- Real local execution of Landing -> Bronze -> Silver Raw -> Reconciliation
- Deterministic demo feed: 4 rows input -> 3 Silver Raw rows + 1 Quarantined row
- Verification of Bronze bit-for-bit immutability
- Verification of Quarantine record details and named reasons
- Verification of Reconciliation balance: 4 in = 3 silver + 1 quarantine (PASS)
- Verification of Idempotency: duplicate submission skipped
- Verification of Failure & Restart:
    Simulate Silver Raw failure -> restart -> Landing and Bronze NOT rerun -> Silver Raw succeeds
- Verification of immutable Audit trail
"""
import io
import pytest
from backend.models.feed import Feed, FeedVersion, FeedFormatEnum, FeedStatusEnum, FeedVersionStatusEnum
from backend.models.pipeline import Batch, BatchStage, BatchStatusEnum, StageNameEnum, StageStatusEnum
from backend.models.input_registry import InputRegistry, QuarantineRecord, QuarantineReasonEnum
from backend.models.reconciliation import BatchReconciliation, ReconciliationStatusEnum
from backend.models.audit import AuditEvent, AuditActionEnum
from backend.adapters.storage import get_storage_adapter


@pytest.fixture
def demo_feed(db):
    """
    Setup the deterministic demo feed with published schema:
    member_id (STRING, required)
    first_name (STRING, required)
    last_name (STRING, required)
    date_of_birth (DATE, required)
    gender (ENUM: M/F/U)
    """
    feed = Feed(
        name="DEMO_E2E_MEMBER_FEED",
        domain="MEMBERSHIP",
        description="Demo feed for Wave 0 acceptance verification",
        format=FeedFormatEnum.CSV,
        landing_folder="./data/landing/demo",
        filename_pattern="MEMBER_*.csv",
        schedule_expression="manual",
        status=FeedStatusEnum.ACTIVE,
        created_by="system",
        updated_by="system",
    )
    db.add(feed)
    db.flush()

    version = FeedVersion(
        feed_id=feed.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED,
        config_snapshot={
            "fields": [
                {"name": "member_id", "type": "STRING", "required": True},
                {"name": "first_name", "type": "STRING", "required": True},
                {"name": "last_name", "type": "STRING", "required": True},
                {"name": "date_of_birth", "type": "DATE", "required": True},
                {"name": "gender", "type": "ENUM", "allowed_values": ["M", "F", "U"], "required": False},
            ],
            "delimiter": ",",
            "has_header": True,
        },
        change_notes="Wave 0 demo schema",
        published_by="mock-engineer-001",
        created_by="system",
        updated_by="system",
    )
    db.add(version)
    db.commit()
    db.refresh(feed)
    return feed


# Deterministic 4-row demo CSV:
# 3 valid records + 1 invalid record (M004 has empty last_name, future DOB 2099-01-01, invalid gender 'X')
DEMO_CSV_BYTES = (
    "member_id,first_name,last_name,date_of_birth,gender\n"
    "M001,Alice,Johnson,1985-06-15,F\n"
    "M002,Bob,Smith,1990-03-22,M\n"
    "M003,Carol,Williams,1978-11-08,F\n"
    "M004,David,,2099-01-01,X\n"
).encode("utf-8")


def test_full_pipeline_end_to_end(client, engineer_headers, demo_feed, db):
    """
    PHASE 7, 8, 9, 10, 11, 14 Acceptance Verification:
    Executes Landing -> Bronze -> Silver Raw -> Reconciliation.
    Proves:
      Input rows = 4
      Silver Raw rows = 3
      Quarantined rows = 1
      Reconciliation: PASS (4 = 3 + 1)
    """
    storage = get_storage_adapter()

    # 1. Register File Arrival
    files = {"file": ("MEMBER_DEMO_001.csv", io.BytesIO(DEMO_CSV_BYTES), "text/csv")}
    res_reg = client.post("/api/v1/inputs/register", files=files, headers=engineer_headers)
    assert res_reg.status_code == 200
    reg_data = res_reg.json()
    assert reg_data["status"] == "ACCEPTED"
    batch_id = reg_data["batch"]["id"]

    # 2. Execute Batch
    res_exec = client.post(f"/api/v1/pipeline/batches/{batch_id}/execute", headers=engineer_headers)
    assert res_exec.status_code == 200
    batch_data = res_exec.json()
    assert batch_data["status"] == "SUCCESS"

    # 3. Verify Stage Execution Records
    res_stages = client.get(f"/api/v1/pipeline/batches/{batch_id}/stages", headers=engineer_headers)
    stages = res_stages.json()
    assert len(stages) == 3
    s_landing = next(s for s in stages if s["stage_name"] == "LANDING")
    s_bronze = next(s for s in stages if s["stage_name"] == "BRONZE")
    s_silver = next(s for s in stages if s["stage_name"] == "SILVER_RAW")

    assert s_landing["status"] == "SUCCESS"
    assert s_landing["rows_in"] == 4

    # 4. Phase 8: Verify Bronze Immutability
    assert s_bronze["status"] == "SUCCESS"
    assert s_bronze["rows_in"] == 4
    bronze_content = storage.read_file(s_bronze["output_path"])
    # Exact bit-for-bit match
    assert bronze_content == DEMO_CSV_BYTES

    # 5. Phase 9: Verify Silver Raw Transformation
    assert s_silver["status"] == "SUCCESS"
    assert s_silver["rows_in"] == 4
    assert s_silver["rows_out"] == 3
    assert s_silver["rows_quarantined"] == 1

    silver_csv = storage.read_file(s_silver["output_path"]).decode("utf-8")
    assert "M001" in silver_csv
    assert "M002" in silver_csv
    assert "M003" in silver_csv
    # Invalid record must NOT be in Silver Raw
    assert "M004" not in silver_csv

    # 6. Phase 10: Verify Quarantine Record
    res_q = client.get(f"/api/v1/quarantine?batch_id={batch_id}", headers=engineer_headers)
    q_records = res_q.json()
    assert len(q_records) == 1
    qr = q_records[0]
    assert qr["stage_name"] == "SILVER_RAW"
    assert qr["source_row_number"] == 4
    assert "M004,David,,2099-01-01,X" in qr["source_record_raw"]
    # Named failure reason
    assert qr["reason"] in ["MISSING_REQUIRED_FIELD", "FUTURE_DATE", "INVALID_ENUM_VALUE"]

    # 7. Phase 11: Verify Reconciliation Math
    res_recon = client.get(f"/api/v1/reconciliation/batches/{batch_id}", headers=engineer_headers)
    assert res_recon.status_code == 200
    recon = res_recon.json()
    assert recon["rows_in"] == 4
    assert recon["rows_silver_raw"] == 3
    assert recon["rows_quarantined"] == 1
    assert recon["rows_dropped"] == 0
    assert recon["balance_check_passed"] is True
    assert recon["status"] == "PASS"
    assert recon["discrepancy"] == 0

    # Verify Reconciliation Ledger
    res_ledger = client.get(f"/api/v1/reconciliation/batches/{batch_id}/ledger", headers=engineer_headers)
    ledger = res_ledger.json()
    assert len(ledger) >= 1
    assert sum(item["row_count"] for item in ledger) == 1

    # 8. Phase 14: Verify Audit Trail
    res_audit = client.get("/api/v1/audit/events", headers=engineer_headers)
    assert res_audit.status_code == 200
    actions = [e["action"] for e in res_audit.json()]
    assert "input.registered" in actions
    assert "batch.started" in actions
    assert "stage.completed" in actions
    assert "quarantine.record_added" in actions
    assert "reconciliation.computed" in actions
    assert "batch.completed" in actions


def test_idempotency_same_file_submitted_twice(client, engineer_headers, demo_feed):
    """
    PHASE 12 Acceptance Verification:
    Repeated submission of the same input fingerprint must not create
    duplicate processing or duplicate batches.
    """
    files1 = {"file": ("MEMBER_DEMO_FIRST.csv", io.BytesIO(DEMO_CSV_BYTES), "text/csv")}
    res1 = client.post("/api/v1/inputs/register", files=files1, headers=engineer_headers)
    assert res1.status_code == 200
    assert res1.json()["is_duplicate"] is False

    # Second submission
    files2 = {"file": ("MEMBER_DEMO_SECOND.csv", io.BytesIO(DEMO_CSV_BYTES), "text/csv")}
    res2 = client.post("/api/v1/inputs/register", files=files2, headers=engineer_headers)
    assert res2.status_code == 200
    assert res2.json()["is_duplicate"] is True
    assert res2.json()["file_fingerprint"] == res1.json()["file_fingerprint"]


def test_failure_and_stage_restart(client, engineer_headers, demo_feed, db):
    """
    PHASE 13 Acceptance Verification:
    Simulate failure at Silver Raw:
      Landing: SUCCESS
      Bronze: SUCCESS
      Silver Raw: FAILED
    Restart the batch:
      Landing: NOT rerun
      Bronze: NOT rerun
      Silver Raw: reruns -> SUCCESS
    Batch completes with SUCCESS.
    """
    # Use distinct CSV content so it isn't rejected as a duplicate
    unique_csv = (
        "member_id,first_name,last_name,date_of_birth,gender\n"
        "M901,Restart,Tester,1980-05-20,M\n"
    ).encode("utf-8")

    files = {"file": ("MEMBER_RESTART_TEST.csv", io.BytesIO(unique_csv), "text/csv")}
    res_reg = client.post("/api/v1/inputs/register", files=files, headers=engineer_headers)
    batch_id = res_reg.json()["batch"]["id"]

    # 1. Execute with simulated failure at Silver Raw
    from backend.engine.executor import PipelineExecutor
    executor = PipelineExecutor(db)
    batch_failed = executor.execute_batch(
        batch_id=batch_id,
        actor_id="mock-engineer-001",
        simulate_failure_stage=StageNameEnum.SILVER_RAW,
    )
    assert batch_failed.status == BatchStatusEnum.FAILED

    # Check stage statuses
    s_landing = batch_failed.get_stage(StageNameEnum.LANDING)
    s_bronze = batch_failed.get_stage(StageNameEnum.BRONZE)
    s_silver = batch_failed.get_stage(StageNameEnum.SILVER_RAW)

    assert s_landing.status == StageStatusEnum.SUCCESS
    assert s_bronze.status == StageStatusEnum.SUCCESS
    assert s_silver.status == StageStatusEnum.FAILED

    # Save original completion timestamps of completed stages
    landing_completed_at = s_landing.completed_at
    bronze_completed_at = s_bronze.completed_at

    # 2. Restart the batch via API
    res_restart = client.post(f"/api/v1/pipeline/batches/{batch_id}/restart", headers=engineer_headers)
    assert res_restart.status_code == 200
    batch_restarted = res_restart.json()
    assert batch_restarted["status"] == "SUCCESS"
    assert batch_restarted["restart_count"] == 1

    # 3. Verify earlier completed stages were NOT rerun (timestamps untouched)
    db.refresh(s_landing)
    db.refresh(s_bronze)
    db.refresh(s_silver)

    assert s_landing.status == StageStatusEnum.SUCCESS
    assert s_landing.completed_at == landing_completed_at
    assert s_bronze.status == StageStatusEnum.SUCCESS
    assert s_bronze.completed_at == bronze_completed_at
    assert s_silver.status == StageStatusEnum.SUCCESS
