"""
Unit tests for Deterministic Identity Engine & Scoring Matrix (CF-V3-E9-01, CF-V3-E9-02)
"""
import uuid
from decimal import Decimal
import pytest
from backend.services.identity_service import (
    IdentityService,
    normalize_string,
    compute_hmac_token,
    THRESHOLD_HIGH_CONFIDENCE,
    THRESHOLD_AMBIGUOUS_MIN,
)
from backend.schemas.identity import (
    IdentityTokens,
    MatchRecordRequest,
    compute_canonical_source_hash,
)
from backend.models.identity import (
    MasterIdentity,
    IdentityToken,
    IdentityCrosswalk,
    IdentityException,
    MasterIdentityStatusEnum,
    CrosswalkMatchTypeEnum,
    IdentityExceptionStatusEnum,
)


def test_normalize_string():
    assert normalize_string("  john   doe  ") == "JOHN DOE"
    assert normalize_string("MARY-JANE") == "MARY-JANE"
    assert normalize_string("") is None
    assert normalize_string(None) is None


def test_compute_hmac_token():
    t1 = compute_hmac_token("123-45-6789", pepper="pepper1")
    t2 = compute_hmac_token("123-45-6789", pepper="pepper1")
    t3 = compute_hmac_token("123-45-6789", pepper="pepper2")
    assert t1 == t2
    assert t1 != t3
    assert len(t1) == 64
    assert compute_hmac_token(None) is None


def test_canonical_source_hashing_namespace_isolation():
    pepper = "cinqflow-test-pepper"
    # Same member ID from two different source systems MUST produce different hashes
    h1 = compute_canonical_source_hash("EPIC_HOSPITAL", "MEM001", pepper)
    h2 = compute_canonical_source_hash("CERNER_CLINIC", "MEM001", pepper)
    assert h1 != h2

    # Same member ID from two feeds sharing the SAME source system MUST produce identical hashes
    h3 = compute_canonical_source_hash("EPIC_HOSPITAL", "MEM001", pepper)
    assert h1 == h3


def test_canonical_source_hashing_contract_and_vectors():
    pepper = "TEST_PEPPER_KEY_V1"

    # Deterministic vector 1: lowercase with leading/trailing spaces normalizes identically to uppercase
    v1 = compute_canonical_source_hash("epic", " pat-00123 ", pepper)
    v2 = compute_canonical_source_hash("  EPIC  ", "PAT-00123", pepper)
    assert v1 == v2
    assert v1 == "637fa2f7b438ec099c8cd7aaac490920e5fd3b26c9c41406f9c3594a3ca63fe2"

    # Deterministic vector 2: different system produces different namespace
    v_cerner = compute_canonical_source_hash("cerner", "PAT-00123", pepper)
    assert v_cerner == "89df2afdd4827dbe54491f3c485d1cfc198fb05e7c7f5dd7786d144937e9ab91"
    assert v_cerner != v1

    # Deterministic vector 3: EPIC::123
    v_epic_123 = compute_canonical_source_hash("epic", "123", pepper)
    assert v_epic_123 == "1016057d4240e7b3407a7aaafe8a596962b547295ab1ea06e7385fcd18c424c6"

    # Deterministic vector 4: significant leading zeros MUST be preserved (00123 != 123)
    v_no_leading = compute_canonical_source_hash("epic", "PAT-123", pepper)
    assert v_no_leading == "ffd0684fad566918a9ab25e15771b68a1022e75034805caa2198db41b9478b39"
    assert v_no_leading != v1

    # Internal whitespace collapsing in system name
    v_sys_spaces = compute_canonical_source_hash("EPIC   HEALTH   SYSTEM", "ID1", pepper)
    v_sys_clean = compute_canonical_source_hash("EPIC HEALTH SYSTEM", "ID1", pepper)
    assert v_sys_spaces == v_sys_clean

    # Null / empty validation
    with pytest.raises(ValueError, match="source_system cannot be empty"):
        compute_canonical_source_hash("", "PAT-123", pepper)
    with pytest.raises(ValueError, match="source_system cannot be empty"):
        compute_canonical_source_hash("   ", "PAT-123", pepper)
    with pytest.raises(ValueError, match="raw_source_identifier cannot be empty"):
        compute_canonical_source_hash("EPIC", "", pepper)
    with pytest.raises(ValueError, match="raw_source_identifier cannot be empty"):
        compute_canonical_source_hash("EPIC", "   ", pepper)


def test_canonical_source_hashing_delimiter_ambiguity_rejection():
    pepper = "TEST_PEPPER_KEY_V1"
    # source_system containing colon must be rejected
    with pytest.raises(ValueError, match="colons are prohibited"):
        compute_canonical_source_hash("EPIC:HOSPITAL", "PAT-00123", pepper)

    with pytest.raises(ValueError, match="colons are prohibited"):
        compute_canonical_source_hash("EPIC::PRIMARY", "PAT-00123", pepper)

    # raw_source_identifier containing '::' must be rejected
    with pytest.raises(ValueError, match="cannot contain delimiter sequence '::'"):
        compute_canonical_source_hash("EPIC", "PAT::00123", pepper)


# --- SCORE BOUNDARY RED TEAM MATRIX ---

def test_scoring_matrix_0_00_no_tokens():
    tokens = IdentityTokens()
    cand = {}
    score, matched, conflicts = IdentityService.calculate_score(tokens, cand)
    assert score == Decimal("0.00")
    assert score < THRESHOLD_AMBIGUOUS_MIN


def test_scoring_matrix_exact_100_00_high_confidence():
    tokens = IdentityTokens(
        ssn_hash="h_ssn",
        dob_hash="h_dob",
        last_name_hash="h_ln",
        first_name_hash="h_fn",
        gender_hash="h_gm",
        postal_code_hash="h_zip",
    )
    cand = {
        "ssn_hash": "h_ssn",
        "dob_hash": "h_dob",
        "last_name_hash": "h_ln",
        "first_name_hash": "h_fn",
        "gender_hash": "h_gm",
        "postal_code_hash": "h_zip",
    }
    score, matched, conflicts = IdentityService.calculate_score(tokens, cand)
    assert score == Decimal("100.00")
    assert score > THRESHOLD_HIGH_CONFIDENCE
    assert len(conflicts) == 0


def test_scoring_matrix_85_01_high_confidence():
    # SSN (40) + DOB (25) + Last Name (15) + First Name (10) = 90.00 > 85.00
    tokens = IdentityTokens(
        ssn_hash="h_ssn",
        dob_hash="h_dob",
        last_name_hash="h_ln",
        first_name_hash="h_fn",
    )
    cand = {
        "ssn_hash": "h_ssn",
        "dob_hash": "h_dob",
        "last_name_hash": "h_ln",
        "first_name_hash": "h_fn",
    }
    score, matched, conflicts = IdentityService.calculate_score(tokens, cand)
    assert score == Decimal("90.00")
    assert score > THRESHOLD_HIGH_CONFIDENCE


def test_scoring_matrix_exact_85_00_ambiguous_requires_steward():
    # SSN (40) + DOB (25) + Last Name (15) + Gender (5) = 85.00
    tokens = IdentityTokens(
        ssn_hash="h_ssn",
        dob_hash="h_dob",
        last_name_hash="h_ln",
        gender_hash="h_gf",
    )
    cand = {
        "ssn_hash": "h_ssn",
        "dob_hash": "h_dob",
        "last_name_hash": "h_ln",
        "gender_hash": "h_gf",
    }
    score, matched, conflicts = IdentityService.calculate_score(tokens, cand)
    assert score == Decimal("85.00")
    assert score <= THRESHOLD_HIGH_CONFIDENCE
    assert score >= THRESHOLD_AMBIGUOUS_MIN


def test_scoring_matrix_84_99_ambiguous():
    # SSN (40) + DOB (25) + Last Name (15) + Gender (5) - First Name Conflict (-5) = 80.00
    tokens = IdentityTokens(
        ssn_hash="h_ssn",
        dob_hash="h_dob",
        last_name_hash="h_ln",
        first_name_hash="h_fn1",
        gender_hash="h_gf",
    )
    cand = {
        "ssn_hash": "h_ssn",
        "dob_hash": "h_dob",
        "last_name_hash": "h_ln",
        "first_name_hash": "h_fn2",  # conflict -5
        "gender_hash": "h_gf",
    }
    score, matched, conflicts = IdentityService.calculate_score(tokens, cand)
    assert score == Decimal("80.00")
    assert THRESHOLD_AMBIGUOUS_MIN <= score < THRESHOLD_HIGH_CONFIDENCE


def test_scoring_matrix_exact_65_00_ambiguous_minimum():
    # SSN (40) + DOB (25) = 65.00
    tokens = IdentityTokens(
        ssn_hash="h_ssn",
        dob_hash="h_dob",
    )
    cand = {
        "ssn_hash": "h_ssn",
        "dob_hash": "h_dob",
    }
    score, matched, conflicts = IdentityService.calculate_score(tokens, cand)
    assert score == Decimal("65.00")
    assert score >= THRESHOLD_AMBIGUOUS_MIN


def test_scoring_matrix_64_99_no_viable_candidate():
    # SSN (40) + Last Name (15) + First Name (10) = 65.00 - gender conflict (-10) = 55.00 < 65.00
    tokens = IdentityTokens(
        ssn_hash="h_ssn",
        last_name_hash="h_ln",
        first_name_hash="h_fn",
        gender_hash="h_gm",
    )
    cand = {
        "ssn_hash": "h_ssn",
        "last_name_hash": "h_ln",
        "first_name_hash": "h_fn",
        "gender_hash": "h_gf",  # -10 conflict
    }
    score, matched, conflicts = IdentityService.calculate_score(tokens, cand)
    assert score == Decimal("55.00")
    assert score < THRESHOLD_AMBIGUOUS_MIN


def test_scoring_missing_ssn_cannot_exceed_60_proof():
    # When SSN is missing, max possible score is DOB(25) + LN(15) + FN(10) + G(5) + Z(5) = 60.00
    # Proves mathematically that an incoming record without SSN can NEVER auto-link!
    tokens = IdentityTokens(
        dob_hash="h_dob",
        last_name_hash="h_ln",
        first_name_hash="h_fn",
        gender_hash="h_gm",
        postal_code_hash="h_zip",
    )
    cand = {
        "dob_hash": "h_dob",
        "last_name_hash": "h_ln",
        "first_name_hash": "h_fn",
        "gender_hash": "h_gm",
        "postal_code_hash": "h_zip",
    }
    score, matched, conflicts = IdentityService.calculate_score(tokens, cand)
    assert score == Decimal("60.00")
    assert score < THRESHOLD_AMBIGUOUS_MIN  # Strictly routes to NO_VIABLE_CANDIDATE exception!


def test_scoring_missing_dob_cannot_exceed_75_proof():
    # When DOB is missing, max possible score is SSN(40) + LN(15) + FN(10) + G(5) + Z(5) = 75.00
    # Proves mathematically that without DOB, record can NEVER auto-link! Always routes to steward.
    tokens = IdentityTokens(
        ssn_hash="h_ssn",
        last_name_hash="h_ln",
        first_name_hash="h_fn",
        gender_hash="h_gm",
        postal_code_hash="h_zip",
    )
    cand = {
        "ssn_hash": "h_ssn",
        "last_name_hash": "h_ln",
        "first_name_hash": "h_fn",
        "gender_hash": "h_gm",
        "postal_code_hash": "h_zip",
    }
    score, matched, conflicts = IdentityService.calculate_score(tokens, cand)
    assert score == Decimal("75.00")
    assert score <= THRESHOLD_HIGH_CONFIDENCE  # Max score without DOB is 75 <= 85


def test_scoring_ssn_match_with_dob_conflict():
    # SSN (40) + DOB Conflict (-15) + Last Name (15) = 40.00
    tokens = IdentityTokens(
        ssn_hash="h_ssn",
        dob_hash="h_dob1",
        last_name_hash="h_ln",
    )
    cand = {
        "ssn_hash": "h_ssn",
        "dob_hash": "h_dob2",  # Conflict -15
        "last_name_hash": "h_ln",
    }
    score, matched, conflicts = IdentityService.calculate_score(tokens, cand)
    assert score == Decimal("40.00")
    assert "dob_hash" in conflicts


def test_match_record_exact_active_crosswalk(db):
    master = MasterIdentity(
        status=MasterIdentityStatusEnum.ACTIVE.value,
        created_by="test_setup",
        updated_by="test_setup",
    )
    db.add(master)
    db.flush()

    cw = IdentityCrosswalk(
        cinq_id=master.cinq_id,
        source_system="SYS_A",
        source_identifier_hash="src_hash_123",
        is_active=True,
        match_score=Decimal("100.00"),
        match_type=CrosswalkMatchTypeEnum.DETERMINISTIC_HIGH_CONFIDENCE.value,
        created_by="test_setup",
        updated_by="test_setup",
    )
    db.add(cw)
    db.commit()

    req = MatchRecordRequest(
        source_system="SYS_A",
        source_identifier_hash="src_hash_123",
        tokens=IdentityTokens(),
    )
    res = IdentityService.match_record(db, req)
    assert res.disposition == "HIGH_CONFIDENCE"
    assert res.cinq_id == master.cinq_id
    assert res.match_score == Decimal("100.00")
    assert res.exception_id is None


def test_match_record_candidate_blocking_via_identity_tokens(db):
    # Setup master identity and identity tokens
    master = MasterIdentity(created_by="test", updated_by="test")
    db.add(master)
    db.flush()

    token_row = IdentityToken(
        cinq_id=master.cinq_id,
        ssn_hash="ssn_candidate_123",
        dob_hash="dob_candidate_123",
        last_name_hash="ln_candidate_123",
        first_name_hash="fn_candidate_123",
        is_current=True,
        created_by="test",
        updated_by="test",
    )
    db.add(token_row)
    db.commit()

    # Incoming record matching SSN + DOB + Name
    req = MatchRecordRequest(
        source_system="SYS_BLOCKING",
        source_identifier_hash="src_block_01",
        tokens=IdentityTokens(
            ssn_hash="ssn_candidate_123",
            dob_hash="dob_candidate_123",
            last_name_hash="ln_candidate_123",
            first_name_hash="fn_candidate_123",
        ),
    )
    res = IdentityService.match_record(db, req)
    assert res.disposition == "HIGH_CONFIDENCE"
    assert res.cinq_id == master.cinq_id
    assert res.match_score == Decimal("90.00")
    assert res.exception_id is None


def test_match_record_high_confidence_tie_forces_exception(db):
    # Setup two different master identities with identical high scores
    m1 = MasterIdentity(created_by="test", updated_by="test")
    m2 = MasterIdentity(created_by="test", updated_by="test")
    db.add_all([m1, m2])
    db.flush()

    t1 = IdentityToken(
        cinq_id=m1.cinq_id,
        ssn_hash="ssn_shared_tie",
        dob_hash="dob_shared_tie",
        last_name_hash="ln_shared_tie",
        first_name_hash="fn_shared_tie",
        is_current=True,
        created_by="test",
        updated_by="test",
    )
    t2 = IdentityToken(
        cinq_id=m2.cinq_id,
        ssn_hash="ssn_shared_tie",
        dob_hash="dob_shared_tie",
        last_name_hash="ln_shared_tie",
        first_name_hash="fn_shared_tie",
        is_current=True,
        created_by="test",
        updated_by="test",
    )
    db.add_all([t1, t2])
    db.commit()

    req = MatchRecordRequest(
        source_system="SYS_TIE",
        source_identifier_hash="src_tie_01",
        tokens=IdentityTokens(
            ssn_hash="ssn_shared_tie",
            dob_hash="dob_shared_tie",
            last_name_hash="ln_shared_tie",
            first_name_hash="fn_shared_tie",
        ),
    )
    res = IdentityService.match_record(db, req)
    assert res.disposition == "SCORE_TIE"
    assert res.cinq_id is None
    assert res.exception_id is not None

    exc = db.query(IdentityException).filter(IdentityException.id == res.exception_id).first()
    assert exc.exception_type == "SCORE_TIE"
    assert exc.status == "PENDING"
