"""
Integration tests for Wave 2 Slice 5 — Batch Data Certification Flow (CF-V2-E13-04).
Verifies:
- GET /api/v1/ops/batches/{id}/certification-evaluation (checklist inspection)
- POST /api/v1/ops/batches/{id}/certify (signing ceremony)
- GET /api/v1/ops/batches/{id}/certification (retrieval of immutable certificate & evidence)
- POST /api/v1/ops/certifications/{id}/revoke (revocation of certificate)
- Four-eyes enforcement: trigger cannot certify
"""
import uuid
import hashlib
from datetime import datetime, timezone, timedelta
import pytest
from jose import jwt

from backend.core.config import settings
from backend.models.feed import Feed, FeedVersion, FeedFormatEnum, FeedStatusEnum, FeedVersionStatusEnum
from backend.models.pipeline import (
    Batch,
    BatchStatusEnum,
    BatchStage,
    StageNameEnum,
    StageStatusEnum,
    WAVE0_STAGE_ORDER,
)
from backend.models.reconciliation import BatchReconciliation, ReconciliationStatusEnum
from backend.models.input_registry import InputRegistry, InputStatusEnum


@pytest.fixture
def cert_api_env(db):
    test_id = uuid.uuid4().hex[:6]
    feed = Feed(
        id=uuid.uuid4(),
        name=f"CERT_API_FEED_{test_id}",
        domain="CLAIMS",
        format=FeedFormatEnum.CSV,
        status=FeedStatusEnum.ACTIVE,
        landing_folder="./data/landing",
        filename_pattern="*.csv",
        created_by="system",
        updated_by="system",
    )
    db.add(feed)

    fv = FeedVersion(
        id=uuid.uuid4(),
        feed_id=feed.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED,
        created_by="system",
        updated_by="system",
    )
    db.add(fv)

    inp = InputRegistry(
        id=uuid.uuid4(),
        feed_id=feed.id,
        filename=f"claims_{test_id}.csv",
        file_path=f"./data/landing/claims_{test_id}.csv",
        file_size_bytes=2048,
        file_fingerprint=hashlib.sha256(b"claims_bytes").hexdigest(),
        status=InputStatusEnum.ACCEPTED,
        registered_by="system",
        detected_at=datetime.now(timezone.utc),
        created_by="system",
        updated_by="system",
    )
    db.add(inp)

    # Triggered by engineer (mock-engineer-001)
    batch = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=fv.id,
        input_registry_id=inp.id,
        status=BatchStatusEnum.SUCCESS,
        triggered_by="mock-engineer-001",
        created_by="mock-engineer-001",
        updated_by="mock-engineer-001",
    )
    db.add(batch)

    for idx, sname in enumerate(WAVE0_STAGE_ORDER, start=1):
        stage = BatchStage(
            id=uuid.uuid4(),
            batch_id=batch.id,
            stage_name=sname,
            stage_order=idx,
            status=StageStatusEnum.SUCCESS,
            created_by="system",
            updated_by="system",
        )
        db.add(stage)

    recon = BatchReconciliation(
        id=uuid.uuid4(),
        batch_id=batch.id,
        rows_in=250,
        rows_silver_raw=250,
        rows_quarantined=0,
        rows_dropped=0,
        balance_check_passed=True,
        status=ReconciliationStatusEnum.PASS,
        discrepancy=0,
        created_by="system",
        updated_by="system",
    )
    db.add(recon)
    db.commit()

    return {"feed": feed, "batch": batch}


def test_batch_data_certification_governed_flow(client, engineer_headers, readonly_headers, cert_api_env):
    batch = cert_api_env["batch"]

    # 1. Evaluate certification eligibility (anyone can read)
    res_eval = client.get(
        f"/api/v1/ops/batches/{batch.id}/certification-evaluation",
        headers=readonly_headers,
    )
    assert res_eval.status_code == 200
    eval_data = res_eval.json()
    assert eval_data["is_eligible"] is True
    assert len(eval_data["checklist"]) == 7

    # 2. Trigger user (mock-engineer-001) attempts to certify: rejected with 403 (Four-eyes)
    res_trigger_cert = client.post(
        f"/api/v1/ops/batches/{batch.id}/certify",
        headers=engineer_headers,
        json={"certification_notes": "Attempting self certification"},
    )
    assert res_trigger_cert.status_code == 403
    assert "Four-eyes violation" in res_trigger_cert.json()["detail"]

    # 3. Independent steward token
    token_steward = jwt.encode(
        {
            "sub": "steward-certifier-009",
            "email": "steward_certifier@cinqflow.local",
            "roles": ["DATA_STEWARD"],
            "provider": "mock",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    steward_headers = {"Authorization": f"Bearer {token_steward}"}

    # 4. Independent steward certifies batch
    res_cert = client.post(
        f"/api/v1/ops/batches/{batch.id}/certify",
        headers=steward_headers,
        json={"certification_notes": "Production readiness verified against claims schema"},
    )
    assert res_cert.status_code == 201
    cert_data = res_cert.json()
    assert cert_data["status"] == "CERTIFIED"
    assert cert_data["certified_by"] == "steward-certifier-009"
    assert cert_data["certified_with_waivers"] is False
    assert cert_data["evidence_hash"] is not None
    cert_id = cert_data["id"]

    # 5. Fetch certification details
    res_get_cert = client.get(
        f"/api/v1/ops/batches/{batch.id}/certification",
        headers=readonly_headers,
    )
    assert res_get_cert.status_code == 200
    assert res_get_cert.json()["id"] == cert_id

    # 6. Revoke certification
    res_revoke = client.post(
        f"/api/v1/ops/certifications/{cert_id}/revoke",
        headers=steward_headers,
        json={"revocation_reason": "Downstream reconciliation audit identified vendor discrepancy"},
    )
    assert res_revoke.status_code == 200
    assert res_revoke.json()["status"] == "REVOKED"
