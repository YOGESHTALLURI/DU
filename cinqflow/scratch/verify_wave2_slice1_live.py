"""
Comprehensive Live Verification Script for Wave 2 Slice 1:
- CF-V2-E5-04: Schema Drift Detection
- CF-V2-E7-05: Rules Running in Production
"""
import os
import sys
import uuid
import json
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

sys.path.insert(0, r"d:\Digitalurth\cinqflow")

from backend.core.database import engine, SessionLocal
from backend.main import app
from backend.models.user import User, RoleEnum
from backend.models.feed import Feed, FeedFormatEnum, FeedStatusEnum, FeedVersion, FeedVersionStatusEnum
from backend.models.pipeline import Batch, BatchStage, BatchStatusEnum, StageNameEnum, StageStatusEnum
from backend.models.input_registry import InputRegistry, QuarantineRecord
from backend.models.reconciliation import BatchReconciliation
from backend.models.schema import (
    Schema,
    SchemaVersion,
    SchemaField,
    SchemaDataTypeEnum,
    SchemaVersionStatusEnum,
)
from backend.models.rule import (
    DataQualityRule,
    RuleVersion,
    RuleVersionStatusEnum,
    RuleTypeEnum,
    RuleSeverityEnum,
)
from backend.models.drift import SchemaDriftReport, DriftSeverityEnum, DriftStatusEnum
from backend.models.dq_result import DQResult, DQActionTakenEnum
from backend.models.audit import AuditEvent, AuditActionEnum
from backend.engine.executor import PipelineExecutor
from backend.adapters.storage import get_storage_adapter


def run_live_verification():
    print("================================================================================")
    print("CINQFLOW WAVE 2 SLICE 1 — INDEPENDENT LIVE VERIFICATION")
    print("================================================================================")

    db = SessionLocal()
    client = TestClient(app)
    storage = get_storage_adapter()

    # Step 0: Auth Tokens
    engineer_res = client.post("/api/v1/auth/login", json={"credential": "engineer:engineer123"})
    assert engineer_res.status_code == 200
    eng_token = engineer_res.json()["access_token"]
    eng_headers = {"Authorization": f"Bearer {eng_token}"}

    analyst_res = client.post("/api/v1/auth/login", json={"credential": "analyst:analyst123"})
    assert analyst_res.status_code == 200
    ana_token = analyst_res.json()["access_token"]
    ana_headers = {"Authorization": f"Bearer {ana_token}"}

    readonly_res = client.post("/api/v1/auth/login", json={"credential": "readonly:readonly123"})
    ro_token = readonly_res.json()["access_token"]
    ro_headers = {"Authorization": f"Bearer {ro_token}"}

    print("[PASS] Authentication tokens acquired for ENGINEER, ANALYST, and READ_ONLY.")

    # 1. Database Schema & Migration Verification
    print("\n--- 1. DATABASE SCHEMA & ENUMS INSPECTION ---")
    with engine.connect() as conn:
        tables = conn.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('schema_drift_reports', 'dq_results')"
        )).fetchall()
        table_names = [t[0] for t in tables]
        assert "schema_drift_reports" in table_names
        assert "dq_results" in table_names
        print(f"Verified PostgreSQL tables exist: {table_names}")

        # Check enums
        drift_sev = conn.execute(text("SELECT enumlabel FROM pg_enum JOIN pg_type ON pg_enum.enumtypid = pg_type.oid WHERE typname = 'drift_severity_enum'")).fetchall()
        print(f"drift_severity_enum values: {[r[0] for r in drift_sev]}")

        dq_actions = conn.execute(text("SELECT enumlabel FROM pg_enum JOIN pg_type ON pg_enum.enumtypid = pg_type.oid WHERE typname = 'dq_action_taken_enum'")).fetchall()
        print(f"dq_action_taken_enum values: {[r[0] for r in dq_actions]}")

        audit_actions = conn.execute(text("SELECT enumlabel FROM pg_enum JOIN pg_type ON pg_enum.enumtypid = pg_type.oid WHERE typname = 'audit_action_enum' AND enumlabel LIKE '%DRIFT%' OR enumlabel LIKE '%RULE%'")).fetchall()
        print(f"New audit action enum values: {[r[0] for r in audit_actions]}")

    # Setup Feed, FeedVersion, Schema, SchemaVersion
    prefix = uuid.uuid4().hex[:6]
    feed = Feed(
        id=uuid.uuid4(),
        name=f"LIVE_PROD_{prefix}",
        domain="MEMBERS",
        format=FeedFormatEnum.CSV,
        status=FeedStatusEnum.ACTIVE,
        landing_folder=f"./data/landing/live_{prefix}",
        filename_pattern="*.csv",
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(feed)
    db.flush()

    fv = FeedVersion(
        id=uuid.uuid4(),
        feed_id=feed.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED,
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(fv)
    db.flush()

    schema_obj = Schema(
        id=uuid.uuid4(),
        feed_id=feed.id,
        name=f"Live Schema {prefix}",
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(schema_obj)
    db.flush()

    sv = SchemaVersion(
        id=uuid.uuid4(),
        schema_id=schema_obj.id,
        version_number=1,
        status=SchemaVersionStatusEnum.PUBLISHED,
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(sv)
    db.flush()

    f_mid = SchemaField(
        id=uuid.uuid4(),
        schema_version_id=sv.id,
        field_name="member_id",
        data_type=SchemaDataTypeEnum.STRING,
        is_required=True,
        ordinal_position=1,
        created_by="engineer",
        updated_by="engineer",
    )
    f_fname = SchemaField(
        id=uuid.uuid4(),
        schema_version_id=sv.id,
        field_name="first_name",
        data_type=SchemaDataTypeEnum.STRING,
        is_required=True,
        ordinal_position=2,
        created_by="engineer",
        updated_by="engineer",
    )
    f_age = SchemaField(
        id=uuid.uuid4(),
        schema_version_id=sv.id,
        field_name="age",
        data_type=SchemaDataTypeEnum.INTEGER,
        is_required=False,
        ordinal_position=3,
        created_by="engineer",
        updated_by="engineer",
    )
    db.add_all([f_mid, f_fname, f_age])
    db.commit()

    print(f"\n[PASS] Seeded live feed '{feed.name}' with SchemaVersion 1 (fields: member_id [req], first_name [req], age [opt]).")

    def create_batch(csv_bytes: bytes, filename: str):
        import hashlib
        fp = hashlib.sha256(csv_bytes).hexdigest()
        file_path = f"./data/landing/{feed.id}/{filename}"
        storage.write_file(file_path, csv_bytes)

        input_reg = InputRegistry(
            id=uuid.uuid4(),
            feed_id=feed.id,
            filename=filename,
            file_path=file_path,
            file_size_bytes=len(csv_bytes),
            file_fingerprint=fp,
            registered_by="engineer",
            detected_at=datetime.now(timezone.utc),
            created_by="engineer",
            updated_by="engineer",
        )
        db.add(input_reg)
        db.flush()

        batch = Batch(
            id=uuid.uuid4(),
            feed_id=feed.id,
            feed_version_id=fv.id,
            input_registry_id=input_reg.id,
            status=BatchStatusEnum.PENDING,
            triggered_by="engineer",
            created_by="engineer",
            updated_by="engineer",
        )
        db.add(batch)
        db.commit()
        db.refresh(batch)
        return batch

    executor = PipelineExecutor(db)

    # 2. SCENARIO A: Breaking Schema Drift Execution & Halting
    print("\n--- 2. SCENARIO A: BREAKING SCHEMA DRIFT HALTS AT LANDING ---")
    # CSV missing required 'first_name' column
    breaking_csv = f"member_id,age\nM_{prefix}_901,42\nM_{prefix}_902,35\n".encode("utf-8")
    b_breaking = create_batch(breaking_csv, "live_breaking.csv")
    b_breaking = executor.execute_batch(batch_id=b_breaking.id, actor_id="engineer")

    assert b_breaking.status == BatchStatusEnum.FAILED
    assert b_breaking.get_stage(StageNameEnum.LANDING).status == StageStatusEnum.FAILED
    assert b_breaking.get_stage(StageNameEnum.BRONZE) is None or b_breaking.get_stage(StageNameEnum.BRONZE).status == StageStatusEnum.PENDING

    drift_report_breaking = db.query(SchemaDriftReport).filter(SchemaDriftReport.batch_id == b_breaking.id).first()
    assert drift_report_breaking is not None
    assert drift_report_breaking.drift_severity == DriftSeverityEnum.BREAKING
    assert "first_name" in drift_report_breaking.missing_fields

    print(f"Batch {b_breaking.id} status: {b_breaking.status.value}")
    print(f"Landing stage status: {b_breaking.get_stage(StageNameEnum.LANDING).status.value}")
    print(f"Drift report ID: {drift_report_breaking.id}, Severity: {drift_report_breaking.drift_severity.value}, Missing: {drift_report_breaking.missing_fields}")
    print("[PASS] Breaking drift successfully halted ingestion at LANDING stage with 0 Bronze writes.")

    # 3. SCENARIO B: Non-Breaking Drift Execution & Acknowledgment Flow
    print("\n--- 3. SCENARIO B: NON-BREAKING DRIFT & ACKNOWLEDGMENT FLOW ---")
    # CSV has unexpected extra column 'allergies'
    nonbreaking_csv = f"member_id,first_name,age,allergies\nM_{prefix}_801,Charlie,28,Peanuts\nM_{prefix}_802,Dana,33,None\n".encode("utf-8")
    b_nonbreaking = create_batch(nonbreaking_csv, "live_nonbreaking.csv")
    b_nonbreaking = executor.execute_batch(batch_id=b_nonbreaking.id, actor_id="engineer")

    assert b_nonbreaking.status == BatchStatusEnum.SUCCESS
    drift_report_nb = db.query(SchemaDriftReport).filter(SchemaDriftReport.batch_id == b_nonbreaking.id).first()
    assert drift_report_nb is not None
    assert drift_report_nb.drift_severity == DriftSeverityEnum.NON_BREAKING
    assert "allergies" in drift_report_nb.unexpected_fields
    print(f"Batch {b_nonbreaking.id} status: {b_nonbreaking.status.value}")
    print(f"Drift report ID: {drift_report_nb.id}, Severity: {drift_report_nb.drift_severity.value}, Unexpected: {drift_report_nb.unexpected_fields}")

    # Test RBAC on Acknowledge:
    # 3a. Readonly attempts acknowledge -> 403 Forbidden
    res_ro = client.post(f"/api/v1/schemas/drift/{drift_report_nb.id}/acknowledge", headers=ro_headers, json={"notes": "Readonly trying to acknowledge"})
    assert res_ro.status_code == 403
    print(f"Read-only acknowledge attempt returned HTTP {res_ro.status_code} (Expected 403)")

    # 3b. Analyst attempts acknowledge -> 403 Forbidden
    res_ana = client.post(f"/api/v1/schemas/drift/{drift_report_nb.id}/acknowledge", headers=ana_headers, json={"notes": "Analyst trying to acknowledge"})
    assert res_ana.status_code == 403
    print(f"Analyst acknowledge attempt returned HTTP {res_ana.status_code} (Expected 403)")

    # 3c. Engineer attempts acknowledge BREAKING drift -> 400 Bad Request
    res_brk = client.post(f"/api/v1/schemas/drift/{drift_report_breaking.id}/acknowledge", headers=eng_headers, json={"notes": "Trying to bypass breaking drift"})
    assert res_brk.status_code == 400
    print(f"Engineer acknowledge of BREAKING drift returned HTTP {res_brk.status_code} (Expected 400: {res_brk.json()['detail']})")

    # 3d. Engineer acknowledges NON_BREAKING drift with notes -> 200 OK
    res_eng = client.post(f"/api/v1/schemas/drift/{drift_report_nb.id}/acknowledge", headers=eng_headers, json={"notes": "Approved unexpected allergies column from upstream system."})
    assert res_eng.status_code == 200
    db.refresh(drift_report_nb)
    assert drift_report_nb.status == DriftStatusEnum.ACKNOWLEDGED
    assert "engineer" in drift_report_nb.acknowledged_by
    print(f"Engineer acknowledge of NON_BREAKING drift returned HTTP {res_eng.status_code}, Status: {drift_report_nb.status.value}")
    print("[PASS] Schema drift detection and governance acknowledgment lifecycle verified.")

    # 4. SCENARIO C: Production DQ Rules - QUARANTINE & Reconciliation Balance
    print("\n--- 4. SCENARIO C: PRODUCTION DQ RULES — QUARANTINE & RECONCILIATION ---")
    rule_quarantine = DataQualityRule(
        id=uuid.uuid4(),
        feed_id=feed.id,
        schema_id=schema_obj.id,
        name="max_age_cap_75",
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(rule_quarantine)
    db.flush()

    r_quarantine_v = RuleVersion(
        id=uuid.uuid4(),
        rule_id=rule_quarantine.id,
        version_number=1,
        schema_version_id=sv.id,
        status=RuleVersionStatusEnum.PUBLISHED,
        rule_type=RuleTypeEnum.RANGE,
        target_field="age",
        severity=RuleSeverityEnum.QUARANTINE,
        rule_config={"max": 75},
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(r_quarantine_v)
    db.commit()

    # 5 rows: 3 valid (age <= 75), 2 quarantined (age > 75)
    csv_quarantine = f"member_id,first_name,age\nM_{prefix}_01,Alice,25\nM_{prefix}_02,Bob,85\nM_{prefix}_03,Carol,40\nM_{prefix}_04,Dave,92\nM_{prefix}_05,Eve,60\n".encode("utf-8")
    b_quar = create_batch(csv_quarantine, "live_quarantine.csv")
    b_quar = executor.execute_batch(batch_id=b_quar.id, actor_id="engineer")

    assert b_quar.status == BatchStatusEnum.SUCCESS
    recon = db.query(BatchReconciliation).filter(BatchReconciliation.batch_id == b_quar.id).first()
    assert recon is not None
    assert recon.rows_in == 5
    assert recon.rows_silver_raw == 3
    assert recon.rows_quarantined == 2
    assert recon.balance_check_passed is True

    # Inspect dq_results
    dq_res = db.query(DQResult).filter(DQResult.batch_id == b_quar.id, DQResult.rule_version_id == r_quarantine_v.id).first()
    assert dq_res is not None
    assert dq_res.total_rows_evaluated == 5
    assert dq_res.passed_rows == 3
    assert dq_res.failed_rows == 2
    assert dq_res.action_taken == DQActionTakenEnum.QUARANTINED_ROWS
    print(f"Batch {b_quar.id} reconciliation: rows_in={recon.rows_in}, silver_raw={recon.rows_silver_raw}, quarantined={recon.rows_quarantined}, balance_check_passed={recon.balance_check_passed}")
    print(f"DQ Result: Rule '{r_quarantine_v.rule.name}', Evaluated={dq_res.total_rows_evaluated}, Passed={dq_res.passed_rows}, Failed={dq_res.failed_rows}, PassRate={dq_res.pass_rate}, Action={dq_res.action_taken.value}, ExecutionTime={dq_res.execution_duration_ms}ms")
    print("[PASS] Production DQ quarantine and measurable reconciliation balance verified.")

    # 5. SCENARIO D: Production DQ Rules - REJECT_FILE Abort
    print("\n--- 5. SCENARIO D: PRODUCTION DQ RULES — REJECT_FILE ABORT ---")
    rule_reject = DataQualityRule(
        id=uuid.uuid4(),
        feed_id=feed.id,
        schema_id=schema_obj.id,
        name="member_id_regex_strict",
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(rule_reject)
    db.flush()

    r_reject_v = RuleVersion(
        id=uuid.uuid4(),
        rule_id=rule_reject.id,
        version_number=1,
        schema_version_id=sv.id,
        status=RuleVersionStatusEnum.PUBLISHED,
        rule_type=RuleTypeEnum.REGEX,
        target_field="member_id",
        severity=RuleSeverityEnum.REJECT_FILE,
        rule_config={"pattern": r"^M\d{3}$"},
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(r_reject_v)
    db.commit()

    # File with invalid member_id format 'BAD_ID_99'
    csv_reject = f"member_id,first_name,age\nM001,Alice,30\nBAD_ID_{prefix},Bob,25\n".encode("utf-8")
    b_rej = create_batch(csv_reject, "live_reject.csv")
    b_rej = executor.execute_batch(batch_id=b_rej.id, actor_id="engineer")

    assert b_rej.status == BatchStatusEnum.FAILED
    assert "rejected by rule" in b_rej.error_message.lower()

    dq_res_rej = db.query(DQResult).filter(DQResult.batch_id == b_rej.id, DQResult.rule_version_id == r_reject_v.id).first()
    assert dq_res_rej is not None
    assert dq_res_rej.action_taken == DQActionTakenEnum.BATCH_ABORTED
    print(f"Batch {b_rej.id} status: {b_rej.status.value}, Error: {b_rej.error_message}")
    print(f"DQ Result: Action={dq_res_rej.action_taken.value}, Passed={dq_res_rej.passed_rows}, Failed={dq_res_rej.failed_rows}")
    print("[PASS] REJECT_FILE severity rule aborted batch execution as designed.")

    # 6. REST API Endpoints Verification
    print("\n--- 6. REST API ENDPOINTS VERIFICATION ---")
    # Test /api/v1/schemas/drift list and detail
    drift_list_res = client.get(f"/api/v1/schemas/drift?feed_id={feed.id}", headers=eng_headers)
    assert drift_list_res.status_code == 200
    assert drift_list_res.json()["total"] >= 2
    print(f"GET /api/v1/schemas/drift total: {drift_list_res.json()['total']}")

    drift_detail_res = client.get(f"/api/v1/schemas/drift/{drift_report_breaking.id}", headers=eng_headers)
    assert drift_detail_res.status_code == 200
    assert drift_detail_res.json()["drift_severity"] == "BREAKING"
    print(f"GET /api/v1/schemas/drift/{drift_report_breaking.id} status: {drift_detail_res.status_code}")

    # Test /api/v1/rules/executions
    exec_list_res = client.get(f"/api/v1/rules/executions?batch_id={b_quar.id}", headers=eng_headers)
    assert exec_list_res.status_code == 200
    print(f"GET /api/v1/rules/executions total: {exec_list_res.json()['total']}")

    batch_summary_res = client.get(f"/api/v1/rules/executions/batch/{b_quar.id}", headers=eng_headers)
    assert batch_summary_res.status_code == 200
    summary_data = batch_summary_res.json()
    assert summary_data["total_rows_evaluated"] == 5
    assert summary_data["has_quarantined_rows"] is True
    print(f"GET /api/v1/rules/executions/batch/{b_quar.id} summary: {json.dumps(summary_data, indent=2)}")
    print("[PASS] All REST APIs verified.")

    # 7. PHI & Privacy Audit Inspection
    print("\n--- 7. PHI & DATA ISOLATION AUDIT INSPECTION ---")
    drift_rows = db.query(SchemaDriftReport).filter(SchemaDriftReport.feed_id == feed.id).all()
    for dr in drift_rows:
        text_repr = f"{dr.missing_fields} {dr.unexpected_fields} {dr.type_mismatches} {dr.acknowledgement_notes}"
        for patient_val in ["Alice", "Bob", "Charlie", "Dana", "Dave", "Eve", "M01", "M02", "M901", "Peanuts"]:
            assert patient_val not in text_repr, f"PHI LEAKAGE: '{patient_val}' found in SchemaDriftReport {dr.id}"
    print("[PASS] Verified ZERO PHI in schema_drift_reports table.")

    dq_rows = db.query(DQResult).filter(DQResult.batch_id.in_([b_breaking.id, b_nonbreaking.id, b_quar.id, b_rej.id])).all()
    for dqr in dq_rows:
        # dq_results only has count columns and metadata
        assert hasattr(dqr, "passed_rows")
        assert hasattr(dqr, "failed_rows")
        assert hasattr(dqr, "pass_rate")
        assert not hasattr(dqr, "sample_data")
        assert not hasattr(dqr, "raw_records")
    print("[PASS] Verified ZERO PHI in dq_results table (telemetry counts and pass rates only).")

    audit_rows = db.query(AuditEvent).filter(
        AuditEvent.action.in_([
            AuditActionEnum.SCHEMA_DRIFT_DETECTED,
            AuditActionEnum.SCHEMA_DRIFT_ACKNOWLEDGED,
            AuditActionEnum.RULE_PRODUCTION_EXECUTED,
            AuditActionEnum.RULE_BATCH_ABORTED,
        ])
    ).all()
    print(f"Total Slice 1 audit events emitted: {len(audit_rows)}")
    for a in audit_rows:
        audit_str = json.dumps(a.after_state or {}) + " " + (a.description or "")
        for patient_val in ["Alice", "Bob", "Charlie", "Dana", "Dave", "Eve", "Peanuts"]:
            assert patient_val not in audit_str, f"PHI LEAKAGE in audit event {a.id}: '{patient_val}'"
        print(f"  Audit Action: {a.action.value}, Actor: {a.actor_email or a.actor_id}, Target: {a.object_type}/{a.object_id}")
    print("[PASS] Verified ZERO PHI across all Slice 1 audit events.")

    print("\n================================================================================")
    print("ALL WAVE 2 SLICE 1 INDEPENDENT LIVE VERIFICATIONS PASSED SUCCESSFULLY!")
    print("================================================================================")
    db.close()


if __name__ == "__main__":
    run_live_verification()
