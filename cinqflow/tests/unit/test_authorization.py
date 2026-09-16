"""
Authorization Test Suite — Wave 0

Verifies Phase 3 requirements:
- MockAuthProvider credentials & token generation
- Server-side role enforcement (ENGINEER vs READ_ONLY)
- Missing / invalid token returns 401 Unauthorized
- READ_ONLY role attempting create/update returns 403 Forbidden
- ENGINEER role allowed to perform privileged actions
- Verification that authorization is strictly enforced at API layer, not UI
"""
import pytest
from fastapi import APIRouter, Depends, status
from fastapi.testclient import TestClient
from backend.main import app
from backend.core.security import get_current_user, require_engineer, require_any_role, CurrentUser

# Create a temporary test router to verify security dependencies in isolation
test_auth_router = APIRouter(prefix="/api/v1/test-auth", tags=["TestAuth"])


@test_auth_router.get("/public")
def public_endpoint():
    return {"status": "public_ok"}


@test_auth_router.get("/protected-view")
def protected_view_endpoint(current_user: CurrentUser = Depends(require_any_role)):
    return {"status": "view_ok", "user": current_user.email, "roles": current_user.roles}


@test_auth_router.post("/privileged-create")
def privileged_create_endpoint(current_user: CurrentUser = Depends(require_engineer)):
    return {"status": "created_ok", "user": current_user.email}


@test_auth_router.put("/privileged-update")
def privileged_update_endpoint(current_user: CurrentUser = Depends(require_engineer)):
    return {"status": "updated_ok", "user": current_user.email}


app.include_router(test_auth_router)


def test_public_endpoint_accessible_without_token(client):
    res = client.get("/api/v1/test-auth/public")
    assert res.status_code == 200
    assert res.json()["status"] == "public_ok"


def test_protected_endpoint_without_token_rejected_401(client):
    res = client.get("/api/v1/test-auth/protected-view")
    assert res.status_code == 401
    assert "Authentication required" in res.json()["detail"]


def test_protected_endpoint_with_invalid_token_rejected_401(client):
    headers = {"Authorization": "Bearer invalid.token.signature"}
    res = client.get("/api/v1/test-auth/protected-view", headers=headers)
    assert res.status_code == 401
    assert "Invalid or expired token" in res.json()["detail"]


def test_readonly_user_can_access_view_endpoints(client, readonly_headers):
    res = client.get("/api/v1/test-auth/protected-view", headers=readonly_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "view_ok"
    assert "READ_ONLY" in res.json()["roles"]


def test_readonly_user_cannot_create_rejected_403(client, readonly_headers):
    """Server-side enforcement: READ_ONLY role cannot execute create."""
    res = client.post("/api/v1/test-auth/privileged-create", headers=readonly_headers)
    assert res.status_code == 403
    assert "ENGINEER role required" in res.json()["detail"]


def test_readonly_user_cannot_update_rejected_403(client, readonly_headers):
    """Server-side enforcement: READ_ONLY role cannot execute update."""
    res = client.put("/api/v1/test-auth/privileged-update", headers=readonly_headers)
    assert res.status_code == 403
    assert "ENGINEER role required" in res.json()["detail"]


def test_engineer_user_can_access_view_and_privileged_endpoints(client, engineer_headers):
    """ENGINEER has full operational privileges."""
    res_view = client.get("/api/v1/test-auth/protected-view", headers=engineer_headers)
    assert res_view.status_code == 200

    res_create = client.post("/api/v1/test-auth/privileged-create", headers=engineer_headers)
    assert res_create.status_code == 200
    assert res_create.json()["status"] == "created_ok"

    res_update = client.put("/api/v1/test-auth/privileged-update", headers=engineer_headers)
    assert res_update.status_code == 200
    assert res_update.json()["status"] == "updated_ok"


def test_auth_me_endpoint_returns_correct_profile(client, engineer_headers, readonly_headers):
    res_eng = client.get("/api/v1/auth/me", headers=engineer_headers)
    assert res_eng.status_code == 200
    assert res_eng.json()["roles"] == ["ENGINEER"]

    res_ro = client.get("/api/v1/auth/me", headers=readonly_headers)
    assert res_ro.status_code == 200
    assert res_ro.json()["roles"] == ["READ_ONLY"]
