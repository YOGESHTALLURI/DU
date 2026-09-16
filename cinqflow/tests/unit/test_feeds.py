"""
Feed Registry API & Service Tests — Wave 0

Verifies Phase 5 requirements:
- Source/feed metadata management (6 minimum fields)
- Feed versioning and publishing (immutable configuration snapshot)
- Generic filename pattern validation without feed-specific branching
- Authorization enforcement (ENGINEER vs READ_ONLY)
- Audit event generation for feed operations
"""
import pytest
from backend.models.feed import FeedStatusEnum, FeedVersionStatusEnum
from backend.models.audit import AuditEvent, AuditActionEnum


def test_create_feed_engineer(client, engineer_headers, db):
    payload = {
        "name": "CUSTOM_TEST_FEED_01",
        "domain": "LAB_RESULTS",
        "description": "Lab observation extracts",
        "format": "CSV",
        "landing_folder": "./data/landing/lab",
        "filename_pattern": "LAB_*.csv",
        "schedule_expression": "0 2 * * *",
        "initial_config": {
            "fields": [
                {"name": "patient_id", "type": "STRING", "required": True},
                {"name": "test_code", "type": "STRING", "required": True},
                {"name": "result_value", "type": "STRING", "required": True},
            ],
            "delimiter": ",",
            "has_header": True,
        },
    }
    res = client.post("/api/v1/feeds", json=payload, headers=engineer_headers)
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "CUSTOM_TEST_FEED_01"
    assert data["domain"] == "LAB_RESULTS"
    assert data["format"] == "CSV"
    assert len(data["versions"]) == 1
    assert data["versions"][0]["version_number"] == 1
    assert data["versions"][0]["status"] == "DRAFT"

    # Verify audit event emitted
    audit = (
        db.query(AuditEvent)
        .filter(AuditEvent.action == AuditActionEnum.FEED_CREATED)
        .order_by(AuditEvent.created_at.desc())
        .first()
    )
    assert audit is not None
    assert audit.object_id == data["id"]


def test_create_feed_readonly_rejected_403(client, readonly_headers):
    payload = {
        "name": "HACK_FEED",
        "domain": "SECURITY",
        "format": "CSV",
        "landing_folder": "./data",
        "filename_pattern": "*.csv",
    }
    res = client.post("/api/v1/feeds", json=payload, headers=readonly_headers)
    assert res.status_code == 403


def test_update_feed_engineer(client, engineer_headers):
    # Create feed
    res_c = client.post(
        "/api/v1/feeds",
        json={
            "name": "FEED_TO_UPDATE",
            "domain": "CLINICAL",
            "format": "CSV",
            "landing_folder": "./data/landing",
            "filename_pattern": "CLIN_*.csv",
        },
        headers=engineer_headers,
    )
    feed_id = res_c.json()["id"]

    # Update description and landing folder
    res_u = client.put(
        f"/api/v1/feeds/{feed_id}",
        json={"description": "Updated clinical feed", "landing_folder": "./data/landing/clinical"},
        headers=engineer_headers,
    )
    assert res_u.status_code == 200
    assert res_u.json()["description"] == "Updated clinical feed"
    assert res_u.json()["landing_folder"] == "./data/landing/clinical"


def test_version_lifecycle_and_publish(client, engineer_headers, db):
    # Create feed
    res_c = client.post(
        "/api/v1/feeds",
        json={
            "name": "FEED_VERSIONING_TEST",
            "domain": "MEMBERSHIP",
            "format": "CSV",
            "landing_folder": "./data/landing",
            "filename_pattern": "MBR_*.csv",
        },
        headers=engineer_headers,
    )
    feed_id = res_c.json()["id"]
    v1_id = res_c.json()["versions"][0]["id"]

    # Publish version 1
    res_p1 = client.post(
        f"/api/v1/feeds/{feed_id}/versions/{v1_id}/publish",
        json={"change_notes": "First production release"},
        headers=engineer_headers,
    )
    assert res_p1.status_code == 200
    assert res_p1.json()["status"] == "PUBLISHED"

    # Create version 2
    res_v2 = client.post(
        f"/api/v1/feeds/{feed_id}/versions",
        json={
            "config_snapshot": {
                "fields": [
                    {"name": "member_id", "type": "STRING", "required": True},
                    {"name": "dob", "type": "DATE", "required": True},
                ],
                "delimiter": "|",
                "has_header": True,
            },
            "change_notes": "Switch to pipe delimiter and add dob",
        },
        headers=engineer_headers,
    )
    assert res_v2.status_code == 201
    assert res_v2.json()["version_number"] == 2
    assert res_v2.json()["status"] == "DRAFT"
    v2_id = res_v2.json()["id"]

    # Publish version 2 -> version 1 should be superseded
    res_p2 = client.post(
        f"/api/v1/feeds/{feed_id}/versions/{v2_id}/publish",
        json={"change_notes": "Promoting version 2 to active"},
        headers=engineer_headers,
    )
    assert res_p2.status_code == 200
    assert res_p2.json()["status"] == "PUBLISHED"

    # Fetch all versions and verify statuses
    res_list = client.get(f"/api/v1/feeds/{feed_id}/versions", headers=engineer_headers)
    assert res_list.status_code == 200
    versions = res_list.json()
    assert len(versions) == 2
    v1_check = next(v for v in versions if v["id"] == v1_id)
    v2_check = next(v for v in versions if v["id"] == v2_id)
    assert v1_check["status"] == "SUPERSEDED"
    assert v2_check["status"] == "PUBLISHED"


def test_generic_pattern_validation(client, engineer_headers, readonly_headers):
    """
    CRITICAL REQUIREMENT: The feed pattern matching is generic and uses metadata.
    No hardcoded feed names.
    """
    res_c = client.post(
        "/api/v1/feeds",
        json={
            "name": "ARBITRARY_FEED_XYZ",
            "domain": "FINANCE",
            "format": "CSV",
            "landing_folder": "./data/landing",
            "filename_pattern": "FIN_EXTRACT_????[0-9].csv",
        },
        headers=engineer_headers,
    )
    feed_id = res_c.json()["id"]

    # Matching sample
    res_match = client.post(
        f"/api/v1/feeds/{feed_id}/validate-pattern",
        json={"sample_filename": "FIN_EXTRACT_ABCD1.csv"},
        headers=readonly_headers,
    )
    assert res_match.status_code == 200
    assert res_match.json()["matches"] is True

    # Non-matching sample
    res_nomatch = client.post(
        f"/api/v1/feeds/{feed_id}/validate-pattern",
        json={"sample_filename": "WRONG_FILE.csv"},
        headers=readonly_headers,
    )
    assert res_nomatch.status_code == 200
    assert res_nomatch.json()["matches"] is False
