"""Unit tests for ApprovalService (Wave 1 Slice 5)."""
import io
import uuid
import pytest
from backend.models.feed import Feed, FeedStatusEnum
from backend.models.approval import ApprovalRequestStatusEnum, FeedActivationRecord
from backend.models.schema import OnboardingSession, OnboardingStatusEnum
from tests.unit.test_sandbox_executor import _setup_feed_with_full_stack


def test_review_packet_aggregation_complete(client, engineer_headers, analyst_headers):
    """Review packet aggregates all domain summaries, readiness checklist, and user capabilities."""
    feed_id, sample_id, schema_id, schema_ver_id, mapping_id, field_map = _setup_feed_with_full_stack(
        client, engineer_headers, analyst_headers
    )

    # Execute sandbox test
    sb_res = client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=analyst_headers)
    assert sb_res.status_code == 200

    # Fetch review packet as analyst
    res = client.get(f"/api/v1/onboarding/feed/{feed_id}/review-packet", headers=analyst_headers)
    assert res.status_code == 200
    packet = res.json()

    # 1. Metadata
    assert packet["feed_metadata"]["id"] == feed_id
    assert packet["feed_metadata"]["status"] == "DRAFT"

    # 2. Profiling
    assert packet["profiling_summary"]["sample_file_id"] == sample_id
    assert packet["profiling_summary"]["total_rows"] == 4

    # 3. Schema
    assert packet["schema_summary"]["schema_id"] == schema_id
    assert packet["schema_summary"]["status"] == "PUBLISHED"

    # 4. Mapping
    assert packet["mapping_summary"]["mapping_id"] == mapping_id
    assert packet["mapping_summary"]["canonical_model_name"] == "Member"
    assert packet["mapping_summary"]["mapped_fields_count"] == 5

    # 5. Rules
    assert packet["rules_summary"]["published_rules_count"] == 1
    assert "QUARANTINE" in packet["rules_summary"]["severities"]

    # 6. Latest sandbox run
    assert packet["latest_sandbox_run"] is not None
    assert packet["latest_sandbox_run"]["status"] == "SUCCESS"
    assert packet["latest_sandbox_run"]["reconciliation_status"] == "BALANCED"

    # 7. Readiness checklist
    assert packet["readiness_checklist"]["all_prerequisites_met"] is True
    assert packet["readiness_checklist"]["step1_metadata_valid"] is True
    assert packet["readiness_checklist"]["step2_profiling_complete"] is True
    assert packet["readiness_checklist"]["step3_schema_published"] is True
    assert packet["readiness_checklist"]["step4_mapping_published"] is True
    assert packet["readiness_checklist"]["step4_rules_published"] is True
    assert packet["readiness_checklist"]["step5_sandbox_passed"] is True

    # 8. User capabilities
    assert packet["user_capabilities"]["can_run_test"] is True
    assert packet["user_capabilities"]["can_submit"] is True
    assert packet["user_capabilities"]["can_approve"] is False  # Analyst cannot approve


def test_review_packet_readiness_checklist_gating(client, engineer_headers, analyst_headers):
    """Readiness checklist gates all_prerequisites_met based on each individual step."""
    feed_id, sample_id, schema_id, schema_ver_id, mapping_id, field_map = _setup_feed_with_full_stack(
        client, engineer_headers, analyst_headers
    )

    # Before running sandbox test, step5_sandbox_passed is False
    res = client.get(f"/api/v1/onboarding/feed/{feed_id}/review-packet", headers=analyst_headers)
    assert res.status_code == 200
    chk = res.json()["readiness_checklist"]
    assert chk["step5_sandbox_passed"] is False
    assert chk["all_prerequisites_met"] is False

    # Run sandbox test
    sb_res = client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=analyst_headers)
    assert sb_res.status_code == 200

    # After running sandbox test, all prerequisites are met
    res2 = client.get(f"/api/v1/onboarding/feed/{feed_id}/review-packet", headers=analyst_headers)
    chk2 = res2.json()["readiness_checklist"]
    assert chk2["step5_sandbox_passed"] is True
    assert chk2["all_prerequisites_met"] is True


def test_submit_approval_blocks_if_prerequisites_incomplete(client, engineer_headers, analyst_headers):
    """Submitting for approval before prerequisites are met returns 400 Bad Request."""
    feed_name = f"INCOMPLETE_FEED_{uuid.uuid4().hex[:6]}"
    f_res = client.post("/api/v1/feeds", json={
        "name": feed_name,
        "domain": "CLAIMS",
        "landing_folder": "./data/landing",
        "filename_pattern": "claims_.*\\.csv",
    }, headers=engineer_headers)
    feed_id = f_res.json()["id"]

    sub_res = client.post(
        f"/api/v1/onboarding/feed/{feed_id}/submit-approval",
        json={"notes": "Premature submission"},
        headers=analyst_headers,
    )
    assert sub_res.status_code == 400
    assert "prerequisites not met" in sub_res.json()["detail"].lower()


def test_submit_approval_blocks_if_no_successful_sandbox_test(client, engineer_headers, analyst_headers):
    """Submitting for approval with published schema/mapping/rules but without sandbox test returns 400."""
    feed_id, sample_id, schema_id, schema_ver_id, mapping_id, field_map = _setup_feed_with_full_stack(
        client, engineer_headers, analyst_headers
    )

    # Attempt submission without running sandbox test
    sub_res = client.post(
        f"/api/v1/onboarding/feed/{feed_id}/submit-approval",
        json={"notes": "Submission without sandbox test"},
        headers=analyst_headers,
    )
    assert sub_res.status_code == 400
    assert "sandbox test" in sub_res.json()["detail"].lower()


def test_submit_approval_success_transitions_to_pending(client, engineer_headers, analyst_headers):
    """Successful submission transitions request to PENDING_APPROVAL and records metadata."""
    feed_id, sample_id, schema_id, schema_ver_id, mapping_id, field_map = _setup_feed_with_full_stack(
        client, engineer_headers, analyst_headers
    )

    client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=analyst_headers)

    sub_res = client.post(
        f"/api/v1/onboarding/feed/{feed_id}/submit-approval",
        json={"notes": "Ready for engineering review and activation"},
        headers=analyst_headers,
    )
    assert sub_res.status_code == 201
    data = sub_res.json()
    assert data["status"] == "PENDING_APPROVAL"
    assert data["submission_notes"] == "Ready for engineering review and activation"
    assert data["submitted_by"] is not None


def test_submit_approval_duplicate_prevention(client, engineer_headers, analyst_headers):
    """Submitting when an approval request is already pending returns 409 Conflict."""
    feed_id, sample_id, schema_id, schema_ver_id, mapping_id, field_map = _setup_feed_with_full_stack(
        client, engineer_headers, analyst_headers
    )
    client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=analyst_headers)

    # First submission
    sub1 = client.post(
        f"/api/v1/onboarding/feed/{feed_id}/submit-approval",
        json={"notes": "First submission"},
        headers=analyst_headers,
    )
    assert sub1.status_code == 201

    # Second submission returns 409
    sub2 = client.post(
        f"/api/v1/onboarding/feed/{feed_id}/submit-approval",
        json={"notes": "Duplicate submission attempt"},
        headers=analyst_headers,
    )
    assert sub2.status_code == 409
    assert "already pending" in sub2.json()["detail"].lower()


def test_approve_activation_locks_version_bundle(db, client, engineer_headers, engineer2_headers, analyst_headers):
    """Approving activation transitions feed to ACTIVE, completes onboarding, and inserts immutable ledger record."""
    feed_id, sample_id, schema_id, schema_ver_id, mapping_id, field_map = _setup_feed_with_full_stack(
        client, engineer_headers, analyst_headers
    )
    client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=analyst_headers)

    # Analyst submits
    sub_res = client.post(
        f"/api/v1/onboarding/feed/{feed_id}/submit-approval",
        json={"notes": "Submitted by analyst for activation"},
        headers=analyst_headers,
    )
    assert sub_res.status_code == 201

    # Engineer 2 approves
    app_res = client.post(
        f"/api/v1/onboarding/feed/{feed_id}/approve",
        json={"decision_notes": "Reviewed sandbox evidence and verified contracts. Approved for production."},
        headers=engineer2_headers,
    )
    assert app_res.status_code == 200
    act_data = app_res.json()
    assert act_data["status"] == "ACTIVE"
    activation_record_id = act_data["activation_record_id"]

    # Verify immutable record in DB
    record = db.query(FeedActivationRecord).filter(FeedActivationRecord.id == activation_record_id).first()
    assert record is not None
    assert str(record.schema_version_id) == str(schema_ver_id)
    assert str(record.feed_id) == str(feed_id)
    assert len(record.rule_version_ids) == 1

    # Verify Feed in DB is ACTIVE
    feed = db.query(Feed).filter(Feed.id == feed_id).first()
    assert feed.status == FeedStatusEnum.ACTIVE

    # Verify OnboardingSession is COMPLETED
    session = db.query(OnboardingSession).filter(OnboardingSession.feed_id == feed_id).first()
    if session:
        assert session.status == OnboardingStatusEnum.COMPLETED
        assert 5 in session.completed_steps


def test_reject_activation_records_mandatory_reason(client, engineer_headers, engineer2_headers, analyst_headers):
    """Rejecting activation requires a mandatory decision reason and marks request REJECTED."""
    feed_id, sample_id, schema_id, schema_ver_id, mapping_id, field_map = _setup_feed_with_full_stack(
        client, engineer_headers, analyst_headers
    )
    client.post(f"/api/v1/onboarding/feed/{feed_id}/sandbox-test", headers=analyst_headers)

    client.post(
        f"/api/v1/onboarding/feed/{feed_id}/submit-approval",
        json={"notes": "Please review"},
        headers=analyst_headers,
    )

    # Reject with whitespace-only reason -> 400 Bad Request
    rej_bad = client.post(
        f"/api/v1/onboarding/feed/{feed_id}/reject",
        json={"decision_notes": "   "},
        headers=engineer2_headers,
    )
    assert rej_bad.status_code == 400
    assert "mandatory" in rej_bad.json()["detail"].lower()

    # Reject with valid reason -> 200 OK
    rej_good = client.post(
        f"/api/v1/onboarding/feed/{feed_id}/reject",
        json={"decision_notes": "Sample data pass rate is only 75% which is below 90% SLA threshold. Please refine DQ rules."},
        headers=engineer2_headers,
    )
    assert rej_good.status_code == 200
    data = rej_good.json()
    assert data["status"] == "REJECTED"
    assert "below 90% SLA" in data["decision_notes"]
