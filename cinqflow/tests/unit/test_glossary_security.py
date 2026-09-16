"""
Security & RBAC unit tests for Wave 1 Slice 7: Business Glossary Service.
"""
import pytest
from backend.models.canonical_model import CanonicalField
from backend.services.canonical_model_service import CanonicalModelService


@pytest.fixture(autouse=True)
def seed_canonical(db):
    service = CanonicalModelService(db)
    service.seed_default_models_if_needed()
    db.commit()


def test_read_only_can_browse_and_search(client, steward_headers, readonly_headers):
    # Setup term
    client.post("/api/v1/glossary", json={
        "name": "Member Eligibility End Date",
        "domain": "Eligibility",
        "definition": "The date when health plan coverage concludes.",
    }, headers=steward_headers)

    res = client.get("/api/v1/glossary", headers=readonly_headers)
    assert res.status_code == 200
    assert "items" in res.json()


def test_read_only_forbidden_on_create(client, readonly_headers):
    res = client.post("/api/v1/glossary", json={
        "name": "Unauthorized Term Creation",
        "domain": "Clinical",
        "definition": "Should be rejected.",
    }, headers=readonly_headers)
    assert res.status_code == 403


def test_read_only_forbidden_on_update_and_delete(client, steward_headers, readonly_headers):
    term = client.post("/api/v1/glossary", json={
        "name": "Immutable Under ReadOnly Role",
        "domain": "Common",
        "definition": "Testing read-only denial.",
    }, headers=steward_headers).json()
    term_id = term["id"]

    # Try update
    put_res = client.put(f"/api/v1/glossary/{term_id}", json={"definition": "Hacked"}, headers=readonly_headers)
    assert put_res.status_code == 403

    # Try delete
    del_res = client.delete(f"/api/v1/glossary/{term_id}", headers=readonly_headers)
    assert del_res.status_code == 403


def test_analyst_can_create_draft_and_link(client, db, analyst_headers):
    # BA creates term
    res = client.post("/api/v1/glossary", json={
        "name": "Analyst Proposed Term",
        "domain": "Claims",
        "definition": "Proposed by BA for review.",
    }, headers=analyst_headers)
    assert res.status_code == 201
    term_id = res.json()["id"]

    # BA edits draft
    edit_res = client.put(f"/api/v1/glossary/{term_id}", json={"definition": "Revised proposal."}, headers=analyst_headers)
    assert edit_res.status_code == 200

    # BA links canonical field
    c_field = db.query(CanonicalField).filter(CanonicalField.field_name == "claim_id").first()
    assert c_field is not None
    link_res = client.post(f"/api/v1/glossary/{term_id}/links", json={"canonical_field_id": str(c_field.id)}, headers=analyst_headers)
    assert link_res.status_code == 201


def test_analyst_forbidden_on_approve_and_deprecate(client, steward_headers, analyst_headers):
    term = client.post("/api/v1/glossary", json={
        "name": "Steward Governed Term",
        "domain": "Eligibility",
        "definition": "Only stewards can approve.",
    }, headers=steward_headers).json()
    term_id = term["id"]

    # Analyst tries to approve
    app_res = client.post(f"/api/v1/glossary/{term_id}/approve", headers=analyst_headers)
    assert app_res.status_code == 403

    # Steward approves
    client.post(f"/api/v1/glossary/{term_id}/approve", headers=steward_headers)

    # Analyst tries to deprecate
    dep_res = client.post(f"/api/v1/glossary/{term_id}/deprecate", json={"deprecation_reason": "Not allowed"}, headers=analyst_headers)
    assert dep_res.status_code == 403


def test_steward_and_engineer_authorized_for_all(client, engineer_headers, steward_headers):
    # Engineer creates and approves
    term = client.post("/api/v1/glossary", json={
        "name": "Engineer Governed Term",
        "domain": "Financial",
        "definition": "Full privileges.",
    }, headers=engineer_headers).json()
    term_id = term["id"]

    app_res = client.post(f"/api/v1/glossary/{term_id}/approve", headers=engineer_headers)
    assert app_res.status_code == 200

    # Steward deprecates
    dep_res = client.post(
        f"/api/v1/glossary/{term_id}/deprecate",
        json={"deprecation_reason": "Data steward routine retirement."},
        headers=steward_headers,
    )
    assert dep_res.status_code == 200
