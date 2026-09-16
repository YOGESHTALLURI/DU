"""Integration tests for Mapping Lifecycle, RBAC, Immutability & Audit (Slice 3)."""
import io
import uuid
import pytest

def _setup_feed_and_schema(client, engineer_headers, analyst_headers):
    """Helper to create a feed and publish a schema contract."""
    feed_name = f"MAP_LIFECYCLE_FEED_{uuid.uuid4().hex[:6]}"
    f_res = client.post("/api/v1/feeds", json={
        "name": feed_name,
        "domain": "Eligibility",
        "format": "CSV",
        "landing_folder": "./data/landing",
        "filename_pattern": "mapping_.*\\.csv",
        "schedule_expression": "0 0 * * *"
    }, headers=engineer_headers)
    assert f_res.status_code == 201
    feed_id = f_res.json()["id"]

    # Upload sample & profile
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

    # Create schema contract
    sc_res = client.post("/api/v1/schemas", json={
        "feed_id": feed_id,
        "name": "Mapping Schema Contract",
        "source_profiling_run_id": run_id,
    }, headers=analyst_headers)
    assert sc_res.status_code == 201
    schema_id = sc_res.json()["id"]
    version_id = sc_res.json()["draft_version"]["id"]

    # Publish schema contract
    pub_schema = client.post(f"/api/v1/schemas/{schema_id}/versions/{version_id}/publish", json={"change_notes": "Pub v1"}, headers=analyst_headers)
    assert pub_schema.status_code == 200
    schema_version_id = pub_schema.json()["id"]

    # Get canonical model Member
    cm_res = client.get("/api/v1/canonical-models", headers=analyst_headers)
    member_cm = next(m for m in cm_res.json() if m["name"] == "Member")
    model_detail = client.get(f"/api/v1/canonical-models/{member_cm['id']}", headers=analyst_headers).json()
    field_map = {f["field_name"]: f["id"] for f in model_detail["fields"]}

    return feed_id, schema_id, schema_version_id, member_cm["id"], field_map

def test_mapping_create_and_unique_constraint(client, engineer_headers, analyst_headers):
    """Creating a mapping initializes v1 DRAFT and pins schema_version_id; duplicate model is rejected."""
    feed_id, schema_id, schema_version_id, canonical_model_id, field_map = _setup_feed_and_schema(client, engineer_headers, analyst_headers)

    create_res = client.post("/api/v1/mappings", json={
        "feed_id": feed_id,
        "canonical_model_id": canonical_model_id,
        "description": "Member mapping v1"
    }, headers=analyst_headers)
    assert create_res.status_code == 201
    data = create_res.json()
    assert data["feed_id"] == feed_id
    assert data["canonical_model_id"] == canonical_model_id
    assert len(data["versions"]) == 1
    v1 = data["versions"][0]
    assert v1["version_number"] == 1
    assert v1["status"] == "DRAFT"
    assert v1["schema_version_id"] == schema_version_id

    # Duplicate mapping for same (feed_id, canonical_model_id) must be rejected 400
    dup_res = client.post("/api/v1/mappings", json={
        "feed_id": feed_id,
        "canonical_model_id": canonical_model_id,
    }, headers=analyst_headers)
    assert dup_res.status_code == 400
    assert "already exists" in dup_res.json()["detail"]

def test_mapping_draft_lines_update(client, engineer_headers, analyst_headers):
    """Updating mapping lines in DRAFT calculates valid lines and saves configuration."""
    feed_id, schema_id, schema_version_id, canonical_model_id, field_map = _setup_feed_and_schema(client, engineer_headers, analyst_headers)
    m_res = client.post("/api/v1/mappings", json={
        "feed_id": feed_id,
        "canonical_model_id": canonical_model_id,
    }, headers=analyst_headers)
    mapping = m_res.json()
    v1_id = mapping["versions"][0]["id"]

    update_lines = [
        {"canonical_field_id": field_map["member_id"], "source_field_names": ["member_id"], "transform_type": "DIRECT"},
        {"canonical_field_id": field_map["first_name"], "source_field_names": ["first_name"], "transform_type": "DIRECT"},
        {"canonical_field_id": field_map["last_name"], "source_field_names": ["last_name"], "transform_type": "DIRECT"},
    ]
    put_res = client.put(f"/api/v1/mappings/{mapping['id']}/versions/{v1_id}/lines", json={"lines": update_lines}, headers=analyst_headers)
    assert put_res.status_code == 200
    saved_detail = put_res.json()
    mem_line = next(l for l in saved_detail["lines"] if l["canonical_field_name"] == "member_id")
    assert mem_line["transform_type"] == "DIRECT"
    assert mem_line["source_field_names"] == ["member_id"]

def test_mapping_publish_locks_immutability(client, engineer_headers, analyst_headers):
    """Publishing a valid mapping version locks it as PUBLISHED; subsequent edits return 400."""
    feed_id, schema_id, schema_version_id, canonical_model_id, field_map = _setup_feed_and_schema(client, engineer_headers, analyst_headers)
    m_res = client.post("/api/v1/mappings", json={
        "feed_id": feed_id,
        "canonical_model_id": canonical_model_id,
    }, headers=analyst_headers)
    mapping = m_res.json()
    v1_id = mapping["versions"][0]["id"]

    # Try publish without required fields mapped -> 400
    bad_pub = client.post(f"/api/v1/mappings/{mapping['id']}/versions/{v1_id}/publish", json={}, headers=analyst_headers)
    assert bad_pub.status_code == 400
    assert "cannot publish mapping" in bad_pub.json()["detail"].lower()

    # Map all 5 required Member fields (member_id, first_name, last_name, date_of_birth, gender)
    all_required = [
        {"canonical_field_id": field_map["member_id"], "source_field_names": ["member_id"], "transform_type": "DIRECT"},
        {"canonical_field_id": field_map["first_name"], "source_field_names": ["first_name"], "transform_type": "DIRECT"},
        {"canonical_field_id": field_map["last_name"], "source_field_names": ["last_name"], "transform_type": "DIRECT"},
        {"canonical_field_id": field_map["date_of_birth"], "source_field_names": ["dob"], "transform_type": "DIRECT"},
        {"canonical_field_id": field_map["gender"], "source_field_names": ["gender"], "transform_type": "DIRECT"},
    ]
    client.put(f"/api/v1/mappings/{mapping['id']}/versions/{v1_id}/lines", json={"lines": all_required}, headers=analyst_headers)

    # Publish succeeds
    pub_res = client.post(f"/api/v1/mappings/{mapping['id']}/versions/{v1_id}/publish", json={"change_notes": "Initial publish"}, headers=analyst_headers)
    assert pub_res.status_code == 200
    pub_data = pub_res.json()
    assert pub_data["status"] == "PUBLISHED"
    assert pub_data["compiled_spec"] is not None

    # Subsequent edit on PUBLISHED version fails 400
    edit_res = client.put(f"/api/v1/mappings/{mapping['id']}/versions/{v1_id}/lines", json={"lines": all_required}, headers=analyst_headers)
    assert edit_res.status_code == 400
    assert "strictly immutable" in edit_res.json()["detail"].lower() or "cannot modify" in edit_res.json()["detail"].lower()

def test_mapping_spawn_new_version(client, engineer_headers, analyst_headers):
    """POST /api/v1/mappings/{id}/versions spawns independent v2 DRAFT inheriting v1 lines without mutating v1."""
    feed_id, schema_id, schema_version_id, canonical_model_id, field_map = _setup_feed_and_schema(client, engineer_headers, analyst_headers)
    m_res = client.post("/api/v1/mappings", json={
        "feed_id": feed_id,
        "canonical_model_id": canonical_model_id,
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

    # Spawn v2
    spawn_res = client.post(f"/api/v1/mappings/{mapping['id']}/versions", json={
        "change_notes": "v2 adjustments"
    }, headers=analyst_headers)
    assert spawn_res.status_code == 201
    v2 = spawn_res.json()
    assert v2["version_number"] == 2
    assert v2["status"] == "DRAFT"
    assert v2["id"] != v1_id
    assert len(v2["lines"]) == 5

    # Editing v2 succeeds while v1 remains PUBLISHED and untouched
    v2_update = all_required + [
        {"canonical_field_id": field_map["address_line1"], "source_field_names": [], "transform_type": "CONSTANT", "transform_params": {"value": "UNKNOWN"}}
    ]
    edit_v2 = client.put(f"/api/v1/mappings/{mapping['id']}/versions/{v2['id']}/lines", json={"lines": v2_update}, headers=analyst_headers)
    assert edit_v2.status_code == 200

    # Verify v1 is still published
    v1_check = client.get(f"/api/v1/mappings/{mapping['id']}/versions/{v1_id}", headers=analyst_headers)
    assert v1_check.status_code == 200
    assert v1_check.json()["status"] == "PUBLISHED"

def test_mapping_rbac_read_only_forbidden(client, engineer_headers, analyst_headers, readonly_headers):
    """READ_ONLY role receives 403 on all mapping create/update/publish/spawn mutations."""
    feed_id, schema_id, schema_version_id, canonical_model_id, field_map = _setup_feed_and_schema(client, engineer_headers, analyst_headers)

    # READ_ONLY cannot create mapping
    c_res = client.post("/api/v1/mappings", json={
        "feed_id": feed_id,
        "canonical_model_id": canonical_model_id,
    }, headers=readonly_headers)
    assert c_res.status_code == 403

    # Create mapping as analyst
    m_res = client.post("/api/v1/mappings", json={
        "feed_id": feed_id,
        "canonical_model_id": canonical_model_id,
    }, headers=analyst_headers)
    mapping = m_res.json()
    v1_id = mapping["versions"][0]["id"]

    # READ_ONLY cannot update lines
    u_res = client.put(f"/api/v1/mappings/{mapping['id']}/versions/{v1_id}/lines", json={"lines": []}, headers=readonly_headers)
    assert u_res.status_code == 403

    # READ_ONLY cannot publish
    p_res = client.post(f"/api/v1/mappings/{mapping['id']}/versions/{v1_id}/publish", json={}, headers=readonly_headers)
    assert p_res.status_code == 403

    # READ_ONLY cannot spawn version
    s_res = client.post(f"/api/v1/mappings/{mapping['id']}/versions", json={}, headers=readonly_headers)
    assert s_res.status_code == 403

def test_mapping_audit_events_emitted(client, engineer_headers, analyst_headers):
    """Audit events (mapping.created, mapping.draft_updated, mapping.published) are emitted."""
    feed_id, schema_id, schema_version_id, canonical_model_id, field_map = _setup_feed_and_schema(client, engineer_headers, analyst_headers)
    m_res = client.post("/api/v1/mappings", json={
        "feed_id": feed_id,
        "canonical_model_id": canonical_model_id,
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

    audit_res = client.get("/api/v1/audit/events?limit=50", headers=analyst_headers)
    assert audit_res.status_code == 200
    events = audit_res.json()
    actions = [e["action"] for e in events]
    assert "mapping.created" in actions
    assert "mapping.draft_updated" in actions
    assert "mapping.published" in actions
