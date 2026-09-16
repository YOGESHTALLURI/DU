"""
Integration tests for Operations Alerts, Fingerprints & Playbooks REST API (CF-V2-E12-04, CF-V2-E12-05)
Verifies RBAC enforcement, query filtering, and lifecycle state changes over HTTP.
"""
import uuid
import pytest
from backend.models.incident import FailureCategoryEnum, AlertSeverityEnum, AlertStatusEnum
from backend.services.alert_service import AlertService
from backend.models.feed import Feed, FeedFormatEnum, FeedStatusEnum


@pytest.fixture
def test_feed(db):
    feed = Feed(
        name=f"api-test-feed-{uuid.uuid4().hex[:8]}",
        domain="CLAIMS",
        format=FeedFormatEnum.CSV,
        landing_folder="/landing/claims",
        filename_pattern="claims_*.csv",
        schedule_expression="0 6 * * *",
        status=FeedStatusEnum.ACTIVE,
        created_by="test-setup",
        updated_by="test-setup",
    )
    db.add(feed)
    db.commit()
    db.refresh(feed)
    return feed


def test_get_alerts_endpoint(client, db, test_feed, engineer_headers):
    """GET /api/v1/ops/alerts returns active operational alerts."""
    AlertService.record_failure(
        db=db,
        feed_id=test_feed.id,
        category=FailureCategoryEnum.DATA_QUALITY,
        failure_stage="SILVER_RAW",
        root_cause_pattern="Missing member ID",
    )
    db.commit()

    res = client.get("/api/v1/ops/alerts", headers=engineer_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 1
    item = next(a for a in data if a["feed_id"] == str(test_feed.id))
    assert item["status"] == "OPEN"
    assert item["severity"] == "CRITICAL"


def test_get_alert_detail_endpoint(client, db, test_feed, engineer_headers):
    """GET /api/v1/ops/alerts/{id} returns full alert details with occurrences timeline."""
    alert = AlertService.record_failure(
        db=db,
        feed_id=test_feed.id,
        category=FailureCategoryEnum.SCHEMA_DRIFT,
        failure_stage="LANDING",
        root_cause_pattern="Column count mismatch in CSV",
    )
    db.commit()

    res = client.get(f"/api/v1/ops/alerts/{alert.id}", headers=engineer_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == str(alert.id)
    assert "fingerprint" in data
    assert len(data["occurrences"]) >= 1


def test_acknowledge_alert_api(client, db, test_feed, engineer_headers):
    """POST /api/v1/ops/alerts/{id}/acknowledge transitions alert to ACKNOWLEDGED."""
    alert = AlertService.record_failure(
        db=db,
        feed_id=test_feed.id,
        category=FailureCategoryEnum.STAGE_EXECUTION,
        failure_stage="BRONZE",
        root_cause_pattern="Network timeout fetching file",
    )
    db.commit()

    res = client.post(f"/api/v1/ops/alerts/{alert.id}/acknowledge", headers=engineer_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ACKNOWLEDGED"
    assert data["acknowledged_at"] is not None


def test_acknowledge_alert_rbac_readonly_forbidden(client, db, test_feed, readonly_headers):
    """POST /api/v1/ops/alerts/{id}/acknowledge by READ_ONLY role returns 403 Forbidden."""
    alert = AlertService.record_failure(
        db=db,
        feed_id=test_feed.id,
        category=FailureCategoryEnum.STAGE_EXECUTION,
        failure_stage="BRONZE",
        root_cause_pattern="Permission denied on file",
    )
    db.commit()

    res = client.post(f"/api/v1/ops/alerts/{alert.id}/acknowledge", headers=readonly_headers)
    assert res.status_code == 403


def test_resolve_alert_api(client, db, test_feed, engineer_headers):
    """POST /api/v1/ops/alerts/{id}/resolve transitions alert to RESOLVED with notes."""
    alert = AlertService.record_failure(
        db=db,
        feed_id=test_feed.id,
        category=FailureCategoryEnum.DATA_QUALITY,
        failure_stage="SILVER_RAW",
        root_cause_pattern="Invalid date range",
    )
    db.commit()

    res = client.post(
        f"/api/v1/ops/alerts/{alert.id}/resolve",
        json={"resolution_notes": "Rule threshold relaxed per business request"},
        headers=engineer_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "RESOLVED"
    assert "Rule threshold relaxed" in data["resolution_notes"]


def test_reopen_alert_api(client, db, test_feed, engineer_headers):
    """POST /api/v1/ops/alerts/{id}/reopen transitions resolved alert back to REOPENED."""
    alert = AlertService.record_failure(
        db=db,
        feed_id=test_feed.id,
        category=FailureCategoryEnum.DATA_QUALITY,
        failure_stage="SILVER_RAW",
        root_cause_pattern="Missing provider NPI",
    )
    AlertService.resolve_alert(db=db, alert_id=alert.id, resolution_notes="Fixed", user_id="lead")
    db.commit()

    res = client.post(
        f"/api/v1/ops/alerts/{alert.id}/reopen",
        json={"reason": "NPIs still missing in secondary batch"},
        headers=engineer_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "REOPENED"


def test_playbook_create_and_approve_api(client, db, engineer_headers):
    """Engineer can create a playbook in DRAFT, and approve its version."""
    code = f"PB-API-{uuid.uuid4().hex[:6]}"
    create_payload = {
        "title": "API Test Playbook",
        "category": "DATA_QUALITY",
        "playbook_code": code,
        "explanation_template": "Follow standard quarantine review",
        "suggested_action_type": "REPROCESS_QUARANTINE",
        "manual_steps_markdown": "1. Review quarantine table.",
    }

    create_res = client.post("/api/v1/ops/playbooks", json=create_payload, headers=engineer_headers)
    assert create_res.status_code == 201
    pb_data = create_res.json()
    assert pb_data["status"] == "DRAFT"
    pb_id = pb_data["id"]

    approve_res = client.post(f"/api/v1/ops/playbooks/{pb_id}/approve", headers=engineer_headers)
    assert approve_res.status_code == 200
    assert approve_res.json()["status"] == "APPROVED"


def test_playbook_create_readonly_forbidden(client, db, readonly_headers):
    """READ_ONLY role cannot create playbooks (403 Forbidden)."""
    payload = {
        "title": "Unauthorized Playbook",
        "category": "DATA_QUALITY",
        "playbook_code": f"PB-NOAUTH-{uuid.uuid4().hex[:6]}",
        "explanation_template": "None",
    }
    res = client.post("/api/v1/ops/playbooks", json=payload, headers=readonly_headers)
    assert res.status_code == 403
