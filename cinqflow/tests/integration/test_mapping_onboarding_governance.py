"""Integration tests for Step 4 gating & Feed Activation governance (Slice 3)."""
import io
import uuid
import pytest

def _setup_full_feed(client, engineer_headers, analyst_headers):
    """Creates a feed with sample profiling and published schema contract."""
    feed_name = f"GOV_TEST_FEED_{uuid.uuid4().hex[:6]}"
    f_res = client.post("/api/v1/feeds", json={
        "name": feed_name,
        "domain": "Eligibility",
        "format": "CSV",
        "landing_folder": "./data/landing",
        "filename_pattern": "gov_.*\\.csv",
        "schedule_expression": "0 0 * * *"
    }, headers=engineer_headers)
    assert f_res.status_code == 201
    feed_id = f_res.json()["id"]

    # Step 1 complete
    client.put(f"/api/v1/onboarding/feed/{feed_id}/step", json={"current_step": 1, "mark_step_completed": 1}, headers=analyst_headers)

    # Step 2: Upload sample & profile
    csv_bytes = b"member_id,first_name,last_name,dob,gender\nM001,John,Doe,1980-01-01,M\n"
    s_res = client.post(
        f"/api/v1/feeds/{feed_id}/samples",
        files={"file": ("sample.csv", io.BytesIO(csv_bytes), "text/csv")},
        headers=analyst_headers,
    )
    assert s_res.status_code == 201
    sample_id = s_res.json()["id"]

    p_res = client.post(f"/api/v1/feeds/{feed_id}/samples/{sample_id}/profile", headers=analyst_headers)
    assert p_res.status_code == 201
    run_id = p_res.json()["id"]

    client.put(f"/api/v1/onboarding/feed/{feed_id}/step", json={"current_step": 2, "mark_step_completed": 2}, headers=analyst_headers)

    # Step 3: Schema Contract
    sc_res = client.post("/api/v1/schemas", json={
        "feed_id": feed_id,
        "name": "Gov Schema Contract",
        "source_profiling_run_id": run_id,
    }, headers=analyst_headers)
    assert sc_res.status_code == 201
    schema_id = sc_res.json()["id"]
    version_id = sc_res.json()["draft_version"]["id"]

    client.post(f"/api/v1/schemas/{schema_id}/versions/{version_id}/publish", json={"change_notes": "Gov pub"}, headers=analyst_headers)
    client.put(f"/api/v1/onboarding/feed/{feed_id}/step", json={"current_step": 3, "mark_step_completed": 3}, headers=analyst_headers)

    # Canonical model
    cm_res = client.get("/api/v1/canonical-models", headers=analyst_headers)
    member_cm = next(m for m in cm_res.json() if m["name"] == "Member")
    model_detail = client.get(f"/api/v1/canonical-models/{member_cm['id']}", headers=analyst_headers).json()
    field_map = {f["field_name"]: f["id"] for f in model_detail["fields"]}

    return feed_id, member_cm["id"], field_map

def test_onboarding_step_4_completion_gated(client, engineer_headers, analyst_headers):
    """Step 4 completion is rejected if no mapping exists or if mapping is only DRAFT."""
    feed_id, cm_id, field_map = _setup_full_feed(client, engineer_headers, analyst_headers)

    # Create mapping draft
    m_res = client.post("/api/v1/mappings", json={
        "feed_id": feed_id,
        "canonical_model_id": cm_id
    }, headers=analyst_headers)
    mapping = m_res.json()
    v1_id = mapping["versions"][0]["id"]

    # Still DRAFT -> 400 when attempting to complete Step 4
    res2 = client.put(f"/api/v1/onboarding/feed/{feed_id}/step", json={"current_step": 4, "mark_step_completed": 4}, headers=analyst_headers)
    assert res2.status_code == 400
    assert "draft only" in res2.json()["detail"].lower()

    # Publish mapping
    all_required = [
        {"canonical_field_id": field_map["member_id"], "source_field_names": ["member_id"], "transform_type": "DIRECT"},
        {"canonical_field_id": field_map["first_name"], "source_field_names": ["first_name"], "transform_type": "DIRECT"},
        {"canonical_field_id": field_map["last_name"], "source_field_names": ["last_name"], "transform_type": "DIRECT"},
        {"canonical_field_id": field_map["date_of_birth"], "source_field_names": ["dob"], "transform_type": "DIRECT"},
        {"canonical_field_id": field_map["gender"], "source_field_names": ["gender"], "transform_type": "DIRECT"},
    ]
    client.put(f"/api/v1/mappings/{mapping['id']}/versions/{v1_id}/lines", json={"lines": all_required}, headers=analyst_headers)
    pub_res = client.post(f"/api/v1/mappings/{mapping['id']}/versions/{v1_id}/publish", json={}, headers=analyst_headers)
    assert pub_res.status_code == 200

    # Step 4 completion succeeds now
    res3 = client.put(f"/api/v1/onboarding/feed/{feed_id}/step", json={"current_step": 4, "mark_step_completed": 4}, headers=analyst_headers)
    assert res3.status_code == 200
    assert 4 in res3.json()["completed_steps"]

def test_feed_activation_fails_without_published_mapping(client, engineer_headers, analyst_headers):
    """Feed activation fails if require_mapping is True and mapping is missing or draft."""
    feed_id, cm_id, field_map = _setup_full_feed(client, engineer_headers, analyst_headers)

    # Attempt activation with require_mapping=True when no mapping exists
    act_res = client.put(f"/api/v1/feeds/{feed_id}/status", json={"status": "ACTIVE", "require_mapping": True}, headers=analyst_headers)
    assert act_res.status_code == 400
    assert "mapping" in act_res.json()["detail"].lower()

def test_feed_activation_succeeds_with_published_schema_and_mapping(client, engineer_headers, analyst_headers):
    """Feed activation succeeds when feed metadata, profiling, published schema, and published mapping exist."""
    feed_id, cm_id, field_map = _setup_full_feed(client, engineer_headers, analyst_headers)

    # Create and publish mapping
    m_res = client.post("/api/v1/mappings", json={
        "feed_id": feed_id,
        "canonical_model_id": cm_id
    }, headers=analyst_headers)
    mapping = m_res.json()
    v1_id = mapping["versions"][0]["id"]
    all_required = [
        {"canonical_field_id": field_map["member_id"], "source_field_names": ["member_id"], "transform_type": "DIRECT"},
        {"canonical_field_id": field_map["first_name"], "source_field_names": ["first_name"], "transform_type": "DIRECT"},
        {"canonical_field_id": field_map["last_name"], "source_field_names": ["last_name"], "transform_type": "DIRECT"},
        {"canonical_field_id": field_map["date_of_birth"], "source_field_names": ["dob"], "transform_type": "DIRECT"},
        {"canonical_field_id": field_map["gender"], "source_field_names": ["gender"], "transform_type": "DIRECT"},
    ]
    client.put(f"/api/v1/mappings/{mapping['id']}/versions/{v1_id}/lines", json={"lines": all_required}, headers=analyst_headers)
    pub_res = client.post(f"/api/v1/mappings/{mapping['id']}/versions/{v1_id}/publish", json={}, headers=analyst_headers)
    assert pub_res.status_code == 200

    # Mark Step 4 completed
    client.put(f"/api/v1/onboarding/feed/{feed_id}/step", json={"current_step": 4, "mark_step_completed": 4}, headers=analyst_headers)

    # Activate feed with require_mapping=True
    act_res = client.put(f"/api/v1/feeds/{feed_id}/status", json={"status": "ACTIVE", "require_mapping": True}, headers=analyst_headers)
    assert act_res.status_code == 200
    assert act_res.json()["status"] == "ACTIVE"
