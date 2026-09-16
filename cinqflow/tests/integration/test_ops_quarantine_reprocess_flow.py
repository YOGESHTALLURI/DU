"""
Integration tests for Quarantine Reprocess, Discard, and Governed Action flows (Wave 2 Slice 3).
"""
import uuid
import pytest

from backend.models.pipeline import Batch, BatchStatusEnum, StageNameEnum
from backend.models.input_registry import (
    QuarantineRecord,
    QuarantineReasonEnum,
    QuarantineStatusEnum,
)
from backend.models.audit import AuditEvent, AuditActionEnum
from tests.unit.test_ops_recovery_service import recovery_feed, _create_sample_batch


def test_api_reprocess_quarantine_records_end_to_end(client, engineer_headers, recovery_feed, db):
    """23. Test reprocessing quarantine records end-to-end via convenience endpoint."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)

    # Valid record for this feed
    qr = QuarantineRecord(
        id=uuid.uuid4(),
        batch_id=batch.id,
        stage_name=StageNameEnum.SILVER_RAW.value,
        source_row_number=1,
        source_record_raw="M001,Alice,Johnson,1985-06-15,F",
        field_name="member_id",
        reason=QuarantineReasonEnum.MISSING_REQUIRED_FIELD,
        status=QuarantineStatusEnum.QUARANTINED,
        created_by="system",
        updated_by="system",
    )
    db.add(qr)
    db.commit()

    payload = {
        "record_ids": [str(qr.id)],
        "reason": "Reprocessing after fixing validation logic",
    }
    res = client.post("/api/v1/ops/quarantine/reprocess", json=payload, headers=engineer_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "COMPLETED"
    assert data["execution_result"]["reprocessed_count"] == 1
    assert data["execution_result"]["still_quarantined_count"] == 0

    db.refresh(qr)
    assert qr.status == QuarantineStatusEnum.REPROCESSED
    assert qr.resolution_batch_id is not None


def test_api_reprocess_quarantine_partial_resolution(client, engineer_headers, recovery_feed, db):
    """24. Test reprocessing mixed quarantine records: valid resolves, invalid remains quarantined."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)

    qr_valid = QuarantineRecord(
        id=uuid.uuid4(),
        batch_id=batch.id,
        stage_name=StageNameEnum.SILVER_RAW.value,
        source_row_number=1,
        source_record_raw="M100,Bob,Builder,1980-05-12,M",
        field_name="gender",
        reason=QuarantineReasonEnum.INVALID_ENUM_VALUE,
        status=QuarantineStatusEnum.QUARANTINED,
        created_by="system",
        updated_by="system",
    )
    qr_invalid = QuarantineRecord(
        id=uuid.uuid4(),
        batch_id=batch.id,
        stage_name=StageNameEnum.SILVER_RAW.value,
        source_row_number=2,
        source_record_raw="M101,,Broken,2099-01-01,Z",  # Missing first_name & future date & invalid gender
        field_name="first_name",
        reason=QuarantineReasonEnum.MISSING_REQUIRED_FIELD,
        status=QuarantineStatusEnum.QUARANTINED,
        created_by="system",
        updated_by="system",
    )
    db.add_all([qr_valid, qr_invalid])
    db.commit()

    payload = {
        "record_ids": [str(qr_valid.id), str(qr_invalid.id)],
        "reason": "Attempting partial batch fix",
    }
    res = client.post("/api/v1/ops/quarantine/reprocess", json=payload, headers=engineer_headers)
    assert res.status_code == 200
    result = res.json()["execution_result"]
    assert result["reprocessed_count"] == 1
    assert result["still_quarantined_count"] == 1

    db.refresh(qr_valid)
    db.refresh(qr_invalid)
    assert qr_valid.status == QuarantineStatusEnum.REPROCESSED
    assert qr_invalid.status == QuarantineStatusEnum.QUARANTINED


def test_api_discard_quarantine_records_audit_trail(client, engineer_headers, engineer2_headers, recovery_feed, db):
    """25. Test discarding quarantine records requires dual control, and produces immutable audit records."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)

    qr = QuarantineRecord(
        id=uuid.uuid4(),
        batch_id=batch.id,
        stage_name=StageNameEnum.SILVER_RAW.value,
        source_row_number=1,
        source_record_raw="IRRECOVERABLE_GARBAGE_BYTES",
        field_name="all",
        reason=QuarantineReasonEnum.ENCODING_ERROR,
        status=QuarantineStatusEnum.QUARANTINED,
        created_by="system",
        updated_by="system",
    )
    db.add(qr)
    db.commit()

    # Engineer 1 requests discard -> 202 Accepted (HIGH_RISK)
    payload = {
        "record_ids": [str(qr.id)],
        "reason": "Confirmed corrupted file payload with vendor",
    }
    submit_res = client.post("/api/v1/ops/quarantine/discard", json=payload, headers=engineer_headers)
    assert submit_res.status_code == 202
    action_id = submit_res.json()["id"]

    # Engineer 2 approves -> 200 OK
    approve_res = client.post(
        f"/api/v1/ops/actions/{action_id}/approve",
        json={"decision_notes": "Vendor confirmation attached in JIRA-402"},
        headers=engineer2_headers,
    )
    assert approve_res.status_code == 200

    db.refresh(qr)
    assert qr.status == QuarantineStatusEnum.DISCARDED

    # Audit event verified
    audit_evt = (
        db.query(AuditEvent)
        .filter(AuditEvent.action == AuditActionEnum.OPS_QUARANTINE_DISCARDED)
        .order_by(AuditEvent.created_at.desc())
        .first()
    )
    assert audit_evt is not None


def test_api_action_idempotency_key_replay_returns_cached(client, engineer_headers, recovery_feed, db):
    """26. Test replaying identical idempotency key returns cached action without re-execution."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    batch.status = BatchStatusEnum.FAILED
    db.commit()

    idem_key = f"idem-api-{uuid.uuid4().hex}"
    payload = {
        "action_type": "RESTART_BATCH",
        "target_type": "BATCH",
        "target_id": str(batch.id),
        "reason": "Idempotent restart test",
        "idempotency_key": idem_key,
    }

    res1 = client.post("/api/v1/ops/actions", json=payload, headers=engineer_headers)
    assert res1.status_code == 200
    action_id_1 = res1.json()["id"]

    res2 = client.post("/api/v1/ops/actions", json=payload, headers=engineer_headers)
    assert res2.status_code == 200
    action_id_2 = res2.json()["id"]

    assert action_id_1 == action_id_2


def test_api_batch_restart_endpoint_delegates_to_governed_surface(client, engineer_headers, recovery_feed, db):
    """27. Test that the legacy pipeline /batches/{id}/restart endpoint delegates to governed action surface."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    batch.status = BatchStatusEnum.FAILED
    db.commit()

    res = client.post(f"/api/v1/pipeline/batches/{batch.id}/restart", headers=engineer_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert data["restart_count"] == 1

    # Verify action engine logged ops.action_executed
    action_evt = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.action == AuditActionEnum.OPS_ACTION_EXECUTED,
            AuditEvent.object_type == "operational_action_requests",
        )
        .order_by(AuditEvent.created_at.desc())
        .first()
    )
    assert action_evt is not None


def test_api_action_audit_trail_immutable_and_zero_phi(client, engineer_headers, recovery_feed, db):
    """28. Test that API submissions containing patient PHI in reason text are scrubbed before persistence."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    batch.status = BatchStatusEnum.FAILED
    db.commit()

    phi_reason = "Manual restart for patient SSN 987-65-4321, phone 555-123-4567, email test@patient.com"
    payload = {
        "action_type": "RESTART_BATCH",
        "target_type": "BATCH",
        "target_id": str(batch.id),
        "reason": phi_reason,
    }

    res = client.post("/api/v1/ops/actions", json=payload, headers=engineer_headers)
    assert res.status_code == 200
    action_id = res.json()["id"]

    # Verify response masks PHI
    assert "987-65-4321" not in res.json()["reason"]
    assert "[REDACTED_SSN]" in res.json()["reason"]

    # Verify audit event in DB has zero PHI
    audit_evt = (
        db.query(AuditEvent)
        .filter(AuditEvent.object_id == action_id)
        .first()
    )
    assert audit_evt is not None
    assert "987-65-4321" not in (audit_evt.description or "")
    assert "test@patient.com" not in (audit_evt.description or "")
