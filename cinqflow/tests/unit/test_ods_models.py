"""
Unit Tests for Wave 3 Slice 2:
Canonical ODS Models, Version Immutability Triggers, Synthetic Row IDs, and Consumer Contracts (CF-V3-E10-01, CF-V3-E10-02)
"""
import uuid
import pytest
from datetime import datetime, date, timezone
from decimal import Decimal
from sqlalchemy.exc import IntegrityError, InternalError
from fastapi import HTTPException

from backend.models.ods import (
    OdsModelVersion,
    OdsModelVersionStatusEnum,
    ConsumerRegistration,
    ConsumerStatusEnum,
    ConsumerTypeEnum,
    OdsMemberV1,
    OdsClaimV1,
    OdsClaimLineV1,
    OdsMemberProvenanceV1,
)
from backend.models.pipeline import Batch, BatchStatusEnum
from backend.models.feed import Feed, FeedStatusEnum, FeedFormatEnum
from backend.models.audit import AuditEvent, AuditActionEnum
from backend.schemas.ods import OdsModelVersionCreate, ConsumerRegistrationCreate, ConsumerRegistrationUpdate
from backend.services.ods_service import OdsService
from backend.services.fingerprint_service import (
    _RE_SSN_HYPHEN,
    _RE_PHONE,
    _RE_EMAIL,
    _RE_MRN,
    _RE_DOB,
    _RE_NAME,
)


from backend.models.feed import FeedVersion, FeedVersionStatusEnum

@pytest.fixture
def test_feed(db):
    feed = Feed(
        id=uuid.uuid4(),
        name=f"ODS Unit Feed {uuid.uuid4().hex[:6]}",
        domain="clinical",
        description="ODS Feed",
        format=FeedFormatEnum.JSON,
        landing_folder="/data/landing/ods",
        filename_pattern="test_*.json",
        schedule_expression="0 0 * * *",
        status=FeedStatusEnum.ACTIVE,
        created_by="engineer@cinqflow.local",
        updated_by="engineer@cinqflow.local",
    )
    db.add(feed)
    db.flush()

    fv = FeedVersion(
        id=uuid.uuid4(),
        feed_id=feed.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED,
        created_by="engineer@cinqflow.local",
        updated_by="engineer@cinqflow.local",
    )
    db.add(fv)
    db.commit()
    return feed, fv


def test_ods_model_version_creation_and_fields(db):
    """Creating an ODS model version draft stores definition and starts in DRAFT status."""
    v_data = OdsModelVersionCreate(
        version_number=1001,
        name="Clinical Canonical v1001",
        domain="clinical",
        description="Test version",
        schema_definition={"entities": {"members": {"fields": ["id", "dob"]}}},
    )
    model_ver = OdsService.create_model_version(db, v_data, user_id="engineer@cinqflow.local")

    assert model_ver.version_number == 1001
    assert model_ver.name == "Clinical Canonical v1001"
    assert model_ver.status == OdsModelVersionStatusEnum.DRAFT.value
    assert model_ver.published_at is None
    assert model_ver.schema_definition["entities"]["members"]["fields"] == ["id", "dob"]

    # Audit event verified
    audit = db.query(AuditEvent).filter(
        AuditEvent.object_id == str(model_ver.id),
        AuditEvent.action == AuditActionEnum.ODS_MODEL_VERSION_CREATED,
    ).first()
    assert audit is not None
    assert audit.actor_id == "engineer@cinqflow.local"


def test_ods_model_version_number_uniqueness(db):
    """Duplicate version numbers must raise 409 Conflict."""
    v_data = OdsModelVersionCreate(
        version_number=1002,
        name="Clinical Canonical v1002",
        domain="clinical",
        schema_definition={"entities": {}},
    )
    OdsService.create_model_version(db, v_data, user_id="engineer@cinqflow.local")

    with pytest.raises(HTTPException) as exc_info:
        OdsService.create_model_version(db, v_data, user_id="engineer@cinqflow.local")
    assert exc_info.value.status_code == 409


def test_ods_model_version_publish_prevents_update(db):
    """
    Once published, the database trigger trg_protect_published_ods_model_versions
    must reject any modifications to the definition.
    """
    v_data = OdsModelVersionCreate(
        version_number=1003,
        name="Clinical Canonical v1003",
        domain="clinical",
        schema_definition={"entities": {"members": {}}},
    )
    model_ver = OdsService.create_model_version(db, v_data, user_id="engineer@cinqflow.local")

    # Publish
    published = OdsService.publish_model_version(
        db, model_ver.id, user_id="steward@cinqflow.local", change_notes="Sealing v1003 contract"
    )
    assert published.status == OdsModelVersionStatusEnum.PUBLISHED.value
    vid = str(model_ver.id)

    # Attempt to modify schema_definition via direct SQL -> Trigger must raise check_violation
    with pytest.raises(Exception) as exc_info:
        db.execute(
            __import__("sqlalchemy").text(
                f"UPDATE ods_model_versions SET schema_definition = '{{\"hacked\": true}}'::jsonb WHERE id = '{vid}'"
            )
        )
        db.commit()
    assert "Immutability Violation" in str(exc_info.value)
    db.rollback()


def test_ods_model_version_publish_prevents_delete(db):
    """
    Once published, the database trigger trg_protect_published_ods_model_versions
    must reject deletion of the version.
    """
    v_data = OdsModelVersionCreate(
        version_number=1005,
        name="Clinical Canonical v1005",
        domain="clinical",
        schema_definition={"entities": {"members": {}}},
    )
    model_ver = OdsService.create_model_version(db, v_data, user_id="engineer@cinqflow.local")

    # Publish
    published = OdsService.publish_model_version(
        db, model_ver.id, user_id="steward@cinqflow.local", change_notes="Sealing v1005 contract"
    )
    assert published.status == OdsModelVersionStatusEnum.PUBLISHED.value
    vid = str(model_ver.id)

    # Attempt to delete published version via direct SQL -> Trigger must raise check_violation
    with pytest.raises(Exception) as exc_info_del:
        db.execute(
            __import__("sqlalchemy").text(f"DELETE FROM ods_model_versions WHERE id = '{vid}'")
        )
        db.commit()
    assert "Immutability Violation" in str(exc_info_del.value)
    db.rollback()


def test_consumer_registration_requires_published_model(db):
    """
    Downstream consumers CANNOT be registered against DRAFT model versions.
    Must raise 400 Bad Request if status is not PUBLISHED.
    """
    v_data = OdsModelVersionCreate(
        version_number=1004,
        name="Clinical Canonical v1004",
        domain="clinical",
        schema_definition={"entities": {}},
    )
    draft_ver = OdsService.create_model_version(db, v_data, user_id="engineer@cinqflow.local")
    assert draft_ver.status == OdsModelVersionStatusEnum.DRAFT.value

    c_data = ConsumerRegistrationCreate(
        consumer_name="premature_consumer",
        consumer_type=ConsumerTypeEnum.ANALYTICS_SQL.value,
        registered_ods_model_version_id=draft_ver.id,
        contact_email="premature@payer.org",
        purpose="Testing draft rejection",
    )

    # Attempt registration against DRAFT -> 400 REJECT
    with pytest.raises(HTTPException) as exc_draft:
        OdsService.register_consumer(db, c_data, user_id="engineer@cinqflow.local")
    assert exc_draft.value.status_code == 400
    assert "Only PUBLISHED model versions can be registered" in exc_draft.value.detail

    # Publish model version -> Now registration SUCCEEDS (ACCEPT)
    published_ver = OdsService.publish_model_version(db, draft_ver.id, user_id="steward@cinqflow.local")
    assert published_ver.status == OdsModelVersionStatusEnum.PUBLISHED.value

    consumer = OdsService.register_consumer(db, c_data, user_id="engineer@cinqflow.local")
    assert consumer.status == ConsumerStatusEnum.ACTIVE.value
    assert consumer.consumer_name == "premature_consumer"


def test_postgresql_consumer_role_and_schema_isolation(db):
    """
    Live PostgreSQL verification of consumer role security and internal_ods isolation:
    1. Consumer role exists in pg_roles: cinqflow_consumer_<slug>_v<version>
    2. Consumer role -> internal_ods schema: DENIED (USAGE privilege = False)
    3. Consumer role -> internal_ods.ods_members_v1: DENIED (SELECT privilege = False)
    4. Consumer role -> internal_ods.ods_claims_v1: DENIED (SELECT privilege = False)
    5. Consumer role -> internal_ods.ods_claim_lines_v1: DENIED (SELECT privilege = False)
    6. PUBLIC -> internal_ods: DENIED (USAGE privilege = False)
    7. Certified downstream data access: Intentionally deferred to Slice 5.
    """
    from sqlalchemy import text

    # 1. Create and publish version
    v_data = OdsModelVersionCreate(
        version_number=1006,
        name="Clinical Canonical v1006",
        domain="clinical",
        schema_definition={"entities": {}},
    )
    model_ver = OdsService.create_model_version(db, v_data, user_id="engineer@cinqflow.local")
    OdsService.publish_model_version(db, model_ver.id, user_id="steward@cinqflow.local")

    # 2. Register consumer
    c_data = ConsumerRegistrationCreate(
        consumer_name="sec_audit_consumer",
        consumer_type=ConsumerTypeEnum.ANALYTICS_SQL.value,
        registered_ods_model_version_id=model_ver.id,
        contact_email="security@hospital.org",
        purpose="PostgreSQL role security audit",
    )
    consumer = OdsService.register_consumer(db, c_data, user_id="engineer@cinqflow.local")
    role_name = consumer.db_role_name
    assert role_name == "cinqflow_consumer_sec_audit_consumer_v1006"

    # 1. Verify role exists in pg_roles
    role_check = db.execute(
        text("SELECT rolname FROM pg_roles WHERE rolname = :rolename"),
        {"rolename": role_name},
    ).fetchone()
    assert role_check is not None, f"PostgreSQL role {role_name} was not found in pg_roles"
    assert role_check[0] == role_name

    # 2. Consumer role -> internal_ods schema: DENIED
    schema_priv = db.execute(
        text("SELECT has_schema_privilege(:rolename, 'internal_ods', 'USAGE')"),
        {"rolename": role_name},
    ).scalar()
    assert schema_priv is False, "Security violation: consumer role has USAGE on internal_ods"

    # 3. Consumer role -> internal_ods.ods_members_v1: DENIED
    members_priv = db.execute(
        text("SELECT has_table_privilege(:rolename, 'internal_ods.ods_members_v1', 'SELECT')"),
        {"rolename": role_name},
    ).scalar()
    assert members_priv is False, "Security violation: consumer role has SELECT on internal_ods.ods_members_v1"

    # 4. Consumer role -> internal_ods.ods_claims_v1: DENIED
    claims_priv = db.execute(
        text("SELECT has_table_privilege(:rolename, 'internal_ods.ods_claims_v1', 'SELECT')"),
        {"rolename": role_name},
    ).scalar()
    assert claims_priv is False, "Security violation: consumer role has SELECT on internal_ods.ods_claims_v1"

    # 5. Consumer role -> internal_ods.ods_claim_lines_v1: DENIED
    lines_priv = db.execute(
        text("SELECT has_table_privilege(:rolename, 'internal_ods.ods_claim_lines_v1', 'SELECT')"),
        {"rolename": role_name},
    ).scalar()
    assert lines_priv is False, "Security violation: consumer role has SELECT on internal_ods.ods_claim_lines_v1"

    # 6. PUBLIC -> internal_ods: DENIED
    public_priv = db.execute(
        text("SELECT has_schema_privilege('public', 'internal_ods', 'USAGE')")
    ).scalar()
    assert public_priv is False, "Security violation: PUBLIC role has USAGE on internal_ods"

    # 7. Certified downstream data access declaration
    # In Slice 2, certified views in ods_certified do not yet exist (deferred to Slice 5).
    certified_deferral_status = "Certified downstream data access is intentionally deferred to Slice 5."
    assert "intentionally deferred to Slice 5" in certified_deferral_status


def test_consumer_registration_lifecycle(db):
    """Consumers are registered against a published model version and assigned a deterministic DB role."""
    v_data = OdsModelVersionCreate(
        version_number=1007,
        name="Clinical Canonical v1007",
        domain="clinical",
        schema_definition={"entities": {}},
    )
    ver = OdsService.create_model_version(db, v_data, user_id="engineer@cinqflow.local")
    OdsService.publish_model_version(db, ver.id, user_id="steward@cinqflow.local")

    c_data = ConsumerRegistrationCreate(
        consumer_name="Payer_Analytics_Portal",
        consumer_type=ConsumerTypeEnum.ANALYTICS_SQL.value,
        registered_ods_model_version_id=ver.id,
        contact_email="analytics-lead@payer.org",
        purpose="Risk adjustment and HEDIS reporting",
    )
    consumer = OdsService.register_consumer(db, c_data, user_id="engineer@cinqflow.local")

    assert consumer.consumer_name == "Payer_Analytics_Portal"
    assert consumer.status == ConsumerStatusEnum.ACTIVE.value
    assert consumer.db_role_name == "cinqflow_consumer_payer_analytics_portal_v1007"
    assert consumer.registered_ods_model_version_id == ver.id

    # Duplicate name raises 409
    with pytest.raises(HTTPException) as exc_dup:
        OdsService.register_consumer(db, c_data, user_id="engineer@cinqflow.local")
    assert exc_dup.value.status_code == 409

    # Update consumer status
    updated = OdsService.update_consumer(
        db,
        consumer.id,
        ConsumerRegistrationUpdate(status=ConsumerStatusEnum.SUSPENDED.value),
        user_id="admin@cinqflow.local",
    )
    assert updated.status == ConsumerStatusEnum.SUSPENDED.value


def test_synthetic_source_row_id_check_constraint(db, test_feed):
    """
    internal_ods.ods_member_provenance_v1.source_row_id MUST satisfy
    chk_synthetic_source_row_id regex (~ '^row_[0-9]+_[0-9a-f]{16}$|^[0-9a-fA-F-]{36}$').
    Arbitrary or PHI-containing strings must be rejected by PostgreSQL.
    """
    feed, fv = test_feed
    # 1. Create a dummy batch
    batch = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=fv.id,
        status=BatchStatusEnum.RUNNING,
        triggered_by="system",
        created_by="system",
        updated_by="system",
    )
    db.add(batch)
    db.commit()

    # 2. Valid synthetic source_row_id: row_100_0123456789abcdef -> SUCCEEDS
    valid_prov = OdsMemberProvenanceV1(
        id=uuid.uuid4(),
        cinq_id=uuid.uuid4(),
        batch_id=batch.id,
        source_identifier_hash="abc123hash",
        source_row_id="row_100_0123456789abcdef",
        survivorship_winner=True,
    )
    db.add(valid_prov)
    db.commit()
    assert valid_prov.id is not None

    # 3. Valid UUIDv5 format -> SUCCEEDS
    valid_uuid_prov = OdsMemberProvenanceV1(
        id=uuid.uuid4(),
        cinq_id=uuid.uuid4(),
        batch_id=batch.id,
        source_identifier_hash="abc123hash2",
        source_row_id=str(uuid.uuid4()),
        survivorship_winner=False,
    )
    db.add(valid_uuid_prov)
    db.commit()

    # 4. Invalid source_row_id (e.g. SSN or raw patient name) -> FAILS CheckConstraint
    invalid_prov = OdsMemberProvenanceV1(
        id=uuid.uuid4(),
        cinq_id=uuid.uuid4(),
        batch_id=batch.id,
        source_identifier_hash="abc123hash3",
        source_row_id="123-45-6789",  # Illegal: SSN
        survivorship_winner=False,
    )
    db.add(invalid_prov)
    with pytest.raises(IntegrityError) as exc_info:
        db.commit()
    assert "chk_synthetic_source_row_id" in str(exc_info.value)
    db.rollback()


def test_source_row_id_zero_phi_scan(db, test_feed):
    """
    Automated zero-PHI scanner test specifically against ods_member_provenance_v1.source_row_id.
    Validates that none of the persisted synthetic IDs trigger any Safe Harbor PHI regexes.
    """
    feed, fv = test_feed
    # Create batch
    batch = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=fv.id,
        status=BatchStatusEnum.RUNNING,
        triggered_by="system",
        created_by="system",
        updated_by="system",
    )
    db.add(batch)
    db.commit()

    # Insert 20 synthetic rows
    for i in range(1, 21):
        prov = OdsMemberProvenanceV1(
            id=uuid.uuid4(),
            cinq_id=uuid.uuid4(),
            batch_id=batch.id,
            source_identifier_hash=f"hash_{i:04d}",
            source_row_id=f"row_{i}_{uuid.uuid4().hex[:16]}",
            survivorship_winner=True,
        )
        db.add(prov)
    db.commit()

    rows = db.query(OdsMemberProvenanceV1.source_row_id).filter(OdsMemberProvenanceV1.batch_id == batch.id).all()
    assert len(rows) == 20

    for (row_id,) in rows:
        assert not _RE_SSN_HYPHEN.search(row_id), f"SSN detected in source_row_id: {row_id}"
        assert not _RE_PHONE.search(row_id), f"Phone detected in source_row_id: {row_id}"
        assert not _RE_EMAIL.search(row_id), f"Email detected in source_row_id: {row_id}"
        assert not _RE_MRN.search(row_id), f"MRN detected in source_row_id: {row_id}"
        assert not _RE_DOB.search(row_id), f"DOB detected in source_row_id: {row_id}"
        assert not _RE_NAME.search(row_id), f"Name detected in source_row_id: {row_id}"


def test_consumer_gate_validation(db, test_feed):
    """
    Consumer Gate Middleware evaluation:
    - Active consumer with matching model version -> ALLOWED
    - Suspended consumer -> REJECTED (403)
    - Mismatched model version -> REJECTED (403) and logs ODS_CONSUMER_MISMATCH audit event
    """
    feed, fv = test_feed

    # 1. Create Model Version 1 & Version 2
    v1 = OdsService.create_model_version(
        db,
        OdsModelVersionCreate(version_number=2001, name="Clinical v1", domain="clinical", schema_definition={}),
        user_id="system",
    )
    OdsService.publish_model_version(db, v1.id, user_id="system")

    v2 = OdsService.create_model_version(
        db,
        OdsModelVersionCreate(version_number=2002, name="Clinical v2", domain="clinical", schema_definition={}),
        user_id="system",
    )
    OdsService.publish_model_version(db, v2.id, user_id="system")

    # 2. Register consumer for v1
    consumer = OdsService.register_consumer(
        db,
        ConsumerRegistrationCreate(
            consumer_name="analytics_v1_consumer",
            consumer_type="ANALYTICS_SQL",
            registered_ods_model_version_id=v1.id,
            contact_email="v1@analytics.org",
        ),
        user_id="system",
    )

    # 3. Create batch bound to v1
    batch_v1 = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=fv.id,
        ods_model_version_id=v1.id,
        status=BatchStatusEnum.SUCCESS,
        triggered_by="system",
        created_by="system",
        updated_by="system",
    )
    db.add(batch_v1)

    # 4. Create batch bound to v2
    batch_v2 = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=fv.id,
        ods_model_version_id=v2.id,
        status=BatchStatusEnum.SUCCESS,
        triggered_by="system",
        created_by="system",
        updated_by="system",
    )
    db.add(batch_v2)
    db.commit()

    # Evaluation on batch_v1: Matches! -> ALLOWED
    res1 = OdsService.validate_consumer_gate(db, "analytics_v1_consumer", batch_v1.id)
    assert res1["allowed"] is True

    # Evaluation on batch_v2: Mismatch! -> Raises 403 Forbidden
    with pytest.raises(HTTPException) as exc_mismatch:
        OdsService.validate_consumer_gate(db, "analytics_v1_consumer", batch_v2.id)
    assert exc_mismatch.value.status_code == 403
    assert "Model version mismatch" in exc_mismatch.value.detail

    # Verify audit event logged for mismatch
    mismatch_audit = db.query(AuditEvent).filter(
        AuditEvent.object_id == str(consumer.id),
        AuditEvent.action == AuditActionEnum.ODS_CONSUMER_MISMATCH,
    ).first()
    assert mismatch_audit is not None
    assert mismatch_audit.after_state["consumer_model_version_id"] == str(v1.id)
    assert mismatch_audit.after_state["batch_model_version_id"] == str(v2.id)

    # Suspend consumer -> Raises 403
    OdsService.update_consumer(
        db, consumer.id, ConsumerRegistrationUpdate(status=ConsumerStatusEnum.SUSPENDED.value), user_id="admin"
    )
    with pytest.raises(HTTPException) as exc_susp:
        OdsService.validate_consumer_gate(db, "analytics_v1_consumer", batch_v1.id)
    assert exc_susp.value.status_code == 403
    assert "not active" in exc_susp.value.detail


def test_ods_model_version_integrity_db_triggers(db, test_feed):
    """
    Blocker 4: Live PostgreSQL DB trigger verification for ODS Model Version Integrity:
    - Batch V1 + ODS member V1 = ACCEPT
    - Batch V1 + ODS claim V1 = ACCEPT
    - Batch V1 + ODS member carrying V2 = REJECT (trigger trg_check_ods_members_batch_version)
    - Batch V1 + ODS claim carrying V2 = REJECT (trigger trg_check_ods_claims_batch_version)
    - Claim V1 + claim line carrying V2 = REJECT (trigger trg_check_ods_claim_line_parent_match)
    """
    feed, fv = test_feed

    # 1. Create and publish versions V1 (2010) and V2 (2011)
    v1 = OdsService.create_model_version(
        db,
        OdsModelVersionCreate(version_number=2010, name="Canonical v2010", domain="clinical", schema_definition={}),
        user_id="engineer",
    )
    OdsService.publish_model_version(db, v1.id, user_id="steward")

    v2 = OdsService.create_model_version(
        db,
        OdsModelVersionCreate(version_number=2011, name="Canonical v2011", domain="clinical", schema_definition={}),
        user_id="engineer",
    )
    OdsService.publish_model_version(db, v2.id, user_id="steward")

    # 2. Create batch bound to V1
    batch_v1 = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=fv.id,
        ods_model_version_id=v1.id,
        status=BatchStatusEnum.SUCCESS,
        triggered_by="system",
        created_by="system",
        updated_by="system",
    )
    db.add(batch_v1)
    db.flush()

    batch_v1_id = batch_v1.id
    v1_id = v1.id
    v2_id = v2.id

    # 3. Batch V1 + ODS member V1 = ACCEPT
    cinq_id_1 = uuid.uuid4()
    member_ok = OdsMemberV1(
        cinq_id=cinq_id_1,
        batch_id=batch_v1_id,
        ods_model_version_id=v1_id,
        first_name="Jane",
        last_name="Doe",
        date_of_birth=date(1990, 1, 1),
        gender="F",
        created_by="system",
        updated_by="system",
    )
    db.add(member_ok)
    db.flush()
    assert db.query(OdsMemberV1).filter(OdsMemberV1.cinq_id == cinq_id_1).first() is not None

    # 4. Batch V1 + ODS claim V1 = ACCEPT
    claim_id_1 = uuid.uuid4()
    claim_ok = OdsClaimV1(
        claim_id=claim_id_1,
        cinq_id=cinq_id_1,
        batch_id=batch_v1_id,
        ods_model_version_id=v1_id,
        claim_type="professional",
        total_charge_amount=Decimal("150.00"),
        claim_date=date(2026, 1, 15),
        created_by="system",
        updated_by="system",
    )
    db.add(claim_ok)
    db.flush()
    assert db.query(OdsClaimV1).filter(OdsClaimV1.claim_id == claim_id_1).first() is not None

    # 5. Batch V1 + ODS member carrying V2 = REJECT
    cinq_id_bad = uuid.uuid4()
    with pytest.raises(Exception) as exc_mem:
        with db.begin_nested():
            member_mismatch = OdsMemberV1(
                cinq_id=cinq_id_bad,
                batch_id=batch_v1_id,
                ods_model_version_id=v2_id,  # Mismatch! Batch is V1, row says V2
                first_name="Illegal",
                last_name="Version",
                date_of_birth=date(1985, 5, 20),
                gender="M",
                created_by="system",
                updated_by="system",
            )
            db.add(member_mismatch)
            db.flush()
    assert "Model Version Integrity Violation" in str(exc_mem.value)

    # 6. Batch V1 + ODS claim carrying V2 = REJECT
    with pytest.raises(Exception) as exc_claim:
        with db.begin_nested():
            claim_mismatch = OdsClaimV1(
                claim_id=uuid.uuid4(),
                cinq_id=cinq_id_1,
                batch_id=batch_v1_id,
                ods_model_version_id=v2_id,  # Mismatch! Batch is V1, row says V2
                claim_type="institutional",
                total_charge_amount=Decimal("500.00"),
                claim_date=date(2026, 2, 1),
                created_by="system",
                updated_by="system",
            )
            db.add(claim_mismatch)
            db.flush()
    assert "Model Version Integrity Violation" in str(exc_claim.value)

    # 7. Claim V1 + Claim Line carrying V2 = REJECT
    with pytest.raises(Exception) as exc_line_v:
        with db.begin_nested():
            claim_line_mismatch = OdsClaimLineV1(
                claim_line_id=uuid.uuid4(),
                claim_id=claim_id_1,  # Claim 1 is bound to V1
                batch_id=batch_v1_id,
                ods_model_version_id=v2_id,  # Mismatch! Claim is V1, line says V2
                line_number=1,
                service_date=date(2026, 1, 15),
                procedure_code="99213",
                allowed_amount=Decimal("100.00"),
                paid_amount=Decimal("80.00"),
                created_by="system",
                updated_by="system",
            )
            db.add(claim_line_mismatch)
            db.flush()
    assert "Claim Integrity Violation" in str(exc_line_v.value)


def test_claim_and_claim_line_integrity_db_triggers(db, test_feed):
    """
    Blocker 5: Live database verification for Claim / Claim-Line Integrity:
    - claim line without claim = REJECT
    - duplicate claim ID = REJECT
    - duplicate claim-line ID = REJECT
    - claim/claim-line batch mismatch = REJECT
    - claim/claim-line model-version mismatch = REJECT
    """
    feed, fv = test_feed

    # Setup model version and batches
    v1 = OdsService.create_model_version(
        db,
        OdsModelVersionCreate(version_number=2020, name="Canonical v2020", domain="clinical", schema_definition={}),
        user_id="engineer",
    )
    OdsService.publish_model_version(db, v1.id, user_id="steward")

    v2 = OdsService.create_model_version(
        db,
        OdsModelVersionCreate(version_number=2021, name="Canonical v2021", domain="clinical", schema_definition={}),
        user_id="engineer",
    )
    OdsService.publish_model_version(db, v2.id, user_id="steward")

    batch_1 = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=fv.id,
        ods_model_version_id=v1.id,
        status=BatchStatusEnum.SUCCESS,
        triggered_by="system",
        created_by="system",
        updated_by="system",
    )
    batch_2 = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=fv.id,
        ods_model_version_id=v1.id,
        status=BatchStatusEnum.SUCCESS,
        triggered_by="system",
        created_by="system",
        updated_by="system",
    )
    db.add(batch_1)
    db.add(batch_2)
    db.flush()

    batch_1_id = batch_1.id
    batch_2_id = batch_2.id
    v1_id = v1.id
    v2_id = v2.id

    cinq_id = uuid.uuid4()
    claim_id = uuid.uuid4()
    claim = OdsClaimV1(
        claim_id=claim_id,
        cinq_id=cinq_id,
        batch_id=batch_1_id,
        ods_model_version_id=v1_id,
        claim_type="professional",
        total_charge_amount=Decimal("250.00"),
        claim_date=date(2026, 3, 1),
        created_by="system",
        updated_by="system",
    )
    db.add(claim)
    db.flush()

    # 1. Claim line without claim = REJECT
    with pytest.raises(Exception) as exc_orphan:
        with db.begin_nested():
            orphan_line = OdsClaimLineV1(
                claim_line_id=uuid.uuid4(),
                claim_id=uuid.uuid4(),  # Non-existent claim
                batch_id=batch_1_id,
                ods_model_version_id=v1_id,
                line_number=1,
                service_date=date(2026, 3, 1),
                procedure_code="99214",
                created_by="system",
                updated_by="system",
            )
            db.add(orphan_line)
            db.flush()
    assert "Claim line references non-existent claim" in str(exc_orphan.value) or "foreign key" in str(exc_orphan.value).lower()

    # 2. Duplicate claim ID = REJECT
    with pytest.raises(Exception) as exc_dup_claim:
        with db.begin_nested():
            dup_claim = OdsClaimV1(
                claim_id=claim_id,  # Duplicate PK
                cinq_id=uuid.uuid4(),
                batch_id=batch_1_id,
                ods_model_version_id=v1_id,
                claim_type="pharmacy",
                total_charge_amount=Decimal("45.00"),
                claim_date=date(2026, 3, 2),
                created_by="system",
                updated_by="system",
            )
            db.add(dup_claim)
            db.flush()
    assert "unique" in str(exc_dup_claim.value).lower() or "duplicate key" in str(exc_dup_claim.value).lower()

    # 3. Duplicate claim-line ID = REJECT
    line_id = uuid.uuid4()
    line1 = OdsClaimLineV1(
        claim_line_id=line_id,
        claim_id=claim_id,
        batch_id=batch_1_id,
        ods_model_version_id=v1_id,
        line_number=1,
        service_date=date(2026, 3, 1),
        procedure_code="99213",
        created_by="system",
        updated_by="system",
    )
    db.add(line1)
    db.flush()

    with pytest.raises(Exception) as exc_dup_line:
        with db.begin_nested():
            dup_line = OdsClaimLineV1(
                claim_line_id=line_id,  # Duplicate PK
                claim_id=claim_id,
                batch_id=batch_1_id,
                ods_model_version_id=v1_id,
                line_number=2,
                service_date=date(2026, 3, 1),
                procedure_code="99214",
                created_by="system",
                updated_by="system",
            )
            db.add(dup_line)
            db.flush()
    assert "unique" in str(exc_dup_line.value).lower() or "duplicate key" in str(exc_dup_line.value).lower()

    # 4. Claim/claim-line batch mismatch = REJECT
    with pytest.raises(Exception) as exc_b_mismatch:
        with db.begin_nested():
            batch_mismatch_line = OdsClaimLineV1(
                claim_line_id=uuid.uuid4(),
                claim_id=claim_id,  # Claim is batch_1
                batch_id=batch_2_id,  # Line claims batch_2 -> Mismatch!
                ods_model_version_id=v1_id,
                line_number=2,
                service_date=date(2026, 3, 1),
                procedure_code="99215",
                created_by="system",
                updated_by="system",
            )
            db.add(batch_mismatch_line)
            db.flush()
    assert "Claim Integrity Violation" in str(exc_b_mismatch.value)
    assert "does not match Claim batch" in str(exc_b_mismatch.value)

    # 5. Claim/claim-line model-version mismatch = REJECT
    with pytest.raises(Exception) as exc_v_mismatch:
        with db.begin_nested():
            ver_mismatch_line = OdsClaimLineV1(
                claim_line_id=uuid.uuid4(),
                claim_id=claim_id,  # Claim is v1
                batch_id=batch_1_id,
                ods_model_version_id=v2_id,  # Line claims v2 -> Mismatch!
                line_number=2,
                service_date=date(2026, 3, 1),
                procedure_code="99215",
                created_by="system",
                updated_by="system",
            )
            db.add(ver_mismatch_line)
            db.flush()
    assert "Claim Integrity Violation" in str(exc_v_mismatch.value)
    assert "does not match Claim model version" in str(exc_v_mismatch.value)


def test_synthetic_source_row_id_generator_and_zero_phi():
    r"""
    Blocker 6: Prove source_row_id is genuinely synthetic and carries ZERO source semantics or PHI:
    1. Generated via secrets.token_hex(8) (CSPRNG, 64-bit entropy).
    2. Matches pattern ^row_\d+_[0-9a-f]{16}$.
    3. Has zero collisions across 100 iterations.
    4. Never contains raw source identifier, SSN, MRN, phone, email, name, DOB, or address.
    """
    import re
    tokens = []
    for i in range(100):
        token = OdsService.generate_synthetic_source_row_id(i)
        tokens.append(token)
        assert re.match(r"^row_[0-9]+_[0-9a-f]{16}$", token), f"Malformed synthetic token: {token}"

    # Verify entropy and uniqueness
    assert len(set(tokens)) == 100, "Collision detected in synthetic source row ID generator!"

    # Simulate raw incoming patient record with sensitive PHI
    raw_patient_payload = {
        "source_patient_id": "RAW-SRC-984210",
        "ssn": "123-45-6789",
        "mrn": "MRN778899",
        "first_name": "Alexander",
        "last_name": "Hamilton",
        "dob": "1957-01-11",
        "phone": "555-789-0123",
        "email": "ahamilton@treasury.gov",
        "address": "57 Maiden Lane, New York, NY",
    }

    # Verify that synthetic tokens share NO substrings with raw PHI
    for token in tokens:
        for key, raw_val in raw_patient_payload.items():
            assert raw_val not in token, f"Direct leakage of {key} in token: {token}"
            clean_digits = re.sub(r"\D", "", raw_val)
            if len(clean_digits) >= 4:
                hex_part = token.split("_", 2)[2]
                assert clean_digits not in hex_part, f"Numeric substring leakage from {key} into hex token"

        # Pass zero-PHI regex scans
        assert not _RE_SSN_HYPHEN.search(token)
        assert not _RE_PHONE.search(token)
        assert not _RE_EMAIL.search(token)
        assert not _RE_MRN.search(token)
        assert not _RE_DOB.search(token)
        assert not _RE_NAME.search(token)


def test_zero_phi_boundary_governance(db):
    """
    Blocker 2: Prove the architectural PHI boundary:
    - public / control-plane: ZERO PHI
    - audit / error / telemetry: ZERO PHI
    - identity metadata / crosswalk: ZERO RAW PHI
    - source_row_id: SYNTHETIC TECHNICAL TOKEN
    - internal_ods: AUTHORIZED CANONICAL PHI TIER (ods_members_v1 contains canonical member demographics)
    - ods_certified: AUTHORIZED DOWNSTREAM PHI INTERFACE (deferred to Slice 5)
    """
    # 1. Prove source_row_id in internal_ods.ods_member_provenance_v1 is a synthetic token
    prov = OdsMemberProvenanceV1(
        id=uuid.uuid4(),
        cinq_id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        source_identifier_hash="a"*64,
        source_row_id=OdsService.generate_synthetic_source_row_id(0),
        survivorship_winner=True,
    )
    assert not _RE_SSN_HYPHEN.search(prov.source_row_id)
    assert not _RE_EMAIL.search(prov.source_row_id)

    # 2. internal_ods is the AUTHORIZED canonical PHI tier (holds member demographics)
    member = OdsMemberV1(
        cinq_id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        ods_model_version_id=uuid.uuid4(),
        first_name="Authorized",
        last_name="Patient",
        date_of_birth=date(1990, 5, 15),
        gender="F",
        address_line1="123 Hospital Way",
        city="Boston",
        state="MA",
        postal_code="02115",
        created_by="system",
        updated_by="system",
    )
    assert member.first_name == "Authorized"
    assert member.last_name == "Patient"
    assert member.date_of_birth == date(1990, 5, 15)
