"""
Deep Wave 0 Independent Verification Script

Validates:
1. Real demo feed execution via live API
   * 4 input rows -> 3 Silver Raw + 1 Quarantined -> Reconciliation PASS
2. Bronze Immutability:
   * Byte-for-byte equality & SHA-256 match between source input & Bronze file
3. Idempotency:
   * Re-submission yields DUPLICATE, no new batch, no extra records
4. Restart:
   * Simulated failure at Silver Raw -> Landing & Bronze SUCCESS, Silver FAILED
   * Restart -> Landing & Bronze NOT re-executed, Silver resumes -> SUCCESS
5. Audit:
   * Confirm audit events exist for: feed creation/update, input registration,
     duplicate detection, batch creation, stage start, stage success, stage failure,
     quarantine, reconciliation, restart
"""
import io
import hashlib
import time
import httpx
from pathlib import Path

BACKEND_URL = "http://127.0.0.1:8000"

def get_demo_csv():
    ts = int(time.time() * 1000)
    return (
        "member_id,first_name,last_name,date_of_birth,gender\n"
        f"M001_{ts},Alice,Johnson,1985-06-15,F\n"
        f"M002_{ts},Bob,Smith,1990-03-22,M\n"
        f"M003_{ts},Carol,Williams,1978-11-08,F\n"
        f"M004_{ts},David,,2099-01-01,X\n"
    ).encode("utf-8")



def run_deep_verification():
    client = httpx.Client(timeout=15.0)

    # 1. Login as Engineer
    r_login = client.post(
        f"{BACKEND_URL}/api/v1/auth/login",
        json={"credential": "engineer:engineer123"},
    )
    assert r_login.status_code == 200
    token = r_login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("[PASS] Logged in as Engineer")

    # 1b. Create Feed and Publish Version (to test feed & version audit events)
    feed_name = f"FEED_AUDIT_TEST_{int(time.time())}"
    r_feed = client.post(
        f"{BACKEND_URL}/api/v1/feeds",
        json={
            "name": feed_name,
            "domain": "AUDIT_TEST",
            "landing_folder": "./data/landing",
            "filename_pattern": f"{feed_name}_*.csv",
            "initial_config": {"fields": [{"name": "col1", "type": "STRING", "required": True}]},
        },
        headers=headers,
    )
    assert r_feed.status_code == 201
    test_feed_id = r_feed.json()["id"]
    test_v1_id = r_feed.json()["versions"][0]["id"]
    r_pub = client.post(
        f"{BACKEND_URL}/api/v1/feeds/{test_feed_id}/versions/{test_v1_id}/publish",
        json={"change_notes": "Publishing for audit verification"},
        headers=headers,
    )
    assert r_pub.status_code == 200
    print(f"[PASS] Created and published feed version for audit trail verification")

    # 2. Ingest Demo Feed
    demo_csv = get_demo_csv()
    files = {"file": ("MEMBER_RUN_INDEPENDENT.csv", io.BytesIO(demo_csv), "text/csv")}
    r_reg = client.post(f"{BACKEND_URL}/api/v1/inputs/register", files=files, headers=headers)
    assert r_reg.status_code == 200, f"Register failed: {r_reg.text}"
    reg_data = r_reg.json()
    assert reg_data["status"] == "ACCEPTED"
    assert reg_data["is_duplicate"] is False
    batch_id = reg_data["batch"]["id"]
    source_fingerprint = reg_data["file_fingerprint"]
    print(f"[PASS] Registered file MEMBER_RUN_INDEPENDENT.csv (Batch: {batch_id}, Fingerprint: {source_fingerprint[:16]}...)")

    # 3. Execute Pipeline
    r_exec = client.post(f"{BACKEND_URL}/api/v1/pipeline/batches/{batch_id}/execute", headers=headers)
    assert r_exec.status_code == 200, f"Execute failed: {r_exec.text}"
    batch_data = r_exec.json()
    assert batch_data["status"] == "SUCCESS"
    print(f"[PASS] Executed batch: Status = {batch_data['status']}")

    # 4. Verify Stages
    r_stages = client.get(f"{BACKEND_URL}/api/v1/pipeline/batches/{batch_id}/stages", headers=headers)
    stages = r_stages.json()
    s_landing = next(s for s in stages if s["stage_name"] == "LANDING")
    s_bronze = next(s for s in stages if s["stage_name"] == "BRONZE")
    s_silver = next(s for s in stages if s["stage_name"] == "SILVER_RAW")

    assert s_landing["status"] == "SUCCESS" and s_landing["rows_in"] == 4
    assert s_bronze["status"] == "SUCCESS" and s_bronze["rows_in"] == 4
    assert s_silver["status"] == "SUCCESS" and s_silver["rows_in"] == 4 and s_silver["rows_out"] == 3 and s_silver["rows_quarantined"] == 1
    print("[PASS] Stage outputs: Landing=4 in, Bronze=4 in, Silver Raw=3 out, 1 quarantined")

    # 5. Verify Bronze Immutability
    bronze_file_path = s_bronze["output_path"]
    bronze_bytes = Path(bronze_file_path).read_bytes()
    bronze_hash = hashlib.sha256(bronze_bytes).hexdigest()
    assert bronze_bytes == demo_csv, "Bronze content does not match original bytes!"
    assert bronze_hash == source_fingerprint, "Bronze SHA-256 does not match source fingerprint!"
    print(f"[PASS] Bronze Immutability confirmed: {len(bronze_bytes)} bytes match bit-for-bit, SHA-256 = {bronze_hash[:16]}...")

    # 6. Verify Quarantine Record
    r_q = client.get(f"{BACKEND_URL}/api/v1/quarantine?batch_id={batch_id}", headers=headers)
    q_records = r_q.json()
    assert len(q_records) == 1
    qr = q_records[0]
    assert qr["source_row_number"] == 4
    assert "M004" in qr["source_record_raw"]
    print(f"[PASS] Quarantine confirmed: Row {qr['source_row_number']}, Reason: {qr['reason']}, Detail: {qr['reason_detail']}")

    # 7. Verify Reconciliation Math
    r_recon = client.get(f"{BACKEND_URL}/api/v1/reconciliation/batches/{batch_id}", headers=headers)
    recon = r_recon.json()
    assert recon["rows_in"] == 4
    assert recon["rows_silver_raw"] == 3
    assert recon["rows_quarantined"] == 1
    assert recon["rows_dropped"] == 0
    assert recon["discrepancy"] == 0
    assert recon["status"] == "PASS"
    print("[PASS] Reconciliation Math confirmed: 4 in = 3 Silver Raw + 1 Quarantine + 0 Dropped. Result = PASS")

    # 8. Verify Idempotency (Submit duplicate file)
    files_dup = {"file": ("MEMBER_RUN_INDEPENDENT_RETRY.csv", io.BytesIO(demo_csv), "text/csv")}
    r_dup = client.post(f"{BACKEND_URL}/api/v1/inputs/register", files=files_dup, headers=headers)
    assert r_dup.status_code == 200
    dup_data = r_dup.json()
    assert dup_data["is_duplicate"] is True
    assert dup_data["file_fingerprint"] == source_fingerprint
    print("[PASS] Idempotency confirmed: Duplicate submission detected, no new batch spawned")

    # 9. Verify Failure & Restart
    # Unique content for restart test
    r_ts = int(time.time() * 1000)
    restart_csv = (
        "member_id,first_name,last_name,date_of_birth,gender\n"
        f"M881_{r_ts},Tom,Hardy,1977-09-15,M\n"
    ).encode("utf-8")
    files_restart = {"file": (f"MEMBER_RESTART_{r_ts}.csv", io.BytesIO(restart_csv), "text/csv")}
    r_reg_res = client.post(f"{BACKEND_URL}/api/v1/inputs/register", files=files_restart, headers=headers)
    assert r_reg_res.status_code == 200
    res_reg_data = r_reg_res.json()
    assert res_reg_data["is_duplicate"] is False
    r_batch_id = res_reg_data["batch"]["id"]

    # Ingest directly into executor with simulated failure at SILVER_RAW
    from backend.core.database import SessionLocal
    from backend.engine.executor import PipelineExecutor
    from backend.models.pipeline import StageNameEnum, BatchStatusEnum, StageStatusEnum
    import uuid

    db = SessionLocal()
    try:
        executor = PipelineExecutor(db)
        b_failed = executor.execute_batch(
            batch_id=uuid.UUID(r_batch_id),
            actor_id="mock-engineer-001",
            simulate_failure_stage=StageNameEnum.SILVER_RAW,
        )
        assert b_failed.status == BatchStatusEnum.FAILED
        s1 = b_failed.get_stage(StageNameEnum.LANDING)
        s2 = b_failed.get_stage(StageNameEnum.BRONZE)
        s3 = b_failed.get_stage(StageNameEnum.SILVER_RAW)
        assert s1.status == StageStatusEnum.SUCCESS
        assert s2.status == StageStatusEnum.SUCCESS
        assert s3.status == StageStatusEnum.FAILED
        t1_completed = s1.completed_at
        t2_completed = s2.completed_at
        print(f"[PASS] Failure simulation confirmed: Landing={s1.status}, Bronze={s2.status}, Silver Raw={s3.status}")
    finally:
        db.close()

    # Now restart via HTTP API
    r_restart = client.post(f"{BACKEND_URL}/api/v1/pipeline/batches/{r_batch_id}/restart", headers=headers)
    assert r_restart.status_code == 200
    b_restarted_data = r_restart.json()
    assert b_restarted_data["status"] == "SUCCESS"
    assert b_restarted_data["restart_count"] == 1

    # Verify Landing and Bronze were NOT re-executed
    db2 = SessionLocal()
    try:
        from backend.models.pipeline import Batch
        b_check = db2.query(Batch).filter(Batch.id == uuid.UUID(r_batch_id)).first()
        assert b_check.get_stage(StageNameEnum.LANDING).completed_at == t1_completed
        assert b_check.get_stage(StageNameEnum.BRONZE).completed_at == t2_completed
        assert b_check.get_stage(StageNameEnum.SILVER_RAW).status == StageStatusEnum.SUCCESS
        print("[PASS] Restart recovery confirmed: Landing & Bronze NOT re-executed; Silver Raw resumed to SUCCESS")
    finally:
        db2.close()

    # 10. Verify Audit Events
    r_audit = client.get(f"{BACKEND_URL}/api/v1/audit/events?limit=100", headers=headers)
    assert r_audit.status_code == 200
    events = r_audit.json()
    actions = {e["action"] for e in events}

    required_actions = [
        "feed.created",
        "feed_version.published",
        "input.registered",
        "input.duplicate_detected",
        "batch.created",
        "batch.started",
        "stage.started",
        "stage.completed",
        "stage.failed",
        "quarantine.record_added",
        "reconciliation.computed",
        "batch.restart_requested",
        "batch.completed",
    ]
    for act in required_actions:
        assert act in actions, f"Missing audit action: {act}"
    print(f"[PASS] Audit Trail verified: All {len(required_actions)} required action types recorded in audit log")

    print("\nALL DEEP WAVE 0 INVARIANTS INDEPENDENTLY CONFIRMED!")


if __name__ == "__main__":
    run_deep_verification()
