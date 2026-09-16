"""
Unit tests for Wave 1 Slice 2: Feed Lifecycle, Strict Clone Isolation, and Activation Validation
"""
import uuid
import pytest
from fastapi import status


def test_clone_feed_strict_isolation(client, engineer_headers, analyst_headers):
    # 1. Create a source feed with rich metadata
    source_payload = {
        "name": f"SOURCE_FEED_{uuid.uuid4().hex[:6]}",
        "domain": "PATIENT_CLINICAL",
        "description": "Source feed for cloning test",
        "format": "CSV",
        "landing_folder": "./data/landing/patient",
        "filename_pattern": "PATIENT_*.csv",
        "schedule_expression": "0 2 * * *",
        "source_system": "EPIC_EMR",
        "data_owner": "Clinical Data Team",
        "sla_expectation": "T+4h",
        "initial_config": {
            "fields": [{"name": "patient_id", "type": "STRING"}],
            "delimiter": ",",
            "has_header": True,
        },
    }
    res_create = client.post("/api/v1/feeds", json=source_payload, headers=engineer_headers)
    assert res_create.status_code == status.HTTP_201_CREATED
    source_feed = res_create.json()
    source_id = source_feed["id"]

    # 2. Clone the feed as Business Analyst
    clone_payload = {
        "new_name": f"CLONE_FEED_{uuid.uuid4().hex[:6]}",
        "new_filename_pattern": "CLONE_PATIENT_*.csv",
        "description": "Independent clone of source feed",
    }
    res_clone = client.post(f"/api/v1/feeds/{source_id}/clone", json=clone_payload, headers=analyst_headers)
    assert res_clone.status_code == status.HTTP_201_CREATED
    cloned_feed = res_clone.json()
    clone_id = cloned_feed["id"]

    # Verify strict isolation properties
    assert clone_id != source_id
    assert cloned_feed["name"] == clone_payload["new_name"]
    assert cloned_feed["domain"] == source_feed["domain"]
    assert cloned_feed["format"] == source_feed["format"]
    assert cloned_feed["landing_folder"] == source_feed["landing_folder"]
    assert cloned_feed["filename_pattern"] == "CLONE_PATIENT_*.csv"
    assert cloned_feed["source_system"] == source_feed["source_system"]
    assert cloned_feed["data_owner"] == source_feed["data_owner"]
    assert cloned_feed["sla_expectation"] == source_feed["sla_expectation"]
    assert cloned_feed["cloned_from_feed_id"] == source_id
    assert cloned_feed["status"] == "DRAFT"

    # Verify clone has independent version 1
    res_versions_source = client.get(f"/api/v1/feeds/{source_id}/versions", headers=analyst_headers)
    res_versions_clone = client.get(f"/api/v1/feeds/{clone_id}/versions", headers=analyst_headers)
    assert res_versions_source.status_code == 200
    assert res_versions_clone.status_code == 200

    source_v1 = res_versions_source.json()[0]
    clone_v1 = res_versions_clone.json()[0]
    assert clone_v1["id"] != source_v1["id"]
    assert clone_v1["feed_id"] == clone_id
    assert clone_v1["status"] == "DRAFT"
    assert clone_v1["config_snapshot"] == source_v1["config_snapshot"]

    # 3. Mutate the clone's metadata and add a version to clone
    mutate_payload = {
        "description": "Updated cloned feed description",
        "source_system": "CERNER_EHR",
    }
    res_update_clone = client.put(f"/api/v1/feeds/{clone_id}", json=mutate_payload, headers=engineer_headers)
    assert res_update_clone.status_code == 200

    # 4. Verify source feed remains completely UNTOUCHED
    res_source_check = client.get(f"/api/v1/feeds/{source_id}", headers=analyst_headers)
    assert res_source_check.status_code == 200
    source_check = res_source_check.json()
    assert source_check["description"] == "Source feed for cloning test"
    assert source_check["source_system"] == "EPIC_EMR"
    assert source_check["filename_pattern"] == "PATIENT_*.csv"


def test_clone_feed_name_collision_rejected(client, engineer_headers, analyst_headers):
    # Create feed A
    name_a = f"FEED_A_{uuid.uuid4().hex[:6]}"
    res_a = client.post(
        "/api/v1/feeds",
        json={
            "name": name_a,
            "domain": "CLAIMS",
            "landing_folder": "./data/landing/claims",
            "filename_pattern": "CLAIMS_*.csv",
        },
        headers=engineer_headers,
    )
    assert res_a.status_code == 201
    feed_a = res_a.json()

    # Attempt to clone feed A with existing name
    res_clone = client.post(
        f"/api/v1/feeds/{feed_a['id']}/clone",
        json={"new_name": name_a},
        headers=analyst_headers,
    )
    assert res_clone.status_code == status.HTTP_400_BAD_REQUEST
    assert "already exists" in res_clone.json()["detail"]


def test_clone_feed_rbac(client, engineer_headers, analyst_headers, readonly_headers):
    feed_name = f"FEED_RBAC_{uuid.uuid4().hex[:6]}"
    res = client.post(
        "/api/v1/feeds",
        json={
            "name": feed_name,
            "domain": "MEMBER",
            "landing_folder": "./data/landing/member",
            "filename_pattern": "MEMBER_*.csv",
        },
        headers=engineer_headers,
    )
    assert res.status_code == 201
    feed_id = res.json()["id"]

    # Read-only user cannot clone -> 403
    res_ro = client.post(
        f"/api/v1/feeds/{feed_id}/clone",
        json={"new_name": f"CLONE_RO_{uuid.uuid4().hex[:6]}"},
        headers=readonly_headers,
    )
    assert res_ro.status_code == status.HTTP_403_FORBIDDEN

    # Analyst can clone -> 201
    res_analyst = client.post(
        f"/api/v1/feeds/{feed_id}/clone",
        json={"new_name": f"CLONE_BA_{uuid.uuid4().hex[:6]}"},
        headers=analyst_headers,
    )
    assert res_analyst.status_code == status.HTTP_201_CREATED


def test_activation_validation_requires_published_schema(client, engineer_headers, analyst_headers):
    # 1. Create a feed
    feed_name = f"FEED_ACT_{uuid.uuid4().hex[:6]}"
    res = client.post(
        "/api/v1/feeds",
        json={
            "name": feed_name,
            "domain": "BILLING",
            "landing_folder": "./data/landing/billing",
            "filename_pattern": "BILLING_*.csv",
        },
        headers=engineer_headers,
    )
    assert res.status_code == 201
    feed_id = res.json()["id"]

    # 2. Attempt to activate without any schema -> 400 Bad Request
    res_act1 = client.put(
        f"/api/v1/feeds/{feed_id}/status",
        json={"status": "ACTIVE", "reason": "Attempt activation without schema"},
        headers=analyst_headers,
    )
    assert res_act1.status_code == status.HTTP_400_BAD_REQUEST
    assert "associated schema contract" in res_act1.json()["detail"].lower()

    # 3. Create a draft schema contract (without publishing it)
    schema_payload = {
        "feed_id": feed_id,
        "name": f"{feed_name}_Schema",
        "description": "Draft schema contract",
        "initial_fields": [
            {
                "field_name": "invoice_id",
                "ordinal_position": 1,
                "data_type": "STRING",
                "is_nullable": False,
                "is_required": True,
            }
        ],
    }
    res_schema = client.post("/api/v1/schemas", json=schema_payload, headers=analyst_headers)
    assert res_schema.status_code == 201
    schema_id = res_schema.json()["id"]

    # 4. Attempt to activate with only a DRAFT schema -> 400 Bad Request
    res_act2 = client.put(
        f"/api/v1/feeds/{feed_id}/status",
        json={"status": "ACTIVE", "reason": "Attempt activation with draft schema"},
        headers=analyst_headers,
    )
    assert res_act2.status_code == status.HTTP_400_BAD_REQUEST
    assert "published version" in res_act2.json()["detail"].lower()

    # 5. Publish the schema version
    # Get schema versions to find version 1 id
    res_versions = client.get(f"/api/v1/schemas/{schema_id}/versions", headers=analyst_headers)
    assert res_versions.status_code == 200
    v1_id = res_versions.json()[0]["id"]

    res_pub = client.post(
        f"/api/v1/schemas/{schema_id}/versions/{v1_id}/publish",
        json={"change_notes": "Publishing v1 for activation"},
        headers=analyst_headers,
    )
    assert res_pub.status_code == 200
    assert res_pub.json()["status"] == "PUBLISHED"

    # 6. Now activate the feed -> SUCCESS (200)
    res_act3 = client.put(
        f"/api/v1/feeds/{feed_id}/status",
        json={"status": "ACTIVE", "reason": "Schema is published, activating feed"},
        headers=analyst_headers,
    )
    assert res_act3.status_code == status.HTTP_200_OK
    assert res_act3.json()["status"] == "ACTIVE"


def test_feed_lifecycle_transitions(client, engineer_headers, analyst_headers):
    # Create feed
    feed_name = f"FEED_LIFE_{uuid.uuid4().hex[:6]}"
    res = client.post(
        "/api/v1/feeds",
        json={
            "name": feed_name,
            "domain": "PHARMACY",
            "landing_folder": "./data/landing/rx",
            "filename_pattern": "RX_*.csv",
        },
        headers=engineer_headers,
    )
    assert res.status_code == 201
    feed_id = res.json()["id"]

    # Publish schema so feed can become ACTIVE
    schema_res = client.post(
        "/api/v1/schemas",
        json={
            "feed_id": feed_id,
            "name": f"{feed_name}_Schema",
            "initial_fields": [{"field_name": "rx_id", "ordinal_position": 1, "data_type": "STRING"}],
        },
        headers=analyst_headers,
    )
    assert schema_res.status_code == 201
    schema_id = schema_res.json()["id"]
    v1_id = schema_res.json()["draft_version"]["id"]
    client.post(f"/api/v1/schemas/{schema_id}/versions/{v1_id}/publish", json={}, headers=analyst_headers)

    # DRAFT -> ACTIVE
    r1 = client.put(f"/api/v1/feeds/{feed_id}/status", json={"status": "ACTIVE"}, headers=analyst_headers)
    assert r1.status_code == 200
    assert r1.json()["status"] == "ACTIVE"

    # ACTIVE -> INACTIVE
    r2 = client.put(f"/api/v1/feeds/{feed_id}/status", json={"status": "INACTIVE"}, headers=analyst_headers)
    assert r2.status_code == 200
    assert r2.json()["status"] == "INACTIVE"

    # INACTIVE -> ACTIVE
    r3 = client.put(f"/api/v1/feeds/{feed_id}/status", json={"status": "ACTIVE"}, headers=analyst_headers)
    assert r3.status_code == 200
    assert r3.json()["status"] == "ACTIVE"

    # ACTIVE -> RETIRED
    r4 = client.put(f"/api/v1/feeds/{feed_id}/status", json={"status": "RETIRED"}, headers=analyst_headers)
    assert r4.status_code == 200
    assert r4.json()["status"] == "RETIRED"

    # RETIRED -> ACTIVE (Must be rejected)
    r5 = client.put(f"/api/v1/feeds/{feed_id}/status", json={"status": "ACTIVE"}, headers=analyst_headers)
    assert r5.status_code == status.HTTP_400_BAD_REQUEST
    assert "retired feed" in r5.json()["detail"].lower()
