"""
Integration Tests for Wave 3 Slice 2:
ODS REST Endpoints, Model Version Publishing Lifecycle, Consumer Registration & Gate Validation (CF-V3-E10-01, CF-V3-E10-02)
"""
import uuid
import pytest
from backend.models.ods import OdsModelVersionStatusEnum, ConsumerStatusEnum, ConsumerTypeEnum
from backend.models.pipeline import Batch, BatchStatusEnum
from backend.models.feed import Feed, FeedStatusEnum, FeedFormatEnum, FeedVersion, FeedVersionStatusEnum


@pytest.fixture
def active_feed_and_version(db):
    feed = Feed(
        id=uuid.uuid4(),
        name=f"ODS Integration Feed {uuid.uuid4().hex[:6]}",
        domain="clinical",
        description="Integration Test Feed",
        format=FeedFormatEnum.JSON,
        landing_folder="/data/landing/ods_int",
        filename_pattern="test_int_*.json",
        schedule_expression="0 0 * * *",
        status=FeedStatusEnum.ACTIVE,
        created_by="engineer@cinqflow.local",
        updated_by="engineer@cinqflow.local",
    )
    db.add(feed)
    db.flush()

    fv = FeedVersion(
        id=uuid.uuid4(),
        feed_id=feed.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED,
        created_by="engineer@cinqflow.local",
        updated_by="engineer@cinqflow.local",
    )
    db.add(fv)
    db.commit()
    return feed, fv


def test_model_version_api_crud_and_rbac(client, engineer_headers, readonly_headers):
    # 1. Read-only user cannot create model version (403)
    res_ro = client.post(
        "/api/v1/ods/model-versions",
        headers=readonly_headers,
        json={
            "version_number": 3001,
            "name": "Unauthorized Version",
            "domain": "clinical",
            "schema_definition": {},
        },
    )
    assert res_ro.status_code == 403

    # 2. Engineer creates model version (201)
    res_create = client.post(
        "/api/v1/ods/model-versions",
        headers=engineer_headers,
        json={
            "version_number": 3001,
            "name": "Canonical Clinical Core v3001",
            "domain": "clinical",
            "description": "Integration test model version",
            "schema_definition": {
                "entities": {
                    "members": {"primary_key": ["cinq_id", "batch_id"]},
                    "claims": {"primary_key": ["claim_id"]},
                }
            },
        },
    )
    assert res_create.status_code == 201
    created_data = res_create.json()
    assert created_data["version_number"] == 3001
    assert created_data["status"] == OdsModelVersionStatusEnum.DRAFT.value
    version_id = created_data["id"]

    # 3. List model versions
    res_list = client.get("/api/v1/ods/model-versions", headers=engineer_headers)
    assert res_list.status_code == 200
    versions = res_list.json()
    assert any(v["id"] == version_id for v in versions)

    # 4. Publish model version
    res_pub = client.post(
        f"/api/v1/ods/model-versions/{version_id}/publish",
        headers=engineer_headers,
        json={"change_notes": "Official release for downstream analytics"},
    )
    assert res_pub.status_code == 200
    pub_data = res_pub.json()
    assert pub_data["status"] == OdsModelVersionStatusEnum.PUBLISHED.value
    assert pub_data["published_at"] is not None

    # 5. Publishing again should fail with 400
    res_pub_repeat = client.post(
        f"/api/v1/ods/model-versions/{version_id}/publish",
        headers=engineer_headers,
        json={"change_notes": "Duplicate publish"},
    )
    assert res_pub_repeat.status_code == 400


def test_consumer_registration_and_gate_api(client, engineer_headers, active_feed_and_version, db):
    feed, fv = active_feed_and_version

    # 1. Create and publish a model version
    res_v1 = client.post(
        "/api/v1/ods/model-versions",
        headers=engineer_headers,
        json={
            "version_number": 3002,
            "name": "Canonical v3002",
            "domain": "clinical",
            "schema_definition": {},
        },
    )
    assert res_v1.status_code == 201
    v1_id = res_v1.json()["id"]

    client.post(f"/api/v1/ods/model-versions/{v1_id}/publish", headers=engineer_headers, json={})

    # Create v2
    res_v2 = client.post(
        "/api/v1/ods/model-versions",
        headers=engineer_headers,
        json={
            "version_number": 3003,
            "name": "Canonical v3003",
            "domain": "clinical",
            "schema_definition": {},
        },
    )
    v2_id = res_v2.json()["id"]

    # 2. Register consumer bound to v1
    res_c = client.post(
        "/api/v1/ods/consumers",
        headers=engineer_headers,
        json={
            "consumer_name": "tableau_clinical_dashboard",
            "consumer_type": ConsumerTypeEnum.REPORTING.value,
            "registered_ods_model_version_id": v1_id,
            "contact_email": "bi-team@cinqflow.com",
            "purpose": "Monthly executive clinical KPI dashboards",
        },
    )
    assert res_c.status_code == 201
    c_data = res_c.json()
    consumer_id = c_data["id"]
    assert c_data["db_role_name"] == "cinqflow_consumer_tableau_clinical_dashboard_v3002"
    assert c_data["status"] == ConsumerStatusEnum.ACTIVE.value

    # 3. Create batches bound to v1 and v2
    batch_v1 = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=fv.id,
        ods_model_version_id=uuid.UUID(v1_id),
        status=BatchStatusEnum.SUCCESS,
        triggered_by="system",
        created_by="system",
        updated_by="system",
    )
    batch_v2 = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=fv.id,
        ods_model_version_id=uuid.UUID(v2_id),
        status=BatchStatusEnum.SUCCESS,
        triggered_by="system",
        created_by="system",
        updated_by="system",
    )
    db.add(batch_v1)
    db.add(batch_v2)
    db.commit()

    # 4. Test consumer gate via API: Batch v1 matches consumer -> 200
    res_gate_ok = client.post(
        f"/api/v1/ods/consumer-gate/tableau_clinical_dashboard/batches/{batch_v1.id}",
        headers=engineer_headers,
    )
    assert res_gate_ok.status_code == 200
    gate_data = res_gate_ok.json()
    assert gate_data["allowed"] is True
    assert gate_data["ods_model_version_id"] == v1_id
    assert gate_data["consumer_name"] == "tableau_clinical_dashboard"

    # 5. Test consumer gate via API: Batch v2 mismatch -> 403
    res_gate_mismatch = client.post(
        f"/api/v1/ods/consumer-gate/tableau_clinical_dashboard/batches/{batch_v2.id}",
        headers=engineer_headers,
    )
    assert res_gate_mismatch.status_code == 403
    assert "Model version mismatch" in res_gate_mismatch.json()["detail"]

    # 6. Update consumer status to SUSPENDED
    res_patch = client.patch(
        f"/api/v1/ods/consumers/{consumer_id}",
        headers=engineer_headers,
        json={"status": ConsumerStatusEnum.SUSPENDED.value},
    )
    assert res_patch.status_code == 200
    assert res_patch.json()["status"] == ConsumerStatusEnum.SUSPENDED.value

    # 7. Gate evaluation now blocked due to inactive consumer
    res_gate_inactive = client.post(
        f"/api/v1/ods/consumer-gate/tableau_clinical_dashboard/batches/{batch_v1.id}",
        headers=engineer_headers,
    )
    assert res_gate_inactive.status_code == 403
    assert "not active" in res_gate_inactive.json()["detail"]
