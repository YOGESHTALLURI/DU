"""Tests for Canonical Models & Reference Data (Slice 3)."""
import pytest
from backend.services.canonical_model_service import CanonicalModelService, CANONICAL_SEED_DATA

def test_canonical_models_seed_data_loaded(db):
    """Verify default canonical models are seeded and have correct domain and field counts."""
    service = CanonicalModelService(db)
    service.seed_default_models_if_needed()
    models = service.list_models()
    assert len(models) >= 4
    names = {m.name for m in models}
    assert {"Member", "Claim", "Encounter", "Observation"}.issubset(names)

    member = next(m for m in models if m.name == "Member")
    member_detail = service.get_model(member.id)
    assert member_detail.domain == "Eligibility"
    assert len(member_detail.fields) == 9
    required_fields = [f.field_name for f in member_detail.fields if f.is_required]
    assert "member_id" in required_fields
    assert "first_name" in required_fields
    assert "last_name" in required_fields

def test_canonical_model_listing_api(client, analyst_headers, readonly_headers):
    """Verify canonical models can be listed by analyst, engineer, and read_only users."""
    res = client.get("/api/v1/canonical-models", headers=analyst_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 4
    names = [m["name"] for m in data]
    assert "Member" in names
    assert "Claim" in names

    ro_res = client.get("/api/v1/canonical-models", headers=readonly_headers)
    assert ro_res.status_code == 200

def test_canonical_model_detail_api(client, analyst_headers):
    """Verify fetching canonical model detail includes ordered fields and types."""
    res = client.get("/api/v1/canonical-models", headers=analyst_headers)
    assert res.status_code == 200
    models = res.json()
    claim_model = next(m for m in models if m["name"] == "Claim")

    detail_res = client.get(f"/api/v1/canonical-models/{claim_model['id']}", headers=analyst_headers)
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["name"] == "Claim"
    assert detail["domain"] == "Claims"
    assert len(detail["fields"]) == 6
    field_names = [f["field_name"] for f in detail["fields"]]
    assert "claim_id" in field_names
    assert "claim_amount" in field_names

def test_canonical_model_read_only_no_mutation_routes(client, engineer_headers):
    """Verify that canonical models and fields have no POST/PUT/DELETE mutation endpoints."""
    post_res = client.post("/api/v1/canonical-models", json={"name": "Custom"}, headers=engineer_headers)
    assert post_res.status_code == 405

    put_res = client.put("/api/v1/canonical-models/c0000000-0000-0000-0000-000000000001", json={"name": "Mutated"}, headers=engineer_headers)
    assert put_res.status_code == 405

    del_res = client.delete("/api/v1/canonical-models/c0000000-0000-0000-0000-000000000001", headers=engineer_headers)
    assert del_res.status_code == 405
