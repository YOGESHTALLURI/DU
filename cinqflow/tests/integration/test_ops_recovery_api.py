"""
Integration tests for Operations Governed Action API (Wave 2 Slice 3 — CF-V2-E12-03, CF-V2-E8-04).
"""
import uuid
import pytest

from backend.models.pipeline import Batch, BatchStatusEnum
from backend.models.ops_action import ActionTypeEnum, ActionStatusEnum
from tests.unit.test_ops_recovery_service import recovery_feed, _create_sample_batch


def test_api_submit_standard_restart_action_by_engineer(client, engineer_headers, recovery_feed, db):
    """17. Test submitting a standard restart action via API succeeds immediately (200 OK)."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    batch.status = BatchStatusEnum.FAILED
    db.commit()

    payload = {
        "action_type": "RESTART_BATCH",
        "target_type": "BATCH",
        "target_id": str(batch.id),
        "reason": "Restarting batch after network timeout",
    }
    res = client.post("/api/v1/ops/actions", json=payload, headers=engineer_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["action_type"] == "RESTART_BATCH"
    assert data["status"] == "COMPLETED"
    assert data["risk_level"] == "STANDARD"
    assert data["requires_approval"] is False
    assert data["execution_result"]["batch_id"] == str(batch.id)


def test_api_submit_standard_action_forbidden_for_readonly_or_analyst(client, readonly_headers, recovery_feed, db):
    """18. Test that READ_ONLY or ANALYST roles receive 403 Forbidden when attempting recovery actions."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    batch.status = BatchStatusEnum.FAILED
    db.commit()

    payload = {
        "action_type": "RESTART_BATCH",
        "target_type": "BATCH",
        "target_id": str(batch.id),
        "reason": "Unauthorized attempt",
    }
    res = client.post("/api/v1/ops/actions", json=payload, headers=readonly_headers)
    assert res.status_code == 403
    assert "Only ENGINEER role is authorized" in res.json()["detail"]


def test_api_submit_high_risk_retrigger_action_creates_pending_request(client, engineer_headers, recovery_feed, db):
    """19. Test submitting a high-risk RETRIGGER_BATCH action enters PENDING_APPROVAL (202 Accepted)."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    batch.status = BatchStatusEnum.SUCCESS
    db.commit()

    payload = {
        "action_type": "RETRIGGER_BATCH",
        "target_type": "BATCH",
        "target_id": str(batch.id),
        "reason": "Client retroactive claims reprocessing request",
    }
    res = client.post("/api/v1/ops/actions", json=payload, headers=engineer_headers)
    assert res.status_code == 202
    data = res.json()
    assert data["action_type"] == "RETRIGGER_BATCH"
    assert data["status"] == "PENDING_APPROVAL"
    assert data["risk_level"] == "HIGH_RISK"
    assert data["requires_approval"] is True


def test_api_approve_action_enforces_different_user_four_eyes(client, engineer_headers, engineer2_headers, recovery_feed, db):
    """20. Test Four-Eyes enforcement via API: requester cannot self-approve, second engineer can."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    batch.status = BatchStatusEnum.SUCCESS
    db.commit()

    # Engineer 1 submits
    payload = {
        "action_type": "RETRIGGER_BATCH",
        "target_type": "BATCH",
        "target_id": str(batch.id),
        "reason": "High risk action test",
    }
    submit_res = client.post("/api/v1/ops/actions", json=payload, headers=engineer_headers)
    assert submit_res.status_code == 202
    action_id = submit_res.json()["id"]

    # Engineer 1 attempts self-approval -> 403 Forbidden
    self_approve_res = client.post(
        f"/api/v1/ops/actions/{action_id}/approve",
        json={"decision_notes": "Self approval attempt"},
        headers=engineer_headers,
    )
    assert self_approve_res.status_code == 403
    assert "four-eyes" in self_approve_res.json()["detail"].lower()

    # Engineer 2 approves -> 200 OK
    approve_res = client.post(
        f"/api/v1/ops/actions/{action_id}/approve",
        json={"decision_notes": "Second engineer approved after verification"},
        headers=engineer2_headers,
    )
    assert approve_res.status_code == 200
    assert approve_res.json()["status"] == "COMPLETED"


def test_api_reject_action_by_authorized_operator(client, engineer_headers, engineer2_headers, recovery_feed, db):
    """21. Test rejecting a pending action via API."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    batch.status = BatchStatusEnum.SUCCESS
    db.commit()

    submit_res = client.post(
        "/api/v1/ops/actions",
        json={
            "action_type": "RETRIGGER_BATCH",
            "target_type": "BATCH",
            "target_id": str(batch.id),
            "reason": "Action to be rejected",
        },
        headers=engineer_headers,
    )
    assert submit_res.status_code == 202
    action_id = submit_res.json()["id"]

    reject_res = client.post(
        f"/api/v1/ops/actions/{action_id}/reject",
        json={"decision_notes": "Maintenance window conflict. Rejected."},
        headers=engineer2_headers,
    )
    assert reject_res.status_code == 200
    assert reject_res.json()["status"] == "REJECTED"


def test_api_list_pending_action_queue_with_filters(client, engineer_headers, recovery_feed, db):
    """22. Test retrieving pending dual-control action queue via GET /api/v1/ops/actions/pending."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    batch.status = BatchStatusEnum.SUCCESS
    db.commit()

    client.post(
        "/api/v1/ops/actions",
        json={
            "action_type": "RETRIGGER_BATCH",
            "target_type": "BATCH",
            "target_id": str(batch.id),
            "reason": "Queue list test",
        },
        headers=engineer_headers,
    )

    res = client.get("/api/v1/ops/actions/pending", headers=engineer_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    assert any(item["action_type"] == "RETRIGGER_BATCH" for item in data["items"])


def test_api_schedule_pause_and_resume_governed_actions(client, engineer_headers, recovery_feed, db):
    """Test PAUSE_SCHEDULE and RESUME_SCHEDULE via POST /api/v1/ops/actions and convenience delegation."""
    from backend.services.scheduling_service import SchedulingService
    from backend.models.schedule import ScheduleStatusEnum
    feed, version = recovery_feed

    # Set schedule active
    sched_service = SchedulingService(db)
    from backend.core.security import CurrentUser
    mock_eng = CurrentUser(user_id="mock-engineer-001", email="engineer@cinqflow.local", roles=["ENGINEER"], auth_provider="mock")
    sched = sched_service.update_schedule(feed.id, "0 * * * *", "UTC", False, current_user=mock_eng)
    assert sched.status == ScheduleStatusEnum.ACTIVE

    # 1. Pause via POST /api/v1/ops/actions -> 200
    pause_payload = {
        "action_type": "PAUSE_SCHEDULE",
        "target_type": "FEED_SCHEDULE",
        "target_id": str(feed.id),
        "reason": "Pause feed for scheduled database index maintenance",
    }
    pause_res = client.post("/api/v1/ops/actions", json=pause_payload, headers=engineer_headers)
    assert pause_res.status_code == 200
    assert pause_res.json()["status"] == "COMPLETED"

    db.refresh(sched)
    assert sched.status == ScheduleStatusEnum.PAUSED

    # 2. Duplicate pause attempt -> 400 Bad Request
    pause_dup = client.post("/api/v1/ops/actions", json=pause_payload, headers=engineer_headers)
    assert pause_dup.status_code == 400
    assert "already PAUSED" in pause_dup.json()["detail"]

    # 3. Resume via convenience endpoint /api/v1/schedules/feed/{id}/resume -> delegates to action engine
    resume_res = client.post(f"/api/v1/schedules/feed/{feed.id}/resume", headers=engineer_headers)
    assert resume_res.status_code == 200
    assert resume_res.json()["status"] == "ACTIVE"

    db.refresh(sched)
    assert sched.status == ScheduleStatusEnum.ACTIVE


def test_api_idempotency_conflict_returns_409(client, engineer_headers, recovery_feed, db):
    """Test replaying same idempotency key with different action parameters returns 409 Conflict."""
    feed, version = recovery_feed
    batch1 = _create_sample_batch(db, feed, version, content_csv="member_id,first_name,last_name,date_of_birth,gender\nM101,John,Doe,1980-01-01,M\n")
    batch1.status = BatchStatusEnum.FAILED
    batch2 = _create_sample_batch(db, feed, version, content_csv="member_id,first_name,last_name,date_of_birth,gender\nM102,Jane,Smith,1985-02-02,F\n")
    batch2.status = BatchStatusEnum.FAILED
    db.commit()

    idem_key = f"idem-api-conflict-{uuid.uuid4().hex}"
    payload1 = {
        "action_type": "RESTART_BATCH",
        "target_type": "BATCH",
        "target_id": str(batch1.id),
        "reason": "First attempt",
        "idempotency_key": idem_key,
    }
    res1 = client.post("/api/v1/ops/actions", json=payload1, headers=engineer_headers)
    assert res1.status_code == 200

    payload2 = {
        "action_type": "RESTART_BATCH",
        "target_type": "BATCH",
        "target_id": str(batch2.id),
        "reason": "Second attempt with conflicting target_id",
        "idempotency_key": idem_key,
    }
    res2 = client.post("/api/v1/ops/actions", json=payload2, headers=engineer_headers)
    assert res2.status_code == 409
    assert "Idempotency key conflict" in res2.json()["detail"]
