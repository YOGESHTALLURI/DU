"""
Integration Tests for Data Quality Rule Lifecycle — Wave 1 Slice 4
3 tests covering:
1. test_rule_full_lifecycle_create_validate_test_publish
2. test_rule_versioning_spawn_and_isolation
3. test_rule_schema_pinning_on_version_spawn
"""
import uuid
import pytest
from backend.models.feed import Feed, FeedFormatEnum
from backend.models.schema import Schema, SchemaVersion, SchemaField, SchemaVersionStatusEnum, SchemaDataTypeEnum, SampleFile
from backend.models.rule import RuleVersionStatusEnum, RuleTypeEnum, RuleSeverityEnum
from backend.adapters.storage import get_storage_adapter


@pytest.fixture
def setup_lifecycle_data(db):
    storage = get_storage_adapter()
    feed = Feed(
        id=uuid.uuid4(),
        name=f"Feed_Lifecycle_{uuid.uuid4().hex[:6]}",
        domain="CLAIMS",
        format=FeedFormatEnum.CSV,
        landing_folder="claims/lifecycle",
        filename_pattern="claims_*.csv",
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(feed)
    db.flush()

    schema = Schema(
        id=uuid.uuid4(),
        feed_id=feed.id,
        name=f"{feed.name}_Schema",
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(schema)
    db.flush()

    schema_v1 = SchemaVersion(
        id=uuid.uuid4(),
        schema_id=schema.id,
        version_number=1,
        status=SchemaVersionStatusEnum.PUBLISHED,
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(schema_v1)
    db.flush()

    fields_v1 = [
        SchemaField(id=uuid.uuid4(), schema_version_id=schema_v1.id, field_name="claim_id", data_type=SchemaDataTypeEnum.STRING, ordinal_position=1, created_by="engineer", updated_by="engineer"),
        SchemaField(id=uuid.uuid4(), schema_version_id=schema_v1.id, field_name="amount", data_type=SchemaDataTypeEnum.DECIMAL, ordinal_position=2, created_by="engineer", updated_by="engineer"),
    ]
    db.add_all(fields_v1)
    db.flush()

    csv_data = b"claim_id,amount\nCLM-01,100\nCLM-02,200\n"
    storage_path = f"sample_files/{feed.id}/sample.csv"
    storage.write_file(storage_path, csv_data)

    sample = SampleFile(
        id=uuid.uuid4(),
        feed_id=feed.id,
        filename="sample.csv",
        storage_path=storage_path,
        file_size_bytes=len(csv_data),
        file_fingerprint="fp1234567890",
        mime_type="text/csv",
        row_count_estimate=2,
        uploaded_by="engineer",
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(sample)
    db.commit()
    db.refresh(feed)
    db.refresh(schema)
    db.refresh(schema_v1)
    db.refresh(sample)
    return feed, schema, schema_v1, sample


# Test 23
def test_rule_full_lifecycle_create_validate_test_publish(client, engineer_token, setup_lifecycle_data):
    feed, schema, schema_v1, sample = setup_lifecycle_data
    headers = {"Authorization": f"Bearer {engineer_token}"}

    # 1. Create rule
    create_res = client.post(
        "/api/v1/rules",
        headers=headers,
        json={
            "feed_id": str(feed.id),
            "name": "full_lifecycle_rule",
            "target_field": "amount",
            "rule_type": "RANGE",
            "severity": "QUARANTINE",
            "rule_config": {"min": 50, "max": 500},
        },
    )
    assert create_res.status_code == 201
    rule_data = create_res.json()
    rule_id = rule_data["id"]
    version_id = rule_data["draft_version"]["id"]

    # 2. Update draft
    put_res = client.put(
        f"/api/v1/rules/{rule_id}/versions/{version_id}",
        headers=headers,
        json={
            "rule_config": {"min": 0, "max": 1000},
            "error_message_template": "Amount {value} out of range",
        },
    )
    assert put_res.status_code == 200
    assert put_res.json()["rule_config"]["max"] == 1000

    # 3. Validate
    val_res = client.post(f"/api/v1/rules/{rule_id}/versions/{version_id}/validate", headers=headers)
    assert val_res.status_code == 200
    assert val_res.json()["is_valid"] is True

    # 4. Test against sample
    test_res = client.post(f"/api/v1/rules/{rule_id}/versions/{version_id}/test", headers=headers)
    assert test_res.status_code == 200
    assert test_res.json()["total_rows"] == 2
    assert test_res.json()["passed_rows"] == 2

    # 5. Publish
    pub_res = client.post(
        f"/api/v1/rules/{rule_id}/versions/{version_id}/publish",
        headers=headers,
        json={"change_notes": "First release"},
    )
    assert pub_res.status_code == 200
    assert pub_res.json()["status"] == "PUBLISHED"
    assert pub_res.json()["compiled_spec"] is not None

    # 6. Verify immutability
    fail_put = client.put(
        f"/api/v1/rules/{rule_id}/versions/{version_id}",
        headers=headers,
        json={"target_field": "claim_id"},
    )
    assert fail_put.status_code == 400
    assert "immutable" in fail_put.json()["detail"].lower()


# Test 24
def test_rule_versioning_spawn_and_isolation(client, engineer_token, setup_lifecycle_data):
    feed, schema, schema_v1, sample = setup_lifecycle_data
    headers = {"Authorization": f"Bearer {engineer_token}"}

    # Create and publish v1
    c_res = client.post(
        "/api/v1/rules",
        headers=headers,
        json={
            "feed_id": str(feed.id),
            "name": "isolation_rule",
            "target_field": "amount",
            "rule_type": "NOT_NULL",
        },
    )
    rule_id = c_res.json()["id"]
    v1_id = c_res.json()["draft_version"]["id"]

    client.post(f"/api/v1/rules/{rule_id}/versions/{v1_id}/publish", headers=headers, json={})

    # Spawn v2
    spawn_res = client.post(f"/api/v1/rules/{rule_id}/versions", headers=headers, json={"change_notes": "v2 draft"})
    assert spawn_res.status_code == 201
    v2_data = spawn_res.json()
    v2_id = v2_data["id"]
    assert v2_id != v1_id
    assert v2_data["version_number"] == 2
    assert v2_data["status"] == "DRAFT"

    # Modify v2
    mod_res = client.put(
        f"/api/v1/rules/{rule_id}/versions/{v2_id}",
        headers=headers,
        json={"severity": "WARNING"},
    )
    assert mod_res.status_code == 200
    assert mod_res.json()["severity"] == "WARNING"

    # Verify v1 is UNTOUCHED
    v1_check = client.get(f"/api/v1/rules/{rule_id}/versions/{v1_id}", headers=headers).json()
    assert v1_check["status"] == "PUBLISHED"
    assert v1_check["severity"] == "QUARANTINE"


# Test 25
def test_rule_schema_pinning_on_version_spawn(client, engineer_token, db, setup_lifecycle_data):
    feed, schema, schema_v1, sample = setup_lifecycle_data
    headers = {"Authorization": f"Bearer {engineer_token}"}

    # Create and publish rule v1 pinned to schema v1
    c_res = client.post(
        "/api/v1/rules",
        headers=headers,
        json={
            "feed_id": str(feed.id),
            "name": "schema_pin_test",
            "target_field": "amount",
            "rule_type": "NOT_NULL",
        },
    )
    rule_id = c_res.json()["id"]
    v1_id = c_res.json()["draft_version"]["id"]
    client.post(f"/api/v1/rules/{rule_id}/versions/{v1_id}/publish", headers=headers, json={})

    # Now create and publish Schema Version 2 in database
    schema_v2 = SchemaVersion(
        id=uuid.uuid4(),
        schema_id=schema.id,
        version_number=2,
        status=SchemaVersionStatusEnum.PUBLISHED,
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(schema_v2)
    schema_v1.status = SchemaVersionStatusEnum.SUPERSEDED
    db.commit()

    # Spawn rule v2 — defaults to currently PUBLISHED schema (schema v2)
    spawn_res = client.post(f"/api/v1/rules/{rule_id}/versions", headers=headers, json={})
    assert spawn_res.status_code == 201
    v2_data = spawn_res.json()
    assert v2_data["schema_version_id"] == str(schema_v2.id)

    # But v1 MUST still remain pinned to schema v1
    v1_data = client.get(f"/api/v1/rules/{rule_id}/versions/{v1_id}", headers=headers).json()
    assert v1_data["schema_version_id"] == str(schema_v1.id)
