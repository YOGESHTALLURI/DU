"""
Live End-to-End Demonstration Script for Wave 1 Slice 1:
1. Logs in as Business Analyst (mock-analyst-001)
2. Uploads first representative CSV (Member Roster)
3. Profiles Member Roster -> validates row count (4), column count (5), date pattern (YYYY-MM-DD), null %
4. Uploads second completely different CSV (Healthcare Claims)
5. Profiles Claims -> validates row count (3), column count (4), types (DECIMAL, DATE), null %
6. Creates Schema Contract draft for Claims feed seeded from profiling facts
7. Validates Lineage (schema_version.source_profiling_run_id == profiling_run.id)
8. Edits draft schema contract (custom field description and required constraint)
9. Publishes schema contract -> verifies status=PUBLISHED and version locked
10. Attempts edit on published schema -> verifies 400 Bad Request (strict immutability)
11. Creates incremented v2 draft -> verifies version_number=2 and editable
12. Verifies complete audit trail
"""
import io
import time
import httpx
from pathlib import Path

BACKEND_URL = "http://127.0.0.1:8000"


def run_e2e_demo():
    client = httpx.Client(timeout=15.0)

    # 1. Login as Business Analyst
    r_login = client.post(
        f"{BACKEND_URL}/api/v1/auth/login",
        json={"credential": "analyst:analyst123"},
    )
    assert r_login.status_code == 200, f"Login failed: {r_login.text}"
    token = r_login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("[PASS] 1. Logged in as Business Analyst (mock-analyst-001)")

    # 2. Login as Engineer to create the two feeds
    r_eng_login = client.post(
        f"{BACKEND_URL}/api/v1/auth/login",
        json={"credential": "engineer:engineer123"},
    )
    eng_token = r_eng_login.json()["access_token"]
    eng_headers = {"Authorization": f"Bearer {eng_token}"}

    ts = int(time.time() * 1000)
    feed1_name = f"MEMBERS_FEED_{ts}"
    r_feed1 = client.post(
        f"{BACKEND_URL}/api/v1/feeds",
        json={
            "name": feed1_name,
            "domain": "ELIGIBILITY",
            "landing_folder": "./data/landing",
            "filename_pattern": f"{feed1_name}_*.csv",
            "initial_config": {"fields": [{"name": "member_id", "type": "STRING"}]},
        },
        headers=eng_headers,
    )
    assert r_feed1.status_code == 201
    feed1_id = r_feed1.json()["id"]

    feed2_name = f"CLAIMS_FEED_{ts}"
    r_feed2 = client.post(
        f"{BACKEND_URL}/api/v1/feeds",
        json={
            "name": feed2_name,
            "domain": "CLAIMS",
            "landing_folder": "./data/landing",
            "filename_pattern": f"{feed2_name}_*.csv",
            "initial_config": {"fields": [{"name": "claim_id", "type": "STRING"}]},
        },
        headers=eng_headers,
    )
    assert r_feed2.status_code == 201
    feed2_id = r_feed2.json()["id"]
    print(f"[PASS] 2. Created testing feeds: {feed1_name} and {feed2_name}")

    # 3. BA Uploads Sample 1 (Member Data)
    member_csv = (
        "member_id,first_name,last_name,date_of_birth,gender\n"
        "M001,Alice,Johnson,1985-06-15,F\n"
        "M002,Bob,Smith,1990-03-22,M\n"
        "M003,Carol,Williams,1978-11-08,F\n"
        "M004,David,,1982-01-30,M\n"
    ).encode("utf-8")
    files1 = {"file": ("members_sample.csv", io.BytesIO(member_csv), "text/csv")}
    r_sample1 = client.post(f"{BACKEND_URL}/api/v1/feeds/{feed1_id}/samples", files=files1, headers=headers)
    assert r_sample1.status_code == 201
    sample1_id = r_sample1.json()["id"]
    print(f"[PASS] 3. Uploaded Sample 1 to {feed1_name} (ID: {sample1_id})")

    # 4. Profile Sample 1 (Member Data)
    r_prof1 = client.post(f"{BACKEND_URL}/api/v1/feeds/{feed1_id}/samples/{sample1_id}/profile", headers=headers)
    assert r_prof1.status_code == 201
    run1_id = r_prof1.json()["id"]
    r_det1 = client.get(f"{BACKEND_URL}/api/v1/profiling-runs/{run1_id}", headers=headers)
    det1 = r_det1.json()
    assert det1["row_count"] == 4
    assert det1["column_count"] == 5
    cols1 = {c["column_name"]: c for c in det1["column_stats"]}
    assert cols1["last_name"]["null_count"] == 1
    assert cols1["date_of_birth"]["inferred_type"] == "DATE"
    assert cols1["date_of_birth"]["detected_date_patterns"][0]["pattern"] == "YYYY-MM-DD"
    print(f"[PASS] 4. Profiled Sample 1: 4 rows, 5 columns, last_name has 1 null (25%), date_of_birth inferred as DATE (YYYY-MM-DD)")

    # 5. BA Uploads Sample 2 (Completely different Claims CSV as requested)
    claims_csv = (
        "claim_id,provider_id,claim_amount,service_date\n"
        "C001,P100,125.50,2026-01-15\n"
        "C002,P101,450.00,2026-01-17\n"
        "C003,P100,,2026-01-20\n"
    ).encode("utf-8")
    files2 = {"file": ("claims_sample.csv", io.BytesIO(claims_csv), "text/csv")}
    r_sample2 = client.post(f"{BACKEND_URL}/api/v1/feeds/{feed2_id}/samples", files=files2, headers=headers)
    assert r_sample2.status_code == 201
    sample2_id = r_sample2.json()["id"]
    print(f"[PASS] 5. Uploaded Sample 2 to {feed2_name} (ID: {sample2_id})")

    # 6. Profile Sample 2 (Claims Data)
    r_prof2 = client.post(f"{BACKEND_URL}/api/v1/feeds/{feed2_id}/samples/{sample2_id}/profile", headers=headers)
    assert r_prof2.status_code == 201
    run2_id = r_prof2.json()["id"]
    r_det2 = client.get(f"{BACKEND_URL}/api/v1/profiling-runs/{run2_id}", headers=headers)
    det2 = r_det2.json()
    assert det2["row_count"] == 3
    assert det2["column_count"] == 4
    cols2 = {c["column_name"]: c for c in det2["column_stats"]}
    assert cols2["claim_amount"]["inferred_type"] == "DECIMAL"
    assert cols2["claim_amount"]["null_count"] == 1
    assert cols2["service_date"]["inferred_type"] == "DATE"
    assert cols2["provider_id"]["distinct_count"] == 2
    print(f"[PASS] 6. Profiled Sample 2: 3 rows, 4 columns, claim_amount inferred as DECIMAL (1 null), service_date inferred as DATE")

    # 7. Create Schema Contract Draft with Lineage from Profiling Run 2
    r_schema = client.post(
        f"{BACKEND_URL}/api/v1/schemas",
        json={
            "feed_id": feed2_id,
            "name": f"Institutional Claims Schema v1",
            "description": "Governed contract for claims feed",
            "source_profiling_run_id": run2_id,
        },
        headers=headers,
    )
    assert r_schema.status_code == 201
    schema_data = r_schema.json()
    schema_id = schema_data["id"]
    draft_v1 = schema_data["draft_version"]
    v1_id = draft_v1["id"]

    # Verify Lineage
    assert draft_v1["source_profiling_run_id"] == run2_id
    assert draft_v1["source_sample_file_id"] == sample2_id
    assert len(draft_v1["fields"]) == 4
    print(f"[PASS] 7. Created Schema Contract Draft '{schema_data['name']}' with verified lineage to Run {run2_id[:8]}")

    # 8. BA Edits Draft Schema (Distinguishing Schema Decision from Profiling Fact)
    fields_update = []
    for f in draft_v1["fields"]:
        if f["field_name"] == "claim_amount":
            # BA makes explicit decision: claim_amount is required even though sample had null
            f["is_required"] = True
            f["description"] = "Billed amount before copay and adjustments"
        fields_update.append({
            "field_name": f["field_name"],
            "ordinal_position": f["ordinal_position"],
            "data_type": f["data_type"],
            "is_nullable": f["is_nullable"],
            "is_required": f["is_required"],
            "format_pattern": f["format_pattern"],
            "description": f["description"],
            "source_metadata": f["source_metadata"],
        })

    r_update = client.put(
        f"{BACKEND_URL}/api/v1/schemas/{schema_id}/versions/{v1_id}",
        json={"change_notes": "Enforced claim_amount as required field", "fields": fields_update},
        headers=headers,
    )
    assert r_update.status_code == 200
    updated_ver = r_update.json()
    amt_field = next(f for f in updated_ver["fields"] if f["field_name"] == "claim_amount")
    assert amt_field["is_required"] is True
    print("[PASS] 8. Updated Schema Draft: BA explicitly set claim_amount is_required=True and documented description")

    # 9. BA Publishes Schema Version 1 (Locks it immutably)
    r_pub = client.post(
        f"{BACKEND_URL}/api/v1/schemas/{schema_id}/versions/{v1_id}/publish",
        json={"change_notes": "Production release of Claims Schema v1"},
        headers=headers,
    )
    assert r_pub.status_code == 200
    pub_ver = r_pub.json()
    assert pub_ver["status"] == "PUBLISHED"
    assert pub_ver["published_by"] == "mock-analyst-001"
    print("[PASS] 9. Published Schema Version 1 -> Locked into PUBLISHED status")

    # 10. Attempt to modify PUBLISHED version -> Verify rejection
    r_illegal_edit = client.put(
        f"{BACKEND_URL}/api/v1/schemas/{schema_id}/versions/{v1_id}",
        json={"change_notes": "Illegal edit attempt", "fields": fields_update},
        headers=headers,
    )
    assert r_illegal_edit.status_code == 400
    assert "strictly immutable" in r_illegal_edit.json()["detail"]
    print("[PASS] 10. Strict Immutability enforced: Modification of PUBLISHED version rejected with HTTP 400")

    # 11. Create New Draft v2 from v1
    r_v2 = client.post(
        f"{BACKEND_URL}/api/v1/schemas/{schema_id}/versions/{v1_id}/new-draft",
        headers=headers,
    )
    assert r_v2.status_code == 201
    v2_data = r_v2.json()
    assert v2_data["version_number"] == 2
    assert v2_data["status"] == "DRAFT"
    assert len(v2_data["fields"]) == 4
    print("[PASS] 11. Incremented Draft Version 2 created from v1 (status=DRAFT, editable)")

    # 12. Verify Audit Trail
    r_audit = client.get(f"{BACKEND_URL}/api/v1/audit/events?limit=100", headers=headers)
    assert r_audit.status_code == 200
    events = r_audit.json()
    actions = {e["action"] for e in events}
    expected_actions = [
        "sample.uploaded",
        "profiling.started",
        "profiling.completed",
        "schema.created",
        "schema.draft_updated",
        "schema.published",
        "schema.version_created",
    ]
    for act in expected_actions:
        assert act in actions, f"Missing audit action: {act}"
    print(f"[PASS] 12. Complete Audit Trail verified: All {len(expected_actions)} Wave 1 actions recorded")

    print("\nALL WAVE 1 SLICE 1 REQUIREMENTS AND CONSTRAINTS INDEPENDENTLY CONFIRMED!")


if __name__ == "__main__":
    run_e2e_demo()
