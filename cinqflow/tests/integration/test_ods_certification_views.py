"""
Integration Tests for Wave 3 Slice 5:
PostgreSQL Certified Views and Consumer Role Security Boundary (CF-V3-E10-03)
"""
import uuid
import pytest
from datetime import datetime, date, timezone
from decimal import Decimal
from sqlalchemy import text

from backend.models.ods import (
    OdsModelVersion,
    OdsModelVersionStatusEnum,
    OdsMemberV1,
    OdsClaimV1,
    OdsClaimLineV1,
    OdsCertification,
    OdsCertificationStatusEnum,
)
from backend.models.pipeline import Batch, BatchStatusEnum
from backend.models.feed import Feed, FeedStatusEnum, FeedFormatEnum, FeedVersion, FeedVersionStatusEnum
from backend.core.database import engine


@pytest.fixture
def ods_pipeline_data(db):
    feed = Feed(
        id=uuid.uuid4(),
        name=f"Integration Feed {uuid.uuid4().hex[:6]}",
        domain="clinical",
        description="Integration Feed",
        format=FeedFormatEnum.JSON,
        landing_folder="/data/landing/integ",
        filename_pattern="test_*.json",
        schedule_expression="0 0 * * *",
        status=FeedStatusEnum.ACTIVE,
        created_by="system@cinqflow.local",
        updated_by="system@cinqflow.local",
    )
    db.add(feed)
    db.flush()

    fv = FeedVersion(
        id=uuid.uuid4(),
        feed_id=feed.id,
        version_number=1,
        config_snapshot={"fields": []},
        status=FeedVersionStatusEnum.PUBLISHED,
        created_by="system@cinqflow.local",
        updated_by="system@cinqflow.local",
    )
    db.add(fv)
    db.flush()

    mv = OdsModelVersion(
        id=uuid.uuid4(),
        version_number=601,
        name="Clinical Canonical ODS v601",
        domain="clinical",
        description="Model for view testing",
        schema_definition={"entities": {}},
        status=OdsModelVersionStatusEnum.PUBLISHED,
        published_at=datetime.now(timezone.utc),
        published_by="architect@cinqflow.local",
        created_by="architect@cinqflow.local",
        updated_by="architect@cinqflow.local",
    )
    db.add(mv)
    db.flush()

    batch = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=fv.id,
        status=BatchStatusEnum.SUCCESS,
        triggered_by="operator@cinqflow.local",
        ods_model_version_id=mv.id,
        created_by="operator@cinqflow.local",
        updated_by="operator@cinqflow.local",
    )
    db.add(batch)
    db.flush()

    cinq_id_val = uuid.uuid4()
    member = OdsMemberV1(
        cinq_id=cinq_id_val,
        batch_id=batch.id,
        ods_model_version_id=mv.id,
        first_name="Jane",
        last_name="Doe",
        date_of_birth=date(1990, 5, 20),
        gender="F",
        address_line1="123 Health Ave",
        city="Metro",
        state="CA",
        postal_code="90210",
        created_by="system@cinqflow.local",
        updated_by="system@cinqflow.local",
    )
    db.add(member)

    claim = OdsClaimV1(
        claim_id=uuid.uuid4(),
        cinq_id=cinq_id_val,
        batch_id=batch.id,
        ods_model_version_id=mv.id,
        claim_type="PROFESSIONAL",
        total_charge_amount=Decimal("250.00"),
        claim_date=date(2026, 1, 15),
        created_by="system@cinqflow.local",
        updated_by="system@cinqflow.local",
    )
    db.add(claim)

    claim_line = OdsClaimLineV1(
        claim_line_id=uuid.uuid4(),
        claim_id=claim.claim_id,
        batch_id=batch.id,
        ods_model_version_id=mv.id,
        line_number=1,
        service_date=date(2026, 1, 15),
        procedure_code="99213",
        allowed_amount=Decimal("150.00"),
        paid_amount=Decimal("120.00"),
        created_by="system@cinqflow.local",
        updated_by="system@cinqflow.local",
    )
    db.add(claim_line)
    db.commit()

    return {
        "batch": batch,
        "model_version": mv,
        "member": member,
        "claim": claim,
        "claim_line": claim_line,
    }


def test_certified_views_hide_uncertified_data(db, ods_pipeline_data):
    batch = ods_pipeline_data["batch"]

    # 1. With NO certification row, view must return 0 rows for this batch
    rows = db.execute(
        text("SELECT * FROM ods_certified.members_v1 WHERE batch_id = :b"),
        {"b": batch.id},
    ).fetchall()
    assert len(rows) == 0

    rows_claim = db.execute(
        text("SELECT * FROM ods_certified.claims_v1 WHERE batch_id = :b"),
        {"b": batch.id},
    ).fetchall()
    assert len(rows_claim) == 0

    rows_line = db.execute(
        text("SELECT * FROM ods_certified.claim_lines_v1 WHERE batch_id = :b"),
        {"b": batch.id},
    ).fetchall()
    assert len(rows_line) == 0


def test_certified_views_expose_certified_data(db, ods_pipeline_data):
    batch = ods_pipeline_data["batch"]
    mv = ods_pipeline_data["model_version"]
    member = ods_pipeline_data["member"]

    # 2. Add CERTIFIED certification
    cert = OdsCertification(
        id=uuid.uuid4(),
        batch_id=batch.id,
        ods_model_version_id=mv.id,
        status=OdsCertificationStatusEnum.CERTIFIED,
        certified_by="steward@cinqflow.local",
        certified_at=datetime.now(timezone.utc),
        certification_notes="Certified for downstream consumption.",
        checklist_snapshot={"model_published": True, "identity_status": "SUCCESS"},
        created_by="steward@cinqflow.local",
        updated_by="steward@cinqflow.local",
    )
    db.add(cert)
    db.commit()

    # Query view
    rows = db.execute(
        text("SELECT * FROM ods_certified.members_v1 WHERE batch_id = :b"),
        {"b": batch.id},
    ).mappings().fetchall()

    assert len(rows) == 1
    assert rows[0]["cinq_id"] == member.cinq_id
    assert rows[0]["first_name"] == "Jane"
    assert rows[0]["last_name"] == "Doe"
    assert rows[0]["city"] == "Metro"

    # Query claims view
    c_rows = db.execute(
        text("SELECT * FROM ods_certified.claims_v1 WHERE batch_id = :b"),
        {"b": batch.id},
    ).mappings().fetchall()
    assert len(c_rows) == 1
    assert c_rows[0]["claim_type"] == "PROFESSIONAL"
    assert c_rows[0]["total_charge_amount"] == Decimal("250.00")

    # Query claim lines view
    l_rows = db.execute(
        text("SELECT * FROM ods_certified.claim_lines_v1 WHERE batch_id = :b"),
        {"b": batch.id},
    ).mappings().fetchall()
    assert len(l_rows) == 1
    assert l_rows[0]["procedure_code"] == "99213"


def test_certified_views_hide_failed_certification(db, ods_pipeline_data):
    batch = ods_pipeline_data["batch"]
    mv = ods_pipeline_data["model_version"]

    cert = OdsCertification(
        id=uuid.uuid4(),
        batch_id=batch.id,
        ods_model_version_id=mv.id,
        status=OdsCertificationStatusEnum.FAILED,
        certified_by="steward@cinqflow.local",
        certified_at=datetime.now(timezone.utc),
        certification_notes="Rejected batch.",
        checklist_snapshot={},
        created_by="steward@cinqflow.local",
        updated_by="steward@cinqflow.local",
    )
    db.add(cert)
    db.commit()

    rows = db.execute(
        text("SELECT * FROM ods_certified.members_v1 WHERE batch_id = :b"),
        {"b": batch.id},
    ).fetchall()
    assert len(rows) == 0


def test_consumer_role_security_boundary(db):
    """Verify live PostgreSQL role privilege boundary:
    cinqflow_consumer_base can SELECT ods_certified.* but CANNOT select internal_ods.*
    """
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            # Switch session to temporary consumer user inheriting cinqflow_consumer_base
            conn.execute(text("""
                DO $$ BEGIN
                    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'test_tmp_consumer') THEN
                        CREATE ROLE test_tmp_consumer IN ROLE cinqflow_consumer_base;
                    END IF;
                END $$;
            """))

            # Test querying certified view as test_tmp_consumer
            conn.execute(text("SET ROLE test_tmp_consumer;"))
            cert_res = conn.execute(text("SELECT count(*) FROM ods_certified.members_v1;")).scalar()
            assert cert_res is not None

            # Test querying internal_ods table as test_tmp_consumer -> MUST FAIL with permission denied (SQLSTATE 42501)
            conn.execute(text("SAVEPOINT sp_perm;"))
            try:
                conn.execute(text("SELECT * FROM internal_ods.ods_members_v1 LIMIT 1;"))
                raise AssertionError("Consumer role should NOT have access to internal_ods!")
            except Exception as e:
                conn.execute(text("ROLLBACK TO SAVEPOINT sp_perm;"))
                assert "permission denied" in str(e) or "42501" in str(e)
        finally:
            conn.execute(text("RESET ROLE;"))
            conn.execute(text("DROP ROLE IF EXISTS test_tmp_consumer;"))
            trans.rollback()


def test_unauthorized_role_cannot_query_certified_views(db):
    """Verify live PostgreSQL: role with NO grants cannot SELECT from ods_certified.* (SQLSTATE 42501)"""
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text("""
                DO $$ BEGIN
                    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'test_unauthorized_user') THEN
                        CREATE ROLE test_unauthorized_user;
                    END IF;
                END $$;
            """))
            conn.execute(text("SET ROLE test_unauthorized_user;"))
            conn.execute(text("SAVEPOINT sp_unauth;"))
            try:
                conn.execute(text("SELECT count(*) FROM ods_certified.members_v1;"))
                raise AssertionError("Unauthorized role should NOT have access to ods_certified!")
            except Exception as e:
                conn.execute(text("ROLLBACK TO SAVEPOINT sp_unauth;"))
                assert "permission denied" in str(e) or "42501" in str(e)
        finally:
            conn.execute(text("RESET ROLE;"))
            conn.execute(text("DROP ROLE IF EXISTS test_unauthorized_user;"))
            trans.rollback()


def test_e2e_pipeline_to_certification_to_consumer(db, ods_pipeline_data):
    """End-to-end test:
    Completed batch with identity run -> certified by steward -> accessible via certified views & consumer gate
    """
    from backend.services.ods_certification_service import OdsCertificationService
    from backend.schemas.ods import OdsCertifyBatchRequest
    from backend.models.identity_run_status import IdentityRunStatus
    from backend.services.ods_service import OdsService
    from backend.models.ods import ConsumerRegistration, ConsumerTypeEnum, ConsumerStatusEnum

    batch = ods_pipeline_data["batch"]
    mv = ods_pipeline_data["model_version"]
    member = ods_pipeline_data["member"]

    # 1. Add identity run status = SUCCESS
    id_run = IdentityRunStatus(
        batch_id=batch.id,
        identity_run_id=uuid.uuid4(),
        run_status="SUCCESS",
        completed_at=datetime.now(timezone.utc),
    )
    db.add(id_run)

    # 2. Register consumer
    consumer = ConsumerRegistration(
        id=uuid.uuid4(),
        consumer_name="e2e_analytics_consumer",
        consumer_type=ConsumerTypeEnum.ANALYTICS_SQL,
        registered_ods_model_version_id=mv.id,
        status=ConsumerStatusEnum.ACTIVE,
        db_role_name="cinqflow_consumer_e2e_analytics",
        contact_email="e2e@cinqflow.local",
        created_by="admin@cinqflow.local",
        updated_by="admin@cinqflow.local",
    )
    db.add(consumer)
    db.commit()

    # 3. Before certification, consumer gate denies access
    with pytest.raises(Exception) as exc:
        OdsService.validate_consumer_gate(
            db=db,
            consumer_name="e2e_analytics_consumer",
            batch_id=batch.id,
            require_certified=True,
        )
    assert "not certified" in str(exc.value)

    # 4. View has 0 rows
    rows_pre = db.execute(
        text("SELECT * FROM ods_certified.members_v1 WHERE batch_id = :b"),
        {"b": batch.id},
    ).fetchall()
    assert len(rows_pre) == 0

    # 5. Steward certifies batch
    req = OdsCertifyBatchRequest(
        batch_id=batch.id,
        status="CERTIFIED",
        notes="E2E Pipeline certification complete.",
    )
    cert = OdsCertificationService.certify_batch(
        db=db,
        request=req,
        steward_user="steward@cinqflow.local",
    )
    assert cert.status == "CERTIFIED"

    # 6. Now view exposes member row
    rows_post = db.execute(
        text("SELECT * FROM ods_certified.members_v1 WHERE batch_id = :b"),
        {"b": batch.id},
    ).mappings().fetchall()
    assert len(rows_post) == 1
    assert rows_post[0]["cinq_id"] == member.cinq_id

    # 7. Consumer gate authorizes access
    gate_res = OdsService.validate_consumer_gate(
        db=db,
        consumer_name="e2e_analytics_consumer",
        batch_id=batch.id,
        require_certified=True,
    )
    assert gate_res["allowed"] is True
    assert gate_res["certified"] is True

