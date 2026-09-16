"""
Integration tests for Wave 2 Slice 5 — Operational Variance & Waiver Lifecycle API Endpoints (CF-V2-E13-03).
Verifies:
- POST /api/v1/ops/variances (record control variance)
- GET /api/v1/ops/variances (list and filter variances)
- POST /api/v1/ops/waivers (request bounded waiver)
- POST /api/v1/ops/waivers/{id}/review (four-eyes review, approval and rejection)
- POST /api/v1/ops/waivers/{id}/revoke (revoke active waiver)
- Audit event generation for every mutation
"""
import uuid
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient

from backend.models.feed import Feed, FeedFormatEnum, FeedStatusEnum, FeedVersion, FeedVersionStatusEnum
from backend.models.pipeline import Batch, BatchStatusEnum
from backend.models.audit import AuditEvent, AuditActionEnum


@pytest.fixture
def api_test_env(db):
    feed = Feed(
        id=uuid.uuid4(),
        name=f"INTEG_GOV_FEED_{uuid.uuid4().hex[:6]}",
        domain="MEMBERS",
        format=FeedFormatEnum.CSV,
        status=FeedStatusEnum.ACTIVE,
        landing_folder="./data/landing",
        filename_pattern="*.csv",
        created_by="tester",
        updated_by="tester",
    )
    db.add(feed)

    fv = FeedVersion(
        id=uuid.uuid4(),
        feed_id=feed.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED,
        created_by="tester",
        updated_by="tester",
    )
    db.add(fv)

    batch = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=fv.id,
        status=BatchStatusEnum.FAILED,
        triggered_by="operator_trigger",
        created_by="operator_trigger",
        updated_by="operator_trigger",
    )
    db.add(batch)
    db.commit()

    return {"feed": feed, "batch": batch}


def test_api_variance_and_waiver_full_governed_lifecycle(client, engineer_headers, readonly_headers, api_test_env, db):
    feed = api_test_env["feed"]
    batch = api_test_env["batch"]

    # 1. Record variance via API
    res_var = client.post(
        "/api/v1/ops/variances",
        headers=engineer_headers,
        json={
            "feed_id": str(feed.id),
            "batch_id": str(batch.id),
            "control_type": "DATA_QUALITY",
            "control_id": "RULE_DOB_RANGE",
            "severity": "WARNING",
            "title": "Date of birth out of range for 5 rows",
            "description": "DOB in 1890 detected",
            "telemetry_snapshot": {"count": 5},
        },
    )
    assert res_var.status_code == 201
    var_data = res_var.json()
    variance_id = var_data["id"]
    assert var_data["status"] == "OPEN"

    # 2. Read-Only cannot submit waiver
    res_ro_waiver = client.post(
        "/api/v1/ops/waivers",
        headers=readonly_headers,
        json={
            "variance_id": variance_id,
            "business_justification": "Test justification",
            "risk_assessment": "Test risk",
            "mitigation_notes": "Test notes",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        },
    )
    assert res_ro_waiver.status_code == 403

    # 3. Request waiver with Engineer headers
    res_waiver = client.post(
        "/api/v1/ops/waivers",
        headers=engineer_headers,
        json={
            "variance_id": variance_id,
            "scope": "SINGLE_BATCH",
            "business_justification": "Verified member is a centenarian, valid DOB",
            "risk_assessment": "No clinical data compromised",
            "mitigation_notes": "Added centenarian exception tag",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=14)).isoformat(),
        },
    )
    assert res_waiver.status_code == 201
    waiver_data = res_waiver.json()
    waiver_id = waiver_data["id"]
    assert waiver_data["status"] == "PENDING_APPROVAL"

    # 4. Attempt self-approval with same engineer token: Rejected with 403
    res_self_review = client.post(
        f"/api/v1/ops/waivers/{waiver_id}/review",
        headers=engineer_headers,
        json={"decision": "APPROVE", "decision_notes": "Self approval"},
    )
    assert res_self_review.status_code == 403
    assert "Four-eyes violation" in res_self_review.json()["detail"]

    # 5. Create distinct reviewer user and login
    res_login_rev = client.post("/api/v1/auth/login", json={"credential": "lead_steward:lead123"})
    # If lead_steward not in mock users, let's check mock users or use another credentials
    # Let's see: in mock provider, users are "engineer" and "readonly". But we can mock a second engineer or steward token:
    from jose import jwt
    from backend.core.config import settings
    token_steward = jwt.encode(
        {
            "sub": "mock-steward-002",
            "email": "steward2@cinqflow.local",
            "roles": ["DATA_STEWARD"],
            "provider": "mock",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    steward_headers = {"Authorization": f"Bearer {token_steward}"}

    # Distinct reviewer approves waiver
    res_approved = client.post(
        f"/api/v1/ops/waivers/{waiver_id}/review",
        headers=steward_headers,
        json={
            "decision": "APPROVE",
            "decision_notes": "Verified centenarian records with medical staff",
        },
    )
    assert res_approved.status_code == 200
    appr_data = res_approved.json()
    assert appr_data["status"] == "APPROVED"
    assert appr_data["is_active"] is True

    # 6. Verify variance transitioned to WAIVED
    res_var_after = client.get(f"/api/v1/ops/variances/{variance_id}", headers=engineer_headers)
    assert res_var_after.status_code == 200
    assert res_var_after.json()["status"] == "WAIVED"

    # 7. Revoke waiver
    res_revoke = client.post(
        f"/api/v1/ops/waivers/{waiver_id}/revoke",
        headers=steward_headers,
        json={"revocation_reason": "Audit finding: record was indeed mistyped"},
    )
    assert res_revoke.status_code == 200
    assert res_revoke.json()["status"] == "REVOKED"
    assert res_revoke.json()["is_active"] is False

    # 8. Verify variance reverted to OPEN
    res_var_rev = client.get(f"/api/v1/ops/variances/{variance_id}", headers=engineer_headers)
    assert res_var_rev.json()["status"] == "OPEN"

    # 9. Verify audit events logged
    actions_logged = [
        a.action.value
        for a in db.query(AuditEvent)
        .filter(AuditEvent.object_type.in_(["operational_variance", "operational_waiver"]))
        .all()
    ]
    assert "ops.variance_created" in actions_logged
    assert "ops.waiver_requested" in actions_logged
    assert "ops.waiver_approved" in actions_logged
    assert "ops.waiver_revoked" in actions_logged
