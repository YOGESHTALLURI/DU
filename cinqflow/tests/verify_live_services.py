"""
Live HTTP Verification Script for CINQFLOW Wave 0

Performs live HTTP socket requests against running servers:
- Backend health: GET http://127.0.0.1:8000/health
- API Docs: GET http://127.0.0.1:8000/docs
- Frontend: GET http://localhost:3000/
- Authentication:
    * Login Engineer -> verify token & ENGINEER role
    * Login Read-Only -> verify token & READ_ONLY role
- Authorization:
    * Read-Only can read GET /api/v1/feeds (200)
    * Read-Only cannot create POST /api/v1/feeds (403)
    * Read-Only cannot update PUT /api/v1/contracts/{id} (403)
    * Read-Only cannot execute POST /api/v1/pipeline/batches/{id}/execute (403)
"""
import httpx
import sys

BACKEND_URL = "http://127.0.0.1:8000"
FRONTEND_URL = "http://localhost:3000"


def run_verification():
    print("=== LIVE SERVICE VERIFICATION ===")
    client = httpx.Client(timeout=10.0)

    # 1. Health endpoint
    r_health = client.get(f"{BACKEND_URL}/health")
    assert r_health.status_code == 200, f"Health failed: {r_health.status_code}"
    health_data = r_health.json()
    print(f"1. Health endpoint: {r_health.status_code} OK -> {health_data}")

    # 2. API Docs
    r_docs = client.get(f"{BACKEND_URL}/docs")
    assert r_docs.status_code == 200, f"Docs failed: {r_docs.status_code}"
    print(f"2. OpenAPI /docs: {r_docs.status_code} OK (HTML returned: {len(r_docs.text)} bytes)")

    # 3. Frontend Home
    r_fe = client.get(f"{FRONTEND_URL}/")
    assert r_fe.status_code == 200, f"Frontend home failed: {r_fe.status_code}"
    print(f"3. Frontend Home (3000): {r_fe.status_code} OK")

    # 4. Login Engineer
    r_eng_login = client.post(
        f"{BACKEND_URL}/api/v1/auth/login",
        json={"credential": "engineer:engineer123"},
    )
    assert r_eng_login.status_code == 200, f"Engineer login failed: {r_eng_login.status_code}"
    eng_data = r_eng_login.json()
    eng_token = eng_data["access_token"]
    assert "ENGINEER" in eng_data["roles"]
    print(f"4. Engineer login: {r_eng_login.status_code} OK -> User: {eng_data['email']}, Roles: {eng_data['roles']}")

    # 5. Login Read-Only
    r_ro_login = client.post(
        f"{BACKEND_URL}/api/v1/auth/login",
        json={"credential": "readonly:readonly123"},
    )
    assert r_ro_login.status_code == 200, f"Read-Only login failed: {r_ro_login.status_code}"
    ro_data = r_ro_login.json()
    ro_token = ro_data["access_token"]
    assert "READ_ONLY" in ro_data["roles"]
    print(f"5. Read-Only login: {r_ro_login.status_code} OK -> User: {ro_data['email']}, Roles: {ro_data['roles']}")

    # 6. Authorization: Read-Only can read
    headers_ro = {"Authorization": f"Bearer {ro_token}"}
    r_ro_get = client.get(f"{BACKEND_URL}/api/v1/feeds", headers=headers_ro)
    assert r_ro_get.status_code == 200, f"Read-Only read failed: {r_ro_get.status_code}"
    print(f"6. Read-Only GET /api/v1/feeds: {r_ro_get.status_code} OK (Items: {len(r_ro_get.json())})")

    # 7. Authorization: Read-Only CANNOT create
    r_ro_create = client.post(
        f"{BACKEND_URL}/api/v1/feeds",
        json={"name": "HACK_FEED", "domain": "TEST", "landing_folder": "./", "filename_pattern": "*.csv"},
        headers=headers_ro,
    )
    assert r_ro_create.status_code == 403, f"Read-Only create was not rejected: {r_ro_create.status_code}"
    print(f"7. Read-Only POST /api/v1/feeds: {r_ro_create.status_code} FORBIDDEN (detail: {r_ro_create.json()['detail']})")

    # 8. Authorization: Read-Only CANNOT update
    # Fetch first contract
    r_contracts = client.get(f"{BACKEND_URL}/api/v1/contracts", headers=headers_ro)
    contracts = r_contracts.json()
    if contracts:
        c_id = contracts[0]["id"]
        r_ro_update = client.put(
            f"{BACKEND_URL}/api/v1/contracts/{c_id}",
            json={"description": "Hacked description"},
            headers=headers_ro,
        )
        assert r_ro_update.status_code == 403, f"Read-Only update was not rejected: {r_ro_update.status_code}"
        print(f"8. Read-Only PUT /api/v1/contracts: {r_ro_update.status_code} FORBIDDEN (detail: {r_ro_update.json()['detail']})")

    # 9. Authorization: Read-Only CANNOT execute pipeline
    r_ro_exec = client.post(
        f"{BACKEND_URL}/api/v1/pipeline/batches/00000000-0000-0000-0000-000000000000/execute",
        headers=headers_ro,
    )
    assert r_ro_exec.status_code == 403, f"Read-Only execute was not rejected: {r_ro_exec.status_code}"
    print(f"9. Read-Only POST /api/v1/pipeline/batches/.../execute: {r_ro_exec.status_code} FORBIDDEN (detail: {r_ro_exec.json()['detail']})")

    print("\nALL LIVE SERVICE AND AUTHORIZATION CHECKS PASSED!")


if __name__ == "__main__":
    run_verification()
