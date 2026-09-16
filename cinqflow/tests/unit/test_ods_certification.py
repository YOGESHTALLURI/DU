"""
Unit Tests for Wave 3 Slice 5:
ODS Batch Certification & Consumer Compatibility Gate (CF-V3-E10-03)
"""
import uuid
import pytest
from datetime import datetime, timezone
from fastapi import HTTPException

from backend.models.ods import (
    OdsModelVersion,
    OdsModelVersionStatusEnum,
    ConsumerRegistration,
    ConsumerStatusEnum,
    ConsumerTypeEnum,
    OdsCertification,
    OdsCertificationStatusEnum,
)
from backend.models.pipeline import Batch, BatchStatusEnum
from backend.models.identity_run_status import IdentityRunStatus
from backend.models.feed import Feed, FeedStatusEnum, FeedFormatEnum, FeedVersion, FeedVersionStatusEnum
from backend.models.audit import AuditEvent, AuditActionEnum
from backend.schemas.ods import OdsCertifyBatchRequest
from backend.services.ods_certification_service import OdsCertificationService
from backend.services.ods_service import OdsService


@pytest.fixture
def cert_fixtures(db):
    feed = Feed(
        id=uuid.uuid4(),
        name=f"Cert Feed {uuid.uuid4().hex[:6]}",
        domain="clinical",
        description="Certification Test Feed",
        format=FeedFormatEnum.JSON,
        landing_folder="/data/landing/cert",
        filename_pattern="test_*.json",
        schedule_expression="0 0 * * *",
        status=FeedStatusEnum.ACTIVE,
        created_by="pipeline_runner@cinqflow.local",
        updated_by="pipeline_runner@cinqflow.local",
    )
    db.add(feed)
    db.flush()

    fv = FeedVersion(
        id=uuid.uuid4(),
        feed_id=feed.id,
        version_number=1,
        config_snapshot={"fields": []},
        status=FeedVersionStatusEnum.PUBLISHED,
        created_by="pipeline_runner@cinqflow.local",
        updated_by="pipeline_runner@cinqflow.local",
    )
    db.add(fv)
    db.flush()

    model_version = OdsModelVersion(
        id=uuid.uuid4(),
        version_number=501,
        name="Clinical Canonical ODS v501",
        domain="clinical",
        description="Canonical schema for cert tests",
        schema_definition={"entities": {"ods_members": {}}},
        status=OdsModelVersionStatusEnum.PUBLISHED.value,
        published_at=datetime.now(timezone.utc),
        published_by="architect@cinqflow.local",
        created_by="architect@cinqflow.local",
        updated_by="architect@cinqflow.local",
    )
    db.add(model_version)
    db.flush()

    batch = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=fv.id,
        status=BatchStatusEnum.SUCCESS,
        triggered_by="operator@cinqflow.local",
        ods_model_version_id=model_version.id,
        created_by="operator@cinqflow.local",
        updated_by="operator@cinqflow.local",
    )
    db.add(batch)
    db.flush()

    id_run = IdentityRunStatus(
        batch_id=batch.id,
        identity_run_id=uuid.uuid4(),
        run_status="SUCCESS",
        completed_at=datetime.now(timezone.utc),
    )
    db.add(id_run)
    db.commit()

    return {
        "feed": feed,
        "feed_version": fv,
        "model_version": model_version,
        "batch": batch,
        "identity_run": id_run,
    }


def test_evaluate_batch_eligibility_success(db, cert_fixtures):
    batch = cert_fixtures["batch"]
    res = OdsCertificationService.evaluate_batch_eligibility(db, batch.id)
    assert res["eligible_for_certification"] is True
    assert res["batch_status"] == "SUCCESS"
    assert res["identity_status"] == "SUCCESS"
    assert res["ods_model_version_status"] == "PUBLISHED"
    assert len(res["disqualifying_reasons"]) == 0


def test_evaluate_batch_eligibility_incomplete_batch(db, cert_fixtures):
    batch = cert_fixtures["batch"]
    batch.status = BatchStatusEnum.RUNNING
    db.commit()

    res = OdsCertificationService.evaluate_batch_eligibility(db, batch.id)
    assert res["eligible_for_certification"] is False
    assert any("must be SUCCESS" in r for r in res["disqualifying_reasons"])


def test_evaluate_batch_eligibility_failed_identity(db, cert_fixtures):
    id_run = cert_fixtures["identity_run"]
    id_run.run_status = "FAILURE"
    id_run.completed_at = None
    db.commit()

    res = OdsCertificationService.evaluate_batch_eligibility(db, cert_fixtures["batch"].id)
    assert res["eligible_for_certification"] is False
    assert any("Identity stage status" in r for r in res["disqualifying_reasons"])


def test_evaluate_batch_eligibility_unpublished_model(db, cert_fixtures):
    mv = cert_fixtures["model_version"]
    mv.status = OdsModelVersionStatusEnum.DRAFT.value
    db.commit()

    res = OdsCertificationService.evaluate_batch_eligibility(db, cert_fixtures["batch"].id)
    assert res["eligible_for_certification"] is False
    assert any("must be PUBLISHED" in r for r in res["disqualifying_reasons"])


def test_certify_batch_success(db, cert_fixtures):
    batch = cert_fixtures["batch"]
    req = OdsCertifyBatchRequest(
        batch_id=batch.id,
        status="CERTIFIED",
        notes="Verified downstream canonical schema compatibility.",
    )
    cert = OdsCertificationService.certify_batch(
        db=db,
        request=req,
        steward_user="data_steward@cinqflow.local",
    )
    assert cert.status == OdsCertificationStatusEnum.CERTIFIED.value
    assert cert.certified_by == "data_steward@cinqflow.local"
    assert cert.certified_at is not None
    assert cert.batch_id == batch.id

    # Verify audit event emitted
    audit = db.query(AuditEvent).filter(
        AuditEvent.object_id == str(cert.id),
        AuditEvent.action == AuditActionEnum.ODS_BATCH_CERTIFIED,
    ).first()
    assert audit is not None
    assert audit.actor_id == "data_steward@cinqflow.local"


def test_certify_batch_rejection(db, cert_fixtures):
    batch = cert_fixtures["batch"]
    req = OdsCertifyBatchRequest(
        batch_id=batch.id,
        status="FAILED",
        notes="Rejected due to cross-entity data anomalies.",
    )
    cert = OdsCertificationService.certify_batch(
        db=db,
        request=req,
        steward_user="lead_steward@cinqflow.local",
    )
    assert cert.status == OdsCertificationStatusEnum.FAILED.value
    assert cert.certified_by == "lead_steward@cinqflow.local"

    # Verify audit event
    audit = db.query(AuditEvent).filter(
        AuditEvent.object_id == str(cert.id),
        AuditEvent.action == AuditActionEnum.ODS_BATCH_CERTIFICATION_FAILED,
    ).first()
    assert audit is not None


def test_certify_batch_four_eyes_violation(db, cert_fixtures):
    batch = cert_fixtures["batch"]
    # operator created the batch, so operator cannot certify it
    req = OdsCertifyBatchRequest(
        batch_id=batch.id,
        status="CERTIFIED",
        notes="Self-certification attempt.",
    )
    with pytest.raises(HTTPException) as exc:
        OdsCertificationService.certify_batch(
            db=db,
            request=req,
            steward_user=batch.created_by,
        )
    assert exc.value.status_code == 403
    assert "Four-Eyes segregation violation" in exc.value.detail


def test_certify_batch_api_endpoint_rbac(client, db, cert_fixtures, readonly_headers, steward_headers):
    batch = cert_fixtures["batch"]

    # READ_ONLY role cannot certify -> HTTP 403
    res_ro = client.post(
        "/api/v1/ods/certify",
        headers=readonly_headers,
        json={
            "batch_id": str(batch.id),
            "status": "CERTIFIED",
            "notes": "Read only attempting cert",
        },
    )
    assert res_ro.status_code == 403

    # DATA_STEWARD role can certify -> HTTP 201
    res_stew = client.post(
        "/api/v1/ods/certify",
        headers=steward_headers,
        json={
            "batch_id": str(batch.id),
            "status": "CERTIFIED",
            "notes": "Steward certified",
        },
    )
    assert res_stew.status_code == 201
    assert res_stew.json()["status"] == "CERTIFIED"


def test_certify_batch_phi_notes_rejected(db, cert_fixtures):
    batch = cert_fixtures["batch"]
    # Attempting to include SSN in notes
    req = OdsCertifyBatchRequest(
        batch_id=batch.id,
        status="CERTIFIED",
        notes="Batch for patient with SSN 123-45-6789.",
    )
    with pytest.raises(HTTPException) as exc:
        OdsCertificationService.certify_batch(
            db=db,
            request=req,
            steward_user="steward@cinqflow.local",
        )
    assert exc.value.status_code == 422
    assert "Certification notes contain prohibited PHI/PII" in exc.value.detail


def test_certification_immutability_app_level(db, cert_fixtures):
    batch = cert_fixtures["batch"]
    req = OdsCertifyBatchRequest(
        batch_id=batch.id,
        status="CERTIFIED",
        notes="First certification.",
    )
    OdsCertificationService.certify_batch(
        db=db,
        request=req,
        steward_user="steward1@cinqflow.local",
    )

    # Attempting to re-certify
    req2 = OdsCertifyBatchRequest(
        batch_id=batch.id,
        status="FAILED",
        notes="Second certification attempt.",
    )
    with pytest.raises(HTTPException) as exc:
        OdsCertificationService.certify_batch(
            db=db,
            request=req2,
            steward_user="steward2@cinqflow.local",
        )
    assert exc.value.status_code == 409
    assert "already CERTIFIED" in exc.value.detail


def test_consumer_gate_certified_vs_uncertified(db, cert_fixtures):
    batch = cert_fixtures["batch"]
    mv = cert_fixtures["model_version"]

    consumer = ConsumerRegistration(
        id=uuid.uuid4(),
        consumer_name="analytics_pipeline",
        consumer_type=ConsumerTypeEnum.ANALYTICS_SQL,
        registered_ods_model_version_id=mv.id,
        status=ConsumerStatusEnum.ACTIVE,
        db_role_name="cinqflow_consumer_analytics_pipeline",
        contact_email="analytics@cinqflow.local",
        created_by="admin@cinqflow.local",
        updated_by="admin@cinqflow.local",
    )
    db.add(consumer)
    db.commit()

    # 1. Before certification, require_certified=True must deny access (403)
    with pytest.raises(HTTPException) as exc:
        OdsService.validate_consumer_gate(
            db=db,
            consumer_name="analytics_pipeline",
            batch_id=batch.id,
            require_certified=True,
        )
    assert exc.value.status_code == 403
    assert "not certified" in exc.value.detail

    # 2. Before certification, require_certified=False (Slice 2 legacy mode) passes
    res = OdsService.validate_consumer_gate(
        db=db,
        consumer_name="analytics_pipeline",
        batch_id=batch.id,
        require_certified=False,
    )
    assert res["allowed"] is True
    assert res["certified"] is False

    # 3. Now certify batch
    req = OdsCertifyBatchRequest(
        batch_id=batch.id,
        status="CERTIFIED",
        notes="Certified for analytics consumption.",
    )
    OdsCertificationService.certify_batch(
        db=db,
        request=req,
        steward_user="steward@cinqflow.local",
    )

    # 4. After certification, require_certified=True must pass (AUTHORIZED)
    res2 = OdsService.validate_consumer_gate(
        db=db,
        consumer_name="analytics_pipeline",
        batch_id=batch.id,
        require_certified=True,
    )
    assert res2["allowed"] is True
    assert res2["certified"] is True


def test_certification_model_creation(db, cert_fixtures):
    batch = cert_fixtures["batch"]
    mv = cert_fixtures["model_version"]
    cert = OdsCertification(
        batch_id=batch.id,
        ods_model_version_id=mv.id,
        status=OdsCertificationStatusEnum.PENDING.value,
        checklist_snapshot={"test": True},
        created_by="system@cinqflow.local",
        updated_by="system@cinqflow.local",
    )
    db.add(cert)
    db.commit()
    assert cert.id is not None
    assert cert.status == "PENDING"
    assert cert.checklist_snapshot == {"test": True}
    assert cert.created_at is not None


def test_evaluate_batch_eligibility_dq_failure(db, cert_fixtures):
    batch = cert_fixtures["batch"]
    from backend.models.pipeline import BatchStage, StageNameEnum, StageStatusEnum
    stage = BatchStage(
        batch_id=batch.id,
        stage_name=StageNameEnum.SILVER_RAW,
        stage_order=3,
        status=StageStatusEnum.FAILED,
        created_by="system@cinqflow.local",
        updated_by="system@cinqflow.local",
    )
    db.add(stage)
    db.commit()

    res = OdsCertificationService.evaluate_batch_eligibility(db, batch.id)
    assert res["eligible_for_certification"] is False
    assert any("Pipeline stage" in r and "FAILED" in r for r in res["disqualifying_reasons"])


def test_invalid_certification_transition_db_trigger(db, cert_fixtures):
    from sqlalchemy.exc import IntegrityError, InternalError
    from sqlalchemy import text
    batch = cert_fixtures["batch"]
    mv = cert_fixtures["model_version"]
    cert = OdsCertification(
        batch_id=batch.id,
        ods_model_version_id=mv.id,
        status=OdsCertificationStatusEnum.CERTIFIED.value,
        certified_by="steward@cinqflow.local",
        certified_at=datetime.now(timezone.utc),
        checklist_snapshot={},
        created_by="steward@cinqflow.local",
        updated_by="steward@cinqflow.local",
    )
    db.add(cert)
    db.commit()
    cert_id = str(cert.id)

    # Direct SQL UPDATE from CERTIFIED to PENDING must fail with check_violation
    db.execute(text("SAVEPOINT sp_inv_trans"))
    with pytest.raises((IntegrityError, InternalError)) as exc:
        db.execute(text(f"UPDATE ods_certifications SET status = 'PENDING' WHERE id = '{cert_id}'"))
    assert "check_violation" in str(exc.value) or "sealed" in str(exc.value)
    db.execute(text("ROLLBACK TO SAVEPOINT sp_inv_trans"))


def test_ods_certification_direct_sql_delete_rejected(db, cert_fixtures):
    """Direct SQL DELETE against ods_certifications must fail with SQLSTATE 23514 (check_violation)."""
    from sqlalchemy.exc import IntegrityError, InternalError
    from sqlalchemy import text
    batch = cert_fixtures["batch"]
    mv = cert_fixtures["model_version"]
    cert = OdsCertification(
        batch_id=batch.id,
        ods_model_version_id=mv.id,
        status=OdsCertificationStatusEnum.CERTIFIED.value,
        certified_by="steward@cinqflow.local",
        certified_at=datetime.now(timezone.utc),
        checklist_snapshot={"verified": True},
        created_by="steward@cinqflow.local",
        updated_by="steward@cinqflow.local",
    )
    db.add(cert)
    db.commit()
    cert_id = str(cert.id)

    db.execute(text("SAVEPOINT sp_delete_cert"))
    with pytest.raises((IntegrityError, InternalError)) as exc:
        db.execute(text(f"DELETE FROM ods_certifications WHERE id = '{cert_id}'"))
    err_msg = str(exc.value)
    assert "check_violation" in err_msg or "23514" in err_msg or "strictly prohibited" in err_msg
    db.execute(text("ROLLBACK TO SAVEPOINT sp_delete_cert"))

    # Verify row still exists and was not deleted
    surviving_count = db.execute(text(f"SELECT count(*) FROM ods_certifications WHERE id = '{cert_id}'")).scalar()
    assert surviving_count == 1


def test_ods_certification_orm_delete_rejected(db, cert_fixtures):
    """ORM / application-level delete against ods_certifications must fail with SQLSTATE 23514."""
    from sqlalchemy.exc import IntegrityError, InternalError
    from sqlalchemy import text
    batch = cert_fixtures["batch"]
    mv = cert_fixtures["model_version"]
    cert = OdsCertification(
        batch_id=batch.id,
        ods_model_version_id=mv.id,
        status=OdsCertificationStatusEnum.PENDING.value,
        checklist_snapshot={},
        created_by="steward@cinqflow.local",
        updated_by="steward@cinqflow.local",
    )
    db.add(cert)
    db.commit()
    cert_id = str(cert.id)

    nested = db.begin_nested()
    with pytest.raises((IntegrityError, InternalError)) as exc:
        db.delete(cert)
        nested.commit()
    err_msg = str(exc.value)
    assert "check_violation" in err_msg or "23514" in err_msg or "strictly prohibited" in err_msg
    nested.rollback()

    surviving_count = db.execute(text(f"SELECT count(*) FROM ods_certifications WHERE id = '{cert_id}'")).scalar()
    assert surviving_count == 1


def test_ods_certification_certified_record_field_mutations_rejected(db, cert_fixtures):
    """Once sealed in CERTIFIED status, no fields may be mutated."""
    from sqlalchemy.exc import IntegrityError, InternalError
    from sqlalchemy import text
    batch = cert_fixtures["batch"]
    mv = cert_fixtures["model_version"]
    cert = OdsCertification(
        batch_id=batch.id,
        ods_model_version_id=mv.id,
        status=OdsCertificationStatusEnum.CERTIFIED.value,
        certified_by="steward@cinqflow.local",
        certified_at=datetime.now(timezone.utc),
        certification_notes="Original official notes",
        checklist_snapshot={"initial": 1},
        created_by="steward@cinqflow.local",
        updated_by="steward@cinqflow.local",
    )
    db.add(cert)
    db.commit()
    cert_id = str(cert.id)

    fields_to_test = [
        ("certified_by", "'malicious_user'"),
        ("certification_notes", "'tampered'"),
        ("checklist_snapshot", "'{\"tampered\": true}'"),
        ("certified_at", "'2020-01-01 00:00:00+00'"),
        ("status", "'FAILED'"),
        ("status", "'PENDING'"),
    ]

    for idx, (col, val) in enumerate(fields_to_test):
        sp_name = f"sp_cert_field_{idx}"
        db.execute(text(f"SAVEPOINT {sp_name}"))
        with pytest.raises((IntegrityError, InternalError)) as exc:
            db.execute(text(f"UPDATE ods_certifications SET {col} = {val} WHERE id = '{cert_id}'"))
        assert "check_violation" in str(exc.value) or "sealed" in str(exc.value)
        db.execute(text(f"ROLLBACK TO SAVEPOINT {sp_name}"))

    # Verify fields remain untouched
    row = db.execute(text(f"SELECT status, certified_by, certification_notes FROM ods_certifications WHERE id = '{cert_id}'")).fetchone()
    assert row[0] == "CERTIFIED"
    assert row[1] == "steward@cinqflow.local"
    assert row[2] == "Original official notes"


def test_ods_certification_failed_record_field_mutations_rejected(db, cert_fixtures):
    """Once sealed in FAILED status, no fields may be mutated or reverted."""
    from sqlalchemy.exc import IntegrityError, InternalError
    from sqlalchemy import text
    batch = cert_fixtures["batch"]
    mv = cert_fixtures["model_version"]
    cert = OdsCertification(
        batch_id=batch.id,
        ods_model_version_id=mv.id,
        status=OdsCertificationStatusEnum.FAILED.value,
        certified_by="steward@cinqflow.local",
        certified_at=datetime.now(timezone.utc),
        certification_notes="Failed due to data quality",
        checklist_snapshot={"dq_passed": False},
        created_by="steward@cinqflow.local",
        updated_by="steward@cinqflow.local",
    )
    db.add(cert)
    db.commit()
    cert_id = str(cert.id)

    fields_to_test = [
        ("status", "'CERTIFIED'"),
        ("status", "'PENDING'"),
        ("certification_notes", "'overriding failure'"),
        ("certified_by", "'tampered_user'"),
    ]

    for idx, (col, val) in enumerate(fields_to_test):
        sp_name = f"sp_fail_field_{idx}"
        db.execute(text(f"SAVEPOINT {sp_name}"))
        with pytest.raises((IntegrityError, InternalError)) as exc:
            db.execute(text(f"UPDATE ods_certifications SET {col} = {val} WHERE id = '{cert_id}'"))
        assert "check_violation" in str(exc.value) or "sealed" in str(exc.value)
        db.execute(text(f"ROLLBACK TO SAVEPOINT {sp_name}"))

    row = db.execute(text(f"SELECT status, certification_notes FROM ods_certifications WHERE id = '{cert_id}'")).fetchone()
    assert row[0] == "FAILED"
    assert row[1] == "Failed due to data quality"


def test_ods_certification_pending_immutable_coordinates_rejected(db, cert_fixtures):
    """In PENDING status, core immutable coordinates (batch_id, ods_model_version_id, created_by) cannot be changed."""
    from sqlalchemy.exc import IntegrityError, InternalError
    from sqlalchemy import text
    batch = cert_fixtures["batch"]
    mv = cert_fixtures["model_version"]
    cert = OdsCertification(
        batch_id=batch.id,
        ods_model_version_id=mv.id,
        status=OdsCertificationStatusEnum.PENDING.value,
        checklist_snapshot={},
        created_by="steward@cinqflow.local",
        updated_by="steward@cinqflow.local",
    )
    db.add(cert)
    db.commit()
    cert_id = str(cert.id)

    # 1. Mutate batch_id
    new_batch_id = uuid.uuid4()
    db.execute(text("SAVEPOINT sp_pend_batch"))
    with pytest.raises((IntegrityError, InternalError)) as exc:
        db.execute(text(f"UPDATE ods_certifications SET batch_id = '{new_batch_id}' WHERE id = '{cert_id}'"))
    assert "check_violation" in str(exc.value) or "immutable" in str(exc.value)
    db.execute(text("ROLLBACK TO SAVEPOINT sp_pend_batch"))

    # 2. Mutate created_by
    db.execute(text("SAVEPOINT sp_pend_created_by"))
    with pytest.raises((IntegrityError, InternalError)) as exc:
        db.execute(text(f"UPDATE ods_certifications SET created_by = 'impostor' WHERE id = '{cert_id}'"))
    assert "check_violation" in str(exc.value) or "immutable" in str(exc.value)
    db.execute(text("ROLLBACK TO SAVEPOINT sp_pend_created_by"))


def test_ods_certification_parent_batch_delete_rejected(db, cert_fixtures):
    """Parent batch deletion must be rejected when an ods_certifications record exists (FK RESTRICT + trigger)."""
    from sqlalchemy.exc import IntegrityError, InternalError
    from sqlalchemy import text
    batch = cert_fixtures["batch"]
    mv = cert_fixtures["model_version"]
    cert = OdsCertification(
        batch_id=batch.id,
        ods_model_version_id=mv.id,
        status=OdsCertificationStatusEnum.CERTIFIED.value,
        certified_by="steward@cinqflow.local",
        certified_at=datetime.now(timezone.utc),
        checklist_snapshot={},
        created_by="steward@cinqflow.local",
        updated_by="steward@cinqflow.local",
    )
    db.add(cert)
    db.commit()
    batch_id = str(batch.id)
    cert_id = str(cert.id)

    # Attempting to delete the parent batch must fail
    db.execute(text("SAVEPOINT sp_del_batch"))
    with pytest.raises((IntegrityError, InternalError)) as exc:
        db.execute(text(f"DELETE FROM batches WHERE id = '{batch_id}'"))
    err_msg = str(exc.value)
    assert "foreign_key_violation" in err_msg or "23503" in err_msg or "ForeignKeyViolation" in err_msg
    db.execute(text("ROLLBACK TO SAVEPOINT sp_del_batch"))

    # Verify parent batch and certification record both still exist
    batch_count = db.execute(text(f"SELECT count(*) FROM batches WHERE id = '{batch_id}'")).scalar()
    assert batch_count == 1
    cert_count = db.execute(text(f"SELECT count(*) FROM ods_certifications WHERE id = '{cert_id}'")).scalar()
    assert cert_count == 1



