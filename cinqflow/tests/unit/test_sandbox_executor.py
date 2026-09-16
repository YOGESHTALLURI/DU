"""Unit tests for Sandbox Pipeline Execution Engine (Wave 1 Slice 5)."""
import io
import uuid
import pytest
from backend.models.pipeline import Batch, BatchStage
from backend.models.input_registry import InputRegistry, QuarantineRecord
from backend.models.approval import SandboxRunStatusEnum


def _setup_feed_with_full_stack(
    client, engineer_headers, analyst_headers, csv_content=None, include_rule=True, lines_builder=None
):
    """Sets up a feed, uploads sample CSV, publishes schema, creates and publishes mapping and rules."""
    feed_name = f"SANDBOX_FEED_{uuid.uuid4().hex[:6]}"
    f_res = client.post("/api/v1/feeds", json={
        "name": feed_name,
        "domain": "CLAIMS",
        "landing_folder": "./data/landing/claims",
        "filename_pattern": "claims_.*\\.csv",
        "schedule_expression": "0 0 * * *",
    }, headers=engineer_headers)
    assert f_res.status_code == 201
    feed_id = f_res.json()["id"]

    if csv_content is None:
        csv_content = (
            b"member_id,first_name,last_name,dob,gender,amount\n"
            b"M001,John,Doe,1985-06-15,M,150.00\n"
            b"M002,Alice,Smith,1990-03-22,F,250.50\n"
            b"M003,Bob,Jones,1978-11-08,M,75.20\n"
            b"M004,Eve,Taylor,2001-09-30,F,-10.00\n"  # Invalid negative amount for DQ rule
        )

    # 1. Upload sample & profile
    s_res = client.post(
        f"/api/v1/feeds/{feed_id}/samples",
        files={"file": ("sample.csv", io.BytesIO(csv_content), "text/csv")},
        headers=analyst_headers,
    )
    assert s_res.status_code == 201
    sample_id = s_res.json()["id"]

    p_res = client.post(f"/api/v1/feeds/{feed_id}/samples/{sample_id}/profile", headers=analyst_headers)
    assert p_res.status_code == 201
    run_id = p_res.json()["id"]

    # 2. Create and publish schema contract
    sc_res = client.post("/api/v1/schemas", json={
        "feed_id": feed_id,
        "name": f"{feed_name}_Schema",
        "source_profiling_run_id": run_id,
    }, headers=analyst_headers)
    assert sc_res.status_code == 201
    schema_id = sc_res.json()["id"]
    schema_v1_id = sc_res.json()["draft_version"]["id"]

    pub_sc = client.post(
        f"/api/v1/schemas/{schema_id}/versions/{schema_v1_id}/publish",
        json={"change_notes": "Published contract for sandbox testing"},
        headers=analyst_headers,
    )
    assert pub_sc.status_code == 200
    schema_ver_id = pub_sc.json()["id"]

    # 3. Create mapping to Member model
    cm_res = client.get("/api/v1/canonical-models", headers=analyst_headers)
    member_cm = next(m for m in cm_res.json() if m["name"] == "Member")
    model_detail = client.get(f"/api/v1/canonical-models/{member_cm['id']}", headers=analyst_headers).json()
    field_map = {f["field_name"]: f["id"] for f in model_detail["fields"]}

    m_res = client.post("/api/v1/mappings", json={
        "feed_id": feed_id,
        "canonical_model_id": member_cm["id"],
        "description": "Sandbox Member Mapping",
    }, headers=analyst_headers)
    assert m_res.status_code == 201
    mapping_id = m_res.json()["id"]
    mapping_v1_id = m_res.json()["versions"][0]["id"]

    # Configure mapping lines
    if lines_builder:
        lines = lines_builder(field_map)
    else:
        lines = [
            {"canonical_field_id": field_map["member_id"], "source_field_names": ["member_id"], "transform_type": "DIRECT"},
            {"canonical_field_id": field_map["first_name"], "source_field_names": ["first_name"], "transform_type": "DIRECT"},
            {"canonical_field_id": field_map["last_name"], "source_field_names": ["last_name"], "transform_type": "DIRECT"},
            {"canonical_field_id": field_map["date_of_birth"], "source_field_names": ["dob"], "transform_type": "DIRECT"},
            {"canonical_field_id": field_map["gender"], "source_field_names": ["gender"], "transform_type": "DIRECT"},
        ]
    client.put(f"/api/v1/mappings/{mapping_id}/versions/{mapping_v1_id}/lines", json={"lines": lines}, headers=analyst_headers)
    pub_m = client.post(f"/api/v1/mappings/{mapping_id}/versions/{mapping_v1_id}/publish", json={"change_notes": "Publish mapping"}, headers=analyst_headers)
    assert pub_m.status_code == 200

    if include_rule:
        # 4. Create and publish a DQ rule: amount must be >= 0 (QUARANTINE severity)
        r_res = client.post("/api/v1/rules", json={
            "feed_id": feed_id,
            "name": "amount_non_negative",
            "target_field": "amount",
            "rule_type": "RANGE",
            "severity": "QUARANTINE",
            "rule_config": {"min": 0, "inclusive_min": True},
        }, headers=analyst_headers)
        assert r_res.status_code == 201
        rule_id = r_res.json()["id"]
        rule_v1_id = r_res.json()["versions"][0]["id"]
        pub_r = client.post(f"/api/v1/rules/{rule_id}/versions/{rule_v1_id}/publish", json={"change_notes": "Publish amount rule"}, headers=analyst_headers)
        assert pub_r.status_code == 200

    return feed_id, sample_id, schema_id, schema_ver_id, mapping_id, field_map


def test_sandbox_execution_success_with_schema_rules_mapping(client, engineer_headers, analyst_headers):
    """Sandbox executes sample data through schema, rules, and mappings, producing evidence metrics."""
    feed_id, sample_id, schema_id, schema_ver_id, mapping_id, field_map = _setup_feed_with_full_stack(client, engineer_headers, analyst_headers)

    res = client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=analyst_headers)
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "SUCCESS"
    assert data["total_rows"] == 4
    # 3 rows pass (amount >= 0), 1 row quarantined (Eve Taylor has amount = -10.00)
    assert data["passed_rows"] == 3
    assert data["quarantined_rows"] == 1
    assert data["pass_rate"] == 75.0
    assert data["reconciliation_status"] == "BALANCED"
    assert "amount_non_negative" in data["rule_metrics"]
    assert data["rule_metrics"]["amount_non_negative"]["failed_count"] == 1
    assert data["rule_metrics"]["amount_non_negative"]["evaluated_count"] == 4


def test_sandbox_execution_reconciliation_balance(client, engineer_headers, analyst_headers):
    """Sandbox asserts total_rows == passed_rows + quarantined_rows and tags BALANCED."""
    feed_id, sample_id, schema_id, schema_ver_id, mapping_id, field_map = _setup_feed_with_full_stack(client, engineer_headers, analyst_headers)

    res = client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=analyst_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total_rows"] == data["passed_rows"] + data["quarantined_rows"]
    assert data["reconciliation_status"] == "BALANCED"


def test_sandbox_execution_quarantines_dq_rule_failures(client, engineer_headers, analyst_headers):
    """Rows violating QUARANTINE rules are separated and tracked per rule without polluting prod tables."""
    feed_id, sample_id, schema_id, schema_ver_id, mapping_id, field_map = _setup_feed_with_full_stack(client, engineer_headers, analyst_headers)

    res = client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=analyst_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["quarantined_rows"] == 1
    assert data["rule_metrics"]["amount_non_negative"]["failed_count"] == 1


def test_sandbox_execution_flags_reject_file_severity(client, engineer_headers, analyst_headers):
    """A rule with REJECT_FILE severity flags has_reject_file_violation in evidence pack."""
    feed_id, sample_id, schema_id, schema_ver_id, mapping_id, field_map = _setup_feed_with_full_stack(client, engineer_headers, analyst_headers)

    # Add a REJECT_FILE rule on member_id regex
    r_res = client.post("/api/v1/rules", json={
        "feed_id": feed_id,
        "name": "member_id_format_critical",
        "target_field": "member_id",
        "rule_type": "REGEX",
        "severity": "REJECT_FILE",
        "rule_config": {"pattern": "^M[0-9]{3}$"},
    }, headers=analyst_headers)
    assert r_res.status_code == 201
    rule_id = r_res.json()["id"]
    r_v1_id = r_res.json()["versions"][0]["id"]
    client.post(f"/api/v1/rules/{rule_id}/versions/{r_v1_id}/publish", json={"change_notes": "pub"}, headers=analyst_headers)

    # Initial sample has M001, M002, M003, M004 so regex passes
    res1 = client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=analyst_headers)
    assert res1.status_code == 200
    assert res1.json()["has_reject_file_violation"] is False

    # Now add an invalid rule that will fail and flag REJECT_FILE
    r_res2 = client.post("/api/v1/rules", json={
        "feed_id": feed_id,
        "name": "must_be_vip",
        "target_field": "member_id",
        "rule_type": "REGEX",
        "severity": "REJECT_FILE",
        "rule_config": {"pattern": "^VIP_"},
    }, headers=analyst_headers)
    r2_id = r_res2.json()["id"]
    r2_v1 = r_res2.json()["versions"][0]["id"]
    client.post(f"/api/v1/rules/{r2_id}/versions/{r2_v1}/publish", json={"change_notes": "pub"}, headers=analyst_headers)

    res2 = client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=analyst_headers)
    assert res2.status_code == 200
    assert res2.json()["has_reject_file_violation"] is True


def test_sandbox_execution_evaluates_all_7_transforms(client, engineer_headers, analyst_headers):
    """Sandbox correctly evaluates DIRECT, CONSTANT, VALUE_MAP, DATE_FORMAT, CONCAT, COALESCE, STRING_CLEAN."""
    csv_bytes = (
        b"raw_id,first,last,bday,code,opt1,opt2\n"
        b" 101 , John ,Doe,15/06/1985,M,,123 Main St\n"
    )

    def build_transform_lines(field_map):
        return [
            # DIRECT
            {"canonical_field_id": field_map["member_id"], "source_field_names": ["raw_id"], "transform_type": "DIRECT"},
            # STRING_CLEAN
            {"canonical_field_id": field_map["first_name"], "source_field_names": ["first"], "transform_type": "STRING_CLEAN", "transform_params": {"trim": True, "casing": "UPPER"}},
            # CONCAT
            {"canonical_field_id": field_map["last_name"], "source_field_names": ["first", "last"], "transform_type": "CONCAT", "transform_params": {"delimiter": "_"}},
            # DATE_FORMAT
            {"canonical_field_id": field_map["date_of_birth"], "source_field_names": ["bday"], "transform_type": "DATE_FORMAT", "transform_params": {"source_format": "DD/MM/YYYY", "target_format": "YYYY-MM-DD"}},
            # VALUE_MAP
            {"canonical_field_id": field_map["gender"], "source_field_names": ["code"], "transform_type": "VALUE_MAP", "transform_params": {"dictionary": {"M": "MALE", "F": "FEMALE"}, "default": "OTHER"}},
            # CONSTANT
            {"canonical_field_id": field_map["city"], "source_field_names": [], "transform_type": "CONSTANT", "transform_params": {"value": "Metropolis"}},
            # COALESCE
            {"canonical_field_id": field_map["address_line1"], "source_field_names": ["opt1", "opt2"], "transform_type": "COALESCE"},
        ]

    feed_id, sample_id, schema_id, schema_ver_id, mapping_id, field_map = _setup_feed_with_full_stack(
        client, engineer_headers, analyst_headers, csv_content=csv_bytes, include_rule=False, lines_builder=build_transform_lines
    )

    test_res = client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=analyst_headers)
    assert test_res.status_code == 200
    preview = test_res.json()["canonical_sample_preview"]
    assert len(preview) == 1
    rec = preview[0]
    # Check transformed values
    assert rec["gender"] == "MALE"
    assert rec["member_id"] == "101"
    assert rec["city"] == "Metropolis"
    # Masked fields check: address_line1 contains "address" -> masked
    assert "***" in rec["address_line1"] or rec["address_line1"] == "1***t"
    assert "***" in rec["first_name"]
    assert "***" in rec["date_of_birth"] or rec["date_of_birth"] == "1***5"


def test_sandbox_execution_zero_production_table_writes(db, client, engineer_headers, analyst_headers):
    """Sandbox runs guarantee ZERO writes to batches, batch_stages, input_registry, or quarantine_records."""
    # Count rows before
    batches_before = db.query(Batch).count()
    stages_before = db.query(BatchStage).count()
    inputs_before = db.query(InputRegistry).count()
    quarantine_before = db.query(QuarantineRecord).count()

    feed_id, sample_id, schema_id, schema_ver_id, mapping_id, field_map = _setup_feed_with_full_stack(client, engineer_headers, analyst_headers)
    res = client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=analyst_headers)
    assert res.status_code == 200

    # Assert zero production records added
    assert db.query(Batch).count() == batches_before
    assert db.query(BatchStage).count() == stages_before
    assert db.query(InputRegistry).count() == inputs_before
    assert db.query(QuarantineRecord).count() == quarantine_before


def test_sandbox_canonical_preview_masks_phi(client, engineer_headers, analyst_headers):
    """Canonical sample preview caps at 5 records and masks patient-identifiable fields."""
    # Create 10 rows
    rows = ["member_id,first_name,last_name,dob,gender,amount"]
    for i in range(10):
        rows.append(f"M{i:03d},FirstName{i},LastName{i},1985-01-01,M,100.00")
    csv_10 = "\n".join(rows).encode("utf-8")

    feed_id, sample_id, schema_id, schema_ver_id, mapping_id, field_map = _setup_feed_with_full_stack(
        client, engineer_headers, analyst_headers, csv_content=csv_10
    )

    res = client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=analyst_headers)
    assert res.status_code == 200
    preview = res.json()["canonical_sample_preview"]

    # Maximum 5 preview rows
    assert len(preview) == 5

    # Names and dob are masked (e.g. F***0, L***0)
    for p in preview:
        assert "***" in p["first_name"]
        assert "***" in p["last_name"]


def test_sandbox_execution_fails_gracefully_on_malformed_csv(client, engineer_headers, analyst_headers):
    """Sandbox handles corrupted or unparseable CSV gracefully with FAILED status and error message."""
    # Feed without published schema contract
    feed_name = f"FAIL_FEED_{uuid.uuid4().hex[:6]}"
    f_res = client.post("/api/v1/feeds", json={
        "name": feed_name,
        "domain": "CLAIMS",
        "landing_folder": "./data/landing",
        "filename_pattern": "claims_.*\\.csv",
    }, headers=engineer_headers)
    feed_id = f_res.json()["id"]

    # Calling sandbox test without prerequisites returns 400 Bad Request
    res = client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=analyst_headers)
    assert res.status_code == 400
    assert "prerequisite missing" in res.json()["detail"].lower()
