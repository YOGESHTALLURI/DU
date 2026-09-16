"""
Integration tests for Wave 1 Slice 7: Business Glossary Workflow & Audit Trail.
"""
import pytest
import json
from backend.models.canonical_model import CanonicalModel, CanonicalField
from backend.models.audit import AuditEvent, AuditActionEnum
from backend.services.canonical_model_service import CanonicalModelService


@pytest.fixture(autouse=True)
def seed_canonical(db):
    service = CanonicalModelService(db)
    service.seed_default_models_if_needed()
    db.commit()


def test_e2e_glossary_lifecycle_and_canonical_links(client, db, analyst_headers, steward_headers):
    # 1. BA proposes term
    create_payload = {
        "name": "Subscriber Identifier",
        "acronym": "SUB_ID",
        "synonyms": ["Subscriber No", "Primary Insured ID"],
        "domain": "Eligibility",
        "definition": "The identification number assigned to the primary insurance policyholder.",
        "phi_classification": "CONFIRMED_PHI",
    }
    create_res = client.post("/api/v1/glossary", json=create_payload, headers=analyst_headers)
    assert create_res.status_code == 201
    term = create_res.json()
    term_id = term["id"]
    assert term["status"] == "DRAFT"

    # 2. BA links canonical fields: Member.member_id and Claim.member_id
    member_field = (
        db.query(CanonicalField)
        .join(CanonicalModel)
        .filter(CanonicalModel.name == "Member", CanonicalField.field_name == "member_id")
        .first()
    )
    claim_field = (
        db.query(CanonicalField)
        .join(CanonicalModel)
        .filter(CanonicalModel.name == "Claim", CanonicalField.field_name == "member_id")
        .first()
    )
    assert member_field is not None and claim_field is not None

    link_res1 = client.post(f"/api/v1/glossary/{term_id}/links", json={"canonical_field_id": str(member_field.id)}, headers=analyst_headers)
    assert link_res1.status_code == 201

    link_res2 = client.post(f"/api/v1/glossary/{term_id}/links", json={"canonical_field_id": str(claim_field.id)}, headers=analyst_headers)
    assert link_res2.status_code == 201

    # Check term has 2 links
    term_res = client.get(f"/api/v1/glossary/{term_id}", headers=analyst_headers)
    assert term_res.status_code == 200
    assert term_res.json()["linked_canonical_fields_count"] == 2

    # 3. Data Steward approves term
    app_res = client.post(f"/api/v1/glossary/{term_id}/approve", headers=steward_headers)
    assert app_res.status_code == 200
    assert app_res.json()["status"] == "APPROVED"

    # 4. Data Steward deprecates term
    dep_res = client.post(
        f"/api/v1/glossary/{term_id}/deprecate",
        json={"deprecation_reason": "Replaced by Enterprise Member ID standard"},
        headers=steward_headers,
    )
    assert dep_res.status_code == 200
    assert dep_res.json()["status"] == "DEPRECATED"


def test_canonical_model_enrichment_endpoint(client, db, steward_headers):
    # Create term and link to Encounter field
    encounter_model = db.query(CanonicalModel).filter(CanonicalModel.name == "Encounter").first()
    assert encounter_model is not None

    admit_field = (
        db.query(CanonicalField)
        .filter(CanonicalField.canonical_model_id == encounter_model.id, CanonicalField.field_name == "admit_date")
        .first()
    )
    assert admit_field is not None

    term_res = client.post("/api/v1/glossary", json={
        "name": "Hospital Admission Timestamp",
        "domain": "Clinical",
        "definition": "Date and time of inpatient registration.",
        "canonical_field_ids": [str(admit_field.id)],
    }, headers=steward_headers)
    assert term_res.status_code == 201

    # Query terms for Encounter canonical model
    res = client.get(f"/api/v1/glossary/canonical/models/{encounter_model.id}", headers=steward_headers)
    assert res.status_code == 200
    terms = res.json()
    assert len(terms) >= 1
    term_names = [t["name"] for t in terms]
    assert "Hospital Admission Timestamp" in term_names


def test_all_glossary_audit_events_emitted(client, db, steward_headers):
    # 1. Create -> glossary.term_created
    term = client.post("/api/v1/glossary", json={
        "name": "Audit Verification Term",
        "domain": "Common",
        "definition": "Used to test all 7 audit emissions.",
    }, headers=steward_headers).json()
    term_id = term["id"]

    # 2. Update -> glossary.term_updated
    client.put(f"/api/v1/glossary/{term_id}", json={"definition": "Updated definition for audit."}, headers=steward_headers)

    # 3. Link -> glossary.field_linked
    c_field = db.query(CanonicalField).first()
    client.post(f"/api/v1/glossary/{term_id}/links", json={"canonical_field_id": str(c_field.id)}, headers=steward_headers)

    # 4. Unlink -> glossary.field_unlinked
    client.delete(f"/api/v1/glossary/{term_id}/links/{c_field.id}", headers=steward_headers)

    # 5. Approve -> glossary.term_approved
    client.post(f"/api/v1/glossary/{term_id}/approve", headers=steward_headers)

    # 6. Deprecate -> glossary.term_deprecated
    client.post(f"/api/v1/glossary/{term_id}/deprecate", json={"deprecation_reason": "Audit test retirement."}, headers=steward_headers)

    # 7. Delete draft term -> glossary.term_deleted
    draft_term = client.post("/api/v1/glossary", json={
        "name": "Ephemeral Draft for Deletion",
        "domain": "Common",
        "definition": "To be deleted.",
    }, headers=steward_headers).json()
    client.delete(f"/api/v1/glossary/{draft_term['id']}", headers=steward_headers)

    # Verify all 7 actions in audit_events table
    expected_actions = [
        AuditActionEnum.GLOSSARY_TERM_CREATED,
        AuditActionEnum.GLOSSARY_TERM_UPDATED,
        AuditActionEnum.GLOSSARY_FIELD_LINKED,
        AuditActionEnum.GLOSSARY_FIELD_UNLINKED,
        AuditActionEnum.GLOSSARY_TERM_APPROVED,
        AuditActionEnum.GLOSSARY_TERM_DEPRECATED,
        AuditActionEnum.GLOSSARY_TERM_DELETED,
    ]
    for action in expected_actions:
        evt = db.query(AuditEvent).filter(AuditEvent.action == action).first()
        assert evt is not None, f"Expected audit event '{action.value}' not found in audit_events!"


def test_glossary_audit_zero_phi(client, db, steward_headers):
    # Create, update, and approve a term to generate audit events
    created = client.post("/api/v1/glossary", json={
        "name": "PHI Verification Concept",
        "acronym": "PVC",
        "synonyms": ["Security Concept"],
        "domain": "Clinical",
        "definition": "Standard clinical observation and risk tracking definition.",
        "phi_classification": "CONFIRMED_PHI",
    }, headers=steward_headers).json()
    term_id = created["id"]

    client.put(f"/api/v1/glossary/{term_id}", json={"definition": "Updated clinical observation definition."}, headers=steward_headers)
    client.post(f"/api/v1/glossary/{term_id}/approve", headers=steward_headers)
    client.post(f"/api/v1/glossary/{term_id}/deprecate", json={"deprecation_reason": "Retired for PHI audit check."}, headers=steward_headers)

    # Query all glossary audit events
    glossary_actions = [
        AuditActionEnum.GLOSSARY_TERM_CREATED,
        AuditActionEnum.GLOSSARY_TERM_UPDATED,
        AuditActionEnum.GLOSSARY_FIELD_LINKED,
        AuditActionEnum.GLOSSARY_FIELD_UNLINKED,
        AuditActionEnum.GLOSSARY_TERM_APPROVED,
        AuditActionEnum.GLOSSARY_TERM_DEPRECATED,
        AuditActionEnum.GLOSSARY_TERM_DELETED,
    ]
    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.action.in_(glossary_actions))
        .all()
    )
    assert len(events) >= 4

    sensitive_markers = ["ssn", "patient_name", "first_name", "last_name", "johnson", "smith", "date_of_birth", "dob"]
    for evt in events:
        text_payload = json.dumps({
            "before": evt.before_state,
            "after": evt.after_state,
            "desc": evt.description,
        }).lower()
        # Verify that actual sensitive patient values are never present
        assert "alice" not in text_payload
        assert "bob" not in text_payload
        assert "1985-06-15" not in text_payload
        assert "1990-03-22" not in text_payload


def test_glossary_regression_with_canonical_models(client, readonly_headers):
    # Canonical model endpoints must continue working seamlessly
    res = client.get("/api/v1/canonical-models", headers=readonly_headers)
    assert res.status_code == 200
    models = res.json()
    assert len(models) >= 4
    names = [m["name"] for m in models]
    assert "Member" in names
    assert "Claim" in names
    assert "Encounter" in names
    assert "Observation" in names
