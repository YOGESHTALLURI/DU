"""Security & RBAC Unit Tests for Wave 1 Slice 5 (Four-Eyes Principle & Access Control)."""
import uuid
import pytest
from tests.unit.test_sandbox_executor import _setup_feed_with_full_stack


def test_four_eyes_principle_rejects_author_self_approval(client, engineer_headers, analyst_headers):
    """Four-Eyes Principle: An engineer who submits an activation request CANNOT approve it."""
    feed_id, sample_id, schema_id, schema_ver_id, mapping_id, field_map = _setup_feed_with_full_stack(
        client, engineer_headers, analyst_headers
    )
    # Run sandbox test
    client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=engineer_headers)

    # Engineer 1 submits
    sub_res = client.post(
        f"/api/v1/onboarding/feed/{feed_id}/submit-approval",
        json={"notes": "Submitted by Engineer 1"},
        headers=engineer_headers,
    )
    assert sub_res.status_code == 201

    # Engineer 1 attempts to approve their own submission -> 403 Forbidden
    app_res = client.post(
        f"/api/v1/onboarding/feed/{feed_id}/approve",
        json={"decision_notes": "Self-approving my own submission"},
        headers=engineer_headers,
    )
    assert app_res.status_code == 403
    assert "four-eyes principle violation" in app_res.json()["detail"].lower()


def test_four_eyes_principle_allows_different_engineer_approval(client, engineer_headers, engineer2_headers, analyst_headers):
    """Four-Eyes Principle: A different independent engineer CAN review and approve."""
    feed_id, sample_id, schema_id, schema_ver_id, mapping_id, field_map = _setup_feed_with_full_stack(
        client, engineer_headers, analyst_headers
    )
    client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=engineer_headers)

    # Engineer 1 submits
    sub_res = client.post(
        f"/api/v1/onboarding/feed/{feed_id}/submit-approval",
        json={"notes": "Submitted by Engineer 1"},
        headers=engineer_headers,
    )
    assert sub_res.status_code == 201

    # Engineer 2 approves -> 200 OK
    app_res = client.post(
        f"/api/v1/onboarding/feed/{feed_id}/approve",
        json={"decision_notes": "Second engineer independent sign-off."},
        headers=engineer2_headers,
    )
    assert app_res.status_code == 200
    assert app_res.json()["status"] == "ACTIVE"


def test_business_analyst_can_submit_but_cannot_approve(client, engineer_headers, analyst_headers):
    """A Business Analyst can author and submit a feed, but cannot approve activation."""
    feed_id, sample_id, schema_id, schema_ver_id, mapping_id, field_map = _setup_feed_with_full_stack(
        client, engineer_headers, analyst_headers
    )
    client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=analyst_headers)

    # Analyst submits -> 201 Created
    sub_res = client.post(
        f"/api/v1/onboarding/feed/{feed_id}/submit-approval",
        json={"notes": "Analyst submission for activation"},
        headers=analyst_headers,
    )
    assert sub_res.status_code == 201

    # Analyst attempts to approve -> 403 Forbidden
    app_res = client.post(
        f"/api/v1/onboarding/feed/{feed_id}/approve",
        json={"decision_notes": "Analyst attempting approval"},
        headers=analyst_headers,
    )
    assert app_res.status_code == 403
    assert "engineer role required" in app_res.json()["detail"].lower()


def test_read_only_forbidden_on_all_mutation_endpoints(client, engineer_headers, analyst_headers, readonly_headers):
    """READ_ONLY role receives 403 Forbidden on all mutation endpoints."""
    feed_id, sample_id, schema_id, schema_ver_id, mapping_id, field_map = _setup_feed_with_full_stack(
        client, engineer_headers, analyst_headers
    )

    # 1. READ_ONLY cannot run sandbox test
    sb_res = client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=readonly_headers)
    assert sb_res.status_code == 403

    # 2. READ_ONLY cannot submit for approval
    sub_res = client.post(
        f"/api/v1/onboarding/feed/{feed_id}/submit-approval",
        json={"notes": "Read only submission"},
        headers=readonly_headers,
    )
    assert sub_res.status_code == 403

    # 3. READ_ONLY cannot approve
    app_res = client.post(
        f"/api/v1/onboarding/feed/{feed_id}/approve",
        json={"decision_notes": "Read only approval"},
        headers=readonly_headers,
    )
    assert app_res.status_code == 403

    # 4. READ_ONLY cannot reject
    rej_res = client.post(
        f"/api/v1/onboarding/feed/{feed_id}/reject",
        json={"decision_notes": "Read only reject"},
        headers=readonly_headers,
    )
    assert rej_res.status_code == 403

    # But READ_ONLY CAN read the review packet
    pkt_res = client.get(f"/api/v1/onboarding/feed/{feed_id}/review-packet", headers=readonly_headers)
    assert pkt_res.status_code == 200
    assert pkt_res.json()["user_capabilities"]["can_run_test"] is False
    assert pkt_res.json()["user_capabilities"]["can_submit"] is False
    assert pkt_res.json()["user_capabilities"]["can_approve"] is False
    assert pkt_res.json()["user_capabilities"]["can_reject"] is False
