"""
Unit and Integration tests for Wave 1 Slice 1:
- Sample upload
- Deterministic profiling
- Lineage tracking
- Schema contract authoring
- Schema draft editing
- Schema immutability on publish
- Authorization (Analyst vs Read-Only)
- Audit logging
"""
import io
import time
import pytest
from backend.models.schema import SchemaDataTypeEnum, SchemaVersionStatusEnum


@pytest.fixture
def created_feed(client, engineer_headers):
    feed_name = f"FEED_W1_TEST_{int(time.time() * 1000)}"
    res = client.post(
        "/api/v1/feeds",
        json={
            "name": feed_name,
            "domain": "CLAIMS",
            "landing_folder": "./data/landing",
            "filename_pattern": f"{feed_name}_*.csv",
            "initial_config": {"fields": [{"name": "col1", "type": "STRING"}]},
        },
        headers=engineer_headers,
    )
    assert res.status_code == 201
    return res.json()


def test_sample_upload_analyst_and_storage(client, created_feed, analyst_headers):
    feed_id = created_feed["id"]
    csv_bytes = b"id,name,amount\n1,Alice,50.0\n2,Bob,75.2\n"
    files = {"file": ("sample_claims.csv", io.BytesIO(csv_bytes), "text/csv")}

    res = client.post(f"/api/v1/feeds/{feed_id}/samples", files=files, headers=analyst_headers)
    assert res.status_code == 201
    data = res.json()
    assert data["filename"] == "sample_claims.csv"
    assert data["file_size_bytes"] == len(csv_bytes)
    assert data["uploaded_by"] == "mock-analyst-001"


def test_sample_upload_readonly_forbidden(client, created_feed, readonly_headers):
    feed_id = created_feed["id"]
    csv_bytes = b"id,name\n1,Alice\n"
    files = {"file": ("sample.csv", io.BytesIO(csv_bytes), "text/csv")}

    res = client.post(f"/api/v1/feeds/{feed_id}/samples", files=files, headers=readonly_headers)
    assert res.status_code == 403


def test_profiling_and_facts(client, created_feed, analyst_headers):
    feed_id = created_feed["id"]
    csv_bytes = (
        b"patient_id,birth_date,copay,is_active\n"
        b"P001,1980-05-12,25.00,true\n"
        b"P002,1992-10-24,,false\n"
        b"P003,1975-01-01,15.50,true\n"
    )
    files = {"file": ("patients.csv", io.BytesIO(csv_bytes), "text/csv")}
    upload_res = client.post(f"/api/v1/feeds/{feed_id}/samples", files=files, headers=analyst_headers)
    assert upload_res.status_code == 201
    sample_id = upload_res.json()["id"]

    # Trigger profiling
    run_res = client.post(f"/api/v1/feeds/{feed_id}/samples/{sample_id}/profile", headers=analyst_headers)
    assert run_res.status_code == 201
    run_id = run_res.json()["id"]

    # Get profiling details
    detail_res = client.get(f"/api/v1/profiling-runs/{run_id}", headers=analyst_headers)
    assert detail_res.status_code == 200
    details = detail_res.json()

    assert details["status"] == "COMPLETED"
    assert details["row_count"] == 3
    assert details["column_count"] == 4

    col_map = {c["column_name"]: c for c in details["column_stats"]}
    assert col_map["patient_id"]["inferred_type"] == SchemaDataTypeEnum.STRING
    assert col_map["birth_date"]["inferred_type"] == SchemaDataTypeEnum.DATE
    assert col_map["copay"]["inferred_type"] == SchemaDataTypeEnum.DECIMAL
    assert col_map["copay"]["null_count"] == 1
    assert col_map["is_active"]["inferred_type"] == SchemaDataTypeEnum.BOOLEAN


def test_schema_contract_creation_with_lineage(client, created_feed, analyst_headers):
    feed_id = created_feed["id"]
    csv_bytes = b"member_num,service_date,fee\nM10,2026-03-01,100.0\nM20,2026-03-02,200.0\n"
    files = {"file": ("test_feed.csv", io.BytesIO(csv_bytes), "text/csv")}
    s_res = client.post(f"/api/v1/feeds/{feed_id}/samples", files=files, headers=analyst_headers)
    sample_id = s_res.json()["id"]

    p_res = client.post(f"/api/v1/feeds/{feed_id}/samples/{sample_id}/profile", headers=analyst_headers)
    run_id = p_res.json()["id"]

    # Create schema seeded from profiling run
    schema_payload = {
        "feed_id": feed_id,
        "name": "Member Claims Schema",
        "description": "Standard schema for claims feed",
        "source_profiling_run_id": run_id,
    }
    sc_res = client.post("/api/v1/schemas", json=schema_payload, headers=analyst_headers)
    assert sc_res.status_code == 201
    schema_data = sc_res.json()

    assert schema_data["name"] == "Member Claims Schema"
    draft_ver = schema_data["draft_version"]
    assert draft_ver["version_number"] == 1
    assert draft_ver["status"] == "DRAFT"
    # Verify Lineage
    assert draft_ver["source_profiling_run_id"] == run_id
    assert draft_ver["source_sample_file_id"] == sample_id
    assert len(draft_ver["fields"]) == 3


def test_schema_draft_update_and_immutability(client, created_feed, analyst_headers):
    feed_id = created_feed["id"]
    # 1. Create schema directly with manual initial fields
    schema_payload = {
        "feed_id": feed_id,
        "name": "Draft Immutability Test Schema",
        "initial_fields": [
            {
                "field_name": "id",
                "ordinal_position": 1,
                "data_type": "STRING",
                "is_nullable": False,
                "is_required": True,
            }
        ],
    }
    sc_res = client.post("/api/v1/schemas", json=schema_payload, headers=analyst_headers)
    assert sc_res.status_code == 201
    schema_id = sc_res.json()["id"]
    version_id = sc_res.json()["draft_version"]["id"]

    # 2. Update Draft Version
    update_payload = {
        "change_notes": "Added description and changed nullable",
        "fields": [
            {
                "field_name": "id",
                "ordinal_position": 1,
                "data_type": "STRING",
                "is_nullable": True,
                "is_required": False,
                "description": "Unique identifier",
            },
            {
                "field_name": "name",
                "ordinal_position": 2,
                "data_type": "STRING",
                "is_nullable": False,
                "is_required": True,
            },
        ],
    }
    up_res = client.put(f"/api/v1/schemas/{schema_id}/versions/{version_id}", json=update_payload, headers=analyst_headers)
    assert up_res.status_code == 200
    updated_version = up_res.json()
    assert len(updated_version["fields"]) == 2
    assert updated_version["change_notes"] == "Added description and changed nullable"

    # 3. Publish Version
    pub_res = client.post(
        f"/api/v1/schemas/{schema_id}/versions/{version_id}/publish",
        json={"change_notes": "Finalized version 1"},
        headers=analyst_headers,
    )
    assert pub_res.status_code == 200
    published_version = pub_res.json()
    assert published_version["status"] == "PUBLISHED"
    assert published_version["published_by"] == "mock-analyst-001"

    # 4. Attempt to modify PUBLISHED version -> must be rejected (400 Bad Request)
    fail_res = client.put(f"/api/v1/schemas/{schema_id}/versions/{version_id}", json=update_payload, headers=analyst_headers)
    assert fail_res.status_code == 400
    assert "strictly immutable" in fail_res.json()["detail"]


def test_audit_trail_for_wave1_actions(client, created_feed, analyst_headers):
    feed_id = created_feed["id"]
    csv_bytes = b"colA,colB\n1,2\n"
    files = {"file": ("audit_sample.csv", io.BytesIO(csv_bytes), "text/csv")}
    s_res = client.post(f"/api/v1/feeds/{feed_id}/samples", files=files, headers=analyst_headers)
    sample_id = s_res.json()["id"]

    p_res = client.post(f"/api/v1/feeds/{feed_id}/samples/{sample_id}/profile", headers=analyst_headers)
    run_id = p_res.json()["id"]

    sc_res = client.post(
        "/api/v1/schemas",
        json={"feed_id": feed_id, "name": "Audit Schema Test", "source_profiling_run_id": run_id},
        headers=analyst_headers,
    )
    schema_id = sc_res.json()["id"]
    version_id = sc_res.json()["draft_version"]["id"]

    client.post(
        f"/api/v1/schemas/{schema_id}/versions/{version_id}/publish",
        json={"change_notes": "Publishing for audit verification"},
        headers=analyst_headers,
    )

    # Check Audit Log
    a_res = client.get("/api/v1/audit/events?limit=50", headers=analyst_headers)
    assert a_res.status_code == 200
    events = a_res.json()
    actions = {e["action"] for e in events}

    assert "sample.uploaded" in actions
    assert "profiling.started" in actions
    assert "profiling.completed" in actions
    assert "schema.created" in actions
    assert "schema.published" in actions


def test_e2e_sample_upload_profiling_and_api_verification(client, created_feed, analyst_headers):
    """
    End-to-end verification through:
      Sample Upload -> Profiling Execution -> Database Persistence -> Live API Response
    Verifies:
      claim_amount = DECIMAL, min=48, max=450
      service_date = DATE, pattern=DD/MM/YYYY, min=15/01/2026, max=22/01/2026
    """
    feed_id = created_feed["id"]
    csv_bytes = (
        b"claim_id,provider_id,claim_amount,service_date\r\n"
        b"C001,P100,125.5,15/01/2026\r\n"
        b"C002,P101,450,17/01/2026\r\n"
        b"C003,P100,48,20/01/2026\r\n"
        b"C004,P102,75.25,22/01/2026\r\n"
    )
    files = {"file": ("Aplus_e2e.csv", io.BytesIO(csv_bytes), "text/csv")}

    # 1. Upload sample
    upload_res = client.post(f"/api/v1/feeds/{feed_id}/samples", files=files, headers=analyst_headers)
    assert upload_res.status_code == 201
    sample_id = upload_res.json()["id"]

    # 2. Trigger profiling run
    profile_res = client.post(f"/api/v1/feeds/{feed_id}/samples/{sample_id}/profile", headers=analyst_headers)
    assert profile_res.status_code == 201
    run_id = profile_res.json()["id"]

    # 3. Fetch profiling results from API
    detail_res = client.get(f"/api/v1/profiling-runs/{run_id}", headers=analyst_headers)
    assert detail_res.status_code == 200
    details = detail_res.json()

    assert details["status"] == "COMPLETED"
    assert details["row_count"] == 4
    assert details["column_count"] == 4

    col_map = {c["column_name"]: c for c in details["column_stats"]}

    # Verify claim_amount numeric min/max
    assert col_map["claim_amount"]["inferred_type"] == SchemaDataTypeEnum.DECIMAL
    assert col_map["claim_amount"]["min_value"] == "48"
    assert col_map["claim_amount"]["max_value"] == "450"

    # Verify service_date DD/MM/YYYY date pattern & chronological min/max
    assert col_map["service_date"]["inferred_type"] == SchemaDataTypeEnum.DATE
    assert col_map["service_date"]["min_value"] == "15/01/2026"
    assert col_map["service_date"]["max_value"] == "22/01/2026"
    patterns = [p["pattern"] for p in col_map["service_date"]["detected_date_patterns"]]
    assert "DD/MM/YYYY" in patterns

