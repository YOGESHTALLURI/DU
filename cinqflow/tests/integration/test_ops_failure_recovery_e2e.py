"""
End-to-end integration tests for Failure Recovery Operations & Governance (CF-V2-E12-04, CF-V2-E12-05)
Traces: Pipeline failure -> Fingerprint & Alert -> Playbook Recommendation -> Slice 3 Governed Action Surface.
"""
import uuid
import hashlib
import pytest
from backend.models.incident import (
    OperationalAlert,
    FailureFingerprint,
    FailureCategoryEnum,
    AlertStatusEnum,
)
from datetime import datetime, timezone
from backend.models.ops_action import ActionTypeEnum, ActionStatusEnum
from backend.models.feed import Feed, FeedFormatEnum, FeedStatusEnum, FeedVersion, FeedVersionStatusEnum
from backend.models.input_registry import InputRegistry, InputStatusEnum
from backend.models.pipeline import (
    Batch,
    BatchStage,
    BatchStatusEnum,
    StageNameEnum,
    StageStatusEnum,
    WAVE0_STAGE_ORDER,
)
from backend.adapters.storage import get_storage_adapter
from backend.services.alert_service import AlertService
from backend.services.playbook_service import PlaybookService


@pytest.fixture
def e2e_feed(db):
    feed = Feed(
        name=f"e2e-feed-{uuid.uuid4().hex[:8]}",
        domain="CLAIMS",
        format=FeedFormatEnum.CSV,
        landing_folder="/landing/claims",
        filename_pattern="claims_*.csv",
        schedule_expression="0 6 * * *",
        status=FeedStatusEnum.ACTIVE,
        created_by="test-setup",
        updated_by="test-setup",
    )
    db.add(feed)
    db.commit()
    db.refresh(feed)
    return feed


def test_e2e_failure_generates_alert_and_fingerprint(client, db, e2e_feed, engineer_headers):
    """Pipeline failure automatically registers a deterministic fingerprint and an operational alert."""
    alert = AlertService.record_failure(
        db=db,
        feed_id=e2e_feed.id,
        batch_id=None,
        category=FailureCategoryEnum.STAGE_EXECUTION,
        failure_stage="BRONZE",
        root_cause_pattern="UnicodeDecodeError: 'utf-8' codec can't decode byte 0x96 in position 42",
        error_context={"stage": "BRONZE"},
    )
    db.commit()

    # Query API as operator
    res = client.get(f"/api/v1/ops/alerts/{alert.id}", headers=engineer_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "OPEN"
    assert data["failure_fingerprint_id"] == str(alert.failure_fingerprint_id)
    assert data["fingerprint"]["category"] == "STAGE_EXECUTION"
    assert "utf-8" in data["fingerprint"]["root_cause_pattern"]


def test_e2e_storm_suppression_across_batches(db, e2e_feed):
    """Multiple sequential pipeline batches failing on the same error suppress alerts into a single incident."""
    err_text = "Database deadlock on table 'silver_claims' during concurrent load"

    for i in range(5):
        AlertService.record_failure(
            db=db,
            feed_id=e2e_feed.id,
            batch_id=None,
            category=FailureCategoryEnum.STAGE_EXECUTION,
            failure_stage="SILVER_RAW",
            root_cause_pattern=err_text,
        )
    db.commit()

    alerts = db.query(OperationalAlert).filter(OperationalAlert.feed_id == e2e_feed.id).all()
    assert len(alerts) == 1
    assert alerts[0].occurrence_count == 5
    assert len(alerts[0].occurrences) == 5


def test_e2e_playbook_action_submission_to_governed_surface(client, db, e2e_feed, engineer_headers):
    """Executing an advisory playbook recovery action submits to POST /api/v1/ops/actions adhering to Slice 3 governance."""
    # 1. Setup standard restart playbook
    pb = PlaybookService.create_playbook(
        db=db,
        title="Stage Restart SOP",
        category=FailureCategoryEnum.STAGE_EXECUTION,
        playbook_code=f"PB-RESTART-{uuid.uuid4().hex[:6]}",
        explanation_template="Restart failed batch from stage boundary",
        suggested_action_type=ActionTypeEnum.RESTART_BATCH,
    )
    PlaybookService.approve_playbook_version(db=db, version_id=pb.current_version_id, approved_by="lead-steward")

    # 2. Setup a real failed batch with storage file and published feed version
    ver = FeedVersion(
        feed_id=e2e_feed.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED,
        config_snapshot={
            "fields": [
                {"name": "member_id", "type": "STRING", "required": True},
                {"name": "first_name", "type": "STRING", "required": True},
                {"name": "last_name", "type": "STRING", "required": True},
                {"name": "date_of_birth", "type": "DATE", "required": True},
                {"name": "gender", "type": "ENUM", "allowed_values": ["M", "F", "U"], "required": False},
            ],
            "stages": [
                {"name": "LANDING", "order": 1, "config": {}},
                {"name": "BRONZE", "order": 2, "config": {}},
                {"name": "SILVER_RAW", "order": 3, "config": {"delimiter": ","}},
                {"name": "RECONCILIATION", "order": 4, "config": {}},
            ],
        },
        created_by="test",
        updated_by="test",
    )
    db.add(ver)
    db.flush()
    e2e_feed.active_version_id = ver.id
    db.flush()

    storage = get_storage_adapter()
    file_bytes = b"member_id,first_name,last_name,date_of_birth,gender\nM001,John,Doe,1980-01-01,M\n"
    file_path = f"./data/landing/e2e_{uuid.uuid4().hex[:8]}.csv"
    storage.write_file(file_path, file_bytes)

    inp = InputRegistry(
        id=uuid.uuid4(),
        feed_id=e2e_feed.id,
        filename="test.csv",
        file_path=file_path,
        file_size_bytes=len(file_bytes),
        file_fingerprint=hashlib.sha256(file_bytes).hexdigest(),
        status=InputStatusEnum.ACCEPTED,
        registered_by="test",
        detected_at=datetime.now(timezone.utc),
        created_by="test",
        updated_by="test",
    )
    db.add(inp)
    db.flush()

    batch = Batch(
        id=uuid.uuid4(),
        feed_id=e2e_feed.id,
        feed_version_id=ver.id,
        input_registry_id=inp.id,
        status=BatchStatusEnum.FAILED,
        triggered_by="test",
        created_by="test",
        updated_by="test",
    )
    db.add(batch)
    db.flush()

    for idx, stage_name in enumerate(WAVE0_STAGE_ORDER, start=1):
        stage = BatchStage(
            id=uuid.uuid4(),
            batch_id=batch.id,
            stage_name=stage_name,
            stage_order=idx,
            status=StageStatusEnum.PENDING,
            created_by="test",
            updated_by="test",
        )
        db.add(stage)
    db.commit()

    # 3. Trigger failure
    alert = AlertService.record_failure(
        db=db,
        feed_id=e2e_feed.id,
        batch_id=batch.id,
        category=FailureCategoryEnum.STAGE_EXECUTION,
        failure_stage="BRONZE",
        root_cause_pattern="Timeout waiting for lock",
    )
    db.commit()

    # 4. Submit recovery action recommended by playbook
    action_payload = {
        "action_type": "RESTART_BATCH",
        "target_type": "BATCH",
        "target_id": str(batch.id),
        "reason": "Executing recommended playbook PB-RESTART recovery",
        "idempotency_key": f"e2e-act-{uuid.uuid4().hex[:8]}",
    }
    action_res = client.post("/api/v1/ops/actions", json=action_payload, headers=engineer_headers)
    assert action_res.status_code == 200
    act_data = action_res.json()
    assert act_data["action_type"] == "RESTART_BATCH"
    assert act_data["status"] in ["COMPLETED", "EXECUTING", "PENDING_APPROVAL"]


def test_e2e_high_risk_playbook_action_enforces_dual_control(client, db, e2e_feed, engineer_headers, readonly_token):
    """A high-risk playbook action (RETRIGGER_BATCH) mandates Four-Eyes approval with self-approval blocked."""
    alert = AlertService.record_failure(
        db=db,
        feed_id=e2e_feed.id,
        batch_id=None,
        category=FailureCategoryEnum.DATA_QUALITY,
        failure_stage="SILVER_RAW",
        root_cause_pattern="Fatal data corruption",
    )
    db.commit()

    # Submit high risk action
    dummy_batch_id = uuid.uuid4()
    action_payload = {
        "action_type": "RETRIGGER_BATCH",
        "target_type": "BATCH",
        "target_id": str(dummy_batch_id),
        "reason": "Retrigger entire batch from landing per critical SOP",
        "idempotency_key": f"e2e-highrisk-{uuid.uuid4().hex[:8]}",
    }
    submit_res = client.post("/api/v1/ops/actions", json=action_payload, headers=engineer_headers)
    assert submit_res.status_code == 202
    action_obj = submit_res.json()
    assert action_obj["status"] == "PENDING_APPROVAL"
    assert action_obj["risk_level"] == "HIGH_RISK"
    act_id = action_obj["id"]

    # Requester self-approval is strictly forbidden (HTTP 403)
    self_approve_res = client.post(
        f"/api/v1/ops/actions/{act_id}/approve",
        json={"decision_notes": "Attempting self approval"},
        headers=engineer_headers,
    )
    assert self_approve_res.status_code == 403

