"""
Integration tests for Wave 1 Slice 2: Business Analyst 5-Step Feed Onboarding Wizard
"""
import uuid
import pytest
from fastapi import status


def test_onboarding_session_initialization_and_rbac(client, engineer_headers, analyst_headers, readonly_headers):
    # 1. Create feed
    feed_name = f"FEED_ONBOARD_{uuid.uuid4().hex[:6]}"
    res_feed = client.post(
        "/api/v1/feeds",
        json={
            "name": feed_name,
            "domain": "ENROLLMENT",
            "landing_folder": "./data/landing/enrollment",
            "filename_pattern": "ENROLL_*.csv",
            "source_system": "SALESFORCE",
            "data_owner": "Ops Team",
        },
        headers=engineer_headers,
    )
    assert res_feed.status_code == 201
    feed_id = res_feed.json()["id"]

    # 2. READ_ONLY user can fetch onboarding session
    res_ro = client.get(f"/api/v1/onboarding/feed/{feed_id}", headers=readonly_headers)
    assert res_ro.status_code == 200
    session_ro = res_ro.json()
    assert session_ro["feed_id"] == feed_id
    assert session_ro["current_step"] == 1
    assert 1 in session_ro["completed_steps"]
    assert session_ro["status"] == "IN_PROGRESS"

    # 3. READ_ONLY user cannot update onboarding step -> 403 Forbidden
    res_update_ro = client.put(
        f"/api/v1/onboarding/feed/{feed_id}/step",
        json={"current_step": 2, "mark_step_completed": 1},
        headers=readonly_headers,
    )
    assert res_update_ro.status_code == status.HTTP_403_FORBIDDEN

    # 4. Analyst user can advance step
    res_update_ba = client.put(
        f"/api/v1/onboarding/feed/{feed_id}/step",
        json={"current_step": 2, "mark_step_completed": 1},
        headers=analyst_headers,
    )
    assert res_update_ba.status_code == 200
    assert res_update_ba.json()["current_step"] == 2


def test_onboarding_full_progression_with_prerequisites(client, engineer_headers, analyst_headers):
    # Step 1: Create Feed
    feed_name = f"FEED_E2E_ONBOARD_{uuid.uuid4().hex[:6]}"
    res_feed = client.post(
        "/api/v1/feeds",
        json={
            "name": feed_name,
            "domain": "CLAIMS",
            "landing_folder": "./data/landing/claims",
            "filename_pattern": "CLAIMS_*.csv",
        },
        headers=engineer_headers,
    )
    assert res_feed.status_code == 201
    feed_id = res_feed.json()["id"]

    # Check Step 1 session
    res_sess = client.get(f"/api/v1/onboarding/feed/{feed_id}", headers=analyst_headers)
    assert res_sess.status_code == 200
    session = res_sess.json()
    assert 1 in session["completed_steps"]

    # Step 2: Attempting to mark step 2 completed before profiling is rejected
    res_fail_step2 = client.put(
        f"/api/v1/onboarding/feed/{feed_id}/step",
        json={"current_step": 2, "mark_step_completed": 2},
        headers=analyst_headers,
    )
    assert res_fail_step2.status_code == status.HTTP_400_BAD_REQUEST
    assert "sample file must be uploaded" in res_fail_step2.json()["detail"].lower()

    # Upload sample file and profile it
    csv_bytes = b"claim_id,amount,status\nCLM101,150.50,APPROVED\nCLM102,220.00,PENDING\n"
    res_upload = client.post(
        f"/api/v1/feeds/{feed_id}/samples",
        files={"file": ("CLAIMS_sample.csv", csv_bytes, "text/csv")},
        headers=analyst_headers,
    )
    assert res_upload.status_code == 201
    sample_file_id = res_upload.json()["id"]

    # Trigger profiling
    res_prof = client.post(
        f"/api/v1/feeds/{feed_id}/samples/{sample_file_id}/profile",
        headers=analyst_headers,
    )
    assert res_prof.status_code == 201
    assert res_prof.json()["status"] == "COMPLETED"

    # Now marking step 2 completed succeeds
    res_step2_ok = client.put(
        f"/api/v1/onboarding/feed/{feed_id}/step",
        json={"current_step": 3, "mark_step_completed": 2},
        headers=analyst_headers,
    )
    assert res_step2_ok.status_code == 200
    sess2 = res_step2_ok.json()
    assert 2 in sess2["completed_steps"]
    assert sess2["current_step"] == 3

    # Step 3: Attempting to mark step 3 completed without published schema is rejected
    res_fail_step3 = client.put(
        f"/api/v1/onboarding/feed/{feed_id}/step",
        json={"current_step": 3, "mark_step_completed": 3},
        headers=analyst_headers,
    )
    assert res_fail_step3.status_code == status.HTTP_400_BAD_REQUEST
    assert "schema contract" in res_fail_step3.json()["detail"].lower()

    # Create schema and publish it
    res_schema = client.post(
        "/api/v1/schemas",
        json={
            "feed_id": feed_id,
            "name": f"{feed_name}_Schema",
            "initial_fields": [
                {"field_name": "claim_id", "ordinal_position": 1, "data_type": "STRING"},
                {"field_name": "amount", "ordinal_position": 2, "data_type": "DECIMAL"},
                {"field_name": "status", "ordinal_position": 3, "data_type": "STRING"},
            ],
        },
        headers=analyst_headers,
    )
    assert res_schema.status_code == 201
    schema_id = res_schema.json()["id"]
    v1_id = res_schema.json()["draft_version"]["id"]

    # Still draft -> cannot mark step 3 complete
    res_draft_step3 = client.put(
        f"/api/v1/onboarding/feed/{feed_id}/step",
        json={"current_step": 3, "mark_step_completed": 3},
        headers=analyst_headers,
    )
    assert res_draft_step3.status_code == status.HTTP_400_BAD_REQUEST
    assert "published" in res_draft_step3.json()["detail"].lower()

    # Publish schema
    res_pub = client.post(
        f"/api/v1/schemas/{schema_id}/versions/{v1_id}/publish",
        json={"change_notes": "Published contract"},
        headers=analyst_headers,
    )
    assert res_pub.status_code == 200

    # Now step 3 can be marked completed
    res_step3_ok = client.put(
        f"/api/v1/onboarding/feed/{feed_id}/step",
        json={"current_step": 4, "mark_step_completed": 3},
        headers=analyst_headers,
    )
    assert res_step3_ok.status_code == 200
    assert 3 in res_step3_ok.json()["completed_steps"]

    # Step 4: Mapping Studio Preview (Placeholder acknowledged)
    res_step4_ok = client.put(
        f"/api/v1/onboarding/feed/{feed_id}/step",
        json={"current_step": 5, "mark_step_completed": 4},
        headers=analyst_headers,
    )
    assert res_step4_ok.status_code == 200
    assert 4 in res_step4_ok.json()["completed_steps"]

    # Step 5: Review & Activate
    res_step5_ok = client.put(
        f"/api/v1/onboarding/feed/{feed_id}/step",
        json={"current_step": 5, "mark_step_completed": 5},
        headers=analyst_headers,
    )
    assert res_step5_ok.status_code == 200
    sess_final = res_step5_ok.json()
    assert sess_final["status"] == "COMPLETED"
    assert set(sess_final["completed_steps"]) == {1, 2, 3, 4, 5}

    # Verify the Feed itself transitioned to ACTIVE
    res_feed_final = client.get(f"/api/v1/feeds/{feed_id}", headers=analyst_headers)
    assert res_feed_final.status_code == 200
    assert res_feed_final.json()["status"] == "ACTIVE"
