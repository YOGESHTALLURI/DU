"""
Unit tests for Wave 1 Slice 7: Enterprise Business Glossary Service (CF-V1-E14-01).
"""
import pytest
import uuid
from backend.models.canonical_model import CanonicalModel, CanonicalField
from backend.models.schema import SchemaDataTypeEnum
from backend.services.canonical_model_service import CanonicalModelService


@pytest.fixture(autouse=True)
def seed_canonical(db):
    """Ensure canonical reference models are present in test DB."""
    service = CanonicalModelService(db)
    service.seed_default_models_if_needed()
    db.commit()


def test_create_glossary_term_draft(client, steward_headers):
    payload = {
        "name": "Patient Medical Record Number",
        "acronym": "MRN",
        "synonyms": ["Hospital Patient ID", "Chart Number"],
        "domain": "Clinical",
        "definition": "A unique internal identification number assigned to a patient by a single clinical healthcare facility.",
        "clinical_context": "Used in local EMR systems before enterprise identity crosswalking.",
        "phi_classification": "CONFIRMED_PHI",
        "code_set": "NONE",
    }
    res = client.post("/api/v1/glossary", json=payload, headers=steward_headers)
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "Patient Medical Record Number"
    assert data["normalized_name"] == "patient medical record number"
    assert data["status"] == "DRAFT"
    assert data["phi_classification"] == "CONFIRMED_PHI"
    assert data["version"] == 1
    assert data["linked_canonical_fields_count"] == 0


def test_duplicate_term_name_case_insensitive(client, steward_headers):
    payload = {
        "name": "Health Insurance Policy Number",
        "domain": "Eligibility",
        "definition": "Identifier for the member health benefit policy.",
    }
    res1 = client.post("/api/v1/glossary", json=payload, headers=steward_headers)
    assert res1.status_code == 201

    # Attempt duplicate with different casing and whitespace
    dup_payload = {
        "name": "  HEALTH INSURANCE policy   number ",
        "domain": "Eligibility",
        "definition": "Duplicate definition.",
    }
    res2 = client.post("/api/v1/glossary", json=dup_payload, headers=steward_headers)
    assert res2.status_code == 409
    assert "already exists" in res2.json()["detail"].lower()


def test_update_term_metadata(client, steward_headers):
    payload = {
        "name": "Primary Care Physician NPI",
        "domain": "Provider",
        "definition": "National Provider Identifier of the member assigned primary care physician.",
    }
    created = client.post("/api/v1/glossary", json=payload, headers=steward_headers).json()
    term_id = created["id"]

    update_payload = {
        "acronym": "PCP NPI",
        "synonyms": ["Attending NPI", "Gatekeeper NPI"],
        "definition": "Authoritative 10-digit National Provider Identifier of the member assigned primary care provider.",
        "phi_classification": "POTENTIAL_PHI",
        "code_set": "NPI",
    }
    update_res = client.put(f"/api/v1/glossary/{term_id}", json=update_payload, headers=steward_headers)
    assert update_res.status_code == 200
    updated = update_res.json()
    assert updated["acronym"] == "PCP NPI"
    assert "Attending NPI" in updated["synonyms"]
    assert updated["code_set"] == "NPI"
    assert updated["version"] == 2


def test_term_approval_lifecycle(client, steward_headers):
    payload = {
        "name": "Inpatient Admission Timestamp",
        "domain": "Clinical",
        "definition": "Exact ISO-8601 date and time an inpatient admission begins.",
    }
    term = client.post("/api/v1/glossary", json=payload, headers=steward_headers).json()
    assert term["status"] == "DRAFT"

    approve_res = client.post(f"/api/v1/glossary/{term['id']}/approve", headers=steward_headers)
    assert approve_res.status_code == 200
    approved = approve_res.json()
    assert approved["status"] == "APPROVED"
    assert approved["version"] == 2


def test_term_deprecation_requires_reason(client, steward_headers):
    payload = {
        "name": "Legacy Claim Tracking Flag",
        "domain": "Claims",
        "definition": "Obsolete internal tracking indicator from legacy claims system.",
    }
    term = client.post("/api/v1/glossary", json=payload, headers=steward_headers).json()
    term_id = term["id"]

    # Approve first
    client.post(f"/api/v1/glossary/{term_id}/approve", headers=steward_headers)

    # Attempt deprecation with empty reason
    dep_res = client.post(f"/api/v1/glossary/{term_id}/deprecate", json={"deprecation_reason": "   "}, headers=steward_headers)
    assert dep_res.status_code in [400, 422]


def test_term_deprecation_success(client, steward_headers):
    payload = {
        "name": "Legacy Diagnostic Grouping Code",
        "domain": "Clinical",
        "definition": "Legacy DRG classification superseded by modern MS-DRG.",
    }
    term = client.post("/api/v1/glossary", json=payload, headers=steward_headers).json()
    term_id = term["id"]
    client.post(f"/api/v1/glossary/{term_id}/approve", headers=steward_headers)

    dep_res = client.post(
        f"/api/v1/glossary/{term_id}/deprecate",
        json={"deprecation_reason": "Replaced by standard MS-DRG 2026 taxonomy"},
        headers=steward_headers,
    )
    assert dep_res.status_code == 200
    deprecated = dep_res.json()
    assert deprecated["status"] == "DEPRECATED"
    assert deprecated["deprecation_reason"] == "Replaced by standard MS-DRG 2026 taxonomy"


def test_deprecated_term_cannot_be_updated(client, steward_headers):
    payload = {
        "name": "Obsolete Encounter Room Code",
        "domain": "Clinical",
        "definition": "Old room number classification.",
    }
    term = client.post("/api/v1/glossary", json=payload, headers=steward_headers).json()
    term_id = term["id"]
    client.post(f"/api/v1/glossary/{term_id}/approve", headers=steward_headers)
    client.post(f"/api/v1/glossary/{term_id}/deprecate", json={"deprecation_reason": "Outdated"}, headers=steward_headers)

    edit_res = client.put(f"/api/v1/glossary/{term_id}", json={"definition": "Try to change"}, headers=steward_headers)
    assert edit_res.status_code == 400
    assert "cannot edit deprecated" in edit_res.json()["detail"].lower()


def test_delete_draft_term_success(client, steward_headers):
    payload = {
        "name": "Draft Temporary Term",
        "domain": "Common",
        "definition": "Temporary draft concept that is discarded.",
    }
    term = client.post("/api/v1/glossary", json=payload, headers=steward_headers).json()
    term_id = term["id"]

    del_res = client.delete(f"/api/v1/glossary/{term_id}", headers=steward_headers)
    assert del_res.status_code == 200

    # Ensure 404
    get_res = client.get(f"/api/v1/glossary/{term_id}", headers=steward_headers)
    assert get_res.status_code == 404


def test_delete_approved_term_rejected(client, steward_headers):
    payload = {
        "name": "Permanent Approved Standard Term",
        "domain": "Eligibility",
        "definition": "Standard enterprise term that cannot be deleted.",
    }
    term = client.post("/api/v1/glossary", json=payload, headers=steward_headers).json()
    term_id = term["id"]
    client.post(f"/api/v1/glossary/{term_id}/approve", headers=steward_headers)

    del_res = client.delete(f"/api/v1/glossary/{term_id}", headers=steward_headers)
    assert del_res.status_code == 400
    assert "only draft terms may be deleted" in del_res.json()["detail"].lower()


def test_link_canonical_field_success(client, db, steward_headers):
    payload = {
        "name": "Health Plan Enrollee Identifier",
        "domain": "Eligibility",
        "definition": "The identifier of the subscriber or member.",
    }
    term = client.post("/api/v1/glossary", json=payload, headers=steward_headers).json()
    term_id = term["id"]

    c_field = db.query(CanonicalField).filter(CanonicalField.field_name == "member_id").first()
    assert c_field is not None

    link_res = client.post(f"/api/v1/glossary/{term_id}/links", json={"canonical_field_id": str(c_field.id)}, headers=steward_headers)
    assert link_res.status_code == 201
    link_data = link_res.json()
    assert link_data["canonical_field_name"] == "member_id"
    assert link_data["canonical_model_name"] in ["Member", "Claim"]

    # Verify term has link
    term_detail = client.get(f"/api/v1/glossary/{term_id}", headers=steward_headers).json()
    assert term_detail["linked_canonical_fields_count"] == 1
    assert term_detail["linked_canonical_fields"][0]["canonical_field_id"] == str(c_field.id)


def test_duplicate_canonical_link_rejected(client, db, steward_headers):
    payload = {
        "name": "Clinical Encounter ID Test",
        "domain": "Clinical",
        "definition": "Visit identifier.",
    }
    term = client.post("/api/v1/glossary", json=payload, headers=steward_headers).json()
    term_id = term["id"]

    c_field = db.query(CanonicalField).filter(CanonicalField.field_name == "encounter_id").first()
    assert c_field is not None

    res1 = client.post(f"/api/v1/glossary/{term_id}/links", json={"canonical_field_id": str(c_field.id)}, headers=steward_headers)
    assert res1.status_code == 201

    # Attempt duplicate
    res2 = client.post(f"/api/v1/glossary/{term_id}/links", json={"canonical_field_id": str(c_field.id)}, headers=steward_headers)
    assert res2.status_code == 409
    assert "already linked" in res2.json()["detail"].lower()


def test_unlink_canonical_field(client, db, steward_headers):
    payload = {
        "name": "Facility National Code",
        "domain": "Clinical",
        "definition": "Identification of the hospital facility.",
    }
    term = client.post("/api/v1/glossary", json=payload, headers=steward_headers).json()
    term_id = term["id"]

    c_field = db.query(CanonicalField).filter(CanonicalField.field_name == "facility_id").first()
    assert c_field is not None

    client.post(f"/api/v1/glossary/{term_id}/links", json={"canonical_field_id": str(c_field.id)}, headers=steward_headers)

    # Unlink
    unlink_res = client.delete(f"/api/v1/glossary/{term_id}/links/{c_field.id}", headers=steward_headers)
    assert unlink_res.status_code == 200
    assert "removed" in unlink_res.json()["message"].lower()

    # Verify count is 0
    term_detail = client.get(f"/api/v1/glossary/{term_id}", headers=steward_headers).json()
    assert term_detail["linked_canonical_fields_count"] == 0


def test_search_terms_by_query(client, steward_headers):
    client.post("/api/v1/glossary", json={
        "name": "Emergency Room Triage Level",
        "acronym": "ESI",
        "domain": "Clinical",
        "definition": "Emergency Severity Index acuity score from 1 (most urgent) to 5 (least urgent).",
    }, headers=steward_headers)

    res = client.get("/api/v1/glossary?query=Severity", headers=steward_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    found_names = [item["name"] for item in data["items"]]
    assert "Emergency Room Triage Level" in found_names


def test_filter_terms_by_domain_and_phi(client, steward_headers):
    client.post("/api/v1/glossary", json={
        "name": "Confidential Psychiatric Diagnosis",
        "domain": "Clinical",
        "definition": "Special diagnostic classification requiring enhanced confidentiality protection.",
        "phi_classification": "CONFIRMED_PHI",
    }, headers=steward_headers)

    res = client.get("/api/v1/glossary?domain=Clinical&phi=CONFIRMED_PHI", headers=steward_headers)
    assert res.status_code == 200
    data = res.json()
    assert all(item["domain"] == "Clinical" for item in data["items"])
    assert all(item["phi_classification"] == "CONFIRMED_PHI" for item in data["items"])


def test_filter_terms_by_code_set(client, steward_headers):
    client.post("/api/v1/glossary", json={
        "name": "Standard Lab Serum Glucose",
        "domain": "Clinical",
        "definition": "Blood serum glucose observation measurement code.",
        "code_set": "LOINC",
    }, headers=steward_headers)

    res = client.get("/api/v1/glossary?code_set=LOINC", headers=steward_headers)
    assert res.status_code == 200
    data = res.json()
    assert any(item["name"] == "Standard Lab Serum Glucose" for item in data["items"])
    assert all(item["code_set"] == "LOINC" for item in data["items"])


def test_seed_glossary_terms_bootstrap(client, steward_headers):
    res = client.post("/api/v1/glossary/seed/bootstrap", headers=steward_headers)
    assert res.status_code == 200
    assert "count" in res.json()

    # Search without filters should return seeded items
    list_res = client.get("/api/v1/glossary", headers=steward_headers)
    assert list_res.status_code == 200
    data = list_res.json()
    assert data["total"] >= 14
    term_names = [item["name"] for item in data["items"]]
    assert "Member Identifier" in term_names
    assert "Date of Birth" in term_names
    assert "Claim Identifier" in term_names
    assert "National Provider Identifier" in term_names
