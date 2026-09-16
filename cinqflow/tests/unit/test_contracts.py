"""
Contract Register API & Service Tests — Wave 0

Verifies Phase 4 requirements:
- Create contract register entry (ENGINEER only)
- Update draft record (ENGINEER only)
- Unauthorized attempts rejected (401/403)
- Add unknown production assumption (ENGINEER only)
- Confirm unknown assumption (ENGINEER only)
- Risk-view rollup calculation
- Audit event generation for every state change
"""
import pytest
from backend.models.audit import AuditEvent, AuditActionEnum


def test_create_contract_engineer(client, engineer_headers, db):
    payload = {
        "source_system": "TEST_PAYER_SYSTEM",
        "target_domain": "CLAIMS",
        "description": "Monthly claims extract from primary payer",
        "data_owner": "Claims Integration Team",
        "story_id": "CF-V0-E1-01",
        "notes": "Testing creation",
    }
    res = client.post("/api/v1/contracts", json=payload, headers=engineer_headers)
    assert res.status_code == 201
    data = res.json()
    assert data["source_system"] == "TEST_PAYER_SYSTEM"
    assert data["target_domain"] == "CLAIMS"
    assert data["status"] == "DRAFT"
    assert data["version"] == 1

    # Verify audit event was emitted
    audit = (
        db.query(AuditEvent)
        .filter(AuditEvent.action == AuditActionEnum.CONTRACT_CREATED)
        .order_by(AuditEvent.created_at.desc())
        .first()
    )
    assert audit is not None
    assert audit.object_id == data["id"]


def test_create_contract_readonly_rejected_403(client, readonly_headers):
    payload = {
        "source_system": "UNAUTHORIZED_PAYER",
        "target_domain": "MEMBERSHIP",
        "description": "Attempted create by readonly user",
        "data_owner": "Ops",
    }
    res = client.post("/api/v1/contracts", json=payload, headers=readonly_headers)
    assert res.status_code == 403
    assert "ENGINEER role required" in res.json()["detail"]


def test_create_contract_unauthenticated_rejected_401(client):
    payload = {
        "source_system": "NO_AUTH_PAYER",
        "target_domain": "MEMBERSHIP",
        "description": "Attempted create with no auth",
        "data_owner": "Ops",
    }
    res = client.post("/api/v1/contracts", json=payload)
    assert res.status_code == 401


def test_update_contract_engineer(client, engineer_headers, db):
    # 1. Create contract
    create_payload = {
        "source_system": "UPDATE_TEST_SYSTEM",
        "target_domain": "PROVIDER",
        "description": "Provider roster feed",
        "data_owner": "Provider Ops",
    }
    res_create = client.post("/api/v1/contracts", json=create_payload, headers=engineer_headers)
    assert res_create.status_code == 201
    contract_id = res_create.json()["id"]

    # 2. Update contract
    update_payload = {
        "description": "Updated provider roster feed with NPI crosswalk",
        "data_owner": "Lead Provider Steward",
    }
    res_update = client.put(f"/api/v1/contracts/{contract_id}", json=update_payload, headers=engineer_headers)
    assert res_update.status_code == 200
    updated_data = res_update.json()
    assert updated_data["description"] == "Updated provider roster feed with NPI crosswalk"
    assert updated_data["data_owner"] == "Lead Provider Steward"
    assert updated_data["version"] == 2

    # Verify update audit event was emitted
    audit = (
        db.query(AuditEvent)
        .filter(AuditEvent.action == AuditActionEnum.CONTRACT_UPDATED)
        .order_by(AuditEvent.created_at.desc())
        .first()
    )
    assert audit is not None
    assert audit.object_id == contract_id


def test_update_contract_readonly_rejected_403(client, engineer_headers, readonly_headers):
    # Create by engineer
    create_payload = {
        "source_system": "READONLY_UPDATE_TEST",
        "target_domain": "PHARMACY",
        "description": "Pharmacy claims feed",
        "data_owner": "Pharmacy Team",
    }
    res_create = client.post("/api/v1/contracts", json=create_payload, headers=engineer_headers)
    contract_id = res_create.json()["id"]

    # Attempt update by read_only
    update_payload = {"description": "Hacked description"}
    res_update = client.put(f"/api/v1/contracts/{contract_id}", json=update_payload, headers=readonly_headers)
    assert res_update.status_code == 403


def test_record_and_confirm_unknown(client, engineer_headers, db):
    # 1. Create contract
    res_c = client.post(
        "/api/v1/contracts",
        json={
            "source_system": "SFTP_FEED",
            "target_domain": "ELIGIBILITY",
            "description": "SFTP eligibility feed",
            "data_owner": "Integration",
        },
        headers=engineer_headers,
    )
    contract_id = res_c.json()["id"]

    # 2. Add unknown assumption
    unk_res = client.post(
        f"/api/v1/contracts/{contract_id}/unknowns",
        json={
            "description": "SFTP connection port and SSH key rotation cycle unconfirmed",
            "risk_level": "HIGH",
        },
        headers=engineer_headers,
    )
    assert unk_res.status_code == 201
    unknown_id = unk_res.json()["id"]
    assert unk_res.json()["status"] == "OPEN"
    assert unk_res.json()["risk_level"] == "HIGH"

    # Verify audit event for unknown added
    audit_add = (
        db.query(AuditEvent)
        .filter(AuditEvent.action == AuditActionEnum.CONTRACT_UNKNOWN_ADDED)
        .order_by(AuditEvent.created_at.desc())
        .first()
    )
    assert audit_add is not None
    assert audit_add.object_id == unknown_id

    # 3. Confirm unknown assumption
    conf_res = client.put(
        f"/api/v1/contracts/unknowns/{unknown_id}/confirm",
        json={"resolution_notes": "Confirmed port 2222 with weekly key rotation via vault"},
        headers=engineer_headers,
    )
    assert conf_res.status_code == 200
    assert conf_res.json()["status"] == "CONFIRMED"
    assert conf_res.json()["resolution_notes"] == "Confirmed port 2222 with weekly key rotation via vault"

    # Verify audit event for unknown confirmed
    audit_conf = (
        db.query(AuditEvent)
        .filter(AuditEvent.action == AuditActionEnum.CONTRACT_UNKNOWN_CONFIRMED)
        .order_by(AuditEvent.created_at.desc())
        .first()
    )
    assert audit_conf is not None
    assert audit_conf.object_id == unknown_id


def test_risk_view_rollup(client, engineer_headers, readonly_headers):
    # Both engineer and readonly can view risk rollup
    res = client.get("/api/v1/contracts/risk-view", headers=readonly_headers)
    assert res.status_code == 200
    data = res.json()
    assert "total_unknowns" in data
    assert "open_unknowns" in data
    assert "by_risk_level" in data
    assert "CRITICAL" in data["by_risk_level"]
    assert "HIGH" in data["by_risk_level"]
