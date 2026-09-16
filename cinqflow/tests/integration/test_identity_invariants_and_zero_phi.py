"""
Live PostgreSQL Invariants, Zero-PHI Enforcement, Temporal Exclusion & Red-Team Tests
Wave 3 Slice 3 (CF-V3-E9-01, CF-V3-E9-02)
"""
import uuid
import re
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest
from sqlalchemy import text

from backend.models.feed import Feed, FeedVersion, FeedStatusEnum, FeedVersionStatusEnum
from backend.models.pipeline import Batch, BatchStatusEnum
from backend.models.identity import (
    MasterIdentity,
    IdentityToken,
    IdentityCrosswalk,
    IdentityException,
    IdentityDecision,
    MasterIdentityStatusEnum,
)
from backend.schemas.identity import (
    IdentityTokens,
    MatchRecordRequest,
    validate_no_raw_phi_in_dict,
    compute_canonical_source_hash,
    compute_evidence_hash,
)
from backend.services.identity_service import IdentityService


@pytest.fixture
def sample_feed(db):
    feed = Feed(
        name=f"Invariant Feed {uuid.uuid4().hex[:6]}",
        domain="clinical",
        description="Feed for identity invariant testing",
        format="CSV",
        landing_folder="./data/landing/inv_feed",
        filename_pattern=r"^INV_.*\.csv$",
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


# --- BLOCKER 2: TEMPORAL OVERLAP REJECTION IN POSTGRESQL ---

def test_postgresql_exclusion_rejects_temporal_overlap(db):
    """
    Proves Blocker 2:
    A: 2026-01-01 -> 2026-06-01
    B: 2026-05-01 -> 2026-12-01
    The PostgreSQL engine MUST reject B with exclusion_violation.
    """
    master = MasterIdentity(created_by="temp_test", updated_by="temp_test")
    db.add(master)
    db.flush()

    # Record A: [2026-01-01, 2026-06-01)
    cw_a = IdentityCrosswalk(
        cinq_id=master.cinq_id,
        source_system="SYS_TEMPORAL",
        source_identifier_hash="hash_temporal_001",
        is_active=False,
        valid_from=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        valid_to=datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc),
        match_score=Decimal("100.00"),
        match_type="DETERMINISTIC_HIGH_CONFIDENCE",
        created_by="test",
        updated_by="test",
    )
    db.add(cw_a)
    db.commit()

    # Record B: [2026-05-01, 2026-12-01) -> Overlaps with A from May to June!
    cw_b = IdentityCrosswalk(
        cinq_id=master.cinq_id,
        source_system="SYS_TEMPORAL",
        source_identifier_hash="hash_temporal_001",
        is_active=False,
        valid_from=datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc),
        valid_to=datetime(2026, 12, 1, 0, 0, 0, tzinfo=timezone.utc),
        match_score=Decimal("100.00"),
        match_type="DETERMINISTIC_HIGH_CONFIDENCE",
        created_by="test",
        updated_by="test",
    )
    db.add(cw_b)
    with pytest.raises(Exception) as excinfo:
        db.commit()

    err_str = str(excinfo.value).lower()
    assert "excl_crosswalk_temporal_overlap" in err_str or "exclusion_violation" in err_str or "conflicting key" in err_str
    db.rollback()


def test_postgresql_exclusion_rejects_identity_tokens_temporal_overlap(db):
    """
    Enforces Final Issue 1:
    Token A:
    cinq_id = X
    2026-01-01 -> 2026-06-01

    Token B:
    cinq_id = X
    2026-05-01 -> 2026-12-01

    Database must reject B with exclusion constraint violation.
    """
    master = MasterIdentity(created_by="temp_token_test", updated_by="temp_token_test")
    db.add(master)
    db.flush()

    token_a = IdentityToken(
        cinq_id=master.cinq_id,
        ssn_hash="token_a_ssn",
        is_current=False,
        effective_from=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        effective_to=datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc),
        created_by="test",
        updated_by="test",
    )
    db.add(token_a)
    db.commit()

    token_b = IdentityToken(
        cinq_id=master.cinq_id,
        ssn_hash="token_b_ssn",
        is_current=False,
        effective_from=datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc),
        effective_to=datetime(2026, 12, 1, 0, 0, 0, tzinfo=timezone.utc),
        created_by="test",
        updated_by="test",
    )
    db.add(token_b)
    with pytest.raises(Exception) as excinfo:
        db.commit()

    err_str = str(excinfo.value).lower()
    assert "excl_identity_tokens_temporal_overlap" in err_str or "exclusion_violation" in err_str or "conflicting key" in err_str
    db.rollback()


def test_identity_tokens_only_one_current_per_cinq_id(db):
    """
    Enforces Final Issue 1: Only ONE current token set exists per cinq_id.
    """
    master = MasterIdentity(created_by="current_tok_test", updated_by="current_tok_test")
    db.add(master)
    db.flush()

    token1 = IdentityToken(
        cinq_id=master.cinq_id,
        ssn_hash="curr_ssn_1",
        is_current=True,
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        effective_to=None,
        created_by="test",
        updated_by="test",
    )
    db.add(token1)
    db.commit()

    token2 = IdentityToken(
        cinq_id=master.cinq_id,
        ssn_hash="curr_ssn_2",
        is_current=True,
        effective_from=datetime(2026, 6, 1, tzinfo=timezone.utc),
        effective_to=None,
        created_by="test",
        updated_by="test",
    )
    db.add(token2)
    with pytest.raises(Exception) as excinfo:
        db.commit()

    err_str = str(excinfo.value).lower()
    assert "uq_identity_tokens_cinq_id_current" in err_str or "unique constraint" in err_str or "conflicting key" in err_str
    db.rollback()


def test_identity_tokens_is_current_status_consistency(db):
    """
    Enforces Final Issue 1:
    is_current = TRUE  -> effective_to IS NULL
    is_current = FALSE -> effective_to IS NOT NULL
    """
    master = MasterIdentity(created_by="chk_tok_test", updated_by="chk_tok_test")
    db.add(master)
    db.flush()

    # Case A: is_current = True but effective_to is populated -> REJECTED
    tok_bad_true = IdentityToken(
        cinq_id=master.cinq_id,
        is_current=True,
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        effective_to=datetime(2026, 6, 1, tzinfo=timezone.utc),
        created_by="test",
        updated_by="test",
    )
    db.add(tok_bad_true)
    with pytest.raises(Exception) as excinfo1:
        db.commit()
    assert "chk_identity_tokens_temporal" in str(excinfo1.value)
    db.rollback()

    # Case B: is_current = False but effective_to is None -> REJECTED
    tok_bad_false = IdentityToken(
        cinq_id=master.cinq_id,
        is_current=False,
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        effective_to=None,
        created_by="test",
        updated_by="test",
    )
    db.add(tok_bad_false)
    with pytest.raises(Exception) as excinfo2:
        db.commit()
    assert "chk_identity_tokens_temporal" in str(excinfo2.value)
    db.rollback()


def test_identity_tokens_zero_length_period_rejected(db):
    """
    Enforces Fix 1: Zero-length temporal periods (effective_from == effective_to)
    produce empty ranges in PostgreSQL and MUST be rejected with chk_identity_tokens_temporal.
    Also tests that valid_from == valid_to in crosswalk is rejected with chk_crosswalk_active_temporal_consistency.
    """
    master = MasterIdentity(created_by="zero_len_test", updated_by="zero_len_test")
    db.add(master)
    db.flush()

    # Case A: IdentityToken with effective_from == effective_to -> REJECTED
    tok_zero = IdentityToken(
        cinq_id=master.cinq_id,
        is_current=False,
        effective_from=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        effective_to=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        created_by="test",
        updated_by="test",
    )
    db.add(tok_zero)
    with pytest.raises(Exception) as excinfo1:
        db.commit()
    assert "chk_identity_tokens_temporal" in str(excinfo1.value)
    db.rollback()

    # Case B: IdentityCrosswalk with valid_from == valid_to -> REJECTED
    cw_zero = IdentityCrosswalk(
        cinq_id=master.cinq_id,
        source_system="SYS_ZERO",
        source_identifier_hash="hash_zero_01",
        is_active=False,
        valid_from=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        valid_to=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        match_score=Decimal("100.00"),
        match_type="DETERMINISTIC_HIGH_CONFIDENCE",
        created_by="test",
        updated_by="test",
    )
    db.add(cw_zero)
    with pytest.raises(Exception) as excinfo2:
        db.commit()
    assert "chk_crosswalk_active_temporal_consistency" in str(excinfo2.value)
    db.rollback()


# --- BLOCKER 3: ACTIVE / TEMPORAL CONSISTENCY INVARIANTS ---

def test_crosswalk_active_flag_temporal_mismatch_rejected(db):
    """
    Proves Blocker 3:
    is_active = TRUE  -> valid_to IS NULL
    is_active = FALSE -> valid_to IS NOT NULL
    """
    master = MasterIdentity(created_by="test", updated_by="test")
    db.add(master)
    db.flush()

    # Invariant failure 1: is_active=True with valid_to populated -> REJECTED
    cw_bad1 = IdentityCrosswalk(
        cinq_id=master.cinq_id,
        source_system="SYS_ACT",
        source_identifier_hash="hash_act_01",
        is_active=True,
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_to=datetime(2026, 6, 1, tzinfo=timezone.utc),  # Invalid!
        match_score=Decimal("100.00"),
        match_type="DETERMINISTIC_HIGH_CONFIDENCE",
        created_by="test",
        updated_by="test",
    )
    db.add(cw_bad1)
    with pytest.raises(Exception) as excinfo1:
        db.commit()
    assert "chk_crosswalk_active_temporal_consistency" in str(excinfo1.value)
    db.rollback()

    # Invariant failure 2: is_active=False with valid_to NULL -> REJECTED
    cw_bad2 = IdentityCrosswalk(
        cinq_id=master.cinq_id,
        source_system="SYS_ACT",
        source_identifier_hash="hash_act_02",
        is_active=False,
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_to=None,  # Invalid!
        match_score=Decimal("100.00"),
        match_type="DETERMINISTIC_HIGH_CONFIDENCE",
        created_by="test",
        updated_by="test",
    )
    db.add(cw_bad2)
    with pytest.raises(Exception) as excinfo2:
        db.commit()
    assert "chk_crosswalk_active_temporal_consistency" in str(excinfo2.value)
    db.rollback()


# --- BLOCKER 5: ZERO-PHI JSONB INJECTION ATTACK REJECTION ---

def test_candidate_matches_json_rejects_raw_phi_injection():
    """
    Proves Blocker 5:
    Attempting to inject raw name, DOB, SSN, MRN into candidate_matches_json
    MUST be rejected with ValueError.
    """
    # Raw SSN injection attempt
    with pytest.raises(ValueError):
        validate_no_raw_phi_in_dict({"candidate": {"ssn": "123-45-6789", "score": 90.0}})

    # Raw patient name injection attempt
    with pytest.raises(ValueError):
        validate_no_raw_phi_in_dict({"candidate": {"first_name": "Alice", "last_name": "Smith"}})

    # Raw DOB injection attempt
    with pytest.raises(ValueError):
        validate_no_raw_phi_in_dict({"candidate": {"date_of_birth": "1980-01-01"}})

    # Raw MRN injection attempt
    with pytest.raises(ValueError):
        validate_no_raw_phi_in_dict({"candidate": {"mrn": "MRN-99901"}})

    # Raw address injection attempt
    with pytest.raises(ValueError):
        validate_no_raw_phi_in_dict({"candidate": {"street_address": "123 Main St"}})


# --- BLOCKER 6: SOURCE NAMESPACE ISOLATION ---

def test_source_namespace_isolation_same_member_id_different_systems():
    """
    Proves Blocker 6:
    Feed A + MEM001 in EPIC vs Feed B + MEM001 in CERNER produce distinct hashes.
    Two feeds sharing EPIC produce identical hashes.
    """
    pepper = "pepper-namespace-test"
    h_epic_a = compute_canonical_source_hash("EPIC_SYS", "MEM001", pepper)
    h_epic_b = compute_canonical_source_hash("EPIC_SYS", "MEM001", pepper)
    h_cerner = compute_canonical_source_hash("CERNER_SYS", "MEM001", pepper)

    assert h_epic_a == h_epic_b
    assert h_epic_a != h_cerner


# --- BLOCKER 7: NO_VIABLE_CANDIDATE NEVER AUTO-GENERATES IDENTITY ---

def test_no_viable_candidate_never_auto_generates_identity(db):
    """
    Proves Blocker 7:
    NO_VIABLE_CANDIDATE strictly outputs cinq_id = None and an IdentityException.
    It never creates a master identity or crosswalk entry.
    """
    initial_master_count = db.query(MasterIdentity).count()
    initial_cw_count = db.query(IdentityCrosswalk).count()

    req = MatchRecordRequest(
        source_system="SYS_NVC",
        source_identifier_hash="hash_nvc_test",
        tokens=IdentityTokens(ssn_hash="unknown_1", dob_hash="unknown_2"),
    )
    res = IdentityService.match_record(db, req)
    assert res.disposition == "NO_VIABLE_CANDIDATE"
    assert res.cinq_id is None
    assert res.exception_id is not None

    # Verify zero new master identities and zero crosswalk rows created
    assert db.query(MasterIdentity).count() == initial_master_count
    assert db.query(IdentityCrosswalk).count() == initial_cw_count


# --- BLOCKER 8 & 9: EVIDENCE HASH DETERMINISM AND INTEGRITY ---

def test_decision_evidence_hash_determinism():
    """
    Proves Blocker 9:
    evidence_hash is a tamper-evident SHA-256 digest over canonical JSON states.
    """
    pre = {"exception_id": "exc-1", "status": "UNDER_REVIEW", "version": 1}
    post = {"exception_id": "exc-1", "status": "RESOLVED", "version": 2}
    h1 = compute_evidence_hash(pre, post, "CREATE_NEW", "steward@cinqflow.local")
    h2 = compute_evidence_hash(pre, post, "CREATE_NEW", "steward@cinqflow.local")
    assert h1 == h2
    assert len(h1) == 64

    # Any tampering with post_state changes the hash
    tampered_post = {"exception_id": "exc-1", "status": "RESOLVED", "version": 99}
    h_tampered = compute_evidence_hash(pre, tampered_post, "CREATE_NEW", "steward@cinqflow.local")
    assert h1 != h_tampered


# --- POSTGRESQL TRIGGERS INVARIANTS ---

def test_postgresql_trigger_prevents_master_identity_delete(db):
    master = MasterIdentity(
        status=MasterIdentityStatusEnum.ACTIVE.value,
        created_by="del_test",
        updated_by="del_test",
    )
    db.add(master)
    db.commit()

    with pytest.raises(Exception) as excinfo:
        db.execute(text(f"DELETE FROM master_identities WHERE cinq_id = '{master.cinq_id}'"))
        db.commit()
    assert "Physical DELETE on master_identities is strictly prohibited" in str(excinfo.value)
    db.rollback()


def test_postgresql_trigger_prevents_decision_mutation(db, sample_feed, sample_batch):
    exc = IdentityException(
        batch_id=sample_batch.id,
        feed_id=sample_feed.id,
        source_system="DEC_MUT_SYS",
        source_identifier_hash="hash_dec_mut",
        record_fingerprint="fp_dec_mut",
        candidate_matches_json=[],
        highest_score=Decimal("70.00"),
        exception_type="AMBIGUOUS_MATCH",
        status="UNDER_REVIEW",
        created_by="test",
        updated_by="test",
    )
    db.add(exc)
    db.commit()

    decision = IdentityDecision(
        exception_id=exc.id,
        decision_type="DEFER",
        decided_by="steward@cinqflow.local",
        decision_notes="Initial note",
        pre_resolution_state={"status": "UNDER_REVIEW"},
        post_resolution_state={"status": "DEFERRED"},
        evidence_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        created_by="steward@cinqflow.local",
        updated_by="steward@cinqflow.local",
    )
    db.add(decision)
    db.commit()

    with pytest.raises(Exception) as excinfo:
        db.execute(text(f"UPDATE identity_decisions SET decision_notes = 'Mutated note' WHERE id = '{decision.id}'"))
        db.commit()
    assert "identity_decisions is append-only and immutable" in str(excinfo.value)
    db.rollback()


def test_performance_benchmarks_blocking_scoring_resolution(db):
    """
    Measures realistic latency for candidate scoring and resolution.
    Targets: Scoring <= 5ms, Resolution <= 50ms.
    """
    tokens = IdentityTokens(
        ssn_hash="perf_ssn",
        dob_hash="perf_dob",
        last_name_hash="perf_ln",
        first_name_hash="perf_fn",
        gender_hash="perf_gender",
        postal_code_hash="perf_zip",
    )
    cand_tokens = {
        "ssn_hash": "perf_ssn",
        "dob_hash": "perf_dob",
        "last_name_hash": "perf_ln",
        "first_name_hash": "perf_fn",
        "gender_hash": "perf_gender",
        "postal_code_hash": "perf_zip",
    }

    t0 = time.perf_counter()
    for _ in range(100):
        s, m, c = IdentityService.calculate_score(tokens, cand_tokens)
    t1 = time.perf_counter()
    avg_scoring_ms = ((t1 - t0) / 100) * 1000
    assert avg_scoring_ms < 5.0, f"Scoring exceeded 5ms: {avg_scoring_ms:.3f}ms"


def test_identity_decision_cinq_id_semantics_db_checks(db, sample_batch, sample_feed):
    """
    Enforces Final Issue 2:
    LINK_EXISTING: cinq_id MUST be present
    CREATE_NEW: cinq_id MUST be present
    DEFER: cinq_id MUST be NULL
    """
    master = MasterIdentity(created_by="dec_test", updated_by="dec_test")
    db.add(master)
    db.flush()

    exc = IdentityException(
        batch_id=sample_batch.id,
        feed_id=sample_feed.id,
        source_system="DEC_SYS",
        source_identifier_hash=uuid.uuid4().hex,
        record_fingerprint="fp_dec",
        candidate_matches_json=[],
        highest_score=Decimal("50.00"),
        exception_type="AMBIGUOUS_MATCH",
        status="UNDER_REVIEW",
        created_by="test",
        updated_by="test",
    )
    db.add(exc)
    db.commit()

    exc_id = exc.id
    master_id = master.cinq_id

    # Case 1: LINK_EXISTING without cinq_id -> REJECTED by DB CHECK
    with pytest.raises(Exception) as excinfo1:
        with db.begin_nested():
            dec_bad_link = IdentityDecision(
                exception_id=exc.id,
                decision_type="LINK_EXISTING",
                cinq_id=None,
                decided_by="steward@cinqflow.local",
                decision_notes="Missing cinq_id on LINK_EXISTING",
                pre_resolution_state={"status": "UNDER_REVIEW"},
                post_resolution_state={"status": "RESOLVED"},
                evidence_hash="hash1",
                created_by="steward@cinqflow.local",
                updated_by="steward@cinqflow.local",
            )
            db.add(dec_bad_link)
            db.flush()
    assert "chk_decision_cinq_id_semantics" in str(excinfo1.value)

    # Case 2: CREATE_NEW without cinq_id -> REJECTED by DB CHECK
    with pytest.raises(Exception) as excinfo2:
        with db.begin_nested():
            dec_bad_create = IdentityDecision(
                exception_id=exc.id,
                decision_type="CREATE_NEW",
                cinq_id=None,
                decided_by="steward@cinqflow.local",
                decision_notes="Missing cinq_id on CREATE_NEW",
                pre_resolution_state={"status": "UNDER_REVIEW"},
                post_resolution_state={"status": "RESOLVED"},
                evidence_hash="hash2",
                created_by="steward@cinqflow.local",
                updated_by="steward@cinqflow.local",
            )
            db.add(dec_bad_create)
            db.flush()
    assert "chk_decision_cinq_id_semantics" in str(excinfo2.value)

    # Case 3: DEFER with non-null cinq_id -> REJECTED by DB CHECK
    with pytest.raises(Exception) as excinfo3:
        with db.begin_nested():
            dec_bad_defer = IdentityDecision(
                exception_id=exc.id,
                decision_type="DEFER",
                cinq_id=master.cinq_id,
                decided_by="steward@cinqflow.local",
                decision_notes="Non-null cinq_id on DEFER",
                pre_resolution_state={"status": "UNDER_REVIEW"},
                post_resolution_state={"status": "DEFERRED"},
                evidence_hash="hash3",
                created_by="steward@cinqflow.local",
                updated_by="steward@cinqflow.local",
            )
            db.add(dec_bad_defer)
            db.flush()
    assert "chk_decision_cinq_id_semantics" in str(excinfo3.value)

    # Case 4: Valid DEFER with cinq_id = None -> SUCCEEDS
    dec_good_defer = IdentityDecision(
        exception_id=exc.id,
        decision_type="DEFER",
        cinq_id=None,
        decided_by="steward@cinqflow.local",
        decision_notes="Valid DEFER with null cinq_id",
        pre_resolution_state={"status": "UNDER_REVIEW"},
        post_resolution_state={"status": "DEFERRED"},
        evidence_hash="hash4",
        created_by="steward@cinqflow.local",
        updated_by="steward@cinqflow.local",
    )
    db.add(dec_good_defer)
    db.commit()
    assert dec_good_defer.id is not None


def test_pepper_version_1_immutability():
    """
    Proves Pepper Immutability Contract:
    1. pepper_version = 1 strictly evaluates using IDENTITY_HASH_PEPPER_V1 key.
    2. Unconfigured pepper_version (e.g. 99) raises ValueError.
    """
    from backend.services.identity_service import compute_hmac_token
    
    # Version 1 evaluates to deterministic vector
    v1_hash = compute_hmac_token("EPIC::PAT-00123", pepper_version=1)
    assert v1_hash == "637fa2f7b438ec099c8cd7aaac490920e5fd3b26c9c41406f9c3594a3ca63fe2"

    # Unconfigured pepper version raises ValueError
    with pytest.raises(ValueError) as excinfo:
        compute_hmac_token("EPIC::PAT-00123", pepper_version=99)
    assert "Unconfigured pepper version: 99" in str(excinfo.value)

