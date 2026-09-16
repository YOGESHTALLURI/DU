"""
Live verification script for Wave 1 Slice 6: Scheduling, Dependencies & Downstream Protection.
Tests live HTTP endpoints on port 8000 and inspects PostgreSQL database records and audit trail.
"""
import requests
import uuid
import psycopg

BASE_URL = "http://localhost:8000"
DB_CONN = "postgresql://cinqflow:cinqflow@localhost:5432/cinqflow"

def run_live_verification():
    print("=== 1. Authentication ===")
    eng_res = requests.post(f"{BASE_URL}/api/v1/auth/login", json={"credential": "engineer:engineer123"})
    assert eng_res.status_code == 200, f"Engineer login failed: {eng_res.text}"
    eng_token = eng_res.json()["access_token"]
    eng_headers = {"Authorization": f"Bearer {eng_token}", "Content-Type": "application/json"}
    print("Engineer authenticated.")

    ro_res = requests.post(f"{BASE_URL}/api/v1/auth/login", json={"credential": "readonly:readonly123"})
    assert ro_res.status_code == 200
    ro_token = ro_res.json()["access_token"]
    ro_headers = {"Authorization": f"Bearer {ro_token}", "Content-Type": "application/json"}
    print("Read-Only user authenticated.")

    print("\n=== 2. Feed Creation ===")
    uid = uuid.uuid4().hex[:6]
    up_name = f"LIVE_CLAIMS_UP_{uid}"
    down_name = f"LIVE_ENCOUNTERS_DOWN_{uid}"

    f1 = requests.post(f"{BASE_URL}/api/v1/feeds", json={
        "name": up_name,
        "domain": "CLAIMS",
        "landing_folder": f"./data/landing/{up_name.lower()}",
        "filename_pattern": "claims_.*\\.csv",
        "schedule_expression": "0 2 * * *",
    }, headers=eng_headers)
    assert f1.status_code == 201
    up_feed_id = f1.json()["id"]

    f2 = requests.post(f"{BASE_URL}/api/v1/feeds", json={
        "name": down_name,
        "domain": "ENCOUNTERS",
        "landing_folder": f"./data/landing/{down_name.lower()}",
        "filename_pattern": "encounters_.*\\.csv",
        "schedule_expression": "0 4 * * *",
    }, headers=eng_headers)
    assert f2.status_code == 201
    down_feed_id = f2.json()["id"]
    print(f"Created upstream feed: {up_name} ({up_feed_id}) and downstream feed: {down_name} ({down_feed_id})")

    print("\n=== 3. Authoritative Feed Schedules ===")
    # Initial GET schedule (migrated/seeded from Feed)
    s1 = requests.get(f"{BASE_URL}/api/v1/schedules/feed/{up_feed_id}", headers=eng_headers)
    assert s1.status_code == 200, f"Failed GET schedule: {s1.text}"
    s1_data = s1.json()
    assert s1_data["schedule_expression"] == "0 2 * * *"
    assert s1_data["status"] == "ACTIVE"
    assert s1_data["next_run_at"] is not None
    print(f"Initial schedule verified: {s1_data['schedule_expression']}, next_run: {s1_data['next_run_at']}")

    # Idempotent PUT schedule update
    s1_update = requests.put(f"{BASE_URL}/api/v1/schedules/feed/{up_feed_id}", json={
        "schedule_expression": "30 2 * * *",
        "timezone": "America/New_York",
    }, headers=eng_headers)
    assert s1_update.status_code == 200
    assert s1_update.json()["schedule_expression"] == "30 2 * * *"
    assert s1_update.json()["timezone"] == "America/New_York"
    print("Updated schedule: 30 2 * * * with timezone America/New_York")

    # State machine: Pause & Resume
    pause_res = requests.post(f"{BASE_URL}/api/v1/schedules/feed/{up_feed_id}/pause", headers=eng_headers)
    assert pause_res.status_code == 200
    assert pause_res.json()["status"] == "PAUSED"
    assert pause_res.json()["next_run_at"] is None
    print("Schedule paused successfully. next_run_at cleared.")

    resume_res = requests.post(f"{BASE_URL}/api/v1/schedules/feed/{up_feed_id}/resume", headers=eng_headers)
    assert resume_res.status_code == 200
    assert resume_res.json()["status"] == "ACTIVE"
    assert resume_res.json()["next_run_at"] is not None
    print("Schedule resumed successfully. next_run_at recalculated.")

    print("\n=== 4. Dependency DAG & Topological Cycle Prevention ===")
    # Add dependency: Downstream depends on Upstream
    dep_res = requests.post(f"{BASE_URL}/api/v1/dependencies/", json={
        "downstream_feed_id": down_feed_id,
        "upstream_feed_id": up_feed_id,
        "dependency_type": "HARD",
        "max_lag_hours": 24,
        "block_on_upstream_failure": True,
        "block_on_reject_file": True,
        "block_on_unbalanced_reconciliation": True,
        "max_quarantine_rate_pct": 5.0,
    }, headers=eng_headers)
    assert dep_res.status_code == 201, f"Failed adding dependency: {dep_res.text}"
    dep_id = dep_res.json()["id"]
    print(f"Added dependency: {down_name} -> {up_name} (ID: {dep_id})")

    # Cycle Detection: Attempt Upstream depends on Downstream (should 400 Bad Request)
    cycle_res = requests.post(f"{BASE_URL}/api/v1/dependencies/", json={
        "downstream_feed_id": up_feed_id,
        "upstream_feed_id": down_feed_id,
        "dependency_type": "HARD",
    }, headers=eng_headers)
    assert cycle_res.status_code == 400, f"Expected 400 cycle error, got {cycle_res.status_code}: {cycle_res.text}"
    assert "Circular dependency detected" in cycle_res.json()["detail"]
    print(f"Cycle prevented: {cycle_res.json()['detail']}")

    print("\n=== 5. Downstream Gate Inspection ===")
    gate_res = requests.get(f"{BASE_URL}/api/v1/dependencies/gate-check/{down_feed_id}", headers=eng_headers)
    assert gate_res.status_code == 200
    gate_data = gate_res.json()
    assert gate_data["is_allowed"] is False
    assert len(gate_data["blocking_reasons"]) > 0
    assert any("has never completed" in r for r in gate_data["blocking_reasons"])
    print(f"Gate check correctly BLOCKED downstream: {gate_data['blocking_reasons']}")

    print("\n=== 6. System DAG Retrieval ===")
    dag_res = requests.get(f"{BASE_URL}/api/v1/dependencies/dag", headers=eng_headers)
    assert dag_res.status_code == 200
    dag_data = dag_res.json()
    assert dag_data["is_acyclic"] is True
    assert any(n["feed_id"] == down_feed_id for n in dag_data["nodes"])
    assert any(e["id"] == dep_id for e in dag_data["edges"])
    print(f"DAG graph validated: {dag_data['total_feeds']} nodes, {dag_data['total_dependencies']} edges, acyclic={dag_data['is_acyclic']}")

    print("\n=== 7. RBAC Verification ===")
    # READ_ONLY forbidden on schedule mutation
    ro_sched = requests.post(f"{BASE_URL}/api/v1/schedules/feed/{up_feed_id}/pause", headers=ro_headers)
    assert ro_sched.status_code == 403
    # READ_ONLY forbidden on dependency creation
    ro_dep = requests.post(f"{BASE_URL}/api/v1/dependencies/", json={
        "downstream_feed_id": down_feed_id,
        "upstream_feed_id": up_feed_id,
        "dependency_type": "HARD",
    }, headers=ro_headers)
    assert ro_dep.status_code == 403
    print("RBAC verified: READ_ONLY receives 403 Forbidden on schedule & dependency mutations.")

    print("\n=== 8. Audit Trail & Zero-PHI Verification ===")
    with psycopg.connect(DB_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT action, object_type, actor_email, before_state, after_state
                FROM audit_events
                WHERE object_id = %s OR description LIKE %s
                ORDER BY created_at ASC
            """, (str(dep_id), f"%{up_name}%"))
            rows = cur.fetchall()
            print(f"Found {len(rows)} audit events logged for this workflow:")
            for action, obj_type, actor, before, after in rows:
                print(f"  - Action: {action} on {obj_type} by {actor}")
                # Check zero-PHI (no personal data keys)
                state_str = str(before) + str(after)
                for sensitive in ["ssn", "dob", "patient", "member_id", "first_name", "last_name", "mrn"]:
                    assert sensitive not in state_str.lower(), f"Potential PHI leaked in audit: {sensitive}"
            print("Zero PHI verified in all audit events.")

    print("\n>>> LIVE VERIFICATION COMPLETED CLEANLY! <<<")

if __name__ == "__main__":
    run_live_verification()
