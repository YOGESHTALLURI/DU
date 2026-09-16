"""
Targeted live verification script for Wave 1 Slice 6.
Executes all required actions against live API (port 8000) and directly queries PostgreSQL
to prove all 8 audit events, HTTP status codes, structural IDs, and Zero PHI.
"""
import requests
import uuid
import json
from datetime import datetime, timezone
import psycopg

BASE_URL = "http://localhost:8000"
DB_CONN = "postgresql://cinqflow:cinqflow@localhost:5432/cinqflow"

def check_no_phi(obj, label=""):
    """Validates that no patient or sample data exists in audit payloads."""
    text_repr = json.dumps(obj) if isinstance(obj, (dict, list)) else str(obj)
    sensitive_markers = ["ssn", "dob", "patient", "member_id", "first_name", "last_name", "mrn", "diagnosis", "claim_id"]
    for marker in sensitive_markers:
        assert marker not in text_repr.lower(), f"Potential PHI found in {label}: {marker}"

def get_audit_record(action_name, object_id=None):
    """Directly queries PostgreSQL for the latest audit event of a specific action."""
    with psycopg.connect(DB_CONN) as conn:
        with conn.cursor() as cur:
            if object_id:
                cur.execute("""
                    SELECT id, action, actor_id, actor_email, object_type, object_id, before_state, after_state, description, created_at
                    FROM audit_events
                    WHERE action = %s AND object_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (action_name, str(object_id)))
            else:
                cur.execute("""
                    SELECT id, action, actor_id, actor_email, object_type, object_id, before_state, after_state, description, created_at
                    FROM audit_events
                    WHERE action = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (action_name,))
            row = cur.fetchone()
            if not row:
                return None
            return {
                "id": str(row[0]),
                "action": row[1],
                "actor_id": row[2],
                "actor_email": row[3],
                "object_type": row[4],
                "object_id": str(row[5]),
                "before_state": row[6],
                "after_state": row[7],
                "description": row[8],
                "created_at": row[9].isoformat() if row[9] else None,
            }

def run_targeted_verification():
    print("================================================================================")
    print("STARTING TARGETED LIVE AUDIT & SYSTEM VERIFICATION FOR SLICE 6")
    print("================================================================================\n")

    # 0. Auth
    eng_res = requests.post(f"{BASE_URL}/api/v1/auth/login", json={"credential": "engineer:engineer123"})
    assert eng_res.status_code == 200
    token = eng_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    results = {}

    # =========================================================================
    # REQUIREMENT 5 & 1: schedule.created (Upsert path for feed without schedule)
    # =========================================================================
    print("--- 1. Testing schedule.created ---")
    prefix = uuid.uuid4().hex[:6]
    # Create feed directly in DB without creating a feed_schedules entry so it has NO schedule record
    with psycopg.connect(DB_CONN, autocommit=True) as conn:
        with conn.cursor() as cur:
            feed_sched_id = uuid.uuid4()
            feed_name = f"FEED_SCHED_NEW_{prefix}"
            cur.execute("""
                INSERT INTO feeds (id, name, domain, format, landing_folder, filename_pattern, schedule_expression, status, created_by, updated_by, version)
                VALUES (%s, %s, 'CLAIMS', 'CSV', './data/landing', '*.csv', '0 0 * * *', 'ACTIVE', 'engineer@cinqflow.local', 'engineer@cinqflow.local', 1)
            """, (feed_sched_id, feed_name))

    # Verify no feed_schedules record exists yet
    with psycopg.connect(DB_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM feed_schedules WHERE feed_id = %s", (feed_sched_id,))
            assert cur.fetchone()[0] == 0, "Schedule record should not exist before creation"

    # Call PUT /api/v1/schedules/feed/{feed_id} to perform first creation
    put_sched_res = requests.put(
        f"{BASE_URL}/api/v1/schedules/feed/{feed_sched_id}",
        json={"schedule_expression": "15 4 * * *", "timezone": "America/Chicago"},
        headers=headers
    )
    assert put_sched_res.status_code == 200, f"PUT schedule failed: {put_sched_res.text}"
    sched_data = put_sched_res.json()
    assert sched_data["schedule_expression"] == "15 4 * * *"
    assert sched_data["timezone"] == "America/Chicago"
    assert sched_data["next_run_at"] is not None
    sched_id = sched_data["id"]

    audit_sched_created = get_audit_record("schedule.created", sched_id)
    assert audit_sched_created is not None, "schedule.created audit record missing in PostgreSQL!"
    check_no_phi(audit_sched_created, "schedule.created audit")
    print(f"  [PASS] schedule.created verified in DB:")
    print(f"         Action:    {audit_sched_created['action']}")
    print(f"         Actor:     {audit_sched_created['actor_email']} ({audit_sched_created['actor_id']})")
    print(f"         Target:    {audit_sched_created['object_type']} ID {audit_sched_created['object_id']}")
    print(f"         Timestamp: {audit_sched_created['created_at']}")
    print(f"         After:     {audit_sched_created['after_state']}")
    results["schedule.created"] = audit_sched_created

    # =========================================================================
    # REQUIREMENT 1: schedule.updated
    # =========================================================================
    print("\n--- 2. Testing schedule.updated ---")
    update_res = requests.put(
        f"{BASE_URL}/api/v1/schedules/feed/{feed_sched_id}",
        json={"schedule_expression": "30 6 * * *", "timezone": "UTC"},
        headers=headers
    )
    assert update_res.status_code == 200
    sched_updated_data = update_res.json()
    assert sched_updated_data["schedule_expression"] == "30 6 * * *"

    audit_sched_updated = get_audit_record("schedule.updated", sched_id)
    assert audit_sched_updated is not None, "schedule.updated audit record missing in PostgreSQL!"
    check_no_phi(audit_sched_updated, "schedule.updated audit")
    print(f"  [PASS] schedule.updated verified in DB:")
    print(f"         Action:    {audit_sched_updated['action']}")
    print(f"         Actor:     {audit_sched_updated['actor_email']}")
    print(f"         Before:    {audit_sched_updated['before_state']}")
    print(f"         After:     {audit_sched_updated['after_state']}")
    results["schedule.updated"] = audit_sched_updated

    # =========================================================================
    # REQUIREMENT 1: schedule.paused
    # =========================================================================
    print("\n--- 3. Testing schedule.paused ---")
    pause_res = requests.post(f"{BASE_URL}/api/v1/schedules/feed/{feed_sched_id}/pause", headers=headers)
    assert pause_res.status_code == 200
    assert pause_res.json()["status"] == "PAUSED"
    assert pause_res.json()["next_run_at"] is None

    audit_sched_paused = get_audit_record("schedule.paused", sched_id)
    assert audit_sched_paused is not None, "schedule.paused audit record missing in PostgreSQL!"
    check_no_phi(audit_sched_paused, "schedule.paused audit")
    print(f"  [PASS] schedule.paused verified in DB:")
    print(f"         Action:    {audit_sched_paused['action']}")
    print(f"         Actor:     {audit_sched_paused['actor_email']}")
    print(f"         After:     {audit_sched_paused['after_state']}")
    results["schedule.paused"] = audit_sched_paused

    # =========================================================================
    # REQUIREMENT 1: schedule.resumed
    # =========================================================================
    print("\n--- 4. Testing schedule.resumed ---")
    resume_res = requests.post(f"{BASE_URL}/api/v1/schedules/feed/{feed_sched_id}/resume", headers=headers)
    assert resume_res.status_code == 200
    assert resume_res.json()["status"] == "ACTIVE"
    assert resume_res.json()["next_run_at"] is not None

    audit_sched_resumed = get_audit_record("schedule.resumed", sched_id)
    assert audit_sched_resumed is not None, "schedule.resumed audit record missing in PostgreSQL!"
    check_no_phi(audit_sched_resumed, "schedule.resumed audit")
    print(f"  [PASS] schedule.resumed verified in DB:")
    print(f"         Action:    {audit_sched_resumed['action']}")
    print(f"         Actor:     {audit_sched_resumed['actor_email']}")
    print(f"         After:     {audit_sched_resumed['after_state']}")
    results["schedule.resumed"] = audit_sched_resumed

    # =========================================================================
    # REQUIREMENT 6: DISABLED Lifecycle (ACTIVE -> DISABLED -> ENABLED/ACTIVE)
    # =========================================================================
    print("\n--- 5. Testing DISABLED lifecycle ---")
    # ACTIVE -> DISABLED
    dis_res = requests.post(f"{BASE_URL}/api/v1/schedules/feed/{feed_sched_id}/disable", headers=headers)
    assert dis_res.status_code == 200
    assert dis_res.json()["status"] == "DISABLED"
    assert dis_res.json()["next_run_at"] is None
    print(f"  [PASS] Schedule disabled: status=DISABLED, next_run_at={dis_res.json()['next_run_at']}")

    # Check DB state
    with psycopg.connect(DB_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status, next_run_at FROM feed_schedules WHERE feed_id = %s", (feed_sched_id,))
            row = cur.fetchone()
            assert row[0] == "DISABLED" and row[1] is None, f"Expected DISABLED with NULL next_run_at, got {row}"

    audit_sched_disabled = get_audit_record("schedule.disabled", sched_id)
    assert audit_sched_disabled is not None, "schedule.disabled audit missing!"
    print(f"  [PASS] schedule.disabled logged in audit: {audit_sched_disabled['after_state']}")

    # DISABLED -> ENABLED / ACTIVE
    ena_res = requests.post(f"{BASE_URL}/api/v1/schedules/feed/{feed_sched_id}/enable", headers=headers)
    assert ena_res.status_code == 200
    assert ena_res.json()["status"] == "ACTIVE"
    assert ena_res.json()["next_run_at"] is not None
    print(f"  [PASS] Schedule re-enabled: status=ACTIVE, next_run_at recalculated to {ena_res.json()['next_run_at']}")

    # Check DB state
    with psycopg.connect(DB_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status, next_run_at FROM feed_schedules WHERE feed_id = %s", (feed_sched_id,))
            row = cur.fetchone()
            assert row[0] == "ACTIVE" and row[1] is not None, f"Expected ACTIVE with non-null next_run_at, got {row}"

    audit_sched_enabled = get_audit_record("schedule.enabled", sched_id)
    assert audit_sched_enabled is not None, "schedule.enabled audit missing!"
    print(f"  [PASS] schedule.enabled logged in audit: {audit_sched_enabled['after_state']}")
    results["DISABLED lifecycle"] = {"disabled": audit_sched_disabled, "enabled": audit_sched_enabled}

    # =========================================================================
    # REQUIREMENT 1 & 4: dependency.created
    # =========================================================================
    print("\n--- 6. Testing dependency.created ---")
    feed_up_res = requests.post(f"{BASE_URL}/api/v1/feeds", json={
        "name": f"TARGETED_UP_{prefix}",
        "domain": "CLAIMS",
        "landing_folder": f"./data/landing/up_{prefix}",
        "filename_pattern": "*.csv",
        "schedule_expression": "0 1 * * *",
    }, headers=headers)
    assert feed_up_res.status_code == 201
    up_feed_id = feed_up_res.json()["id"]

    feed_down_res = requests.post(f"{BASE_URL}/api/v1/feeds", json={
        "name": f"TARGETED_DOWN_{prefix}",
        "domain": "ENCOUNTERS",
        "landing_folder": f"./data/landing/down_{prefix}",
        "filename_pattern": "*.csv",
        "schedule_expression": "0 3 * * *",
    }, headers=headers)
    assert feed_down_res.status_code == 201
    down_feed_id = feed_down_res.json()["id"]

    # Create dependency
    dep_create_res = requests.post(f"{BASE_URL}/api/v1/dependencies/", json={
        "downstream_feed_id": down_feed_id,
        "upstream_feed_id": up_feed_id,
        "dependency_type": "HARD",
        "max_lag_hours": 12,
        "block_on_upstream_failure": True,
        "block_on_reject_file": True,
        "block_on_unbalanced_reconciliation": True,
        "max_quarantine_rate_pct": 5.0,
    }, headers=headers)
    assert dep_create_res.status_code == 201
    dep_id = dep_create_res.json()["id"]

    audit_dep_created = get_audit_record("dependency.created", dep_id)
    assert audit_dep_created is not None, "dependency.created audit record missing in PostgreSQL!"
    check_no_phi(audit_dep_created, "dependency.created audit")
    print(f"  [PASS] dependency.created verified in DB:")
    print(f"         Action:    {audit_dep_created['action']}")
    print(f"         Actor:     {audit_dep_created['actor_email']}")
    print(f"         Target:    {audit_dep_created['object_type']} ID {audit_dep_created['object_id']}")
    print(f"         After:     {audit_dep_created['after_state']}")
    results["dependency.created"] = audit_dep_created

    # =========================================================================
    # REQUIREMENT 3: dependency.cycle_rejected
    # =========================================================================
    print("\n--- 7. Testing dependency.cycle_rejected ---")
    cycle_res = requests.post(f"{BASE_URL}/api/v1/dependencies/", json={
        "downstream_feed_id": up_feed_id,
        "upstream_feed_id": down_feed_id,
        "dependency_type": "HARD",
    }, headers=headers)
    assert cycle_res.status_code == 400, f"Expected 400, got {cycle_res.status_code}: {cycle_res.text}"
    detail = cycle_res.json()["detail"]
    assert "Circular dependency detected" in detail
    assert "TARGETED_DOWN_" in detail and "TARGETED_UP_" in detail
    print(f"  [PASS] HTTP 400 returned with cycle path: '{detail}'")

    # Verify dependency.cycle_rejected audit event
    audit_cycle = get_audit_record("dependency.cycle_rejected")
    assert audit_cycle is not None, "dependency.cycle_rejected missing from audit_events table!"
    assert audit_cycle["object_id"] == str(up_feed_id)
    check_no_phi(audit_cycle, "dependency.cycle_rejected audit")
    print(f"  [PASS] dependency.cycle_rejected verified in DB:")
    print(f"         Action:    {audit_cycle['action']}")
    print(f"         Actor:     {audit_cycle['actor_email']}")
    print(f"         Cycle Path:{audit_cycle['after_state']['cycle_path']}")
    print(f"         Readable:  {audit_cycle['after_state']['readable_path']}")

    # Verify no invalid edge was persisted
    with psycopg.connect(DB_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM feed_dependencies
                WHERE downstream_feed_id = %s AND upstream_feed_id = %s
            """, (up_feed_id, down_feed_id))
            assert cur.fetchone()[0] == 0, "Circular dependency edge was improperly persisted in DB!"
    print("  [PASS] Zero invalid dependency edges persisted in feed_dependencies.")
    results["dependency.cycle_rejected"] = audit_cycle

    # =========================================================================
    # REQUIREMENT 4: dependency.deleted
    # =========================================================================
    print("\n--- 8. Testing dependency.deleted ---")
    del_res = requests.delete(f"{BASE_URL}/api/v1/dependencies/{dep_id}", headers=headers)
    assert del_res.status_code == 200
    assert "deleted" in del_res.json().get("message", "").lower()

    # Verify no longer present in DB
    with psycopg.connect(DB_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM feed_dependencies WHERE id = %s", (dep_id,))
            assert cur.fetchone()[0] == 0, "Dependency was not removed from DB!"

    audit_dep_deleted = get_audit_record("dependency.deleted", dep_id)
    assert audit_dep_deleted is not None, "dependency.deleted missing from audit_events!"
    check_no_phi(audit_dep_deleted, "dependency.deleted audit")
    print(f"  [PASS] dependency.deleted verified in DB:")
    print(f"         Action:    {audit_dep_deleted['action']}")
    print(f"         Actor:     {audit_dep_deleted['actor_email']}")
    print(f"         Before:    {audit_dep_deleted['before_state']}")
    results["dependency.deleted"] = audit_dep_deleted

    # =========================================================================
    # REQUIREMENT 2: dependency.gate_blocked on actual POST /pipeline/.../execute
    # =========================================================================
    print("\n--- 9. Testing dependency.gate_blocked via POST /api/v1/pipeline/batches/{id}/execute ---")
    # 1. Recreate HARD dependency: downstream depends on upstream
    dep_hard_res = requests.post(f"{BASE_URL}/api/v1/dependencies/", json={
        "downstream_feed_id": down_feed_id,
        "upstream_feed_id": up_feed_id,
        "dependency_type": "HARD",
        "block_on_upstream_failure": True,
    }, headers=headers)
    assert dep_hard_res.status_code == 201

    # 2. Ensure upstream violates protection gate by creating a FAILED production batch for upstream
    with psycopg.connect(DB_CONN, autocommit=True) as conn:
        with conn.cursor() as cur:
            # Query version for upstream feed
            cur.execute("SELECT id FROM feed_versions WHERE feed_id = %s", (up_feed_id,))
            v_up_id = cur.fetchone()[0]

            up_batch_id = uuid.uuid4()
            cur.execute("""
                INSERT INTO batches (id, feed_id, feed_version_id, status, error_message, triggered_by, created_by, updated_by, version)
                VALUES (%s, %s, %s, 'FAILED', 'Fatal upstream upstream parser crash', 'system', 'system', 'system', 1)
            """, (up_batch_id, up_feed_id, v_up_id))

            # Query version for downstream feed
            cur.execute("SELECT id FROM feed_versions WHERE feed_id = %s", (down_feed_id,))
            v_down_id = cur.fetchone()[0]

            # Create a PENDING batch for downstream feed
            down_batch_id = uuid.uuid4()
            cur.execute("""
                INSERT INTO batches (id, feed_id, feed_version_id, status, triggered_by, created_by, updated_by, version)
                VALUES (%s, %s, %s, 'PENDING', 'engineer@cinqflow.local', 'engineer@cinqflow.local', 'engineer@cinqflow.local', 1)
            """, (down_batch_id, down_feed_id, v_down_id))

            # Count total batches before execute attempt
            cur.execute("SELECT COUNT(*) FROM batches")
            batch_count_before = cur.fetchone()[0]

    # 3. Attempt execution of downstream batch via actual pipeline execution endpoint
    print(f"  Attempting execution on downstream batch {down_batch_id}...")
    exec_res = requests.post(f"{BASE_URL}/api/v1/pipeline/batches/{down_batch_id}/execute", headers=headers)

    # 4. Confirm HTTP 412
    assert exec_res.status_code == 412, f"Expected HTTP 412 Precondition Failed, got {exec_res.status_code}: {exec_res.text}"
    detail_412 = exec_res.json()["detail"]
    assert "Downstream protection gate blocked execution" in detail_412
    assert "is FAILED" in detail_412 or "failed" in detail_412.lower()
    print(f"  [PASS] HTTP 412 Precondition Failed confirmed: '{detail_412}'")

    # 5. Confirm dependency.gate_blocked audit event appears in PostgreSQL
    audit_gate_blocked = get_audit_record("dependency.gate_blocked", down_feed_id)
    assert audit_gate_blocked is not None, "dependency.gate_blocked audit missing in PostgreSQL!"
    check_no_phi(audit_gate_blocked, "dependency.gate_blocked audit")
    print(f"  [PASS] dependency.gate_blocked verified in DB:")
    print(f"         Action:    {audit_gate_blocked['action']}")
    print(f"         Actor:     {audit_gate_blocked['actor_email']} ({audit_gate_blocked['actor_id']})")
    print(f"         Target:    {audit_gate_blocked['object_type']} ID {audit_gate_blocked['object_id']}")
    print(f"         Reasons:   {audit_gate_blocked['after_state']['blocking_reasons']}")
    results["dependency.gate_blocked"] = audit_gate_blocked

    # 6. Confirm no pipeline execution started (downstream batch remains PENDING, 0 stages)
    with psycopg.connect(DB_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status, started_at, completed_at FROM batches WHERE id = %s", (down_batch_id,))
            row = cur.fetchone()
            assert row[0] == "PENDING", f"Batch status should remain PENDING, got {row[0]}"
            assert row[1] is None, "Batch should not have started_at set"
            assert row[2] is None, "Batch should not have completed_at set"

            cur.execute("SELECT COUNT(*) FROM batch_stages WHERE batch_id = %s", (down_batch_id,))
            assert cur.fetchone()[0] == 0, "No batch stages should have been created or started!"

            # Confirm no new production batch was created as a result of the blocked request
            cur.execute("SELECT COUNT(*) FROM batches")
            batch_count_after = cur.fetchone()[0]
            assert batch_count_after == batch_count_before, f"Batch count changed! Before: {batch_count_before}, After: {batch_count_after}"

    print("  [PASS] Verified: batch remains PENDING, 0 stages executed, 0 new batches created.")

    print("\n================================================================================")
    print("ALL TARGETED VERIFICATIONS COMPLETED SUCCESSFULLY WITH ZERO PHI")
    print("================================================================================")
    return results

if __name__ == "__main__":
    run_targeted_verification()
