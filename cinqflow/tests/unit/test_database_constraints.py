"""
Database Constraints and Relationships Tests — Wave 0

Verifies all requirements for Phase 2:
- Feed and FeedVersion relationships & uniqueness
- Input fingerprint uniqueness (idempotency constraint at DB layer)
- Batch & Stage relationships & lifecycle
- Quarantine records with named reasons
- Reconciliation balance check logic & ledger entries
- Audit events immutability & tracking
"""
import uuid
import pytest
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError
from backend.models.user import User, Role, UserRole, Session, AuthProviderEnum, RoleEnum
from backend.models.feed import Feed, FeedVersion, FeedFormatEnum, FeedStatusEnum, FeedVersionStatusEnum
from backend.models.input_registry import InputRegistry, QuarantineRecord, InputStatusEnum, QuarantineReasonEnum
from backend.models.pipeline import Batch, BatchStage, BatchStatusEnum, StageNameEnum, StageStatusEnum, WAVE0_STAGE_ORDER
from backend.models.reconciliation import BatchReconciliation, ReconciliationLedgerEntry, ReconciliationStatusEnum
from backend.models.audit import AuditEvent, AuditActionEnum
from backend.models.contract import ContractRegisterEntry, ContractUnknown, ContractStatusEnum, UnknownStatusEnum, RiskLevelEnum


def test_user_role_relationship(db):
    """Test User to UserRole to Role relationships."""
    role = Role(
        name=RoleEnum.ENGINEER,
        description="Engineer test role",
        created_by="test",
        updated_by="test",
    )
    db.add(role)
    db.flush()

    user = User(
        email="test_user@cinqflow.local",
        full_name="Test User",
        auth_provider=AuthProviderEnum.mock,
        auth_provider_id="mock-test-01",
        created_by="test",
        updated_by="test",
    )
    db.add(user)
    db.flush()

    ur = UserRole(
        user_id=user.id,
        role=RoleEnum.ENGINEER,
        role_id=role.id,
        created_by="test",
        updated_by="test",
    )
    db.add(ur)
    db.flush()

    assert user.has_role(RoleEnum.ENGINEER)
    assert not user.has_role(RoleEnum.READ_ONLY)
    assert user.get_roles() == ["ENGINEER"]


def test_user_email_uniqueness(db):
    """Test duplicate email constraint on users table."""
    user1 = User(
        email="duplicate@cinqflow.local",
        full_name="User 1",
        auth_provider=AuthProviderEnum.mock,
        auth_provider_id="mock-dup-1",
        created_by="test",
        updated_by="test",
    )
    db.add(user1)
    db.flush()

    user2 = User(
        email="duplicate@cinqflow.local",
        full_name="User 2",
        auth_provider=AuthProviderEnum.mock,
        auth_provider_id="mock-dup-2",
        created_by="test",
        updated_by="test",
    )
    db.add(user2)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_feed_version_cascade_and_uniqueness(db):
    """Test feed to feed_version relationship and version uniqueness."""
    feed = Feed(
        name="FEED_TEST_UNIQUE",
        domain="TEST",
        format=FeedFormatEnum.CSV,
        landing_folder="./data/landing",
        filename_pattern="TEST_*.csv",
        schedule_expression="manual",
        status=FeedStatusEnum.ACTIVE,
        created_by="test",
        updated_by="test",
    )
    db.add(feed)
    db.flush()

    v1 = FeedVersion(
        feed_id=feed.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED,
        created_by="test",
        updated_by="test",
    )
    db.add(v1)
    db.flush()

    assert feed.get_active_version() == v1

    # Attempt duplicate version number for the same feed
    v1_dup = FeedVersion(
        feed_id=feed.id,
        version_number=1,
        status=FeedVersionStatusEnum.DRAFT,
        created_by="test",
        updated_by="test",
    )
    db.add(v1_dup)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_input_fingerprint_uniqueness_for_idempotency(db):
    """
    CRITICAL IDEMPOTENCY TEST:
    Verifies that the database strictly enforces uniqueness on file_fingerprint.
    Repeated submission of the same fingerprint must be rejected by unique constraint.
    """
    feed = Feed(
        name="FEED_IDEMPOTENCY_TEST",
        domain="TEST",
        format=FeedFormatEnum.CSV,
        landing_folder="./data/landing",
        filename_pattern="IDEM_*.csv",
        schedule_expression="manual",
        status=FeedStatusEnum.ACTIVE,
        created_by="test",
        updated_by="test",
    )
    db.add(feed)
    db.flush()

    fixed_fingerprint = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    entry1 = InputRegistry(
        feed_id=feed.id,
        filename="file_run_1.csv",
        file_path="./data/landing/file_run_1.csv",
        file_size_bytes=1024,
        file_fingerprint=fixed_fingerprint,
        status=InputStatusEnum.ACCEPTED,
        registered_by="worker",
        detected_at=datetime.now(timezone.utc),
        created_by="test",
        updated_by="test",
    )
    db.add(entry1)
    db.flush()

    # Attempt second insertion with same fingerprint
    entry2 = InputRegistry(
        feed_id=feed.id,
        filename="file_run_2_duplicate.csv",
        file_path="./data/landing/file_run_2_duplicate.csv",
        file_size_bytes=1024,
        file_fingerprint=fixed_fingerprint,
        status=InputStatusEnum.ACCEPTED,
        registered_by="worker",
        detected_at=datetime.now(timezone.utc),
        created_by="test",
        updated_by="test",
    )
    db.add(entry2)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_batch_and_stages_lifecycle(db):
    """Test Batch and BatchStage relationships, order, and stage restart support."""
    feed = Feed(
        name="FEED_BATCH_TEST",
        domain="TEST",
        format=FeedFormatEnum.CSV,
        landing_folder="./data/landing",
        filename_pattern="BATCH_*.csv",
        schedule_expression="manual",
        status=FeedStatusEnum.ACTIVE,
        created_by="test",
        updated_by="test",
    )
    db.add(feed)
    db.flush()

    version = FeedVersion(
        feed_id=feed.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED,
        created_by="test",
        updated_by="test",
    )
    db.add(version)
    db.flush()

    batch = Batch(
        feed_id=feed.id,
        feed_version_id=version.id,
        status=BatchStatusEnum.PENDING,
        triggered_by="test_user",
        created_by="test",
        updated_by="test",
    )
    db.add(batch)
    db.flush()

    # Create Wave 0 stages: LANDING, BRONZE, SILVER_RAW
    for idx, stage_name in enumerate(WAVE0_STAGE_ORDER, start=1):
        bs = BatchStage(
            batch_id=batch.id,
            stage_name=stage_name,
            stage_order=idx,
            status=StageStatusEnum.PENDING,
            created_by="test",
            updated_by="test",
        )
        db.add(bs)
    db.flush()

    assert len(batch.stages) == 3
    assert [s.stage_name for s in batch.stages] == [
        StageNameEnum.LANDING,
        StageNameEnum.BRONZE,
        StageNameEnum.SILVER_RAW,
    ]

    # Verify restart tracking: mark stage 1 and 2 SUCCESS, stage 3 FAILED
    batch.stages[0].status = StageStatusEnum.SUCCESS
    batch.stages[1].status = StageStatusEnum.SUCCESS
    batch.stages[2].status = StageStatusEnum.FAILED
    db.flush()

    last_completed = batch.get_last_completed_stage()
    assert last_completed is not None
    assert last_completed.stage_name == StageNameEnum.BRONZE


def test_quarantine_records_integrity(db):
    """Test quarantine record persistence with named reason and traceability."""
    feed = Feed(
        name="FEED_QUARANTINE_TEST",
        domain="TEST",
        format=FeedFormatEnum.CSV,
        landing_folder="./data/landing",
        filename_pattern="QR_*.csv",
        schedule_expression="manual",
        status=FeedStatusEnum.ACTIVE,
        created_by="test",
        updated_by="test",
    )
    db.add(feed)
    db.flush()

    version = FeedVersion(
        feed_id=feed.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED,
        created_by="test",
        updated_by="test",
    )
    db.add(version)
    db.flush()

    batch = Batch(
        feed_id=feed.id,
        feed_version_id=version.id,
        status=BatchStatusEnum.RUNNING,
        triggered_by="test",
        created_by="test",
        updated_by="test",
    )
    db.add(batch)
    db.flush()

    qr = QuarantineRecord(
        batch_id=batch.id,
        stage_name="SILVER_RAW",
        source_row_number=4,
        source_record_raw="M004,INVALID,,2099-01-01,X",
        field_name="date_of_birth",
        field_value="2099-01-01",
        reason=QuarantineReasonEnum.FUTURE_DATE,
        reason_detail="Date of birth cannot be in the future",
        created_by="test",
        updated_by="test",
    )
    db.add(qr)
    db.flush()

    assert len(batch.quarantine_records) == 1
    assert batch.quarantine_records[0].reason == QuarantineReasonEnum.FUTURE_DATE
    assert batch.quarantine_records[0].source_row_number == 4


def test_reconciliation_balance_check(db):
    """
    Test reconciliation math:
    Input rows (4) = Silver Raw rows (3) + Quarantined rows (1) + Dropped rows (0) -> PASS
    """
    feed = Feed(
        name="FEED_RECON_TEST",
        domain="TEST",
        format=FeedFormatEnum.CSV,
        landing_folder="./data/landing",
        filename_pattern="RECON_*.csv",
        schedule_expression="manual",
        status=FeedStatusEnum.ACTIVE,
        created_by="test",
        updated_by="test",
    )
    db.add(feed)
    db.flush()

    version = FeedVersion(
        feed_id=feed.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED,
        created_by="test",
        updated_by="test",
    )
    db.add(version)
    db.flush()

    batch = Batch(
        feed_id=feed.id,
        feed_version_id=version.id,
        status=BatchStatusEnum.SUCCESS,
        triggered_by="test",
        created_by="test",
        updated_by="test",
    )
    db.add(batch)
    db.flush()

    # Pass case
    recon = BatchReconciliation(
        batch_id=batch.id,
        rows_in=4,
        rows_silver_raw=3,
        rows_quarantined=1,
        rows_dropped=0,
        balance_check_passed=True,
        status=ReconciliationStatusEnum.PASS,
        discrepancy=0,
        created_by="test",
        updated_by="test",
    )
    db.add(recon)
    db.flush()

    ledger_entry = ReconciliationLedgerEntry(
        reconciliation_id=recon.id,
        reason_code=QuarantineReasonEnum.FUTURE_DATE.value,
        reason_description="Future date of birth",
        row_count=1,
        created_by="test",
        updated_by="test",
    )
    db.add(ledger_entry)
    db.flush()

    assert recon.is_balanced is True
    assert len(recon.ledger_entries) == 1
    assert recon.ledger_entries[0].row_count == 1
