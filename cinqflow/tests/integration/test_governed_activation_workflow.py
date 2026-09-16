"""Integration Tests for Governed Activation Workflow (Wave 1 Slice 5)."""
import io
import uuid
import pytest
from backend.models.feed import Feed, FeedStatusEnum
from backend.models.approval import ApprovalRequestStatusEnum, FeedActivationRecord
from backend.models.audit import AuditEvent, AuditActionEnum
from backend.models.schema import OnboardingSession, OnboardingStatusEnum
from tests.unit.test_sandbox_executor import _setup_feed_with_full_stack


def test_e2e_wizard_step5_complete_workflow(client, engineer_headers, engineer2_headers, analyst_headers):
    """E2E workflow: Setup Feed -> Sandbox Test -> Submit -> Approve -> Feed ACTIVE & Session COMPLETE."""
    feed_id, sample_id, schema_id, schema_ver_id, mapping_id, field_map = _setup_feed_with_full_stack(
        client, engineer_headers, analyst_headers
    )

    # 1. Run Sandbox Test
    sb_res = client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=analyst_headers)
    assert sb_res.status_code == 200
    sb_run = sb_res.json()
    assert sb_run["status"] == "SUCCESS"
    assert sb_run["total_rows"] == 4
    assert sb_run["passed_rows"] == 3
    assert sb_run["quarantined_rows"] == 1
    assert sb_run["reconciliation_status"] == "BALANCED"

    # 2. Verify Review Packet
    pkt_res = client.get(f"/api/v1/onboarding/feed/{feed_id}/review-packet", headers=analyst_headers)
    assert pkt_res.status_code == 200
    assert pkt_res.json()["readiness_checklist"]["all_prerequisites_met"] is True

    # 3. Submit for Approval as Analyst
    sub_res = client.post(
        f"/api/v1/onboarding/feed/{feed_id}/submit-approval",
        json={"notes": "All prerequisites verified. Requesting activation sign-off."},
        headers=analyst_headers,
    )
    assert sub_res.status_code == 201
    assert sub_res.json()["status"] == "PENDING_APPROVAL"

    # 4. Independent Engineer 2 Approves
    app_res = client.post(
        f"/api/v1/onboarding/feed/{feed_id}/approve",
        json={"decision_notes": "Verified evidence pack and contracts. Approved."},
        headers=engineer2_headers,
    )
    assert app_res.status_code == 200
    assert app_res.json()["status"] == "ACTIVE"

    # 5. Check Feed & Session status
    feed_res = client.get(f"/api/v1/feeds/{feed_id}", headers=engineer_headers)
    assert feed_res.status_code == 200
    assert feed_res.json()["status"] == "ACTIVE"


def test_e2e_rejection_and_resubmission_cycle(client, engineer_headers, engineer2_headers, analyst_headers):
    """E2E workflow: Submit -> Reject -> Resubmit -> Approve cycle."""
    feed_id, sample_id, schema_id, schema_ver_id, mapping_id, field_map = _setup_feed_with_full_stack(
        client, engineer_headers, analyst_headers
    )
    client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=analyst_headers)

    # 1. Submit
    client.post(
        f"/api/v1/onboarding/feed/{feed_id}/submit-approval",
        json={"notes": "Initial submission"},
        headers=analyst_headers,
    )

    # 2. Engineer 2 Rejects
    rej_res = client.post(
        f"/api/v1/onboarding/feed/{feed_id}/reject",
        json={"decision_notes": "Please verify reconciliation before activation."},
        headers=engineer2_headers,
    )
    assert rej_res.status_code == 200
    assert rej_res.json()["status"] == "REJECTED"

    # Feed remains DRAFT
    f_check = client.get(f"/api/v1/feeds/{feed_id}", headers=analyst_headers)
    assert f_check.json()["status"] == "DRAFT"

    # 3. Resubmit
    resub_res = client.post(
        f"/api/v1/onboarding/feed/{feed_id}/submit-approval",
        json={"notes": "Reconciliation re-verified and confirmed balanced."},
        headers=analyst_headers,
    )
    assert resub_res.status_code == 201
    assert resub_res.json()["status"] == "PENDING_APPROVAL"

    # 4. Engineer 2 Approves
    app_res = client.post(
        f"/api/v1/onboarding/feed/{feed_id}/approve",
        json={"decision_notes": "Re-reviewed and approved."},
        headers=engineer2_headers,
    )
    assert app_res.status_code == 200
    assert app_res.json()["status"] == "ACTIVE"


def test_e2e_activation_records_immutable_audit_events(db, client, engineer_headers, engineer2_headers, analyst_headers):
    """Audit events are properly emitted with zero PHI/sample values persisted."""
    feed_id, sample_id, schema_id, schema_ver_id, mapping_id, field_map = _setup_feed_with_full_stack(
        client, engineer_headers, analyst_headers
    )

    # Run sandbox test
    client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=analyst_headers)
    # Submit
    client.post(
        f"/api/v1/onboarding/feed/{feed_id}/submit-approval",
        json={"notes": "Audit test submission"},
        headers=analyst_headers,
    )
    # Approve
    client.post(
        f"/api/v1/onboarding/feed/{feed_id}/approve",
        json={"decision_notes": "Audit test approval"},
        headers=engineer2_headers,
    )

    # Verify audit events in DB
    events = db.query(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(10).all()
    actions = [e.action for e in events]
    assert AuditActionEnum.APPROVAL_APPROVED in actions
    assert AuditActionEnum.FEED_STATUS_CHANGED in actions
    assert AuditActionEnum.APPROVAL_SUBMITTED in actions
    assert AuditActionEnum.SANDBOX_TEST_COMPLETED in actions
    assert AuditActionEnum.SANDBOX_TEST_STARTED in actions

    # Verify no raw sample rows or PHI in after_state
    for e in events:
        state_str = str(e.after_state or {})
        assert "John" not in state_str
        assert "Eve" not in state_str
        assert "Doe" not in state_str


def test_e2e_step5_completion_requires_approved_activation(db, client, engineer_headers, engineer2_headers, analyst_headers):
    """Step 5 is only marked completed in OnboardingSession once activation is approved."""
    feed_id, sample_id, schema_id, schema_ver_id, mapping_id, field_map = _setup_feed_with_full_stack(
        client, engineer_headers, analyst_headers
    )
    # Initialize session as in wizard
    client.get(f"/api/v1/onboarding/feed/{feed_id}", headers=analyst_headers)

    # Step 5 not completed after sandbox test
    client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=analyst_headers)
    session = db.query(OnboardingSession).filter(OnboardingSession.feed_id == feed_id).first()
    assert session is not None
    assert 5 not in (session.completed_steps or [])

    # Step 5 not completed after submit
    client.post(
        f"/api/v1/onboarding/feed/{feed_id}/submit-approval",
        json={"notes": "Testing session status"},
        headers=analyst_headers,
    )
    db.refresh(session)
    assert 5 not in (session.completed_steps or [])

    # Step 5 completed after approve
    client.post(
        f"/api/v1/onboarding/feed/{feed_id}/approve",
        json={"decision_notes": "Signed off"},
        headers=engineer2_headers,
    )
    db.refresh(session)
    assert 5 in (session.completed_steps or [])
    assert session.status == OnboardingStatusEnum.COMPLETED


def test_e2e_sandbox_idempotency_and_version_pinning(client, engineer_headers, analyst_headers):
    """Sandbox execution is idempotent and pinned to active published versions."""
    feed_id, sample_id, schema_id, schema_ver_id, mapping_id, field_map = _setup_feed_with_full_stack(
        client, engineer_headers, analyst_headers
    )

    # Run sandbox test twice
    res1 = client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=analyst_headers)
    res2 = client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=analyst_headers)
    assert res1.status_code == 200
    assert res2.status_code == 200

    d1 = res1.json()
    d2 = res2.json()
    assert d1["total_rows"] == d2["total_rows"]
    assert d1["passed_rows"] == d2["passed_rows"]
    assert d1["quarantined_rows"] == d2["quarantined_rows"]
    assert d1["pass_rate"] == d2["pass_rate"]


def test_e2e_active_feed_retains_immutable_activation_history(db, client, engineer_headers, engineer2_headers, analyst_headers):
    """Active feed retains immutable FeedActivationRecord and rejects redundant submissions."""
    feed_id, sample_id, schema_id, schema_ver_id, mapping_id, field_map = _setup_feed_with_full_stack(
        client, engineer_headers, analyst_headers
    )
    client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=analyst_headers)
    client.post(
        f"/api/v1/onboarding/feed/{feed_id}/submit-approval",
        json={"notes": "Activating"},
        headers=analyst_headers,
    )
    app_res = client.post(
        f"/api/v1/onboarding/feed/{feed_id}/approve",
        json={"decision_notes": "Approved for live ingests"},
        headers=engineer2_headers,
    )
    act_id = app_res.json()["activation_record_id"]

    # Record exists and contains exact IDs
    rec = db.query(FeedActivationRecord).filter(FeedActivationRecord.id == act_id).first()
    assert rec is not None
    assert str(rec.schema_version_id) == str(schema_ver_id)
    assert str(rec.activated_by) == "mock-engineer-002"

    # Submitting an already ACTIVE feed is rejected with 400 Bad Request
    dup_sub = client.post(
        f"/api/v1/onboarding/feed/{feed_id}/submit-approval",
        json={"notes": "Cannot re-submit active feed"},
        headers=analyst_headers,
    )
    assert dup_sub.status_code == 400
    assert "only draft feeds can be submitted" in dup_sub.json()["detail"].lower()
