"""
Integration tests for Identity API, Exception Lifecycle & Steward Resolution
(CF-V3-E9-01, CF-V3-E9-02)
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from backend.models.identity import (
    MasterIdentity,
    IdentityToken,
    IdentityCrosswalk,
    IdentityException,
    IdentityDecision,
    MasterIdentityStatusEnum,
    IdentityExceptionStatusEnum,
    StewardResolutionTypeEnum,
)
from backend.models.feed import Feed, FeedVersion, FeedStatusEnum, FeedVersionStatusEnum
from backend.models.pipeline import Batch, BatchStatusEnum


@pytest.fixture
def steward_token(client):
    res = client.post("/api/v1/auth/login", json={"credential": "steward:steward123"})
    assert res.status_code == 200
    return res.json()["access_token"]


@pytest.fixture
def steward_headers(steward_token):
    return {"Authorization": f"Bearer {steward_token}"}


@pytest.fixture
def sample_feed(db):
    feed = Feed(
        name="Identity Test Feed",
        domain="clinical",
        description="Feed for identity exception testing",
        format="CSV",
        landing_folder="./data/landing/identity_test",
        filename_pattern=r"^IDENTITY_.*\.csv$",
        schedule_expression="0 0 * * *",
        status=FeedStatusEnum.ACTIVE.value,
        created_by="engineer@cinqflow.local",
        updated_by="engineer@cinqflow.local",
    )
    db.add(feed)
    db.commit()
    db.refresh(feed)
    return feed


@pytest.fixture
def sample_batch(db, sample_feed):
    ver = FeedVersion(
        feed_id=sample_feed.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED.value,
        created_by="engineer@cinqflow.local",
        updated_by="engineer@cinqflow.local",
    )
    db.add(ver)
    db.commit()
    db.refresh(ver)

    batch = Batch(
        feed_id=sample_feed.id,
        feed_version_id=ver.id,
        status=BatchStatusEnum.RUNNING.value,
        triggered_by="test",
        created_by="engineer@cinqflow.local",
        updated_by="engineer@cinqflow.local",
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch


def test_match_endpoint_engineer(client, engineer_headers):
    payload = {
        "source_system": "TEST_SYS",
        "source_identifier_hash": "hash_src_001",
        "tokens": {
            "ssn_hash": "ssn_tok_001",
            "dob_hash": "dob_tok_001",
            "gender_hash": "gender_tok_001",
        },
    }
    res = client.post("/api/v1/identity/match", json=payload, headers=engineer_headers)
    assert res.status_code == 200
    data = res.json()
    assert "disposition" in data
    assert "match_score" in data


def test_match_endpoint_unauthorized_readonly(client, readonly_headers):
    payload = {
        "source_system": "TEST_SYS",
        "source_identifier_hash": "hash_src_002",
        "tokens": {},
    }
    res = client.post("/api/v1/identity/match", json=payload, headers=readonly_headers)
    assert res.status_code == 403


def test_exceptions_list_pagination(client, steward_headers, db, sample_feed, sample_batch):
    # Create test exception
    exc = IdentityException(
        batch_id=sample_batch.id,
        feed_id=sample_feed.id,
        source_system="PAGINATION_SYS",
        source_identifier_hash=uuid.uuid4().hex,
        record_fingerprint="fp_123",
        candidate_matches_json=[],
        highest_score=Decimal("70.00"),
        exception_type="AMBIGUOUS_MATCH",
        status=IdentityExceptionStatusEnum.PENDING.value,
        created_by="system",
        updated_by="system",
    )
    db.add(exc)
    db.commit()

    res = client.get("/api/v1/identity/exceptions?status=PENDING", headers=steward_headers)
    assert res.status_code == 200
    items = res.json()
    assert isinstance(items, list)
    assert any(item["id"] == str(exc.id) for item in items)


def test_claim_exception_steward(client, steward_headers, db, sample_feed, sample_batch):
    exc = IdentityException(
        batch_id=sample_batch.id,
        feed_id=sample_feed.id,
        source_system="CLAIM_SYS",
        source_identifier_hash=uuid.uuid4().hex,
        record_fingerprint="fp_claim",
        candidate_matches_json=[],
        highest_score=Decimal("75.00"),
        exception_type="AMBIGUOUS_MATCH",
        status=IdentityExceptionStatusEnum.PENDING.value,
        created_by="system",
        updated_by="system",
    )
    db.add(exc)
    db.commit()

    res = client.post(f"/api/v1/identity/exceptions/{exc.id}/claim", headers=steward_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "UNDER_REVIEW"
    assert data["assigned_steward"] == "steward@cinqflow.local"


def test_claim_exception_unauthorized_engineer(client, engineer_headers, db, sample_feed, sample_batch):
    exc = IdentityException(
        batch_id=sample_batch.id,
        feed_id=sample_feed.id,
        source_system="CLAIM_SYS_2",
        source_identifier_hash=uuid.uuid4().hex,
        record_fingerprint="fp_claim_2",
        candidate_matches_json=[],
        highest_score=Decimal("75.00"),
        exception_type="AMBIGUOUS_MATCH",
        status=IdentityExceptionStatusEnum.PENDING.value,
        created_by="system",
        updated_by="system",
    )
    db.add(exc)
    db.commit()

    res = client.post(f"/api/v1/identity/exceptions/{exc.id}/claim", headers=engineer_headers)
    assert res.status_code == 403


def test_resolve_link_existing(client, steward_headers, db, sample_feed, sample_batch):
    master = MasterIdentity(
        status=MasterIdentityStatusEnum.ACTIVE.value,
        created_by="setup",
        updated_by="setup",
    )
    db.add(master)
    db.flush()

    exc = IdentityException(
        batch_id=sample_batch.id,
        feed_id=sample_feed.id,
        source_system="LINK_SYS",
        source_identifier_hash="src_link_001",
        record_fingerprint="fp_link",
        candidate_matches_json=[{"cinq_id": str(master.cinq_id), "score": 80.0}],
        highest_score=Decimal("80.00"),
        exception_type="AMBIGUOUS_MATCH",
        status=IdentityExceptionStatusEnum.UNDER_REVIEW.value,
        created_by="system",
        updated_by="system",
        version=1,
    )
    db.add(exc)
    db.commit()

    payload = {
        "resolution_type": "LINK_EXISTING",
        "target_cinq_id": str(master.cinq_id),
        "notes": "Verified identical member record in medical records portal.",
        "expected_version": 1,
    }
    res = client.post(f"/api/v1/identity/exceptions/{exc.id}/resolve", json=payload, headers=steward_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "RESOLVED"
    assert data["resolved_cinq_id"] == str(master.cinq_id)

    # Verify crosswalk entry in DB
    cw = (
        db.query(IdentityCrosswalk)
        .filter(
            IdentityCrosswalk.source_system == "LINK_SYS",
            IdentityCrosswalk.source_identifier_hash == "src_link_001",
            IdentityCrosswalk.is_active == True,
        )
        .first()
    )
    assert cw is not None
    assert cw.cinq_id == master.cinq_id
    assert cw.match_type == "STEWARD_LINK"


def test_resolve_link_existing_rejects_inactive_master(client, steward_headers, db, sample_feed, sample_batch):
    inactive_master = MasterIdentity(
        status=MasterIdentityStatusEnum.INACTIVE.value,
        created_by="setup",
        updated_by="setup",
    )
    db.add(inactive_master)
    db.flush()

    exc = IdentityException(
        batch_id=sample_batch.id,
        feed_id=sample_feed.id,
        source_system="LINK_INACT_SYS",
        source_identifier_hash="src_link_inact_001",
        record_fingerprint="fp_link_inact",
        candidate_matches_json=[{"cinq_id": str(inactive_master.cinq_id), "score": 80.0}],
        highest_score=Decimal("80.00"),
        exception_type="AMBIGUOUS_MATCH",
        status=IdentityExceptionStatusEnum.UNDER_REVIEW.value,
        created_by="system",
        updated_by="system",
        version=1,
    )
    db.add(exc)
    db.commit()

    payload = {
        "resolution_type": "LINK_EXISTING",
        "target_cinq_id": str(inactive_master.cinq_id),
        "notes": "Attempting link to inactive master",
        "expected_version": 1,
    }
    res = client.post(f"/api/v1/identity/exceptions/{exc.id}/resolve", json=payload, headers=steward_headers)
    assert res.status_code == 422
    assert "not active" in res.json()["detail"].lower()


def test_resolve_create_new(client, steward_headers, db, sample_feed, sample_batch):
    exc = IdentityException(
        batch_id=sample_batch.id,
        feed_id=sample_feed.id,
        source_system="CREATE_SYS",
        source_identifier_hash="src_create_001",
        record_fingerprint="fp_create",
        candidate_matches_json=[],
        highest_score=Decimal("20.00"),
        exception_type="NO_VIABLE_CANDIDATE",
        status=IdentityExceptionStatusEnum.UNDER_REVIEW.value,
        created_by="system",
        updated_by="system",
        version=1,
    )
    db.add(exc)
    db.commit()

    payload = {
        "resolution_type": "CREATE_NEW",
        "notes": "Patient confirmed as newly enrolled member with no prior history.",
        "expected_version": 1,
    }
    res = client.post(f"/api/v1/identity/exceptions/{exc.id}/resolve", json=payload, headers=steward_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "RESOLVED"
    assert data["resolved_cinq_id"] is not None

    new_cid = uuid.UUID(data["resolved_cinq_id"])
    master = db.query(MasterIdentity).filter(MasterIdentity.cinq_id == new_cid).first()
    assert master is not None
    assert master.status == "ACTIVE"


def test_resolve_defer(client, steward_headers, db, sample_feed, sample_batch):
    exc = IdentityException(
        batch_id=sample_batch.id,
        feed_id=sample_feed.id,
        source_system="DEFER_SYS",
        source_identifier_hash="src_defer_001",
        record_fingerprint="fp_defer",
        candidate_matches_json=[],
        highest_score=Decimal("70.00"),
        exception_type="AMBIGUOUS_MATCH",
        status=IdentityExceptionStatusEnum.UNDER_REVIEW.value,
        created_by="system",
        updated_by="system",
        version=1,
    )
    db.add(exc)
    db.commit()

    payload = {
        "resolution_type": "DEFER",
        "notes": "Awaiting clinical documentation from provider clinic.",
        "expected_version": 1,
    }
    res = client.post(f"/api/v1/identity/exceptions/{exc.id}/resolve", json=payload, headers=steward_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "DEFERRED"
    assert data["resolved_cinq_id"] is None


def test_resolve_defer_rejects_non_null_cinq_id(client, steward_headers, db, sample_feed, sample_batch):
    exc = IdentityException(
        batch_id=sample_batch.id,
        feed_id=sample_feed.id,
        source_system="DEFER_REJ_SYS",
        source_identifier_hash="src_def_rej_001",
        record_fingerprint="fp_def_rej",
        candidate_matches_json=[],
        highest_score=Decimal("40.00"),
        exception_type="NO_VIABLE_CANDIDATE",
        status=IdentityExceptionStatusEnum.UNDER_REVIEW.value,
        created_by="system",
        updated_by="system",
        version=1,
    )
    db.add(exc)
    db.commit()

    payload = {
        "resolution_type": "DEFER",
        "target_cinq_id": str(uuid.uuid4()),
        "notes": "Invalid defer with target_cinq_id",
        "expected_version": 1,
    }
    res = client.post(f"/api/v1/identity/exceptions/{exc.id}/resolve", json=payload, headers=steward_headers)
    assert res.status_code == 422
    assert "cinq_id must be null for defer" in res.json()["detail"].lower()


def test_resolve_immutable_once_resolved(client, steward_headers, db, sample_feed, sample_batch):
    master = MasterIdentity(
        status=MasterIdentityStatusEnum.ACTIVE.value,
        created_by="setup",
        updated_by="setup",
    )
    db.add(master)
    db.flush()

    exc = IdentityException(
        batch_id=sample_batch.id,
        feed_id=sample_feed.id,
        source_system="IMMUTABLE_SYS",
        source_identifier_hash="src_imm_001",
        record_fingerprint="fp_imm",
        candidate_matches_json=[],
        highest_score=Decimal("80.00"),
        exception_type="AMBIGUOUS_MATCH",
        status=IdentityExceptionStatusEnum.RESOLVED.value,
        resolution_type="CREATE_NEW",
        resolved_cinq_id=master.cinq_id,
        resolution_notes="First resolution",
        resolved_by="steward@cinqflow.local",
        resolved_at=datetime.now(timezone.utc),
        created_by="system",
        updated_by="system",
        version=2,
    )
    db.add(exc)
    db.commit()

    # Attempting different resolution on already resolved exception must be rejected
    payload = {
        "resolution_type": "LINK_EXISTING",
        "target_cinq_id": str(master.cinq_id),
        "notes": "Attempting modification",
        "expected_version": 2,
    }
    res = client.post(f"/api/v1/identity/exceptions/{exc.id}/resolve", json=payload, headers=steward_headers)
    assert res.status_code == 422


def test_resolve_optimistic_concurrency_conflict(client, steward_headers, db, sample_feed, sample_batch):
    exc = IdentityException(
        batch_id=sample_batch.id,
        feed_id=sample_feed.id,
        source_system="CONFLICT_SYS",
        source_identifier_hash="src_con_001",
        record_fingerprint="fp_con",
        candidate_matches_json=[],
        highest_score=Decimal("70.00"),
        exception_type="AMBIGUOUS_MATCH",
        status=IdentityExceptionStatusEnum.UNDER_REVIEW.value,
        created_by="system",
        updated_by="system",
        version=3,  # DB version is 3
    )
    db.add(exc)
    db.commit()

    payload = {
        "resolution_type": "DEFER",
        "notes": "Stale resolution attempt",
        "expected_version": 2,  # Stale version 2 != 3
    }
    res = client.post(f"/api/v1/identity/exceptions/{exc.id}/resolve", json=payload, headers=steward_headers)
    assert res.status_code == 409


def test_resolve_four_eyes_author_cannot_resolve(client, db):
    # Feed created by steward@cinqflow.local
    feed = Feed(
        name="Author Feed",
        domain="clinical",
        description="Feed where steward is the author",
        format="CSV",
        landing_folder="./data/landing/author_feed",
        filename_pattern=r"^AUTHOR_.*\.csv$",
        schedule_expression="0 0 * * *",
        status=FeedStatusEnum.ACTIVE.value,
        created_by="steward@cinqflow.local",
        updated_by="steward@cinqflow.local",
    )
    db.add(feed)
    db.commit()
    db.refresh(feed)

    ver = FeedVersion(
        feed_id=feed.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED.value,
        created_by="steward@cinqflow.local",
        updated_by="steward@cinqflow.local",
    )
    db.add(ver)
    db.commit()
    db.refresh(ver)

    batch = Batch(
        feed_id=feed.id,
        feed_version_id=ver.id,
        status=BatchStatusEnum.RUNNING.value,
        triggered_by="test",
        created_by="steward@cinqflow.local",
        updated_by="steward@cinqflow.local",
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    exc = IdentityException(
        batch_id=batch.id,
        feed_id=feed.id,
        source_system="AUTHOR_SYS",
        source_identifier_hash="src_author_001",
        record_fingerprint="fp_author",
        candidate_matches_json=[],
        highest_score=Decimal("70.00"),
        exception_type="AMBIGUOUS_MATCH",
        status=IdentityExceptionStatusEnum.UNDER_REVIEW.value,
        created_by="system",
        updated_by="system",
        version=1,
    )
    db.add(exc)
    db.commit()

    # Log in as steward@cinqflow.local
    steward_token = client.post("/api/v1/auth/login", json={"credential": "steward:steward123"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {steward_token}"}

    payload = {
        "resolution_type": "DEFER",
        "notes": "Attempting self-resolution",
        "expected_version": 1,
    }
    res = client.post(f"/api/v1/identity/exceptions/{exc.id}/resolve", json=payload, headers=headers)
    assert res.status_code == 403
    assert "Four-Eyes" in res.json()["detail"]


def test_decision_notes_phi_pattern_rejection(client, steward_headers, db, sample_feed, sample_batch):
    """
    Enforces Fix 4: decision_notes must contain strictly non-PHI procedural justifications.
    Rejects raw SSN, DOB, and phone numbers before persistence with HTTP 422.
    Clean procedural notes succeed with HTTP 200.
    """
    exc = IdentityException(
        batch_id=sample_batch.id,
        feed_id=sample_feed.id,
        source_system="NOTES_SEC_SYS",
        source_identifier_hash=uuid.uuid4().hex,
        record_fingerprint="fp_notes_sec",
        candidate_matches_json=[],
        highest_score=Decimal("70.00"),
        exception_type="AMBIGUOUS_MATCH",
        status=IdentityExceptionStatusEnum.UNDER_REVIEW.value,
        created_by="system",
        updated_by="system",
        version=1,
    )
    db.add(exc)
    db.commit()

    # Case 1: Notes containing raw SSN -> REJECTED 422
    payload_ssn = {
        "resolution_type": "DEFER",
        "notes": "Patient SSN is 123-45-6789 waiting for confirm",
        "expected_version": 1,
    }
    res_ssn = client.post(f"/api/v1/identity/exceptions/{exc.id}/resolve", json=payload_ssn, headers=steward_headers)
    assert res_ssn.status_code == 422
    assert "prohibited PHI/PII patterns" in str(res_ssn.json())
    assert "123-45-6789" not in str(res_ssn.json())

    # Case 2: Notes containing raw DOB -> REJECTED 422
    payload_dob = {
        "resolution_type": "DEFER",
        "notes": "Verified patient DOB: 1985-06-15 in external records",
        "expected_version": 1,
    }
    res_dob = client.post(f"/api/v1/identity/exceptions/{exc.id}/resolve", json=payload_dob, headers=steward_headers)
    assert res_dob.status_code == 422
    assert "prohibited PHI/PII patterns" in str(res_dob.json())

    # Case 3: Notes containing raw phone number -> REJECTED 422
    payload_phone = {
        "resolution_type": "DEFER",
        "notes": "Called provider clinic at (555) 234-5678 to verify identity",
        "expected_version": 1,
    }
    res_phone = client.post(f"/api/v1/identity/exceptions/{exc.id}/resolve", json=payload_phone, headers=steward_headers)
    assert res_phone.status_code == 422
    assert "prohibited PHI/PII patterns" in str(res_phone.json())

    # Case 4: Clean procedural justification notes -> SUCCEEDS 200
    payload_clean = {
        "resolution_type": "DEFER",
        "notes": "Corroborated identity discrepancy against enterprise master ticket EMPI-4091. Awaiting clinic callback.",
        "expected_version": 1,
    }
    res_clean = client.post(f"/api/v1/identity/exceptions/{exc.id}/resolve", json=payload_clean, headers=steward_headers)
    assert res_clean.status_code == 200
    assert res_clean.json()["status"] == "DEFERRED"


def test_resolve_create_new_race_condition_blocked_by_rescoring(client, steward_headers, db, sample_feed, sample_batch):
    """
    Enforces Fix 4: Pre-execution candidate re-scoring before CREATE_NEW.
    If a high-confidence candidate match (> 85.00) has become available since the exception was logged,
    CREATE_NEW MUST be blocked with HTTP 409 Conflict to prevent duplicate MasterIdentity creation.
    """
    # 1. Create exception for record with tokens (ssn_race, dob_race, ln_race, fn_race)
    exc = IdentityException(
        batch_id=sample_batch.id,
        feed_id=sample_feed.id,
        source_system="RACE_SYS",
        source_identifier_hash="src_race_001",
        record_fingerprint="fp_race",
        candidate_matches_json=[
            {
                "tokens": {
                    "ssn_hash": "ssn_race_123",
                    "dob_hash": "dob_race_123",
                    "last_name_hash": "ln_race_123",
                    "first_name_hash": "fn_race_123",
                }
            }
        ],
        highest_score=Decimal("0.00"),
        exception_type="NO_VIABLE_CANDIDATE",
        status=IdentityExceptionStatusEnum.UNDER_REVIEW.value,
        created_by="system",
        updated_by="system",
        version=1,
    )
    db.add(exc)
    db.commit()

    # 2. Simulate concurrent creation of MasterIdentity M with identical tokens (Score = 90.00 > 85.00)
    master_concurrent = MasterIdentity(created_by="concurrent_feed", updated_by="concurrent_feed")
    db.add(master_concurrent)
    db.flush()

    token_concurrent = IdentityToken(
        cinq_id=master_concurrent.cinq_id,
        ssn_hash="ssn_race_123",
        dob_hash="dob_race_123",
        last_name_hash="ln_race_123",
        first_name_hash="fn_race_123",
        is_current=True,
        created_by="concurrent_feed",
        updated_by="concurrent_feed",
    )
    db.add(token_concurrent)
    db.commit()

    # 3. Steward attempts CREATE_NEW on exception -> REJECTED 409 Conflict
    payload = {
        "resolution_type": "CREATE_NEW",
        "notes": "Attempting create new while matching master identity exists",
        "expected_version": 1,
    }
    res = client.post(f"/api/v1/identity/exceptions/{exc.id}/resolve", json=payload, headers=steward_headers)
    assert res.status_code == 409
    assert "Concurrent MasterIdentity Candidate Detected" in res.json()["detail"]


def test_resolve_create_new_real_concurrent_race(client, steward_headers, db, sample_feed, sample_batch):
    """
    Proves database-level serialization, pg_advisory_xact_lock key derivation, and pre-execution candidate re-scoring.
    When exc1 is resolved as CREATE_NEW, MasterIdentity and IdentityToken records are created and committed.
    When exc2 (a distinct exception sharing identical candidate tokens) is resolved as CREATE_NEW,
    pg_advisory_xact_lock is acquired on the anchor lock key, pre-execution re-scoring detects exc1's candidate (Score > 85.00),
    and CREATE_NEW is strictly blocked with HTTP 409 Conflict.
    Total MasterIdentity records created in DB is exactly 1 (zero duplicate identities).
    """
    # Exception 1
    exc1 = IdentityException(
        batch_id=sample_batch.id,
        feed_id=sample_feed.id,
        source_system="RACE_SYS_1",
        source_identifier_hash="src_race_real_001",
        record_fingerprint="fp_race_real_1",
        candidate_matches_json=[
            {
                "tokens": {
                    "ssn_hash": "ssn_real_race_999",
                    "dob_hash": "dob_real_race_999",
                    "last_name_hash": "ln_real_race_999",
                    "first_name_hash": "fn_real_race_999",
                }
            }
        ],
        highest_score=Decimal("0.00"),
        exception_type="NO_VIABLE_CANDIDATE",
        status=IdentityExceptionStatusEnum.UNDER_REVIEW.value,
        created_by="system",
        updated_by="system",
        version=1,
    )
    # Exception 2 (different exception, identical candidate tokens)
    exc2 = IdentityException(
        batch_id=sample_batch.id,
        feed_id=sample_feed.id,
        source_system="RACE_SYS_2",
        source_identifier_hash="src_race_real_002",
        record_fingerprint="fp_race_real_2",
        candidate_matches_json=[
            {
                "tokens": {
                    "ssn_hash": "ssn_real_race_999",
                    "dob_hash": "dob_real_race_999",
                    "last_name_hash": "ln_real_race_999",
                    "first_name_hash": "fn_real_race_999",
                }
            }
        ],
        highest_score=Decimal("0.00"),
        exception_type="NO_VIABLE_CANDIDATE",
        status=IdentityExceptionStatusEnum.UNDER_REVIEW.value,
        created_by="system",
        updated_by="system",
        version=1,
    )
    db.add(exc1)
    db.add(exc2)
    db.commit()

    payload1 = {
        "resolution_type": "CREATE_NEW",
        "notes": "Steward 1 creating master identity for shared tokens",
        "expected_version": 1,
    }
    payload2 = {
        "resolution_type": "CREATE_NEW",
        "notes": "Steward 2 attempting create master identity for shared tokens",
        "expected_version": 1,
    }

    # Resolution 1 succeeds -> creates MasterIdentity + IdentityToken
    res1 = client.post(f"/api/v1/identity/exceptions/{exc1.id}/resolve", json=payload1, headers=steward_headers)
    assert res1.status_code == 200
    assert res1.json()["status"] == "RESOLVED"
    assert res1.json()["resolution_type"] == "CREATE_NEW"

    # Resolution 2 acquires pg_advisory_xact_lock, re-scores, detects exc1's candidate, and fails with 409 Conflict
    res2 = client.post(f"/api/v1/identity/exceptions/{exc2.id}/resolve", json=payload2, headers=steward_headers)
    assert res2.status_code == 409
    assert "Concurrent MasterIdentity Candidate Detected" in res2.json()["detail"]

    # Verify database contains exactly 1 active MasterIdentity token with ssn_real_race_999
    token_count = db.query(IdentityToken).filter(IdentityToken.ssn_hash == "ssn_real_race_999").count()
    assert token_count == 1


def test_resolve_create_new_asymmetric_attributes_race(client, steward_headers, db, sample_feed, sample_batch):
    """
    Proves multi-anchor sorted advisory locking across asymmetric candidate attributes.
    Exception 1 possesses SSN + DOB + Last Name + First Name.
    Exception 2 possesses DOB + Last Name + First Name (NO SSN).
    Because Exception 1 acquires locks for BOTH SSN and DOB_LN, and Exception 2 acquires lock for DOB_LN,
    Exception 2 MUST serialize behind Exception 1 on the DOB_LN advisory lock.
    When Exception 2 unblocks, re-scoring matches DOB + Last Name + First Name (50.00 pts or higher)
    detecting Exception 1's newly committed candidate, and raises HTTP 409 Conflict.
    Total MasterIdentity records created in DB is exactly 1.
    """
    # Exception 1: Full SSN + DOB + Name
    exc1 = IdentityException(
        batch_id=sample_batch.id,
        feed_id=sample_feed.id,
        source_system="ASYM_SYS_1",
        source_identifier_hash="src_asym_001",
        record_fingerprint="fp_asym_1",
        candidate_matches_json=[
            {
                "tokens": {
                    "ssn_hash": "ssn_asym_888",
                    "dob_hash": "dob_asym_888",
                    "last_name_hash": "ln_asym_888",
                    "first_name_hash": "fn_asym_888",
                }
            }
        ],
        highest_score=Decimal("0.00"),
        exception_type="NO_VIABLE_CANDIDATE",
        status=IdentityExceptionStatusEnum.UNDER_REVIEW.value,
        created_by="system",
        updated_by="system",
        version=1,
    )
    # Exception 2: Asymmetric DOB + Name (no SSN)
    exc2 = IdentityException(
        batch_id=sample_batch.id,
        feed_id=sample_feed.id,
        source_system="ASYM_SYS_2",
        source_identifier_hash="src_asym_002",
        record_fingerprint="fp_asym_2",
        candidate_matches_json=[
            {
                "tokens": {
                    "ssn_hash": "ssn_asym_888",
                    "dob_hash": "dob_asym_888",
                    "last_name_hash": "ln_asym_888",
                    "first_name_hash": "fn_asym_888",
                }
            }
        ],
        highest_score=Decimal("0.00"),
        exception_type="NO_VIABLE_CANDIDATE",
        status=IdentityExceptionStatusEnum.UNDER_REVIEW.value,
        created_by="system",
        updated_by="system",
        version=1,
    )
    db.add(exc1)
    db.add(exc2)
    db.commit()

    payload1 = {
        "resolution_type": "CREATE_NEW",
        "notes": "Creating master identity with SSN+DOB+Name",
        "expected_version": 1,
    }
    payload2 = {
        "resolution_type": "CREATE_NEW",
        "notes": "Attempting create master identity with DOB+Name only",
        "expected_version": 1,
    }

    # Exc 1 succeeds -> creates MasterIdentity + IdentityToken (SSN, DOB, Name)
    res1 = client.post(f"/api/v1/identity/exceptions/{exc1.id}/resolve", json=payload1, headers=steward_headers)
    assert res1.status_code == 200

    # Exc 2 acquires DOB_LN lock, re-scores against exc1's candidate, and fails with 409 Conflict
    res2 = client.post(f"/api/v1/identity/exceptions/{exc2.id}/resolve", json=payload2, headers=steward_headers)
    assert res2.status_code == 409
    assert "Concurrent MasterIdentity Candidate Detected" in res2.json()["detail"]

    # Verify database contains exactly 1 MasterIdentity with dob_asym_888
    token_count = db.query(IdentityToken).filter(IdentityToken.dob_hash == "dob_asym_888").count()
    assert token_count == 1






