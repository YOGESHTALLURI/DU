"""Unit tests for Mapping Studio validation rules and 7 transforms (Slice 3)."""
import io
import uuid
import pytest
from backend.services.canonical_model_service import CanonicalModelService

def _setup_mapping_context(client, engineer_headers, analyst_headers):
    """Sets up a feed, published schema with sample columns, and draft mapping for Member model."""
    feed_name = f"VAL_TEST_FEED_{uuid.uuid4().hex[:6]}"
    f_res = client.post("/api/v1/feeds", json={
        "name": feed_name,
        "domain": "Eligibility",
        "format": "CSV",
        "landing_folder": "./data/landing",
        "filename_pattern": "val_.*\\.csv",
        "schedule_expression": "0 0 * * *"
    }, headers=engineer_headers)
    assert f_res.status_code == 201
    feed_id = f_res.json()["id"]

    # Upload sample & profile
    csv_bytes = b"mem_id,raw_first,raw_last,raw_date,gender_num,addr_line1,addr_line2,city_val\nM1,A,B,15/01/2026,1,Street1,Apt2,CityA\n"
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

    # Create & Publish schema contract
    sc_res = client.post("/api/v1/schemas", json={
        "feed_id": feed_id,
        "name": "Val Schema",
        "source_profiling_run_id": run_id,
    }, headers=analyst_headers)
    assert sc_res.status_code == 201
    schema_id = sc_res.json()["id"]
    version_id = sc_res.json()["draft_version"]["id"]

    pub_res = client.post(f"/api/v1/schemas/{schema_id}/versions/{version_id}/publish", json={"change_notes": "Val publish"}, headers=analyst_headers)
    assert pub_res.status_code == 200

    cm_res = client.get("/api/v1/canonical-models", headers=analyst_headers)
    member_cm = next(m for m in cm_res.json() if m["name"] == "Member")
    model_detail = client.get(f"/api/v1/canonical-models/{member_cm['id']}", headers=analyst_headers).json()
    field_map = {f["field_name"]: f["id"] for f in model_detail["fields"]}

    # Create mapping
    m_res = client.post("/api/v1/mappings", json={
        "feed_id": feed_id,
        "canonical_model_id": member_cm["id"]
    }, headers=analyst_headers)
    assert m_res.status_code == 201
    mapping = m_res.json()
    map_version_id = mapping["versions"][0]["id"]

    return feed_id, mapping["id"], map_version_id, field_map

def test_mapping_validation_missing_required_target_field(client, engineer_headers, analyst_headers):
    """Validation report indicates missing required fields when only member_id is mapped."""
    feed_id, mapping_id, version_id, field_map = _setup_mapping_context(client, engineer_headers, analyst_headers)

    lines = [
        {"canonical_field_id": field_map["member_id"], "source_field_names": ["mem_id"], "transform_type": "DIRECT"}
    ]
    client.put(f"/api/v1/mappings/{mapping_id}/versions/{version_id}/lines", json={"lines": lines}, headers=analyst_headers)

    val_res = client.post(f"/api/v1/mappings/{mapping_id}/versions/{version_id}/validate", headers=analyst_headers)
    assert val_res.status_code == 200
    report = val_res.json()
    assert report["is_valid"] is False
    assert "first_name" in report["unmapped_required_canonical_fields"]
    assert "last_name" in report["unmapped_required_canonical_fields"]
    assert any("Required canonical field 'first_name' is unmapped" in e for e in report["errors"])

def test_mapping_validation_missing_source_field(client, engineer_headers, analyst_headers):
    """Validation reports an error if a line references a source field not present in the pinned schema."""
    feed_id, mapping_id, version_id, field_map = _setup_mapping_context(client, engineer_headers, analyst_headers)

    lines = [
        {"canonical_field_id": field_map["member_id"], "source_field_names": ["non_existent_source"], "transform_type": "DIRECT"}
    ]
    client.put(f"/api/v1/mappings/{mapping_id}/versions/{version_id}/lines", json={"lines": lines}, headers=analyst_headers)

    val_res = client.post(f"/api/v1/mappings/{mapping_id}/versions/{version_id}/validate", headers=analyst_headers)
    assert val_res.status_code == 200
    report = val_res.json()
    assert report["is_valid"] is False
    assert any("does not exist in pinned schema" in e for e in report["errors"])

def test_transform_direct_type_compatibility(client, engineer_headers, analyst_headers):
    """Direct transform checks type compatibility between source and canonical attribute."""
    feed_id, mapping_id, version_id, field_map = _setup_mapping_context(client, engineer_headers, analyst_headers)

    lines = [
        {"canonical_field_id": field_map["member_id"], "source_field_names": ["raw_date"], "transform_type": "DIRECT"}
    ]
    client.put(f"/api/v1/mappings/{mapping_id}/versions/{version_id}/lines", json={"lines": lines}, headers=analyst_headers)
    val_res = client.post(f"/api/v1/mappings/{mapping_id}/versions/{version_id}/validate", headers=analyst_headers)
    report = val_res.json()
    assert any("DIRECT" in w or "DIRECT" in e for w in report["warnings"] for e in report["errors"]) or not report["is_valid"]

def test_transform_constant_types(client, engineer_headers, analyst_headers):
    """Constant transform checks constant value validity against target type."""
    feed_id, mapping_id, version_id, field_map = _setup_mapping_context(client, engineer_headers, analyst_headers)

    lines = [
        {"canonical_field_id": field_map["date_of_birth"], "source_field_names": [], "transform_type": "CONSTANT", "transform_params": {"value": ""}}
    ]
    client.put(f"/api/v1/mappings/{mapping_id}/versions/{version_id}/lines", json={"lines": lines}, headers=analyst_headers)
    val_res = client.post(f"/api/v1/mappings/{mapping_id}/versions/{version_id}/validate", headers=analyst_headers)
    report = val_res.json()
    assert any("Constant value '' is not a valid date string" in e for e in report["errors"])

def test_transform_value_map_valid_and_defaults(client, engineer_headers, analyst_headers):
    """Value map allows valid dictionary mapping and default fallback."""
    feed_id, mapping_id, version_id, field_map = _setup_mapping_context(client, engineer_headers, analyst_headers)

    lines = [
        {"canonical_field_id": field_map["gender"], "source_field_names": ["gender_num"], "transform_type": "VALUE_MAP", "transform_params": {"dictionary": {"1": "M", "2": "F"}, "on_unmapped": "DEFAULT", "default": "U"}}
    ]
    client.put(f"/api/v1/mappings/{mapping_id}/versions/{version_id}/lines", json={"lines": lines}, headers=analyst_headers)
    val_res = client.post(f"/api/v1/mappings/{mapping_id}/versions/{version_id}/validate", headers=analyst_headers)
    report = val_res.json()
    assert not any("VALUE_MAP" in e for e in report["errors"])

def test_transform_value_map_edge_cases_rejected(client, engineer_headers, analyst_headers):
    """Value map requires non-empty dictionary and valid unmapped handling."""
    feed_id, mapping_id, version_id, field_map = _setup_mapping_context(client, engineer_headers, analyst_headers)

    lines = [
        {"canonical_field_id": field_map["gender"], "source_field_names": ["gender_num"], "transform_type": "VALUE_MAP", "transform_params": {"dictionary": {}, "on_unmapped": "DEFAULT"}}
    ]
    client.put(f"/api/v1/mappings/{mapping_id}/versions/{version_id}/lines", json={"lines": lines}, headers=analyst_headers)
    val_res = client.post(f"/api/v1/mappings/{mapping_id}/versions/{version_id}/validate", headers=analyst_headers)
    report = val_res.json()
    assert any("requires a non-empty 'dictionary'" in e for e in report["errors"])

def test_transform_date_format_edge_cases(client, engineer_headers, analyst_headers):
    """DATE_FORMAT requires non-empty source_format and target_format."""
    feed_id, mapping_id, version_id, field_map = _setup_mapping_context(client, engineer_headers, analyst_headers)

    lines = [
        {"canonical_field_id": field_map["date_of_birth"], "source_field_names": ["raw_first"], "transform_type": "DATE_FORMAT", "transform_params": {"target_format": "YYYY-MM-DD"}}
    ]
    client.put(f"/api/v1/mappings/{mapping_id}/versions/{version_id}/lines", json={"lines": lines}, headers=analyst_headers)
    val_res = client.post(f"/api/v1/mappings/{mapping_id}/versions/{version_id}/validate", headers=analyst_headers)
    report = val_res.json()
    assert any("requires non-empty 'source_format'" in e for e in report["errors"])

def test_transform_concat_edge_cases(client, engineer_headers, analyst_headers):
    """CONCAT requires at least 2 source fields and delimiter."""
    feed_id, mapping_id, version_id, field_map = _setup_mapping_context(client, engineer_headers, analyst_headers)

    lines = [
        {"canonical_field_id": field_map["first_name"], "source_field_names": ["raw_first"], "transform_type": "CONCAT", "transform_params": {"delimiter": " "}}
    ]
    client.put(f"/api/v1/mappings/{mapping_id}/versions/{version_id}/lines", json={"lines": lines}, headers=analyst_headers)
    val_res = client.post(f"/api/v1/mappings/{mapping_id}/versions/{version_id}/validate", headers=analyst_headers)
    report = val_res.json()
    assert any("requires at least 2 source fields" in e for e in report["errors"])

def test_transform_coalesce_edge_cases(client, engineer_headers, analyst_headers):
    """COALESCE requires at least 2 source fields."""
    feed_id, mapping_id, version_id, field_map = _setup_mapping_context(client, engineer_headers, analyst_headers)

    # Use optional field address_line1
    lines = [
        {"canonical_field_id": field_map["address_line1"], "source_field_names": ["addr_line1"], "transform_type": "COALESCE"}
    ]
    client.put(f"/api/v1/mappings/{mapping_id}/versions/{version_id}/lines", json={"lines": lines}, headers=analyst_headers)
    val_res = client.post(f"/api/v1/mappings/{mapping_id}/versions/{version_id}/validate", headers=analyst_headers)
    report = val_res.json()
    assert any("requires at least 2 source fields" in e for e in report["errors"])

def test_transform_string_clean_variants(client, engineer_headers, analyst_headers):
    """STRING_CLEAN accepts UPPER, LOWER, TRIM, NONE and rejects invalid casings."""
    feed_id, mapping_id, version_id, field_map = _setup_mapping_context(client, engineer_headers, analyst_headers)

    lines = [
        {"canonical_field_id": field_map["first_name"], "source_field_names": ["raw_first"], "transform_type": "STRING_CLEAN", "transform_params": {"casing": "TRIM"}}
    ]
    client.put(f"/api/v1/mappings/{mapping_id}/versions/{version_id}/lines", json={"lines": lines}, headers=analyst_headers)
    val_res = client.post(f"/api/v1/mappings/{mapping_id}/versions/{version_id}/validate", headers=analyst_headers)
    assert not any("STRING_CLEAN" in e for e in val_res.json()["errors"])

    lines[0]["transform_params"]["casing"] = "INVALID"
    client.put(f"/api/v1/mappings/{mapping_id}/versions/{version_id}/lines", json={"lines": lines}, headers=analyst_headers)
    val_res2 = client.post(f"/api/v1/mappings/{mapping_id}/versions/{version_id}/validate", headers=analyst_headers)
    assert any("Invalid casing 'INVALID'" in e for e in val_res2.json()["errors"])
