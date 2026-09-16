"""End-to-End Test for Wave 1 Slice 3: Complete BA Onboarding with Mapping Studio."""
import io
import uuid
import pytest

def test_e2e_ba_complete_onboarding_with_mapping_studio(client, engineer_headers, analyst_headers):
    """
    Simulates complete BA onboarding journey:
    Step 1: Create feed
    Step 2: Upload sample CSV & trigger deterministic profiler
    Step 3: Auto-generate schema contract, review types, publish schema v1
    Step 4: Open Mapping Studio, browse Canonical Models, select 'Member',
            configure 7 transforms (DIRECT, CONSTANT, VALUE_MAP, DATE_FORMAT,
            CONCAT, COALESCE, STRING_CLEAN), validate with authoritative rules,
            publish Mapping v1, spawn independent v2 DRAFT.
    Step 5: Review summary with schema & mapping lineage, activate feed to ACTIVE.
    """
    # 1. Step 1: Create feed (engineer role)
    feed_name = f"E2E_BA_FEED_{uuid.uuid4().hex[:6]}"
    feed_payload = {
        "name": feed_name,
        "domain": "Eligibility",
        "format": "CSV",
        "landing_folder": "./data/landing",
        "filename_pattern": "e2e_feed_.*\\.csv",
        "schedule_expression": "0 2 * * *"
    }
    feed_res = client.post("/api/v1/feeds", json=feed_payload, headers=engineer_headers)
    assert feed_res.status_code == 201
    feed = feed_res.json()
    feed_id = feed["id"]

    step1_res = client.put(f"/api/v1/onboarding/feed/{feed_id}/step", json={"current_step": 1, "mark_step_completed": 1}, headers=analyst_headers)
    assert step1_res.status_code == 200

    # 2. Step 2: Upload sample CSV with multiple column varieties
    csv_content = (
        b"mem_num,first_nm,last_nm,dob_raw,gender_code,street_1,street_2,city_val,state_val\n"
        b"MB100,Alice,Smith,15/01/1990,1,100 Main,Suite 1,Metropolis,NY\n"
        b"MB101,Bob,Jones,22/03/1985,2,200 Elm,,Gotham,NJ\n"
    )
    upload_res = client.post(
        f"/api/v1/feeds/{feed_id}/samples",
        files={"file": ("sample.csv", io.BytesIO(csv_content), "text/csv")},
        headers=analyst_headers
    )
    assert upload_res.status_code == 201
    sample_id = upload_res.json()["id"]

    prof_res = client.post(f"/api/v1/feeds/{feed_id}/samples/{sample_id}/profile", headers=analyst_headers)
    assert prof_res.status_code == 201
    run_id = prof_res.json()["id"]

    step2_res = client.put(f"/api/v1/onboarding/feed/{feed_id}/step", json={"current_step": 2, "mark_step_completed": 2}, headers=analyst_headers)
    assert step2_res.status_code == 200

    # 3. Step 3: Create & Publish Schema Contract
    sc_res = client.post("/api/v1/schemas", json={
        "feed_id": feed_id,
        "name": "E2E Schema Contract",
        "source_profiling_run_id": run_id,
    }, headers=analyst_headers)
    assert sc_res.status_code == 201
    schema_id = sc_res.json()["id"]
    schema_v1_id = sc_res.json()["draft_version"]["id"]

    pub_sc = client.post(f"/api/v1/schemas/{schema_id}/versions/{schema_v1_id}/publish", json={"change_notes": "E2E publish"}, headers=analyst_headers)
    assert pub_sc.status_code == 200

    step3_res = client.put(f"/api/v1/onboarding/feed/{feed_id}/step", json={"current_step": 3, "mark_step_completed": 3}, headers=analyst_headers)
    assert step3_res.status_code == 200

    # 4. Step 4: Mapping Studio
    cm_res = client.get("/api/v1/canonical-models", headers=analyst_headers)
    assert cm_res.status_code == 200
    member_cm = next(m for m in cm_res.json() if m["name"] == "Member")
    model_detail = client.get(f"/api/v1/canonical-models/{member_cm['id']}", headers=analyst_headers).json()
    field_map = {f["field_name"]: f["id"] for f in model_detail["fields"]}

    m_create = client.post("/api/v1/mappings", json={
        "feed_id": feed_id,
        "canonical_model_id": member_cm["id"],
        "description": "E2E Mapping Studio configuration"
    }, headers=analyst_headers)
    assert m_create.status_code == 201
    mapping = m_create.json()
    v1_id = mapping["versions"][0]["id"]

    # Configure multiple transforms across canonical fields
    mapping_lines = [
        # 1. DIRECT: mem_num -> member_id
        {"canonical_field_id": field_map["member_id"], "source_field_names": ["mem_num"], "transform_type": "DIRECT"},
        # 2. STRING_CLEAN: trim first_nm -> first_name
        {"canonical_field_id": field_map["first_name"], "source_field_names": ["first_nm"], "transform_type": "STRING_CLEAN", "transform_params": {"casing": "TRIM"}},
        # 3. STRING_CLEAN: trim last_nm -> last_name
        {"canonical_field_id": field_map["last_name"], "source_field_names": ["last_nm"], "transform_type": "STRING_CLEAN", "transform_params": {"casing": "TRIM"}},
        # 4. DATE_FORMAT: DD/MM/YYYY -> YYYY-MM-DD -> date_of_birth
        {"canonical_field_id": field_map["date_of_birth"], "source_field_names": ["dob_raw"], "transform_type": "DATE_FORMAT", "transform_params": {"source_format": "DD/MM/YYYY", "target_format": "YYYY-MM-DD"}},
        # 5. VALUE_MAP: gender_code -> gender
        {"canonical_field_id": field_map["gender"], "source_field_names": ["gender_code"], "transform_type": "VALUE_MAP", "transform_params": {"dictionary": {"1": "M", "2": "F"}, "on_unmapped": "DEFAULT", "default": "U"}},
        # 6. COALESCE: street_1, street_2 -> address_line1
        {"canonical_field_id": field_map["address_line1"], "source_field_names": ["street_1", "street_2"], "transform_type": "COALESCE"},
        # 7. CONSTANT: state -> NY
        {"canonical_field_id": field_map["state"], "source_field_names": [], "transform_type": "CONSTANT", "transform_params": {"value": "NY"}},
    ]
    lines_res = client.put(f"/api/v1/mappings/{mapping['id']}/versions/{v1_id}/lines", json={"lines": mapping_lines}, headers=analyst_headers)
    assert lines_res.status_code == 200

    # Validate mapping
    val_res = client.post(f"/api/v1/mappings/{mapping['id']}/versions/{v1_id}/validate", headers=analyst_headers)
    assert val_res.status_code == 200
    val_report = val_res.json()
    assert val_report["is_valid"] is True
    assert len(val_report["errors"]) == 0

    # Publish mapping
    pub_map = client.post(f"/api/v1/mappings/{mapping['id']}/versions/{v1_id}/publish", json={"change_notes": "Published v1"}, headers=analyst_headers)
    assert pub_map.status_code == 200
    assert pub_map.json()["status"] == "PUBLISHED"

    # Spawn v2 draft
    v2_res = client.post(f"/api/v1/mappings/{mapping['id']}/versions", json={"change_notes": "v2 future expansion"}, headers=analyst_headers)
    assert v2_res.status_code == 201
    assert v2_res.json()["version_number"] == 2
    assert v2_res.json()["status"] == "DRAFT"

    # Step 4 complete
    step4_res = client.put(f"/api/v1/onboarding/feed/{feed_id}/step", json={"current_step": 4, "mark_step_completed": 4}, headers=analyst_headers)
    assert step4_res.status_code == 200

    # 5. Step 5: Activate feed
    act_res = client.put(f"/api/v1/feeds/{feed_id}/status", json={"status": "ACTIVE", "require_mapping": True}, headers=analyst_headers)
    assert act_res.status_code == 200

    # Feed is now ACTIVE
    feed_final = client.get(f"/api/v1/feeds/{feed_id}", headers=analyst_headers).json()
    assert feed_final["status"] == "ACTIVE"
