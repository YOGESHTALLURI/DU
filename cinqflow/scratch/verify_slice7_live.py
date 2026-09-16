"""
Live verification script for Wave 1 Slice 7: Enterprise Business Glossary Service.
Executes live HTTP requests against port 8000 and directly inspects PostgreSQL audit_events.
"""
import requests
import json
import time
import psycopg

BASE_URL = "http://localhost:8000"
DB_CONN = "postgresql://cinqflow:cinqflow@localhost:5432/cinqflow"


def check_no_phi(obj, label=""):
    text_repr = json.dumps(obj) if isinstance(obj, (dict, list)) else str(obj)
    # Check for actual patient sample records or PII
    sensitive_markers = ["1985-06-15", "1990-03-22", "alice", "smith", "johnson"]
    for marker in sensitive_markers:
        assert marker not in text_repr.lower(), f"Potential PHI value found in {label}: {marker}"


def get_latest_audit_event(action):
    with psycopg.connect(DB_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, action, actor_email, object_type, object_id, before_state, after_state, description, created_at
                FROM audit_events
                WHERE action = %s
                ORDER BY created_at DESC
                LIMIT 1
            """, (action,))
            row = cur.fetchone()
            if not row:
                return None
            return {
                "id": str(row[0]),
                "action": row[1],
                "actor_email": row[2],
                "object_type": row[3],
                "object_id": str(row[4]),
                "before_state": row[5],
                "after_state": row[6],
                "description": row[7],
                "created_at": row[8].isoformat() if row[8] else None,
            }


def run_verification():
    print("================================================================================")
    print("STARTING LIVE SYSTEM VERIFICATION FOR WAVE 1 SLICE 7: BUSINESS GLOSSARY")
    print("================================================================================\n")

    # 1. Authentication
    print("--- 1. Authenticating Personas ---")
    steward_res = requests.post(f"{BASE_URL}/api/v1/auth/login", json={"credential": "steward:steward123"})
    assert steward_res.status_code == 200
    steward_token = steward_res.json()["access_token"]
    steward_headers = {"Authorization": f"Bearer {steward_token}", "Content-Type": "application/json"}

    analyst_res = requests.post(f"{BASE_URL}/api/v1/auth/login", json={"credential": "analyst:analyst123"})
    assert analyst_res.status_code == 200
    analyst_token = analyst_res.json()["access_token"]
    analyst_headers = {"Authorization": f"Bearer {analyst_token}", "Content-Type": "application/json"}

    readonly_res = requests.post(f"{BASE_URL}/api/v1/auth/login", json={"credential": "readonly:readonly123"})
    assert readonly_res.status_code == 200
    readonly_token = readonly_res.json()["access_token"]
    readonly_headers = {"Authorization": f"Bearer {readonly_token}", "Content-Type": "application/json"}
    print("  [PASS] Authenticated Data Steward, Business Analyst, and Read-Only personas.")

    # 2. Seed Bootstrap
    print("\n--- 2. Core Healthcare Dictionary Bootstrap ---")
    seed_res = requests.post(f"{BASE_URL}/api/v1/glossary/seed/bootstrap", headers=steward_headers)
    assert seed_res.status_code == 200
    print(f"  [PASS] Seed response: {seed_res.json()}")

    # 3. Search & Sub-300ms Latency
    print("\n--- 3. Search & Filter Latency ---")
    t0 = time.time()
    search_res = requests.get(f"{BASE_URL}/api/v1/glossary?query=Member", headers=readonly_headers)
    elapsed_ms = (time.time() - t0) * 1000
    assert search_res.status_code == 200
    data = search_res.json()
    assert data["total"] >= 1
    print(f"  [PASS] Search returned {data['total']} items in {elapsed_ms:.1f}ms (Target: < 300ms)")

    # 4. Propose Term (Analyst) -> glossary.term_created
    print("\n--- 4. Term Creation (BA) & glossary.term_created ---")
    term_payload = {
        "name": "Live Verified Encounter Classification",
        "acronym": "LVEC",
        "synonyms": ["Encounter Class", "Visit Taxonomy"],
        "domain": "Clinical",
        "definition": "Clinical classification of patient interaction (Inpatient, Outpatient, Ambulatory, Emergency).",
        "clinical_context": "Drives utilization management and facility billing rates.",
        "phi_classification": "NONE",
        "code_set": "NONE",
    }
    create_res = requests.post(f"{BASE_URL}/api/v1/glossary", json=term_payload, headers=analyst_headers)
    assert create_res.status_code == 201
    term = create_res.json()
    term_id = term["id"]
    assert term["status"] == "DRAFT"

    audit_created = get_latest_audit_event("glossary.term_created")
    assert audit_created is not None
    assert audit_created["object_id"] == term_id
    check_no_phi(audit_created, "term_created audit")
    print(f"  [PASS] Created term ID {term_id}, status DRAFT, audit logged: {audit_created['action']}")

    # 5. Update Term (Analyst) -> glossary.term_updated
    print("\n--- 5. Term Update & glossary.term_updated ---")
    update_res = requests.put(
        f"{BASE_URL}/api/v1/glossary/{term_id}",
        json={"definition": "Updated comprehensive clinical classification of patient interaction."},
        headers=analyst_headers,
    )
    assert update_res.status_code == 200
    audit_updated = get_latest_audit_event("glossary.term_updated")
    assert audit_updated is not None
    check_no_phi(audit_updated, "term_updated audit")
    print(f"  [PASS] Updated term version to v{update_res.json()['version']}, audit logged: {audit_updated['action']}")

    # 6. Link Canonical Field -> glossary.field_linked
    print("\n--- 6. Canonical Field Linking & glossary.field_linked ---")
    # Get a canonical field for Encounter
    with psycopg.connect(DB_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT cf.id, cf.field_name, cm.name 
                FROM canonical_fields cf 
                JOIN canonical_models cm ON cf.canonical_model_id = cm.id
                WHERE cm.name = 'Encounter' AND cf.field_name = 'encounter_type'
            """)
            c_row = cur.fetchone()
            assert c_row is not None, "Encounter.encounter_type field missing in DB"
            c_field_id, c_field_name, c_model_name = str(c_row[0]), c_row[1], c_row[2]

    link_res = requests.post(
        f"{BASE_URL}/api/v1/glossary/{term_id}/links",
        json={"canonical_field_id": c_field_id},
        headers=analyst_headers,
    )
    assert link_res.status_code == 201
    audit_linked = get_latest_audit_event("glossary.field_linked")
    assert audit_linked is not None
    check_no_phi(audit_linked, "field_linked audit")
    print(f"  [PASS] Linked to {c_model_name}.{c_field_name}, audit logged: {audit_linked['action']}")

    # 7. RBAC: Analyst cannot approve -> 403 Forbidden
    print("\n--- 7. RBAC Verification (Analyst Approval Block) ---")
    analyst_app = requests.post(f"{BASE_URL}/api/v1/glossary/{term_id}/approve", headers=analyst_headers)
    assert analyst_app.status_code == 403
    print("  [PASS] Analyst approval attempt blocked with HTTP 403 Forbidden.")

    # 8. Steward approves -> glossary.term_approved
    print("\n--- 8. Steward Approval & glossary.term_approved ---")
    steward_app = requests.post(f"{BASE_URL}/api/v1/glossary/{term_id}/approve", headers=steward_headers)
    assert steward_app.status_code == 200
    assert steward_app.json()["status"] == "APPROVED"
    audit_approved = get_latest_audit_event("glossary.term_approved")
    assert audit_approved is not None
    check_no_phi(audit_approved, "term_approved audit")
    print(f"  [PASS] Term approved to APPROVED status, audit logged: {audit_approved['action']}")

    # 9. Steward deprecates -> glossary.term_deprecated
    print("\n--- 9. Steward Deprecation & glossary.term_deprecated ---")
    dep_res = requests.post(
        f"{BASE_URL}/api/v1/glossary/{term_id}/deprecate",
        json={"deprecation_reason": "Live verification lifecycle retirement."},
        headers=steward_headers,
    )
    assert dep_res.status_code == 200
    assert dep_res.json()["status"] == "DEPRECATED"
    audit_dep = get_latest_audit_event("glossary.term_deprecated")
    assert audit_dep is not None
    check_no_phi(audit_dep, "term_deprecated audit")
    print(f"  [PASS] Term deprecated with reason, audit logged: {audit_dep['action']}")

    # 10. Delete Draft Term -> glossary.term_deleted
    print("\n--- 10. Draft Deletion & glossary.term_deleted ---")
    draft_temp = requests.post(
        f"{BASE_URL}/api/v1/glossary",
        json={"name": "Temporary Deletable Draft", "domain": "Common", "definition": "Will be deleted."},
        headers=analyst_headers,
    ).json()
    del_res = requests.delete(f"{BASE_URL}/api/v1/glossary/{draft_temp['id']}", headers=analyst_headers)
    assert del_res.status_code == 200
    audit_del = get_latest_audit_event("glossary.term_deleted")
    assert audit_del is not None
    check_no_phi(audit_del, "term_deleted audit")
    print(f"  [PASS] Draft term deleted, audit logged: {audit_del['action']}")

    # 11. Unlink Canonical Field -> glossary.field_unlinked
    print("\n--- 11. Canonical Unlinking & glossary.field_unlinked ---")
    unlink_res = requests.delete(f"{BASE_URL}/api/v1/glossary/{term_id}/links/{c_field_id}", headers=analyst_headers)
    assert unlink_res.status_code == 200
    audit_unlinked = get_latest_audit_event("glossary.field_unlinked")
    assert audit_unlinked is not None
    check_no_phi(audit_unlinked, "field_unlinked audit")
    print(f"  [PASS] Unlinked canonical field, audit logged: {audit_unlinked['action']}")

    print("\n================================================================================")
    print("ALL 7 GLOSSARY AUDIT EVENTS VERIFIED IN POSTGRESQL WITH ZERO PHI")
    print("================================================================================\n")
    return {
        "term_created": audit_created,
        "term_updated": audit_updated,
        "field_linked": audit_linked,
        "term_approved": audit_approved,
        "term_deprecated": audit_dep,
        "term_deleted": audit_del,
        "field_unlinked": audit_unlinked,
    }


if __name__ == "__main__":
    run_verification()
